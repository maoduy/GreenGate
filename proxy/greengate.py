"""
GreenGate - mitmproxy addon.

* Allows only websites listed in the Google Sheet (tab "websites"), for ENFORCED users.
* On youtube.com, only videos from channels listed in the sheet (tab "youtube") play;
  search/home/related lists are filtered to those channels; Shorts are blocked.
* Users that are members of the local Administrators group (or listed in EXEMPT_USERS)
  are not filtered at all. Service accounts (SYSTEM, *$) are never filtered.
* Lists are re-downloaded every REFRESH_SECONDS. On failure the last good list stays.

Run:  mitmdump -s greengate.py --listen-host 127.0.0.1 --listen-port 8080
Config: greengate.json next to this file (optional), keys: sitesUrl, channelsUrl,
        refreshSeconds, exemptUsers (list), enforceUsers (list, overrides admin check).
"""
import csv, io, ipaddress, json, os, re, sys, threading, time, types, urllib.request, urllib.parse, urllib.error, subprocess, platform
from mitmproxy import http, ctx

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import policy, timewindow        # plain modules next to this file (shared with the agents)
VERSION = "2.0.0"

# mitmproxy loads this script as SEVERAL independent modules. Module-level globals are
# therefore per-load, not per-process: each copy would refresh its own list, and only the
# copy whose addon instance serves a request decides that request. Everything that must be
# singular lives on one object parked in sys.modules instead.
_shared = sys.modules.get("__greengate_shared__")
if _shared is None:
    _shared = types.ModuleType("__greengate_shared__")
    _shared.lists = None
    _shared.lock = threading.Lock()
    _shared.counts = None
    _shared.sheet = None
    _shared.usage = None
    _shared.refresher = False
    _shared.urllog = False
    _shared.update_running = False
    _shared.update_pending = False
    _shared.start_lock = threading.Lock()
    _shared.cats = None
    _shared.gids = None       # {tab: gid} from /htmlview, kept across failed refreshes
    _shared.backoff = 0
    sys.modules["__greengate_shared__"] = _shared
DEFAULTS = {
    # Preferred: the spreadsheet id (or its full link) plus TAB NAMES. gid numbers differ in
    # every copy of a sheet, so a shared setup cannot use them.
    "sheetId": "",
    "sitesTab": "websites",
    "channelsTab": "youtube",
    "settingsTab": "settings",
    "blockedTab": "blocked",
    "appsTab": "apps",
    # Where the compiled category lists live (docs/SPEC.md §4). file:// works for tests.
    "listsUrl": policy.LISTS_URL,
    # Explicit CSV urls still win when set, for anything the pair above cannot express.
    "sitesUrl": "",
    "channelsUrl": "",
    "refreshSeconds": 60,         # the sheet's settings.refreshSeconds overrides this
    "exemptUsers": [],
    "enforceUsers": [],      # if non-empty: ONLY these users are filtered
    "blockShorts": True,
    "filterFeeds": True,
    # smart mode: only page navigations must be to a listed site; resources a listed page loads
    # (scripts, images, video, embedded players) are allowed automatically via Referer/Origin.
    "smartDependencies": True,
    "dependencyTtlSeconds": 3600,
    "passthroughMedia": True,   # tunnel googlevideo/ytimg/ggpht/gstatic without decrypting (speed)
    # A minute counts toward a budget after this many browser requests, or at once on a
    # page navigation. Stops a background tab burning the day's allowance while nobody
    # is at the machine. 1 = count every minute that saw any browser traffic.
    "activityRequests": 3,
    "dataDir": "",          # empty -> C:\ProgramData\GreenGate
    "logFile": "",          # empty -> greengate.log inside dataDir
    # URL log -> Google Sheet: one tab per month "MM-yyyy", row = URL, column = day, cell = hits.
    # Blocked attempts go to "MM-yyyy chan". Only filtered (kid) accounts are logged.
    "urlLog": {
        "enabled": False,
        "sheetId": "",
        "credentials": "greengate-sheets.json",   # its OWN service account, not a shared one
        "flushSeconds": 300,
        "sheetAllRequests": False,   # False = only page navigations reach the sheet
        "localFile": "",             # a path (or true = <dataDir>/urls.jsonl) to also keep a JSONL of EVERY request
        "localMaxMB": 20,            # rotate that JSONL at this size (one generation kept)
    },
}
CFG = dict(DEFAULTS)


def _pick_data_dir(preferred):
    """Everything written at runtime lives here - NOT in Program Files. Controlled Folder
    Access blocks unrecognised binaries from writing there, silently, which looks exactly
    like the proxy never starting. Falls back to TEMP so there is always somewhere to log."""
    for cand in (preferred,
                 r"C:\ProgramData\GreenGate" if os.name == "nt" else None,
                 os.path.join(os.environ.get("TEMP") or "/tmp", "GreenGate")):
        if not cand:
            continue
        try:
            os.makedirs(cand, exist_ok=True)
            probe = os.path.join(cand, ".write-test")
            with open(probe, "w") as f:
                f.write("x")
            os.remove(probe)
            return cand
        except Exception:
            continue
    return HERE

try:
    # utf-8-sig, not utf-8: Windows PowerShell 5.1's Set-Content -Encoding UTF8 writes a
    # BOM, and a plain utf-8 read then fails on the very first character - the config is
    # silently discarded, sheetId comes back empty and everything is blocked.
    with open(os.path.join(HERE, "greengate.json"), encoding="utf-8-sig") as f:
        _user_cfg = json.load(f)
    _ul = dict(DEFAULTS["urlLog"]); _ul.update(_user_cfg.pop("urlLog", {}) or {})
    CFG.update(_user_cfg); CFG["urlLog"] = _ul
    CFG["_configLoaded"] = True
except FileNotFoundError:
    CFG["_configError"] = "greengate.json not found in " + HERE
except Exception as e:
    CFG["_configError"] = "greengate.json is malformed: %s" % e

DATA = _pick_data_dir(CFG.get("dataDir"))

GLOBAL = "*"          # the whole-internet budget, written as a "*" row in the sheet

YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtubei.googleapis.com"}
HEADERS = {"site", "sites", "website", "websites", "domain", "domains", "url", "urls", "channel", "channels", "kênh", "trang", "trang web",
           "blocked", "chặn", "bị chặn", "trang bị chặn", "trang chặn", "app", "apps", "ứng dụng", "gói", "package", "tên", "key", "khoá", "khóa", "cài đặt", "setting", "settings"}
# never allowed, even as a dependency of a listed page
AD_HOSTS = ("doubleclick.net", "googlesyndication.com", "googleadservices.com", "adnxs.com", "adsrvr.org", "rubiconproject.com",
            "pubmatic.com", "openx.net", "criteo.com", "criteo.net", "taboola.com", "outbrain.com", "amazon-adsystem.com",
            "adsafeprotected.com", "moatads.com", "3lift.com", "casalemedia.com", "yieldmo.com", "sharethrough.com")
def is_ad_host(host):
    host = (host or "").lower()
    return any(host == a or host.endswith("." + a) for a in AD_HOSTS)
SYSTEM_USERS = {"system", "local service", "network service"}

def _log_path():
    """Never rely on the config for this. If greengate.json is missing or malformed there
    would be no log at all - and no way to find out why everything is being blocked."""
    return CFG.get("logFile") or os.path.join(DATA, "greengate.log")


# Writing to disk from the hooks is what made this unstable. Windows retries a blocked
# endpoint in a tight loop - activity.windows.com was refused 4,786 times in six minutes,
# peaking at 1,448 log lines in one minute - and every one of them opened, wrote and
# closed two files ON MITMPROXY'S SINGLE EVENT-LOOP THREAD. The proxy drowned in its own
# logging, stopped answering, and the watchdog restarted it, over and over.
# Hooks now only append to a buffer; one background thread does the I/O.
_log_buf = []
_log_buf_lock = threading.Lock()
_BLOCK_SUPPRESS = 60          # seconds to collapse an identical repeated block into a count
_block_seen = {}              # key -> [count since last emit, when last emitted]


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _log_buf_lock:
        if len(_log_buf) < 5000:              # a stuck flusher must not eat memory
            _log_buf.append(line)
    try:
        print("greengate:", msg)
    except Exception:
        pass          # no console under Task Scheduler -> stdout is an invalid handle


def log_repeating(key, msg):
    """For things that can arrive hundreds of times a second. Emits the first one, then
    counts the rest and emits a single summary when the window closes."""
    now = time.time()
    with _log_buf_lock:
        ent = _block_seen.get(key)
        if ent is None:
            _block_seen[key] = [0, now]
            emit = msg
        elif now - ent[1] >= _BLOCK_SUPPRESS:
            n = ent[0]
            _block_seen[key] = [0, now]
            emit = msg + (" (+%d lần nữa trong %ds qua)" % (n, _BLOCK_SUPPRESS) if n else "")
        else:
            ent[0] += 1
            return
    log(emit)


def _log_flush_now():
    """Write whatever is buffered right now.

    The buffer is what keeps a block storm off the event loop, but it also means
    the last couple of seconds vanish if the process is killed - precisely the
    seconds worth reading after a crash. Call this on the way out."""
    try:
        with _log_buf_lock:
            if not _log_buf:
                return
            lines, _log_buf[:] = list(_log_buf), []
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass


def _log_flusher():
    while True:
        time.sleep(2)
        try:
            with _log_buf_lock:
                if not _log_buf:
                    continue
                lines, _log_buf[:] = list(_log_buf), []
            with open(_log_path(), "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        except Exception:
            pass

# ---------------------------------------------------------------- lists
class Lists:
    domains: set = set()
    paths: list = []
    handles: set = set()
    ids: set = set()
    limits: dict = {}        # domain -> minutes allowed per day (0 / missing = unlimited)
    site_windows: dict = {}  # domain -> parsed time windows (column D of websites)
    blocked_domains: set = set()
    blocked_paths: list = []
    apps: list = []          # [{name, block, minutes, hours}] enforced by the agents
    settings = policy.Settings()
    keywords = policy.Keywords()
    windows: list = []       # parsed settings.schedule
    yt_mode = "channels"     # effective: channels | restricted | block | any
    sig = ""                 # fingerprint of the last published lists (log only on change)
    loaded = False
    last_ok = 0
    last_err = ""

if _shared.lists is None:
    _shared.lists = Lists()
L = _shared.lists
# mitmproxy hot-reloads this script when the file changes, but the shared object survives
# the reload. Give an instance created by an older version every attribute the new one has.
for _name, _val in vars(Lists).items():
    if not _name.startswith("_") and not callable(_val) and not hasattr(L, _name):
        setattr(L, _name, _val)
lock = _shared.lock

def sheet_id(value):
    """Accept a full spreadsheet link or a bare id and return the id."""
    v = (value or "").strip()
    m = re.search(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})", v)
    if m:
        return m.group(1)
    m = re.match(r"^([A-Za-z0-9_-]{20,})(?:[/?#].*)?$", v)   # id with /edit?usp=... attached
    return m.group(1) if m else ""


def sheet_csv_url(sid, tab, gids=None):
    """CSV for one tab BY NAME (survives the sheet being copied). See policy.sheet_tab_url:
    export-by-gid when the tab map is known, gviz otherwise."""
    return policy.sheet_tab_url(sid, tab, gids)


def sheet_tab_map(sid):
    """{tab: gid} read from /htmlview; the previous map when the page cannot be read now;
    None when it was never readable (then gviz by name is used)."""
    try:
        gids = policy.sheet_tab_gids(_fetch(policy.sheet_htmlview_url(sid)))
        if gids:
            _shared.gids = gids
            return gids
        log("sheet tab list: htmlview had no tab entries (reading tabs by name via gviz)")
    except Exception as e:
        log(f"sheet tab list: {e} (using the previous map or gviz)")
    return _shared.gids


def source_urls(gids=None):
    sid = sheet_id(CFG.get("sheetId"))
    sites, chans = CFG.get("sitesUrl") or "", CFG.get("channelsUrl") or ""
    if sid:
        sites = sites or sheet_csv_url(sid, CFG.get("sitesTab") or "websites", gids)
        chans = chans or sheet_csv_url(sid, CFG.get("channelsTab") or "youtube", gids)
    return sites, chans


def optional_tab_urls(gids=None):
    """settings / blocked / apps tabs. Without a tab map, gviz answers a request for a
    missing tab with the FIRST tab of the spreadsheet, so a probe for a tab name that cannot
    exist is fetched too and a tab is only trusted when its content differs from the probe."""
    sid = sheet_id(CFG.get("sheetId"))
    out = {"settings": CFG.get("settingsUrl") or "", "blocked": CFG.get("blockedUrl") or "",
           "apps": CFG.get("appsUrl") or "", "_probe": ""}
    if sid:
        out["settings"] = out["settings"] or sheet_csv_url(sid, CFG.get("settingsTab") or "settings", gids)
        out["blocked"] = out["blocked"] or sheet_csv_url(sid, CFG.get("blockedTab") or "blocked", gids)
        out["apps"] = out["apps"] or sheet_csv_url(sid, CFG.get("appsTab") or "apps", gids)
        if gids is None:
            out["_probe"] = sheet_csv_url(sid, "__greengate_no_such_tab__")
    return out


class RateLimited(Exception):
    pass


def _fetch(url):
    opener = policy.direct_opener()  # never via ourselves; OS trust store + certifi (policy.https_handler)
    req = urllib.request.Request(url, headers={"User-Agent": "greengate/" + VERSION, "Cache-Control": "no-cache"})
    try:
        with opener.open(req, timeout=30) as r:
            return r.read().decode("utf-8-sig", "replace")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimited("Google từ chối vì đọc quá nhanh (429)")
        raise


def _rows(text):
    return [r for r in csv.reader(io.StringIO(text)) if r and any(c.strip() for c in r)]


def _not_a_rule(v):
    """Column A cells that are no site / app / channel: blank, comment, a known header word,
    or any header the parent wrote themselves (contains whitespace or brackets; a domain,
    package, exe or @handle never does). SPEC §1: the first row is a header."""
    return not v or v.startswith("#") or v.lower() in HEADERS or bool(re.search(r"[\s(\[]", v))


def _blocked_list(text):
    """blocked tab: column A, same grammar as websites (domain or domain/path)."""
    doms, paths = set(), []
    for v in _first_col(text):
        k, d = _norm_site(v)
        (doms.add(d) if k == "domain" else paths.append(d))
    return doms, paths


def _apps_list(text):
    """apps tab: A package/exe, B 'chặn' or minutes, C hours."""
    out = []
    for row in _rows(text):
        name = (row[0] or "").strip()
        if _not_a_rule(name):
            continue
        rule = (row[1] if len(row) > 1 else "").strip().lower()
        hours = (row[2] if len(row) > 2 else "").strip()
        mins = _parse_minutes(rule) if rule and not re.search(r"ch[aặ]n|block|cấm|cam", rule) else 0
        block = bool(rule) and not mins
        try:
            timewindow.parse(hours)
        except ValueError as e:
            log(f"apps: {name}: {e}")
            hours = ""
        out.append({"name": name.lower(), "block": block, "minutes": mins, "hours": hours})
    return out

def _first_col(text):
    out = []
    for row in csv.reader(io.StringIO(text)):
        if not row: continue
        v = row[0].strip()
        if _not_a_rule(v): continue
        out.append(v)
    return out

def _parse_minutes(cell):
    """Column C of the websites tab -> minutes. '30' and '30 phút' are 30 minutes; '1h',
    '1 giờ' and '60' are an hour; '1:30' and '1h30' are 90. Blank or 0 means no limit."""
    c = (cell or "").strip().lower()
    if not c:
        return 0
    m = re.match(r"^(\d+)\s*[:h]\s*(\d+)\s*$", c)
    if m:
        return int(m.group(1)) * 60 + int(m.group(2))
    m = re.search(r"(\d+(?:[.,]\d+)?)", c)
    if not m:
        return 0
    n = float(m.group(1).replace(",", "."))
    unit = c[m.end():]                     # only what FOLLOWS the number is the unit:
    if re.search(r"ph[uú]t|min", unit):    # "30 phút" must not read as hours because of its h
        pass
    elif re.search(r"gi[ờo]|hour|h", unit):
        n *= 60
    return int(round(n))


def _sites_with_limits(text):
    """-> (sites, limits, site_windows). Column C = minutes/day, column D = hours (§3)."""
    sites, limits, windows = [], {}, {}
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        v = row[0].strip()
        if _not_a_rule(v):
            continue
        mins = _parse_minutes(row[2] if len(row) > 2 else "")
        hours = (row[3] if len(row) > 3 else "").strip()
        win = []
        if hours:
            try:
                win = timewindow.parse(hours)
            except ValueError as e:
                log(f"websites: {v}: {e}")
        if v.strip() in ("*", "**"):        # the whole-internet budget, not a site
            if mins:
                limits[GLOBAL] = mins
            continue
        sites.append(v)
        kind, dom = _norm_site(v)
        if kind == "domain":
            if mins:
                limits[dom] = mins
            if win:
                windows[dom] = win
    return sites, limits, windows


def _norm_site(s):
    s = s.strip().lower()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^\*\.?", "", s)
    s = re.sub(r"^www\.", "", s)
    if "/" in s.rstrip("/"):
        return ("path", s.rstrip("/"))
    return ("domain", s.strip("/"))

def _norm_channel(s):
    s = s.strip()
    s = re.sub(r"^https?://(www\.|m\.)?youtube\.com/", "", s, flags=re.I)
    s = re.sub(r"^channel/", "", s, flags=re.I)
    s = re.sub(r"[/?#].*$", "", s)
    if re.match(r"^UC[\w-]{20,}$", s): return ("id", s)
    return ("handle", s.lstrip("@").lower())

_ID_CACHE_FILE = os.path.join(DATA, "channel-ids.json")
_id_cache = {}
_id_fail = {}            # handle -> when resolution last failed
_ID_FAIL_TTL = 6 * 3600
try:
    with open(_ID_CACHE_FILE, encoding="utf-8") as f: _id_cache = json.load(f)
except Exception:
    pass

def _save_id_cache():
    """Once per refresh. Rewriting it per handle churns a file next to the script,
    which makes mitmproxy reload the addon mid-load."""
    try:
        tmp = _ID_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(_id_cache, f)
        os.replace(tmp, _ID_CACHE_FILE)
    except Exception as e:
        log(f"channel id cache write failed: {e}")


def resolve_handle(handle):
    """@handle -> UC... channel id via YouTube's own URL resolver (cached on disk).

    Some handles (seen with @codeorg) come back as a bare urlEndpoint pointing at
    "youtube.com/<legacy-name>" instead of a browseEndpoint - the resolver knows the
    handle exists but does not hand back its id directly. Falling back to fetching the
    channel page itself and reading its externalId covers those."""
    h = handle.lower()
    if h in _id_cache: return _id_cache[h]
    if time.time() - _id_fail.get(h, 0) < _ID_FAIL_TTL: return None   # don't retry a dud every refresh
    opener = policy.direct_opener()   # OS trust store + certifi, never via ourselves
    try:
        body = json.dumps({"context": {"client": {"clientName": "WEB", "clientVersion": "2.20240101.00.00"}},
                           "url": f"https://www.youtube.com/@{handle}"}).encode()
        req = urllib.request.Request("https://www.youtube.com/youtubei/v1/navigation/resolve_url?prettyPrint=false",
                                     data=body, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=8) as r:
            cid = (json.load(r).get("endpoint") or {}).get("browseEndpoint", {}).get("browseId")
        if cid and cid.startswith("UC"):
            _id_cache[h] = cid
            return cid
    except Exception as e:
        log(f"resolve @{handle} failed: {e}")
        _id_fail[h] = time.time()
        return None
    try:
        req = urllib.request.Request(f"https://www.youtube.com/@{handle}", headers={"User-Agent": "Mozilla/5.0"})
        with opener.open(req, timeout=8) as r:
            html = r.read().decode("utf-8", "replace")
        m = re.search(r'"externalId":"(UC[\w-]+)"', html)
        if m:
            _id_cache[h] = m.group(1)
            return m.group(1)
        log(f"resolve @{handle}: no channel id in response or page")
    except Exception as e:
        log(f"resolve @{handle} page fallback failed: {e}")
    _id_fail[h] = time.time()
    return None

def refresh():
    sid = sheet_id(CFG.get("sheetId"))
    gids = sheet_tab_map(sid) if sid else None
    sites_url, chans_url = source_urls(gids)
    if not sites_url:
        L.last_err = "no sheet configured" if not sid else "sheet has no 'websites' tab"
        log("no sheet configured (sheetId is empty) - everything stays blocked" if not sid
            else "the sheet has no 'websites' tab - everything stays blocked")
        return
    opt = optional_tab_urls(gids)
    try:
        sites_text = _fetch(sites_url)
        sites, limits, site_windows = _sites_with_limits(sites_text)
        chans_text = _fetch(chans_url) if chans_url else ""
        probe = _fetch(opt["_probe"]) if opt["_probe"] else None
        texts = {}
        for name in ("settings", "blocked", "apps"):
            texts[name] = _fetch(opt[name]) if opt[name] else ""
    except RateLimited as e:
        L.last_err = str(e)
        _shared.backoff = min(900, (_shared.backoff or 60) * 2)
        log(f"list refresh: {e} - slowing down to every {_shared.backoff}s")
        return
    except Exception as e:
        L.last_err = str(e)
        log(f"list refresh failed: {e} (keeping previous list)")
        return
    _shared.backoff = 0
    # A tab that gviz answered with the first tab's content does not exist.
    def present(name, text, check=None):
        if not text:
            return False
        if probe is not None and text == probe and not (check and check(_rows(text))):
            return False
        if text == sites_text and name != "websites" and not (check and check(_rows(text))):
            return False
        return True
    chans = _first_col(chans_text) if present("youtube", chans_text) else []
    settings = (policy.parse_settings(_rows(texts["settings"]))
                if present("settings", texts["settings"], policy.looks_like_settings) else policy.Settings())
    for err in settings.errors:
        log("settings: " + err)
    blocked_d, blocked_p = _blocked_list(texts["blocked"]) if present("blocked", texts["blocked"]) else (set(), [])
    apps = _apps_list(texts["apps"]) if present("apps", texts["apps"]) else []
    try:
        windows = timewindow.parse(settings.schedule)
    except ValueError as e:
        log(f"settings: schedule: {e} - ignored")
        windows = []
    d, p, h, i = set(), [], set(), set()
    for s_ in sites:
        k, v = _norm_site(s_)
        (d.add(v) if k == "domain" else p.append(v))
    for c in chans:
        k, v = _norm_channel(c)
        (i.add(v) if k == "id" else h.add(v))
    extra = {"settings": settings, "blocked": (blocked_d, blocked_p), "apps": apps,
             "windows": windows, "site_windows": site_windows,
             "keywords": policy.Keywords(settings.keywords_extra, settings.keywords_default)}
    # Publish the site list FIRST. host_allowed() fails closed until the first publish, and
    # resolving @handles costs a network round trip each - doing that first left every site
    # blocked for a minute after every start, watchdog restart and reboot.
    _publish(d, p, h, i, limits, extra)
    added = False
    for hd in sorted(h):
        cid = resolve_handle(hd)
        if cid and cid not in i:
            i.add(cid); added = True
    if added:
        _save_id_cache()
        _publish(d, p, h, i, limits, extra)
    # Category lists: enable what the settings ask for, download what is missing or a day old.
    if _shared.cats is not None:
        _shared.cats.set_enabled(settings.effective_categories())
        _shared.cats.refresh()


def _publish(d, p, h, i, limits=None, extra=None):
    # hosts needed to keep the sheet itself, the YouTube player and bot checks (which send no referer) working
    dd = set(d)
    for e_ in ("docs.google.com", "googleusercontent.com", "googlevideo.com", "ytimg.com", "ggpht.com", "gstatic.com", "googleapis.com",
               "challenges.cloudflare.com", "recaptcha.net"):
        dd.add(e_)
    for e_ in (CFG.get("alwaysAllow") or []):          # e.g. the relay host
        dd.add(e_.lower())
    if h or i:
        dd.update({"youtube.com", "youtube-nocookie.com"})
    settings = (extra or {}).get("settings") or L.settings
    yt_mode = settings.effective_youtube(bool(h or i))
    with lock:
        L.domains, L.paths, L.handles, L.ids = dd, list(p), set(h), set(i)
        if limits is not None:
            L.limits = dict(limits)
        if extra:
            L.settings = settings
            L.blocked_domains, L.blocked_paths = extra["blocked"]
            L.apps = extra["apps"]
            L.windows = extra["windows"]
            L.site_windows = extra["site_windows"]
            L.keywords = extra["keywords"]
        L.yt_mode = yt_mode
        L.loaded, L.last_ok, L.last_err = True, time.time(), ""
        sig = json.dumps([sorted(dd), sorted(p), sorted(h), sorted(i), sorted((limits or L.limits).items()),
                          sorted(L.blocked_domains), L.blocked_paths, L.apps, settings.to_dict(),
                          {k: str(v) for k, v in L.site_windows.items()}], sort_keys=True, default=str)
        changed = sig != L.sig
        L.sig = sig
    if not changed:
        return
    lim = " ".join("%s=%dm" % kv for kv in sorted((limits or L.limits).items()))
    log(f"lists loaded: {len(dd)} domains, {len(p)} paths, {len(h)} handles, {len(i)} channel ids, "
        f"{len(L.blocked_domains)} blocked, {len(L.apps)} apps; mode={settings.mode} youtube={yt_mode} "
        f"safesearch={'on' if settings.safesearch else 'off'} categories={','.join(settings.effective_categories()) or '-'}"
        + ("" if settings.deepInspect else " deepInspect=off (listed sites tunnelled)")
        + (f", schedule={settings.schedule}" if settings.schedule else "")
        + (f", limits: {lim}" if lim else ""))

# ---------------------------------------------------------------- URL log
KEEP_PARAMS = ("v", "list", "q", "search_query")
_local_log_lock = threading.Lock()
MAX_DAYS = 31


class Counts:
    """tab -> url -> {day: hits}, persisted locally. The viewer reads it directly;
    pushing it to Google Sheets is optional and layered on top."""

    def __init__(self, path, log=print):
        self.path, self.log = path, log
        self.lock = threading.Lock()
        self.totals, self.rows, self.dirty = {}, {}, {}
        try:
            with open(path, encoding="utf-8") as f:
                st = json.load(f)
            self.totals, self.rows = st.get("totals", {}), st.get("rows", {})
        except Exception:
            pass

    def record(self, tab, url, day):
        with self.lock:
            t = self.totals.setdefault(tab, {}).setdefault(url, {})
            k = str(day)
            t[k] = t.get(k, 0) + 1
            self.dirty.setdefault(tab, set()).add(day)

    def save(self):
        try:
            with self.lock:
                blob = json.dumps({"totals": self.totals, "rows": self.rows}, ensure_ascii=False)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(blob)
            os.replace(tmp, self.path)
        except Exception as e:
            self.log(f"url log: cannot save counts: {e}")

    def months(self):
        with self.lock:
            return sorted({t[:7] for t in self.totals}, reverse=True)

    def grid(self, tab):
        """[(url, {day: n}, total)] sorted by total, busiest first."""
        with self.lock:
            rows = [(u, dict(d), sum(d.values())) for u, d in self.totals.get(tab, {}).items()]
        return sorted(rows, key=lambda r: (-r[2], r[0]))


def _log_url(req):
    """Row key: host + path, keeping only the query params that identify a page."""
    base = req.host.lower() + (req.path.split("?")[0].rstrip("/") or "/")
    kept = []
    if "?" in req.path:
        for k, v in urllib.parse.parse_qsl(req.path.split("?", 1)[1]):
            if k in KEEP_PARAMS and v:
                kept.append((k, v[:80]))
    if kept:
        base += "?" + urllib.parse.urlencode(kept)
    return base[:400]


_jsonl_buf = []


def _local_append(rec):
    """Buffered for the same reason as log(): this ran once per request, on the event
    loop, and a blocked endpoint retrying in a loop turned it into a disk storm."""
    if not CFG["urlLog"].get("localFile") and not CFG["urlLog"].get("enabled"):
        return
    with _local_log_lock:
        if len(_jsonl_buf) < 20000:
            _jsonl_buf.append(rec)


def _local_log_path():
    """urlLog.localFile: a path, or true for <dataDir>/urls.jsonl. Anything else falls back
    to the default too - open(True) would wrap fd 1, and closing it took stdout away from
    mitmproxy, which then failed every connection in its own log handler."""
    lf = CFG["urlLog"].get("localFile")
    return lf if isinstance(lf, str) and lf.strip() else os.path.join(DATA, "urls.jsonl")


def _jsonl_flusher():
    while True:
        time.sleep(5)
        try:
            with _local_log_lock:
                if not _jsonl_buf:
                    continue
                recs, _jsonl_buf[:] = list(_jsonl_buf), []
            path = _local_log_path()
            cap = int(CFG["urlLog"].get("localMaxMB", 20)) * 1024 * 1024
            if cap and os.path.exists(path) and os.path.getsize(path) > cap:
                os.replace(path, path + ".1")     # keep one generation, never grow forever
            with open(path, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
        except Exception:
            pass


def record_url(flow, blocked, user=None, nav=None):
    ul = CFG["urlLog"]
    if not ul.get("enabled") and not ul.get("localFile"):
        return
    try:
        req = flow.request
        if nav is None:
            dest = req.headers.get("sec-fetch-dest", "").lower()
            nav = dest in NAV_DESTS or not dest
        url = _log_url(req)
        now = time.localtime()
        _local_append({"t": time.strftime("%Y-%m-%d %H:%M:%S", now), "user": user, "url": url,
                       "blocked": bool(blocked), "nav": bool(nav)})
        if _shared.counts is None or not (nav or ul.get("sheetAllRequests")):
            return
        tab = time.strftime("%m-%Y", now)
        _shared.counts.record(tab + " chan" if blocked else tab, url, now.tm_mday)
    except Exception as e:
        log(f"url log error: {e}")


def _url_log_flusher():
    every = max(60, int(CFG["urlLog"].get("flushSeconds", 300)))
    while True:
        time.sleep(every)
        try:
            n = _shared.sheet.flush()
            if n:
                log(f"url log: pushed {n} rows")
        except Exception as e:
            log(f"url log push failed: {e} (kept locally, will retry)")


def _start_url_log():
    ul = CFG["urlLog"]
    if not ul.get("enabled"):
        return
    with _shared.start_lock:
        if _shared.urllog:
            return
        _shared.urllog = True
    _shared.counts = Counts(os.path.join(DATA, "urllog-state.json"), log)
    threading.Thread(target=_counts_saver, daemon=True).start()
    log("url log: on - http://greengate.local/log")

    # Optional: also mirror it into a Google Sheet. Drop a service-account key in and
    # set sheetId to turn this on later; nothing else changes.
    if not ul.get("sheetId"):
        return
    cred = ul.get("credentials") or ""
    if not os.path.isabs(cred):
        cred = os.path.join(HERE, cred)
    if not os.path.exists(cred):
        log(f"url log: sheet mirror off, no key at {cred}")
        return
    try:
        sys.path.insert(0, HERE)
        from sheetlog import SheetLog
        _shared.sheet = SheetLog(ul["sheetId"], cred, _shared.counts, log)
    except Exception as e:
        log(f"url log: sheet mirror off ({e})")
        return
    threading.Thread(target=_url_log_flusher, daemon=True).start()
    log(f"url log: mirroring to sheet {ul['sheetId']} every {ul.get('flushSeconds')}s")


def _usage_saver():
    while True:
        time.sleep(60)
        if _shared.usage is not None:
            _shared.usage.save()


def _counts_saver():
    while True:
        time.sleep(60)
        if _shared.counts is not None:
            _shared.counts.save()


# ---------------------------------------------------------------- manual refresh
CONTROL_HOSTS = {"greengate", "greengate.local"}
CONTROL_MIN_INTERVAL = 10
_last_manual = [0.0]

CONTROL_HTML = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>GreenGate</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<body style="margin:0;font-family:system-ui,sans-serif;background:#f4f5f7;display:flex;align-items:center;justify-content:center;min-height:100vh">
<div style="background:#fff;padding:36px 44px;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:620px">
<h1 style="font-size:20px;margin:0 0 8px">{title}</h1>
<p style="color:#555;margin:0 0 18px">{sub}</p>
<pre style="background:#f7f8fa;border-radius:8px;padding:14px;font-size:13px;color:#333;margin:0 0 18px;white-space:pre-wrap">{stats}</pre>
<a href="http://greengate.local/update" style="display:inline-block;background:#1a73e8;color:#fff;text-decoration:none;padding:10px 18px;border-radius:8px">Cập nhật lại</a>
</div></body></html>"""


def _usage_lines():
    """[(user, domain, used, cap)] - every budget, for every account that used one."""
    with lock:
        caps = dict(L.limits)
    if not caps or _shared.usage is None:
        return []
    today = _shared.usage.today()
    rows = []
    for who in sorted(today) or [""]:
        for d, c in sorted(caps.items()):
            rows.append((who, d, today.get(who, {}).get(d, 0), c))
    return rows


def _control_stats():
    with lock:
        n_d, n_p, n_i, ok, err = len(L.domains), len(L.paths), len(L.ids), L.last_ok, L.last_err
    with lock:
        mode, yt, nb, cats = L.settings.mode, L.yt_mode, len(L.blocked_domains) + len(L.blocked_paths), L.settings.effective_categories()
    lines = ["Chế độ              : %s" % ("chỉ cho phép danh sách (whitelist)" if mode == "whitelist" else "cho phép tất cả, trừ danh sách chặn (blacklist)"),
             "Trang web được phép : %d tên miền%s" % (n_d, " + %d đường dẫn" % n_p if n_p else ""),
             "Trang bị chặn       : %d%s" % (nb, (" + danh mục " + ",".join(cats)) if cats else ""),
             "Kênh YouTube        : %d (chế độ %s)" % (n_i, yt),
             "Cập nhật lần cuối   : %s" % (
                 time.strftime("%H:%M:%S", time.localtime(ok)) + " (%ds trước)" % int(time.time() - ok)
                 if ok else "chưa lần nào")]
    if err:
        lines.append("Lỗi                 : %s" % err)
    for who, d, used, cap in _usage_lines():
        lines.append("%-10s %-16s: %d/%d phút hôm nay"
                     % (who, "TẤT CẢ" if d == GLOBAL else d, used, cap))
    return "\n".join(lines)



LOG_HTML = """<!doctype html><html lang="vi"><meta charset="utf-8"><title>GreenGate - nhật ký</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
 body{{margin:0;font-family:system-ui,sans-serif;background:#f4f5f7;color:#222;padding:24px}}
 h1{{font-size:20px;margin:0 0 4px}} h2{{font-size:15px;margin:28px 0 8px}}
 .sub{{color:#666;font-size:13px;margin:0 0 16px}}
 .m a{{display:inline-block;margin:0 6px 6px 0;padding:5px 11px;border-radius:7px;background:#fff;
      border:1px solid #dcdfe4;color:#1a73e8;text-decoration:none;font-size:13px}}
 .m a.on{{background:#1a73e8;color:#fff;border-color:#1a73e8}}
 .wrap{{overflow-x:auto;background:#fff;border-radius:10px;box-shadow:0 1px 4px rgba(0,0,0,.07)}}
 table{{border-collapse:collapse;font-size:13px;width:100%}}
 th,td{{padding:6px 9px;border-bottom:1px solid #eef0f2;text-align:right;white-space:nowrap}}
 th:first-child,td:first-child{{text-align:left;position:sticky;left:0;background:#fff;
      max-width:520px;overflow:hidden;text-overflow:ellipsis}}
 thead th{{background:#fafbfc;position:sticky;top:0;font-weight:600;color:#555}}
 td.z{{color:#dfe2e6}} .tot{{font-weight:600}} .today{{background:#fff7e6}}
 .none{{color:#777;font-size:13px;padding:14px}}
 .bar{{margin:0 0 18px}} .bar a{{color:#1a73e8;font-size:13px;margin-right:14px}}
</style>
<body>
<h1>Nhật ký truy cập</h1>
<p class="sub">Mỗi dòng là một trang, mỗi cột là một ngày trong tháng.</p>
<div class="m">{months}</div>
<div class="bar"><a href="http://greengate.local/log.csv?m={month}">Tải CSV tháng này</a>
<a href="http://greengate.local/update">Cập nhật danh sách</a></div>
{tables}
</body></html>"""


def _esc(t):
    return (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def _log_table(tab, today):
    rows = _shared.counts.grid(tab) if _shared.counts else []
    if not rows:
        return '<div class="wrap"><div class="none">Chưa có dữ liệu.</div></div>'
    days = sorted({int(d) for _, dd, _ in rows for d in dd})
    head = "".join('<th class="%s">%d</th>' % ("today" if d == today else "", d) for d in days)
    body = []
    for url, dd, total in rows:
        cells = "".join('<td class="%s">%s</td>' % (
            ("today " if d == today else "") + ("" if dd.get(str(d)) else "z"),
            dd.get(str(d), "\u00b7")) for d in days)
        body.append("<tr><th>%s</th>%s<td class='tot'>%d</td></tr>" % (_esc(url), cells, total))
    return ('<div class="wrap"><table><thead><tr><th>URL</th>%s<th>Tổng</th></tr></thead>'
            "<tbody>%s</tbody></table></div>" % (head, "".join(body)))


def log_page(query):
    now = time.localtime()
    cur = time.strftime("%m-%Y", now)
    want = (urllib.parse.parse_qs(query).get("m") or [cur])[0]
    have = _shared.counts.months() if _shared.counts else []
    if cur not in have:
        have = [cur] + have
    if want not in have:
        want = have[0]
    months = "".join('<a class="%s" href="http://greengate.local/log?m=%s">%s</a>'
                     % ("on" if m == want else "", m, m) for m in have)
    today = now.tm_mday if want == cur else -1
    budget = ""
    rows = _usage_lines() if want == cur else []
    if rows:
        budget = ("<h2>Thời gian hôm nay</h2><div class='wrap'><table><thead><tr>"
                  "<th>Tài khoản</th><th>Trang</th><th>Đã dùng</th><th>Giới hạn</th>"
                  "<th>Còn lại</th></tr></thead><tbody>"
                  + "".join("<tr><th>%s</th><td style='text-align:left'>%s</td>"
                            "<td>%d</td><td>%d</td><td class='tot'>%d</td></tr>"
                            % (_esc(w), _esc("TẤT CẢ" if d == GLOBAL else d), u, c, max(0, c - u))
                            for w, d, u, c in rows)
                  + "</tbody></table></div>")
    tables = (budget + "<h2>Đã vào</h2>" + _log_table(want, today) +
              "<h2>Bị chặn</h2>" + _log_table(want + " chan", today))
    body = LOG_HTML.format(months=months, month=want, tables=tables).encode("utf-8")
    return http.Response.make(200, body, {"Content-Type": "text/html; charset=utf-8",
                                          "Cache-Control": "no-store"})


def log_csv(query):
    want = (urllib.parse.parse_qs(query).get("m") or [time.strftime("%m-%Y")])[0]
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Loại", "URL"] + [str(d) for d in range(1, MAX_DAYS + 1)] + ["Tổng"])
    for label, tab in (("Đã vào", want), ("Bị chặn", want + " chan")):
        for url, dd, total in (_shared.counts.grid(tab) if _shared.counts else []):
            w.writerow([label, url] + [dd.get(str(d), "") for d in range(1, MAX_DAYS + 1)] + [total])
    return http.Response.make(200, out.getvalue().encode("utf-8-sig"),
                              {"Content-Type": "text/csv; charset=utf-8",
                               "Content-Disposition": 'attachment; filename="greengate-%s.csv"' % want,
                               "Cache-Control": "no-store"})


def status_json():
    """Machine-readable state for the agent and the self-test (docs/SPEC.md §6)."""
    with lock:
        st = {"version": VERSION, "sheet": sheet_id(CFG.get("sheetId")) or "", "mode": L.settings.mode, "youtube": L.yt_mode,
              "safesearch": L.settings.safesearch, "shorts": L.settings.shorts,
              "schedule": L.settings.schedule,
              "scheduleOpen": timewindow.allowed(L.windows, time.localtime().tm_wday,
                                                 time.localtime().tm_hour * 60 + time.localtime().tm_min),
              "domains": len(L.domains), "paths": len(L.paths), "handles": len(L.handles), "channelIds": len(L.ids),
              "blocked": len(L.blocked_domains) + len(L.blocked_paths), "apps": list(L.apps),
              "limits": dict(L.limits), "loaded": L.loaded, "lastOk": L.last_ok, "lastError": L.last_err,
              "refreshSeconds": L.settings.refreshSeconds, "settings": L.settings.to_dict(),
              "screenshotEvery": L.settings.screenshotEvery, "retentionDays": L.settings.retentionDays,
              "enforceUsers": CFG.get("enforceUsers"), "exemptUsers": CFG.get("exemptUsers")}
    st["categories"] = _shared.cats.status() if _shared.cats is not None else {}
    st["usage"] = [{"user": w, "site": d, "used": u, "cap": c} for w, d, u, c in _usage_lines()]
    st["updating"] = bool(_shared.update_running)
    return http.Response.make(200, json.dumps(st, ensure_ascii=False).encode("utf-8"),
                              {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
                               "Access-Control-Allow-Origin": "*"})


def control_response(path, accept=""):
    p = path.split("?")[0].rstrip("/") or "/"
    q = path.split("?", 1)[1] if "?" in path else ""
    if p in ("/status.json", "/status"):
        return status_json()
    if p == "/log":
        return log_page(q)
    if p in ("/log.csv", "/logcsv"):
        return log_csv(q)
    if p in ("/update", "/refresh"):
        now = time.time()
        waited = now - _last_manual[0]
        if _shared.update_running:
            # Do not drop the request: the running refresh may have read the Sheet
            # before the parent's edit landed. Run once more as soon as it finishes.
            _shared.update_pending = True
            title = "Đang cập nhật..."
            sub = "Một lần cập nhật khác đang chạy nền; sẽ tải lại thêm một lần nữa ngay khi xong."
        elif waited < CONTROL_MIN_INTERVAL:
            title = "Vừa cập nhật xong"
            sub = "Đợi %d giây rồi bấm lại." % (CONTROL_MIN_INTERVAL - int(waited))
        else:
            # refresh() can take many seconds (network round trips per YouTube handle,
            # up to 16s each on a failure). request() runs on mitmproxy's single event
            # loop - calling refresh() here directly would freeze EVERY connection
            # through the proxy, for every account, until it returns. That is exactly
            # what happened: "greengate update" blocked the whole household's internet.
            # Run it on its own thread instead, same as the periodic background refresh.
            _last_manual[0] = now
            _shared.update_running = True

            def _bg():
                try:
                    with lock:
                        before = set(L.domains)
                    while True:
                        _shared.update_pending = False
                        refresh()
                        if not _shared.update_pending:
                            break
                        log("update: chạy lại vì có yêu cầu mới trong lúc đang tải")
                    if _shared.sheet is not None:
                        try:
                            _shared.sheet.flush()
                        except Exception as e:
                            log(f"url log push failed: {e}")
                    with lock:
                        added = sorted(L.domains - before)
                    if added:
                        log("update: mới thêm " + ", ".join(added))
                finally:
                    _shared.update_running = False

            threading.Thread(target=_bg, daemon=True).start()
            title = "Đang cập nhật ở chế độ nền..."
            sub = "Không chặn trang nào khác trong lúc này. Mở lại /update hoặc /log sau vài giây để xem kết quả."
    else:
        title, sub = "GreenGate", "/update để tải lại danh sách, /log để xem nhật ký truy cập."
    stats = _control_stats()
    if "text/html" in (accept or "").lower():
        body = CONTROL_HTML.format(title=title, sub=sub, stats=stats).encode("utf-8")
        ct = "text/html; charset=utf-8"
    else:
        body = ("%s\n%s\n\n%s\n" % (title, sub, stats)).encode("utf-8")
        ct = "text/plain; charset=utf-8"
    return http.Response.make(200, body, {"Content-Type": ct, "Cache-Control": "no-store"})



def _refresher():
    # At boot the network is often not up yet. refresh() keeps the previous list on failure,
    # but before the FIRST success there is no list and host_allowed() fails closed - so retry
    # quickly until we have one instead of waiting out a full refresh interval.
    delay = 5
    while True:
        try:
            refresh()
        except Exception as e:
            log(f"refresh crashed: {e}")
        with lock:
            loaded = L.loaded
        if loaded:
            delay = 5
            with lock:
                every = L.settings.refreshSeconds if L.settings.raw.get("refreshSeconds") else int(CFG["refreshSeconds"])
            time.sleep(max(30, every, _shared.backoff))
        else:
            log(f"no list yet, retrying in {delay}s")
            time.sleep(delay)
            delay = min(delay * 2, 120)


class Usage:
    """Which minutes of the day each account spent on each limited site, plus a "*" total
    across everything. A minute counts once however many requests it held, and it is
    counted PER ACCOUNT - one child running out does not spend another's allowance.

    A minute only counts once it looks like real use: a page navigation, or enough
    requests to rule out a background tab polling while nobody is at the machine."""

    VERSION = 2

    def __init__(self, path, log=print):
        self.path, self.log = path, log
        self.lock = threading.Lock()
        self.days = {}          # day -> user -> domain -> set(minute-of-day)
        self._pending = {}      # (day, user, domain, minute) -> requests seen so far
        try:
            with open(path, encoding="utf-8-sig") as f:
                blob = json.load(f)
            if blob.get("v") == self.VERSION:       # v1 had no per-user dimension
                for day, users in (blob.get("days") or {}).items():
                    self.days[day] = {u: {k: set(v) for k, v in doms.items()}
                                      for u, doms in users.items()}
        except Exception:
            pass

    # ------------------------------------------------------------------ reads
    def used(self, day, user, domain):
        with self.lock:
            return len(self.days.get(day, {}).get(user, {}).get(domain, ()))

    def has(self, day, user, domain, minute):
        with self.lock:
            return minute in self.days.get(day, {}).get(user, {}).get(domain, ())

    def today(self):
        """{user: {domain: minutes}} for today."""
        day = time.strftime("%Y-%m-%d")
        with self.lock:
            return {u: {k: len(v) for k, v in doms.items()}
                    for u, doms in self.days.get(day, {}).items()}

    # ------------------------------------------------------------------ writes
    def touch(self, day, user, domain, minute):
        with self.lock:
            self.days.setdefault(day, {}).setdefault(user, {}).setdefault(domain, set()).add(minute)

    def note(self, day, user, domain, minute, nav, threshold):
        """Count this minute once it is clearly someone using the machine."""
        if self.has(day, user, domain, minute):
            return
        key = (day, user, domain, minute)
        with self.lock:
            seen = self._pending.get(key, 0) + 1
            self._pending[key] = seen
        if nav or seen >= max(1, threshold):
            self.touch(day, user, domain, minute)
            with self.lock:
                self._pending.pop(key, None)

    def save(self):
        keep = {time.strftime("%Y-%m-%d"), time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))}
        try:
            with self.lock:
                for stale in [d for d in self.days if d not in keep]:
                    del self.days[stale]
                for k in [k for k in self._pending if k[0] not in keep]:
                    del self._pending[k]
                blob = json.dumps({"v": self.VERSION, "days": {
                    d: {u: {k: sorted(v) for k, v in doms.items()} for u, doms in users.items()}
                    for d, users in self.days.items()}})
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(blob)
            os.replace(tmp, self.path)
        except Exception as e:
            self.log(f"usage: cannot save: {e}")


def matched_domain(host):
    """Which allowlist domain this host falls under, if any."""
    host = (host or "").lower().rstrip(".")
    with lock:
        for d in L.domains:
            if host == d or host.endswith("." + d):
                return d
    return None


def req_host(flow) -> str:
    """The hostname a request is for. Regular proxy mode (Windows): the CONNECT/URL host. Transparent
    mode (Linux): request.host is only the destination IP, so prefer the TLS SNI the client sent
    (cannot be faked separately from the certificate it then expects), then the Host header."""
    h = flow.request.host or ""
    if h and not _is_ip(h):
        return h
    sni = getattr(getattr(flow, "client_conn", None), "sni", None)
    if sni:
        return sni
    return flow.request.pretty_host or h


def _is_ip(h: str) -> bool:
    try:
        ipaddress.ip_address(h.strip("[]"))
        return True
    except ValueError:
        return False


def limited_site(flow):
    """(domain, minutes) of the limited site this request belongs to. The referer wins, so
    the video stream on googlevideo.com counts against youtube.com, not against itself."""
    h = flow.request.headers
    ref = _hdr_host(h.get("referer", "")) or _hdr_host(h.get("origin", ""))
    for cand in (ref, req_host(flow)):
        if not cand:
            continue
        d = matched_domain(cand)
        if d:
            with lock:
                cap = L.limits.get(d, 0)
            if cap:
                return d, cap
    return None, 0


def host_allowed(host):
    host = (host or "").lower().rstrip(".")
    if host in ("localhost", "127.0.0.1", "::1"): return True
    with lock:
        if not L.loaded: return False  # fail closed until the first successful load
        for d in L.domains:
            if host == d or host.endswith("." + d): return True
    return False

def url_allowed(host, path):
    if host_allowed(host): return True
    hp = re.sub(r"^www\.", "", (host or "").lower()) + path
    with lock:
        return any(hp.startswith(p) for p in L.paths)

def channel_allowed(handle=None, cid=None):
    with lock:
        if handle and handle.lstrip("@").lower() in L.handles: return True
        if cid and cid in L.ids: return True
    return False

# hosts that were embedded (iframe) by a listed page; their own sub-resources are trusted for a while
_dyn = {}
def _dyn_allow(host):
    _dyn[host.lower()] = time.time() + int(CFG["dependencyTtlSeconds"])
def _dyn_ok(host):
    exp = _dyn.get((host or "").lower())
    return bool(exp and exp > time.time())

def _hdr_host(value):
    try:
        return (urllib.parse.urlsplit(value).hostname or "").lower()
    except Exception:
        return ""

NAV_DESTS = {"document"}
FRAME_DESTS = {"iframe", "frame", "embed", "object", "fencedframe"}
def smart_allowed(flow):
    """Smart mode. Only listed sites may be opened as a page (checked by the caller).
    - frames: allowed when embedded by a listed page (or by a frame that was itself allowed), and the
      frame's host is then trusted for a while so its own sub-resources load;
    - any other browser sub-resource (script, style, image, font, xhr, media, websocket...) is allowed,
      because it can only originate from a page that was itself allowed;
    - requests without Sec-Fetch-Dest (non-browser apps) and ad networks are never allowed this way."""
    if not CFG["smartDependencies"] or is_ad_host(req_host(flow)): return False
    h = flow.request.headers
    dest = h.get("sec-fetch-dest", "").lower()
    if not dest or dest in NAV_DESTS: return False
    if dest in FRAME_DESTS:
        ref = _hdr_host(h.get("referer", "")) or _hdr_host(h.get("origin", ""))
        if ref and (host_allowed(ref) or _dyn_ok(ref)):
            _dyn_allow(req_host(flow))
            return True
        return False
    return True

# ---------------------------------------------------------------- who is connecting?
_admins = {"__t": 0, "names": set()}
_pid_user = {}

def _local_admins():
    if time.time() - _admins["__t"] < 600: return _admins["names"]
    names = set()
    try:
        if platform.system() == "Windows":
            # by SID, because "Administrators" is translated on a localised Windows
            ps = (r"Get-LocalGroupMember -SID S-1-5-32-544 | "
                  r"ForEach-Object { ($_.Name -split '\\')[-1] }")
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                                 capture_output=True, text=True, timeout=20).stdout
            if not out.strip():
                out = subprocess.run(["net", "localgroup", "Administrators"],
                                     capture_output=True, text=True, timeout=10).stdout
            body = out.split("---", 2)[-1] if "---" in out else out
            for line in body.splitlines():
                l = line.strip()
                if l and not l.lower().startswith("the command") and not l.startswith("Lệnh"):
                    names.add(l.lower().split("\\")[-1])
        else:
            import grp
            for g in ("sudo", "admin", "wheel"):
                try: names.update(u.lower() for u in grp.getgrnam(g).gr_mem)
                except KeyError: pass
    except Exception as e:
        log(f"admin lookup failed: {e}")
    _admins["__t"], _admins["names"] = time.time(), names
    return names

def _pid_for_port_windows(port):
    import ctypes
    from ctypes import wintypes
    class ROW(ctypes.Structure):
        _fields_ = [("state", wintypes.DWORD), ("laddr", wintypes.DWORD), ("lport", wintypes.DWORD),
                    ("raddr", wintypes.DWORD), ("rport", wintypes.DWORD), ("pid", wintypes.DWORD)]
    iphlp = ctypes.WinDLL("iphlpapi", use_last_error=True)
    iphlp.GetExtendedTcpTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD),
                                          wintypes.BOOL, wintypes.ULONG,
                                          ctypes.c_int, wintypes.ULONG]
    iphlp.GetExtendedTcpTable.restype = wintypes.DWORD
    size = wintypes.DWORD(0)
    iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, 2, 5, 0)  # AF_INET=2, TCP_TABLE_OWNER_PID_ALL=5
    buf = ctypes.create_string_buffer(size.value)
    if iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, 2, 5, 0) != 0: return None
    n = ctypes.cast(buf, ctypes.POINTER(wintypes.DWORD))[0]
    rows = ctypes.cast(ctypes.addressof(buf) + 4, ctypes.POINTER(ROW * n))[0]
    fallback = None
    for r in rows:
        lport = ((r.lport & 0xFF) << 8) | ((r.lport >> 8) & 0xFF)
        if lport != port:
            continue
        if r.state == 5:            # MIB_TCP_STATE_ESTAB: the socket we are actually talking to
            return int(r.pid)
        if r.state != 11 and fallback is None:   # never a TIME_WAIT leftover (pid 0 / System)
            fallback = int(r.pid)
    return fallback

def _user_for_pid_windows(pid):
    import ctypes
    from ctypes import wintypes
    # Private WinDLL instances, not ctypes.windll: that one is shared process-wide, so
    # setting argtypes on it would also rewrite the signatures mitmproxy itself uses.
    adv = ctypes.WinDLL("advapi32", use_last_error=True)
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    # Undeclared functions are assumed to take and return C ints. On 64-bit Windows a
    # HANDLE and a PSID are 64 bits, so handles came back truncated and passing a SID
    # raised "int too long to convert" - the lookup returned None, every connection
    # looked like an unknown user, and the addon failed closed on all of them.
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    adv.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    adv.OpenProcessToken.restype = wintypes.BOOL
    adv.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    adv.GetTokenInformation.restype = wintypes.BOOL
    adv.LookupAccountSidW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                      wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
                                      wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
                                      ctypes.POINTER(wintypes.DWORD)]
    adv.LookupAccountSidW.restype = wintypes.BOOL
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        log(f"user lookup: OpenProcess({pid}) failed, err={ctypes.get_last_error()}")
        return None
    try:
        tok = wintypes.HANDLE()
        if not adv.OpenProcessToken(h, 8, ctypes.byref(tok)): return None  # TOKEN_QUERY
        try:
            size = wintypes.DWORD(0)
            adv.GetTokenInformation(tok, 1, None, 0, ctypes.byref(size))  # TokenUser
            buf = ctypes.create_string_buffer(size.value)
            if not adv.GetTokenInformation(tok, 1, buf, size, ctypes.byref(size)): return None
            sid = ctypes.cast(buf, ctypes.POINTER(ctypes.c_void_p))[0]
            name = ctypes.create_unicode_buffer(256); dom = ctypes.create_unicode_buffer(256)
            nl, dl, use = wintypes.DWORD(256), wintypes.DWORD(256), wintypes.DWORD()
            if not adv.LookupAccountSidW(None, sid, name, ctypes.byref(nl), dom, ctypes.byref(dl), ctypes.byref(use)): return None
            return name.value
        finally:
            k32.CloseHandle(tok)
    finally:
        k32.CloseHandle(h)

def _user_for_port_linux(port):
    # /proc/net/tcp: local_address ... uid
    import pwd
    for fn in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(fn) as f:
                next(f)
                for line in f:
                    parts = line.split()
                    lp = int(parts[1].split(":")[-1], 16)
                    if lp != port:
                        continue
                    # A port number lives on in TIME_WAIT rows (uid 0) for a minute after
                    # the previous connection closed; the kernel may hand the same port
                    # to a new socket meanwhile. Matching the first row made a child's
                    # connection look like root's - i.e. an admin's - and it went
                    # unfiltered (seen 2x in 25 page loads, 02-11-2026). Only the
                    # ESTABLISHED row (st 01) describes the socket we are talking to.
                    if parts[3] == "01":
                        return pwd.getpwuid(int(parts[7])).pw_name
        except Exception:
            continue
    return None

def client_user(flow_or_ctx):
    """Return the OS user name owning the client socket, or None."""
    try:
        peer = flow_or_ctx.client_conn.peername if hasattr(flow_or_ctx, "client_conn") else flow_or_ctx.client.peername
        port = peer[1]
        if platform.system() == "Windows":
            pid = _pid_for_port_windows(port)
            if pid is None:
                log(f"user lookup: no process owns local port {port}")
                return None
            now = time.time()
            u = _pid_user.get(pid)
            if u and now - u[1] < 60: return u[0]
            name = _user_for_pid_windows(pid)
            if name is None:
                log(f"user lookup: pid {pid} found but no account name")
            _pid_user[pid] = (name, now)
            return name
        return _user_for_port_linux(port)
    except Exception as e:
        log(f"user lookup failed: {e}")
        return None

_conn_cache = {}          # client connection id -> (user, enforced)


def _conn_key(o):
    c = getattr(o, "client_conn", None) or getattr(o, "client", None)
    return getattr(c, "id", None)


def _verdict(user):
    if user is None:
        return True                      # unknown -> fail closed
    u = user.lower()
    if u in SYSTEM_USERS or u.endswith("$"): return False
    if CFG["enforceUsers"]:
        return u in {x.lower() for x in CFG["enforceUsers"]}
    if u in {x.lower() for x in CFG["exemptUsers"]}: return False
    if u in _local_admins(): return False
    return True


def conn_info(flow_or_ctx):
    """(user, enforced) for this client connection. The OS lookup walks the whole TCP
    table, so it must happen once per connection, not once per request."""
    key = _conn_key(flow_or_ctx)
    if key is not None:
        hit = _conn_cache.get(key)
        if hit is not None: return hit
    info = (None, True)
    user = client_user(flow_or_ctx)
    info = (user, _verdict(user))
    if key is not None:
        if len(_conn_cache) > 4096: _conn_cache.clear()
        _conn_cache[key] = info
    return info


def enforced(flow_or_ctx):
    return conn_info(flow_or_ctx)[1]

# ---------------------------------------------------------------- policy decisions
YT_BLOCK_HOSTS = ("youtube.com", "youtube-nocookie.com", "youtubekids.com", "youtubei.googleapis.com", "googlevideo.com")


def blocked_match(host, path):
    """The `blocked` tab: domain (with subdomains) or domain/path prefix."""
    host = (host or "").lower().rstrip(".")
    with lock:
        for d in L.blocked_domains:
            if host == d or host.endswith("." + d):
                return d
        hp = re.sub(r"^www\.", "", host) + path
        for p in L.blocked_paths:
            if hp.startswith(p):
                return p
    return None


def site_window_closed(host):
    """Column D of websites: the listed site this host belongs to has hours, and now is outside."""
    d = matched_domain(host)
    if not d:
        return None
    with lock:
        win = L.site_windows.get(d)
    if not win:
        return None
    t = time.localtime()
    return d if not timewindow.allowed(win, t.tm_wday, t.tm_hour * 60 + t.tm_min) else None


def schedule_closed():
    with lock:
        win = L.windows
    if not win:
        return False
    t = time.localtime()
    return not timewindow.allowed(win, t.tm_wday, t.tm_hour * 60 + t.tm_min)


def decide(flow, nav):
    """-> None (allowed) or (reason, title, subtitle). Order: schedule, blocked tab, keywords,
    category lists, YouTube mode, then the whitelist itself. Everything applies in both modes
    except the whitelist, which only applies in whitelist mode."""
    host, path = req_host(flow).lower(), flow.request.path
    with lock:
        mode, yt_mode, kw, shorts = L.settings.mode, L.yt_mode, L.keywords, L.settings.shorts
    if schedule_closed():
        with lock:
            sched = L.settings.schedule
        return ("schedule", "Ngoài giờ sử dụng", "Giờ được phép: %s" % sched)
    b = blocked_match(host, path)
    if b:
        return ("blocked", "Trang này đã bị chặn", b)
    k = kw.hit_url(host, path)
    if k:
        return ("keyword", "Nội dung không phù hợp", "từ khoá: %s" % k)
    if _shared.cats is not None:
        cat = _shared.cats.match(host)
        if cat:
            return ("category", "Trang thuộc danh mục bị chặn", cat)
    is_yt = host in YT_HOSTS
    if is_yt or any(host == h_ or host.endswith("." + h_) for h_ in YT_BLOCK_HOSTS):
        if yt_mode == "block":
            return ("youtube", "YouTube đã bị tắt", "")
        if is_yt and shorts and (path.startswith("/shorts") or path.startswith("/youtubei/v1/reel/")):
            return ("shorts", "YouTube Shorts đã bị tắt", "")
    if is_yt:
        return None                      # channel / restricted handling happens elsewhere
    w = site_window_closed(host)
    if w:
        with lock:
            hours = L.site_windows.get(w)
        return ("site-hours", "Ngoài giờ cho %s" % w, "")
    if mode == "whitelist" and not (url_allowed(host, path) or smart_allowed(flow)):
        return ("whitelist", "Trang này không nằm trong danh sách được phép", host)
    return None


PASSTHROUGH_HOSTS = ("googlevideo.com", "ytimg.com", "ggpht.com", "gstatic.com", "googleusercontent.com")
YT_FEED_PATHS = ("/results", "/feed", "/@", "/channel/", "/c/", "/user/", "/playlist")


def _yt_rewrite_candidate(flow):
    """Mirror of the branches in GreenGate.response(): which YouTube responses get read or
    rewritten. Only those are buffered; the rest of the same hosts streams."""
    ct = flow.response.headers.get("content-type", "").lower()
    p = flow.request.path.split("?")[0]
    with lock:
        yt_mode, shorts = L.yt_mode, L.settings.shorts
    if "json" in ct and p.startswith("/youtubei/"):
        return yt_mode == "channels" or (shorts and CFG["filterFeeds"])
    if "html" in ct and yt_mode == "channels":
        return p == "/watch" or (CFG["filterFeeds"] and (p == "/" or p.startswith(YT_FEED_PATHS)))
    return False


_tunnel_seen = {}


def _tunnel_ok(host, conn_ctx):
    """settings.deepInspect = off: relay a site without decrypting it, like the media CDNs.
    Whitelist mode: only a site the parents listed as a whole domain. Blacklist mode: any host
    no host-level rule refuses. Always decrypted: YouTube (channel / Shorts filtering), search
    engines (SafeSearch), ad hosts, hosts with a `blocked` path rule or allowed only for a
    path, and a host whose daily budget is spent - request() must answer the block page."""
    with lock:
        if L.settings.deepInspect or not L.loaded:
            return False
        mode, limits, blocked_paths, kw = L.settings.mode, dict(L.limits), list(L.blocked_paths), L.keywords
    if not host or _is_ip(host) or host in CONTROL_HOSTS:
        return False
    if host in YT_HOSTS or any(host == h_ or host.endswith("." + h_) for h_ in YT_BLOCK_HOSTS):
        return False
    if policy.safesearch_host(host) or is_ad_host(host):
        return False
    if schedule_closed() or blocked_match(host, "/") or site_window_closed(host):
        return False
    if kw.hit_host(host) or (_shared.cats is not None and _shared.cats.match(host)):
        return False
    bare = re.sub(r"^www\.", "", host)
    if any(p.split("/", 1)[0] == bare for p in blocked_paths):
        return False
    if mode == "whitelist" and not host_allowed(host):
        return False
    u = _shared.usage
    if u is not None and limits:
        # No request to look at, so a new connection counts as one browser request toward
        # the activity threshold. Once the budget is spent the connection is decrypted
        # instead, and request() shows "Hết giờ".
        user = (conn_info(conn_ctx)[0] or "?").lower()
        now = time.localtime()
        day, minute = time.strftime("%Y-%m-%d", now), now.tm_hour * 60 + now.tm_min
        d = matched_domain(host)
        targets = [(t, limits.get(t, 0)) for t in (d, GLOBAL) if t and limits.get(t, 0)]
        for target, cap in targets:
            if u.used(day, user, target) >= cap and not u.has(day, user, target, minute):
                return False
        for target, cap in targets:
            u.note(day, user, target, minute, False, int(CFG.get("activityRequests", 3)))
    return True


def _record_tunnel(host, user):
    """History for a tunnelled site: one "host/" visit per host per minute (we never see
    its URLs), so the parents' log still shows where the child went."""
    now = time.time()
    if now - _tunnel_seen.get(host, 0) < 60:
        return
    if len(_tunnel_seen) > 4096:
        _tunnel_seen.clear()
    _tunnel_seen[host] = now
    ul = CFG["urlLog"]
    if not ul.get("enabled") and not ul.get("localFile"):
        return
    try:
        lt = time.localtime(now)
        url = host + "/"
        _local_append({"t": time.strftime("%Y-%m-%d %H:%M:%S", lt), "user": user, "url": url,
                       "blocked": False, "nav": True, "tunnel": True})
        if _shared.counts is not None:
            _shared.counts.record(time.strftime("%m-%Y", lt), url, lt.tm_mday)
    except Exception as e:
        log(f"url log error: {e}")


def _passthrough_ok(host):
    """Tunnel without decryption: only for the media CDNs, only when no host-level rule
    (schedule, blocked tab, keyword in host, category, YouTube off) would refuse them."""
    if not CFG.get("passthroughMedia", True):
        return False
    if not any(host == h_ or host.endswith("." + h_) for h_ in PASSTHROUGH_HOSTS):
        return False
    if schedule_closed() or blocked_match(host, "/"):
        return False
    with lock:
        kw, yt_mode = L.keywords, L.yt_mode
    if kw.hit_host(host):
        return False
    if _shared.cats is not None and _shared.cats.match(host):
        return False
    if yt_mode == "block" and host.endswith("googlevideo.com"):
        return False
    return True


# ---------------------------------------------------------------- YouTube filtering
BLOCK_HTML = """<!doctype html><!--greengate-block--><html lang="vi"><meta charset="utf-8"><title>Bị chặn</title>
<body style="margin:0;font-family:system-ui,sans-serif;background:#f4f5f7;display:flex;align-items:center;justify-content:center;height:100vh">
<div style="background:#fff;padding:40px 48px;border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,.08);max-width:560px;text-align:center">
<h1 style="font-size:22px;margin:0 0 12px">{title}</h1><p style="color:#555">{sub}</p></div></body></html>"""

def blocked_page(title, sub):
    with lock:
        note = L.settings.blockPage
    if note:
        sub = (sub + " · " if sub else "") + note
    return http.Response.make(403, BLOCK_HTML.format(title=_esc(title), sub=_esc(sub)).encode("utf-8"),
                              {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"})

RENDERERS = ("videoRenderer", "compactVideoRenderer", "gridVideoRenderer", "richItemRenderer",
             "reelItemRenderer", "playlistVideoRenderer", "lockupViewModel", "videoWithContextRenderer")
DROP_ALWAYS = ("reelShelfRenderer", "shortsLockupViewModel", "richShelfRenderer")

def _find_channels(obj, out, depth=0):
    """Collect (handle, channelId) pairs from every browse endpoint inside a renderer."""
    if depth > 14: return
    if isinstance(obj, dict):
        if "reelWatchEndpoint" in obj: out.append(("__shorts__", None))
        be = obj.get("browseEndpoint")
        if isinstance(be, dict):
            base = be.get("canonicalBaseUrl") or ""
            bid = be.get("browseId") or ""
            m = re.match(r"^/@([^/?#]+)", base)
            if m or bid.startswith("UC"):
                out.append((m.group(1) if m else None, bid if bid.startswith("UC") else None))
        for v in obj.values(): _find_channels(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj: _find_channels(v, out, depth + 1)

def _item_allowed(item):
    found = []
    _find_channels(item, found)
    if any(h == "__shorts__" for h, _ in found) and L.settings.shorts: return False
    found = [(h, c) for h, c in found if h != "__shorts__"]
    if not found: return False
    return any(channel_allowed(h, c) for h, c in found)

def filter_json(obj, stats, depth=0):
    if depth > 60: return obj
    if isinstance(obj, list):
        out = []
        for el in obj:
            if isinstance(el, dict) and len(el) == 1:
                key = next(iter(el))
                if key in DROP_ALWAYS and L.settings.shorts:
                    stats["dropped"] += 1; continue
                if key in RENDERERS:
                    if _item_allowed(el): out.append(filter_json(el, stats, depth + 1))
                    else: stats["dropped"] += 1
                    continue
                if key == "guideEntryRenderer" and L.settings.shorts:
                    if json.dumps(el).find('"FEshorts"') >= 0 or '"reelWatchEndpoint"' in json.dumps(el):
                        stats["dropped"] += 1; continue
            out.append(filter_json(el, stats, depth + 1))
        return out
    if isinstance(obj, dict):
        return {k: filter_json(v, stats, depth + 1) for k, v in obj.items()}
    return obj

def _drop_shorts(obj, stats, depth=0):
    """Remove Shorts shelves and reels from a youtubei response, keep everything else."""
    if depth > 60: return obj
    if isinstance(obj, list):
        out = []
        for el in obj:
            if isinstance(el, dict) and len(el) == 1:
                key = next(iter(el))
                if key in DROP_ALWAYS or (key in RENDERERS and '"reelWatchEndpoint"' in json.dumps(el)):
                    stats["dropped"] += 1; continue
            out.append(_drop_shorts(el, stats, depth + 1))
        return out
    if isinstance(obj, dict):
        return {k: _drop_shorts(v, stats, depth + 1) for k, v in obj.items()}
    return obj


def scrub_player_responses(obj, stats, depth=0):
    """Find every player response (any endpoint: player, get_watch, reel_item_watch, ...) and neuter it
    when the channel is not allowed."""
    if depth > 30: return
    if isinstance(obj, dict):
        if "playabilityStatus" in obj and ("videoDetails" in obj or "microformat" in obj):
            h, cid = _player_channel(obj)
            if not channel_allowed(h, cid):
                obj["playabilityStatus"] = {"status": "UNPLAYABLE", "reason": "Kênh này chưa được duyệt",
                    "errorScreen": {"playerErrorMessageRenderer": {
                        "reason": {"simpleText": "Kênh này chưa được duyệt"},
                        "subreason": {"simpleText": "Chỉ xem được video từ các kênh trong danh sách cho phép."}}}}
                for k in ("streamingData", "captions", "storyboards", "playerConfig", "adPlacements", "adSlots", "playerAds"):
                    obj.pop(k, None)
                stats["blocked"] += 1
                log(f"BLOCK video channel=@{h}/{cid}")
            return
        for v in obj.values(): scrub_player_responses(v, stats, depth + 1)
    elif isinstance(obj, list):
        for v in obj: scrub_player_responses(v, stats, depth + 1)

def _player_channel(pr):
    vd = pr.get("videoDetails") or {}
    mf = ((pr.get("microformat") or {}).get("playerMicroformatRenderer")) or {}
    handle = None
    m = re.search(r"youtube\.com/@([^/?#\"]+)", mf.get("ownerProfileUrl") or "")
    if m: handle = m.group(1)
    return handle, vd.get("channelId")

def _html_channel(body):
    m1 = re.search(r'"ownerProfileUrl":"https?://(?:www\.)?youtube\.com/@([^"/?#]+)"', body)
    m2 = re.search(r'"videoDetails":\{[^{}]*?"channelId":"(UC[\w-]+)"', body)
    return (m1.group(1) if m1 else None, m2.group(1) if m2 else None)

def _rewrite_initial_data(body, stats):
    """Filter the embedded ytInitialData JSON in a YouTube HTML page."""
    m = re.search(r"(var ytInitialData = )(\{.*?\})(;</script>)", body, flags=re.S)
    if not m: return body
    try:
        data = json.loads(m.group(2))
    except Exception:
        return body
    data = filter_json(data, stats)
    return body[:m.start(2)] + json.dumps(data, separators=(",", ":")) + body[m.end(2):]

# ---------------------------------------------------------------- mitmproxy hooks
class GreenGate:
    def load(self, loader):
        with _shared.start_lock:
            first = not _shared.refresher
            _shared.refresher = True
        if first:                       # shared L, so one refresher serves every loaded copy
            log("data dir: " + DATA)
            log("config: " + (CFG.get("_configError") or
                              ("loaded, sheet=" + (sheet_id(CFG.get("sheetId")) or "NONE SET"))))
            log("enforceUsers=%s exempt=%s" % (CFG.get("enforceUsers"), CFG.get("exemptUsers")))
            threading.Thread(target=_log_flusher, daemon=True).start()
            threading.Thread(target=_jsonl_flusher, daemon=True).start()
            threading.Thread(target=_refresher, daemon=True).start()
            _shared.usage = Usage(os.path.join(DATA, "usage-state.json"), log)
            threading.Thread(target=_usage_saver, daemon=True).start()
            _shared.cats = policy.CategoryStore(DATA, log, base_url=CFG.get("listsUrl") or policy.LISTS_URL)
        _start_url_log()
        log(f"GreenGate {VERSION} started; enforceUsers={CFG['enforceUsers'] or 'all non-admins'} exempt={CFG['exemptUsers']}")
        _log_flush_now()          # the start-up lines must survive an early kill

    def running(self):
        # Generate the interception certificate from the SNI alone instead of connecting
        # upstream first to copy the real certificate. Two reasons: a site we are about to
        # refuse (category list, keyword, ISP-blocked domain) must still get OUR block page,
        # which is impossible when the upstream handshake fails; and it removes one upstream
        # round trip from every new connection.
        # connection_strategy=lazy for the same reason: "eager" (the default) connects
        # upstream during CONNECT and answers 502 when that fails, before any hook of ours
        # runs - so an ISP-blocked or dead domain showed a browser error instead of why.
        try:
            want = {}
            if ctx.options.upstream_cert:
                want["upstream_cert"] = False
            if ctx.options.connection_strategy != "lazy":
                want["connection_strategy"] = "lazy"
            if want:
                ctx.options.update(**want)
                log("options: " + ", ".join("%s=%s" % kv for kv in want.items()))
        except Exception as e:
            log(f"could not set proxy options: {e}")

    def done(self):
        _log_flush_now()

    def http_connect(self, flow: http.HTTPFlow):
        host = req_host(flow)
        if host.lower() in CONTROL_HOSTS:
            flow.response = http.Response.make(403, b"greengate: dung http://greengate.local/update")
            return
        if not enforced(flow): return
        if CFG["smartDependencies"]: return          # decided per request after TLS interception
        with lock:
            mode = L.settings.mode
        if mode == "whitelist" and not host_allowed(host):
            flow.response = http.Response.make(403, b"blocked by greengate: " + host.encode())
            log(f"BLOCK site {host} ({conn_info(flow)[0]})")

    def tls_clienthello(self, data):
        # transparent mode (Linux) only knows the destination IP; the name is in the SNI
        sni = getattr(getattr(data, "client_hello", None), "sni", None) or ""
        host = (sni or (data.context.server.address or ("",))[0]).lower()
        if not enforced(data.context):
            data.ignore_connection = True   # admins: pass through untouched
            return
        # Media CDNs carry video segments and images, never a page, a search or a channel
        # decision. Decrypting and re-encrypting them in Python is the single biggest cost
        # on YouTube, so they are tunnelled as-is once the host-level rules allow them.
        if _passthrough_ok(host):
            data.ignore_connection = True
            return
        # Parents may trade per-URL checks for speed on the sites they listed (deepInspect=off)
        if _tunnel_ok(host, data.context):
            data.ignore_connection = True
            user = conn_info(data.context)[0]
            _record_tunnel(host, user)
            log_repeating("tun|%s|%s" % (host, user), f"TUNNEL {host} (deepInspect=off) ({user})")
            return
        if CFG["smartDependencies"]: return            # intercept everything for filtered users
        if host not in YT_HOSTS:
            data.ignore_connection = True

    def client_disconnected(self, client):
        _conn_cache.pop(getattr(client, "id", None), None)

    def responseheaders(self, flow: http.HTTPFlow):
        # Only the YouTube responses response() actually reads (feed JSON, watch/feed HTML)
        # are buffered. Everything else streams through as it arrives - including the
        # several MB of script and style www.youtube.com serves per page, which used to be
        # held back whole and cost the browser its progressive loading.
        if flow.response is None:
            return
        if req_host(flow).lower() not in YT_HOSTS or not _yt_rewrite_candidate(flow):
            flow.response.stream = True

    def request(self, flow: http.HTTPFlow):
        if req_host(flow).lower() in CONTROL_HOSTS:
            flow.response = control_response(flow.request.path, flow.request.headers.get("accept", ""))
            return
        user, filtered = conn_info(flow)
        if not filtered: return
        host, path = req_host(flow).lower(), flow.request.path
        dest = flow.request.headers.get("sec-fetch-dest", "").lower()
        nav = dest in NAV_DESTS or not dest
        blocked = False
        verdict = decide(flow, nav)
        if verdict:
            reason, title, sub = verdict
            blocked = True
            if nav:
                flow.response = blocked_page(title, sub)
            else:
                flow.response = http.Response.make(403, ("greengate-block: %s" % reason).encode(),
                                                   {"Content-Type": "text/plain"})
            log_repeating("blk|%s|%s|%s" % (reason, host, user),
                          f"BLOCK {reason} {host} {sub if reason in ('keyword', 'category', 'blocked') else ''} "
                          f"dest={dest or '-'} ref={_hdr_host(flow.request.headers.get('referer',''))} ({user})".replace("  ", " "))
        if not blocked:
            with lock:
                safesearch, yt_mode = L.settings.safesearch, L.yt_mode
            if safesearch:
                new_path = policy.safesearch_rewrite(host, path)
                if new_path:
                    flow.request.path = new_path
                if yt_mode == "restricted" and (host in YT_HOSTS or host.endswith("youtube.com")
                                                or host == "youtubei.googleapis.com"):
                    flow.request.headers["YouTube-Restrict"] = "Strict"
            blocked = self._meter(flow, nav, user)
        # a /watch page is only really "allowed" once the channel check in response() passes
        with lock:
            yt_channels = L.yt_mode == "channels"
        if not (host in YT_HOSTS and path.split("?")[0] == "/watch" and nav and not blocked and yt_channels):
            record_url(flow, blocked, user, nav)

    def _meter(self, flow, nav, user):
        """Daily time budgets: one per site from column C, plus the "*" row covering all
        web use. Both are counted per account, so one child cannot spend another's."""
        u = _shared.usage
        if u is None:
            return False
        # Only browser traffic is metered. Windows Update and background apps send no
        # Sec-Fetch-Dest, and should not burn a child's allowance.
        if not flow.request.headers.get("sec-fetch-dest", ""):
            return False
        who = (user or "?").lower()
        now = time.localtime()
        day, minute = time.strftime("%Y-%m-%d", now), now.tm_hour * 60 + now.tm_min
        site, site_cap = limited_site(flow)
        with lock:
            total_cap = L.limits.get(GLOBAL, 0)
        threshold = int(CFG.get("activityRequests", 3))

        for target, cap, label in ((site, site_cap, site),
                                   (GLOBAL, total_cap, None)):
            if not target or not cap:
                continue
            used = u.used(day, who, target)
            if used >= cap and not u.has(day, who, target, minute):
                if label:
                    title = "Hết giờ cho %s hôm nay" % label
                else:
                    title = "Hết giờ vào mạng hôm nay"
                if nav:
                    flow.response = blocked_page(
                        title, "Đã dùng %d/%d phút. Mai được dùng tiếp." % (used, cap))
                else:
                    flow.response = http.Response.make(403, b"greengate-block: daily time limit reached")
                log(f"LIMIT {target} {used}/{cap}m ({who})")
                return True
            u.note(day, who, target, minute, nav, threshold)
        return False

    def response(self, flow: http.HTTPFlow):
        host, path = req_host(flow).lower(), flow.request.path
        if host not in YT_HOSTS or flow.response is None or not enforced(flow): return
        with lock:
            yt_mode, shorts = L.yt_mode, L.settings.shorts
        if yt_mode != "channels":
            if shorts and CFG["filterFeeds"] and "json" in flow.response.headers.get("content-type", "") \
                    and path.startswith("/youtubei/"):
                try:            # still hide the Shorts shelves when only Shorts are off
                    data = json.loads(flow.response.get_text(strict=False) or "null")
                    st = {"dropped": 0, "blocked": 0}
                    data = _drop_shorts(data, st)
                    if st["dropped"]:
                        flow.response.set_text(json.dumps(data, separators=(",", ":")))
                except Exception as e:
                    log(f"shorts filter error on {path}: {e}")
            return
        ct = flow.response.headers.get("content-type", "")
        p = path.split("?")[0]
        try:
            if "json" in ct and p.startswith("/youtubei/"):
                data = json.loads(flow.response.get_text(strict=False) or "null")
                st = {"dropped": 0, "blocked": 0}
                scrub_player_responses(data, st)
                if CFG["filterFeeds"]: data = filter_json(data, st)
                if st["dropped"] or st["blocked"]:
                    flow.response.set_text(json.dumps(data, separators=(",", ":")))
            elif p == "/watch" and "html" in ct:
                body = flow.response.get_text(strict=False) or ""
                h, cid = _html_channel(body)
                if not channel_allowed(h, cid):
                    flow.response = blocked_page("Kênh YouTube này chưa được duyệt", f"@{h}" if h else (cid or ""))
                    log(f"BLOCK watch channel=@{h}/{cid}")
                    record_url(flow, True, conn_info(flow)[0], True)
                else:
                    record_url(flow, False, conn_info(flow)[0], True)
                    if CFG["filterFeeds"]:
                        st = {"dropped": 0, "blocked": 0}
                        flow.response.set_text(_rewrite_initial_data(body, st))
            elif CFG["filterFeeds"] and "html" in ct and (p == "/" or p.startswith(("/results", "/feed", "/@", "/channel/", "/c/", "/user/", "/playlist"))):
                body = flow.response.get_text(strict=False) or ""
                st = {"dropped": 0, "blocked": 0}
                flow.response.set_text(_rewrite_initial_data(body, st))
        except Exception as e:
            log(f"filter error on {p}: {e}")

addons = [GreenGate()]
