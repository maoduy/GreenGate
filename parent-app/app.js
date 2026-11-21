/* GreenGate parent app. No build step, no framework. State: IndexedDB (keys) + localStorage
   (devices, relay URL, sheet id). Everything the device sends is decrypted here, in the browser. */
"use strict";

const $ = sel => document.querySelector(sel);
const app = $("#app");
const te = new TextEncoder(), td = new TextDecoder();
const b64 = u8 => btoa(String.fromCharCode(...u8));
const unb64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtTime = ms => ms ? new Date(ms).toLocaleString("vi-VN") : "chưa bao giờ";

// ---------------------------------------------------------------- settings in localStorage
const store = {
  get relay() { return localStorage.getItem("gn.relay") || "http://127.0.0.1:8787"; },
  set relay(v) { localStorage.setItem("gn.relay", v.replace(/\/+$/, "")); },
  get sheet() { return localStorage.getItem("gn.sheet") || "1VtlZ1FJlUmRQ3VDx7Gzlve7LZ-oHo79P9iFbNj-9VCs"; },
  set sheet(v) { localStorage.setItem("gn.sheet", v); },
  get devices() { try { return JSON.parse(localStorage.getItem("gn.devices") || "[]"); } catch { return []; } },
  set devices(v) { localStorage.setItem("gn.devices", JSON.stringify(v)); },
};

// ---------------------------------------------------------------- keys in IndexedDB
function idb() {
  return new Promise((res, rej) => {
    const r = indexedDB.open("greengate", 1);
    r.onupgradeneeded = () => r.result.createObjectStore("kv");
    r.onsuccess = () => res(r.result); r.onerror = () => rej(r.error);
  });
}
async function kvGet(k) { const db = await idb(); return new Promise((res, rej) => { const t = db.transaction("kv").objectStore("kv").get(k); t.onsuccess = () => res(t.result); t.onerror = () => rej(t.error); }); }
async function kvSet(k, v) { const db = await idb(); return new Promise((res, rej) => { const t = db.transaction("kv", "readwrite").objectStore("kv").put(v, k); t.onsuccess = () => res(); t.onerror = () => rej(t.error); }); }

let KEYS = null;                 // { publicKey, secretKey } Uint8Arrays
async function loadKeys() {
  let k = await kvGet("keypair");
  if (!k) { const kp = nacl.box.keyPair(); k = { publicKey: kp.publicKey, secretKey: kp.secretKey }; await kvSet("keypair", k); }
  KEYS = { publicKey: new Uint8Array(k.publicKey), secretKey: new Uint8Array(k.secretKey) };
}
function seal(obj, theirPubB64) {
  const nonce = nacl.randomBytes(24);
  const box = nacl.box(te.encode(JSON.stringify(obj)), nonce, unb64(theirPubB64), KEYS.secretKey);
  const out = new Uint8Array(24 + box.length); out.set(nonce); out.set(box, 24);
  return b64(out);
}
function open(blobB64, theirPubB64) {
  const raw = unb64(blobB64);
  const msg = nacl.box.open(raw.slice(24), raw.slice(0, 24), unb64(theirPubB64), KEYS.secretKey);
  if (!msg) throw new Error("Không giải mã được: khoá không khớp.");
  return JSON.parse(td.decode(msg));
}

// ---------------------------------------------------------------- relay calls
async function api(path, { method = "GET", body, token } = {}) {
  const r = await fetch(store.relay + path, {
    method, headers: { "content-type": "application/json", ...(token ? { authorization: "Bearer " + token } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  let data; const text = await r.text();
  try { data = JSON.parse(text); } catch { data = { error: text }; }
  if (!r.ok) throw new Error(data.error || ("HTTP " + r.status));
  return { data, timing: parseTiming(r.headers.get("X-GreenGate-T")) };
}
function parseTiming(h) {
  const t = {};
  for (const kv of (h || "").split(",")) { const [k, v] = kv.split("="); if (k && v) t[k.trim()] = Number(v); }
  return t;
}

/** Send one command and wait for its result. onStatus(text) keeps the user informed. */
async function runCommand(dev, type, params = {}, { onStatus = () => {}, maxWaitMs = 10 * 60 * 1000 } = {}) {
  const t0 = Date.now();
  const env = { v: 1, id: crypto.randomUUID(), type, ts: Date.now(), params };
  const sent = await api(`/v1/device/${dev.deviceId}/cmd`, { method: "POST", token: dev.parentToken,
    body: { parentPub: b64(KEYS.publicKey), blob: seal(env, dev.devicePub), type } });
  const tSent = Date.now();
  onStatus(sent.data.delivered ? "Máy đã nhận lệnh, đang thực hiện..." : (sent.data.online ? "Đã gửi, chờ máy xác nhận..." : "Máy đang offline. Lệnh được giữ lại, sẽ chạy khi máy lên mạng..."));
  let res;
  while (Date.now() - t0 < maxWaitMs) {
    res = await api(`/v1/device/${dev.deviceId}/result/${sent.data.cmdId}?wait=25`, { token: dev.parentToken });
    if (res.data.status === "done") break;
    if (res.data.status === "expired") throw new Error("Lệnh hết hạn trước khi máy trả lời.");
    onStatus(res.data.online ? "Máy đang online, chờ kết quả..." : "Vẫn đang chờ máy lên mạng... (" + Math.round((Date.now() - t0) / 1000) + "s)");
  }
  if (!res || res.data.status !== "done") throw new Error("Quá thời gian chờ.");
  const tDone = Date.now();
  const result = open(res.data.blob, dev.devicePub);
  const T = res.timing, S = sent.timing;
  const timing = {
    "gửi lệnh (trình duyệt → relay)": tSent - t0,
    "relay → máy con (delivered)": T.delivered && T.sent ? T.delivered - T.sent : null,
    "máy con xử lý (agentMs)": result.agentMs ?? null,
    "máy con → relay (stored)": T.stored && T.delivered ? T.stored - T.delivered - (result.agentMs || 0) : null,
    "relay → trình duyệt": tDone - (T.stored || tDone),
    "tổng cộng": tDone - t0,
    "thời gian lệnh nằm chờ máy": T.delivered && T.sent && T.delivered - T.sent > 5000 ? T.delivered - T.sent : null,
  };
  return { result, timing, sentTiming: S, resultTiming: T };
}
function fmtTiming(t) {
  return Object.entries(t).filter(([, v]) => v !== null && v !== undefined && !Number.isNaN(v)).map(([k, v]) => `${k.padEnd(34, " ")} ${v} ms`).join("\n");
}

// ---------------------------------------------------------------- views
const views = {};

views["/"] = async () => {
  const devs = store.devices;
  if (!devs.length) {
    app.innerHTML = `<div class="card"><h1>Chưa có thiết bị</h1><p>Trên máy của con chạy <code>greengate_agent.py pair</code> (hoặc mở ứng dụng GreenGate trên Android) để lấy mã 6 số, rồi <a href="#/pair">thêm máy</a>.</p></div>`;
    return;
  }
  app.innerHTML = `<h1>Thiết bị</h1>` + devs.map((d, i) => `
    <div class="card device" id="dev-${i}">
      <div><span class="dot" id="dot-${i}"></span><b>${esc(d.name)}</b> <span class="muted">${esc(d.platform)}</span><br>
        <span class="muted" id="seen-${i}">đang kiểm tra...</span></div>
      <a class="btn" href="#/device/${i}">Mở</a>
    </div>`).join("") + `<p class="muted">Relay: ${esc(store.relay)}</p>`;
  devs.forEach(async (d, i) => {
    try {
      const { data } = await api(`/v1/device/${d.deviceId}`, { token: d.parentToken });
      $(`#dot-${i}`).classList.toggle("on", data.online);
      $(`#seen-${i}`).textContent = (data.online ? "Đang online" : "Offline") + " · lần cuối: " + fmtTime(data.lastSeen) + (data.pending ? ` · ${data.pending} lệnh đang chờ` : "");
    } catch (e) { $(`#seen-${i}`).innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  });
};

views["/pair"] = async () => {
  app.innerHTML = `<div class="card"><h1>Thêm máy của con</h1>
    <p>Nhập mã 6 số đang hiện trên máy của con, hoặc quét mã QR.</p>
    <div class="row"><input class="code" id="code" inputmode="numeric" maxlength="7" placeholder="000 000" autofocus>
      <button id="claim">Ghép đôi</button> <button class="secondary" id="scan">Quét QR</button></div>
    <div id="cam"></div>
    <p id="msg" class="muted"></p>
    <details><summary class="muted">Relay khác?</summary><div class="row"><input id="relay" value="${esc(store.relay)}"><button class="secondary" id="saveRelay">Lưu</button></div></details>
  </div>`;
  $("#saveRelay").onclick = () => { store.relay = $("#relay").value.trim(); $("#msg").textContent = "Đã lưu relay."; };
  const claim = async code => {
    $("#msg").textContent = "Đang ghép đôi...";
    try {
      const { data } = await api("/v1/pair/claim", { method: "POST", body: { code, parentPub: b64(KEYS.publicKey) } });
      const devs = store.devices.filter(d => d.deviceId !== data.deviceId);
      devs.push({ deviceId: data.deviceId, devicePub: data.devicePub, parentToken: data.parentToken, name: data.name || "Máy mới", platform: data.platform });
      store.devices = devs;
      $("#msg").innerHTML = `<span class="ok">Đã ghép đôi với <b>${esc(data.name)}</b>.</span>`;
      setTimeout(() => location.hash = "#/", 800);
    } catch (e) { $("#msg").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  $("#claim").onclick = () => claim($("#code").value.replace(/\D/g, ""));
  $("#code").onkeydown = e => { if (e.key === "Enter") $("#claim").click(); };
  $("#scan").onclick = async () => {
    if (!("BarcodeDetector" in window)) { $("#msg").textContent = "Trình duyệt này không quét được QR, hãy nhập mã."; return; }
    const video = document.createElement("video"); video.setAttribute("playsinline", ""); $("#cam").replaceChildren(video);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
      video.srcObject = stream; await video.play();
      const det = new BarcodeDetector({ formats: ["qr_code"] });
      const tick = async () => {
        if (!video.srcObject) return;
        try {
          const codes = await det.detect(video);
          for (const c of codes) {
            const m = /code=(\d{6})/.exec(c.rawValue); const rl = /relay=([^&\s]+)/.exec(c.rawValue);
            if (m) { stream.getTracks().forEach(t => t.stop()); video.srcObject = null; if (rl) store.relay = decodeURIComponent(rl[1]); $("#code").value = m[1]; claim(m[1]); return; }
          }
        } catch {}
        requestAnimationFrame(tick);
      };
      tick();
    } catch (e) { $("#msg").textContent = "Không mở được camera: " + e.message; }
  };
};

views["/device/:i"] = async i => {
  const dev = store.devices[Number(i)];
  if (!dev) { location.hash = "#/"; return; }
  app.innerHTML = `<div class="card">
    <h1>${esc(dev.name)} <span class="muted">${esc(dev.platform)}</span></h1>
    <p class="muted" id="state">đang kiểm tra...</p>
    <div class="row">
      <button data-cmd="screenshot">Chụp màn hình</button>
      <button data-cmd="history">Lịch sử tháng này</button>
      <button data-cmd="refresh">Cập nhật danh sách ngay</button>
      <button data-cmd="pause" class="secondary">Tạm dừng 30 phút</button>
      <button data-cmd="resume" class="secondary">Tiếp tục</button>
      <button data-cmd="status" class="secondary">Trạng thái</button>
    </div>
    <p id="msg" class="muted"></p>
    <div id="out"></div>
    <details><summary class="muted">Khác</summary>
      <div class="row"><input id="rename" value="${esc(dev.name)}"><button class="secondary" id="saveName">Đổi tên</button>
      <button class="danger" id="unpair">Gỡ thiết bị</button></div></details>
  </div>`;
  const refreshState = async () => {
    try { const { data } = await api(`/v1/device/${dev.deviceId}`, { token: dev.parentToken });
      $("#state").innerHTML = `<span class="dot ${data.online ? "on" : ""}"></span>${data.online ? "Đang online" : "Offline"} · lần cuối: ${fmtTime(data.lastSeen)}${data.pending ? ` · ${data.pending} lệnh đang chờ` : ""}${data.version ? ` · agent ${esc(data.version)}` : ""}`;
    } catch (e) { $("#state").innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  };
  refreshState();
  $("#saveName").onclick = () => { const devs = store.devices; devs[Number(i)].name = $("#rename").value.trim() || dev.name; store.devices = devs; location.reload(); };
  $("#unpair").onclick = async () => {
    if (!confirm("Gỡ thiết bị này khỏi tài khoản của bạn?")) return;
    try { await api(`/v1/device/${dev.deviceId}`, { method: "DELETE", token: dev.parentToken }); } catch {}
    store.devices = store.devices.filter(d => d.deviceId !== dev.deviceId); location.hash = "#/";
  };
  for (const b of app.querySelectorAll("button[data-cmd]")) b.onclick = () => doCommand(dev, b.dataset.cmd);
};

async function doCommand(dev, type) {
  const btns = app.querySelectorAll("button[data-cmd]"); btns.forEach(b => b.disabled = true);
  const msg = $("#msg"), out = $("#out");
  out.innerHTML = ""; msg.textContent = "Đang gửi...";
  const params = type === "history" ? { month: new Date().toLocaleDateString("en-GB", { month: "2-digit" }) + "-" + new Date().getFullYear() }
               : type === "pause" ? { minutes: 30 } : {};
  try {
    const { result, timing } = await runCommand(dev, type, params, { onStatus: t => msg.textContent = t });
    msg.innerHTML = result.ok ? `<span class="ok">Xong.</span>` : `<span class="err">Máy báo lỗi: ${esc(result.error)}</span>`;
    let html = "";
    if (result.ok && type === "screenshot") {
      html += `<img class="shot" src="data:${esc(result.data.mime)};base64,${result.data.b64}" alt="Ảnh màn hình">
               <p class="muted">${result.data.width}×${result.data.height}, JPEG q${result.data.quality}, tài khoản ${esc(result.data.user)} trên ${esc(result.data.host)}, ${Math.round(result.data.b64.length * 3 / 4 / 1024)} KB.
               <a download="greengate-${Date.now()}.jpg" href="data:image/jpeg;base64,${result.data.b64}">Tải ảnh</a></p>`;
    } else if (result.ok && type === "history") {
      const csv = await gunzip(unb64(result.data.b64));
      html += renderCsv(csv) + `<p><a class="btn" download="greengate-${esc(result.data.month)}.csv" href="data:text/csv;charset=utf-8,${encodeURIComponent(csv)}">Tải CSV</a></p>`;
    } else if (result.ok) {
      html += `<pre class="timing">${esc(JSON.stringify(result.data, null, 2))}</pre>`;
    }
    html += `<h2>Thời gian</h2><pre class="timing">${esc(fmtTiming(timing))}</pre>`;
    out.innerHTML = html;
  } catch (e) { msg.innerHTML = `<span class="err">${esc(e.message)}</span>`; }
  btns.forEach(b => b.disabled = false);
}

async function gunzip(u8) {
  const ds = new DecompressionStream("gzip");
  const stream = new Blob([u8]).stream().pipeThrough(ds);
  return await new Response(stream).text();
}
function parseCsv(text) {
  const rows = []; let row = [], cell = "", q = false;
  text = text.replace(/^﻿/, "");
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"') { if (text[i + 1] === '"') { cell += '"'; i++; } else q = false; } else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n") { row.push(cell); rows.push(row); row = []; cell = ""; }
    else if (c !== "\r") cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter(r => r.some(x => x !== ""));
}
function renderCsv(csv) {
  const rows = parseCsv(csv);
  if (rows.length < 2) return `<p class="muted">Chưa có dữ liệu trong tháng này.</p>`;
  const head = rows[0], body = rows.slice(1);
  // hide day columns that are empty everywhere
  const keep = head.map((_, c) => c < 2 || c === head.length - 1 || body.some(r => r[c]));
  const tr = r => "<tr>" + r.map((v, c) => keep[c] ? `<td>${esc(v)}</td>` : "").join("") + "</tr>";
  return `<div class="wrap"><table><thead>${tr(head).replace(/td/g, "th")}</thead><tbody>${body.map(tr).join("")}</tbody></table></div>`;
}

views["/settings"] = async () => {
  const sid = store.sheet;
  app.innerHTML = `<div class="card"><h1>Cài đặt (từ Google Sheet)</h1>
    <p class="muted">Mọi cài đặt nằm trong Google Sheet của gia đình; máy con tự đọc lại mỗi phút. Trang này chỉ hiển thị.
    <!-- TODO: sửa trực tiếp cần một Google OAuth client (quyền spreadsheets) do chủ dự án tạo trong Google Cloud Console; xem parent-app/README.md -->
    </p>
    <div class="row"><input id="sheet" value="${esc(sid)}" placeholder="ID hoặc link Google Sheet"><button class="secondary" id="saveSheet">Dùng sheet này</button>
      <a class="btn" target="_blank" rel="noopener" href="https://docs.google.com/spreadsheets/d/${esc(sid)}/edit">Mở Google Sheet để sửa</a></div>
    <div class="row"><button class="secondary" id="applyAll">Cập nhật danh sách ngay trên mọi máy</button><span id="applyMsg" class="muted"></span></div>
  </div><div id="tabs"></div>`;
  $("#saveSheet").onclick = () => { const v = $("#sheet").value.trim(); const m = /\/d\/([A-Za-z0-9_-]{20,})/.exec(v); store.sheet = m ? m[1] : v; location.reload(); };
  $("#applyAll").onclick = async () => {
    const devs = store.devices; if (!devs.length) { $("#applyMsg").textContent = "Chưa có thiết bị."; return; }
    $("#applyMsg").textContent = "Đang gửi...";
    const outs = await Promise.all(devs.map(d => runCommand(d, "refresh", {}, { maxWaitMs: 60000 }).then(r => `${d.name}: ${r.timing["tổng cộng"]} ms`).catch(e => `${d.name}: ${e.message}`)));
    $("#applyMsg").textContent = outs.join(" · ");
  };
  const tabs = ["websites", "youtube", "settings", "blocked", "apps"];
  // {tab name: gid} from the public /htmlview page, so each tab can be read with
  // export?format=csv&gid= (cells as typed). gviz by name is the fallback: it re-types columns
  // and shows text in a numeric column as EMPTY, and answers a missing tab with the first tab.
  let gids = null;
  try {
    const h = await fetch(`https://docs.google.com/spreadsheets/d/${sid}/htmlview`);
    if (h.ok) {
      const m = {}; const re = /items\.push\(\{name: "((?:[^"\\]|\\.)*)",[^}]*?gid: "(\d+)"/g; let hit;
      const html = await h.text();
      while ((hit = re.exec(html))) m[hit[1].replace(/\\(x[0-9A-Fa-f]{2}|u[0-9A-Fa-f]{4}|.)/g, (_, e) => e.length === 3 && e[0] === "x" ? String.fromCharCode(parseInt(e.slice(1), 16)) : e.length === 5 && e[0] === "u" ? String.fromCharCode(parseInt(e.slice(1), 16)) : e)] = hit[2];
      if (Object.keys(m).length) gids = m;
    }
  } catch (e) { /* fall back to gviz */ }
  let websitesHead = "";
  for (const tab of tabs) {
    const box = document.createElement("div"); box.className = "card"; box.innerHTML = `<h2>${tab}</h2><p class="muted">đang tải...</p>`; $("#tabs").appendChild(box);
    try {
      if (gids && !gids[tab]) { box.innerHTML = `<h2>${tab}</h2><p class="muted">Sheet chưa có tab này (máy con dùng mặc định).</p>`; continue; }
      const url = gids ? `https://docs.google.com/spreadsheets/d/${sid}/export?format=csv&gid=${gids[tab]}`
                       : `https://docs.google.com/spreadsheets/d/${sid}/gviz/tq?tqx=out:csv&headers=1&sheet=${encodeURIComponent(tab)}`;
      const r = await fetch(url);
      if (!r.ok) throw new Error("HTTP " + r.status);
      const rows = parseCsv(await r.text()).map(row => row.slice(0, 5));
      // gviz answers with the FIRST tab when the named one does not exist; flag that so the
      // parent does not mistake the website list for the settings tab.
      const missing = !gids && tab !== "websites" && rows.length && websitesHead && rows[0].join("|") === websitesHead;
      if (tab === "websites" && rows.length) websitesHead = rows[0].join("|");
      if (missing) { box.innerHTML = `<h2>${tab}</h2><p class="muted">Sheet chưa có tab này (máy con dùng mặc định).</p>`; continue; }
      if (!rows.length) { box.innerHTML = `<h2>${tab}</h2><p class="muted">Tab trống hoặc chưa có (máy con dùng mặc định).</p>`; continue; }
      if (tab === "settings") {
        // the Drive folder with the scheduled screenshots (SPEC §8): one button, no API needed
        const kv = Object.fromEntries(rows.slice(1).map(r => [String(r[0] || "").trim().toLowerCase(), String(r[1] || "").trim()]));
        const folder = kv["drivefolder"] || kv["thư mục drive"] || kv["thu muc drive"] || kv["folder"];
        const every = kv["screenshotevery"] || kv["chụp mỗi"] || kv["chụp màn hình"] || "15";
        if (folder && /^https:\/\/drive\.google\.com\//.test(folder)) {
          const d = document.createElement("div"); d.className = "card";
          d.innerHTML = `<h2>Ảnh màn hình định kỳ</h2><p class="muted">Máy con tự chụp mỗi ${esc(every)} phút và gửi vào Drive của bạn (có báo cho con). Để chụp ngay lúc này, mở thiết bị đang online và bấm "Chụp màn hình".</p>
            <a class="btn" target="_blank" rel="noopener" href="${esc(folder)}">Mở thư mục Drive</a>`;
          box.before(d);
        }
      }
      box.innerHTML = `<h2>${tab} <span class="muted">${rows.length - 1} dòng</span></h2><div class="wrap"><table><thead><tr>${rows[0].map(h => `<th>${esc(h)}</th>`).join("")}</tr></thead><tbody>${rows.slice(1, 200).map(r => `<tr>${r.map(v => `<td>${esc(v)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    } catch (e) { box.innerHTML = `<h2>${tab}</h2><p class="err">${esc(e.message)}</p>`; }
  }
};

views["/keys"] = async () => {
  app.innerHTML = `<div class="card"><h1>Khoá của bố mẹ</h1>
    <p class="muted">Khoá công khai (máy con dùng để khoá dữ liệu gửi cho bạn):</p><pre class="timing">${b64(KEYS.publicKey)}</pre>
    <p>Mã khôi phục chứa khoá bí mật. Lưu nó ở nơi an toàn: ai có mã này đọc được ảnh và lịch sử của con.</p>
    <div class="row"><button id="export">Xuất mã khôi phục</button><button class="secondary" id="import">Nhập mã khôi phục</button></div>
    <textarea id="recovery" placeholder="Dán mã khôi phục vào đây để nhập"></textarea>
    <p id="msg" class="muted"></p>
    <h2>Dữ liệu trên máy này</h2><p class="muted">${store.devices.length} thiết bị, relay ${esc(store.relay)}.</p>
    <button class="danger" id="wipe">Xoá hết trên máy này</button>
  </div>`;
  $("#export").onclick = () => { $("#recovery").value = "GN1." + b64(KEYS.secretKey); $("#msg").textContent = "Đã xuất. Sao chép và cất kỹ."; };
  $("#import").onclick = async () => {
    const v = $("#recovery").value.trim().replace(/^GN1\./, "");
    try { const sk = unb64(v); if (sk.length !== 32) throw new Error("độ dài sai"); const kp = nacl.box.keyPair.fromSecretKey(sk);
      await kvSet("keypair", { publicKey: kp.publicKey, secretKey: kp.secretKey }); await loadKeys(); $("#msg").innerHTML = `<span class="ok">Đã nhập khoá. Khoá công khai mới: ${b64(KEYS.publicKey)}</span>`;
    } catch (e) { $("#msg").innerHTML = `<span class="err">Mã không hợp lệ (${esc(e.message)}).</span>`; }
  };
  $("#wipe").onclick = async () => { if (confirm("Xoá khoá và danh sách thiết bị trên máy này? Không khôi phục được nếu chưa xuất mã.")) { localStorage.clear(); indexedDB.deleteDatabase("greengate"); location.reload(); } };
};

// ---------------------------------------------------------------- router
async function route() {
  const h = location.hash.replace(/^#/, "") || "/";
  const m = /^\/device\/(\d+)$/.exec(h);
  try {
    if (m) await views["/device/:i"](m[1]);
    else if (views[h]) await views[h]();
    else location.hash = "#/";
  } catch (e) { app.innerHTML = `<div class="card err">${esc(e.message)}</div>`; }
}
window.addEventListener("hashchange", route);
(async () => {
  if (typeof nacl === "undefined") { app.innerHTML = `<div class="card err">Không tải được thư viện mã hoá (tweetnacl). Kiểm tra mạng.</div>`; return; }
  await loadKeys();
  if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js").catch(() => {});
  route();
})();
// Exposed for the automated end-to-end test (test/e2e-parent.mjs).
window.GreenGate = { api, runCommand, seal, open, store, get keys() { return KEYS; } };
