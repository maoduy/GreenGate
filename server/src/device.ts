// One Durable Object per child device. Holds exactly what docs/SPEC.md §5 allows:
// identity, keys, tokens, last-seen, queued encrypted commands and their encrypted
// results until delivered. The device's WebSocket uses the hibernation API, so an idle
// connected device costs nothing.

import { DurableObject } from "cloudflare:workers";
import { HttpError, MAX_BLOB, bearer, errorResponse, fmtTiming, isB64, json, readJson, same, token } from "./util";

const RESULT_TTL_MS = 600_000;
const ACK_WAIT_MS = 3000;
const RATE_LIMIT = 60;                // commands per hour per device
const DEFAULT_TTL: Record<string, number> = { screenshot: 600, history: 86400, refresh: 86400 };
const MAX_TTL = 7 * 86400;

interface Parent { pub: string; token: string; addedAt: number; }
interface Meta {
  deviceId: string; devicePub: string; name: string; platform: string; deviceToken: string;
  parents: Parent[]; createdAt: number; lastSeen: number; version?: string; sheet?: string;
}
interface Cmd {
  cmdId: string; parentPub: string; blob: string; type: string;
  sentAt: number; expiresAt: number; deliveredAt?: number; ackedAt?: number;
}
interface Res { cmdId: string; blob: string; storedAt: number; expiresAt: number; }

export class DeviceDO extends DurableObject {
  private resultWaiters = new Map<string, Array<() => void>>();
  private ackWaiters = new Map<string, () => void>();

  constructor(ctx: DurableObjectState, env: unknown) {
    super(ctx, env as never);
    // Keep-alive handled by the runtime: the device may send {"t":"ping"} and gets a pong
    // without waking this object.
    this.ctx.setWebSocketAutoResponse(new WebSocketRequestResponsePair('{"t":"ping"}', '{"t":"pong"}'));
  }

  // ------------------------------------------------------------------ http
  async fetch(req: Request): Promise<Response> {
    const recv = Date.now();
    try {
      const url = new URL(req.url);
      const p = url.pathname.replace(/\/+$/, "") || "/";
      const meta = await this.ctx.storage.get<Meta>("meta");

      if (req.method === "POST" && p === "/init") return await this.init(req);
      if (!meta) throw new HttpError(404, "unknown device");

      if (req.method === "POST" && p === "/claim") return await this.claim(req, meta);
      if (req.method === "POST" && p === "/hint") {            // from SheetDO only (internal)
        const b = await req.json<{ kind: string; ts: number }>();
        if (!this.online()) return json({ ok: false, online: false });
        this.broadcast({ t: "hint", kind: String(b.kind || "refresh"), ts: Number(b.ts) || Date.now() });
        return json({ ok: true, online: true });
      }
      if (p === "/ws") return await this.openSocket(req, meta);

      if (req.method === "GET" && p === "/pending") { this.authDevice(req, meta); return await this.pending(meta, recv); }
      if (req.method === "POST" && p === "/result") { this.authDevice(req, meta); return await this.postResult(req, recv); }

      this.authParent(req, meta);
      if (req.method === "GET" && p === "/") return await this.info(meta, recv);
      if (req.method === "POST" && p === "/cmd") return await this.command(req, meta, recv);
      const m = /^\/result\/([A-Za-z0-9-]+)$/.exec(p);
      if (req.method === "GET" && m) return await this.getResult(m[1], Number(url.searchParams.get("wait") || 0), recv);
      if (req.method === "DELETE" && p === "/") return await this.unpair();
      throw new HttpError(404, "not found");
    } catch (e) { return errorResponse(e); }
  }

  private authParent(req: Request, meta: Meta) {
    const t = bearer(req);
    if (!t || !meta.parents.some(pr => same(pr.token, t))) throw new HttpError(401, "parent token required");
  }
  private authDevice(req: Request, meta: Meta) {
    const t = bearer(req);
    if (!t || !same(meta.deviceToken, t)) throw new HttpError(401, "device token required");
  }

  private async init(req: Request): Promise<Response> {
    const b = await readJson<Partial<Meta>>(req);
    if (await this.ctx.storage.get("meta")) throw new HttpError(409, "already initialised");
    if (!b.deviceId || !isB64(b.devicePub, 32) || !b.deviceToken) throw new HttpError(400, "bad init");
    const meta: Meta = {
      deviceId: b.deviceId, devicePub: b.devicePub, deviceToken: b.deviceToken,
      name: String(b.name || "").slice(0, 60), platform: String(b.platform || "").slice(0, 20),
      parents: [], createdAt: Date.now(), lastSeen: 0,
    };
    await this.ctx.storage.put("meta", meta);
    return json({ ok: true });
  }

  private async claim(req: Request, meta: Meta): Promise<Response> {
    const { parentPub } = await readJson<{ parentPub: string }>(req);
    if (!isB64(parentPub, 32)) throw new HttpError(400, "parentPub must be a 32-byte key in base64");
    let pr = meta.parents.find(x => x.pub === parentPub);
    if (!pr) {
      if (meta.parents.length >= 5) throw new HttpError(409, "too many parents");
      pr = { pub: parentPub, token: token(), addedAt: Date.now() };
      meta.parents.push(pr);
      await this.ctx.storage.put("meta", meta);
    }
    this.broadcast({ t: "parents", keys: meta.parents.map(x => x.pub) });
    return json({ deviceId: meta.deviceId, devicePub: meta.devicePub, parentToken: pr.token,
                  name: meta.name, platform: meta.platform });
  }

  private async info(meta: Meta, recv: number): Promise<Response> {
    const cmds = await this.ctx.storage.list<Cmd>({ prefix: "cmd:" });
    const now = Date.now();
    let pending = 0;
    for (const c of cmds.values()) if (!c.deliveredAt && c.expiresAt > now) pending++;
    return json({ deviceId: meta.deviceId, name: meta.name, platform: meta.platform, version: meta.version,
                  online: this.online(), lastSeen: meta.lastSeen, pending, parents: meta.parents.length },
                200, { recv, done: Date.now() });
  }

  private async command(req: Request, meta: Meta, recv: number): Promise<Response> {
    const b = await readJson<{ parentPub: string; blob: string; type: string; ttl?: number }>(req);
    if (!meta.parents.some(x => x.pub === b.parentPub)) throw new HttpError(403, "parentPub is not paired with this device");
    if (!isB64(b.blob) || b.blob.length > MAX_BLOB) throw new HttpError(400, "blob must be base64, at most " + MAX_BLOB + " chars");
    const type = String(b.type || "").slice(0, 32);
    if (!type) throw new HttpError(400, "type required");
    await this.rateLimit();
    const ttl = Math.min(MAX_TTL, Math.max(10, Number(b.ttl) || DEFAULT_TTL[type] || 3600));
    const cmd: Cmd = { cmdId: crypto.randomUUID(), parentPub: b.parentPub, blob: b.blob, type,
                       sentAt: recv, expiresAt: recv + ttl * 1000 };
    await this.ctx.storage.put("cmd:" + cmd.cmdId, cmd);
    await this.schedule();
    let delivered = false;
    if (this.online()) {
      const acked = new Promise<boolean>(resolve => {
        const timer = setTimeout(() => { this.ackWaiters.delete(cmd.cmdId); resolve(false); }, ACK_WAIT_MS);
        this.ackWaiters.set(cmd.cmdId, () => { clearTimeout(timer); resolve(true); });
      });
      this.broadcast({ t: "cmd", cmdId: cmd.cmdId, parentPub: cmd.parentPub, blob: cmd.blob, type });
      cmd.deliveredAt = Date.now();
      await this.ctx.storage.put("cmd:" + cmd.cmdId, cmd);
      delivered = await acked;
    }
    const t: Record<string, number> = { recv, delivered: cmd.deliveredAt || 0, acked: cmd.ackedAt || 0, done: Date.now() };
    return json({ cmdId: cmd.cmdId, delivered, online: this.online(), expiresAt: cmd.expiresAt }, 200, t);
  }

  private async rateLimit() {
    const now = Date.now();
    const r = (await this.ctx.storage.get<{ start: number; n: number }>("rate")) || { start: now, n: 0 };
    if (now - r.start > 3600_000) { r.start = now; r.n = 0; }
    if (r.n >= RATE_LIMIT) throw new HttpError(429, "too many commands this hour");
    r.n++;
    await this.ctx.storage.put("rate", r);
  }

  private async getResult(cmdId: string, wait: number, recv: number): Promise<Response> {
    const deadline = Date.now() + Math.min(30, Math.max(0, wait)) * 1000;
    for (;;) {
      const res = await this.ctx.storage.get<Res>("res:" + cmdId);
      const cmd = await this.ctx.storage.get<Cmd>("cmd:" + cmdId);
      if (res) {
        await this.ctx.storage.delete(["res:" + cmdId, "cmd:" + cmdId]);      // fetched once, then gone
        const t = { sent: cmd?.sentAt || 0, delivered: cmd?.deliveredAt || 0, acked: cmd?.ackedAt || 0,
                    stored: res.storedAt, recv, done: Date.now() };
        return json({ status: "done", blob: res.blob, type: cmd?.type }, 200, t);
      }
      if (!cmd || cmd.expiresAt < Date.now()) {
        if (cmd) await this.ctx.storage.delete("cmd:" + cmdId);
        return json({ status: "expired" }, 200, { recv, done: Date.now() });
      }
      const left = deadline - Date.now();
      if (left <= 0) {
        return json({ status: "pending", delivered: !!cmd.deliveredAt, online: this.online() }, 200, { recv, done: Date.now() });
      }
      await new Promise<void>(resolve => {
        const timer = setTimeout(resolve, Math.min(left, 30_000));
        const list = this.resultWaiters.get(cmdId) || [];
        list.push(() => { clearTimeout(timer); resolve(); });
        this.resultWaiters.set(cmdId, list);
      });
    }
  }

  private async unpair(): Promise<Response> {
    for (const ws of this.ctx.getWebSockets()) { try { ws.close(1000, "unpaired"); } catch {} }
    await this.ctx.storage.deleteAll();
    await this.ctx.storage.deleteAlarm();
    return json({ ok: true });
  }

  // ------------------------------------------------------------------ device side
  private async pending(meta: Meta, recv: number): Promise<Response> {
    meta.lastSeen = Date.now();
    await this.ctx.storage.put("meta", meta);
    const out = [];
    const now = Date.now();
    for (const [k, c] of await this.ctx.storage.list<Cmd>({ prefix: "cmd:" })) {
      if (c.expiresAt < now) { await this.ctx.storage.delete(k); continue; }
      if (c.deliveredAt && c.ackedAt) continue;
      c.deliveredAt = c.deliveredAt || now; c.ackedAt = now;
      await this.ctx.storage.put(k, c);
      out.push({ cmdId: c.cmdId, parentPub: c.parentPub, blob: c.blob, type: c.type });
    }
    return json(out, 200, { recv, done: Date.now() });
  }

  private async postResult(req: Request, recv: number): Promise<Response> {
    const { cmdId, blob } = await readJson<{ cmdId: string; blob: string }>(req);
    await this.storeResult(cmdId, blob);
    return json({ ok: true }, 200, { recv, done: Date.now() });
  }

  private async storeResult(cmdId: string, blob: string) {
    if (!cmdId || !isB64(blob) || blob.length > MAX_BLOB) throw new HttpError(400, "bad result");
    const cmd = await this.ctx.storage.get<Cmd>("cmd:" + cmdId);
    if (!cmd) throw new HttpError(404, "unknown command");
    const now = Date.now();
    cmd.ackedAt = cmd.ackedAt || now; cmd.deliveredAt = cmd.deliveredAt || now;
    await this.ctx.storage.put("cmd:" + cmdId, cmd);
    await this.ctx.storage.put<Res>("res:" + cmdId, { cmdId, blob, storedAt: now, expiresAt: now + RESULT_TTL_MS });
    await this.schedule();
    const waiters = this.resultWaiters.get(cmdId);
    if (waiters) { this.resultWaiters.delete(cmdId); for (const w of waiters) w(); }
  }

  private async openSocket(req: Request, meta: Meta): Promise<Response> {
    if (req.headers.get("upgrade")?.toLowerCase() !== "websocket") throw new HttpError(426, "websocket expected");
    const t = bearer(req);
    if (!t || !same(meta.deviceToken, t)) throw new HttpError(401, "device token required");
    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];
    // One live connection per device: a reconnecting agent must not leave ghosts behind.
    for (const old of this.ctx.getWebSockets()) { try { old.close(1000, "replaced"); } catch {} }
    this.ctx.acceptWebSocket(server, ["device"]);
    meta.lastSeen = Date.now();
    await this.ctx.storage.put("meta", meta);
    server.send(JSON.stringify({ t: "parents", keys: meta.parents.map(x => x.pub) }));
    await this.flush(server);
    return new Response(null, { status: 101, webSocket: client });
  }

  /** Send every queued, unexpired command that has not been acked yet. */
  private async flush(ws: WebSocket) {
    const now = Date.now();
    for (const [k, c] of await this.ctx.storage.list<Cmd>({ prefix: "cmd:" })) {
      if (c.expiresAt < now) { await this.ctx.storage.delete(k); continue; }
      if (c.ackedAt) continue;
      if (c.deliveredAt && now - c.deliveredAt < 10_000) continue;   // just sent, ack still in flight
      try { ws.send(JSON.stringify({ t: "cmd", cmdId: c.cmdId, parentPub: c.parentPub, blob: c.blob, type: c.type })); }
      catch { break; }
      c.deliveredAt = c.deliveredAt || Date.now();
      await this.ctx.storage.put(k, c);
    }
  }

  async webSocketMessage(ws: WebSocket, message: string | ArrayBuffer) {
    if (typeof message !== "string" || message.length > MAX_BLOB + 1000) return;
    let m: any;
    try { m = JSON.parse(message); } catch { return; }
    const meta = await this.ctx.storage.get<Meta>("meta");
    if (!meta) return;
    meta.lastSeen = Date.now();
    try {
      if (m.t === "result") {
        await this.storeResult(String(m.cmdId), String(m.blob));
        ws.send(JSON.stringify({ t: "stored", cmdId: m.cmdId }));
      } else if (m.t === "ack") {
        const cmd = await this.ctx.storage.get<Cmd>("cmd:" + m.cmdId);
        if (cmd && !cmd.ackedAt) { cmd.ackedAt = Date.now(); await this.ctx.storage.put("cmd:" + m.cmdId, cmd); }
        const w = this.ackWaiters.get(String(m.cmdId));
        if (w) { this.ackWaiters.delete(String(m.cmdId)); w(); }
      } else if (m.t === "hello" || m.t === "register") {
        if (m.platform) meta.platform = String(m.platform).slice(0, 20);
        if (m.version) meta.version = String(m.version).slice(0, 20);
        if (typeof m.sheet === "string" && /^[A-Za-z0-9_-]{20,80}$/.test(m.sheet)) await this.follow(meta, m.sheet);
        if (m.t === "hello") await this.flush(ws);
      }
    } catch (e) {
      try { ws.send(JSON.stringify({ t: "error", cmdId: m.cmdId, error: (e as Error).message })); } catch {}
    }
    await this.ctx.storage.put("meta", meta);
  }

  async webSocketClose(ws: WebSocket) { await this.touch(); try { ws.close(); } catch {} }
  async webSocketError(ws: WebSocket) { await this.touch(); try { ws.close(); } catch {} }

  private async touch() {
    const meta = await this.ctx.storage.get<Meta>("meta");
    if (meta) { meta.lastSeen = Date.now(); await this.ctx.storage.put("meta", meta); }
  }

  /** Register with the sheet's object so a "sheet changed" webhook can reach this device. */
  private async follow(meta: Meta, sheet: string) {
    const env = this.env as { SHEET: DurableObjectNamespace };
    if (meta.sheet && meta.sheet !== sheet) {
      try { await env.SHEET.get(env.SHEET.idFromName(meta.sheet)).fetch("https://do/unregister", { method: "POST", body: JSON.stringify({ deviceId: meta.deviceId }) }); } catch {}
    }
    meta.sheet = sheet;
    try { await env.SHEET.get(env.SHEET.idFromName(sheet)).fetch("https://do/register", { method: "POST", body: JSON.stringify({ deviceId: meta.deviceId }) }); } catch {}
  }

  private online(): boolean { return this.ctx.getWebSockets("device").length > 0; }

  private broadcast(obj: unknown) {
    const s = JSON.stringify(obj);
    for (const ws of this.ctx.getWebSockets("device")) { try { ws.send(s); } catch {} }
  }

  // ------------------------------------------------------------------ expiry
  private async schedule() {
    let next = Infinity;
    for (const c of (await this.ctx.storage.list<Cmd>({ prefix: "cmd:" })).values()) next = Math.min(next, c.expiresAt);
    for (const r of (await this.ctx.storage.list<Res>({ prefix: "res:" })).values()) next = Math.min(next, r.expiresAt);
    if (next < Infinity) {
      const cur = await this.ctx.storage.getAlarm();
      if (cur === null || cur > next + 1000) await this.ctx.storage.setAlarm(next + 1000);
    }
  }

  async alarm() {
    const now = Date.now();
    const dead: string[] = [];
    for (const [k, c] of await this.ctx.storage.list<Cmd>({ prefix: "cmd:" })) if (c.expiresAt < now) dead.push(k);
    for (const [k, r] of await this.ctx.storage.list<Res>({ prefix: "res:" })) if (r.expiresAt < now) dead.push(k, "cmd:" + r.cmdId);
    if (dead.length) await this.ctx.storage.delete([...new Set(dead)]);
    await this.schedule();
  }
}
