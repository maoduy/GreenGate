package vn.greengate.app

import android.app.admin.DeviceAdminReceiver
import android.content.Context
import android.content.Intent

/** Active device admin = the app cannot be uninstalled until the admin is deactivated. */
class AdminReceiver : DeviceAdminReceiver() {
    override fun onEnabled(context: Context, intent: Intent) {}
    override fun onDisableRequested(context: Context, intent: Intent): CharSequence =
        "GreenGate đang bảo vệ máy này. Chỉ phụ huynh mới nên tắt."
}
