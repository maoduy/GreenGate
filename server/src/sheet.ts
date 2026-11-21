// One Durable Object per Google Sheet id: the set of devices that follow that sheet. When the
// sheet's Apps Script reports a change (POST /v1/sheet/<id>/changed, SPEC §5 "hint"), every
// device object is told to push an unencrypted {"t":"hint","kind":"refresh"} frame. Nothing
// about the sheet's content ever reaches the relay - only "it changed".

import { DurableObject } from "cloudflare:workers";
import { HttpError, errorResponse, json } from "./util";

const MIN_INTERVAL_MS = 10_000;        // one hint per sheet per 10 s, whatever the trigger does
const STALE_MS = 30 * 86400_000;       // forget devices that have not registered for a month

interface Reg { deviceId: string; seenAt: number; }

export class SheetDO extends DurableObject {
  async fetch(req: Request): Promise<Response> {
    try {
      const p = new URL(req.url).pathname.replace(/\/+$/, "");
      if (req.method === "POST" && p === "/register") {
        const { deviceId } = await req.json<{ deviceId: string }>();
        if (!/^[0-9a-f-]{36}$/.test(deviceId)) throw new HttpError(400, "bad deviceId");
        await this.ctx.storage.put<Reg>("dev:" + deviceId, { deviceId, seenAt: Date.now() });
        return json({ ok: true });
      }
      if (req.method === "POST" && p === "/unregister") {
        const { deviceId } = await req.json<{ deviceId: string }>();
        await this.ctx.storage.delete("dev:" + deviceId);
        return json({ ok: true });
      }
      if (req.method === "POST" && p === "/changed") {
        const now = Date.now();
        const last = (await this.ctx.storage.get<number>("lastHint")) || 0;
        if (now - last < MIN_INTERVAL_MS) return json({ ok: true, devices: 0, throttled: true });
        await this.ctx.storage.put("lastHint", now);
        const env = this.env as { DEVICE: DurableObjectNamespace };
        // fan out in parallel: a family with several devices gets them all hinted in one round trip
        const regs = [...(await this.ctx.storage.list<Reg>({ prefix: "dev:" }))];
        const stale = regs.filter(([, r]) => now - r.seenAt > STALE_MS).map(([k]) => k);
        if (stale.length) await this.ctx.storage.delete(stale);
        const body = JSON.stringify({ kind: "refresh", ts: now });
        const results = await Promise.all(regs.filter(([, r]) => now - r.seenAt <= STALE_MS).map(async ([, r]) => {
          try {
            const res = await env.DEVICE.get(env.DEVICE.idFromName(r.deviceId)).fetch("https://do/hint", { method: "POST", body });
            return res.ok ? 1 : 0;
          } catch { return 0; }
        }));
        return json({ ok: true, devices: results.reduce((a: number, b) => a + b, 0) });
      }
      throw new HttpError(404, "not found");
    } catch (e) { return errorResponse(e); }
  }
}
