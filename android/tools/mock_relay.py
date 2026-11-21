"""
Mock GreenGate relay for local testing (SPEC §5). Same HTTP + WebSocket API as the
Cloudflare Worker, in memory, with the X-GreenGate-T timing header. Run:

    .venv/bin/python mock_relay.py --port 8787

The emulator reaches the host as 10.0.2.2, so the app's relay URL is http://10.0.2.2:8787.
"""
import argparse, asyncio, json, secrets, time, uuid
from aiohttp import web, WSMsgType

TTL = {"screenshot": 600, "history": 86400, "refresh": 86400}
RESULT_TTL = 600
devices = {}          # id -> dict(devicePub, name, platform, token, parents:{pub: token}, lastSeen, ws, queue:[cmd], results:{cmdId: dict})
codes = {}            # code -> (deviceId, expires)
events = []           # timing log for the report

def now(): return time.time()
def stamp(resp, **kw):
    resp.headers["X-GreenGate-T"] = json.dumps({"server": round(now(), 3), **kw}); return resp
def jerr(status, msg): return web.json_response({"error": msg}, status=status)

def auth_parent(req, dev):
    tok = req.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    return tok and tok in dev["parents"].values()
def auth_device(req, dev):
    tok = req.headers.get("Authorization", "").removeprefix("Bearer ").strip() or req.query.get("token", "")
    return tok == dev["token"]

async def pair_start(req):
    b = await req.json()
    did = uuid.uuid4().hex[:16]
    code = "%06d" % secrets.randbelow(10**6)
    devices[did] = dict(devicePub=b["devicePub"], name=b.get("name", ""), platform=b.get("platform", ""), token=secrets.token_urlsafe(24),
                        parents={}, lastSeen=0, ws=None, queue=[], results={}, created=now())
    codes[code] = (did, now() + 600)
    print(f"[pair] device {did} code {code}")
    return stamp(web.json_response({"deviceId": did, "deviceToken": devices[did]["token"], "code": code}))

async def pair_claim(req):
    b = await req.json()
    ent = codes.pop(b.get("code", ""), None)
    if not ent or ent[1] < now(): return jerr(404, "code unknown or expired")
    did = ent[0]; dev = devices[did]
    ptok = secrets.token_urlsafe(24)
    dev["parents"][b["parentPub"]] = ptok
    if dev["ws"] is not None:
        await dev["ws"].send_json({"t": "parents", "keys": list(dev["parents"])})
    return stamp(web.json_response({"deviceId": did, "devicePub": dev["devicePub"], "parentToken": ptok, "name": dev["name"], "platform": dev["platform"]}))

async def device_get(req):
    dev = devices.get(req.match_info["id"]);  
    if not dev: return jerr(404, "no device")
    if not auth_parent(req, dev): return jerr(401, "bad token")
    return stamp(web.json_response({"deviceId": req.match_info["id"], "name": dev["name"], "platform": dev["platform"], "online": dev["ws"] is not None,
                                    "lastSeen": dev["lastSeen"], "pending": len(dev["queue"])}))

async def device_cmd(req):
    dev = devices.get(req.match_info["id"])
    if not dev: return jerr(404, "no device")
    if not auth_parent(req, dev): return jerr(401, "bad token")
    b = await req.json()
    if b["parentPub"] not in dev["parents"]: return jerr(403, "not a parent of this device")
    cmd = {"cmdId": uuid.uuid4().hex, "parentPub": b["parentPub"], "blob": b["blob"], "type": b.get("type", ""),
           "expires": now() + int(b.get("ttl") or TTL.get(b.get("type", ""), 3600)), "tQueued": now(), "acked": None}
    dev["queue"].append(cmd)
    delivered = False
    if dev["ws"] is not None:
        try:
            await dev["ws"].send_json({"t": "cmd", "cmdId": cmd["cmdId"], "parentPub": cmd["parentPub"], "blob": cmd["blob"]})
            # wait briefly for the ack
            for _ in range(50):
                await asyncio.sleep(0.05)
                if cmd["acked"]: delivered = True; break
        except Exception as e:
            print("[cmd] ws send failed:", e)
    events.append(("cmd", cmd["cmdId"], cmd["type"], cmd["tQueued"], delivered))
    print(f"[cmd] {cmd['type']} {cmd['cmdId'][:8]} queued, delivered={delivered}")
    return stamp(web.json_response({"cmdId": cmd["cmdId"], "delivered": delivered}), queued=round(cmd["tQueued"], 3), acked=cmd["acked"])

async def device_result_get(req):
    dev = devices.get(req.match_info["id"])
    if not dev: return jerr(404, "no device")
    if not auth_parent(req, dev): return jerr(401, "bad token")
    cid = req.match_info["cmdId"]; wait = min(float(req.query.get("wait", "0")), 25)
    t_end = now() + wait
    while True:
        r = dev["results"].get(cid)
        if r:
            dev["results"].pop(cid, None)
            return stamp(web.json_response({"status": "done", "blob": r["blob"]}), stored=round(r["t"], 3), fetched=round(now(), 3))
        q = next((c for c in dev["queue"] if c["cmdId"] == cid), None)
        if q is None: return stamp(web.json_response({"status": "expired"}))
        if q["expires"] < now(): dev["queue"].remove(q); return stamp(web.json_response({"status": "expired"}))
        if now() >= t_end: return stamp(web.json_response({"status": "pending", "acked": q["acked"]}))
        await asyncio.sleep(0.1)

def store_result(dev, cid, blob):
    dev["results"][cid] = {"blob": blob, "t": now()}
    dev["queue"] = [c for c in dev["queue"] if c["cmdId"] != cid]
    events.append(("result", cid, now()))
    print(f"[result] {cid[:8]} stored")

async def device_pending(req):
    dev = devices.get(req.match_info["id"])
    if not dev: return jerr(404, "no device")
    if not auth_device(req, dev): return jerr(401, "bad token")
    dev["lastSeen"] = now()
    live = [c for c in dev["queue"] if c["expires"] > now()]
    return web.json_response([{"cmdId": c["cmdId"], "parentPub": c["parentPub"], "blob": c["blob"]} for c in live])

async def device_result_post(req):
    dev = devices.get(req.match_info["id"])
    if not dev: return jerr(404, "no device")
    if not auth_device(req, dev): return jerr(401, "bad token")
    b = await req.json(); store_result(dev, b["cmdId"], b["blob"]); return web.json_response({})

async def device_ws(req):
    dev = devices.get(req.match_info["id"])
    if not dev or not auth_device(req, dev): return jerr(401, "bad token")
    ws = web.WebSocketResponse(heartbeat=30)
    await ws.prepare(req)
    dev["ws"] = ws; dev["lastSeen"] = now()
    print(f"[ws] device {req.match_info['id']} connected")
    events.append(("connect", req.match_info["id"], now()))
    await ws.send_json({"t": "parents", "keys": list(dev["parents"])})
    for c in [c for c in dev["queue"] if c["expires"] > now()]:
        await ws.send_json({"t": "cmd", "cmdId": c["cmdId"], "parentPub": c["parentPub"], "blob": c["blob"]})
        print(f"[ws] flushed queued {c['type']} {c['cmdId'][:8]}")
    try:
        async for msg in ws:
            if msg.type != WSMsgType.TEXT: continue
            m = json.loads(msg.data); dev["lastSeen"] = now()
            t = m.get("t")
            if t == "ack":
                for c in dev["queue"]:
                    if c["cmdId"] == m["cmdId"]: c["acked"] = round(now(), 3)
            elif t == "result": store_result(dev, m["cmdId"], m["blob"])
            elif t == "hello": print("[ws] hello", m)
            elif t == "register":
                dev["sheet"] = m.get("sheet", ""); print(f"[ws] device follows sheet {dev['sheet']}")
    finally:
        if dev["ws"] is ws: dev["ws"] = None
        print(f"[ws] device {req.match_info['id']} disconnected")
    return ws

async def events_get(req): return web.json_response(events)

async def sheet_changed(req):
    """The sheet's Apps Script (or a test) says the sheet changed: nudge every registered device (plain frame)."""
    sid = req.match_info["sheetId"]; n = 0; t = now()
    for did, dev in devices.items():
        if dev.get("sheet") == sid and dev["ws"] is not None:
            try: await dev["ws"].send_json({"t": "hint", "kind": "refresh", "ts": int(t * 1000)}); n += 1
            except Exception as e: print("[hint] send failed:", e)
    events.append(("hint", sid, t, n)); print(f"[hint] sheet {sid} changed -> {n} device(s)")
    return stamp(web.json_response({"notified": n}), sent=round(t, 3))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8787); a = ap.parse_args()
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app.add_routes([web.post("/v1/pair/start", pair_start), web.post("/v1/pair/claim", pair_claim),
                    web.get("/v1/device/{id}", device_get), web.post("/v1/device/{id}/cmd", device_cmd),
                    web.get("/v1/device/{id}/result/{cmdId}", device_result_get), web.get("/v1/device/{id}/pending", device_pending),
                    web.post("/v1/device/{id}/result", device_result_post), web.get("/v1/device/{id}/ws", device_ws),
                    web.get("/v1/_events", events_get), web.post("/v1/sheet/{sheetId}/changed", sheet_changed)])
    web.run_app(app, host="0.0.0.0", port=a.port, print=lambda *_: print(f"mock relay on :{a.port}"))

if __name__ == "__main__": main()
