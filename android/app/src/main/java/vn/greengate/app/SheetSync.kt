package vn.greengate.app

import android.content.Context
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URLEncoder
import java.util.concurrent.TimeUnit

/** Reads the five tabs (SPEC §1) and builds [Rules]. Keeps the last good copy on failure. */
object SheetSync {
    private const val TAG = "GreenGateSync"
    val TABS = listOf("websites", "youtube", "blocked", "apps", "settings")

    val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build()

    fun sheetId(value: String): String {
        val v = value.trim()
        Regex("/spreadsheets/d/([A-Za-z0-9_-]{20,})").find(v)?.let { return it.groupValues[1] }
        Regex("^([A-Za-z0-9_-]{20,})(?:[/?#].*)?$").find(v)?.let { return it.groupValues[1] }
        return ""
    }

    private val TAB_ITEM = Regex("items\\.push\\(\\{name: \"((?:[^\"\\\\]|\\\\.)*)\",[^}]*?gid: \"(\\d+)\"")

    /** {tab name: gid} from the sheet's public /htmlview page (SPEC §1); null when unreadable. */
    fun fetchGids(c: Context): Map<String, String>? {
        if (Prefs.sheetBase(c).isNotEmpty()) return null
        val sid = sheetId(Prefs.sheetId(c))
        if (sid.isEmpty()) return null
        return try {
            val req = Request.Builder().url("https://docs.google.com/spreadsheets/d/$sid/htmlview")
                .header("User-Agent", "greengate-android/1.0").header("Cache-Control", "no-cache").build()
            http.newCall(req).execute().use { r ->
                if (!r.isSuccessful) return null
                val html = r.body?.string() ?: return null
                val m = HashMap<String, String>()
                for (hit in TAB_ITEM.findAll(html)) m[jsUnescape(hit.groupValues[1])] = hit.groupValues[2]
                if (m.isEmpty()) null else m
            }
        } catch (e: Exception) { Log.w(TAG, "tab list: ${e.message} (reading tabs by name via gviz)"); null }
    }

    private fun jsUnescape(s: String): String = Regex("\\\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|.)").replace(s) { m ->
        val e = m.groupValues[1]
        when {
            e.length == 3 && e[0] == 'x' -> e.substring(1).toInt(16).toChar().toString()
            e.length == 5 && e[0] == 'u' -> e.substring(1).toInt(16).toChar().toString()
            else -> e
        }
    }

    /** export-by-gid keeps cells as typed ("" = tab absent); gviz (fallback) empties text in a numeric column. */
    fun tabUrl(c: Context, tab: String, gids: Map<String, String>? = null): String {
        val base = Prefs.sheetBase(c)
        if (base.isNotEmpty()) return "${base.trimEnd('/')}/$tab.csv"
        val sid = sheetId(Prefs.sheetId(c))
        if (gids != null) {
            val gid = gids[tab] ?: return ""
            return "https://docs.google.com/spreadsheets/d/$sid/export?format=csv&gid=$gid"
        }
        return "https://docs.google.com/spreadsheets/d/$sid/gviz/tq?tqx=out:csv&headers=1&sheet=" + URLEncoder.encode(tab, "UTF-8")
    }

    /** One tab -> CSV text. A missing tab (not in the map, or 400/404) is null; other errors throw. */
    fun fetchTab(c: Context, tab: String, gids: Map<String, String>? = fetchGids(c)): String? {
        val url = tabUrl(c, tab, gids)
        if (url.isEmpty()) return null
        val req = Request.Builder().url(url)
            .header("User-Agent", "greengate-android/1.0").header("Cache-Control", "no-cache").build()
        http.newCall(req).execute().use { r ->
            if (r.code == 404 || r.code == 400) return null
            if (!r.isSuccessful) throw java.io.IOException("HTTP ${r.code} for $tab")
            val body = r.body?.string() ?: ""
            // gviz answers an HTML error page for a missing tab on some sheets; treat as absent
            if (body.trimStart().startsWith("<")) return null
            return body
        }
    }

    /** Build rules from the cache (what the last sync wrote) - used at service start. */
    fun fromCache(c: Context): Rules {
        if (Prefs.lastSync(c) == 0L) return Rules.EMPTY
        return Rules.build(Prefs.cachedTab(c, "websites"), Prefs.cachedTab(c, "youtube"), Prefs.cachedTab(c, "blocked"),
            Prefs.cachedTab(c, "apps"), Prefs.cachedTab(c, "settings"), overrides(c))
    }

    private fun overrides(c: Context): Map<String, String> {
        val m = HashMap<String, String>()
        for (k in listOf("screenshotevery", "retentiondays")) Prefs.override(c, k)?.let { m[k] = it }
        return m
    }

    /** Fetch everything. Returns the new rules, or null (keeping the old ones) when the sheet is unreachable. */
    fun sync(c: Context): Rules? {
        val t0 = System.currentTimeMillis()
        val got = HashMap<String, String?>()
        try {
            val gids = fetchGids(c)
            for (tab in TABS) got[tab] = fetchTab(c, tab, gids)
        } catch (e: Exception) {
            Log.w(TAG, "sheet refresh failed: ${e.message} (keeping previous list)")
            Prefs.setLastSyncError(c, e.message ?: e.toString())
            return null
        }
        if (got["websites"] == null && got["blocked"] == null && got["settings"] == null) {
            Prefs.setLastSyncError(c, "no readable tab (is the sheet shared as 'anyone with the link'?)")
            return null
        }
        for (tab in TABS) {
            val v = got[tab]
            if (v != null) Prefs.setCachedTab(c, tab, v) else Prefs.setCachedTab(c, tab, "")
        }
        Prefs.setLastSync(c, System.currentTimeMillis())
        Prefs.setLastSyncError(c, "")
        val rules = Rules.build(got["websites"], got["youtube"], got["blocked"], got["apps"], got["settings"], overrides(c))
        Log.i(TAG, "lists loaded: mode=${rules.mode} ${rules.allowed.size} sites, ${rules.blocked.size} blocked, " +
            "${rules.channels} channels, cats=${rules.categories}, kw=${rules.keywords.size}, apps=${rules.blockedApps.size} in ${System.currentTimeMillis() - t0}ms")
        return rules
    }
}
