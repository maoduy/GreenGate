package vn.greengate.app

import android.content.Context
import android.content.SharedPreferences

/** Plain settings. Secrets (device keypair, tokens) live in [SecurePrefs]. */
object Prefs {
    const val DEFAULT_SHEET = "1VtlZ1FJlUmRQ3VDx7Gzlve7LZ-oHo79P9iFbNj-9VCs"
    const val DEFAULT_RELAY = "https://relay.greengate.vn"

    private fun p(c: Context): SharedPreferences = c.getSharedPreferences("greengate", Context.MODE_PRIVATE)

    fun sheetId(c: Context): String = p(c).getString("sheetId", DEFAULT_SHEET) ?: DEFAULT_SHEET
    fun setSheetId(c: Context, v: String) = p(c).edit().putString("sheetId", v).apply()

    /** Test override: tabs are read from "<base>/<tab>.csv" instead of Google. */
    fun sheetBase(c: Context): String = p(c).getString("sheetBase", "") ?: ""
    fun setSheetBase(c: Context, v: String) = p(c).edit().putString("sheetBase", v).apply()

    /** Test override for category lists: "<base>/<category>.txt.gz". */
    fun listsBase(c: Context): String = p(c).getString("listsBase", CategoryLists.DEFAULT_BASE) ?: CategoryLists.DEFAULT_BASE
    fun setListsBase(c: Context, v: String) = p(c).edit().putString("listsBase", v).apply()

    fun relayUrl(c: Context): String = p(c).getString("relayUrl", DEFAULT_RELAY) ?: DEFAULT_RELAY
    fun setRelayUrl(c: Context, v: String) = p(c).edit().putString("relayUrl", v.trimEnd('/')).apply()

    fun enabled(c: Context): Boolean = p(c).getBoolean("enabled", false)
    fun setEnabled(c: Context, v: Boolean) = p(c).edit().putBoolean("enabled", v).apply()

    /** Parent-initiated pause (relay command). 0 = not paused. */
    fun pausedUntil(c: Context): Long = p(c).getLong("pausedUntil", 0)
    fun setPausedUntil(c: Context, v: Long) = p(c).edit().putLong("pausedUntil", v).apply()

    fun deviceId(c: Context): String = p(c).getString("deviceId", "") ?: ""
    fun deviceName(c: Context): String = p(c).getString("deviceName", android.os.Build.MODEL) ?: android.os.Build.MODEL
    fun setDevice(c: Context, id: String, name: String) = p(c).edit().putString("deviceId", id).putString("deviceName", name).apply()

    /** Parent public keys (base64), comma separated. */
    fun parentKeys(c: Context): List<String> =
        (p(c).getString("parentKeys", "") ?: "").split(",").map { it.trim() }.filter { it.isNotEmpty() }
    fun setParentKeys(c: Context, keys: List<String>) = p(c).edit().putString("parentKeys", keys.joinToString(",")).apply()

    /** Cached raw CSV of the last successful sheet read, so a reboot without network still filters. */
    fun cachedTab(c: Context, tab: String): String? = p(c).getString("tab.$tab", null)
    fun setCachedTab(c: Context, tab: String, csv: String) = p(c).edit().putString("tab.$tab", csv).apply()
    fun lastSync(c: Context): Long = p(c).getLong("lastSync", 0)
    fun setLastSync(c: Context, t: Long) = p(c).edit().putLong("lastSync", t).apply()
    fun lastSyncError(c: Context): String = p(c).getString("lastSyncError", "") ?: ""
    fun setLastSyncError(c: Context, e: String) = p(c).edit().putString("lastSyncError", e).apply()

    /** Settings the parent can push over the relay (override the sheet's values until the next sheet change). */
    fun override(c: Context, key: String): String? = p(c).getString("ov.$key", null)
    fun setOverride(c: Context, key: String, v: String?) =
        p(c).edit().apply { if (v == null) remove("ov.$key") else putString("ov.$key", v) }.apply()

    /** Consent for scheduled screenshots (SPEC §8): both a parent and the child confirm during setup. 0 = not given. */
    fun consentParent(c: Context): Long = p(c).getLong("consentParent", 0)
    fun consentChild(c: Context): Long = p(c).getLong("consentChild", 0)
    fun setConsent(c: Context, who: String, given: Boolean) =
        p(c).edit().putLong(if (who == "parent") "consentParent" else "consentChild", if (given) System.currentTimeMillis() else 0).apply()
    fun hasConsent(c: Context): Boolean = consentParent(c) > 0 && consentChild(c) > 0

    /** Drive upload bookkeeping, for the status command and the UI. */
    fun driveUploads(c: Context): Int = p(c).getInt("driveUploads", 0)
    fun driveLastUpload(c: Context): Long = p(c).getLong("driveLastUpload", 0)
    fun driveLastError(c: Context): String = p(c).getString("driveLastError", "") ?: ""
    fun noteUpload(c: Context, ok: Boolean, err: String?) = p(c).edit().apply {
        if (ok) { putInt("driveUploads", driveUploads(c) + 1); putLong("driveLastUpload", System.currentTimeMillis()); putString("driveLastError", "") }
        else putString("driveLastError", err ?: "?")
    }.apply()
    fun lastShot(c: Context): Long = p(c).getLong("lastShot", 0)
    fun setLastShot(c: Context, t: Long) = p(c).edit().putLong("lastShot", t).apply()
}
