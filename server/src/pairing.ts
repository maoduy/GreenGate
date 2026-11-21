// One Durable Object instance ("pairing") maps 6-digit codes to device ids for 10 minutes.
// It is the only place a code lives; a claimed or expired code is gone.

import { DurableObject } from "cloudflare:workers";
import { HttpError, json, errorResponse, readJson } from "./util";

const CODE_TTL_MS = 10 * 60 * 1000;

interface CodeRec { deviceId: string; exp: number; }

export class PairingDO extends DurableObject {
  async fetch(req: Request): Promise<Response> {
    try {
      const url = new URL(req.url);
      if (req.method === "POST" && url.pathname === "/put") {
        const { deviceId } = await readJson<{ deviceId: string }>(req);
        if (!deviceId) throw new HttpError(400, "deviceId required");
        const code = await this.newCode();
        const exp = Date.now() + CODE_TTL_MS;
        await this.ctx.storage.put<CodeRec>("code:" + code, { deviceId, exp });
        await this.schedule();
        return json({ code, exp });
      }
      if (req.method === "POST" && url.pathname === "/take") {
        const { code } = await readJson<{ code: string }>(req);
        if (!/^\d{6}$/.test(code || "")) throw new HttpError(400, "code must be 6 digits");
        const rec = await this.ctx.storage.get<CodeRec>("code:" + code);
        if (!rec || rec.exp < Date.now()) throw new HttpError(404, "code unknown or expired");
        await this.ctx.storage.delete("code:" + code);
        return json({ deviceId: rec.deviceId });
      }
      throw new HttpError(404, "not found");
    } catch (e) { return errorResponse(e); }
  }

  private async newCode(): Promise<string> {
    for (let i = 0; i < 20; i++) {
      const n = crypto.getRandomValues(new Uint32Array(1))[0] % 1_000_000;
      const code = n.toString().padStart(6, "0");
      const rec = await this.ctx.storage.get<CodeRec>("code:" + code);
      if (!rec || rec.exp < Date.now()) return code;
    }
    throw new HttpError(503, "could not allocate a code");
  }

  private async schedule() {
    const cur = await this.ctx.storage.getAlarm();
    if (cur === null) await this.ctx.storage.setAlarm(Date.now() + CODE_TTL_MS + 1000);
  }

  async alarm() {
    const now = Date.now();
    const all = await this.ctx.storage.list<CodeRec>({ prefix: "code:" });
    const dead: string[] = [];
    let next = Infinity;
    for (const [k, v] of all) {
      if (v.exp < now) dead.push(k); else next = Math.min(next, v.exp);
    }
    if (dead.length) await this.ctx.storage.delete(dead);
    if (next < Infinity) await this.ctx.storage.setAlarm(next + 1000);
  }
}
