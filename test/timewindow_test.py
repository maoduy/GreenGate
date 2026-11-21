import json, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "proxy"))
import timewindow

vectors = json.load(open(os.path.join(os.path.dirname(__file__), "..", "docs", "timewindow-vectors.json")))
fails = 0
for c in vectors["cases"]:
    try:
        w = timewindow.parse(c["text"])
        got = None if c.get("error") else timewindow.allowed(w, c["weekday"], c["minute"])
        ok = (not c.get("error")) and got == c["allowed"]
    except ValueError:
        got, ok = "error", bool(c.get("error"))
    if not ok:
        fails += 1
        print("FAIL", c, "->", got)
print("%d cases, %d failed" % (len(vectors["cases"]), fails))
sys.exit(1 if fails else 0)
