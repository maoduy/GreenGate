"""
Parent-side test client for the relay (what the web app will do, from a terminal).

    parent_cli.py --relay http://127.0.0.1:8787 claim 123456            # pair, writes parent.json
    parent_cli.py screenshot [--wait 60]                                 # saves shot-<time>.jpg
    parent_cli.py history 11-2026                                        # saves history-11-2026.csv
    parent_cli.py status | refresh | pause 30 | resume
Prints timings: sent -> acked -> stored -> fetched (ms).
"""
import argparse, base64, gzip, json, os, sys, time, uuid
import requests
from nacl.public import PrivateKey, PublicKey, Box
from nacl.utils import random as nrandom

STATE = os.path.join(os.path.dirname(__file__), "parent.json")

def load():
    if os.path.exists(STATE): return json.load(open(STATE))
    sk = PrivateKey.generate()
    st = {"priv": base64.b64encode(bytes(sk)).decode(), "pub": base64.b64encode(bytes(sk.public_key)).decode(), "devices": {}}
    json.dump(st, open(STATE, "w"), indent=1); return st
def save(st): json.dump(st, open(STATE, "w"), indent=1)

def seal(st, devpub, env):
    box = Box(PrivateKey(base64.b64decode(st["priv"])), PublicKey(base64.b64decode(devpub)))
    nonce = nrandom(Box.NONCE_SIZE)
    return base64.b64encode(box.encrypt(json.dumps(env).encode(), nonce)).decode()   # nonce||mac||cipher
def open_(st, devpub, blob):
    box = Box(PrivateKey(base64.b64decode(st["priv"])), PublicKey(base64.b64decode(devpub)))
    return json.loads(box.decrypt(base64.b64decode(blob)).decode())

def timing(resp):
    """X-GreenGate-T: JSON from the mock, 'k=v,k=v' from the Worker. -> dict of floats (seconds)."""
    raw = resp.headers.get("X-GreenGate-T", "")
    try: d = json.loads(raw)
    except Exception:
        d = {}
        for part in raw.split(","):
            if "=" in part:
                k, v = part.split("=", 1)
                try: d[k.strip()] = float(v)
                except ValueError: pass
    out = {}
    for k, v in d.items():
        if isinstance(v, (int, float)): out[k] = v / 1000 if v > 1e11 else v      # ms epoch -> s
    return out

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--relay", default=None); ap.add_argument("--device", default=None)
    ap.add_argument("--wait", type=int, default=60); ap.add_argument("cmd"); ap.add_argument("arg", nargs="?")
    a = ap.parse_args(); st = load()
    relay = a.relay or st.get("relay")
    if a.cmd == "claim":
        r = requests.post(relay + "/v1/pair/claim", json={"code": a.arg, "parentPub": st["pub"]}, timeout=15); r.raise_for_status(); d = r.json()
        st["devices"][d["deviceId"]] = {"devicePub": d["devicePub"], "parentToken": d["parentToken"], "name": d["name"], "platform": d["platform"]}
        st["relay"] = relay; st["last"] = d["deviceId"]; save(st); print("paired:", d); return
    did = a.device or st.get("last"); dev = st["devices"][did]; H = {"Authorization": "Bearer " + dev["parentToken"]}
    if a.cmd == "info":
        print(requests.get(f"{relay}/v1/device/{did}", headers=H).json()); return
    params = {}
    if a.cmd == "history": params = {"month": a.arg or time.strftime("%m-%Y")}
    if a.cmd == "pause": params = {"minutes": int(a.arg or 60)}
    if a.cmd == "settings": params = json.loads(a.arg)
    env = {"v": 1, "id": uuid.uuid4().hex, "type": a.cmd, "ts": int(time.time() * 1000), "params": params}
    t_sent = time.time()
    r = requests.post(f"{relay}/v1/device/{did}/cmd", json={"parentPub": st["pub"], "blob": seal(st, dev["devicePub"], env), "type": a.cmd}, headers=H, timeout=30)
    r.raise_for_status(); cmd = r.json(); th = timing(r)
    print(f"sent {a.cmd}: cmdId={cmd['cmdId'][:8]} delivered={cmd['delivered']} ack={'%.0f ms' % ((th['acked'] - t_sent) * 1000) if th.get('acked') else '-'}")
    deadline = time.time() + a.wait
    while time.time() < deadline:
        rr = requests.get(f"{relay}/v1/device/{did}/result/{cmd['cmdId']}", params={"wait": 25}, headers=H, timeout=40); rr.raise_for_status(); res = rr.json()
        if res["status"] == "done":
            th = timing(rr); t_fetched = time.time()
            out = open_(st, dev["devicePub"], res["blob"])
            print(f"result ok={out.get('ok')} type={out.get('type')} error={out.get('error')}")
            print(f"timing: sent->stored {((th.get('stored', t_fetched)) - t_sent) * 1000:.0f} ms, sent->fetched {(t_fetched - t_sent) * 1000:.0f} ms, "
                  f"device received->done {out.get('tDone', 0) - out.get('tReceived', 0)} ms")
            data = out.get("data") or {}
            if a.cmd == "screenshot" and data.get("b64"):
                fn = time.strftime("shot-%Y%m%d-%H%M%S.jpg"); open(fn, "wb").write(base64.b64decode(data["b64"])); print("saved", fn, data.get("bytes"), "bytes")
            elif a.cmd == "history" and data.get("b64"):
                fn = f"history-{data.get('month')}.csv"; open(fn, "wb").write(gzip.decompress(base64.b64decode(data["b64"]))); print("saved", fn, data.get("rows"), "rows")
            else: print(json.dumps(data, ensure_ascii=False, indent=1)[:2000])
            return
        if res["status"] == "expired": print("expired"); return
        print("  pending...", res.get("acked") and "acked" or "not acked yet")
    print("timeout waiting for result")

if __name__ == "__main__": main()
