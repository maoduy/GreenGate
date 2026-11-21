// Page-load latency: the same pages directly and through one or more GreenGate instances,
// interleaved run by run so network drift hits every configuration alike. Medians and p90.
//   node test/latency.js --configs "direct=,GreenGate=127.0.0.1:18081" --runs 10 --out /tmp/latency.json
//   node test/latency.js --proxy 127.0.0.1:18081            (same as direct + that one proxy)
//   a configuration "name=@--disable-quic" is direct Chrome with extra flags (what does HTTP/3 cost?)
// "load" = navigation start -> load event (Navigation Timing). YouTube watch: time until the
// <video> element is playing. Prints a markdown table, one column per configuration, with the
// difference against the first configuration (normally "direct").
const { chromium } = require("playwright-core");
const fs = require("fs");
const argv = process.argv.slice(2);
const opt = (n, d) => { const i = argv.indexOf(n); return i >= 0 ? argv[i + 1] : d; };
const RUNS = parseInt(opt("--runs", "5"), 10);
const OUT = opt("--out", "");
const BROWSER = opt("--browser", "/usr/bin/google-chrome");
const CONFIGS = (opt("--configs", "") || ("direct=,GreenGate=" + opt("--proxy", "127.0.0.1:18081")))
  .split(",").map(s => { const [name, proxy] = s.split("="); return { name: name.trim(), proxy: (proxy || "").trim() }; });
const PAGES = [
  ["google.com", "https://www.google.com/"],
  ["ted.com", "https://www.ted.com/"],
  ["nasa.gov", "https://www.nasa.gov/"],
  ["w3schools.com", "https://www.w3schools.com/"],
  ["codeforces.com", "https://codeforces.com/"],
  ["youtube.com (trang chủ)", "https://www.youtube.com/"],
  ["youtube.com (xem video @TED)", "https://www.youtube.com/watch?v=LmszJQzuAcc"],
];
const median = a => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.floor(s.length / 2)] : NaN; };
const p = (a, q) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(q * s.length))] : NaN; };
const r0 = x => isNaN(x) ? "-" : String(Math.round(x));

async function launch(cfg) {
  const args = ["--headless=new", "--no-first-run", "--lang=vi", "--disable-gpu", "--autoplay-policy=no-user-gesture-required"];
  // "name=host:port" = via that proxy; "name=@--flag --flag2" = direct with extra Chrome flags (e.g. @--disable-quic)
  if (cfg.proxy.startsWith("@")) args.push(...cfg.proxy.slice(1).split(/\s+/).filter(Boolean));
  else if (cfg.proxy) args.push("--proxy-server=" + cfg.proxy);
  return chromium.launch({ executablePath: BROWSER, headless: false, args });
}

async function visit(browser, url) {
  const ctx = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  const t0 = Date.now();
  const out = { load: NaN, video: NaN, status: 0, err: "" };
  try {
    const resp = await page.goto(url, { waitUntil: "load", timeout: 60000 });
    out.status = resp ? resp.status() : 0;
    const nav = await page.evaluate(() => {
      const e = performance.getEntriesByType("navigation")[0];
      return e ? { load: e.loadEventEnd } : null;
    });
    if (nav && out.status < 400) out.load = nav.load;
    if (url.includes("/watch")) {
      try {
        await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.currentTime > 0.5; }, null, { timeout: 30000 });
        out.video = Date.now() - t0;
      } catch (e) { /* no playback */ }
    }
  } catch (e) { out.status = -1; out.err = String(e.message || e).split("\n")[0].slice(0, 120); }
  await ctx.close();
  return out;
}

(async () => {
  const browsers = [];
  for (const cfg of CONFIGS) browsers.push(await launch(cfg));
  const res = {};   // res[page][config] = {load: [], video: [], status: []}
  for (const [name] of PAGES) { res[name] = {}; for (const c of CONFIGS) res[name][c.name] = { load: [], video: [], status: [] }; }
  for (let r = 0; r < RUNS; r++) {
    for (const [name, url] of PAGES) {
      for (let i = 0; i < CONFIGS.length; i++) {
        const v = await visit(browsers[i], url);
        const slot = res[name][CONFIGS[i].name];
        slot.load.push(v.load); slot.video.push(v.video); slot.status.push(v.status);
        if (v.err) (slot.errors = slot.errors || []).push(v.err);
      }
    }
    process.stderr.write(`run ${r + 1}/${RUNS} done\n`);
  }
  for (const b of browsers) await b.close();

  const base = CONFIGS[0].name;
  const head = ["Trang", ...CONFIGS.map(c => c.name + " (median)"), ...CONFIGS.slice(1).map(c => "Chênh " + c.name), ...CONFIGS.map(c => "p90 " + c.name), "Mã (" + CONFIGS.slice(1).map(c => c.name).join("/") + ")"];
  console.log("| " + head.join(" | ") + " |");
  console.log("|" + head.map(() => "---").join("|") + "|");
  const rows = [];
  for (const [name, url] of PAGES) {
    const key = url.includes("/watch") ? "video" : "load";
    const vals = {}; for (const c of CONFIGS) vals[c.name] = res[name][c.name][key].filter(x => !isNaN(x));
    const mb = median(vals[base]);
    const diff = CONFIGS.slice(1).map(c => { const m = median(vals[c.name]); return isNaN(m) || isNaN(mb) ? "-" : (m - mb >= 0 ? "+" : "") + Math.round(m - mb) + " ms"; });
    const codes = CONFIGS.slice(1).map(c => [...new Set(res[name][c.name].status)].join(",")).join(" / ");
    rows.push({ page: name, url, metric: key, values: vals, status: Object.fromEntries(CONFIGS.map(c => [c.name, res[name][c.name].status])),
      errors: Object.fromEntries(CONFIGS.map(c => [c.name, res[name][c.name].errors || []])) });
    console.log(`| ${name}${key === "video" ? " (tới khi video chạy)" : ""} | ${CONFIGS.map(c => r0(median(vals[c.name]))).join(" | ")} | ${diff.join(" | ")} | ${CONFIGS.map(c => r0(p(vals[c.name], 0.9))).join(" | ")} | ${codes} |`);
  }
  if (OUT) fs.writeFileSync(OUT, JSON.stringify({ when: new Date().toISOString(), configs: CONFIGS, runs: RUNS, rows }, null, 1));
})().catch(e => { console.error(e); process.exit(2); });
