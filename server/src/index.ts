// GreenGate relay. Routes requests to the pairing object or the device object; holds no state.
// See docs/SPEC.md §5.

import { DeviceDO } from "./device";
import { PairingDO } from "./pairing";
import { SheetDO } from "./sheet";
import { CORS, HttpError, errorResponse, isB64, json, readJson, token } from "./util";

export { DeviceDO, PairingDO, SheetDO };

export interface Env {
  DEVICE: DurableObjectNamespace;
  PAIRING: DurableObjectNamespace;
  SHEET: DurableObjectNamespace;
}

const PLATFORMS = new Set(["windows", "linux", "android", "ios", "mac", "test"]);

export default {
  async fetch(req: Request, env: Env): Promise<Response> {
    const edge = Date.now();
    try {
      if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
      const url = new URL(req.url);
      const p = url.pathname.replace(/\/+$/, "");

      if (p === "/v1/health") return json({ ok: true, now: edge }, 200, { edge });

      if (p === "/v1/pair/start" && req.method === "POST") {
        const b = await readJson<{ devicePub: string; name?: string; platform?: string }>(req);
        if (!isB64(b.devicePub, 32)) throw new HttpError(400, "devicePub must be a 32-byte key in base64");
        const platform = String(b.platform || "").toLowerCase();
        if (!PLATFORMS.has(platform)) throw new HttpError(400, "platform must be one of " + [...PLATFORMS].join(", "));
        const deviceId = crypto.randomUUID();
        const deviceToken = token();
        const dev = env.DEVICE.get(env.DEVICE.idFromName(deviceId));
        const r1 = await dev.fetch("https://do/init", { method: "POST", body: JSON.stringify({ deviceId, devicePub: b.devicePub, name: b.name, platform, deviceToken }) });
        if (!r1.ok) return r1;
        const pairing = env.PAIRING.get(env.PAIRING.idFromName("pairing"));
        const r2 = await pairing.fetch("https://do/put", { method: "POST", body: JSON.stringify({ deviceId }) });
        if (!r2.ok) return r2;
        const { code, exp } = await r2.json<{ code: string; exp: number }>();
        return json({ deviceId, deviceToken, code, codeExpiresAt: exp }, 200, { edge, done: Date.now() });
      }

      if (p === "/v1/pair/claim" && req.method === "POST") {
        const b = await readJson<{ code: string; parentPub: string }>(req);
        if (!isB64(b.parentPub, 32)) throw new HttpError(400, "parentPub must be a 32-byte key in base64");
        const pairing = env.PAIRING.get(env.PAIRING.idFromName("pairing"));
        const r = await pairing.fetch("https://do/take", { method: "POST", body: JSON.stringify({ code: String(b.code || "").trim() }) });
        if (!r.ok) return withCors(r);
        const { deviceId } = await r.json<{ deviceId: string }>();
        const dev = env.DEVICE.get(env.DEVICE.idFromName(deviceId));
        return withCors(await dev.fetch("https://do/claim", { method: "POST", body: JSON.stringify({ parentPub: b.parentPub }) }), edge);
      }

      // The sheet's Apps Script says "something changed": nudge every device following it.
      // Knowing the sheet id is the only requirement (the sheet itself is link-shared), the
      // effect is bounded: one re-read of a public CSV per device per 10 s at most.
      const sm = /^\/v1\/sheet\/([A-Za-z0-9_-]{20,80})\/changed$/.exec(p);
      if (sm && req.method === "POST") {
        const sheet = env.SHEET.get(env.SHEET.idFromName(sm[1]));
        return withCors(await sheet.fetch("https://do/changed", { method: "POST", body: "{}" }), edge);
      }

      const m = /^\/v1\/device\/([0-9a-f-]{36})(\/.*)?$/.exec(p);
      if (m) {
        const dev = env.DEVICE.get(env.DEVICE.idFromName(m[1]));
        const sub = new URL("https://do" + (m[2] || "/"));
        sub.search = url.search;
        // Pass the request through untouched (method, headers, body, WebSocket upgrade).
        const r = await dev.fetch(new Request(sub.toString(), req));
        if (r.status === 101) return r;
        return withCors(r, edge);
      }
      throw new HttpError(404, "not found");
    } catch (e) { return errorResponse(e); }
  },
};

function withCors(r: Response, edge?: number): Response {
  const h = new Headers(r.headers);
  for (const [k, v] of Object.entries(CORS)) h.set(k, v);
  if (edge) h.set("X-GreenGate-T", [h.get("X-GreenGate-T"), `edge=${edge}`].filter(Boolean).join(","));
  return new Response(r.body, { status: r.status, headers: h });
}
