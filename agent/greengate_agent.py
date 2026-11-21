"""
GreenGate agent - runs in the child's login session on Windows and Linux.

Keeps a WebSocket to the relay, answers the parent's encrypted commands (screenshot,
history, refresh, status, pause, resume, settings) and tells the child every time a
screenshot is taken. Settings still come from the Google Sheet through the proxy; the
relay only moves encrypted blobs, see docs/SPEC.md §5.

    greengate_agent.py pair --relay https://relay.example --name "Máy của An"
    greengate_agent.py run
    greengate_agent.py status

Config (JSON): Linux ~/.config/greengate/agent.json, Windows %ProgramData%\\GreenGate\\agent-<user>.json
(override with --config). Keys: relay, deviceId, deviceToken, secretKey, publicKey, parents,
name, platform, proxyPort, screenshotEvery, retentionDays.
"""
import argparse
import base64
import getpass
import gzip
import io
import json
import os
import platform
import subprocess
import sys
import threading
import time
import uuid

# The agent's own traffic (relay) must never go through the filtering proxy. The only
# deliberate proxied calls are the ones to greengate.local, made with an explicit proxy.
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
    os.environ.pop(_k, None)
os.environ["NO_PROXY"] = os.environ["no_proxy"] = "*"

import requests                                   # noqa: E402
import websocket                                  # noqa: E402
from nacl.public import Box, PrivateKey, PublicKey  # noqa: E402
from nacl.utils import random as nacl_random      # noqa: E402

VERSION = "1.0.0"
MAX_BLOB = 950_000            # base64 characters, see SPEC §5
TS_WINDOW = 300               # seconds a command may be old
CONTROL = "http://greengate.local"
IS_WIN = os.name == "nt"


# ---------------------------------------------------------------- config
def default_config_path():
    if IS_WIN:
        base = os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "GreenGate")
        return os.path.join(base, "agent-%s.json" % getpass.getuser().lower())
    return os.path.join(os.path.expanduser("~"), ".config", "greengate", "agent.json")


class Config:
    def __init__(self, path):
        self.path = path
        self.data = {"relay": "", "proxyPort": 8080, "parents": [], "screenshotEvery": None,
                     "retentionDays": 30, "platform": detect_platform(),
                     "uploadUrl": "",            # local override of the sheet's uploadUrl (SPEC §8)
                     "consent": {}}              # {"parent": iso-time, "child": iso-time}
        try:
            with open(path, encoding="utf-8-sig") as f:
                self.data.update(json.load(f))
        except FileNotFoundError:
            pass

    def __getitem__(self, k):
        return self.data.get(k)

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self.path)
        if not IS_WIN:
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass

    @property
    def data_dir(self):
        return os.path.dirname(self.path)


def detect_platform():
    s = platform.system().lower()
    return {"windows": "windows", "linux": "linux", "darwin": "mac"}.get(s, "linux")


_log_lock = threading.Lock()
_log_file = [None]


def log(msg):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
    with _log_lock:
        try:
            print(line, flush=True)
        except Exception:
            pass
        if _log_file[0]:
            try:
                with open(_log_file[0], "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass


# ---------------------------------------------------------------- crypto
def b64(raw):
    return base64.b64encode(raw).decode("ascii")


def unb64(s):
    return base64.b64decode(s)


def seal(obj, their_pub_b64, my_secret):
    """nonce(24) || box(json) -> base64. nacl.box = X25519 + XSalsa20-Poly1305."""
    box = Box(my_secret, PublicKey(unb64(their_pub_b64)))
    nonce = nacl_random(Box.NONCE_SIZE)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return b64(nonce + box.encrypt(data, nonce).ciphertext)


def open_blob(blob_b64, their_pub_b64, my_secret):
    raw = unb64(blob_b64)
    box = Box(my_secret, PublicKey(unb64(their_pub_b64)))
    return json.loads(box.decrypt(raw[24:], raw[:24]).decode("utf-8"))


# ---------------------------------------------------------------- relay http
def relay_session():
    s = requests.Session()
    s.trust_env = False
    return s


def proxy_get(cfg, path, timeout=30):
    """A call to the proxy's own control host, deliberately THROUGH the local proxy."""
    url = CONTROL + path
    proxies = {"http": "http://127.0.0.1:%d" % int(cfg["proxyPort"] or 8080)}
    s = requests.Session()
    s.trust_env = False
    return s.get(url, proxies=proxies, timeout=timeout, headers={"Accept": "text/plain"})


def proxy_settings(cfg):
    """The sheet's `settings` as the proxy publishes them in /status.json (plus the sheet id).
    Cached for 30 s; the last good answer is kept while the proxy is unreachable."""
    now = time.time()
    cache = getattr(proxy_settings, "_cache", None)
    if cache and now - cache[0] < 30:
        return cache[1]
    st = cache[1] if cache else {}
    try:
        r = proxy_get(cfg, "/status.json", timeout=10)
        if r.ok:
            j = r.json()
            st = dict(j.get("settings") or {})
            st["_sheet"] = j.get("sheet") or ""
    except Exception:
        pass
    proxy_settings._cache = (now, st)
    return st


def has_consent(cfg):
    c = cfg["consent"] or {}
    return bool(c.get("parent") and c.get("child"))


def upload_url(cfg, settings=None):
    """Local config wins over the sheet (parents who do not want the URL in a link-shared sheet)."""
    u = (cfg["uploadUrl"] or "").strip()
    if not u:
        u = ((settings if settings is not None else proxy_settings(cfg)).get("uploadUrl") or "").strip()
    return u if u.startswith("http") else ""


def drive_upload(url, jpeg, cfg, reason="schedule", when=None, timeout=30):
    """POST one screenshot to the parents' Apps Script (SPEC §8). Google answers with a 302 to the
    JSON result; requests turns the redirected POST into a GET, which is what the script expects.
    Returns the parsed JSON ({"ok": true, ...} or {"ok": false, "error": ...})."""
    when = when or time.time()
    body = {"v": 1, "device": cfg["name"] or platform.node(), "platform": cfg["platform"],
            "user": getpass.getuser(), "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(when)),
            "reason": reason, "keepDays": int(cfg["retentionDays"] or 30),
            "mime": "image/jpeg", "image": b64(jpeg)}
    s = requests.Session()
    s.trust_env = False                      # straight out, never through the filtering proxy
    r = s.post(url, json=body, timeout=timeout, allow_redirects=True)
    try:
        return r.json()
    except Exception:
        return {"ok": False, "error": "HTTP %d: %s" % (r.status_code, r.text[:120])}


# ---------------------------------------------------------------- notifications
def notify(title, body):
    """Tell the child. Never silent: transparency is a design rule."""
    try:
        if IS_WIN:
            ps = r'''
$t = [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]
$x = [Windows.UI.Notifications.ToastTemplateType, Windows.UI.Notifications, ContentType = WindowsRuntime]
$tmpl = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent($x::ToastText02)
$n = $tmpl.GetElementsByTagName("text"); $n.Item(0).AppendChild($tmpl.CreateTextNode("%s")) | Out-Null
$n.Item(1).AppendChild($tmpl.CreateTextNode("%s")) | Out-Null
$toast = [Windows.UI.Notifications.ToastNotification]::new($tmpl)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("GreenGate").Show($toast)
''' % (title.replace('"', "'"), body.replace('"', "'"))
            r = subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                               capture_output=True, timeout=20, creationflags=0x08000000)
            if r.returncode != 0:
                subprocess.Popen(["msg", "*", "/TIME:10", "%s: %s" % (title, body)], creationflags=0x08000000)
        else:
            subprocess.run(["notify-send", "-a", "GreenGate", "-i", "camera-photo", title, body], timeout=10)
    except Exception as e:
        log("notify failed: %s" % e)


# ---------------------------------------------------------------- command handlers
def take_screenshot(max_chars, side=1280, qualities=(60, 50, 40)):
    """JPEG, longest side `side`, quality stepping down, then smaller, until base64 fits."""
    import mss
    from PIL import Image
    if os.environ.get("GREENGATE_TEST_IMAGE"):          # tests: a known picture instead of the screen
        img = Image.open(os.environ["GREENGATE_TEST_IMAGE"]).convert("RGB")
    else:
        with getattr(mss, "MSS", mss.mss)() as sct:
            mon = sct.monitors[0]              # all monitors combined
            shot = sct.grab(mon)
            img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
    while True:
        im = img.copy()
        im.thumbnail((side, side))
        for q in qualities:
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=q, optimize=True)
            data = buf.getvalue()
            if len(data) * 4 / 3 + 800 < max_chars:
                return data, im.size, q
        side = int(side * 0.75)
        if side < 320:
            return data, im.size, q


class Agent:
    def __init__(self, cfg):
        self.cfg = cfg
        self.secret = PrivateKey(unb64(cfg["secretKey"]))
        self.ws = None
        self.seen = set()                 # command ids already executed
        self.stop = threading.Event()
        self.connected = threading.Event()
        self.last_pong = time.time()
        self.last_hint = 0.0
        self.registered_sheet = ""
        self.drive = {"uploads": 0, "failed": 0, "queued": 0, "lastUpload": None, "lastError": None}

    # ------------------------------------------------------------ websocket
    def url(self):
        base = self.cfg["relay"].rstrip("/")
        ws = "wss://" + base[len("https://"):] if base.startswith("https://") else "ws://" + base[len("http://"):]
        return "%s/v1/device/%s/ws?token=%s" % (ws, self.cfg["deviceId"], self.cfg["deviceToken"])

    def run_forever(self):
        backoff = 2
        threading.Thread(target=self._auto_capture, daemon=True).start()
        threading.Thread(target=self._app_blocker, daemon=True).start()
        while not self.stop.is_set():
            t0 = time.time()
            try:
                self.ws = websocket.WebSocketApp(
                    self.url(), on_open=self._on_open, on_message=self._on_message,
                    on_error=lambda ws, e: log("ws error: %s" % e),
                    on_close=lambda ws, c, m: log("ws closed (%s %s)" % (c, m)))
                self.ws.run_forever(ping_interval=30, ping_timeout=10, ping_payload="",
                                    sslopt=None, suppress_origin=True)
            except Exception as e:
                log("ws loop error: %s" % e)
            self.connected.clear()
            if self.stop.is_set():
                break
            backoff = 2 if time.time() - t0 > 60 else min(60, backoff * 2)
            log("reconnecting in %ds" % backoff)
            self.stop.wait(backoff)

    def _on_open(self, ws):
        self.connected.set()
        log("connected to relay")
        hello = {"t": "hello", "platform": self.cfg["platform"], "version": VERSION}
        sheet = proxy_settings(self.cfg).get("_sheet")
        if sheet:
            hello["sheet"] = sheet            # so a "sheet changed" webhook can reach this device
            self.registered_sheet = sheet
        ws.send(json.dumps(hello))

    def _on_message(self, ws, raw):
        try:
            m = json.loads(raw)
        except Exception:
            return
        t = m.get("t")
        if t == "parents":
            keys = [k for k in m.get("keys") or [] if isinstance(k, str)]
            if keys and keys != self.cfg["parents"]:
                self.cfg["parents"] = keys
                self.cfg.save()
                log("parents updated: %d key(s)" % len(keys))
        elif t == "cmd":
            ws.send(json.dumps({"t": "ack", "cmdId": m.get("cmdId")}))
            threading.Thread(target=self._handle, args=(m,), daemon=True).start()
        elif t == "hint":
            # unencrypted nudge from the relay: the sheet changed, read it again (SPEC §5)
            if m.get("kind") == "refresh" and time.time() - self.last_hint > 10:
                self.last_hint = time.time()
                threading.Thread(target=self._refresh_from_hint, daemon=True).start()
        elif t == "error":
            log("relay error for %s: %s" % (m.get("cmdId"), m.get("error")))

    def _refresh_from_hint(self):
        try:
            r = proxy_get(self.cfg, "/update", timeout=60)
            log("sheet-changed hint -> /update: %s" % (r.text.splitlines()[0] if r.text else r.status_code))
        except Exception as e:
            log("sheet-changed hint failed: %s" % e)

    # ------------------------------------------------------------ commands
    def _handle(self, m):
        cmd_id, parent_pub, blob = m.get("cmdId"), m.get("parentPub"), m.get("blob")
        t_recv = time.time()
        if parent_pub not in (self.cfg["parents"] or []):
            log("command from an unknown parent key - ignored")
            return
        try:
            env = open_blob(blob, parent_pub, self.secret)
        except Exception as e:
            log("command %s did not decrypt: %s" % (cmd_id, e))
            return
        ts = float(env.get("ts") or 0) / 1000.0
        if abs(time.time() - ts) > TS_WINDOW:
            result = self._result(env, False, error="lệnh quá cũ (%.0fs)" % abs(time.time() - ts))
        elif env.get("id") in self.seen:
            log("duplicate delivery of %s ignored" % env.get("type"))   # the first run answers it
            return
        else:
            self.seen.add(env.get("id"))
            if len(self.seen) > 2000:
                self.seen = set(list(self.seen)[-1000:])
            try:
                result = self.execute(env)
            except Exception as e:
                log("command %s failed: %s" % (env.get("type"), e))
                result = self._result(env, False, error=str(e)[:300])
        result["agentMs"] = int((time.time() - t_recv) * 1000)
        if not result.get("ok"):
            log("%s -> error: %s" % (env.get("type"), result.get("error")))
        out = seal(result, parent_pub, self.secret)
        if len(out) > MAX_BLOB:
            out = seal(self._result(env, False, error="kết quả quá lớn (%d)" % len(out)), parent_pub, self.secret)
        try:
            self.ws.send(json.dumps({"t": "result", "cmdId": cmd_id, "blob": out}))
            log("%s -> result sent (%d chars, %d ms)" % (env.get("type"), len(out), result["agentMs"]))
        except Exception as e:
            log("could not send result: %s" % e)

    def _result(self, env, ok, data=None, error=None):
        r = {"v": 1, "id": env.get("id"), "ok": ok, "ts": int(time.time() * 1000), "type": env.get("type")}
        if ok:
            r["data"] = data
        else:
            r["error"] = error
        return r

    def execute(self, env):
        kind = env.get("type")
        params = env.get("params") or {}
        if kind == "screenshot":
            data, size, q = take_screenshot(MAX_BLOB - 2000)
            notify("GreenGate", "Bố mẹ vừa chụp màn hình.")
            url = upload_url(self.cfg)
            if url:                             # the parents' Drive history gets this one too
                threading.Thread(target=self._upload_or_queue, args=(url, data, "parent", time.time()), daemon=True).start()
            return self._result(env, True, {"mime": "image/jpeg", "b64": b64(data), "width": size[0],
                                            "height": size[1], "quality": q, "user": getpass.getuser(),
                                            "host": platform.node()})
        if kind == "history":
            month = params.get("month") or time.strftime("%m-%Y")
            r = proxy_get(self.cfg, "/log.csv?m=%s" % month)
            r.raise_for_status()
            gz = gzip.compress(r.content, 9)
            return self._result(env, True, {"mime": "text/csv+gzip", "b64": b64(gz), "month": month,
                                            "rows": r.text.count("\n")})
        if kind == "refresh":
            r = proxy_get(self.cfg, "/update")
            return self._result(env, True, {"text": r.text[:2000]})
        if kind == "status":
            try:
                r = proxy_get(self.cfg, "/status.json", timeout=15)
                if r.ok and "json" in r.headers.get("content-type", ""):
                    proxy = r.json()
                else:
                    raise ValueError("no status.json")
            except Exception:
                try:
                    proxy = {"text": proxy_get(self.cfg, "/", timeout=15).text[:2000]}
                except Exception as e:
                    proxy = {"error": "proxy không trả lời: %s" % e}
            return self._result(env, True, {"proxy": proxy, "agent": VERSION, "platform": self.cfg["platform"],
                                            "user": getpass.getuser(), "host": platform.node(),
                                            "screenshotEvery": self._every(),
                                            "retentionDays": self.cfg["retentionDays"],
                                            "consent": self.cfg["consent"] or {}, "drive": dict(self.drive),
                                            "driveConfigured": bool(upload_url(self.cfg))})
        if kind in ("pause", "resume"):
            minutes = int(params.get("minutes") or 0)
            if IS_WIN:
                cmd = ["cmd.exe", "/c", "greengate"] + (["pause", str(minutes)] if kind == "pause" and minutes else [kind])
            else:
                hook = "/usr/local/lib/greengate/pause.sh"
                if not os.path.exists(hook):
                    return self._result(env, False, error="chưa có %s trên máy này" % hook)
                cmd = [hook, kind, str(minutes)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return self._result(env, r.returncode == 0, {"text": (r.stdout + r.stderr)[-2000:]},
                                error=None if r.returncode == 0 else (r.stdout + r.stderr)[-500:])
        if kind == "settings":
            for k in ("screenshotEvery", "retentionDays"):
                if k in params:
                    self.cfg[k] = max(0, int(params[k]))
            self.cfg.save()
            return self._result(env, True, {"screenshotEvery": self.cfg["screenshotEvery"],
                                            "retentionDays": self.cfg["retentionDays"]})
        return self._result(env, False, error="lệnh không hỗ trợ: %s" % kind)

    # ------------------------------------------------------------ app rules
    def _app_blocker(self):
        """Every 5 s: close the processes the apps tab blocks, or whose hours are closed, or
        whose daily minutes are spent. Rule names are exe names on Windows (roblox.exe) and
        process names on Linux; Android package names are simply never seen here."""
        usage = AppUsage(os.path.join(self.cfg.data_dir, "app-usage.json"))
        warned = {}
        while not self.stop.is_set():
            self.stop.wait(5)
            try:
                rules = _app_rules(self.cfg)
                if not rules:
                    continue
                procs = _running_processes()
                for rule in rules:
                    name = rule["name"].lower()
                    pids = procs.get(name) or procs.get(name + ".exe") or procs.get(name[:-4] if name.endswith(".exe") else name)
                    if not pids:
                        continue
                    why = None
                    if rule.get("block"):
                        why = "ứng dụng này bị chặn"
                    elif _hours_closed(rule.get("hours")):
                        why = "ngoài giờ cho phép (%s)" % rule.get("hours")
                    elif rule.get("minutes"):
                        usage.note(name)
                        if usage.used(name) > int(rule["minutes"]):
                            why = "hết %d phút hôm nay" % int(rule["minutes"])
                    if why:
                        _kill(pids)
                        if time.time() - warned.get(name, 0) > 60:
                            warned[name] = time.time()
                            notify("GreenGate", "%s: %s." % (rule["name"], why))
                            log("APP %s closed: %s" % (name, why))
                usage.save()
            except Exception as e:
                log("app blocker: %s" % e)

    # ------------------------------------------------------------ automatic capture
    def _every(self):
        """Minutes between scheduled screenshots: the sheet's `screenshotEvery` (default 15), or
        the local override set with the `settings` command."""
        if self.cfg["screenshotEvery"] is not None:
            return int(self.cfg["screenshotEvery"] or 0)
        try:
            return int(proxy_settings(self.cfg).get("screenshotEvery", 15))
        except (TypeError, ValueError):
            return 15

    def _auto_capture(self):
        """Every screenshotEvery minutes (inside screenshotHours, with both consents, screen not
        locked) take a screenshot, tell the child, and send it to the parents' Drive through
        uploadUrl (SPEC §8). Without uploadUrl the old behaviour stays: an encrypted copy per
        parent key is kept locally. Failed uploads wait in shots/queue and are retried."""
        shots = os.path.join(self.cfg.data_dir, "shots")
        queue = os.path.join(shots, "queue")
        last = time.time()          # first shot one interval after start: a watchdog restart must not add shots
        warned = None
        while not self.stop.is_set():
            self.stop.wait(20)
            if self.stop.is_set():
                break
            try:
                st = proxy_settings(self.cfg)
                every = self._every()
                keep = time.time() - int(self.cfg["retentionDays"] or 30) * 86400
                if os.path.isdir(shots):
                    for f in os.listdir(shots):
                        pth = os.path.join(shots, f)
                        if os.path.isfile(pth) and os.path.getmtime(pth) < keep:
                            os.remove(pth)
                url = upload_url(self.cfg, st)
                if url:
                    self._retry_queue(url, queue)
                if st.get("_sheet") and st["_sheet"] != self.registered_sheet and self.connected.is_set():
                    try:
                        self.ws.send(json.dumps({"t": "register", "sheet": st["_sheet"]}))
                        self.registered_sheet = st["_sheet"]
                        log("registered with relay for sheet %s" % st["_sheet"])
                    except Exception:
                        pass
                if not every:
                    continue
                if time.time() - last < every * 60:
                    continue
                if not has_consent(self.cfg):
                    if warned != "consent":
                        log("scheduled screenshots: no consent recorded yet (greengate_agent consent) - skipping")
                        warned = "consent"
                    continue
                if _hours_closed(st.get("screenshotHours") or ""):
                    continue
                if not url and not self.cfg["parents"]:
                    continue
                if screen_locked():
                    continue
                warned = None
                # scheduled shots are many (96/day at 15 min): 1024 px / q50 keeps them readable at
                # roughly half the bytes of a live screenshot, which halves Drive usage
                data, size, q = take_screenshot(MAX_BLOB - 2000, side=1024, qualities=(50, 40))
                if looks_blank(data):
                    continue                    # lock screen / display off: nothing to show, do not count it
                last = time.time()
                notify("GreenGate", "Chụp màn hình theo lịch (mỗi %d phút), ảnh gửi vào Drive của bố mẹ." % every
                       if url else "Ảnh màn hình định kỳ đã được lưu (mỗi %d phút)." % every)
                if url:
                    self._upload_or_queue(url, data, "schedule", last, queue)
                else:
                    os.makedirs(shots, exist_ok=True)
                    stamp = time.strftime("%Y-%m-%d_%H%M")
                    for i, pub in enumerate(self.cfg["parents"]):
                        blob = seal({"v": 1, "type": "autoshot", "ts": int(time.time() * 1000),
                                     "data": {"mime": "image/jpeg", "b64": b64(data)}}, pub, self.secret)
                        with open(os.path.join(shots, "%s.%d.bin" % (stamp, i)), "w") as f:
                            f.write(blob)
            except Exception as e:
                log("auto capture failed: %s" % e)

    def _upload_or_queue(self, url, data, reason, when, queue=None):
        queue = queue or os.path.join(self.cfg.data_dir, "shots", "queue")
        t0 = time.time()
        try:
            res = drive_upload(url, data, self.cfg, reason, when)
            if res.get("ok"):
                self.drive["uploads"] += 1
                self.drive["lastUpload"] = int(when)
                self.drive["lastError"] = None
                log("drive: %s uploaded in %d ms -> %s/%s" % (reason, (time.time() - t0) * 1000, res.get("path"), res.get("name")))
                return True
            err = res.get("error") or "unknown"
        except Exception as e:
            err = str(e)[:200]
        self.drive["failed"] += 1
        self.drive["lastError"] = err
        log("drive: upload failed (%s) - queued" % err)
        os.makedirs(queue, exist_ok=True)
        with open(os.path.join(queue, "%d-%s.jpg" % (int(when), reason)), "wb") as f:
            f.write(data)
        files = sorted(os.listdir(queue))
        for old in files[:-200]:                # never more than 200 waiting
            os.remove(os.path.join(queue, old))
        self.drive["queued"] = min(len(files), 200)
        return False

    def _retry_queue(self, url, queue):
        if not os.path.isdir(queue):
            return
        files = sorted(os.listdir(queue))
        self.drive["queued"] = len(files)
        for f in files[:5]:                     # a few per cycle, oldest first
            pth = os.path.join(queue, f)
            try:
                when, reason = f[:-4].split("-", 1)
                with open(pth, "rb") as fh:
                    data = fh.read()
                res = drive_upload(url, data, self.cfg, reason, int(when))
            except Exception as e:
                res = {"ok": False, "error": str(e)[:200]}
            if not res.get("ok"):
                self.drive["lastError"] = res.get("error")
                return                          # still offline: try again next cycle
            os.remove(pth)
            self.drive["uploads"] += 1
            self.drive["queued"] -= 1
            log("drive: queued %s sent" % f)


def screen_locked():
    """Best effort: on Windows the lock screen host is LogonUI.exe; elsewhere capture and judge."""
    if IS_WIN:
        try:
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq LogonUI.exe", "/NH"], capture_output=True,
                                 text=True, timeout=10, creationflags=0x08000000).stdout
            return "LogonUI.exe" in out
        except Exception:
            return False
    return False


def looks_blank(jpeg):
    """A black or single-colour frame (display off, lock screen, screensaver)."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(jpeg)).convert("L")
        im.thumbnail((64, 64))
        lo, hi = im.getextrema()
        return hi - lo < 8
    except Exception:
        return False


# ---------------------------------------------------------------- app rules (apps tab)
def _running_processes():
    """{lowercase process name: [pid]} for this session's user."""
    out = {}
    try:
        if IS_WIN:
            r = subprocess.run(["tasklist", "/FO", "CSV", "/NH", "/FI", "USERNAME eq %s" % getpass.getuser()],
                               capture_output=True, text=True, timeout=20, creationflags=0x08000000)
            import csv as _csv
            for row in _csv.reader(io.StringIO(r.stdout)):
                if len(row) >= 2 and row[1].isdigit():
                    out.setdefault(row[0].lower(), []).append(int(row[1]))
        else:
            r = subprocess.run(["ps", "-u", getpass.getuser(), "-o", "pid=,comm="], capture_output=True, text=True, timeout=20)
            for line in r.stdout.splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2 and parts[0].isdigit():
                    out.setdefault(parts[1].strip().lower(), []).append(int(parts[0]))
    except Exception as e:
        log("process list failed: %s" % e)
    return out


def _kill(pids):
    for pid in pids:
        try:
            if IS_WIN:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=20, creationflags=0x08000000)
            else:
                os.kill(pid, 15)
        except Exception as e:
            log("kill %s failed: %s" % (pid, e))


def _hours_closed(text):
    """True when the time window text exists and now is outside it. Uses proxy/timewindow.py
    when it is next to us (installed together), otherwise treats the rule as always open."""
    if not text:
        return False
    try:
        here = os.path.dirname(os.path.abspath(__file__))
        for cand in (here, os.path.join(here, "..", "proxy"), os.path.join(here, "proxy")):
            if os.path.exists(os.path.join(cand, "timewindow.py")) and cand not in sys.path:
                sys.path.insert(0, cand)
        import timewindow
        return not timewindow.allowed_now(text)
    except Exception as e:
        log("hours rule '%s' ignored: %s" % (text, e))
        return False


class AppUsage:
    """Minutes an app was seen running today, per app, persisted next to the config."""
    def __init__(self, path):
        self.path = path
        self.day = time.strftime("%Y-%m-%d")
        self.minutes = {}
        try:
            with open(path, encoding="utf-8") as f:
                d = json.load(f)
            if d.get("day") == self.day:
                self.minutes = {k: set(v) for k, v in d.get("minutes", {}).items()}
        except Exception:
            pass

    def note(self, app):
        day = time.strftime("%Y-%m-%d")
        if day != self.day:
            self.day, self.minutes = day, {}
        self.minutes.setdefault(app, set()).add(time.localtime().tm_hour * 60 + time.localtime().tm_min)

    def used(self, app):
        return len(self.minutes.get(app, ()))

    def save(self):
        try:
            with open(self.path + ".tmp", "w", encoding="utf-8") as f:
                json.dump({"day": self.day, "minutes": {k: sorted(v) for k, v in self.minutes.items()}}, f)
            os.replace(self.path + ".tmp", self.path)
        except Exception:
            pass


def _app_rules(cfg):
    """The apps tab, as the proxy publishes it in /status.json. Cached for 60 s."""
    now = time.time()
    cache = getattr(_app_rules, "_cache", None)
    if cache and now - cache[0] < 60:
        return cache[1]
    rules = cache[1] if cache else []
    try:
        r = proxy_get(cfg, "/status.json", timeout=10)
        if r.ok:
            rules = [a for a in (r.json().get("apps") or []) if a.get("name")]
    except Exception:
        pass
    _app_rules._cache = (now, rules)
    return rules


# ---------------------------------------------------------------- commands
def cmd_pair(cfg, args):
    if not args.relay and not cfg["relay"]:
        sys.exit("Cần --relay https://...")
    if args.relay:
        cfg["relay"] = args.relay.rstrip("/")
    if args.name:
        cfg["name"] = args.name
    if args.proxy_port:
        cfg["proxyPort"] = args.proxy_port
    if not cfg["secretKey"]:
        sk = PrivateKey.generate()
        cfg["secretKey"], cfg["publicKey"] = b64(bytes(sk)), b64(bytes(sk.public_key))
    s = relay_session()
    r = s.post(cfg["relay"] + "/v1/pair/start", json={
        "devicePub": cfg["publicKey"], "name": cfg["name"] or platform.node(), "platform": cfg["platform"]}, timeout=30)
    r.raise_for_status()
    d = r.json()
    cfg["deviceId"], cfg["deviceToken"], cfg["parents"] = d["deviceId"], d["deviceToken"], []
    cfg.save()
    code = d["code"]
    print("\n  Mã ghép đôi GreenGate:  %s %s   (hết hạn sau 10 phút)\n" % (code[:3], code[3:]))
    print("  Trên điện thoại/máy của bố mẹ: mở ứng dụng GreenGate > Thêm thiết bị > nhập mã,")
    print("  hoặc quét mã QR dưới đây.\n")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data("greengate://pair?code=%s&relay=%s" % (code, cfg["relay"]))
        qr.print_ascii(invert=True)
    except Exception:
        pass
    if args.no_wait:
        return
    print("\n  Đang chờ bố mẹ xác nhận...", flush=True)
    agent = Agent(cfg)
    done = threading.Event()

    def on_message(ws, raw):
        try:
            m = json.loads(raw)
        except Exception:
            return
        if m.get("t") == "parents" and m.get("keys"):
            cfg["parents"] = m["keys"]
            cfg.save()
            done.set()
            ws.close()

    deadline = time.time() + 600
    while time.time() < deadline and not done.is_set():
        ws = websocket.WebSocketApp(agent.url(), on_message=on_message)
        threading.Thread(target=lambda: ws.run_forever(ping_interval=20, ping_timeout=10, suppress_origin=True),
                         daemon=True).start()
        done.wait(30)
        try:
            ws.close()
        except Exception:
            pass
    if done.is_set():
        print("  Đã ghép đôi với %d phụ huynh. Chạy tiếp:  greengate_agent.py run" % len(cfg["parents"]))
    else:
        sys.exit("  Hết thời gian chờ. Chạy lại lệnh pair để lấy mã mới.")


def cmd_run(cfg, args):
    for k in ("relay", "deviceId", "deviceToken", "secretKey"):
        if not cfg[k]:
            sys.exit("Chưa ghép đôi (thiếu %s). Chạy: greengate_agent.py pair --relay ..." % k)
    log("GreenGate agent %s starting as %s on %s, relay %s, device %s"
        % (VERSION, getpass.getuser(), cfg["platform"], cfg["relay"], cfg["deviceId"]))
    agent = Agent(cfg)
    try:
        agent.run_forever()
    except KeyboardInterrupt:
        agent.stop.set()


def cmd_status(cfg, args):
    print("config    :", cfg.path)
    print("relay     :", cfg["relay"] or "(chưa đặt)")
    print("device    :", cfg["deviceId"] or "(chưa ghép đôi)")
    print("parents   :", len(cfg["parents"] or []))
    print("proxy port:", cfg["proxyPort"])
    print("consent   :", "đủ (bố mẹ + con)" if has_consent(cfg) else "chưa đủ")
    print("drive     :", upload_url(cfg) or "(chưa cài)")
    if cfg["relay"]:
        try:
            r = relay_session().get(cfg["relay"] + "/v1/health", timeout=10)
            print("relay says:", r.status_code, r.text[:100])
        except Exception as e:
            print("relay     : không nối được -", e)
    try:
        r = proxy_get(cfg, "/", timeout=10)
        print("proxy says:", r.text.splitlines()[0] if r.text else r.status_code)
    except Exception as e:
        print("proxy     : không trả lời -", e)


CONSENT_TEXT = """GreenGate chụp màn hình máy này theo lịch (mặc định mỗi 15 phút, bố mẹ đổi được trong Google Sheet)
và khi bố mẹ bấm "Chụp màn hình". Mỗi lần chụp máy đều hiện thông báo. Ảnh được gửi vào Google Drive
của bố mẹ (hoặc lưu mã hoá trên máy nếu chưa cài Drive) và xoá sau %s ngày. Không chụp khi màn hình
khoá hoặc ngoài giờ đã đặt. Cả bố mẹ và con cùng đồng ý thì máy mới tự chụp."""


def cmd_consent(cfg, args):
    print(CONSENT_TEXT % (cfg["retentionDays"] or 30))
    c = dict(cfg["consent"] or {})
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    if args.reset:
        c = {}
    if args.parent or args.child:
        if args.parent:
            c["parent"] = now
        if args.child:
            c["child"] = now
    elif not args.reset:
        for who, ask in (("parent", "Bố/mẹ đồng ý? (y/n): "), ("child", "Con đã nghe giải thích và đồng ý? (y/n): ")):
            if input(ask).strip().lower() in ("y", "yes", "co", "có", "c"):
                c[who] = now
    cfg["consent"] = c
    cfg.save()
    print("đồng ý: bố mẹ=%s con=%s -> %s" % (c.get("parent", "-"), c.get("child", "-"),
                                           "ĐỦ, máy sẽ tự chụp theo lịch" if has_consent(cfg) else "CHƯA ĐỦ, chưa tự chụp"))


def cmd_drive(cfg, args):
    if args.set is not None:
        cfg["uploadUrl"] = args.set.strip()
        cfg.save()
        print("uploadUrl (cục bộ):", cfg["uploadUrl"] or "(bỏ, dùng Sheet)")
    url = upload_url(cfg)
    print("uploadUrl dùng  :", url or "(chưa có: thêm khoá uploadUrl vào tab settings, xem drive/README.md)")
    print("chụp mỗi (phút) :", cfg["screenshotEvery"] if cfg["screenshotEvery"] is not None else proxy_settings(cfg).get("screenshotEvery", 15))
    print("đồng ý          :", "đủ" if has_consent(cfg) else "chưa đủ (greengate_agent consent)")
    if args.test and url:
        from PIL import Image
        im = Image.new("RGB", (640, 360), (46, 125, 50))
        try:
            from PIL import ImageDraw
            ImageDraw.Draw(im).text((20, 20), "GreenGate test %s" % time.strftime("%Y-%m-%d %H:%M:%S"), fill=(255, 255, 255))
        except Exception:
            pass
        buf = io.BytesIO(); im.save(buf, "JPEG", quality=70)
        t0 = time.time()
        res = drive_upload(url, buf.getvalue(), cfg, "schedule")
        print("gửi ảnh thử     : %s (%.0f ms) %s" % ("ok" if res.get("ok") else "LỖI", (time.time() - t0) * 1000,
                                                    json.dumps(res, ensure_ascii=False)[:300]))
        sys.exit(0 if res.get("ok") else 1)


def main():
    ap = argparse.ArgumentParser(description="GreenGate agent")
    ap.add_argument("--config", default=default_config_path())
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pair")
    p.add_argument("--relay")
    p.add_argument("--name")
    p.add_argument("--proxy-port", type=int)
    p.add_argument("--no-wait", action="store_true", help="print the code and exit (tests)")
    sub.add_parser("run")
    sub.add_parser("status")
    c = sub.add_parser("consent", help="record that a parent and the child agree to scheduled screenshots")
    c.add_argument("--parent", action="store_true")
    c.add_argument("--child", action="store_true")
    c.add_argument("--reset", action="store_true")
    d = sub.add_parser("drive", help="show / set / test the Drive upload (SPEC §8)")
    d.add_argument("--set", metavar="URL", help="local uploadUrl ('' to use the sheet's)")
    d.add_argument("--test", action="store_true", help="upload a small test picture now")
    args = ap.parse_args()
    cfg = Config(args.config)
    _log_file[0] = os.path.join(cfg.data_dir, "agent.log")
    {"pair": cmd_pair, "run": cmd_run, "status": cmd_status, "consent": cmd_consent, "drive": cmd_drive}[args.cmd](cfg, args)


if __name__ == "__main__":
    main()
