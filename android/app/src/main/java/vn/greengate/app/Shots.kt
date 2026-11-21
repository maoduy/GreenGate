package vn.greengate.app

import android.app.KeyguardManager
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.PowerManager
import android.util.Base64
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.TimeUnit

/**
 * Scheduled screenshots to the parents' Google Drive (SPEC §8). The device never holds a
 * Google credential: it POSTs the JPEG to the Apps Script web app the parent deployed
 * (`uploadUrl` in the sheet), which runs as the parent and can only *add* files.
 *
 * Rules the child can rely on: nothing is captured without both consents, nothing while the
 * screen is off or locked, nothing outside `screenshotHours`, and every capture - scheduled
 * or requested by a parent - shows a notification that closes by itself.
 */
object Shots {
    private const val TAG = "GreenGateShots"
    private const val CHANNEL = "greengate.shots"
    private const val NOTIF_ID = 2
    private const val MAX_QUEUE = 200
    private const val MAX_IMAGE = 1_500_000
    val http: OkHttpClient = OkHttpClient.Builder().connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS).writeTimeout(30, TimeUnit.SECONDS)
        .followRedirects(true).followSslRedirects(true).build()
    private val iso = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.ROOT)
    @Volatile var lastCaptureMs = -1L       // capture + encode, for the report
    @Volatile var lastUploadMs = -1L
    @Volatile var lastBytes = -1
    @Volatile var lastSkip = ""

    fun queueDir(c: Context): File = File(c.filesDir, "shots/queue").also { it.mkdirs() }
    fun queued(c: Context): Int = queueDir(c).listFiles()?.size ?: 0

    /** Called every minute from the service timer. */
    fun tick(svc: GreenGateVpnService) {
        val r = GreenGateVpnService.rules
        if (!r.loaded || r.screenshotEvery <= 0) return
        if (!Prefs.hasConsent(svc)) { skip("no consent"); return }
        // retry anything left from earlier failures first, whatever the screen state
        flushQueue(svc)
        val now = System.currentTimeMillis()
        if (now - Prefs.lastShot(svc) < r.screenshotEvery * 60_000L - 5_000) return
        if (r.screenshotHours.isNotEmpty() && !TimeWindow.allowedNow(r.screenshotHours)) { skip("outside screenshotHours"); return }
        if (Prefs.pausedUntil(svc) > now) { skip("paused"); return }
        if (!screenUsable(svc)) { skip("screen off or locked"); return }
        Prefs.setLastShot(svc, now)
        capture(svc, "schedule") { ok, err -> if (!ok) Log.w(TAG, "scheduled capture failed: $err") }
    }

    private fun skip(why: String) { if (why != lastSkip) Log.i(TAG, "skip: $why"); lastSkip = why }

    fun screenUsable(c: Context): Boolean {
        val pm = c.getSystemService(PowerManager::class.java)
        val km = c.getSystemService(KeyguardManager::class.java)
        return pm.isInteractive && !km.isKeyguardLocked
    }

    /**
     * Take a screenshot (needs the accessibility service), notify the child, upload (or queue).
     * `reason` = "schedule" | "parent". cb(ok, error).
     */
    fun capture(c: Context, reason: String, cb: (Boolean, String?) -> Unit) {
        val svcA = AppBlockerService.instance
        if (svcA == null) { cb(false, "accessibility service not running"); return }
        val t0 = System.currentTimeMillis()
        svcA.screenshot { bytes, err ->
            lastCaptureMs = System.currentTimeMillis() - t0
            if (bytes == null) { cb(false, err); return@screenshot }
            lastBytes = bytes.size
            notifyCapture(c, reason, GreenGateVpnService.rules.screenshotEvery)
            if (GreenGateVpnService.rules.uploadUrl.isEmpty()) { cb(true, "no uploadUrl"); return@screenshot }
            Thread({
                val e = upload(c, bytes, reason, Date(t0))
                if (e != null) enqueue(c, bytes, reason, t0)
                cb(e == null, e)
            }, "greengate-upload").start()
        }
    }

    /** The auto-dismissing notice the child sees on every capture. */
    fun notifyCapture(c: Context, reason: String, every: Int) {
        try {
            val nm = c.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(NotificationChannel(CHANNEL, c.getString(R.string.shots_channel), NotificationManager.IMPORTANCE_LOW).apply {
                description = c.getString(R.string.shots_channel_desc); setShowBadge(false)
            })
            val text = if (reason == "parent") c.getString(R.string.shot_parent) else c.getString(R.string.shot_schedule, every)
            val n = Notification.Builder(c, CHANNEL).setSmallIcon(R.drawable.ic_shield)
                .setContentTitle(c.getString(R.string.app_name)).setContentText(text)
                .setStyle(Notification.BigTextStyle().bigText(text + "\n" + c.getString(R.string.shot_footer)))
                .setTimeoutAfter(8_000).setAutoCancel(true).setOnlyAlertOnce(true).build()
            nm.notify(NOTIF_ID, n)
            android.os.Handler(android.os.Looper.getMainLooper()).postDelayed({ try { nm.cancel(NOTIF_ID) } catch (e: Exception) {} }, 8_500)
        } catch (e: Exception) { Log.w(TAG, "notify: $e") }
    }

    /** POST per SPEC §8. Returns null on success, else the error text. */
    fun upload(c: Context, jpeg: ByteArray, reason: String, at: Date): String? {
        val url = GreenGateVpnService.rules.uploadUrl
        if (url.isEmpty()) return "no uploadUrl"
        if (jpeg.size > MAX_IMAGE) return "image too large (${jpeg.size})"
        val body = JSONObject().put("v", 1).put("device", Prefs.deviceName(c)).put("platform", "android")
            .put("user", android.os.Build.MODEL).put("ts", iso.format(at)).put("reason", reason)
            .put("keepDays", GreenGateVpnService.rules.retentionDays).put("mime", "image/jpeg")
            .put("image", Base64.encodeToString(jpeg, Base64.NO_WRAP)).toString()
        val t0 = System.currentTimeMillis()
        return try {
            http.newCall(Request.Builder().url(url).post(body.toRequestBody(Relay.JSON)).header("User-Agent", "greengate-android/" + BuildConfig.VERSION_NAME).build()).execute().use { r ->
                lastUploadMs = System.currentTimeMillis() - t0
                val txt = r.body?.string() ?: ""
                if (!r.isSuccessful) { Prefs.noteUpload(c, false, "HTTP ${r.code}"); return "HTTP ${r.code}: ${txt.take(120)}" }
                val j = try { JSONObject(txt) } catch (e: Exception) { null }
                if (j == null || !j.optBoolean("ok", false)) {
                    val err = j?.optString("error")?.ifEmpty { null } ?: "unexpected answer: ${txt.take(120)}"
                    Prefs.noteUpload(c, false, err); return err
                }
                Prefs.noteUpload(c, true, null)
                Log.i(TAG, "uploaded $reason ${jpeg.size} B in ${lastUploadMs}ms -> ${j.optString("path")}/${j.optString("name")}")
                null
            }
        } catch (e: Exception) { lastUploadMs = System.currentTimeMillis() - t0; Prefs.noteUpload(c, false, e.toString()); e.toString() }
    }

    private fun enqueue(c: Context, jpeg: ByteArray, reason: String, t0: Long) {
        try {
            val dir = queueDir(c)
            val files = dir.listFiles()?.sortedBy { it.name } ?: emptyList()
            for (f in files.dropLast(MAX_QUEUE - 1).takeIf { files.size >= MAX_QUEUE } ?: emptyList()) f.delete()   // oldest dropped
            File(dir, "$t0-$reason.jpg").writeBytes(jpeg)
            Log.i(TAG, "queued (${queued(c)} waiting)")
        } catch (e: Exception) { Log.w(TAG, "queue: $e") }
    }

    /** Retry queued files, oldest first; stop at the first failure (the endpoint is probably still down). */
    fun flushQueue(c: Context) {
        if (GreenGateVpnService.rules.uploadUrl.isEmpty()) return
        val files = queueDir(c).listFiles()?.sortedBy { it.name } ?: return
        for (f in files) {
            val parts = f.nameWithoutExtension.split("-")
            val t0 = parts.getOrNull(0)?.toLongOrNull() ?: f.lastModified()
            val reason = parts.getOrNull(1) ?: "schedule"
            val err = upload(c, f.readBytes(), reason, Date(t0))
            if (err != null) { Log.i(TAG, "queue retry failed: $err"); return }
            f.delete()
        }
    }

    fun statusJson(c: Context): JSONObject = JSONObject()
        .put("uploads", Prefs.driveUploads(c)).put("lastUpload", Prefs.driveLastUpload(c))
        .put("lastError", Prefs.driveLastError(c)).put("queued", queued(c))
        .put("uploadUrl", GreenGateVpnService.rules.uploadUrl.isNotEmpty()).put("every", GreenGateVpnService.rules.screenshotEvery)
        .put("hours", GreenGateVpnService.rules.raw["screenshothours"] ?: "")
        .put("lastCaptureMs", lastCaptureMs).put("lastUploadMs", lastUploadMs).put("lastBytes", lastBytes)
}
