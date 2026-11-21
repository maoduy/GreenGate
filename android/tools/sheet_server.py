"""Serves <dir>/<tab>.csv on :8765 (or argv[2]) for the sheetBase override, and <dir>/lists/<cat>.txt.gz for listsBase."""
import http.server, sys, os
d = sys.argv[1] if len(sys.argv) > 1 else "."
os.chdir(d)
class H(http.server.SimpleHTTPRequestHandler):
    def end_headers(self): self.send_header("Cache-Control", "no-store"); super().end_headers()
    def log_message(self, *a): pass
port = int(sys.argv[2]) if len(sys.argv) > 2 else 8765
http.server.ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()
