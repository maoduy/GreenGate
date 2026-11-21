# GreenGate technical spec (v1, 2026-11-01)

Shared contract between the proxy (`proxy/greengate.py`), the Linux and Windows agents (`agent/`),
the Android app (`android/`), the relay (`server/`) and the parent web app (`parent-app/`).
Anything that two components must agree on lives here. English, because the code is.

## 1. The Google Sheet is the only source of settings

One spreadsheet per family, shared as "anyone with the link can view". Devices read tabs by
NAME, never by a configured gid (a copied sheet keeps the names, not the gids). Two public
endpoints exist and the difference matters:

- `/htmlview` lists every tab with its gid; devices parse it on each refresh, then read each tab
  with `/export?format=csv&gid=<gid>`, which returns the cells exactly as typed. A tab missing
  from the list does not exist (defaults apply). This is the normal path.
- `/gviz/tq?tqx=out:csv&headers=1&sheet=<tab>` is the fallback when `/htmlview` cannot be read.
  gviz re-types every column: text in a column that is mostly numbers comes back EMPTY (`chặn`
  next to `60` in `apps`, `blacklist` next to `30` in `settings`), it answers a missing tab with
  the FIRST tab (devices probe for an impossible name and compare), and without `headers=1` it
  merges every row above the first number into the header.
First row of every tab is a header and is ignored. `#` starts a comment. Blank rows ignored.

| Tab | Columns | Meaning |
|---|---|---|
| `websites` | A site, B note, C minutes/day, D hours | Allowed sites (whitelist mode) or sites with a time budget (both modes). `*` row = whole-internet budget. Site = `domain` (covers subdomains) or `domain/path`. D = time window, see §3. |
| `youtube` | A channel (`@handle`, `UC...` id or URL), B.. free | Allowed YouTube channels. |
| `blocked` | A site, B note | Always blocked, in both modes. Overrides `websites` (a path inside an allowed domain can be blocked). |
| `apps` | A package or exe name, B `chặn`/`block` or minutes, C hours | Blocked / limited apps. Android package names (`com.google.android.youtube`) or Windows exe names (`roblox.exe`). |
| `settings` | A key, B value | Key/value, see §2. Missing tab or key = default. |

Legacy sheets (only `websites` + `youtube`) keep working: defaults reproduce today's behaviour.

## 2. `settings` keys

Keys are case-insensitive; Vietnamese aliases in brackets are accepted too.

| Key | Values | Default | Meaning |
|---|---|---|---|
| `mode` (`chế độ`) | `whitelist` (`chỉ cho phép`), `blacklist` (`chặn danh sách`) | `whitelist` | whitelist: only `websites` (+ YouTube when channels are listed). blacklist: everything except `blocked`, the chosen `categories`, `keywords`. |
| `categories` (`danh mục`) | comma list of §4 names | `adult,gambling,drugs,weapons,violence,malware,bypass` | Category lists enforced in blacklist mode. Also enforced in whitelist mode (harmless, a listed site can still be blocked by `blocked`). |
| `keywords` (`từ khoá`) | comma list; `+default` keeps the built-in list | `+default` | Blocked when found as a token in host, path, query or a search query. |
| `safesearch` | `on`/`off` | `on` | Force SafeSearch on Google, Bing, DuckDuckGo, YouTube Restricted Mode (when `youtube` is not `channels`). |
| `youtube` | `channels`, `restricted`, `block`, `any` | `channels` if the `youtube` tab is non-empty else `restricted` | `channels`: only listed channels play (proxy platforms). Android cannot inspect YouTube traffic: `channels` there means the YouTube apps are blocked and youtube.com in the browser is blocked unless `youtube.com` is in `websites`. |
| `shorts` | `block`/`allow` | `block` | YouTube Shorts. |
| `schedule` (`giờ`) | §3 | empty = always | Hours when the internet is allowed at all. |
| `refreshSeconds` | 30..3600 | `60` | How often devices re-read the sheet. |
| `screenshotEvery` | minutes, 0 = off | `15` | Automatic screenshots, uploaded to the parents' Google Drive folder through `uploadUrl` (§8). Aliases `chụp mỗi`, `chụp màn hình`. |
| `screenshotHours` | time windows (§3) | always | Only capture inside these windows (e.g. `07:00-21:00`). Alias `giờ chụp`. |
| `uploadUrl` | URL | empty | Apps Script web-app URL that stores screenshots in the parents' Drive (§8). Aliases `drive`, `upload`, `tải lên`. Empty = keep encrypted copies on the device only. |
| `driveFolder` | URL | empty | The Drive folder link, shown as a button in the parent app. Alias `thư mục drive`. |
| `retentionDays` | days | `30` | How long devices keep history and screenshots. |
| `blockPage` | text | built-in | Message shown on the block page. |
| `deepInspect` (`kiểm tra sâu`) | `on`/`off` | `on` | `on`: every allowed site is decrypted and checked per URL (keywords in paths, SafeSearch, full history). `off`: a site listed in `websites` as a whole domain (blacklist mode: any host no host-level rule refuses) is relayed without decryption, like the media CDNs - faster, but only host-level rules apply to it and history records `host/` once a minute. Always decrypted regardless: YouTube, search engines, ad hosts, hosts with a `blocked` path rule or listed only by path, and a host whose daily budget is spent (so the block page can be shown). Daily budgets then count one new connection as one browser request. Proxy platforms only. |

## 3. Time windows

`HH:MM-HH:MM` optionally followed by days. Days: `T2`..`T7`, `CN` (Vietnamese) or `Mon`..`Sun`.
Ranges `T2-T6`, lists `T7,CN`. Several windows separated by `;`. A window crossing midnight
(`21:00-06:00`) is allowed. Empty = always allowed. Examples:

```
07:00-21:00
17:00-20:00 T2-T6; 08:00-22:00 T7,CN
```

Reference implementation: `proxy/timewindow.py` with tests in `test/timewindow_test.py`. Kotlin
port in `android/.../TimeWindow.kt` with the same test vectors (`docs/timewindow-vectors.json`).

## 4. Category lists

Compiled daily by `.github/workflows/build-lists.yml` from public sources into one gzip text file
per category (one domain per line, lower-case, no wildcards, deduplicated, subdomain-reduced) and
published as assets of the GitHub release tagged `lists`:

```
https://github.com/maoduy/GreenGate/releases/download/lists/<category>.txt.gz
https://github.com/maoduy/GreenGate/releases/download/lists/index.json   # {category: {count, sha256, built}}
```

| Category | Sources |
|---|---|
| `adult` | Blocklist Project `porn`, HaGeZi `nsfw` |
| `adult-extended` | UT1 `adult` (~4M, opt-in) |
| `gambling` | Blocklist Project `gambling`, HaGeZi `gambling`, UT1 `gambling`, `arjel` |
| `drugs` | Blocklist Project `drugs`, `vaping`, UT1 `drogue` |
| `weapons` | UT1 `dangerous_material` |
| `violence` | UT1 `agressif` |
| `dating` | UT1 `dating` |
| `social` | Blocklist Project `facebook`, `twitter`, `tiktok`, UT1 `social_networks` |
| `games` | UT1 `games` |
| `piracy` | Blocklist Project `piracy`, `torrent`, UT1 `warez` |
| `malware` | Blocklist Project `malware`, `phishing`, `scam`, `ransomware` |
| `bypass` | HaGeZi `doh-vpn-proxy-bypass`, UT1 `vpn`, `doh`, `redirector`, `strong_redirector`, `residential-proxies` |
| `ads` | HaGeZi `pro` |

Lookup: a host matches if it or any parent domain is in the set. Devices keep a compact
representation (sorted 64-bit truncated SHA-1 of each domain; 8 bytes per entry; binary search),
refresh daily, keep the last good copy. Source config: `blocklists/sources.json`.

## 5. Relay protocol

The relay (Cloudflare Worker + one Durable Object per device) forwards opaque encrypted blobs.
It stores: device id, device public key, parent public keys, device/parent bearer tokens,
last-seen time, queued commands and their results until delivered (TTL). Never a screenshot,
history or setting in clear.

### Keys

`nacl.box` (X25519 + XSalsa20-Poly1305). Each party has one keypair. Keys base64 (standard).
Libraries: tweetnacl-js (browser), PyNaCl (agents), lazysodium or tweetnacl-java (Android).

### Messages

```
Command (parent -> device):  envelope = { v:1, id, type, ts, params }  (JSON, UTF-8)
Result  (device -> parent):  envelope = { v:1, id, ok, ts, type, data|error }
```
Both are encrypted as `nonce(24) || box(envelope, nonce, receiverPub, senderPriv)` and base64'd.
The receiver rejects `|ts - now| > 300s` and a repeated `id`. Binary payloads (screenshot JPEG,
gzipped CSV) are base64 inside `data` with a `mime`. One result at most 950 KB after encryption;
the device scales a screenshot down (JPEG, longest side 1280, quality 60..40) to fit.

Command types: `screenshot {}`, `history {month:"MM-yyyy"}`, `refresh {}`, `status {}`,
`pause {minutes}`, `resume {}`, `settings {screenshotEvery, retentionDays}`.

### HTTP API (JSON)

| Method, path | Who | Body -> Response |
|---|---|---|
| `POST /v1/pair/start` | device | `{devicePub, name, platform}` -> `{deviceId, deviceToken, code}` (6 digits, valid 10 min) |
| `POST /v1/pair/claim` | parent | `{code, parentPub}` -> `{deviceId, devicePub, parentToken, name, platform}` |
| `GET  /v1/device/:id` | parent (`Authorization: Bearer parentToken`) | -> `{deviceId, name, platform, online, lastSeen, pending}` |
| `POST /v1/device/:id/cmd` | parent | `{parentPub, blob, type, ttl}` -> `{cmdId, delivered}` (`delivered`: device was online and acked) |
| `GET  /v1/device/:id/result/:cmdId?wait=25` | parent | long-poll -> `{status:"pending"|"done"|"expired", blob?}`; a fetched result is deleted |
| `GET  /v1/device/:id/ws` | device (`?token=deviceToken`) | WebSocket, see below |
| `GET  /v1/device/:id/pending` | device (bearer deviceToken) | polling fallback -> `[{cmdId, parentPub, blob}]` |
| `POST /v1/device/:id/result` | device | `{cmdId, blob}` -> `{}` |
| `DELETE /v1/device/:id` | parent | unpair |

### Device WebSocket

Server -> device: `{t:"cmd", cmdId, parentPub, blob}`, `{t:"parents", keys:[...]}`, `{t:"ping"}`.
Device -> server: `{t:"result", cmdId, blob}`, `{t:"ack", cmdId}`, `{t:"pong"}`,
`{t:"hello", platform, version}`.
Queued commands are flushed on connect. TTL defaults: screenshot 600 s, history 86400 s,
refresh 86400 s, others 3600 s. Results expire 600 s after they are stored.

### Measurements the relay must make possible

Every response carries `X-GreenGate-T` with server timestamps so the parent app can print:
command sent -> delivered to device -> result stored -> result fetched.

### Implementation notes (relay v1, see server/README.md)

`POST .../cmd` also returns `online` and `expiresAt`; `delivered` = acked within 3 s. A fetched
result is deleted with its command (second fetch -> `expired`). Blob limit = 950 000 base64
characters. Extra server -> device messages: `{t:"stored", cmdId}`, `{t:"error", cmdId, error}`;
device -> server `{t:"ping"}` is answered `{t:"pong"}` without waking the object. On reconnect a
command delivered less than 10 s earlier is not re-sent. One parent token per parent key, up to 5
parents. Rate limit 60 commands/hour/device. `X-GreenGate-T` keys: `edge, recv, delivered, acked,
stored, done` (epoch ms).

### 5.x Sheet-changed hint (push instead of polling)

Two plain-JSON frames, never encrypted, carrying no sheet content:

- device → relay, right after the socket opens and whenever the sheet id changes:
  `{"t":"hello", ..., "sheet":"<sheetId>"}` or `{"t":"register","sheet":"<sheetId>"}`. The relay keeps,
  per sheet id, the set of device ids following it (`SheetDO`, pruned after 30 days without a register).
- `POST /v1/sheet/<sheetId>/changed` (no auth; called by the sheet's Apps Script `onChange`/`onEdit`
  trigger, see `drive/GreenGateUploader.gs` `setupTrigger`) → relay → every online follower gets
  `{"t":"hint","kind":"refresh","ts":<ms>}` → device calls its proxy `/update` (Android: SheetSync now).
  Throttled to one hint per sheet per 10 s; the device ignores hints closer than 10 s; the proxy keeps
  its own 10 s guard. Knowing the sheet id (already link-shared) lets anyone trigger at most one public
  CSV re-read per device per 10 s - the same thing the 60 s poll does anyway.

Measured locally (wrangler dev): webhook → hint frame on the device socket 14 ms; polling stays as the
fallback (default 60 s, `refreshSeconds`).

## 6. Local control endpoint (proxy platforms)

`http://greengate.local/` through the proxy on 127.0.0.1:8080 (Windows) or the regular-mode control listener on 127.0.0.1:8081 (Linux, next to the transparent one on 8080). `/update` reloads the sheet,
`/log`, `/log.csv?m=MM-yyyy`, `/status.json` (new: mode, counts, last refresh, budgets, schedule
state). The agent uses `/log.csv` and `/status.json`; nothing reads the proxy's files directly.

## 7. Platform matrix (what v1 enforces where)

| Capability | Windows | Linux | Android |
|---|---|---|---|
| Whitelist / blacklist sites | proxy (TLS intercept) | proxy, transparent via nftables per uid | DNS filter VPN (domain level) |
| Category lists, keywords in host | yes | yes | yes |
| Keywords in URL path / search query | yes | yes | search-domain level only |
| YouTube channel filter | yes | yes | no (apps blocked, youtube.com blocked unless listed) |
| SafeSearch / Restricted Mode | yes | yes | DNS CNAME to forcesafesearch / restrict.youtube.com |
| Time budgets, schedule | yes | yes | schedule yes, budgets per app via usage stats |
| App blocking | agent closes listed exe | - | AccessibilityService |
| Screenshot on request | agent (mss) | agent (mss, X11) | AccessibilityService.takeScreenshot (Android 11+) |
| History on request | proxy log via agent | same | DNS query log |
| Anti-removal | HKLM policy, admin-only folder | no sudo, root service | Device Admin + settings guard; Device Owner optional |

## 8. Scheduled screenshots to the parents' Google Drive

No Google Cloud project, no OAuth client, no Google credential on the child's device. The parent
deploys the bound Apps Script in `drive/GreenGateUploader.gs` once (Extensions → Apps Script → Deploy
→ Web app, *Execute as: me*, *Who has access: Anyone*) and pastes the resulting URL into the sheet as
`uploadUrl`, and their folder id into the script. The script runs as the parent and writes into the
parent's folder; the device can only add files (write-only), never list, read or delete them.

Request from the device, every `screenshotEvery` minutes, inside `screenshotHours`, only while a
filtered account is logged in with the screen unlocked:

```
POST <uploadUrl>            Content-Type: application/json   (follow the 302 Google answers with)
{"v": 1, "device": "<name>", "platform": "windows|linux|android", "user": "<account>",
 "ts": "2026-11-01T12:34:56+07:00", "reason": "schedule|parent",
 "keepDays": 30, "mime": "image/jpeg", "image": "<base64 JPEG, ≤ 1.5 MB>"}
```

Response (JSON): `{"ok": true, "id": "<fileId>", "name": "12-34-56.jpg", "path": "GreenGate/<device>/2026-11-01"}`
or `{"ok": false, "error": "..."}`. The script creates `<folder>/<device>/<YYYY-MM-DD>/<HH-MM-SS>.jpg`,
rejects anything that is not a JPEG or larger than 1.5 MB, accepts at most 30 uploads per device per
hour, and on every 20th upload trashes that device's files older than `keepDays`.

Device side: capture → JPEG (≤ 1280 px wide, quality 60) → POST with a 30 s timeout → on failure keep
the file in a local queue (`shots/queue`, at most 200 files, oldest dropped) and retry every refresh
cycle. Every capture, scheduled or requested by a parent, shows a notification that closes by itself
("GreenGate chụp màn hình theo lịch (mỗi 15 phút)" / "Bố mẹ vừa chụp màn hình"). The schedule only
runs once the device records consent from both a parent and the child (`consent` in the agent config
/ app preferences, set during setup); without it the device logs "no consent" and skips.

The parent app offers two views: the Drive folder (`driveFolder` button; history, 15-minute grain)
and the live `screenshot` command (§5) when the device is online.
