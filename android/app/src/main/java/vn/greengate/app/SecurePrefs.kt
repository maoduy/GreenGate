package vn.greengate.app

import android.content.Context
import android.content.SharedPreferences
import androidx.security.crypto.EncryptedSharedPreferences
import androidx.security.crypto.MasterKey

/** Device keypair and relay tokens, encrypted with a Keystore-backed master key. */
object SecurePrefs {
    private var cached: SharedPreferences? = null

    @Synchronized
    private fun p(c: Context): SharedPreferences {
        cached?.let { return it }
        val sp = try {
            val mk = MasterKey.Builder(c).setKeyScheme(MasterKey.KeyScheme.AES256_GCM).build()
            EncryptedSharedPreferences.create(
                c, "greengate.secure", mk,
                EncryptedSharedPreferences.PrefKeyEncryptionScheme.AES256_SIV,
                EncryptedSharedPreferences.PrefValueEncryptionScheme.AES256_GCM)
        } catch (e: Exception) {
            // Keystore unavailable (rare, some emulators): fall back to a private file so the
            // device still works. The keys are then only protected by app sandboxing.
            c.getSharedPreferences("greengate.secure.fallback", Context.MODE_PRIVATE)
        }
        cached = sp
        return sp
    }

    fun devicePub(c: Context): String? = p(c).getString("devicePub", null)
    fun devicePriv(c: Context): String? = p(c).getString("devicePriv", null)
    fun setDeviceKeys(c: Context, pub: String, priv: String) =
        p(c).edit().putString("devicePub", pub).putString("devicePriv", priv).apply()

    fun deviceToken(c: Context): String? = p(c).getString("deviceToken", null)
    fun setDeviceToken(c: Context, t: String?) = p(c).edit().putString("deviceToken", t).apply()
}
