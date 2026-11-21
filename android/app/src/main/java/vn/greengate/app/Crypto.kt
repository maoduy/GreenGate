package vn.greengate.app

import android.util.Base64
import com.goterl.lazysodium.LazySodiumAndroid
import com.goterl.lazysodium.SodiumAndroid
import com.goterl.lazysodium.interfaces.Box

/** nacl.box (X25519 + XSalsa20-Poly1305). Wire format: base64( nonce(24) || box ). */
object Crypto {
    private val ls by lazy { LazySodiumAndroid(SodiumAndroid()) }

    fun b64(b: ByteArray): String = Base64.encodeToString(b, Base64.NO_WRAP)
    fun unb64(s: String): ByteArray = Base64.decode(s, Base64.DEFAULT)

    fun keypair(): Pair<String, String> {
        val pk = ByteArray(Box.PUBLICKEYBYTES); val sk = ByteArray(Box.SECRETKEYBYTES)
        if (!ls.cryptoBoxKeypair(pk, sk)) throw IllegalStateException("keypair failed")
        return b64(pk) to b64(sk)
    }

    fun seal(plain: ByteArray, receiverPub: String, senderPriv: String): String {
        val nonce = ls.randomBytesBuf(Box.NONCEBYTES)
        val out = ByteArray(plain.size + Box.MACBYTES)
        if (!ls.cryptoBoxEasy(out, plain, plain.size.toLong(), nonce, unb64(receiverPub), unb64(senderPriv)))
            throw IllegalStateException("box failed")
        return b64(nonce + out)
    }

    fun open(blob: String, senderPub: String, receiverPriv: String): ByteArray {
        val all = unb64(blob)
        if (all.size < Box.NONCEBYTES + Box.MACBYTES) throw IllegalArgumentException("blob too short")
        val nonce = all.copyOfRange(0, Box.NONCEBYTES)
        val cipher = all.copyOfRange(Box.NONCEBYTES, all.size)
        val out = ByteArray(cipher.size - Box.MACBYTES)
        if (!ls.cryptoBoxOpenEasy(out, cipher, cipher.size.toLong(), nonce, unb64(senderPub), unb64(receiverPriv)))
            throw IllegalArgumentException("box open failed (wrong key or tampered)")
        return out
    }
}
