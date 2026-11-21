package vn.greengate.app

import android.app.Application

class App : Application() {
    override fun onCreate() {
        super.onCreate()
        // Device keypair on first run, so pairing can show a code without any network round trip.
        if (SecurePrefs.devicePub(this) == null) {
            val (pub, priv) = Crypto.keypair()
            SecurePrefs.setDeviceKeys(this, pub, priv)
        }
    }
}
