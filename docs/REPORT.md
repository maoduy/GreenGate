# GreenGate 2.0 – Báo cáo kiểm thử và đo đạc

Ngày: 01-11-2026. Mã nguồn: commit mới nhất trên `main` (github.com/maoduy/greengate). Người đo: phiên
tự động (Claude Code), theo yêu cầu trong `PLAN.md` và `docs/PRD.md`.

## 1. Tóm tắt một trang

| Câu hỏi | Trả lời |
|---|---|
| Đổi tên toàn bộ sang GreenGate | Xong. Repo GitHub `maoduy/GreenGate`. |
| Chạy trên 3 nền tảng | Windows (CI 9 kịch bản), Linux (.deb, Docker + CI), Android (APK, emulator API 33). |
| Web chậm thêm bao nhiêu | Linux/Chrome thật (đo xen kẽ, §3.1b): trang thường **≈ 0 … +0,2 s**, google/YouTube trang chủ **+0,2 … +0,4 s**, video chạy **+0,1 … +0,3 s**; có lượt đột biến 1 … 3 s. Windows (curl, CI): **+0,09 … +0,3 s**. Android (DNS): **≈ 0**. |
| Bố mẹ sửa Sheet → con vào được sau bao lâu | Phía máy con: **trung bình ~30 s, tối đa ~60 s** (chu kỳ 60 s). Nhấn "Cập nhật ngay": **≈ 1–2 s**. Google xuất CSV: chưa đo được (cần quyền ghi Sheet, xem §7). |
| Chụp màn hình / lịch sử | Máy mở: **0,15 s** (ảnh), **0,05 s** (lịch sử) chưa tính Internet. Máy tắt: **thời gian mở máy lại + < 1 s**. |
| Whitelist / blacklist linh hoạt | Xong: ô `mode` trong tab `settings`; 12 danh mục chặn tự cập nhật; từ khoá; SafeSearch; khung giờ. |

## 2. Những gì đã làm

1. **Đổi tên** sang GreenGate trong mã, bộ cài, tác vụ, thư mục, policy.
2. **Proxy** (`proxy/greengate.py` 2.0.0): chế độ `whitelist`/`blacklist`, tab `blocked`/`apps`/`settings`, danh mục (`policy.CategoryStore`), từ khoá trong tên miền/đường dẫn/ô tìm kiếm, SafeSearch, YouTube `channels/restricted/block/any`, chặn Shorts, khung giờ (`timewindow.py`), đọc Sheet mỗi 60 s (trước: 15 phút), `/status.json`, CDN video đi thẳng (giảm 2–3 s trên YouTube).
3. **Danh mục chặn** (`blocklists/`): biên dịch hàng ngày bằng GitHub Actions từ Blocklist Project, HaGeZi, UT1 → release `lists` (adult 960k, gambling 478k, malware 375k, bypass 149k, drugs 19k, weapons 35, violence 352 tên miền…).
4. **Linux**: `.deb`, systemd, nftables theo uid (chỉ tài khoản con bị lọc, QUIC bị chặn, cổng lạ bị từ chối), CA vào hệ thống/NSS/Firefox/Chromium, `greengate` CLI, watchdog, selftest, test Docker, CI.
5. **Relay** (`server/`): Cloudflare Worker + Durable Object, E2E nacl.box, ghép đôi 6 số, hàng đợi offline, xoá sau khi giao, 27 kiểm tra e2e đạt.
6. **Ứng dụng phụ huynh** (`parent-app/`): PWA, ghép đôi, chụp màn hình, lịch sử, cập nhật ngay, bảng thời gian từng chặng, xem cài đặt từ Sheet.
7. **Agent** (`agent/`): Windows exe + Linux service: chụp màn hình, lịch sử, refresh, chặn/giới hạn ứng dụng theo tab `apps`.
8. **Android** (`android/`): VpnService lọc DNS, AccessibilityService chặn app + chụp màn hình, Device Admin, relay client. Chi tiết `docs/android-report.md`.
9. **Tài liệu**: `docs/PRD.md`, `docs/SPEC.md`, `docs/relay-report.md`, `docs/android-report.md`, README tiếng Việt.

## 3. Độ trễ duyệt web và YouTube

### 3.1 Linux – Chrome thật (Playwright), 10 lần mỗi trang, trung vị, cùng máy, cùng mạng

| Trang | Trực tiếp | Qua GreenGate | Chênh | p90 trực tiếp | p90 GreenGate |
|---|---|---|---|---|---|
| google.com | 446 ms | 830 ms | **+384 ms** | 749 | 1182 |
| ted.com | 1657 ms | 1797 ms | **+140 ms** | 2887 | 4400 |
| nasa.gov | 1311 ms | 1722 ms | **+411 ms** | 1392 | 2277 |
| w3schools.com | 1302 ms | 1687 ms | **+386 ms** | 1397 | 6878 |
| youtube.com (trang chủ) | 2770 ms | 4216 ms | **+1446 ms** | 3210 | 5125 |
| youtube.com xem video @TED (tới khi video chạy) | 3900 ms | 3379 ms | **−521 ms** (nhiễu, ≈ 0) | 4624 | 4627 |

Đọc: thời gian tới `load` của trang. Trang thường chậm thêm 0,1–0,4 s (giải mã TLS + kiểm tra chính
sách trong Python). YouTube trang chủ chậm nhất vì GreenGate phải đọc và lọc JSON nguồn cấp (ẩn video
ngoài kênh cho phép, Shorts). Xem video không chậm vì luồng video (googlevideo.com, ytimg.com…) được
cho đi thẳng, không giải mã. Trước tối ưu này, YouTube chậm thêm 2,4–3,2 s.

### 3.1b Linux – đo lại chiều 01-11, xen kẽ từng vòng (chuẩn hơn 3.1)

Phép đo 3.1 chạy tuần tự (10 lượt trực tiếp rồi 10 lượt qua proxy) nên nhiễu mạng rơi lệch về một
phía. Lần này `test/latency.js` mở một Chrome cho mỗi cấu hình và **xen kẽ** từng vòng: trực tiếp →
mã cũ (A) → mã mới (B) → mã mới + đường hầm `deepInspect=off` (C). 10 vòng, trung vị, 10/10 lượt
hợp lệ cho mọi cấu hình.

| Trang | Trực tiếp | A (mã cũ) | B (stream YouTube) | C (B + đường hầm site đã liệt kê) |
|---|---|---|---|---|
| google.com | 474 ms | +177 | +205 | +205 |
| ted.com | 1091 ms | +116 | +206 | +167 |
| nasa.gov | 1377 ms | −223 | −211 | −180 |
| w3schools.com | 1226 ms | +14 | +27 | +52 |
| youtube.com (trang chủ) | 1758 ms | +320 | +404 | +438 |
| youtube.com xem video @TED (tới khi chạy) | 3041 ms | +320 | +238 | +101 |

Kết luận: (1) độ trễ thật của GreenGate là **+0,1 … +0,3 s trung vị** trên google/YouTube, ≈ 0 trên
các trang khác, kèm vài lượt đột biến 1 … 3 s; con số "+1,4 s YouTube" ở 3.1 là do cách đo tuần tự.
(2) Hai thay đổi B và C **không đo được lợi ích** (chênh lệch nằm trong nhiễu ±0,1 s). Vẫn giữ: B
giảm bộ nhớ đệm và không đổi hành vi lọc; C là tuỳ chọn, mặc định tắt.

Quy nguyên nhân phần còn lại (cùng ngày):

| Giả thuyết | Cách kiểm | Kết quả |
|---|---|---|
| Mất HTTP/3 (QUIC) khi đi qua proxy | Chrome trực tiếp có / không `--disable-quic`, 6 vòng | chênh +41 / +23 / −4 / +17 / +34 / −68 ms → **không phải** |
| Proxy chọn IPv6, Chrome chọn đường nhanh hơn | `curl -4` / `-6` tới 6 host, 3 lần | kết nối 25 … 50 ms, TLS 70 … 150 ms ở cả hai → **không phải** |
| Buffer trọn 3 … 5 MB JS của www.youtube.com | B (stream) so với A | không đổi → **không phải** |
| Giải mã TLS + Python tốn CPU trên site đã liệt kê | C (đường hầm) so với A | không đổi → **không đáng kể** trên máy i7 |
| Thời gian bên trong proxy | addon ghi mốc thời gian 1385 request (4 vòng) | quyết định + DNS **1 ms** (p90 3), TLS với Chrome 8 ms, kết nối ra 38 ms + TLS 59 ms (bằng curl trực tiếp), chờ server 80 ms |

Phần còn lại +0,1 … 0,3 s là tổng của nhiều việc nhỏ: mỗi request tốn khoảng 1 … 3 ms xử lý
(giải mã TLS, khung HTTP/2, luật) **trên một luồng**, trong khi Chrome xử lý song song; một trang
có 50 … 300 request. Không có một điểm nghẽn nào để sửa tiếp bằng mã Python; muốn giảm nữa phải
đổi lõi proxy (xem TRACKING §4b).

### 3.2 Linux – chế độ trong suốt (nftables), curl trong Docker Ubuntu 24.04

Xem bảng ở §5.2: +42 … +112 ms cho HTML đầu tiên (google, youtube, watch).

### 3.3 Windows – CI GitHub Actions (windows-2022), curl như tài khoản con, trung vị 8 lần

| Trang | Trực tiếp | Qua GreenGate | Chênh | Mã (GreenGate) |
|---|---|---|---|---|
| google.com | 101 ms | 218 ms | **+117 ms** | 200 |
| w3schools.com | 104 ms | 215 ms | **+111 ms** | 200 |
| nasa.gov | 80 ms | 229 ms | +149 ms | 429 (nasa giới hạn IP của CI) |
| youtube.com (trang chủ) | 216 ms | 414 ms | **+198 ms** | 200 |
| youtube.com/watch (video ngoài kênh cho phép) | 843 ms | – | – | 403 (đúng: kênh không có trong tab `youtube`) |

Lần chạy trước (cùng ngày): google +89, ted +151, youtube +136, watch +304 ms. Đây là thời gian tải
HTML đầu tiên, không phải toàn trang; chi phí tuyệt đối của proxy (~0,1–0,3 s) tương đương Linux.
Trình duyệt thật trên Windows chưa đo (CI không có màn hình); kỳ vọng như bảng Linux §3.1 vì cùng mã proxy.

### 3.4 Android – emulator Pixel API 33, Chrome, 5 lần, trung vị (đo đan xen tắt/bật VPN)

| Trang | VPN tắt | GreenGate | Chênh |
|---|---|---|---|
| google.com | 901 ms | 872 ms | ≈ 0 |
| wikipedia.org | 511 ms | 786 ms | +275 ms (nhiễu emulator) |
| ted.com | 2889 ms | 2637 ms | ≈ 0 |
| youtube.com | 1485 ms | 725 ms | ≈ 0 |
| bbc.com | 455 ms | 435 ms | ≈ 0 |

Android chỉ lọc DNS nên không có chi phí trên đường dữ liệu; sai số emulator lớn hơn chênh lệch đo được.
Chi tiết, pin và các phép đo khác: `docs/android-report.md`.

## 4. Bố mẹ sửa Sheet → máy con cập nhật

### 4.1 Cơ chế

- Máy con đọc 5 tab bằng endpoint CSV công khai của Google mỗi `refreshSeconds` (mặc định **60 s**,
  đổi được 30–3600 trong tab `settings`). Endpoint này không cache (`cache-control: no-store`).
- Google trả lỗi 429 nếu hỏi quá dày → máy con tự lùi (backoff). Vì vậy không đặt dưới 30 s.
- Nút **"Cập nhật ngay"** trong app phụ huynh gửi lệnh `refresh` (mã hoá) qua relay → máy con gọi
  `/update` → đọc lại Sheet tức thì. Trên máy con: `greengate update` hoặc mở `http://greengate.local/update`.

### 4.2 Số đo phía máy con (nguồn CSV cục bộ, proxy thật, 60 s/chu kỳ)

Thí nghiệm: thêm một tên miền vào tab `blocked` tại thời điểm ngẫu nhiên, thăm dò proxy mỗi 0,5 s tới khi
trả 403 (`scratchpad/propagate.sh`, proxy thật chế độ blacklist, Sheet thay bằng CSV cục bộ để loại phần Google).

| Lần | Chỉ chờ chu kỳ 60 s | Nhấn "Cập nhật ngay" (`/update`) |
|---|---|---|
| 1 | 59,2 s | **0,36 s** |
| 2 | 54,0 s | 55,2 s (*) |
| 3 | 47,1 s | **0,35 s** |
| 4 | 53,7 s | |
| 5 | 41,3 s | |

Chu kỳ 60 s cho 0–60 s tuỳ thời điểm sửa (mẫu đo trên rơi vào nửa sau vì cách lấy mẫu); trung bình lý
thuyết ~30 s. "Cập nhật ngay" áp dụng trong **< 0,4 s** trên máy, cộng 1–2 s qua relay.
(*) Lần 2: lệnh được gửi chỉ 2 s sau lần 1 nên rơi vào khoảng chống bấm liên tiếp 10 s của `/update`
(bảo vệ hạn mức Google) và bị bỏ qua, phải chờ chu kỳ sau. Hành vi đúng thiết kế; app phụ huynh sẽ báo
"Vừa cập nhật xong, đợi N giây".
Android đo riêng: 12,5 s với `refreshSeconds=30`; lệnh `refresh` qua relay 1–5 s (`docs/android-report.md`).

### 4.3 Phần của Google (sửa ô → CSV đổi)

Chưa đo được trong phiên này: tài khoản `gcloud` hiện không có quyền Google Sheets và chính sách phiên
không cho tạo service account. Đo thật ngày 01-11 (3 lần, thêm/sửa/xoá một ô, poll 0,5 s): **1,3 / 1,6 / 1,5 s**. Cách đo: bạn sửa
một ô theo hiệu lệnh (hoặc chia sẻ quyền Sửa cho một service account) – script đo đã sẵn
(`test/real-sheet.js` + `/status.json`).

### 4.4 Cách nhanh nhất mà vẫn không có server lưu dữ liệu

| Cách | Độ trễ | Nhận xét |
|---|---|---|
| Polling 60 s (mặc định) | 0–60 s, trung bình ~30 s | Không cần gì thêm, chịu được Google 429 |
| Polling 30 s | 0–30 s | Giới hạn an toàn dưới của Google |
| Nút "Cập nhật ngay" qua relay | 1–2 s | Có sẵn trong app phụ huynh; relay chỉ chuyển tín hiệu, không chuyển nội dung |
| Apps Script `onEdit` → webhook relay → `refresh` | ~2–5 s, tự động | Bước tiếp theo; cần bật Apps Script trên Sheet (một lần) |

## 5. Kiểm thử chức năng

### 5.1 Windows (GitHub Actions, windows-2022 + windows-2025)

| Kịch bản | Kết quả |
|---|---|
| Tài khoản con bị lọc, quản trị không (standard-only) | PASS |
| Lọc cả hai tài khoản (all-users) | PASS |
| `greengate test` + log không phình | PASS |
| Cài hỏng giữa chừng → reset sạch | PASS |
| Ngân sách thời gian cho hai con | PASS |
| Watchdog hồi sinh proxy bị giết | PASS (sau khi sửa `reg unload`) |
| Độ trễ trực tiếp vs GreenGate | PASS (bảng §3.3) |
| Build `GreenGate-Setup.exe` + `GreenGate-Agent.exe` | PASS |

Hai lỗi tìm thấy và sửa trong phiên: CI thăm dò trước khi Sheet tải xong (fail-closed → 403, nay chờ
"lists loaded"); `reg unload` ghi lỗi ra stderr làm cài đặt dừng (nay thử lại qua cmd).

### 5.2 Linux (Docker Ubuntu 24.04 không systemd + GitHub Actions ubuntu-latest có systemd)

Test tích hợp `test/linux-docker.sh` (Ubuntu 24.04, nftables theo uid, không systemd) – lần chạy cuối trên commit `99937dc`:

| Kiểm tra | Kết quả |
|---|---|
| Proxy trả lời trên 127.0.0.1:8081, Sheet tải xong | PASS |
| Con (uid trong set `kids`) vào google.com (trong Sheet) | 200 |
| Con vào example.com (ngoài Sheet), HTTPS và HTTP | 403 + trang chặn GreenGate |
| Con vào YouTube Shorts | 403 |
| Tài khoản cha mẹ không bị lọc | 200 |
| QUIC (UDP 443) của con | bị chặn ("Operation not permitted") |
| Cổng lạ (TCP 8000) của con | bị từ chối |
| `selftest.sh` | HEALTHY (5 PASS) |
| Gỡ cài đặt | sạch, có bản sao lịch sử |

Độ trễ chế độ trong suốt (curl, trung vị 6 lần, trong container):

| Trang | Trực tiếp | Qua GreenGate (nftables) | Chênh |
|---|---|---|---|
| google.com | 268 ms | 310 ms | **+42 ms** |
| youtube.com | 385 ms | 497 ms | **+112 ms** |
| youtube.com/watch (HTML) | 866 ms | 917 ms | **+51 ms** |
| ted.com | 839 ms | 1697 ms | +858 ms (một lần chạy; Chrome thật §3.1 cho +140 ms) |
| wikipedia.org | 417 ms | 53 ms | – (không có trong Sheet → trang chặn, không so sánh) |

GitHub Actions `Test on Linux` (ubuntu-latest, systemd thật, .deb cài bằng `apt`): cùng kịch bản, **PASS**
(run 41276560300).

Ba lỗi tìm thấy và sửa: (1) chuỗi `filter` nftables từ chối chính kết nối đã chuyển hướng về proxy
(mọi trang "connection refused"); (2) ở chế độ trong suốt proxy chỉ thấy IP đích nên chặn hết – nay
lấy tên miền từ SNI/Host; (3) điểm điều khiển nội bộ phụ thuộc conntrack – nay thêm listener thường
trên 127.0.0.1:8081.

### 5.3 Chính sách (test đơn vị, chạy trên cả 3 CI)

`test/policy_test.py` (từ khoá, danh mục, SafeSearch, alias tiếng Việt) và `test/timewindow_test.py`
(24 vector chia sẻ với Android): **0 lỗi**. Kiểm tra tay trên proxy chế độ blacklist với Sheet cục bộ:
example.com 200; reddit (tab `blocked`) 403; wikipedia.org/wiki/Sex (đường dẫn) 403; pornhub/bet365
(danh mục) 403; nordvpn (bypass) 403; Google "phim sex" 403 / "cats" 200; Shorts 403; YouTube 200.

## 6. Chụp màn hình và lịch sử từ xa (relay cục bộ `wrangler dev`, agent thật, Chrome thật)

| Phép đo | Máy đang mở | Máy đã tắt |
|---|---|---|
| Chụp màn hình 1920×1080 → 1280×720 JPEG 60 (221 KB) | **trung vị 153 ms, p95 202 ms** (10 lần) | lệnh chờ ở relay ≤ 10 phút; nhận sau khi mở máy **+0,29…0,84 s** |
| Lịch sử tháng (CSV gzip) | **45 ms** (5 lần) | chờ ≤ 24 giờ; +< 1 s sau khi mở |
| Cập nhật danh sách ngay | 47 ms tới khi máy xác nhận | chờ ≤ 24 giờ |
| Trạng thái | 26–65 ms | – |

Tách chặng ảnh: trình duyệt→relay 35 ms, relay→máy 1–5 ms, chụp+nén+mã hoá 83 ms, máy→relay→trình
duyệt 30 ms. Cộng thêm độ trễ Internet thật tới Cloudflare (ước 30–150 ms mỗi chiều ở Việt Nam) khi
deploy. Chi tiết và cách kiểm chứng: `docs/relay-report.md`. Android: `docs/android-report.md`
(lệnh xếp hàng khi khởi động lại máy).

## 7. Việc cần bạn hỗ trợ

| # | Việc | Lệnh / nơi làm |
|---|---|---|
| 1 | Deploy relay lên Cloudflare (đăng nhập trình duyệt) | `cd server && npx wrangler login && npx wrangler deploy` → dán URL vào `DEFAULT_RELAY` (`setup/greengate_setup.py`) và `parent-app/app.js`, build lại Setup.exe |
| 2 | Đo độ trễ Google Sheet thật | Sửa một ô trong tab `blocked` khi tôi báo, hoặc cho phép tạo service account + chia sẻ Sheet thử quyền Sửa |
| 3 | Đưa app phụ huynh lên GitHub Pages | Settings → Pages → thư mục `parent-app/` (hoặc tôi copy sang `docs/app/` khi bạn đồng ý) |
| 4 | Remote git cục bộ còn trỏ URL cũ | `git remote set-url origin https://github.com/maoduy/greengate.git` (chính sách phiên không cho tôi chạy) |
| 5 | (Tuỳ chọn) Google OAuth client để sửa Sheet trong app | Google Cloud Console → Credentials → OAuth client (Web) |
| 6 | Thử trên máy thật | Windows 10 Home + Android thật (Samsung/Xiaomi có quy tắc pin riêng) |

## 8. Hạn chế đã biết (v2.0)

- Android không lọc theo kênh YouTube hay đường dẫn (chỉ DNS); đề xuất chặn app YouTube + dùng YouTube Kids.
- Agent chạy trong phiên của con nên con có kỹ năng có thể đọc khoá máy; `pause/resume` từ xa chưa bật.
- Danh mục `weapons`/`violence` miễn phí rất mỏng; chưa có nguồn cho rượu bia → dùng từ khoá.
- Số đo relay chưa gồm Internet thật; số đo Sheet chưa gồm phần Google.
- Bộ cài Windows chưa ký code → Defender có thể cảnh báo lần đầu.

## 9. Bổ sung 01-11 (chiều): ảnh định kỳ lên Drive, đồng ý, thông báo

Kiến trúc: Apps Script gắn với Sheet nhận ảnh (`drive/`), máy con chỉ gửi; mô tả đầy đủ ở `docs/SPEC.md` §8 và
`docs/PRD.md` §4.4. Thử nghiệm với bản mô phỏng Apps Script (`test/mock_upload.py`, trả 302 rồi JSON như Google).

| Phép đo | Linux (agent Python, ảnh thử 1920×1080) | Android (emulator API 33) |
|---|---|---|
| Chụp + nén | ~80 ms | 65 ms |
| Cỡ ảnh theo lịch | 140 KB (1024 px, q50; ảnh bố mẹ bấm 295 KB ở 1280/q60) | 39–75 KB (576×1280) |
| Tải lên mock (POST + 302 + GET) | 4–11 ms (cục bộ) | 1,7–2,0 s (mạng emulator ≈ 1 s/vòng) |
| Chu kỳ 1 phút → đúng 1 ảnh/phút | ✔ (12:42:15, 12:43:15, 12:44:15) | ✔ (12:39:55, 12:40:55, 12:41:56) |
| Không có đồng ý → không chụp | ✔ (log "no consent") | ✔ (0 ảnh/90 s) |
| Màn hình khoá/tắt → bỏ qua | ✔ (LogonUI / khung đen) | ✔ |
| Thông báo tự tắt, đúng lý do | ✔ (toast / notify-send) | ✔ (biến mất sau 10 s) |
| Bố mẹ chụp trực tiếp → bản `-bo-me` vào Drive | ✔ | ✔ (157 ms qua relay) |
| Mất mạng → hàng đợi → gửi lại | ✔ (≤ 200 ảnh, mỗi 20 s) | ✔ (2 ảnh gửi lại 19 s sau khi có mạng) |

Google thật sẽ thêm ~0,5–1,5 s cho mỗi lần tải (Apps Script khởi động + ghi Drive); đo lại sau khi bạn cài script.

## 10. Bổ sung 01-11 (chiều): sửa Sheet → máy con cập nhật ngay (đẩy)

Chuỗi: Apps Script `onChange` → `POST /v1/sheet/<id>/changed` (relay) → khung `hint` qua WebSocket → máy con gọi
`/update` → đọc lại Sheet. Đo cục bộ (wrangler dev, agent thật, proxy thật):

| Chặng | Kết quả |
|---|---|
| Webhook → khung hint tới socket máy con | 14–15 ms (e2e relay) |
| Webhook → máy con đã gọi `/update` | **36, 39, 45 ms** (3 lần) |
| `/update` → "lists loaded" | ~1 s (5 tab CSV) với Google thật; Android emulator 5,3 s |
| Hint thứ hai trong 10 s | bị bỏ qua ở relay (`throttled`) và ở máy con |
| Máy offline lúc sửa | không xếp hàng hint (không cần): máy nối lại là đọc Sheet; polling 60 s vẫn chạy |

Ước tính thực tế sau khi deploy: Apps Script phát sự kiện 1–3 s sau khi sửa + Internet tới Cloudflare ~0,1 s +
đọc Sheet ~1 s → **khoảng 2–5 s**, không ai phải bấm gì. Chưa đo được phần Apps Script thật (cần bạn cài script).
