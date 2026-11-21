// Drives the real parent app in Chrome against wrangler dev + a real Linux agent, and measures.
// Usage: node parent-app/test/e2e-parent.mjs   (env: RELAY, APP, AGENT_PY, AGENT_CFG, PROXY_PORT)
import { chromium } from "playwright-core";
import { spawn, execFileSync } from "node:child_process";
import fs from "node:fs";

const RELAY = process.env.RELAY || "http://127.0.0.1:8787";
const APP = process.env.APP || "http://127.0.0.1:8790/index.html";
const PY = process.env.AGENT_PY || "python3";
const CFG = process.env.AGENT_CFG || "/tmp/greengate-agent-test.json";
const PROXY_PORT = process.env.PROXY_PORT || "8080";
const OUT = process.env.OUT || "/tmp/greengate-e2e.json";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const report = { steps: [], screenshot: [], history: [], offline: [], refresh: {}, firstRequestMs: null };
const step = (n, v) => { console.log(n, v ?? ""); report.steps.push({ n, v }); };
const med = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };
const p95 = a => { const s = [...a].sort((x, y) => x - y); return s[Math.min(s.length - 1, Math.floor(s.length * 0.95))]; };

let agent = null;
const agentLog = [];
function startAgent() {
  agent = spawn(PY, ["agent/greengate_agent.py", "--config", CFG, "run"], { env: { ...process.env, DISPLAY: process.env.DISPLAY || ":0" } });
  agent.stdout.on("data", d => agentLog.push(d.toString()));
  agent.stderr.on("data", d => agentLog.push(d.toString()));
  return Date.now();
}
function stopAgent() { if (agent) { agent.kill("SIGTERM"); agent = null; } }

// 1. pair: the agent prints a code
fs.rmSync(CFG, { force: true });
const pairOut = execFileSync(PY, ["agent/greengate_agent.py", "--config", CFG, "pair", "--relay", RELAY, "--name", "Máy Linux test", "--proxy-port", PROXY_PORT, "--no-wait"]).toString();
const code = /(\d{3}) (\d{3})/.exec(pairOut).slice(1).join("");
step("pairing code from agent", code);
const tAgent0 = startAgent();
await sleep(1500);

const browser = await chromium.launch({ executablePath: "/usr/bin/google-chrome", headless: true, args: ["--no-first-run", "--lang=vi"] });
const ctx = await browser.newContext({ viewport: { width: 420, height: 860 }, locale: "vi-VN" });
const page = await ctx.newPage();
page.on("pageerror", e => console.log("PAGE ERROR", e.message));
const t0 = Date.now();
await page.goto(APP, { waitUntil: "load" });
await page.evaluate(r => localStorage.setItem("gn.relay", r), RELAY);
await page.goto(APP + "#/pair", { waitUntil: "load" });
await page.waitForSelector("#code");
await page.fill("#code", code);
await page.click("#claim");
await page.waitForFunction(() => /Đã ghép đôi/.test(document.querySelector("#msg").textContent), null, { timeout: 15000 });
step("paired via UI", await page.textContent("#msg"));
await sleep(1200);
await page.goto(APP + "#/", { waitUntil: "load" });
await page.waitForFunction(() => /online|Offline/i.test(document.querySelector("#seen-0")?.textContent || ""), null, { timeout: 15000 });
step("device list", await page.textContent("#seen-0"));

// helper: run a command through the app's own code
const run = (type, params = {}, maxWaitMs = 120000) => page.evaluate(async ({ type, params, maxWaitMs }) => {
  const dev = GreenGate.store.devices[0];
  const t0 = performance.now();
  const r = await GreenGate.runCommand(dev, type, params, { maxWaitMs });
  return { timing: r.timing, ok: r.result.ok, error: r.result.error, agentMs: r.result.agentMs,
           bytes: r.result.data?.b64 ? Math.round(r.result.data.b64.length * 3 / 4) : 0, extra: { w: r.result.data?.width, h: r.result.data?.height, q: r.result.data?.quality, rows: r.result.data?.rows, text: (r.result.data?.text || "").slice(0, 80) },
           total: Math.round(performance.now() - t0) };
}, { type, params, maxWaitMs });

// 2. screenshot x10 (online)
for (let i = 0; i < 10; i++) {
  const r = await run("screenshot");
  if (!r.ok) { step("screenshot FAILED", r.error); break; }
  report.screenshot.push({ total: r.total, agentMs: r.agentMs, bytes: r.bytes, timing: r.timing, ...r.extra });
  if (i === 0) step("screenshot #1", JSON.stringify(r));
}
if (report.screenshot.length) {
  const tot = report.screenshot.map(x => x.total), ag = report.screenshot.map(x => x.agentMs);
  step(`screenshot x${tot.length}: total median=${med(tot)}ms p95=${p95(tot)}ms | agent(capture+encode) median=${med(ag)}ms | size median=${Math.round(med(report.screenshot.map(x => x.bytes)) / 1024)}KB`);
}
// 3. history x5
const month = new Date().toLocaleDateString("en-GB", { month: "2-digit" }) + "-" + new Date().getFullYear();
for (let i = 0; i < 5; i++) {
  const r = await run("history", { month });
  if (!r.ok) { step("history FAILED", r.error); break; }
  report.history.push({ total: r.total, agentMs: r.agentMs, bytes: r.bytes, rows: r.extra.rows });
}
if (report.history.length) step(`history x${report.history.length}: total median=${med(report.history.map(x => x.total))}ms, ${report.history[0].rows} rows, ${report.history[0].bytes} bytes gz`);
// 4. refresh -> proxy must log an update
const r4 = await run("refresh");
report.refresh = r4; step("refresh", JSON.stringify({ ok: r4.ok, total: r4.total, text: r4.extra.text }));
const r5 = await run("status"); step("status", JSON.stringify({ ok: r5.ok, total: r5.total }));

// 5. device OFF: command issued while the agent is down, agent starts 20 s later
for (const gap of [20, 5]) {
  stopAgent(); await sleep(1500);
  const info = await page.evaluate(async () => (await GreenGate.api(`/v1/device/${GreenGate.store.devices[0].deviceId}`, { token: GreenGate.store.devices[0].parentToken })).data);
  step(`agent stopped, relay says online=${info.online}`);
  const pending = run("screenshot", {}, 180000);                 // long-polls until the agent is back
  await sleep(gap * 1000);
  const tStart = Date.now();
  startAgent();
  const r = await pending;
  const sinceStart = Date.now() - tStart;
  report.offline.push({ gapSeconds: gap, ok: r.ok, totalMs: r.total, fromAgentStartMs: sinceStart, agentMs: r.agentMs, timing: r.timing });
  step(`offline ${gap}s: result ${r.ok ? "OK" : "FAIL " + r.error} total=${r.total}ms, from agent start=${sinceStart}ms`);
}

await browser.close();
stopAgent();
fs.writeFileSync(OUT, JSON.stringify(report, null, 2));
console.log("--- agent log (tail) ---"); console.log(agentLog.join("").split("\n").slice(-12).join("\n"));
console.log("report:", OUT);
