package vn.greengate.app

import android.app.admin.DevicePolicyManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.net.VpnService
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val bg = Executors.newSingleThreadExecutor()
    private val ui = Handler(Looper.getMainLooper())
    private lateinit var sheet: EditText
    private lateinit var relay: EditText
    private lateinit var msg: TextView
    private lateinit var status: TextView
    private lateinit var steps: TextView
    private lateinit var toggle: Button
    private var autoStart = false

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        setContentView(R.layout.activity_main)
        sheet = findViewById(R.id.sheet); relay = findViewById(R.id.relay); msg = findViewById(R.id.sheetMsg)
        status = findViewById(R.id.status); steps = findViewById(R.id.steps); toggle = findViewById(R.id.toggle)
        applyIntent(intent)
        sheet.setText(Prefs.sheetId(this)); relay.setText(Prefs.relayUrl(this))
        findViewById<Button>(R.id.check).setOnClickListener { check() }
        findViewById<Button>(R.id.pair).setOnClickListener { save(); startActivity(Intent(this, PairActivity::class.java)) }
        findViewById<Button>(R.id.access).setOnClickListener { startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS)) }
        findViewById<Button>(R.id.admin).setOnClickListener { requestAdmin() }
        toggle.setOnClickListener { if (GreenGateVpnService.running) { GreenGateVpnService.stop(this); refresh() } else enable() }
        val cp = findViewById<CheckBox>(R.id.consentParent); val cc = findViewById<CheckBox>(R.id.consentChild)
        cp.isChecked = Prefs.consentParent(this) > 0; cc.isChecked = Prefs.consentChild(this) > 0
        cp.setOnCheckedChangeListener { _, on -> Prefs.setConsent(this, "parent", on); refresh() }
        cc.setOnCheckedChangeListener { _, on -> Prefs.setConsent(this, "child", on); refresh() }
        if (android.os.Build.VERSION.SDK_INT >= 33 && checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED)
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 7)
        if (autoStart) enable()
        ui.postDelayed(object : Runnable { override fun run() { refresh(); ui.postDelayed(this, 2000) } }, 300)
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); applyIntent(i); sheet.setText(Prefs.sheetId(this)); relay.setText(Prefs.relayUrl(this)); if (autoStart) enable() }

    /** Test automation: adb shell am start -n vn.greengate.app/.MainActivity --es sheet <id> --es relay <url> --es sheetBase <url> --es listsBase <url> --ez start true
     *  [--ez consentParent true --ez consentChild true] [--ez shotNow true] */
    private fun applyIntent(i: Intent?) {
        i ?: return
        i.getStringExtra("sheet")?.let { Prefs.setSheetId(this, it) }
        i.getStringExtra("relay")?.let { Prefs.setRelayUrl(this, it) }
        i.getStringExtra("sheetBase")?.let { Prefs.setSheetBase(this, it) }
        i.getStringExtra("listsBase")?.let { Prefs.setListsBase(this, it) }
        autoStart = i.getBooleanExtra("start", false)
        if (i.hasExtra("consentParent")) Prefs.setConsent(this, "parent", i.getBooleanExtra("consentParent", false))
        if (i.hasExtra("consentChild")) Prefs.setConsent(this, "child", i.getBooleanExtra("consentChild", false))
        if (i.hasExtra("shotNow")) GreenGateVpnService.instance?.let { s -> Shots.capture(s, "schedule") { ok, e -> android.util.Log.i("GreenGateShots", "shotNow ok=$ok $e") } }
        if (i.getBooleanExtra("stop", false)) GreenGateVpnService.stop(this)
        if (i.getBooleanExtra("sync", false)) GreenGateVpnService.syncNow(this)
        if (i.getBooleanExtra("pair", false)) startActivity(Intent(this, PairActivity::class.java))
    }

    private fun save() {
        val sid = SheetSync.sheetId(sheet.text.toString())
        if (sid.isNotEmpty()) Prefs.setSheetId(this, sid)
        Prefs.setRelayUrl(this, relay.text.toString().trim().ifEmpty { Prefs.DEFAULT_RELAY })
    }

    private fun check() {
        save()
        msg.text = getString(R.string.checking)
        bg.execute {
            val out = StringBuilder()
            var ok = true
            for (tab in SheetSync.TABS) {
                try {
                    val csv = SheetSync.fetchTab(this, tab)
                    val n = if (csv == null) -1 else (Csv.parse(csv).count { it.isNotEmpty() && it[0].isNotBlank() } - 1).coerceAtLeast(0)
                    out.append(tab).append(": ").append(if (n < 0) "không có tab" else "$n dòng").append('\n')
                    if (tab == "websites" && n <= 0) ok = false
                } catch (e: Exception) { out.append(tab).append(": lỗi ").append(e.message).append('\n'); ok = false }
            }
            if (!ok) out.append("Hãy mở Chia sẻ trên Google Sheet và đặt 'Bất kỳ ai có đường liên kết' = Người xem.")
            ui.post { msg.text = out.toString().trim(); msg.setTextColor(if (ok) 0xFF176B3A.toInt() else 0xFFAA0000.toInt()) }
        }
    }

    private fun enable() {
        save()
        val consent = VpnService.prepare(this)
        if (consent != null) startActivityForResult(consent, 1) else onActivityResult(1, RESULT_OK, null)
    }

    @Deprecated("Deprecated in Java")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode == 1 && resultCode == RESULT_OK) { GreenGateVpnService.start(this); ui.postDelayed({ refresh() }, 800) }
    }

    private fun requestAdmin() {
        val i = Intent(DevicePolicyManager.ACTION_ADD_DEVICE_ADMIN)
            .putExtra(DevicePolicyManager.EXTRA_DEVICE_ADMIN, ComponentName(this, AdminReceiver::class.java))
            .putExtra(DevicePolicyManager.EXTRA_ADD_EXPLANATION, "Ngăn gỡ GreenGate khi chưa có phụ huynh.")
        startActivity(i)
    }

    private fun adminActive(): Boolean = (getSystemService(Context.DEVICE_POLICY_SERVICE) as DevicePolicyManager).isAdminActive(ComponentName(this, AdminReceiver::class.java))

    private fun refresh() {
        val r = GreenGateVpnService.rules
        toggle.text = getString(if (GreenGateVpnService.running) R.string.disable else R.string.enable)
        status.text = if (!GreenGateVpnService.running) getString(R.string.status_off) else buildString {
            append(if (r.loaded) "Đang bảo vệ: ${if (r.mode == "whitelist") "chỉ cho phép danh sách" else "chặn danh sách"}" else "Đang bảo vệ: chưa tải được Sheet (mọi trang bị chặn)")
            append("\n${r.allowed.size} trang web, ${r.channels} kênh YouTube, ${r.blocked.size} trang chặn, danh mục: ${r.categories.joinToString(",")}")
            if (r.schedule.isNotEmpty()) append("\nGiờ cho phép: ${r.raw["schedule"]} (${if (TimeWindow.allowedNow(r.schedule)) "đang trong giờ" else "ngoài giờ"})")
            r.scheduleError?.let { append("\nLỗi khung giờ: $it") }
            val ls = Prefs.lastSync(this@MainActivity)
            append("\nĐọc Sheet lần cuối: ").append(if (ls == 0L) "chưa" else java.text.SimpleDateFormat("HH:mm:ss").format(ls) + " (mỗi ${r.refreshSeconds}s)")
            val err = Prefs.lastSyncError(this@MainActivity); if (err.isNotEmpty()) append("\nLỗi: $err")
            append("\nTruy vấn: ${GreenGateVpnService.queries.get()}, đã chặn: ${GreenGateVpnService.blockedCount.get()}")
            val pu = Prefs.pausedUntil(this@MainActivity); if (pu > System.currentTimeMillis()) append("\n" + getString(R.string.paused_until, java.text.SimpleDateFormat("HH:mm").format(pu)))
            val every = r.screenshotEvery
            append("\nẢnh màn hình: ").append(if (every <= 0) "tắt" else "mỗi $every phút" + (r.raw["screenshothours"]?.let { " trong $it" } ?: ""))
            append(if (!Prefs.hasConsent(this@MainActivity)) " - CHƯA đủ đồng ý, không chụp theo lịch" else "")
            append(if (r.uploadUrl.isEmpty()) "\nGoogle Drive: chưa có uploadUrl trong Sheet" else "\nGoogle Drive: ${Prefs.driveUploads(this@MainActivity)} ảnh đã tải" + (Prefs.driveLastError(this@MainActivity).takeIf { it.isNotEmpty() }?.let { ", lỗi: $it" } ?: "") + (Shots.queued(this@MainActivity).takeIf { it > 0 }?.let { ", $it chờ gửi" } ?: ""))
            val rl = GreenGateVpnService.instance?.relay
            append("\nRelay: ").append(if (Prefs.deviceId(this@MainActivity).isEmpty()) "chưa ghép đôi" else (if (rl?.connected == true) "đã kết nối" else "mất kết nối (${rl?.lastEvent ?: ""})") + ", ${Prefs.parentKeys(this@MainActivity).size} phụ huynh")
        }
        val g = getString(R.string.granted); val m = getString(R.string.missing)
        steps.text = "• ${getString(R.string.step_vpn)}: ${if (VpnService.prepare(this) == null) g else m}\n" +
            "• ${getString(R.string.step_access)}: ${if (AppBlockerService.instance != null) g else m}\n" +
            "• ${getString(R.string.step_admin)}: ${if (adminActive()) g else m}"
    }
}
