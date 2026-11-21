package vn.greengate.app

import android.annotation.SuppressLint
import android.graphics.Bitmap
import android.os.Bundle
import android.util.Log
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.appcompat.app.AppCompatActivity
import java.net.InetAddress

/**
 * Measurement harness, not part of the product UI:
 *   am start -n vn.greengate.app/.ProbeActivity --es url https://www.google.com/
 *   am start -n vn.greengate.app/.ProbeActivity --es dns www.google.com
 * Logs "GreenGateProbe: PAGE <url> <ms> <status>" or "GreenGateProbe: DNS <host> <ms> <addr|error>".
 */
class ProbeActivity : AppCompatActivity() {
    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        val url = intent.getStringExtra("url"); val dns = intent.getStringExtra("dns")
        if (intent.getBooleanExtra("status", false)) {
            Log.i("GreenGateProbe", "STATUS " + (GreenGateVpnService.instance?.statusJson() ?: "{\"running\":false}"))
            finish(); return
        }
        if (dns != null) {
            Thread {
                val t0 = System.nanoTime()
                val r = try { InetAddress.getAllByName(dns).joinToString(",") { it.hostAddress ?: "" } } catch (e: Exception) { "error:${e.javaClass.simpleName}" }
                Log.i("GreenGateProbe", "DNS $dns ${(System.nanoTime() - t0) / 1_000_000} $r")
                runOnUiThread { finish() }
            }.start()
            return
        }
        val wv = WebView(this); setContentView(wv)
        wv.settings.javaScriptEnabled = true
        WebView.setWebContentsDebuggingEnabled(false)
        wv.clearCache(true)
        val t0 = System.nanoTime()
        var done = false
        var status = "ok"
        wv.webViewClient = object : WebViewClient() {
            override fun onReceivedError(view: WebView, code: Int, desc: String, failingUrl: String) { if (failingUrl == url) status = "error:$code:$desc" }
            override fun onPageFinished(view: WebView, u: String) {
                if (done) return; done = true
                Log.i("GreenGateProbe", "PAGE $url ${(System.nanoTime() - t0) / 1_000_000} $status")
                view.postDelayed({ finish() }, 300)
            }
        }
        wv.loadUrl(url ?: "about:blank")
    }
}
