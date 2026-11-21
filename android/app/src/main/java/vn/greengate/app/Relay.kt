package vn.greengate.app

import android.util.Base64
import android.util.Log
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.zip.GZIPOutputStream

/**
 * Relay client (SPEC §5). One WebSocket to the relay while the service runs, reconnecting
 * with backoff; commands are opened with the parent's key, results sealed back to it. The
 * relay only ever sees the blobs.
 */
class Relay(private val svc: GreenGateVpnService) {
    companion object {
        private const val TAG = "GreenGateRelay"
        val JSON = "application/json; charset=utf-8".toMediaType()
        val http: OkHttpClient = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS).pingInterval(30, TimeUnit.SECONDS).build()

        /** Pairing, from the UI thread's background executor: -> (deviceId, code). */
        fun pairStart(c: android.content.Context, name: String): Pair<String, String> {
            val pub = SecurePrefs.devicePub(c) ?: throw IllegalStateException("no device key")
            val body = JSONObject().put("devicePub", pub).put("name", name).put("platform", "android").toString()
            val req = Request.Builder().url(Prefs.relayUrl(c) + "/v1/pair/start").post(body.toRequestBody(JSON)).build()
            http.newCall(req).execute().use { r ->
                if (!r.isSuccessful) throw java.io.IOException("HTTP ${r.code}: ${r.body?.string()?.take(200)}")
                val j = JSONObject(r.body!!.string())
                Prefs.setDevice(c, j.getString("deviceId"), name)
                SecurePrefs.setDeviceToken(c, j.getString("deviceToken"))
                return j.getString("deviceId") to j.getString("code")
            }
        }
    }

    private val exec = Executors.newSingleThreadScheduledExecutor()
    private var ws: WebSocket? = null
    @Volatile private var stopped = false
    private var backoff = 2L
    private val seen = java.util.LinkedHashSet<String>()
    @Volatile var connected = false
    @Volatile var lastEvent = ""

    fun start() { exec.execute { connect() } }

    fun stop() { stopped = true; try { ws?.close(1000, "bye") } catch (e: Exception) {}; exec.shutdownNow() }

    /** Called by the service after (re)pairing so the new id/token are used. */
    fun reconnect() { try { ws?.close(1000, "repair") } catch (e: Exception) {}; exec.execute { connect() } }

    private fun connect() {
        if (stopped) return
        val id = Prefs.deviceId(svc); val tok = SecurePrefs.deviceToken(svc)
        if (id.isEmpty() || tok == null) { exec.schedule({ connect() }, 30, TimeUnit.SECONDS); return }
        val url = Prefs.relayUrl(svc).replaceFirst("http", "ws") + "/v1/device/$id/ws?token=$tok"
        Log.i(TAG, "connecting $url")
        ws = http.newWebSocket(Request.Builder().url(url).build(), object : WebSocketListener() {
            override fun onOpen(w: WebSocket, response: Response) {
                connected = true; backoff = 2; lastEvent = "connected"
                w.send(JSONObject().put("t", "hello").put("platform", "android").put("version", BuildConfig.VERSION_NAME).toString())
                registerSheet(w)
            }
            override fun onMessage(w: WebSocket, text: String) { exec.execute { try { onMsg(w, JSONObject(text)) } catch (e: Exception) { Log.w(TAG, "bad message: $e") } } }
            override fun onClosed(w: WebSocket, code: Int, reason: String) { connected = false; retry("closed $code") }
            override fun onFailure(w: WebSocket, t: Throwable, r: Response?) { connected = false; retry("failure ${t.message} ${r?.code ?: ""}") }
        })
    }

    private fun retry(why: String) {
        if (stopped) return
        lastEvent = why
        Log.i(TAG, "ws $why - retry in ${backoff}s")
        exec.schedule({ pollPending(); connect() }, backoff, TimeUnit.SECONDS)
        backoff = minOf(backoff * 2, 120)
    }

    /** Fallback while the socket is down: pick up queued commands over plain HTTP. */
    private fun pollPending() {
        try {
            val id = Prefs.deviceId(svc); val tok = SecurePrefs.deviceToken(svc) ?: return
            if (id.isEmpty()) return
            val req = Request.Builder().url(Prefs.relayUrl(svc) + "/v1/device/$id/pending").header("Authorization", "Bearer $tok").build()
            http.newCall(req).execute().use { r ->
                if (!r.isSuccessful) return
                val arr = org.json.JSONArray(r.body!!.string())
                for (i in 0 until arr.length()) {
                    val c = arr.getJSONObject(i)
                    handleCommand(c.getString("cmdId"), c.getString("parentPub"), c.getString("blob")) { blob ->
                        val body = JSONObject().put("cmdId", c.getString("cmdId")).put("blob", blob).toString()
                        http.newCall(Request.Builder().url(Prefs.relayUrl(svc) + "/v1/device/$id/result").header("Authorization", "Bearer $tok").post(body.toRequestBody(JSON)).build()).execute().close()
                    }
                }
            }
        } catch (e: Exception) { Log.d(TAG, "poll: $e") }
    }

    private var registeredSheet = ""
    private var lastHintSync = 0L

    /** Plain frame telling the relay which sheet this device follows (SPEC §5 hints). */
    private fun registerSheet(w: WebSocket) {
        val sid = SheetSync.sheetId(Prefs.sheetId(svc))
        if (sid.isEmpty()) return
        registeredSheet = sid
        w.send(JSONObject().put("t", "register").put("sheet", sid).toString())
    }

    /** Called by the service after each sync: re-register when the parent changed the sheet id. */
    fun registerIfChanged() {
        val sid = SheetSync.sheetId(Prefs.sheetId(svc))
        val w = ws ?: return
        if (connected && sid.isNotEmpty() && sid != registeredSheet) registerSheet(w)
    }

    private fun onMsg(w: WebSocket, m: JSONObject) {
        when (m.optString("t")) {
            "ping" -> w.send("""{"t":"pong"}""")
            "hint" -> {
                // unencrypted nudge from the relay: "the sheet changed, re-read it now" (at most once per 10 s)
                if (m.optString("kind") != "refresh") return
                val now = System.currentTimeMillis()
                if (now - lastHintSync < 10_000) { Log.d(TAG, "hint ignored (rate limit)"); return }
                lastHintSync = now; lastEvent = "hint refresh"
                Log.i(TAG, "hint refresh ts=${m.optLong("ts")} -> sync")
                GreenGateVpnService.syncNow(svc)
            }
            "parents" -> {
                val keys = ArrayList<String>(); val arr = m.getJSONArray("keys")
                for (i in 0 until arr.length()) keys.add(arr.getString(i))
                Prefs.setParentKeys(svc, keys); lastEvent = "parents: ${keys.size}"
            }
            "cmd" -> {
                val cmdId = m.getString("cmdId")
                w.send(JSONObject().put("t", "ack").put("cmdId", cmdId).toString())
                handleCommand(cmdId, m.getString("parentPub"), m.getString("blob")) { blob ->
                    w.send(JSONObject().put("t", "result").put("cmdId", cmdId).put("blob", blob).toString())
                }
            }
        }
    }

    private fun handleCommand(cmdId: String, parentPub: String, blob: String, send: (String) -> Unit) {
        val tRecv = System.currentTimeMillis()
        val priv = SecurePrefs.devicePriv(svc) ?: return
        val env: JSONObject
        try { env = JSONObject(String(Crypto.open(blob, parentPub, priv), Charsets.UTF_8)) }
        catch (e: Exception) { Log.w(TAG, "cannot open command $cmdId: $e"); return }
        if (parentPub !in Prefs.parentKeys(svc)) Prefs.setParentKeys(svc, Prefs.parentKeys(svc) + parentPub)
        val id = env.optString("id", cmdId); val ts = env.optLong("ts", 0)
        val type = env.optString("type"); val params = env.optJSONObject("params") ?: JSONObject()
        fun reply(ok: Boolean, data: JSONObject?, error: String?) {
            val res = JSONObject().put("v", 1).put("id", id).put("ok", ok).put("ts", System.currentTimeMillis()).put("type", type)
                .put("tReceived", tRecv).put("tDone", System.currentTimeMillis())
            if (data != null) res.put("data", data); if (error != null) res.put("error", error)
            try { send(Crypto.seal(res.toString().toByteArray(Charsets.UTF_8), parentPub, priv)) } catch (e: Exception) { Log.w(TAG, "send result: $e") }
        }
        if (Math.abs(System.currentTimeMillis() - ts) > 300_000) { reply(false, null, "stale command (clock difference > 5 min)"); return }
        synchronized(seen) { if (!seen.add(id)) return; if (seen.size > 500) seen.remove(seen.first()) }
        lastEvent = "cmd $type"
        Log.i(TAG, "command $type ($id)")
        when (type) {
            "screenshot" -> {
                val svcA = AppBlockerService.instance
                if (svcA == null) { reply(false, null, "Dịch vụ trợ năng chưa bật trên máy con"); return }
                svcA.screenshot { bytes, err ->
                    if (bytes == null) { reply(false, null, err); return@screenshot }
                    Shots.notifyCapture(svc, "parent", GreenGateVpnService.rules.screenshotEvery)
                    reply(true, JSONObject().put("mime", "image/jpeg").put("b64", Base64.encodeToString(bytes, Base64.NO_WRAP)).put("bytes", bytes.size)
                        .put("drive", GreenGateVpnService.rules.uploadUrl.isNotEmpty()), null)
                    // the parents' Drive gets a copy too, so the history there is complete (SPEC §8)
                    if (GreenGateVpnService.rules.uploadUrl.isNotEmpty()) Thread({ Shots.upload(svc, bytes, "parent", java.util.Date()) }, "greengate-upload").start()
                }
            }
            "history" -> {
                val month = params.optString("month").ifEmpty { java.text.SimpleDateFormat("MM-yyyy", java.util.Locale.ROOT).format(java.util.Date()) }
                val csv = svc.log.monthCsv(month)
                val bos = ByteArrayOutputStream(); GZIPOutputStream(bos).use { it.write(csv.toByteArray(Charsets.UTF_8)) }
                reply(true, JSONObject().put("mime", "text/csv+gzip").put("month", month).put("b64", Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP)).put("rows", csv.count { it == '\n' } - 1), null)
            }
            "refresh" -> { GreenGateVpnService.syncNow(svc); reply(true, JSONObject().put("status", JSONObject(svc.statusJson())), null) }
            "status" -> reply(true, JSONObject(svc.statusJson()), null)
            "pause" -> { val min = params.optInt("minutes", 60); Prefs.setPausedUntil(svc, System.currentTimeMillis() + min * 60_000L); svc.updateNotification(); reply(true, JSONObject().put("pausedUntil", Prefs.pausedUntil(svc)), null) }
            "resume" -> { Prefs.setPausedUntil(svc, 0); svc.updateNotification(); reply(true, JSONObject().put("pausedUntil", 0), null) }
            "settings" -> {
                if (params.has("screenshotEvery")) Prefs.setOverride(svc, "screenshotevery", params.get("screenshotEvery").toString())
                if (params.has("retentionDays")) Prefs.setOverride(svc, "retentiondays", params.get("retentionDays").toString())
                GreenGateVpnService.syncNow(svc)
                reply(true, JSONObject().put("applied", params), null)
            }
            else -> reply(false, null, "unknown command: $type")
        }
    }
}
