#!/usr/bin/env python3
"""Local stand-in for drive/GreenGateUploader.gs (SPEC §8), for tests and latency measurements.

Behaves like a deployed Apps Script web app: the POST is answered with a 302 to a result URL
(Google does this), the GET of that URL returns the JSON. Files land in <root>/<device>/<day>/<name>.

    python3 test/mock_upload.py --port 18795 --root /tmp/shots
"""
import argparse, base64, json, os, re, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

RESULTS = {}
MAX_BYTES = int(1.5 * 1024 * 1024)
COUNT = {}


class H(BaseHTTPRequestHandler):
    root = "."

    def log_message(self, fmt, *a):  # one line per upload instead of the default chatter
        pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/exec-result":
            k = parse_qs(u.query).get("k", [""])[0]
            return self._json(200, RESULTS.pop(k, {"ok": False, "error": "unknown result"}))
        return self._json(200, {"ok": True, "service": "GreenGate uploader (mock)", "folder": "set"})

    def do_POST(self):
        t0 = time.time()
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n)
        res = self._store(raw)
        k = uuid.uuid4().hex
        RESULTS[k] = res
        print("%s %s %s %dKB %.0fms" % (time.strftime("%H:%M:%S"), "OK " if res.get("ok") else "ERR",
                                         res.get("path") or res.get("error"), n // 1024, (time.time() - t0) * 1000), flush=True)
        # Google answers the POST with a redirect to script.googleusercontent.com
        self.send_response(302)
        self.send_header("Location", "/exec-result?k=" + k)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _store(self, raw):
        try:
            body = json.loads(raw.decode() or "{}")
        except Exception:
            return {"ok": False, "error": "bad json"}
        if body.get("v") != 1 or not body.get("image"):
            return {"ok": False, "error": "bad request"}
        device = re.sub(r'[\\/:*?"<>|]', "-", str(body.get("device") or "may-con")).strip()[:60] or "may-con"
        hour = int(time.time() // 3600)
        COUNT[(device, hour)] = COUNT.get((device, hour), 0) + 1
        if COUNT[(device, hour)] > 30:
            return {"ok": False, "error": "too many uploads this hour"}
        try:
            data = base64.b64decode(body["image"])
        except Exception:
            return {"ok": False, "error": "bad base64"}
        if len(data) > MAX_BYTES:
            return {"ok": False, "error": "image too large"}
        if len(data) < 4 or data[:2] != b"\xff\xd8":
            return {"ok": False, "error": "not a JPEG"}
        ts = body.get("ts") or ""
        m = re.match(r"(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})", ts)
        if m:
            day, name = m.group(1), "%s-%s-%s" % (m.group(2), m.group(3), m.group(4))
        else:
            day, name = time.strftime("%Y-%m-%d"), time.strftime("%H-%M-%S")
        if body.get("reason") == "parent":
            name += "-bo-me"
        name += ".jpg"
        d = os.path.join(self.root, device, day)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, name), "wb") as f:
            f.write(data)
        return {"ok": True, "id": uuid.uuid4().hex, "name": name, "path": "GreenGate/%s/%s" % (device, day)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=18795)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--root", default="shots-mock")
    a = ap.parse_args()
    H.root = a.root
    os.makedirs(a.root, exist_ok=True)
    print("mock uploader on http://%s:%d/exec -> %s" % (a.bind, a.port, a.root), flush=True)
    ThreadingHTTPServer((a.bind, a.port), H).serve_forever()
