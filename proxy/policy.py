"""
GreenGate policy helpers shared by the proxy and the agents:

  * the `settings` tab (key/value) -> a Settings object with defaults (docs/SPEC.md §2)
  * the keyword filter (host substrings + URL/query tokens)
  * SafeSearch rewriting for the big search engines
  * CategoryStore: the compiled category lists (docs/SPEC.md §4), 8 bytes per domain

Plain Python, no mitmproxy import, so it can be unit-tested and reused.
"""
import bisect, gzip, hashlib, json, os, re, struct, time, urllib.parse, urllib.request

LISTS_URL = "https://github.com/maoduy/GreenGate/releases/download/lists/"

# ---------------------------------------------------------------- settings
_ALIASES = {
    "chế độ": "mode", "che do": "mode", "chedo": "mode",
    "danh mục": "categories", "danh muc": "categories", "category": "categories",
    "từ khoá": "keywords", "từ khóa": "keywords", "tu khoa": "keywords", "keyword": "keywords",
    "giờ": "schedule", "gio": "schedule", "khung giờ": "schedule", "khung gio": "schedule", "hours": "schedule",
    "an toàn": "safesearch", "safe search": "safesearch", "tìm kiếm an toàn": "safesearch",
    "refresh": "refreshSeconds", "refreshseconds": "refreshSeconds", "cập nhật": "refreshSeconds",
    "screenshotevery": "screenshotEvery", "chụp màn hình": "screenshotEvery", "chup man hinh": "screenshotEvery",
    "chụp mỗi": "screenshotEvery", "chup moi": "screenshotEvery", "screenshot": "screenshotEvery",
    "screenshothours": "screenshotHours", "giờ chụp": "screenshotHours", "gio chup": "screenshotHours",
    "uploadurl": "uploadUrl", "upload": "uploadUrl", "drive": "uploadUrl", "tải lên": "uploadUrl", "tai len": "uploadUrl",
    "drivefolder": "driveFolder", "thư mục drive": "driveFolder", "thu muc drive": "driveFolder", "folder": "driveFolder",
    "retentiondays": "retentionDays", "giữ": "retentionDays", "lưu": "retentionDays",
    "blockpage": "blockPage", "thông báo chặn": "blockPage",
    "deepinspect": "deepInspect", "inspect": "deepInspect", "kiểm tra sâu": "deepInspect", "kiem tra sau": "deepInspect",
    "giải mã": "deepInspect", "giai ma": "deepInspect", "soi sâu": "deepInspect",
    "shorts": "shorts", "youtube": "youtube", "mode": "mode", "categories": "categories",
    "keywords": "keywords", "safesearch": "safesearch", "schedule": "schedule",
}
_MODE = {"whitelist": "whitelist", "chỉ cho phép": "whitelist", "chi cho phep": "whitelist", "allow": "whitelist",
         "danh sách cho phép": "whitelist", "trắng": "whitelist", "blacklist": "blacklist",
         "chặn danh sách": "blacklist", "chan danh sach": "blacklist", "block": "blacklist", "đen": "blacklist",
         "cho phép tất cả": "blacklist", "cho phep tat ca": "blacklist"}
_ON = {"on", "1", "true", "yes", "có", "co", "bật", "bat", "mở", "strict", "active"}
_OFF = {"off", "0", "false", "no", "không", "khong", "tắt", "tat", "allow"}
_YT = {"channels": "channels", "kênh": "channels", "kenh": "channels", "channel": "channels",
       "restricted": "restricted", "hạn chế": "restricted", "han che": "restricted", "safe": "restricted",
       "block": "block", "chặn": "block", "chan": "block", "off": "block",
       "any": "any", "tất cả": "any", "tat ca": "any", "all": "any", "free": "any"}
DEFAULT_CATEGORIES = ("adult", "gambling", "drugs", "weapons", "violence", "malware", "bypass")

# Built-in keyword list. Two kinds: `host_parts` match anywhere inside a host name (chosen so
# that they do not occur in ordinary words), `tokens` must match a whole token of the host,
# path, query or search text (so "sex" does not hit "sussex" or "essex").
DEFAULT_HOST_PARTS = ("porn", "xxx", "hentai", "xvideos", "xnxx", "redtube", "youporn", "brazzers",
                      "onlyfans", "xhamster", "sexvid", "phimsex", "sexviet", "javhd", "camgirl",
                      "escort", "stripchat", "chaturbate", "livejasmin", "bongacams", "nudes")
DEFAULT_TOKENS = ("porn", "porno", "xxx", "sex", "sexy", "nude", "naked", "hentai", "jav", "18+",
                  "khiêu dâm", "khieu dam", "phim sex", "sex việt", "sex viet", "gái gọi", "gai goi",
                  "mại dâm", "mai dam", "địt", "lồn", "cặc", "buồi", "chịch", "phim người lớn",
                  "phim nguoi lon", "lộ hàng", "lo hang", "clip nóng", "clip nong", "ảnh nóng",
                  "anh nong", "boobs", "tits", "pussy", "dick", "cock", "blowjob", "handjob", "milf",
                  "camsex", "webcam sex", "onlyfans", "escort")
SEARCH_PARAMS = ("q", "query", "search_query", "p", "text", "k", "s", "wd", "search", "keyword", "term")


class Settings:
    def __init__(self):
        self.mode = "whitelist"
        self.categories = None          # None = "use defaults when in blacklist mode"
        self.keywords_extra = []
        self.keywords_default = True
        self.safesearch = True
        self.youtube = None             # None = channels if channels listed, else restricted
        self.shorts = True              # block
        self.schedule = ""
        self.refreshSeconds = 60
        self.screenshotEvery = 15       # minutes; uploaded to Drive when uploadUrl is set (SPEC §8)
        self.screenshotHours = ""       # time windows; empty = always
        self.uploadUrl = ""
        self.driveFolder = ""
        self.retentionDays = 30
        self.blockPage = ""
        # True: every allowed site is decrypted and checked per URL (keywords in the path,
        # full history). False: a site the parents listed is relayed without decryption, like
        # the media CDNs - faster, host-level rules only (SPEC §2, "deepInspect").
        self.deepInspect = True
        self.raw = {}
        self.errors = []

    def effective_categories(self):
        if self.categories is not None:
            return tuple(self.categories)
        return DEFAULT_CATEGORIES if self.mode == "blacklist" else ()

    def effective_youtube(self, channels_listed):
        if self.youtube:
            return self.youtube
        return "channels" if channels_listed else "restricted"

    def to_dict(self):
        return {"mode": self.mode, "categories": list(self.effective_categories()),
                "keywordsDefault": self.keywords_default, "keywordsExtra": self.keywords_extra,
                "safesearch": self.safesearch, "youtube": self.youtube, "shorts": self.shorts,
                "schedule": self.schedule, "refreshSeconds": self.refreshSeconds,
                "screenshotEvery": self.screenshotEvery, "screenshotHours": self.screenshotHours,
                "uploadUrl": self.uploadUrl, "driveFolder": self.driveFolder, "retentionDays": self.retentionDays,
                "blockPage": self.blockPage, "deepInspect": self.deepInspect, "errors": self.errors}


def _split_list(v):
    return [x.strip().lower() for x in re.split(r"[,;\n]+", v or "") if x.strip()]


def parse_settings(rows):
    """rows: iterable of [key, value, ...] (header row already removed or not - a header is
    simply an unknown key and is ignored)."""
    s = Settings()
    for row in rows:
        if not row:
            continue
        k = (row[0] or "").strip().lower().rstrip(":")
        v = (row[1] if len(row) > 1 else "") or ""
        v = v.strip()
        if not k or k.startswith("#"):
            continue
        key = _ALIASES.get(k, k)
        s.raw[key] = v
        try:
            if key == "mode":
                s.mode = _MODE.get(v.lower(), None) or s.mode
                if v and v.lower() not in _MODE:
                    s.errors.append("mode: '%s' không hiểu, dùng whitelist" % v)
            elif key == "categories":
                s.categories = _split_list(v)
            elif key == "keywords":
                items = _split_list(v)
                s.keywords_default = ("+default" in items) or not items
                s.keywords_extra = [x for x in items if x != "+default"]
            elif key == "safesearch":
                s.safesearch = v.lower() not in _OFF
            elif key == "youtube":
                s.youtube = _YT.get(v.lower())
                if v and s.youtube is None:
                    s.errors.append("youtube: '%s' không hiểu" % v)
            elif key == "shorts":
                s.shorts = v.lower() not in {"allow", "cho phép", "cho phep", "on", "mở", "mo"}
            elif key == "schedule":
                s.schedule = v
            elif key == "refreshSeconds":
                n = int(re.sub(r"\D", "", v) or 60)
                if re.search(r"ph[uú]t|min", v.lower()):
                    n *= 60
                s.refreshSeconds = max(30, min(3600, n))
            elif key == "screenshotEvery":
                s.screenshotEvery = max(0, int(re.sub(r"\D", "", v) or 0))
            elif key == "screenshotHours":
                s.screenshotHours = v.strip()
            elif key == "uploadUrl":
                u = v.strip()
                local = re.match(r"^http://(127\.0\.0\.1|localhost|10\.0\.2\.2)[:/]", u) is not None   # tests
                s.uploadUrl = u if (u.startswith("https://") or local) else ""
                if v.strip() and not s.uploadUrl:
                    s.errors.append("uploadUrl: phải là link https://script.google.com/.../exec")
            elif key == "driveFolder":
                s.driveFolder = v.strip()
            elif key == "retentionDays":
                s.retentionDays = max(1, int(re.sub(r"\D", "", v) or 30))
            elif key == "blockPage":
                s.blockPage = v[:300]
            elif key == "deepInspect":
                s.deepInspect = v.lower() not in _OFF
        except Exception as e:
            s.errors.append("%s: %s" % (key, e))
    return s


def looks_like_settings(rows):
    """gviz answers a request for a tab that does not exist with the FIRST tab, so a
    missing settings tab would otherwise be parsed as the site list. Known keys tell."""
    for row in rows:
        if row and _ALIASES.get((row[0] or "").strip().lower().rstrip(":")) in _ALIASES.values():
            return True
    return False


# ---------------------------------------------------------------- sheet tabs
# Two public endpoints read a link-shared sheet. gviz (by tab NAME) re-types every column
# and drops text found in a numeric column ("chặn" next to "60" comes back EMPTY, SPEC §1),
# and answers a missing tab with the first tab. export?format=csv&gid= returns the cells as
# typed, but needs the gid; the public /htmlview page lists every tab with its gid.
_TAB_ITEM = re.compile(r'items\.push\(\{name: "((?:[^"\\]|\\.)*)",[^}]*?gid: "(\d+)"')
_JS_ESC = re.compile(r'\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|.)')


def _js_unescape(s):
    def one(m):
        e = m.group(1)
        if len(e) == 3 and e[0] == "x":
            return chr(int(e[1:], 16))
        if len(e) == 5 and e[0] == "u":
            return chr(int(e[1:], 16))
        return {"n": "\n", "t": "\t"}.get(e, e)
    return _JS_ESC.sub(one, s)


def https_handler():
    """urllib HTTPSHandler whose trust store is the OS store PLUS certifi's bundle.
    A freshly installed Windows ships almost no root CAs: it fetches them on demand
    through schannel, which Python/OpenSSL never triggers - so on a brand-new Home PC
    every Google fetch died with CERTIFICATE_VERIFY_FAILED (seen 02-11-2026 in the
    Windows 11 Home VM) while the browser worked fine. certifi (bundled by mitmproxy and
    by the Setup.exe build) covers that case; the OS store keeps corporate CAs working."""
    import ssl
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    return urllib.request.HTTPSHandler(context=ctx)


def direct_opener():
    """Never via the system proxy (which may be ourselves, or a dead leftover)."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), https_handler())


def sheet_tab_gids(html):
    """{tab name: gid} parsed from the sheet's /htmlview page; {} when nothing matched."""
    return {_js_unescape(n): g for n, g in _TAB_ITEM.findall(html or "")}


def sheet_htmlview_url(sid):
    return "https://docs.google.com/spreadsheets/d/%s/htmlview" % sid


def sheet_tab_url(sid, tab, gids=None):
    """CSV URL for one tab BY NAME. With a gid map: the export endpoint ('' = tab absent).
    Without one (htmlview unreadable): gviz, with the caveats above."""
    if gids is not None:
        gid = gids.get(tab)
        return ("https://docs.google.com/spreadsheets/d/%s/export?format=csv&gid=%s" % (sid, gid)) if gid else ""
    return ("https://docs.google.com/spreadsheets/d/%s/gviz/tq?tqx=out:csv&headers=1&sheet=%s"
            % (sid, urllib.parse.quote(tab)))


# ---------------------------------------------------------------- keywords
class Keywords:
    def __init__(self, extra=(), use_default=True):
        self.host_parts = set(DEFAULT_HOST_PARTS) if use_default else set()
        self.tokens = set(DEFAULT_TOKENS) if use_default else set()
        for k in extra:
            k = k.strip().lower()
            if not k:
                continue
            self.tokens.add(k)
            if len(k) >= 5 and re.match(r"^[a-z0-9]+$", k):
                self.host_parts.add(k)
        # Deterministic order (sets iterate differently per process): longest first, so the
        # most specific phrase is the one reported.
        self._parts = tuple(sorted(self.host_parts, key=lambda x: (-len(x), x)))
        self._single = {t for t in self.tokens if " " not in t}
        self._phrases = tuple(sorted((t for t in self.tokens if " " in t), key=lambda x: (-len(x), x)))

    @staticmethod
    def _tokens(text):
        return re.split(r"[^0-9a-zà-ỹ+]+", text.lower())

    def hit_host(self, host):
        h = (host or "").lower()
        for p in self._parts:
            if p in h:
                return p
        for t in h.replace("-", ".").split("."):
            if t in self._single:
                return t
        return None

    def hit_text(self, text, quoted=False):
        """Path, query, search words. Returns the keyword that matched or None.
        quoted=True when the text is still percent-encoded (a raw path)."""
        if not text:
            return None
        t = (urllib.parse.unquote_plus(text) if quoted else text).lower()
        for ph in self._phrases:
            if ph in t:
                return ph
        for tok in self._tokens(t):
            if tok and tok in self._single:
                return tok
        return None

    def hit_url(self, host, path):
        k = self.hit_host(host)
        if k:
            return k
        p, _, q = (path or "").partition("?")
        k = self.hit_text(p, quoted=True)
        if k:
            return k
        if q:
            for key, val in urllib.parse.parse_qsl(q, keep_blank_values=False):
                if key.lower() in SEARCH_PARAMS:
                    k = self.hit_text(val)
                    if k:
                        return k
        return None


# ---------------------------------------------------------------- SafeSearch
_GOOGLE = re.compile(r"(^|\.)google\.[a-z.]+$")


def safesearch_host(host):
    """True for the search engines safesearch_rewrite() knows: their URLs must be decrypted."""
    h = (host or "").lower()
    return bool(_GOOGLE.search(h)) or h.endswith(("bing.com", "duckduckgo.com", "yandex.com", "yandex.ru"))


def safesearch_rewrite(host, path):
    """-> new path or None. Google: safe=active on /search. Bing: adlt=strict. DuckDuckGo: kp=1.
    Yandex: family=yes."""
    h = (host or "").lower()
    p, _, q = path.partition("?")
    params = urllib.parse.parse_qsl(q, keep_blank_values=True)
    changed = False
    def force(key, val):
        nonlocal params, changed
        if not any(k == key and v == val for k, v in params):
            params = [(k, v) for k, v in params if k != key] + [(key, val)]
            changed = True
    if _GOOGLE.search(h) and p in ("/search", "/images", "/videohp", "/complete/search"):
        force("safe", "active")
    elif h.endswith("bing.com") and p.startswith(("/search", "/images", "/videos")):
        force("adlt", "strict")
    elif h.endswith("duckduckgo.com") and (p == "/" or p.startswith("/html")) and any(k == "q" for k, _ in params):
        force("kp", "1")
    elif h.endswith(("yandex.com", "yandex.ru")) and p.startswith(("/search", "/images", "/video")):
        force("family", "yes")
    if not changed:
        return None
    return p + "?" + urllib.parse.urlencode(params)


# ---------------------------------------------------------------- category lists
def h64(domain):
    return struct.unpack(">Q", hashlib.sha1(domain.encode()).digest()[:8])[0]


class CategoryStore:
    """Keeps <dataDir>/lists/<cat>.bin (sorted uint64 hashes) for the enabled categories,
    refreshes them daily from the GitHub release, keeps the old file when a download fails."""

    def __init__(self, data_dir, log=print, base_url=LISTS_URL, max_age=86400):
        self.dir = os.path.join(data_dir, "lists")
        os.makedirs(self.dir, exist_ok=True)
        self.log, self.base_url, self.max_age = log, base_url, max_age
        self.sets = {}          # cat -> bytes (sorted big-endian uint64)
        self.meta = {}          # cat -> {count, loaded, mtime}
        self.enabled = ()

    def _path(self, cat):
        return os.path.join(self.dir, re.sub(r"[^a-z0-9-]", "", cat) + ".bin")

    def _load(self, cat):
        p = self._path(cat)
        try:
            with open(p, "rb") as f:
                raw = f.read()
            if len(raw) % 8:
                raise ValueError("truncated")
            self.sets[cat] = raw
            self.meta[cat] = {"count": len(raw) // 8, "loaded": time.time(), "mtime": os.path.getmtime(p)}
            return True
        except FileNotFoundError:
            return False
        except Exception as e:
            self.log("category %s: unreadable cache (%s)" % (cat, e))
            return False

    def _download(self, cat):
        url = self.base_url + cat + ".bin"
        opener = direct_opener()
        req = urllib.request.Request(url, headers={"User-Agent": "greengate/1.0"})
        with opener.open(req, timeout=120) as r:
            raw = r.read()
        if len(raw) % 8 or len(raw) < 8:
            raise ValueError("bad list file (%d bytes)" % len(raw))
        tmp = self._path(cat) + ".tmp"
        with open(tmp, "wb") as f:
            f.write(raw)
        os.replace(tmp, self._path(cat))

    def set_enabled(self, cats):
        """Load from disk at once (cheap), download what is missing or stale."""
        self.enabled = tuple(c for c in cats if c)
        for cat in self.enabled:
            if cat not in self.sets:
                self._load(cat)
        for cat in list(self.sets):
            if cat not in self.enabled:
                self.sets.pop(cat, None); self.meta.pop(cat, None)

    def refresh(self):
        """Call from a background thread. Returns the list of categories updated."""
        updated = []
        for cat in self.enabled:
            m = self.meta.get(cat)
            fresh = m and time.time() - m["mtime"] < self.max_age
            if fresh:
                continue
            try:
                self._download(cat)
                self._load(cat)
                updated.append(cat)
                self.log("category %s: %d domains" % (cat, self.meta[cat]["count"]))
            except Exception as e:
                self.log("category %s: download failed (%s)%s" % (
                    cat, e, ", keeping the old list" if cat in self.sets else " - no list yet"))
                if cat in self.meta:
                    self.meta[cat]["mtime"] = time.time() - self.max_age + 3600   # retry in an hour
        return updated

    @staticmethod
    def _has(raw, value):
        n = len(raw) // 8
        lo, hi = 0, n
        while lo < hi:
            mid = (lo + hi) // 2
            v = struct.unpack_from(">Q", raw, mid * 8)[0]
            if v < value:
                lo = mid + 1
            elif v > value:
                hi = mid
            else:
                return True
        return False

    def match(self, host):
        """-> category name that lists this host or a parent domain, or None."""
        if not self.sets:
            return None
        h = (host or "").lower().rstrip(".")
        parts = h.split(".")
        cands = [h64(".".join(parts[i:])) for i in range(len(parts) - 1)]
        for cat, raw in self.sets.items():
            for c in cands:
                if self._has(raw, c):
                    return cat
        return None

    def status(self):
        return {c: {"count": self.meta.get(c, {}).get("count", 0),
                    "loaded": bool(c in self.sets)} for c in self.enabled}
