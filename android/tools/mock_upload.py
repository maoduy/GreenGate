"""
Mock of the parents' Apps Script web app (SPEC §8) for local tests. Like Google, the POST is
answered with a 302 to a result URL that serves the JSON. Files land in <root>/<device>/<day>/<HH-MM-SS>.jpg.

    .venv/bin/python mock_upload.py --port 18795 --root /tmp/drive
The emulator reaches it as http://10.0.2.2:18795/exec
"""
import argparse, base64, json, os, re, time, uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = "/tmp/greengate-drive"; results = {}; log = []

class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _json(self, code, obj):
        b = json.dumps(obj).encode(); self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        m = re.match(r"^/exec-result\?id=(\w+)", self.path)
        if m and m.group(1) in results: return self._json(200, results.pop(m.group(1)))
        if self.path.startswith("/_log"): return self._json(200, log)
        self._json(404, {"ok": False, "error": "not found"})
    def do_POST(self):
        t0 = time.time()
        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n)
        try:
            j = json.loads(raw); img = base64.b64decode(j["image"])
            if j.get("v") != 1 or not j.get("device"): raise ValueError("bad envelope")
            if len(img) > 1_500_000: raise ValueError("image too large")
            if img[:3] != b"\xff\xd8\xff": raise ValueError("not a JPEG")
            dev = re.sub(r"[^\w .-]", "_", j["device"])[:60] or "device"
            ts = j.get("ts", "")
            day = ts[:10] if re.match(r"\d{4}-\d{2}-\d{2}", ts) else time.strftime("%Y-%m-%d")
            name = (ts[11:19].replace(":", "-") if len(ts) >= 19 else time.strftime("%H-%M-%S")) + ("" if j.get("reason") != "parent" else "-parent") + ".jpg"
            d = os.path.join(ROOT, dev, day); os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, name), "wb") as f: f.write(img)
            res = {"ok": True, "id": uuid.uuid4().hex, "name": name, "path": f"GreenGate/{dev}/{day}"}
            log.append({"t": round(t0, 3), "bytes": len(img), "reason": j.get("reason"), "device": dev, "name": name, "ms": round((time.time() - t0) * 1000, 1)})
            print(f"[upload] {dev}/{day}/{name} {len(img)} B reason={j.get('reason')} body={n} B in {(time.time()-t0)*1000:.0f} ms")
        except Exception as e:
            res = {"ok": False, "error": str(e)}; print("[upload] rejected:", e)
        rid = uuid.uuid4().hex; results[rid] = res
        self.send_response(302); self.send_header("Location", f"/exec-result?id={rid}"); self.send_header("Content-Length", "0"); self.end_headers()

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=18795); ap.add_argument("--root", default=ROOT); a = ap.parse_args()
    ROOT = a.root; os.makedirs(ROOT, exist_ok=True)
    print(f"mock upload on :{a.port} -> {ROOT}")
    ThreadingHTTPServer(("0.0.0.0", a.port), H).serve_forever()
