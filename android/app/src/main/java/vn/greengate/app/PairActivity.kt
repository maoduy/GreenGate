package vn.greengate.app

import android.graphics.Bitmap
import android.graphics.Color
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.ImageView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.google.zxing.BarcodeFormat
import com.google.zxing.qrcode.QRCodeWriter
import java.util.concurrent.Executors

class PairActivity : AppCompatActivity() {
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        setContentView(R.layout.activity_pair)
        val code = findViewById<TextView>(R.id.code); val qr = findViewById<ImageView>(R.id.qr); val info = findViewById<TextView>(R.id.info)
        val ui = Handler(Looper.getMainLooper())
        Executors.newSingleThreadExecutor().execute {
            try {
                val (id, c) = Relay.pairStart(this, android.os.Build.MODEL)
                GreenGateVpnService.instance?.relay?.reconnect()
                val payload = "greengate:pair:$c:${Prefs.relayUrl(this)}"
                val m = QRCodeWriter().encode(payload, BarcodeFormat.QR_CODE, 512, 512)
                val bm = Bitmap.createBitmap(512, 512, Bitmap.Config.RGB_565)
                for (x in 0 until 512) for (y in 0 until 512) bm.setPixel(x, y, if (m[x, y]) Color.BLACK else Color.WHITE)
                ui.post { code.text = c.chunked(3).joinToString(" "); qr.setImageBitmap(bm); info.text = "Thiết bị: $id" }
            } catch (e: Exception) {
                ui.post { code.text = "—"; info.text = getString(R.string.pair_error, e.message) }
            }
        }
        // poll parent count so the screen can say "paired"
        ui.postDelayed(object : Runnable { override fun run() {
            val n = Prefs.parentKeys(this@PairActivity).size
            if (n > 0) info.text = getString(R.string.pair_done, n)
            ui.postDelayed(this, 2000) } }, 2000)
    }
}
