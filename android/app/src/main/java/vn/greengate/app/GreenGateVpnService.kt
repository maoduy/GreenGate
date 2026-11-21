package vn.greengate.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.ParcelFileDescriptor
import android.util.Log
import java.io.FileInputStream
import java.io.FileOutputStream
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.nio.ByteBuffer
import java.util.concurrent.Executors
import java.util.concurrent.ScheduledExecutorService
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * The filter. A VPN that captures ONLY DNS: the tun routes a single fake address which is
 * also the DNS server handed to the system, so every app's lookups arrive here and nothing
 * else does. Blocked names answer 0.0.0.0; allowed ones are resolved upstream and relayed.
 *
 * Why DNS and not a full tunnel: no userspace TCP stack, no battery cost on the data path,
 * and the browser's own error page appears instantly for a blocked site. The price is that
 * paths and YouTube channels are invisible here (SPEC §7).
 */
class GreenGateVpnService : VpnService() {
    companion object {
        private const val TAG = "GreenGateVpn"
        const val FAKE_DNS = "10.111.222.3"
        const val TUN_ADDR = "10.111.222.1"
        const val ACTION_START = "vn.greengate.app.START"
        const val ACTION_STOP = "vn.greengate.app.STOP"
        const val ACTION_SYNC = "vn.greengate.app.SYNC"
        val UPSTREAMS = listOf("8.8.8.8", "1.1.1.1", "8.8.4.4")

        @Volatile var instance: GreenGateVpnService? = null
        @Volatile var rules: Rules = Rules.EMPTY
        @Volatile var running = false
        val queries = AtomicLong(); val blockedCount = AtomicLong()
        @Volatile var lastUpstreamMs = -1L
        // timing stats for the report: decision time (ours) and upstream round trip (the network's)
        val decideNs = AtomicLong(); val decideN = AtomicLong(); val upstreamNs = AtomicLong(); val upstreamN = AtomicLong()

        fun start(c: Context) {
            val i = Intent(c, GreenGateVpnService::class.java).setAction(ACTION_START)
            if (android.os.Build.VERSION.SDK_INT >= 26) c.startForegroundService(i) else c.startService(i)
        }
        fun stop(c: Context) { c.startService(Intent(c, GreenGateVpnService::class.java).setAction(ACTION_STOP)) }
        fun syncNow(c: Context) { if (running) c.startService(Intent(c, GreenGateVpnService::class.java).setAction(ACTION_SYNC)) }
    }

    sealed class Decision {
        object Allow : Decision()
        class Block(val reason: String) : Decision()
        class Rewrite(val target: String) : Decision()
    }

    private var tun: ParcelFileDescriptor? = null
    private var reader: Thread? = null
    private val workers = Executors.newFixedThreadPool(6)
    private lateinit var timer: ScheduledExecutorService
    lateinit var log: DnsLog
    var relay: Relay? = null
    private val fakeDns: ByteArray = InetAddress.getByName(FAKE_DNS).address

    override fun onCreate() {
        super.onCreate()
        instance = this
        log = DnsLog(this)
        timer = Executors.newSingleThreadScheduledExecutor()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> { Prefs.setEnabled(this, false); shutdown(); stopSelf(); return START_NOT_STICKY }
            ACTION_SYNC -> { timer.execute { syncOnce() }; return START_STICKY }
        }
        if (running) return START_STICKY
        startForeground(1, notification())
        rules = SheetSync.fromCache(this)
        CategoryLists.loadFromDisk(this, rules.categories)
        if (!establish()) { stopSelf(); return START_NOT_STICKY }
        running = true
        Prefs.setEnabled(this, true)
        timer.execute { syncOnce() }
        timer.scheduleWithFixedDelay({ try { log.flush() } catch (e: Exception) { Log.w(TAG, "flush: $e") } }, 5, 5, TimeUnit.SECONDS)
        timer.scheduleWithFixedDelay({ try { log.prune(rules.retentionDays) } catch (e: Exception) {} }, 1, 60, TimeUnit.MINUTES)
        timer.scheduleWithFixedDelay({ try { CategoryLists.refresh(this, rules.categories) } catch (e: Exception) {} }, 1, 60, TimeUnit.MINUTES)
        // scheduled screenshots (SPEC §8): checked every minute; Shots decides whether it is time
        timer.scheduleWithFixedDelay({ try { Shots.tick(this) } catch (e: Exception) { Log.w(TAG, "shots: $e") } }, 20, 60, TimeUnit.SECONDS)
        relay = Relay(this).also { it.start() }
        Log.i(TAG, "started; rules loaded=${rules.loaded} mode=${rules.mode}")
        return START_STICKY
    }

    private var nextSync: java.util.concurrent.ScheduledFuture<*>? = null

    /** Sheet -> rules, then reschedule itself at the sheet's own refresh interval. */
    private fun syncOnce() {
        try {
            val r = SheetSync.sync(this)
            if (r != null) {
                rules = r
                if (CategoryLists.loaded.keys != r.categories) CategoryLists.loadFromDisk(this, r.categories)
                timer.execute { CategoryLists.refresh(this, r.categories) }
                updateNotification()
            }
        } catch (e: Exception) { Log.w(TAG, "sync crashed: $e") }
        try { relay?.registerIfChanged() } catch (e: Exception) {}
        nextSync?.cancel(false)
        val delay = if (rules.loaded) rules.refreshSeconds.toLong() else 10L
        nextSync = timer.schedule({ syncOnce() }, delay, TimeUnit.SECONDS)
    }

    private fun establish(): Boolean {
        return try {
            val b = Builder().setSession("GreenGate")
                .addAddress(TUN_ADDR, 24)
                .addRoute(FAKE_DNS, 32)
                .addDnsServer(FAKE_DNS)
                .setMtu(1500)
                .setBlocking(true)
            if (android.os.Build.VERSION.SDK_INT >= 29) b.setMetered(false)
            tun = b.establish() ?: return false
            reader = Thread({ readLoop() }, "greengate-tun").also { it.isDaemon = true; it.start() }
            true
        } catch (e: Exception) { Log.e(TAG, "establish failed: $e"); false }
    }

    private fun readLoop() {
        val fd = tun ?: return
        val input = FileInputStream(fd.fileDescriptor)
        val output = FileOutputStream(fd.fileDescriptor)
        val buf = ByteArray(32767)
        while (running || tun != null) {
            val n = try { input.read(buf) } catch (e: Exception) { break }
            if (n <= 0) continue
            val pkt = buf.copyOf(n)
            workers.execute { try { handlePacket(pkt, output) } catch (e: Exception) { Log.w(TAG, "packet: $e") } }
        }
    }

    // ------------------------------------------------------------------ packets
    private fun handlePacket(p: ByteArray, out: FileOutputStream) {
        if (p.size < 28 || (p[0].toInt() shr 4) and 0xf != 4) return          // IPv4 only (the tun has no IPv6 route)
        val ihl = (p[0].toInt() and 0xf) * 4
        if (p[9].toInt() != 17) return                                          // UDP only
        val dstPort = ((p[ihl + 2].toInt() and 0xff) shl 8) or (p[ihl + 3].toInt() and 0xff)
        if (dstPort != 53) return
        val udpLen = ((p[ihl + 4].toInt() and 0xff) shl 8) or (p[ihl + 5].toInt() and 0xff)
        val dnsStart = ihl + 8
        val dnsEnd = minOf(p.size, ihl + udpLen)
        if (dnsEnd <= dnsStart) return
        val dns = p.copyOfRange(dnsStart, dnsEnd)
        val q = Dns.parseQuery(dns) ?: return
        val t0 = System.nanoTime()
        val d0 = System.nanoTime(); val decision = decide(q.name); decideNs.addAndGet(System.nanoTime() - d0); decideN.incrementAndGet()
        val answer = answerFor(q, decision)
        if (answer != null) {
            val srcIp = p.copyOfRange(12, 16); val dstIp = p.copyOfRange(16, 20)
            val srcPort = ((p[ihl].toInt() and 0xff) shl 8) or (p[ihl + 1].toInt() and 0xff)
            val reply = udpPacket(dstIp, 53, srcIp, srcPort, answer)
            synchronized(out) { out.write(reply) }
        }
        lastUpstreamMs = (System.nanoTime() - t0) / 1_000_000
    }

    private fun udpPacket(src: ByteArray, sport: Int, dst: ByteArray, dport: Int, payload: ByteArray): ByteArray {
        val total = 20 + 8 + payload.size
        val b = ByteBuffer.allocate(total)
        b.put(0x45); b.put(0); b.putShort(total.toShort()); b.putShort(0); b.putShort(0x4000); b.put(64); b.put(17); b.putShort(0)
        b.put(src); b.put(dst)
        b.putShort(sport.toShort()); b.putShort(dport.toShort()); b.putShort((8 + payload.size).toShort()); b.putShort(0)
        b.put(payload)
        val arr = b.array()
        val ipSum = checksum(arr, 0, 20, 0)
        arr[10] = (ipSum shr 8).toByte(); arr[11] = ipSum.toByte()
        // UDP checksum over pseudo header + udp
        var pseudo = 0L
        for (i in 0 until 4 step 2) pseudo += ((src[i].toInt() and 0xff) shl 8) or (src[i + 1].toInt() and 0xff)
        for (i in 0 until 4 step 2) pseudo += ((dst[i].toInt() and 0xff) shl 8) or (dst[i + 1].toInt() and 0xff)
        pseudo += 17; pseudo += 8 + payload.size
        var udpSum = checksum(arr, 20, total - 20, pseudo)
        if (udpSum == 0) udpSum = 0xffff
        arr[26] = (udpSum shr 8).toByte(); arr[27] = udpSum.toByte()
        return arr
    }

    private fun checksum(b: ByteArray, off: Int, len: Int, init: Long): Int {
        var sum = init
        var i = off
        var n = len
        while (n > 1) { sum += ((b[i].toInt() and 0xff) shl 8) or (b[i + 1].toInt() and 0xff); i += 2; n -= 2 }
        if (n == 1) sum += (b[i].toInt() and 0xff) shl 8
        while (sum shr 16 != 0L) sum = (sum and 0xffff) + (sum shr 16)
        return (sum.inv() and 0xffff).toInt()
    }

    // ------------------------------------------------------------------ decisions
    fun decide(name: String, r: Rules = rules): Decision {
        if (name.isEmpty() || '.' !in name || name.endsWith(".arpa") || name.endsWith(".local") || name.endsWith(".lan")) return Decision.Allow
        if (Prefs.pausedUntil(this) > System.currentTimeMillis()) return Decision.Allow
        val relayHost = try { java.net.URI(Prefs.relayUrl(this)).host?.lowercase() } catch (e: Exception) { null }
        if (r.inSet(Rules.HELPERS, name) || (relayHost != null && (name == relayHost || name.endsWith(".$relayHost")))) return Decision.Allow
        if (!r.loaded) return Decision.Block("chưa tải được danh sách")           // fail closed
        if (r.schedule.isNotEmpty() && !TimeWindow.allowedNow(r.schedule)) return Decision.Block("ngoài giờ cho phép")
        if (r.inSet(r.blocked, name)) return Decision.Block("danh sách chặn")
        CategoryLists.match(name, r.categories)?.let { return Decision.Block("danh mục: $it") }
        r.keywordHit(name)?.let { return Decision.Block("từ khoá: $it") }
        val isYt = r.inSet(Rules.YT_DOMAINS, name)
        if (isYt && r.youtube == "block") return Decision.Block("youtube tắt")
        if (r.mode == "whitelist" && !r.inSet(r.allowed, name)) return Decision.Block("không có trong danh sách")
        if (r.safeSearch) {
            if (isYt && r.youtube != "channels" && (name == "www.youtube.com" || name == "m.youtube.com" || name == "youtubei.googleapis.com" || name == "youtube.com"))
                return Decision.Rewrite("restrict.youtube.com")
            if (Regex("^(www\\.)?google\\.[a-z.]+$").matches(name)) return Decision.Rewrite("forcesafesearch.google.com")
            if (name == "www.bing.com" || name == "bing.com") return Decision.Rewrite("strict.bing.com")
            if (name == "duckduckgo.com" || name == "www.duckduckgo.com") return Decision.Rewrite("safe.duckduckgo.com")
        }
        return Decision.Allow
    }

    private fun answerFor(q: Dns.Query, d: Decision): ByteArray? {
        queries.incrementAndGet()
        return when (d) {
            is Decision.Block -> { blockedCount.incrementAndGet(); log.record(q.name, true, d.reason); Dns.blockedReply(q) }
            is Decision.Allow -> { if (q.type == Dns.TYPE_A || q.type == Dns.TYPE_HTTPS) log.record(q.name, false, null); upstream(q.raw) }
            is Decision.Rewrite -> {
                if (q.type == Dns.TYPE_A) log.record(q.name, false, "safesearch")
                if (q.type != Dns.TYPE_A && q.type != Dns.TYPE_AAAA) return Dns.reply(q, emptyList(), 60)   // no HTTPS/ECH records that could skip the rewrite
                val tq = buildQuery(d.target, q.type)
                val resp = upstream(tq) ?: return null
                val rd = Dns.answers(resp).filter { it.first == q.type }.map { it.second }
                Dns.reply(q, rd, 60)
            }
        }
    }

    private fun buildQuery(name: String, type: Int): ByteArray {
        val labels = name.split('.')
        val b = ByteBuffer.allocate(12 + name.length + 2 + 4)
        b.putShort((Math.random() * 65535).toInt().toShort()); b.putShort(0x0100); b.putShort(1); b.putShort(0); b.putShort(0); b.putShort(0)
        for (l in labels) { b.put(l.length.toByte()); b.put(l.toByteArray(Charsets.ISO_8859_1)) }
        b.put(0); b.putShort(type.toShort()); b.putShort(1)
        return b.array().copyOf(b.position())
    }

    /** Forward a raw query to the upstream resolvers (protected socket, so it skips the tun). */
    fun upstream(query: ByteArray): ByteArray? {
        for (server in UPSTREAMS) {
            try {
                DatagramSocket().use { s ->
                    protect(s)
                    s.soTimeout = 2500
                    val u0 = System.nanoTime()
                    s.send(DatagramPacket(query, query.size, InetSocketAddress(server, 53)))
                    val buf = ByteArray(4096)
                    val p = DatagramPacket(buf, buf.size)
                    s.receive(p)
                    upstreamNs.addAndGet(System.nanoTime() - u0); upstreamN.incrementAndGet()
                    return buf.copyOf(p.length)
                }
            } catch (e: Exception) { Log.d(TAG, "upstream $server: $e") }
        }
        return null
    }

    // ------------------------------------------------------------------ lifecycle
    private fun shutdown() {
        running = false
        relay?.stop(); relay = null
        try { tun?.close() } catch (e: Exception) {}
        tun = null
        try { log.flush() } catch (e: Exception) {}
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    override fun onRevoke() { Prefs.setEnabled(this, false); shutdown(); super.onRevoke() }

    override fun onDestroy() {
        shutdown()
        timer.shutdownNow(); workers.shutdownNow()
        instance = null
        super.onDestroy()
    }

    private fun notification(): Notification {
        val nm = getSystemService(NotificationManager::class.java)
        if (android.os.Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(NotificationChannel("greengate", getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW))
        }
        val pi = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val r = rules
        val text = if (r.loaded) "${if (r.mode == "whitelist") "Chỉ cho phép" else "Chặn danh sách"} · ${r.allowed.size} trang · ${blockedCount.get()} lần chặn" else getString(R.string.notif_text)
        return Notification.Builder(this, "greengate").setSmallIcon(R.drawable.ic_shield).setContentTitle(getString(R.string.notif_title))
            .setContentText(text).setContentIntent(pi).setOngoing(true).build()
    }

    fun updateNotification() { try { getSystemService(NotificationManager::class.java).notify(1, notification()) } catch (e: Exception) {} }

    fun statusJson(): String {
        val r = rules
        val (ok, bl) = try { log.countToday() } catch (e: Exception) { 0 to 0 }
        return org.json.JSONObject().apply {
            put("platform", "android"); put("version", BuildConfig.VERSION_NAME)
            put("mode", r.mode); put("loaded", r.loaded); put("sites", r.allowed.size); put("blockedSites", r.blocked.size)
            put("channels", r.channels); put("categories", r.categories.joinToString(",")); put("youtube", r.youtube)
            put("safesearch", r.safeSearch); put("schedule", r.raw["schedule"] ?: ""); put("scheduleOk", r.schedule.isEmpty() || TimeWindow.allowedNow(r.schedule))
            put("lastSync", Prefs.lastSync(this@GreenGateVpnService)); put("lastSyncError", Prefs.lastSyncError(this@GreenGateVpnService))
            put("queriesSinceStart", queries.get()); put("blockedSinceStart", blockedCount.get()); put("todayAllowed", ok); put("todayBlocked", bl)
            put("pausedUntil", Prefs.pausedUntil(this@GreenGateVpnService)); put("accessibility", AppBlockerService.instance != null)
            put("lists", CategoryLists.loaded.entries.joinToString(",") { "${it.key}=${it.value.size}" })
            put("avgDecideMicros", if (decideN.get() > 0) decideNs.get() / decideN.get() / 1000 else 0)
            put("avgUpstreamMs", if (upstreamN.get() > 0) upstreamNs.get() / upstreamN.get() / 1_000_000 else 0)
            put("upstreamCount", upstreamN.get())
            put("consent", org.json.JSONObject().put("parent", Prefs.consentParent(this@GreenGateVpnService)).put("child", Prefs.consentChild(this@GreenGateVpnService)))
            put("drive", Shots.statusJson(this@GreenGateVpnService))
            put("driveFolder", r.driveFolder)
        }.toString()
    }
}
