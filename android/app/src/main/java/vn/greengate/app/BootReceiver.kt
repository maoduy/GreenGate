package vn.greengate.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.VpnService

/** Bring the filter back after a reboot or an app update, without asking anyone. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        if (!Prefs.enabled(c)) return
        if (VpnService.prepare(c) != null) return      // consent lost: MainActivity will ask again
        GreenGateVpnService.start(c)
    }
}
