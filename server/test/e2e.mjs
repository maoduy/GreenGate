// End-to-end test of the relay against `npx wrangler dev --port 8787` (or RELAY=url).
// Plays both sides: a parent (tweetnacl in Node) and a simulated device over WebSocket.
import nacl from "tweetnacl";

const RELAY = process.env.RELAY || "http://127.0.0.1:8787";
const WS = RELAY.replace(/^http/, "ws");
const b64 = u8 => Buffer.from(u8).toString("base64");
const unb64 = s => new Uint8Array(Buffer.from(s, "base64"));
const te = new TextEncoder(), td = new TextDecoder();
let failures = 0;
const check = (name, cond, info = "") => { console.log((cond ? "PASS " : "FAIL ") + name + (info ? "  -- " + info : "")); if (!cond) failures++; };
const sleep = ms => new Promise(r => setTimeout(r, ms));

function seal(obj, theirPub, mySecret) {
  const nonce = nacl.randomBytes(24);
  const box = nacl.box(te.encode(JSON.stringify(obj)), nonce, theirPub, mySecret);
  const out = new Uint8Array(24 + box.length); out.set(nonce); out.set(box, 24);
  return b64(out);
}
function open(blob, theirPub, mySecret) {
  const raw = unb64(blob);
  const msg = nacl.box.open(raw.slice(24), raw.slice(0, 24), theirPub, mySecret);
  if (!msg) throw new Error("box did not open");
  return JSON.parse(td.decode(msg));
}
async function api(path, { method = "GET", body, token } = {}) {
  const t0 = Date.now();
  const r = await fetch(RELAY + path, { method, headers: { "content-type": "application/json", ...(token ? { authorization: "Bearer " + token } : {}) }, body: body ? JSON.stringify(body) : undefined });
  const text = await r.text();
  let data; try { data = JSON.parse(text); } catch { data = text; }
  return { status: r.status, data, timing: r.headers.get("x-greengate-t"), ms: Date.now() - t0 };
}

const parent = nacl.box.keyPair();
const device = nacl.box.keyPair();

// ---------------------------------------------------------------- health + pairing
let r = await api("/v1/health");
check("health", r.status === 200 && r.data.ok, `${r.ms}ms (first request = cold start)`);
r = await api("/v1/pair/start", { method: "POST", body: { devicePub: b64(device.publicKey), name: "Máy test", platform: "test" } });
check("pair/start", r.status === 200 && /^\d{6}$/.test(r.data.code), JSON.stringify(r.data));
const { deviceId, deviceToken, code } = r.data;
r = await api("/v1/pair/claim", { method: "POST", body: { code: "000000", parentPub: b64(parent.publicKey) } });
check("claim with a wrong code is refused", r.status === 404);
r = await api("/v1/pair/claim", { method: "POST", body: { code, parentPub: b64(parent.publicKey) } });
check("pair/claim", r.status === 200 && r.data.devicePub === b64(device.publicKey) && r.data.parentToken, JSON.stringify(r.data).slice(0, 120));
const parentToken = r.data.parentToken;
r = await api("/v1/pair/claim", { method: "POST", body: { code, parentPub: b64(parent.publicKey) } });
check("a code works once", r.status === 404);
r = await api(`/v1/device/${deviceId}`);
check("device info without token -> 401", r.status === 401);
r = await api(`/v1/device/${deviceId}`, { token: parentToken });
check("device info", r.status === 200 && r.data.online === false && r.data.name === "Máy test", JSON.stringify(r.data));

// ---------------------------------------------------------------- command while OFFLINE -> queued
const sendCmd = async (type, params = {}, ttl) => {
  const env = { v: 1, id: crypto.randomUUID(), type, ts: Date.now(), params };
  const blob = seal(env, device.publicKey, parent.secretKey);
  const res = await api(`/v1/device/${deviceId}/cmd`, { method: "POST", token: parentToken, body: { parentPub: b64(parent.publicKey), blob, type, ttl } });
  return { ...res, env };
};
r = await sendCmd("refresh");
check("command queued while offline", r.status === 200 && r.data.delivered === false && r.data.cmdId, JSON.stringify(r.data));
const queuedId = r.data.cmdId;
let r2 = await api(`/v1/device/${deviceId}/result/${queuedId}?wait=1`, { token: parentToken });
check("result pending while offline", r2.data.status === "pending" && r2.data.delivered === false, JSON.stringify(r2.data));
r2 = await api(`/v1/device/${deviceId}`, { token: parentToken });
check("pending count = 1", r2.data.pending === 1, JSON.stringify(r2.data));

// ---------------------------------------------------------------- device connects: queue flushed
const received = [];
const ws = new WebSocket(`${WS}/v1/device/${deviceId}/ws?token=${deviceToken}`);
let parentsSeen = null;
const hints = [];
ws.onmessage = ev => {
  const m = JSON.parse(ev.data);
  if (m.t === "parents") parentsSeen = m.keys;
  if (m.t === "hint") hints.push({ ...m, at: Date.now() });
  if (m.t === "cmd") {
    received.push(m);
    ws.send(JSON.stringify({ t: "ack", cmdId: m.cmdId }));
    const env = open(m.blob, unb64(m.parentPub), device.secretKey);
    const result = { v: 1, id: env.id, ok: true, ts: Date.now(), type: env.type, data: { echo: env.params, bytes: "x".repeat(env.params.size || 0) } };
    ws.send(JSON.stringify({ t: "result", cmdId: m.cmdId, blob: seal(result, unb64(m.parentPub), device.secretKey) }));
  }
};
await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
await sleep(500);
check("device told who the parents are", Array.isArray(parentsSeen) && parentsSeen[0] === b64(parent.publicKey));
check("queued command flushed on connect", received.length === 1 && received[0].cmdId === queuedId, `got ${received.length}`);
r2 = await api(`/v1/device/${deviceId}/result/${queuedId}?wait=10`, { token: parentToken });
check("queued result arrives", r2.data.status === "done", r2.timing);
if (r2.data.status === "done") {
  const env = open(r2.data.blob, device.publicKey, parent.secretKey);
  check("result decrypts and echoes", env.ok === true && env.type === "refresh", JSON.stringify(env).slice(0, 80));
}
r2 = await api(`/v1/device/${deviceId}/result/${queuedId}?wait=0`, { token: parentToken });
check("result deleted after one fetch", r2.data.status === "expired", JSON.stringify(r2.data));

// ---------------------------------------------------------------- sheet-changed hint (SPEC §5)
const SHEET = "1TESTSHEETxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" + Math.random().toString(36).slice(2, 6);
ws.send(JSON.stringify({ t: "hello", platform: "test", version: "e2e", sheet: SHEET }));
await sleep(300);
let th = Date.now();
r = await api(`/v1/sheet/${SHEET}/changed`, { method: "POST", body: {} });
await sleep(300);
check("sheet changed -> one device hinted", r.data.ok === true && r.data.devices === 1, JSON.stringify(r.data));
check("device received refresh hint", hints.length === 1 && hints[0].kind === "refresh", `hints=${hints.length}`);
if (hints.length) console.log(`sheet-changed webhook -> hint on the device socket: ${hints[0].at - th} ms`);
r = await api(`/v1/sheet/${SHEET}/changed`, { method: "POST", body: {} });
check("second change within 10 s is throttled", r.data.throttled === true, JSON.stringify(r.data));
r = await api(`/v1/sheet/UNKNOWNSHEETxxxxxxxxxxxxxxxxxx/changed`, { method: "POST", body: {} });
check("unknown sheet hints nobody", r.data.ok === true && r.data.devices === 0, JSON.stringify(r.data));

// ---------------------------------------------------------------- command while ONLINE: timing
const rtts = [];
for (let i = 0; i < 10; i++) {
  const t0 = Date.now();
  r = await sendCmd("screenshot", { size: 600000 });
  const rr = await api(`/v1/device/${deviceId}/result/${r.data.cmdId}?wait=25`, { token: parentToken });
  const rtt = Date.now() - t0;
  rtts.push(rtt);
  if (i === 0) {
    check("online command delivered+acked", r.data.delivered === true, r.timing);
    check("600 KB payload round trip", rr.data.status === "done" && rr.data.blob.length > 800000, `blob ${rr.data.blob?.length} chars, ${r.timing} | ${rr.timing}`);
  }
}
rtts.sort((a, b) => a - b);
console.log(`simulated device (same host): 10 x 600KB round trips  median=${rtts[5]}ms  p95=${rtts[9]}ms  min=${rtts[0]}ms`);

// ---------------------------------------------------------------- guards
r = await api(`/v1/device/${deviceId}/cmd`, { method: "POST", token: parentToken, body: { parentPub: b64(nacl.box.keyPair().publicKey), blob: "AAAA", type: "status" } });
check("unknown parentPub refused", r.status === 403);
r = await api(`/v1/device/${deviceId}/cmd`, { method: "POST", token: "wrong", body: { parentPub: b64(parent.publicKey), blob: "AAAA", type: "status" } });
check("wrong parent token refused", r.status === 401);
r = await api(`/v1/device/${deviceId}/cmd`, { method: "POST", token: parentToken, body: { parentPub: b64(parent.publicKey), blob: "A".repeat(1_100_000), type: "status" } });
check("over-size body refused", r.status === 413 || r.status === 400, `status ${r.status}`);
r = await api(`/v1/device/${deviceId}/pending`, { token: deviceToken });
check("device pending list (polling fallback)", r.status === 200 && Array.isArray(r.data), JSON.stringify(r.data).slice(0, 60));
r = await api(`/v1/device/${deviceId}`, { token: parentToken });
check("device shows online", r.data.online === true);

// ---------------------------------------------------------------- expiry
r = await sendCmd("status", {}, 10);
const shortId = r.data.cmdId;
ws.close();
await sleep(500);
r = await api(`/v1/device/${deviceId}`, { token: parentToken });
check("device shows offline after close", r.data.online === false && r.data.lastSeen > 0, JSON.stringify(r.data));

// ---------------------------------------------------------------- unpair
r = await api(`/v1/device/${deviceId}`, { method: "DELETE", token: parentToken });
check("unpair", r.status === 200);
r = await api(`/v1/device/${deviceId}`, { token: parentToken });
check("gone after unpair", r.status === 404 || r.status === 401, `status ${r.status}`);

console.log(failures ? `\n${failures} FAILED` : "\nALL PASSED");
process.exit(failures ? 1 : 0);
