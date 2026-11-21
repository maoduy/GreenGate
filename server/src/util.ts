// Small helpers shared by the Worker and the Durable Objects.

export const MAX_BODY = 1024 * 1024;          // 1 MB: anything bigger is refused outright
export const MAX_BLOB = 950_000;              // base64 characters per encrypted blob

export const CORS: Record<string, string> = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
  "Access-Control-Allow-Headers": "Authorization,Content-Type",
  "Access-Control-Expose-Headers": "X-GreenGate-T",
  "Access-Control-Max-Age": "86400",
};

export class HttpError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

/** JSON response with CORS and the timing header. */
export function json(body: unknown, status = 200, timing?: Record<string, number>, extra?: Record<string, string>): Response {
  const h: Record<string, string> = { "Content-Type": "application/json; charset=utf-8", ...CORS, ...(extra || {}) };
  if (timing) h["X-GreenGate-T"] = fmtTiming(timing);
  return new Response(JSON.stringify(body), { status, headers: h });
}

export function fmtTiming(t: Record<string, number>): string {
  return Object.entries(t).filter(([, v]) => typeof v === "number" && v > 0).map(([k, v]) => `${k}=${v}`).join(",");
}

export function errorResponse(e: unknown): Response {
  if (e instanceof HttpError) return json({ error: e.message }, e.status);
  console.error(e);
  return json({ error: "internal error" }, 500);
}

/** Read a JSON body, refusing anything over MAX_BODY. */
export async function readJson<T = any>(req: Request): Promise<T> {
  const len = Number(req.headers.get("content-length") || 0);
  if (len > MAX_BODY) throw new HttpError(413, "body too large");
  const text = await req.text();
  if (text.length > MAX_BODY) throw new HttpError(413, "body too large");
  if (!text) return {} as T;
  try { return JSON.parse(text) as T; } catch { throw new HttpError(400, "invalid JSON"); }
}

const B64 = /^[A-Za-z0-9+/]+={0,2}$/;
/** A standard base64 string decoding to exactly `bytes` bytes (32 for a public key). */
export function isB64(s: unknown, bytes?: number): s is string {
  if (typeof s !== "string" || !s || s.length % 4 !== 0 || !B64.test(s)) return false;
  if (bytes === undefined) return true;
  const pad = s.endsWith("==") ? 2 : s.endsWith("=") ? 1 : 0;
  return (s.length / 4) * 3 - pad === bytes;
}

export function token(bytes = 32): string {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  let s = "";
  for (const b of a) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function bearer(req: Request): string {
  const h = req.headers.get("authorization") || "";
  const m = /^Bearer\s+(\S+)$/i.exec(h);
  return m ? m[1] : (new URL(req.url).searchParams.get("token") || "");
}

/** Constant-time-ish string compare (lengths may differ; that leaks only the length). */
export function same(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let r = 0;
  for (let i = 0; i < a.length; i++) r |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return r === 0;
}
