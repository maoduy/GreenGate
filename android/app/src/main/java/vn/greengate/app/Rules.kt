package vn.greengate.app

import java.util.Locale

/**
 * Everything the DNS filter needs, parsed from the sheet (SPEC §1-§3). Immutable; the
 * service swaps the whole object on each successful sync.
 */
class Rules(
    val loaded: Boolean,                       // false until the first successful sheet read
    val mode: String,                          // "whitelist" | "blacklist"
    val allowed: Set<String>,                  // bare domains from `websites` (subdomains covered)
    val blocked: Set<String>,                  // bare domains from `blocked`
    val channels: Int,                         // number of listed YouTube channels
    val categories: Set<String>,
    val keywords: List<String>,
    val safeSearch: Boolean,
    val youtube: String,                       // channels | restricted | block | any
    val schedule: List<TimeWindow.Window>,
    val scheduleError: String?,
    val refreshSeconds: Int,
    val retentionDays: Int,
    val screenshotEvery: Int,                  // minutes, 0 = off (SPEC §8)
    val screenshotHours: List<TimeWindow.Window>,   // only capture inside these windows (empty = always)
    val screenshotHoursError: String?,
    val uploadUrl: String,                     // Apps Script web-app URL (SPEC §8), empty = no upload
    val driveFolder: String,                   // Drive folder link, shown to the parent
    val blockedApps: Set<String>,              // package names from `apps`
    val raw: Map<String, String>,              // settings as read
) {
    companion object {
        val HEADERS = setOf("site", "sites", "website", "websites", "domain", "domains", "url", "urls",
            "channel", "channels", "kênh", "trang", "trang web", "key", "khoá", "khóa", "app", "apps", "ứng dụng")
        val HELPERS = setOf("docs.google.com", "googleusercontent.com", "googlevideo.com", "ytimg.com",
            "ggpht.com", "gstatic.com", "googleapis.com", "challenges.cloudflare.com", "recaptcha.net",
            "github.com", "githubusercontent.com", "objects.githubusercontent.com")
        val YT_DOMAINS = setOf("youtube.com", "youtube-nocookie.com", "youtubei.googleapis.com", "youtu.be")
        val YT_PACKAGES = setOf("com.google.android.youtube", "com.google.android.apps.youtube.kids",
            "com.google.android.apps.youtube.music", "com.google.android.youtube.tv")
        // Built-in keyword list (`keywords = +default`). Tokens, matched between separators.
        val DEFAULT_KEYWORDS = listOf("porn", "porno", "xxx", "sex", "sexy", "hentai", "nude", "nudes", "naked",
            "xvideos", "xnxx", "pornhub", "redtube", "onlyfans", "camgirl", "escort", "erotic", "fetish",
            "bdsm", "milf", "blowjob", "anal", "dick", "pussy", "boobs", "jav", "phim sex", "phimsex",
            "sex viet", "sexviet", "lauxanh", "gai goi", "gaigoi", "casino", "ca cuoc", "cacuoc", "lo de", "lode",
            "gore", "beheading", "suicide", "self harm", "selfharm")
        val DEFAULT_CATEGORIES = setOf("adult", "gambling", "drugs", "weapons", "violence", "malware", "bypass")

        val EMPTY = Rules(false, "whitelist", emptySet(), emptySet(), 0, DEFAULT_CATEGORIES, DEFAULT_KEYWORDS,
            true, "restricted", emptyList(), null, 60, 30, 15, emptyList(), null, "", "", emptySet(), emptyMap())

        fun normSite(s0: String): Pair<String, String> {   // (kind, value) kind = domain | path
            var s = s0.trim().lowercase(Locale.ROOT)
            s = s.replace(Regex("^https?://"), "").replace(Regex("^\\*\\.?"), "").replace(Regex("^www\\."), "")
            return if ("/" in s.trimEnd('/')) "path" to s.trimEnd('/') else "domain" to s.trim('/')
        }

        private fun firstCol(csv: String?): List<List<String>> {
            if (csv == null) return emptyList()
            // a self-written header (contains whitespace or brackets) is no rule either, SPEC §1
            return Csv.parse(csv).filter { r -> r.isNotEmpty() && r[0].trim().let { it.isNotEmpty() && !it.startsWith("#") && it.lowercase() !in HEADERS && !Regex("[\\s(\\[]").containsMatchIn(it) } }
        }

        private fun kv(csv: String?): Map<String, String> {
            val out = HashMap<String, String>()
            for (r in firstCol(csv)) {
                val k = r[0].trim().lowercase(Locale.ROOT)
                val v = if (r.size > 1) r[1].trim() else ""
                out[alias(k)] = v
            }
            return out
        }

        /** Same aliases as proxy/policy.py `_ALIASES` (SPEC §2), lower-cased. */
        private fun alias(k: String) = when (k) {
            "chế độ", "che do", "chedo", "mode" -> "mode"
            "danh mục", "danh muc", "category", "categories" -> "categories"
            "từ khoá", "từ khóa", "tu khoa", "keyword", "keywords" -> "keywords"
            "giờ", "gio", "khung giờ", "khung gio", "hours", "schedule" -> "schedule"
            "an toàn", "safe search", "tìm kiếm an toàn", "safesearch" -> "safesearch"
            "refresh", "refreshseconds", "cập nhật", "cap nhat" -> "refreshseconds"
            "screenshotevery", "chụp màn hình", "chup man hinh", "chụp mỗi", "chup moi" -> "screenshotevery"
            "screenshothours", "giờ chụp", "gio chup" -> "screenshothours"
            "uploadurl", "upload url", "drive", "upload", "tải lên", "tai len", "url tải lên", "url tai len" -> "uploadurl"
            "drivefolder", "drive folder", "thư mục drive", "thu muc drive", "folder" -> "drivefolder"
            "retentiondays", "giữ", "giu", "lưu", "luu" -> "retentiondays"
            "blockpage", "thông báo chặn" -> "blockpage"
            else -> k
        }

        fun build(websites: String?, youtube: String?, blocked: String?, apps: String?, settings: String?,
                  overrides: Map<String, String> = emptyMap()): Rules {
            val allowed = HashSet<String>()
            for (r in firstCol(websites)) {
                val v = r[0].trim()
                if (v == "*" || v == "**") continue
                val (kind, dom) = normSite(v)
                allowed.add(if (kind == "path") dom.substringBefore("/") else dom)   // DNS has no paths
            }
            val blockedSet = HashSet<String>()
            for (r in firstCol(blocked)) {
                val (kind, dom) = normSite(r[0])
                if (kind == "domain") blockedSet.add(dom)          // a blocked *path* cannot be done at DNS level
            }
            val channels = firstCol(youtube).size
            val s = HashMap(kv(settings)); s.putAll(overrides)
            val modeRaw = (s["mode"] ?: "whitelist").lowercase(Locale.ROOT)
            val mode = if (modeRaw.startsWith("black") || modeRaw.contains("chặn") || modeRaw.contains("chan")) "blacklist" else "whitelist"
            val cats = (s["categories"]?.takeIf { it.isNotBlank() }?.split(",")?.map { it.trim().lowercase(Locale.ROOT) }?.filter { it.isNotEmpty() }?.toSet())
                ?: DEFAULT_CATEGORIES
            val kwRaw = s["keywords"] ?: "+default"
            val kws = ArrayList<String>()
            for (k in kwRaw.split(",")) {
                val t = k.trim().lowercase(Locale.ROOT)
                if (t.isEmpty()) continue
                if (t == "+default" || t == "default" || t == "mặc định") kws.addAll(DEFAULT_KEYWORDS) else kws.add(t)
            }
            val safe = (s["safesearch"] ?: "on").lowercase(Locale.ROOT) !in setOf("off", "0", "false", "tắt", "tat", "no")
            val ytDefault = if (channels > 0) "channels" else "restricted"
            val yt = (s["youtube"]?.lowercase(Locale.ROOT)?.takeIf { it in setOf("channels", "restricted", "block", "any") }) ?: ytDefault
            var schedErr: String? = null
            val sched = try { TimeWindow.parse(s["schedule"]) } catch (e: IllegalArgumentException) { schedErr = e.message; emptyList() }
            val refresh = (s["refreshseconds"]?.toIntOrNull() ?: 60).coerceIn(30, 3600)
            val retention = (s["retentiondays"]?.toIntOrNull() ?: 30).coerceIn(1, 365)
            val shotEvery = (s["screenshotevery"]?.toIntOrNull() ?: 15).coerceIn(0, 1440)
            var shotErr: String? = null
            val shotHours = try { TimeWindow.parse(s["screenshothours"]) } catch (e: IllegalArgumentException) { shotErr = e.message; emptyList() }
            val uploadUrl = (s["uploadurl"] ?: "").trim().let { if (it.startsWith("https://") || it.startsWith("http://")) it else "" }
            val driveFolder = (s["drivefolder"] ?: "").trim()
            val appsSet = HashSet<String>()
            for (r in firstCol(apps)) {
                val a = r[0].trim().lowercase(Locale.ROOT)
                if ("." in a && !a.endsWith(".exe")) appsSet.add(a)
            }
            if (yt != "any") appsSet.addAll(YT_PACKAGES)        // channel filtering is impossible here, so the apps go
            return Rules(true, mode, allowed, blockedSet, channels, cats, kws, safe, yt, sched, schedErr,
                refresh, retention, shotEvery, shotHours, shotErr, uploadUrl, driveFolder, appsSet, s)
        }
    }

    /** Does host or one of its parent domains sit in the set? */
    fun inSet(set: Set<String>, host: String): Boolean {
        var h = host
        while (true) {
            if (h in set) return true
            val i = h.indexOf('.')
            if (i < 0) return false
            h = h.substring(i + 1)
        }
    }

    private val tokenSplit = Regex("[^a-z0-9]+")

    fun keywordHit(host: String): String? {
        if (keywords.isEmpty()) return null
        val tokens = host.lowercase(Locale.ROOT).split(tokenSplit).filter { it.isNotEmpty() }.toSet()
        val joined = tokens.joinToString(" ")
        for (k in keywords) {
            if (" " in k) { if (k in joined) return k } else if (k in tokens) return k
        }
        return null
    }
}
