# GreenGate – Tài liệu yêu cầu sản phẩm (PRD)

Phiên bản 2.0 · ngày 01-11-2026 · thay cho PLAN.md ngày 30-10-2026.

GreenGate là bộ lọc Internet cho gia đình: phụ huynh quản lý mọi thiết bị của con bằng **một Google
Sheet** và **một ứng dụng web** trên điện thoại. Không có máy chủ nào giữ dữ liệu của con.

---

## 1. Mục tiêu và nguyên tắc

| # | Mục tiêu | Thước đo |
|---|---|---|
| 1 | Phụ huynh chỉ cần Google Sheet để thay đổi mọi cài đặt | Thay đổi trên Sheet có hiệu lực trên máy con trong **≤ 90 giây** không cần động vào máy con |
| 2 | Chạy trên Windows, Linux, Android | Một gói cài cho mỗi nền tảng, test tự động trên cả ba |
| 3 | Không làm web chậm đến mức khó chịu | Trang thường chậm thêm **< 1 giây**; YouTube **< 2 giây** (xem §8) |
| 4 | Hai cách lọc: chỉ cho phép danh sách, hoặc chặn danh mục xấu | Phụ huynh đổi bằng **một ô** trong Sheet (`mode`) |
| 5 | Chụp màn hình, xem lịch sử từ xa | Máy đang mở: **< 3 giây**; máy tắt: tự thực hiện khi máy mở lại |
| 6 | Miễn phí cho gia đình, chi phí vận hành ≈ 0 | Cloudflare gói miễn phí + GitHub |
| 7 | Server không lưu dữ liệu của con | Relay chỉ chuyển gói đã mã hoá đầu-cuối, xoá ngay sau khi giao |

Nguyên tắc thiết kế không đổi so với bản đầu: *fail closed* (chưa tải được danh sách thì chặn hết), minh
bạch với con (con được báo mỗi lần chụp màn hình, không có chế độ ẩn), tài khoản quản trị không bị lọc.

## 2. Người dùng

- **Phụ huynh**: không rành kỹ thuật, dùng điện thoại, muốn sửa danh sách "như sửa một bảng tính".
- **Con** (6–15 tuổi): dùng tài khoản thường (không phải quản trị) trên PC, điện thoại Android.
- **Người cài đặt** (phụ huynh hoặc người giúp): cài một lần bằng file .exe / .deb / .apk.

## 3. Kiến trúc

```
Phụ huynh                     GitHub (tĩnh, công khai)             Máy con
┌──────────────────┐          ┌──────────────────────────┐        ┌────────────────────────┐
│ Google Sheet     │◄─ sửa ───│                          │        │ Windows: proxy + agent │
│ (nguồn cài đặt)  │──đọc 60s─┼──────────────────────────┼───────►│ Linux:   proxy + agent │
│ Web app GreenGate │          │ Danh mục chặn (daily)    │───────►│ Android: app (VPN DNS) │
│ (PWA, khoá riêng │          │ Web app, bộ cài          │        │                        │
│  trong trình     │          └──────────────────────────┘        │ khoá riêng của máy     │
│  duyệt)          │   lệnh/kết quả đã mã hoá                     │                        │
└────────┬─────────┘          ┌──────────────────────────┐        └───────────▲────────────┘
         └───────────────────►│ Relay (Cloudflare Worker)│◄───────────────────┘
                              │ chỉ chuyển gói mã hoá    │  WebSocket / hàng đợi có hạn
                              └──────────────────────────┘
```

| Thành phần | Thư mục | Công nghệ | Trạng thái 01-11 |
|---|---|---|---|
| Proxy lọc (Windows, Linux) | `proxy/` | mitmproxy 12 + addon Python | Có, mở rộng chế độ mới |
| Bộ cài Windows | `setup/`, `proxy/install.ps1` | PyInstaller → `GreenGate-Setup.exe` | Có, thêm agent + relay |
| Gói Linux | `linux/` | systemd + nftables + .deb | Mới |
| Agent (chụp màn hình, lịch sử, chặn app) | `agent/` | Python → `GreenGate-Agent.exe` | Mới |
| Relay | `server/` | Cloudflare Worker + Durable Object | Mới, chưa deploy |
| Web app phụ huynh | `parent-app/` | PWA tĩnh, tweetnacl | Mới |
| App Android | `android/` | Kotlin, VpnService, AccessibilityService | Mới (APK) |
| Danh mục chặn | `blocklists/` + release `lists` | GitHub Actions hàng ngày | Mới |
| Đặc tả kỹ thuật | `docs/SPEC.md` | | Mới |

## 4. Google Sheet: giao diện quản lý của phụ huynh

Một bảng tính, chia sẻ "bất kỳ ai có liên kết: Người xem". Máy con đọc theo **tên tab**, mỗi 60 giây.

| Tab | Cột | Ý nghĩa |
|---|---|---|
| `websites` | A trang, B ghi chú, C phút/ngày, **D giờ** | Trang được phép (chế độ whitelist) hoặc trang có giới hạn thời gian (cả hai chế độ). Dòng `*` = tổng thời gian vào mạng mỗi ngày. |
| `youtube` | A kênh | Kênh YouTube được phép (`@handle`, id hoặc link). |
| `blocked` *(mới)* | A trang | Luôn chặn, kể cả đường dẫn trong trang được phép (`wikipedia.org/wiki/Sex`). |
| `apps` *(mới)* | A tên gói / .exe, B `chặn` hoặc số phút, C giờ | Chặn hoặc giới hạn ứng dụng: `roblox.exe`, `com.google.android.youtube`. |
| `settings` *(mới)* | A khoá, B giá trị | Các tuỳ chọn dưới đây. Thiếu tab = cách chạy như cũ. |

### 4.1 Tab `settings` (phụ huynh chỉ cần nhớ bảng này)

| Khoá | Giá trị | Mặc định | Ý nghĩa |
|---|---|---|---|
| `mode` / `chế độ` | `whitelist` (chỉ cho phép) · `blacklist` (chặn danh sách) | whitelist | Cách lọc chính |
| `categories` / `danh mục` | `adult, gambling, drugs, weapons, violence, malware, bypass, dating, social, games, piracy, ads` | 7 danh mục đầu (khi blacklist) | Danh mục chặn, cập nhật hàng ngày từ nguồn công khai |
| `keywords` / `từ khoá` | `+default, roblox, ...` | `+default` | Từ khoá chặn trong tên miền, đường dẫn và **ô tìm kiếm** (Google, YouTube, Bing…) |
| `safesearch` | `on` / `off` | on | Ép SafeSearch Google/Bing/DuckDuckGo, YouTube Restricted Mode |
| `youtube` | `channels` · `restricted` · `block` · `any` | channels nếu có kênh, không thì restricted | Cách xử lý YouTube |
| `shorts` | `block` / `allow` | block | YouTube Shorts |
| `schedule` / `giờ` | `07:00-21:00` hoặc `17:00-20:00 T2-T6; 08:00-22:00 T7,CN` | luôn | Giờ được vào mạng |
| `refreshSeconds` | 30–3600 | 60 | Tần suất máy con đọc Sheet |
| `screenshotEvery` / `chụp mỗi` | phút, 0 = tắt | **15** | Chụp màn hình theo lịch, gửi vào Google Drive của bố mẹ (§4.4) |
| `screenshotHours` / `giờ chụp` | khung giờ | cả ngày | Chỉ chụp trong khung giờ này |
| `uploadUrl` / `drive` | URL Apps Script | | Nơi nhận ảnh (cài một lần theo `drive/README.md`) |
| `driveFolder` / `thư mục drive` | link Drive | | Nút "Mở thư mục Drive" trong app phụ huynh |
| `retentionDays` | ngày | 30 | Thời gian giữ lịch sử và ảnh |
| `blockPage` | văn bản | | Lời nhắn trên trang chặn |
| `deepInspect` / `kiểm tra sâu` | `on` / `off` | on | `off`: site đã liệt kê đi thẳng không giải mã (nhanh hơn, chỉ áp dụng luật theo tên miền; YouTube, máy tìm kiếm và site hết giờ vẫn được giải mã) |

Sai chính tả giá trị → ghi vào log, giữ mặc định, **không bao giờ** mở toang bộ lọc.

### 4.2 Hai chế độ

| | Whitelist (chỉ cho phép) | Blacklist (chặn danh sách) |
|---|---|---|
| Vào được | Chỉ `websites` (+ tài nguyên trang đó cần, + YouTube theo kênh) | Mọi trang trừ `blocked`, danh mục, từ khoá |
| Hợp với | Trẻ nhỏ, học online, PC học tập | Trẻ lớn, cần Internet rộng |
| Chặn thêm | `blocked`, từ khoá, danh mục (nếu khai báo) | — |
| Rủi ro | Trang học bị thiếu tài nguyên → thêm vào Sheet | Trang xấu mới chưa có trong danh mục → từ khoá bắt một phần |

Danh mục chặn ghép từ ba nguồn mở (Blocklist Project, HaGeZi, UT1 Toulouse), biên dịch mỗi ngày
thành tệp 8 byte/tên miền: `adult` 960 000, `gambling` 478 000, `malware` 375 000, `bypass` (VPN,
proxy, DNS riêng) 149 000, `drugs` 19 000 tên miền. Danh mục `weapons` (35) và `violence` (352) từ
nguồn miễn phí rất mỏng; bộ từ khoá bù một phần. Chưa có nguồn miễn phí tốt cho **rượu bia**: phụ
huynh thêm từ khoá (`rượu, bia, vodka…`) nếu cần, chấp nhận dương tính giả.

### 4.4 Ảnh màn hình theo lịch lên Google Drive của bố mẹ (mới 01-11, yêu cầu bổ sung)

- Máy con tự chụp mỗi `screenshotEvery` phút (mặc định 15) trong `screenshotHours`, chỉ khi có người
  đăng nhập và màn hình không khoá, và gửi vào thư mục Drive của bố mẹ qua một **Apps Script gắn với
  Sheet** (`drive/GreenGateUploader.gs`). Không cần Google Cloud, không có mật khẩu Google trên máy con;
  máy con chỉ *ghi thêm* ảnh, không đọc/xoá được Drive. Ảnh xếp `<thư mục>/<máy>/<ngày>/<giờ>.jpg`,
  tự dọn sau `retentionDays`.
- **Minh bạch**: mỗi lần chụp hiện thông báo tự tắt, ghi rõ chụp theo lịch hay bố mẹ bấm.
- **Đồng ý hai bên**: khi cài, bố mẹ và con xác nhận riêng (hai ô trong bộ cài / `greengate consent`);
  thiếu một bên thì máy không tự chụp theo lịch (vẫn ghi nhật ký).
- Bố mẹ có hai cách xem: lịch sử trong Drive (kể cả khi máy con đã tắt) hoặc "Chụp màn hình" trực tiếp
  khi máy con online (ảnh này cũng được lưu vào Drive với đuôi `-bo-me`).
- Ngoài danh sách (lý do): ảnh để dạng thường trong Drive của bố mẹ để xem được bằng app Drive; URL
  Apps Script nằm trong Sheet (ai có link Sheet có thể gửi ảnh rác – script chỉ nhận JPEG ≤ 1,5 MB,
  30 ảnh/giờ/máy; có thể chuyển URL vào cấu hình máy con bằng `greengate drive --set`).

### 4.3 Vì sao vẫn là Google Sheet (và không phải một trang quản trị riêng)

- Phụ huynh đã biết dùng, sửa được trên điện thoại, có lịch sử phiên bản, chia sẻ cho ông bà/giáo viên.
- Máy con đọc trực tiếp từ Google: không có server trung gian, GreenGate sập vẫn lọc bình thường.
- Web app phụ huynh **hiển thị** cài đặt hiện tại (đọc CSV công khai) và có nút "Cập nhật ngay" đẩy lệnh
  `refresh` qua relay để máy con đọc lại Sheet tức thì. Sửa trực tiếp trong app cần Google OAuth client
  (chủ dự án tạo trong Google Cloud Console một lần) — mục 10.

## 5. Yêu cầu theo nền tảng

| Tính năng | Windows | Linux | Android |
|---|---|---|---|
| Lọc web whitelist/blacklist | Proxy giải mã TLS | Proxy, trong suốt (nftables theo uid) | VPN lọc DNS (theo tên miền) |
| Danh mục + từ khoá trong tên miền | ✔ | ✔ | ✔ |
| Từ khoá trong đường dẫn / ô tìm kiếm | ✔ | ✔ | ✘ (chỉ tên miền) |
| Lọc YouTube theo kênh | ✔ | ✔ | ✘ → chặn app YouTube, youtube.com chặn trừ khi liệt kê; đề xuất YouTube Kids |
| SafeSearch / Restricted Mode | ✔ (tham số + header) | ✔ | ✔ (DNS CNAME forcesafesearch / restrict.youtube.com) |
| Giới hạn phút/ngày, khung giờ | ✔ | ✔ | khung giờ ✔; phút theo app |
| Chặn ứng dụng (tab `apps`) | Agent tắt .exe | Agent tắt tiến trình | AccessibilityService đưa về màn hình chính |
| Chụp màn hình theo yêu cầu | Agent (mss) | Agent (X11) | AccessibilityService (Android 11+) |
| Chụp theo lịch → Drive, thông báo cho con, đồng ý hai bên | Agent + Apps Script | Agent + Apps Script | App + Apps Script |
| Nhận tín hiệu "Sheet đổi" từ relay | ✔ | ✔ | ✔ |
| Lịch sử theo yêu cầu | Nhật ký proxy | Nhật ký proxy | Nhật ký DNS |
| Chống gỡ | Policy HKLM, thư mục admin, con là tài khoản thường | Con không có sudo, service root | Device Admin + chặn vào Cài đặt của app; Device Owner (tuỳ chọn) |
| Gói cài | `GreenGate-Setup.exe` (kèm agent, mitmdump) | `greengate_<ver>_all.deb` + `greengate-setup` | `GreenGate-<ver>.apk` |

## 6. Relay và mã hoá (tóm tắt, chi tiết trong SPEC §5)

- Mỗi bên một cặp khoá X25519; gói tin `nacl.box` (XSalsa20-Poly1305). Khoá phụ huynh sinh trong trình
  duyệt, có mã khôi phục; khoá máy con sinh khi ghép đôi.
- Relay lưu: id máy, khoá công khai, token, lần cuối online, lệnh đang chờ (TTL) và kết quả cho tới khi
  phụ huynh tải (tối đa 600 s). Không có ảnh, lịch sử hay cài đặt ở dạng đọc được.
- Máy tắt: lệnh xếp hàng (chụp màn hình 10 phút, lịch sử/refresh 24 giờ); máy mở lại là nhận ngay.
- Chi phí: Cloudflare Workers + Durable Objects gói miễn phí; WebSocket hibernation nên máy con nối
  liên tục không tốn phí.

## 7. Hiệu lực của thay đổi trên Sheet ("bố mẹ thêm web → con vào được")

| Chặng | Thời gian | Ghi chú |
|---|---|---|
| Google xuất CSV sau khi sửa ô | **1,3–1,6 s** (đo 3 lần trên Sheet thật, 01-11; endpoint gviz không cache) | Đo được khi có quyền ghi Sheet, xem §8 |
| Máy con đọc lại Sheet | mặc định mỗi **60 s** (cũ: 15 phút) | `refreshSeconds` 30–3600; tự lùi khi Google trả 429 |
| Áp dụng | < 1 s | log `lists loaded` chỉ khi có thay đổi |
| **Tổng, không làm gì thêm** | **≤ ~65 s** (trung bình ~35 s) | |
| Nhấn "Cập nhật ngay" trong web app / `greengate update` | **1–3 s** | qua relay (lệnh `refresh`) hoặc trên máy |
| **Tự động "đẩy"**: Apps Script của Sheet bắt sự kiện sửa → gọi relay → relay nhắc máy con đọc lại | **~1–5 s**, không ai phải bấm | Cần relay đã deploy; cài một lần bằng hàm `setupTrigger` (SPEC §5.x) |

Cách nhanh nhất mà không cần server lưu dữ liệu: **đẩy** – Apps Script `onChange`/`onEdit` của Sheet gọi
`POST /v1/sheet/<id>/changed` trên relay; relay chỉ biết "Sheet này vừa đổi" và gửi một khung
`{"t":"hint","kind":"refresh"}` không mã hoá qua WebSocket đang mở tới từng máy con đang theo Sheet đó;
máy con đọc lại Sheet ngay. Không có nội dung Sheet nào đi qua relay. Polling 60 s giữ làm dự phòng
(máy đang offline lúc sửa sẽ bắt kịp khi nối lại, vì relay không xếp hàng tín hiệu này – không cần,
máy nối lại là đọc Sheet).

## 8. Kết quả đo (01-11-2026)

Xem `docs/REPORT.md` (được tạo cùng phiên) — tóm tắt:

- **Độ trễ Linux (Chrome thật, 10 lần, trung vị)**: trang thường +0,1 … +1 s; YouTube trang chủ +1,3 s;
  xem video tới khi chạy +0,7 s (sau khi cho CDN video đi thẳng không giải mã).
- **Windows**: đo bằng CI (curl như tài khoản con) — bảng trong REPORT.
- **Android (emulator API 33)**: bảng trong `docs/android-report.md`.
- **Chụp màn hình qua relay (cục bộ)**: máy mở trung vị 153 ms, p95 202 ms; lịch sử 45 ms; máy tắt
  N giây → kết quả về sau N + 0,3…0,8 s. Chưa gồm độ trễ Internet thật (relay chưa deploy).

## 9. Ngoài phạm vi v2.0 (có kế hoạch)

1. iPhone/iPad: hướng dẫn Screen Time; app FamilyControls sau.
2. Chụp định kỳ tải lên Google Drive của phụ huynh (hiện lưu mã hoá trên máy con, lấy qua relay).
3. Lọc kênh YouTube trên Android (cần tun2socks + MITM trong app, 4–6 tuần).
4. Lệnh `pause/resume` từ xa cần agent chạy với quyền hệ thống và chữ ký Ed25519 của phụ huynh (hiện
   agent chạy trong phiên của con nên con có thể đọc khoá máy).
5. Web Push cho phụ huynh, FCM đánh thức Android khi màn hình tắt lâu.
6. Bản trường học (nhiều quản lý, báo cáo theo lớp).

## 10. Việc cần chủ dự án làm (không tự động được)

| Việc | Lệnh / nơi làm | Vì sao cần bạn |
|---|---|---|
| Deploy relay | `cd server && npx wrangler login && npx wrangler deploy` | Đăng nhập Cloudflare qua trình duyệt |
| Cài Apps Script nhận ảnh + báo relay (3 phút) | `drive/README.md`: dán script vào Sheet, Triển khai web app, dán URL vào `uploadUrl`, chạy `setupTrigger` | Phải làm bằng tài khoản Google chủ Sheet |
| Tên miền | Thêm zone vào Cloudflare, `routes` trong `server/wrangler.toml` | Mua/trỏ tên miền |
| Google OAuth client (sửa Sheet trong app) | Google Cloud Console → OAuth client "Web application", scope `spreadsheets` | Tạo credential cần tài khoản chủ |
| Đo độ trễ Sheet thật | Chia sẻ Sheet thử (quyền Sửa) cho một service account, hoặc sửa một ô theo hiệu lệnh | Token gcloud hiện không có quyền Sheets; tạo service account bị chặn bởi chính sách phiên |
| Ký APK/EXE | Keystore Android đã tạo trong `android/keystore/`; code-signing Windows (tuỳ chọn, ~70 USD/năm) | Giảm cảnh báo Defender/Play Protect |
| Google Play (sau) | Khai báo AccessibilityService, Device Admin | 25 USD, tài khoản nhà phát triển |

## 11. Rủi ro

| Rủi ro | Mức | Giảm thiểu |
|---|---|---|
| YouTube đổi cấu trúc JSON | Cao | `test/proxy.js` chạy định kỳ; chế độ `restricted` làm dự phòng |
| Defender/Play Protect cảnh báo bộ cài không ký | Trung bình | Zip có mật khẩu (đã có); ký code sau |
| Chrome Android bỏ tin chứng chỉ người dùng | Thấp | Android dùng DNS, không phụ thuộc |
| Con lách: DoH/QUIC/VPN/đổi DNS | Trung bình | Danh mục `bypass`, chặn QUIC, nftables chặn cổng lạ (Linux), policy DoH off |
| Danh mục weapons/violence mỏng | Trung bình | Từ khoá; cân nhắc nguồn trả phí sau |
| Phụ huynh mất khoá | Trung bình | Mã khôi phục, ghép đôi lại |

## 12. Tiêu chí hoàn thành "PRD ready" cho v2.0

- [x] Đổi tên toàn bộ sang GreenGate
- [x] Chế độ whitelist/blacklist, danh mục, từ khoá, SafeSearch, khung giờ – test đơn vị + tích hợp
- [x] Sheet đọc lại mỗi 60 s, có nút cập nhật ngay
- [x] Linux: .deb, systemd, nftables, test Docker + CI
- [x] Relay + web app + agent, đo end-to-end cục bộ
- [x] Android APK (lọc DNS, chặn app, chụp màn hình, relay) + đo trên emulator
- [ ] Relay deploy thật và đo lại qua Internet (chờ đăng nhập Cloudflare)
- [ ] Đo độ trễ Google Sheet thật (chờ quyền ghi Sheet)
- [ ] Test trên máy Android thật (3 phiên bản) và PC Windows 10 thật
