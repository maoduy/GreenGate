package vn.greengate.app

import android.content.Context
import android.util.Log
import okhttp3.Request
import java.io.DataInputStream
import java.io.DataOutputStream
import java.io.File
import java.security.MessageDigest
import java.util.zip.GZIPInputStream

/**
 * Category blocklists (SPEC §4): one gz text file per category, compiled by CI. Kept on the
 * device as a sorted LongArray of the first 8 bytes of SHA-1(domain) - 8 bytes per entry,
 * binary search per lookup. A host matches when it or any parent domain is in the set.
 */
class HashSet64(private val sorted: LongArray) {
    val size get() = sorted.size
    fun contains(domain: String): Boolean = sorted.isNotEmpty() && java.util.Arrays.binarySearch(sorted, CategoryLists.h64(domain)) >= 0
    fun matches(host: String): Boolean {
        var h = host
        while (true) {
            if (contains(h)) return true
            val i = h.indexOf('.'); if (i < 0) return false
            h = h.substring(i + 1)
        }
    }
}

object CategoryLists {
    private const val TAG = "GreenGateLists"
    const val DEFAULT_BASE = "https://github.com/maoduy/GreenGate/releases/download/lists"
    const val MAX_AGE_MS = 24L * 3600 * 1000

    @Volatile var loaded: Map<String, HashSet64> = emptyMap()
    @Volatile var lastError: String = ""
    private val sha1 = ThreadLocal.withInitial { MessageDigest.getInstance("SHA-1") }

    fun h64(domain: String): Long {
        val d = sha1.get()!!; d.reset()
        val b = d.digest(domain.lowercase().toByteArray())
        var v = 0L
        for (i in 0 until 8) v = (v shl 8) or (b[i].toLong() and 0xff)
        return v
    }

    private fun dir(c: Context) = File(c.filesDir, "lists").apply { mkdirs() }
    private fun binFile(c: Context, cat: String) = File(dir(c), "$cat.bin")

    /** Decide: in any of the given categories? Returns the category name or null. */
    fun match(host: String, cats: Set<String>): String? {
        val m = loaded
        for (cat in cats) if (m[cat]?.matches(host) == true) return cat
        return null
    }

    fun loadFromDisk(c: Context, cats: Set<String>) {
        val out = HashMap<String, HashSet64>()
        for (cat in cats) {
            val f = binFile(c, cat)
            if (!f.exists()) continue
            try {
                DataInputStream(f.inputStream().buffered()).use { din ->
                    val n = din.readInt()
                    val arr = LongArray(n) { din.readLong() }
                    out[cat] = HashSet64(arr)
                }
            } catch (e: Exception) { Log.w(TAG, "corrupt $cat.bin: ${e.message}"); f.delete() }
        }
        loaded = out
        Log.i(TAG, "category lists on disk: " + out.entries.joinToString { "${it.key}=${it.value.size}" })
    }

    /** Refresh the categories that are missing or older than a day. Never throws. */
    fun refresh(c: Context, cats: Set<String>, force: Boolean = false) {
        var changed = false
        for (cat in cats) {
            val f = binFile(c, cat)
            if (!force && f.exists() && System.currentTimeMillis() - f.lastModified() < MAX_AGE_MS) continue
            try {
                val url = "${Prefs.listsBase(c).trimEnd('/')}/$cat.txt.gz"
                val req = Request.Builder().url(url).header("User-Agent", "greengate-android/1.0").build()
                SheetSync.http.newCall(req).execute().use { r ->
                    if (r.code == 404) { Log.w(TAG, "$cat: not published yet (404)"); lastError = "$cat: 404"; return@use }
                    if (!r.isSuccessful) throw java.io.IOException("HTTP ${r.code}")
                    val hashes = ArrayList<Long>()
                    GZIPInputStream(r.body!!.byteStream()).bufferedReader().useLines { lines ->
                        for (l0 in lines) {
                            val l = l0.trim().lowercase()
                            if (l.isEmpty() || l.startsWith("#")) continue
                            hashes.add(h64(l.removePrefix("*.")))
                        }
                    }
                    val arr = hashes.toLongArray(); arr.sort()
                    val tmp = File(f.path + ".tmp")
                    DataOutputStream(tmp.outputStream().buffered()).use { dout -> dout.writeInt(arr.size); for (v in arr) dout.writeLong(v) }
                    tmp.renameTo(f)
                    changed = true
                    Log.i(TAG, "$cat: ${arr.size} domains")
                }
            } catch (e: Exception) {
                Log.w(TAG, "$cat refresh failed: ${e.message} (keeping previous copy)")
                lastError = "$cat: ${e.message}"
                if (f.exists()) f.setLastModified(System.currentTimeMillis() - MAX_AGE_MS + 3600_000)   // retry in an hour
            }
        }
        if (changed || loaded.keys != cats) loadFromDisk(c, cats)
    }
}
