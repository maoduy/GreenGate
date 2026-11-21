package vn.greengate.app

import android.accessibilityservice.AccessibilityService
import android.graphics.Bitmap
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.widget.Toast
import java.io.ByteArrayOutputStream

/**
 * Two jobs, both visible to the child: send blocked apps home, and take a screenshot when a
 * parent or the schedule asks (the child sees a notification each time, see Shots). Also guards this app's own settings pages
 * so a kid cannot switch the VPN or the device admin off from Settings.
 */
class AppBlockerService : AccessibilityService() {
    companion object {
        private const val TAG = "GreenGateBlocker"
        @Volatile var instance: AppBlockerService? = null
        // Settings screens a child could use to switch us off.
        val GUARDED_CLASSES = listOf("DeviceAdminAdd", "VpnSettings", "AppVpnSettings", "InstalledAppDetails", "AppInfoDashboard",
            "AccessibilitySettings", "ToggleAccessibilityServicePreferenceFragment", "UninstallerActivity", "DeleteStagedFileOnResult")
    }

    private val main = Handler(Looper.getMainLooper())
    private var lastToast = 0L

    @Volatile private var cached: Rules? = null
    private var lastRevive = 0L

    override fun onServiceConnected() { instance = this; Log.i(TAG, "connected"); reviveVpn() }
    override fun onDestroy() { instance = null; super.onDestroy() }
    override fun onInterrupt() {}

    /**
     * Rules to enforce. Normally the VPN service's live copy; when the process was killed (an ANR,
     * low memory) Android restarts this service alone, so until the VPN is back we read the last
     * synced cache ourselves instead of running with EMPTY rules and letting every app through.
     */
    private fun currentRules(): Rules {
        val live = GreenGateVpnService.rules
        if (live.loaded) { cached = null; return live }
        return cached ?: SheetSync.fromCache(this).also { cached = it }
    }

    /** Filtering is on but the VPN service is not running (process death): bring it back, at most every 30 s. */
    private fun reviveVpn() {
        if (!Prefs.enabled(this) || GreenGateVpnService.running) return
        val now = System.currentTimeMillis()
        if (now - lastRevive < 30_000) return
        lastRevive = now
        if (android.net.VpnService.prepare(this) != null) { Log.w(TAG, "vpn down and consent missing"); return }
        Log.w(TAG, "vpn down, restarting it")
        try { GreenGateVpnService.start(this) } catch (e: Exception) { Log.w(TAG, "revive: $e") }
    }

    override fun onAccessibilityEvent(e: AccessibilityEvent) {
        if (e.eventType != AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) return
        val pkg = e.packageName?.toString()?.lowercase() ?: return
        val cls = e.className?.toString() ?: ""
        if (Prefs.pausedUntil(this) > System.currentTimeMillis()) return
        if (!Prefs.enabled(this)) return
        reviveVpn()
        val r = currentRules()
        val blockedApp = pkg in r.blockedApps
        val outsideHours = r.schedule.isNotEmpty() && !TimeWindow.allowedNow(r.schedule) && pkg != packageName && !pkg.startsWith("com.android.") && !pkg.startsWith("com.google.android.apps.nexuslauncher") && pkg != "android"
        val guarded = pkg.contains("settings") && GUARDED_CLASSES.any { cls.contains(it) } && (
            // only our own pages are guarded: the app-info page of another app is fine
            e.text.joinToString(" ").contains("GreenGate", ignoreCase = true) || cls.contains("DeviceAdminAdd") || cls.contains("VpnSettings") || cls.contains("AppVpnSettings"))
        val uninstaller = pkg == "com.google.android.packageinstaller" || pkg == "com.android.packageinstaller"
        if (blockedApp || outsideHours || guarded || (uninstaller && e.text.joinToString(" ").contains("GreenGate", ignoreCase = true))) {
            performGlobalAction(GLOBAL_ACTION_HOME)
            val now = System.currentTimeMillis()
            if (now - lastToast > 2500) {
                lastToast = now
                val msg = if (outsideHours && !blockedApp) "GreenGate: ngoài giờ cho phép" else getString(R.string.toast_blocked_app)
                main.post { Toast.makeText(this, msg, Toast.LENGTH_SHORT).show() }
            }
            Log.i(TAG, "blocked $pkg/$cls")
        }
    }

    /** JPEG, longest side 1280, quality lowered until <= maxBytes. Null when unsupported or denied. */
    fun screenshot(maxBytes: Int = 700_000, cb: (ByteArray?, String?) -> Unit) {
        if (Build.VERSION.SDK_INT < 30) { cb(null, "Android ${Build.VERSION.RELEASE}: cần Android 11 trở lên"); return }
        main.post {
            try {
                takeScreenshot(Display.DEFAULT_DISPLAY, { r -> r.run() }, object : TakeScreenshotCallback {
                    override fun onSuccess(res: ScreenshotResult) {
                        try {
                            val hw = Bitmap.wrapHardwareBuffer(res.hardwareBuffer, res.colorSpace)
                            val sw = hw?.copy(Bitmap.Config.ARGB_8888, false)
                            res.hardwareBuffer.close()
                            if (sw == null) { cb(null, "no bitmap"); return }
                            val scale = 1280f / maxOf(sw.width, sw.height)
                            val bm = if (scale < 1f) Bitmap.createScaledBitmap(sw, (sw.width * scale).toInt(), (sw.height * scale).toInt(), true) else sw
                            var q = 60
                            var out: ByteArray
                            while (true) {
                                val bos = ByteArrayOutputStream(); bm.compress(Bitmap.CompressFormat.JPEG, q, bos); out = bos.toByteArray()
                                if (out.size <= maxBytes || q <= 25) break
                                q -= 10
                            }
                            // the child is told by the caller (Shots.notifyCapture: schedule vs parent)
                            cb(out, null)
                        } catch (e: Exception) { cb(null, "encode: $e") }
                    }
                    override fun onFailure(code: Int) { cb(null, "takeScreenshot failed: code $code") }
                })
            } catch (e: Exception) { cb(null, "takeScreenshot: $e") }
        }
    }
}
