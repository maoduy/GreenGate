# GreenGate – Sổ theo dõi (tracking)

Một trang duy nhất: trạng thái hiện tại, các số đo, các điểm đã tối ưu, việc còn chờ. Cập nhật mỗi lần có
thay đổi lớn (ngày ở cột đầu). Chi tiết đo đạc nằm trong `docs/REPORT.md`, thiết kế trong `docs/PRD.md`,
hợp đồng kỹ thuật trong `docs/SPEC.md`.

## 0. Bức tranh tổng thể (01-11-2026, tối)

**Đã làm:** đổi tên toàn bộ sang GreenGate (repo, thư mục, tài liệu); proxy lọc 2.0 cho Windows/Linux
(whitelist/blacklist, 12 danh mục tự cập nhật, từ khoá, SafeSearch, kênh/Shorts YouTube, khung giờ, hạn
giờ/ngày, chặn app); Android 0.2.0 (lọc DNS qua VPN cục bộ, chặn app, ảnh định kỳ); agent chụp màn hình +
lịch sử + tải ảnh lên Drive theo lịch, thông báo cho con, đồng ý hai bên; relay Cloudflare + app phụ huynh;
đẩy "Sheet đổi" (Apps Script → relay → máy con); đọc Sheet bền (htmlview + export); Sheet thật đủ 5 tab;
Setup.exe/.deb/APK đều build xong; tài liệu PRD/SPEC/REPORT/TRACKING.

**Đã kiểm thử ở đâu** (✅ đã chạy thật, 🧪 máy ảo/CI/mock, ❌ chưa):

| Hạng mục | Windows | Linux | Android |
|---|---|---|---|
| Thiết bị dùng để test | 🧪 GitHub Actions `windows-2022` + `windows-2025` (Windows **Server**, không màn hình) | ✅ máy thật Ubuntu 24.04 (i7) + 🧪 Docker Ubuntu 24.04 + 🧪 CI `ubuntu-24.04` (systemd thật, cài `.deb` bằng apt) | 🧪 emulator Pixel API 33 |
| Cài đặt / gỡ / lỗi giữa chừng | 🧪 CI: all-users, standard-only, cài hỏng rồi reset (9 kịch bản, 9/9 xanh run 41310845061) | ✅ `.deb` cài trên máy thật + CI | 🧪 cài APK vào emulator |
| Lọc web, chặn, SafeSearch, khung giờ | 🧪 curl dưới tài khoản con (CI) | ✅ Chrome thật (Playwright) + curl | 🧪 Chrome trong emulator (chỉ DNS) |
| Độ trễ duyệt web / YouTube | 🧪 curl CI: +0,09…0,3 s; **trình duyệt thật chưa đo** | ✅ Chrome thật, đo xen kẽ: ≈ 0…+0,4 s | 🧪 ≈ 0 (nhiễu emulator lớn hơn chênh lệch) |
| Sửa Sheet thật → máy con nhận | ✅ Google xuất CSV mới sau 1,3–1,6 s (Sheet thật của bạn) → + chu kỳ 60 s hoặc đẩy | như Windows | như Windows |
| Đẩy "Sheet đổi" qua relay | 🧪 relay cục bộ `wrangler dev`, agent thật: 36–45 ms tới `/update` | 🧪 như Windows | 🧪 emulator: < 0,1 s nhận, 5,3 s đọc xong |
| Chụp màn hình trực tiếp, lịch sử | 🧪 relay cục bộ, agent thật trên Linux (153 ms); **Windows chưa chạy agent thật** (CI không có màn hình) | ✅ agent + Chrome thật, relay cục bộ | 🧪 emulator 76–157 ms |
| Máy tắt → kết quả khi mở | 🧪 lệnh chờ ≤ 10 phút, đo trên Linux (+0,3–0,8 s sau boot) | ✅ máy thật | 🧪 emulator +24 s sau boot |
| Ảnh định kỳ → Drive | 🧪 chụp+nén thật, tải lên **mock** (Apps Script chưa cài) | 🧪 như Windows | 🧪 emulator, mock |
| Watchdog / supervisor | 🧪 CI: dừng proxy → tự hồi (AdoptTree, pid) | ✅ systemd watchdog máy thật + CI | 🧪 emulator (VPN tự nối lại) |

**Chưa có môi trường nào kiểm thử:** Windows 10/11 **client** thật (chỉ Server trên CI), trình duyệt thật
trên Windows, điện thoại Android thật (Samsung/Xiaomi có chính sách pin riêng), relay đã deploy trên
Cloudflare (Internet thật), Apps Script + Drive thật, nhiều máy con cùng một Sheet ngoài CI.

## 1. Trạng thái hiện tại (01-11-2026)

| Hạng mục | Trạng thái | Ghi chú |
|---|---|---|
| Đổi tên sang GreenGate | ✅ | repo `maoduy/GreenGate` |
| Proxy Windows/Linux 2.0 (whitelist/blacklist, danh mục, từ khoá, SafeSearch, khung giờ) | ✅ | test đơn vị + CI xanh |
| Windows: `GreenGate-Setup.exe` + `GreenGate-Agent.exe` | ✅ build CI, release `latest` | chưa ký code |
| Linux: `greengate_2.0.0_all.deb` | ✅ Docker + CI xanh | transparent@8080 + control@8081 |
| Android APK | ✅ `android/dist/GreenGate-0.2.0.apk` (cục bộ) | chưa đăng Release (cần bạn) |
| Relay Cloudflare + app phụ huynh + agent | ✅ cục bộ (wrangler dev) | **chưa deploy** (cần `wrangler login`) |
| Danh mục chặn tự cập nhật | ✅ release `lists`, GitHub Actions hàng ngày | 12 danh mục |
| Ảnh định kỳ → Google Drive, thông báo cho con, đồng ý hai bên | ✅ mã + test mock | cần bạn cài Apps Script (3 phút) |
| Sửa Sheet → máy con cập nhật ngay (đẩy) | ✅ relay + agent + Android + Apps Script | hiệu lực sau khi deploy relay |
| Đo độ trễ Google Sheet thật | ✅ | 1,3 / 1,6 / 1,5 s (01-11 tối); Sheet đủ 5 tab |

## 2. Các số đo chính

| Phép đo | Windows | Linux | Android | Ghi chú |
|---|---|---|---|---|
| Trang thường chậm thêm (trung vị) | +0,09…0,15 s (curl, CI) | ≈ 0 … +0,2 s (Chrome thật, đo xen kẽ 01-11 chiều); +0,04…0,11 s (curl transparent) | ≈ 0 (chỉ DNS) | số buổi sáng +0,14…0,41 s là đo tuần tự |
| YouTube trang chủ | +0,2 s (HTML) | +0,2 … +0,4 s (Chrome; buổi sáng đo +1,4 s do đo tuần tự) | ≈ 0 | có lượt đột biến 1–3 s |
| Xem video YouTube | +0,3 s (HTML) | +0,1 … +0,3 s (tới khi video chạy) | ≈ 0 | CDN video đi thẳng |
| Sửa ô trong Sheet → Google xuất CSV mới (gviz, Sheet thật) | **1,3 / 1,6 / 1,5 s** (3 lần, 01-11 tối) | như Windows | như Windows | thêm dòng, sửa ô, xoá dòng; poll 0,5 s |
| Sửa Sheet → có hiệu lực, chỉ polling | 1,5 s + 0–60 s (đo 41–59 s) | như Windows | 12,5 s với 30 s | mặc định 60 s |
| "Cập nhật ngay" trên máy | 0,35 s | 0,35 s | 1–5 s | `/update` |
| Sửa Sheet → đẩy qua relay → máy đọc lại | **36–45 ms** tới lúc máy gọi `/update` (cục bộ), + ~1 s đọc Sheet | như Windows | < 0,1 s nhận, 5,3 s đọc xong (emulator) | webhook → socket 14 ms |
| Chụp màn hình trực tiếp (máy mở) | 153 ms trung vị (cục bộ) | 153 ms | 76–157 ms | + Internet thật |
| Máy tắt → kết quả | thời gian mở máy + 0,3–0,8 s | như Windows | +24 s sau boot | lệnh chờ ≤ 10 phút (ảnh) |
| Chụp theo lịch + tải Drive (mock) | – | chụp+nén ~80 ms, tải 4–11 ms (cục bộ), 140 KB | chụp 65 ms, tải 1,7–2 s (emulator), 39–75 KB | Google thật: cộng ~0,5–1,5 s |
| Hàng đợi khi mất mạng | giữ ≤ 200 ảnh, gửi lại mỗi 20 s | như Windows | gửi lại mỗi phút (19 s sau khi có mạng) | |

## 3. Đã tối ưu trong phiên này (và vì sao)

| # | Điểm | Trước | Sau | Lợi ích đo được |
|---|---|---|---|---|
| 1 | CDN video/ảnh YouTube đi thẳng không giải mã (`tls_clienthello` ignore) | YouTube +2,4…3,2 s | +1,4 s trang chủ, ≈ 0 khi xem video | −1…3 s mỗi lần xem |
| 2 | `upstream_cert=false` + `connection_strategy=lazy` | trang bị chặn trả 000/502, chờ TLS upstream | trang chặn trả 403 ngay | trang chặn hiện tức thì |
| 3 | Đọc Sheet 60 s thay 15 phút, lùi khi 429 | 0–15 phút | 0–60 s | thay đổi có hiệu lực nhanh 15× |
| 4 | Đẩy "Sheet đổi" qua relay (Apps Script → `/v1/sheet/<id>/changed` → hint) | phải chờ chu kỳ hoặc bấm nút | 1–5 s tự động | không còn phụ thuộc polling |
| 5 | Chỉ ghi log "lists loaded" khi có thay đổi (chữ ký) | 1 dòng/60 s | chỉ khi đổi | log sạch, dễ đọc |
| 6 | Linux: listener thường 8081 cho điều khiển | `greengate update`/watchdog lỗi trên một số kernel (conntrack) | luôn trả lời | watchdog không restart nhầm |
| 7 | Linux: lấy tên miền từ SNI (transparent) | chặn hết (chỉ thấy IP) | đúng tên miền | hoạt động |
| 8 | nftables: chấp nhận kết nối đã redirect | "connection refused" | hoạt động | hoạt động |
| 9 | Danh mục chặn dạng 8 byte/tên miền, tìm nhị phân | – | adult 960k tên miền = 7,7 MB, tra < 0,01 ms | RAM/thời gian nhỏ |
| 10 | Từ khoá: cụm dài ưu tiên, thứ tự xác định | kết quả CI thay đổi theo lần chạy | ổn định | CI tin được |
| 11 | CI chờ "lists loaded" trước khi thăm dò | fail ngẫu nhiên (fail-closed) | ổn định | 9/9 xanh |
| 12 | Ảnh định kỳ: bỏ khung đen/khoá máy, không chụp ngoài giờ | – | ít ảnh vô ích, ít tải lên | tiết kiệm Drive/pin |
| 13 | YouTube: chỉ buffer HTML/JSON cần sửa, stream JS/CSS/ảnh của www.youtube.com (`_yt_rewrite_candidate`) | buffer trọn mọi phản hồi YouTube | stream | **không đo được** (trong nhiễu); giữ vì ít RAM, không đổi lọc |
| 14 | `deepInspect=off`: site đã liệt kê đi thẳng không giải mã (`_tunnel_ok`), vẫn ghi lịch sử `host/` và đếm giờ theo kết nối | mọi site giải mã | tuỳ chọn, mặc định `on` | **không đo được** trên i7; để bố mẹ chọn cho máy yếu |
| 15 | `urlLog.localFile: true` làm proxy mất stdout (open(True) đóng fd 1) → mitmproxy lỗi mọi kết nối | treo im lặng | `_local_log_path()` coi true = đường dẫn mặc định | sửa lỗi tiềm ẩn |
| 16 | `test/latency.js`: nhiều cấu hình xen kẽ từng vòng, cấu hình `@--flag` cho Chrome trực tiếp, ghi lỗi từng lượt | đo tuần tự, lệch | so sánh công bằng | số đo tin được |
| 17 | Mọi URL gviz thêm `headers=1` (proxy, setup, Android, app phụ huynh, test ps1) | tab `settings` có số ở cột B (60, 15, 30) → gviz đoán 6 dòng đầu là tiêu đề và gộp lại, mất `mode`, `youtube`, `shorts`, `safesearch`; phát hiện khi tạo tab thật 01-11 tối |
| 18 | Đọc Sheet bằng `/htmlview` (lấy gid theo tên tab) + `/export?format=csv&gid=` ở proxy, setup, Android, app phụ huynh; gviz chỉ còn là dự phòng | gviz ép kiểu từng cột: ô chữ trong cột đa số là số bị xuất RỖNG (`chặn` cạnh `60` ở tab `apps`, `blacklist` cạnh `30` ở `settings`) → quy tắc của phụ huynh bị bỏ qua trong im lặng; phát hiện 01-11 tối khi ô `block` gõ vào Sheet thật không xuất hiện trong CSV. Export giữ nguyên ô; tab vắng trong htmlview = không tồn tại, bỏ được mẹo dò tab giả |
| 19 | Dòng tiêu đề tự đặt (có khoảng trắng hoặc ngoặc) bị bỏ qua ở mọi tab (proxy + Android) | trước chỉ bỏ qua tiêu đề thuộc danh sách từ quen; tiêu đề `Trang web luôn chặn` và `App (tên gói …)` bị đếm thành 1 quy tắc và báo lỗi khung giờ; tên miền, gói, exe, @handle không bao giờ chứa khoảng trắng nên quy tắc này an toàn |
| 20 | Supervisor Windows: nhận (adopt) mọi tiến trình con của mitmdump vào job object trong lúc chờ proxy sẵn sàng | tiến trình chỉ vào job nếu cha đã ở trong job lúc nó được tạo; bootstrap PyInstaller có thể sinh server trong khe giữa Start-Process và AssignProcessToJobObject → dừng task để sót server (CI job watchdog hỏng 1/3 lần, run 41309889270) |
| 21 | Mọi fetch HTTPS (proxy, sheetlog, Setup.exe) tin OS store **cộng** certifi; Setup.exe đóng gói certifi | Windows 11 Home vừa cài (máy ảo QEMU, 02-11) gần như chưa có CA gốc nào, chỉ tải khi schannel cần; Python/OpenSSL không kích hoạt việc đó → Setup.exe báo `CERTIFICATE_VERIFY_FAILED` khi kiểm tra Sheet dù Edge vào Google bình thường; proxy cũng sẽ không đọc được Sheet trên máy mới. CI Windows Server không lộ lỗi vì image đã có sẵn CA |
| 22 | Tra chủ socket chỉ nhận dòng ESTABLISHED (Linux `st=01`, Windows `MIB_TCP_STATE_ESTAB`) | Dòng TIME_WAIT (uid 0 / pid 0) cùng số cổng làm kết nối của con bị coi là của admin → đi qua **không lọc**, thấy 2/25 lần tải trang khi quay video Linux 02-11 |
| 23 | `/update` gọi trong lúc một lần làm mới đang chạy được xếp hàng và chạy lại ngay sau đó | Trước bị bỏ qua ("đang cập nhật ở chế độ nền"); clip Linux 8 cho thấy quy tắc mới mất 37–46 s thay vì 1 s |
| 24 | Setup.exe: nút "Cài đặt" đặt trên khung log, log còn 4 dòng khi màn hình < 900 px, cho phép kéo cao | Trên màn 1280×800 (và laptop 1366×768 phổ biến) cửa sổ cao hơn màn hình, nút "Cài đặt" nằm dưới thanh taskbar, không bấm được và không phóng to được; thấy trong máy ảo Windows 11 Home 02-11 |
| 25 | Android: dịch vụ chặn app đọc quy tắc từ bộ nhớ đệm khi VPN chưa nạp, và tự bật lại VPN nếu thấy tắt trong lúc bảo vệ đang bật (`AppBlockerService.kt`) | Khi tiến trình app bị Android giết (ANR 02-11 12:04), hệ thống chỉ khởi động lại dịch vụ trợ năng, không bật lại VPN → không chặn app nào và mạng của con không còn lọc; phát hiện khi quay A4 |
| 26 | Windows: `greengate-policy.ps1` mới - installer tự **tạo profile** cho tài khoản con chưa từng đăng nhập (`userenv!CreateProfile`, đúng cách Windows làm ở lần đăng nhập đầu) rồi ghi policy proxy vào hive; supervisor kiểm tra mỗi 30 s và tự áp policy cho tài khoản được bảo vệ đang đăng nhập mà thiếu policy | Trên máy ảo Windows 11 Home 02-11: bố mẹ tạo tài khoản "Con" rồi cài ngay (Con chưa đăng nhập lần nào) → installer cũ chỉ in dòng vàng "log in once, then re-run" rồi báo cài xong; Edge của Con đi thẳng ra mạng, vnexpress.net mở bình thường. CI trước đây "cho tài khoản một profile" trước khi cài nên không bao giờ thấy lỗi này; nay CI để tài khoản con chưa đăng nhập đúng như ở nhà |
| 27 | Windows: CI tự build `mitmdump.exe` từ cùng bản mitmproxy 12.2.3 nhưng **bỏ gói `mitmproxy_windows`** (driver WinDivert chỉ dùng cho chế độ transparent, GreenGate không dùng), quét bằng Defender ngay trên runner trước khi đóng gói; publish thêm `mitmdump.exe` vào release | Máy ảo Windows 11 Home 02-11: cài xong chạy tốt, 25 phút sau Defender cập nhật định nghĩa và cách ly `mitmdump.exe` với tên **Trojan:Win64/WinDivert** → proxy chết, supervisor sau 5 lần khởi động hỏng chuyển sang "mở mạng" (đúng thiết kế, nhưng con không còn được lọc). Không thêm loại trừ Defender vào installer (giữ nguyên tắc "không đụng vào antivirus"); sửa tận gốc bằng cách không đóng gói driver |

## 4. Rà soát tối ưu sau khi hoàn thành (01-11, lần 1)

Rà soát toàn bộ mã mới (agent, relay, Apps Script, policy, Android) sau khi hoàn thành yêu cầu bổ sung.

**Đã tối ưu ngay:**

| # | Chỗ | Vấn đề thấy khi rà soát | Đã làm |
|---|---|---|---|
| R1 | Agent, ảnh theo lịch | Ảnh 1280 px / q60 ≈ 295 KB; 96 ảnh/ngày ≈ 28 MB/ngày/máy ≈ 0,85 GB/tháng với lưu 30 ngày | Ảnh theo lịch dùng 1024 px / q50 (ảnh bố mẹ bấm giữ 1280/q60) → ~140 KB thay vì 295 KB (−53 %) |
| R2 | Agent, khởi động | Lần chụp đầu xảy ra 20 s sau mỗi lần agent khởi động → watchdog/đăng nhập lại tạo ảnh thừa | Lần đầu cách thời điểm khởi động đúng một chu kỳ |
| R3 | Relay `SheetDO.changed` | Báo từng máy tuần tự (await trong vòng lặp) | `Promise.all` – nhà có N máy vẫn chỉ tốn một vòng |
| R4 | Linux điều khiển nội bộ | `greengate update`/watchdog qua cổng transparent phụ thuộc conntrack | Listener thường 8081 (đã làm ở phần trước, giữ lại vì agent cũng dùng) |
| R5 | Agent, hint | Hint tới liên tiếp (nhiều người sửa Sheet) gây nhiều `/update` | Chặn < 10 s ở cả relay (mỗi Sheet), agent và proxy |

**Đã xem, quyết định giữ nguyên (ghi lý do):**

- Polling 60 s giữ làm dự phòng dù đã có đẩy: relay chưa deploy và máy offline lúc sửa Sheet vẫn cần bắt kịp; chi phí 1 request CSV/phút là nhỏ. Khi relay chạy ổn có thể đặt `refreshSeconds=300`.
- Thông báo Windows chạy PowerShell (~0,5 s CPU) mỗi lần chụp: 96 lần/ngày là chấp nhận được; đổi sang thư viện toast riêng không đáng thêm phụ thuộc.
- Ảnh để dạng thường trong Drive (không mã hoá) vì yêu cầu "xem trong Drive"; đã nêu rủi ro ở §6.
- Apps Script kiểm tra hạn mức bằng CacheService (30 ảnh/giờ/máy) và dọn thùng rác mỗi 20 lần: đủ nhẹ, không cần trigger theo giờ.
- Android không giữ bản mã hoá cục bộ (PC có): máy điện thoại ít dung lượng, Drive là nơi lưu; hàng đợi 200 ảnh đủ cho ~2 ngày mất mạng.

**Đề xuất cho vòng sau (chưa làm):**

- Chụp theo lịch thông minh: bỏ qua nếu ảnh không đổi so với lần trước (so sánh ảnh thu nhỏ) → tiết kiệm thêm khi con bỏ máy mở.
- Agent chạy dưới quyền hệ thống (Windows service / systemd system) cho phần tải lên để con không đọc được URL/khoá; phần chụp vẫn trong phiên.
- Trang chỉ mục trong Drive (một file HTML/ngày do Apps Script tạo) để bố mẹ lướt ảnh nhanh hơn trên điện thoại.
- Web Push cho app phụ huynh khi máy con offline quá lâu / khi hàng đợi ảnh > 20.

## 4b. Rà soát lần 2 (01-11, chiều): độ trễ duyệt web

Câu hỏi của bạn: vì sao YouTube +1,4 s, có đẩy nhanh được không. Đã làm mục 1 (stream YouTube) và
mục 2 (đường hầm site đã liệt kê), đo lại xen kẽ 10 vòng (REPORT §3.1b).

| Kết quả | Chi tiết |
|---|---|
| Độ trễ thật nhỏ hơn số buổi sáng | +0,1 … +0,3 s trung vị (google, YouTube), ≈ 0 trang khác; "+1,4 s" là do đo tuần tự |
| Mục 1 và 2 không giảm thêm | chênh lệch trong nhiễu ±0,1 s; giữ mục 1 (ít RAM), mục 2 là tuỳ chọn |
| Không phải do mất HTTP/3 | Chrome trực tiếp tắt QUIC chênh ±40 ms |
| Không phải do IPv6 | `curl -4/-6` tương đương |
| Không phải do Python chậm ở một điểm | bên trong proxy: quyết định 1 ms, TLS với Chrome 8 ms, kết nối ra = curl |
| Nguyên nhân còn lại | 1 … 3 ms mỗi request × 50 … 300 request, xử lý trên **một luồng** |

**Đa luồng có giúp không?** Không với thread: Python có GIL, mitmproxy là một vòng lặp asyncio.
Có thể chạy **nhiều tiến trình** (Linux: nftables chia kết nối theo `numgen` sang 2 … 4 cổng; Windows
cần thêm bộ chia cổng), nhưng trạng thái dùng chung (giờ dùng, hint, log) phải qua file/socket và lợi
ích tối đa cỡ 0,1 … 0,2 s mỗi trang → **không làm**. Cách giảm thật sự là đổi lõi proxy sang Go/Rust
(viết lại bộ lọc), chỉ đáng nếu máy con yếu rõ rệt.

**Giải mã TLS đang mang lại gì** (mất nếu đi đường hầm): chặn theo đường dẫn (`blocked` dạng
`site/đường-dẫn`, cho phép theo đường dẫn), từ khoá trong đường dẫn và **ô tìm kiếm**, ép SafeSearch
và YouTube Restricted, lọc kênh/Shorts YouTube, trang chặn có lý do thay vì lỗi kết nối, lịch sử
đầy đủ URL, phân biệt trang/tài nguyên (`Sec-Fetch-Dest`) cho chế độ smart và đếm giờ đúng.

## 5. Việc cần bạn làm

| # | Việc | Thời gian | Cách |
|---|---|---|---|
| 1 | Deploy relay | 5 phút | `cd server && npx wrangler login && npx wrangler deploy`; dán URL vào `setup/greengate_setup.py` (`DEFAULT_RELAY`), `parent-app/app.js`, Apps Script (`RELAY`) |
| 2 | Cài Apps Script vào Sheet | 3 phút | `drive/README.md` (dán script, Triển khai web app, dán URL vào `uploadUrl`, chạy `setupTrigger`) |
| 3 | Đăng APK lên GitHub Release | 1 phút | `gh release create android-v0.2.0 android/dist/GreenGate-0.2.0.apk -R maoduy/greengate` (chính sách phiên không cho tôi tạo release) |
| 4 | Sao lưu keystore Android | 1 phút | `android/keystore/` (đã gitignore) – mất là không cập nhật được app trên máy đã cài |
| 5 | ~~Đổi tên thư mục + remote git~~ | xong 01-11 | `~/greengate`, remote `maoduy/greengate`, lịch sử Claude Code đã chuyển theo |
| 6 | ~~Đo Sheet thật~~ | xong 01-11 | gviz cập nhật 1,3–1,6 s sau khi sửa ô (3 lần); đã tạo tab `settings`, `blocked`, `apps` trong Sheet của bạn |
| 7 | App phụ huynh lên GitHub Pages | 2 phút | Settings → Pages → thư mục `parent-app/` (hoặc cho phép tôi copy sang `docs/app/`) |

## 6. Hạn chế đã biết

- Android: không lọc kênh YouTube / đường dẫn (DNS); khuyến nghị `youtube=block` + YouTube Kids.
- Agent chạy trong phiên của con: con có kỹ năng có thể đọc cấu hình agent (URL tải ảnh, khoá máy); `pause/resume` từ xa chưa bật.
- Ảnh trong Drive để dạng thường (để xem bằng app Drive); URL tải ảnh nằm trong Sheet công khai → chỉ nhận JPEG ≤ 1,5 MB, 30 ảnh/giờ/máy; có thể giấu URL vào máy con bằng `greengate drive --set`.
- Danh mục weapons/violence mỏng; chưa có nguồn rượu bia → từ khoá.
- Số đo relay và Drive chưa gồm Internet thật.

## 8. Kế thừa từ dự án mã nguồn mở (03-11-2026)

Chi tiết + giấy phép + cách ghi công: [`docs/KE-THUA-NGUON-MO.md`](KE-THUA-NGUON-MO.md).
Nguyên tắc: không đọ engine lọc với dự án đã chín, mượn **dữ liệu + ý tưởng**, dồn sức vào
phần GreenGate độc đáo.

| # | Việc | Loại | Ưu tiên |
|---|---|---|---|
| 1 | `blocklists/CREDITS.md` + `blocklists/LICENSE` (CC BY-SA) | ghi công | cao |
| 2 | Script `blocklists/fetch.sh` tự ghi nguồn/giấy phép/ngày | ghi công | cao |
| 3 | Nhập UT1 Toulouse → ánh xạ ~100 danh mục sang GreenGate (CC BY-SA) | dữ liệu | cao |
| 4 | Nhập StevenBlack (MIT) + abuse.ch URLhaus | dữ liệu | vừa |
| 5 | Chấm điểm cụm từ **có trọng số** trong `proxy/policy.py` (học e2guardian) | engine | vừa |
| 6 | Đọc cú pháp filter kiểu AdGuard/EasyList | engine | thấp |
| 7 | Xác nhận giấy phép Hagezi trong LICENSE gốc trước khi dùng | kiểm tra | chặn #? |

**Tránh:** OISD (gộp list bỏ qua giấy phép gốc → không phân phối lại).

## 7. Lịch sử

| Ngày | Việc |
|---|---|
| 30-10-2026 | Kế hoạch ban đầu (`PLAN.md`) |
| 01-11-2026 | Đổi tên GreenGate; proxy 2.0; Linux .deb; relay + app + agent; Android 0.1.0; danh mục; đo đạc (REPORT) |
| 01-11-2026 | Yêu cầu bổ sung: ảnh định kỳ → Drive + thông báo + đồng ý; đẩy "Sheet đổi"; Android 0.2.0; TRACKING.md |
| 01-11-2026 (chiều) | Rà soát độ trễ: stream YouTube, `deepInspect`, đo xen kẽ, quy nguyên nhân; sửa lỗi `localFile: true` |
| 01-11 tối | Đổi tên thư mục `~/greengate`; tạo tab `settings`/`blocked`/`apps` trong Sheet thật; sửa lỗi gviz gộp tiêu đề (`headers=1`); đo lan truyền Sheet thật 1,3–1,6 s |
| 01-11 tối (sự cố) | Khi gõ tab `settings` qua Chrome, 8 dòng (8–15) rơi vào tab `youtube` và đè 9 dòng đầu cột A–C; người dùng phát hiện. Khôi phục từ bản CSV tải trước khi sửa, so khớp 75/75 dòng; gõ lại 8 khoá vào `settings`. Bài học: sau mỗi lần gõ phải đối chiếu CSV với bản gốc, không chỉ đọc giá trị ra |
| 01-11 tối (2) | Phát hiện gviz làm rỗng ô chữ trong cột số; chuyển sang htmlview + export?gid= trên 4 nền; gviz làm dự phòng |
| 02-11 sáng | Quay video + ảnh 11 kịch bản Linux/Android (`docs/videos/`); sửa 2 lỗi phát hiện khi quay (TIME_WAIT, `/update` bị bỏ); dựng máy ảo Windows 11 Home (QEMU/KVM, 4 GB) → phát hiện và sửa lỗi CA gốc thiếu trên Windows mới cài; Setup.exe chưa ký nên UAC báo "unknown publisher" |
| 03-11-2026 | Phân tích cạnh tranh (tool trường/doanh nghiệp, chi phí); đề xuất hướng open-core (client Apache-2.0 + server AGPL-3.0); lập `KE-THUA-NGUON-MO.md`: dữ liệu/ý tưởng nên mượn + giấy phép + cách ghi công |
