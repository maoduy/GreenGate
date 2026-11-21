# GreenGate Android: báo cáo xây dựng và kiểm thử

Ngày: 2026-11-01. Mã nguồn: `android/`. APK: `android/dist/GreenGate-0.2.0.apk` (0.1.0 vẫn còn cạnh đó) (ký bằng
`android/keystore/greengate-release.jks`, mật khẩu trong `android/keystore/README.md`, **phải giữ
file này**, mất là mọi máy phải gỡ cài lại).

## 1. Tóm tắt

| Hạng mục | Kết quả |
|---|---|
| Lọc web theo Sheet (whitelist / blacklist, tab `blocked`, danh mục, từ khoá, khung giờ) | Hoạt động, kiểm chứng trên emulator Android 13 |
| SafeSearch (Google, Bing, DuckDuckGo) và YouTube Restricted Mode | Hoạt động (trả về địa chỉ của forcesafesearch.google.com / restrict.youtube.com) |
| Đọc lại Sheet | Mỗi `refreshSeconds` (mặc định 60 s), đổi được trong tab `settings` |
| Chặn ứng dụng (tab `apps`, app YouTube) | Hoạt động qua dịch vụ Trợ năng |
| Chụp màn hình, lịch sử, pause/resume, status qua relay | Hoạt động, mã hoá đầu-cuối nacl.box |
| Chống gỡ | Device Admin + chặn vào trang Cài đặt của GreenGate |
| **Lọc kênh YouTube** | **Không làm được trên Android** (xem §5) |

## 2. Kiến trúc trên Android (khác PC)

Trên Windows/Linux, GreenGate là proxy giải mã TLS nên nhìn thấy đường dẫn và nội dung YouTube.
Trên Android không có quyền hệ thống để làm thế. App dùng **VPN chỉ bắt DNS**: VPN chỉ định tuyến
một địa chỉ giả (`10.111.222.3`) và đặt nó làm máy chủ DNS, nên mọi truy vấn tên miền của mọi
ứng dụng đi qua app, còn dữ liệu web đi thẳng ra mạng như bình thường.

- Tên miền bị chặn trả về `0.0.0.0` → trình duyệt báo lỗi ngay, không chờ.
- Tên miền được phép chuyển tiếp lên 8.8.8.8 / 1.1.1.1 và trả về nguyên bản.
- SafeSearch: `www.google.*` trả về địa chỉ của `forcesafesearch.google.com`, `www.bing.com` →
  `strict.bing.com`, `duckduckgo.com` → `safe.duckduckgo.com`, YouTube → `restrict.youtube.com`
  khi `youtube` ≠ `channels`. Bản ghi HTTPS/ECH bị trả rỗng để trình duyệt không lách.
- Chế độ whitelist: chặn hết (fail closed) cho tới khi đọc được Sheet lần đầu; sau đó giữ danh
  sách cũ nếu đọc lỗi. Danh sách cuối cùng được lưu, khởi động lại máy không cần mạng vẫn lọc.
- Danh mục: tải `<category>.txt.gz` mỗi ngày, lưu dạng 8 byte băm/tên miền, tra bằng tìm kiếm
  nhị phân (adult ~300k tên miền ≈ 2,4 MB RAM). Chưa có bản phát hành `lists` thì bỏ qua (404),
  không làm hỏng việc lọc.
- Lịch sử: SQLite (phút, tên miền, bị chặn, số lần), xuất CSV theo tháng cho lệnh `history`.

Hệ quả của thiết kế DNS: không lọc được **đường dẫn** (`domain/path` trong Sheet chỉ lấy phần
tên miền), không lọc được **kênh YouTube**, từ khoá chỉ áp dụng cho **tên miền** (không cho câu
tìm kiếm). Đổi lại: không tốn pin trên đường dữ liệu, không làm chậm tải trang (§4).

## 3. Những gì đã kiểm chứng trên emulator (Pixel API 33, Android 13, x86_64)

Mọi lệnh chạy bằng `adb`, không bấm tay. Sheet được giả lập bằng server CSV cục bộ
(`tools/sheet_server.py`, cùng định dạng gviz) để có thể sửa và đo lan truyền; relay dùng
`tools/mock_relay.py` (cùng API với Worker thật) **và** relay thật của repo (`server/`, chạy
`wrangler dev` trên cổng 8787) để đối chiếu, cả hai đều chạy đủ bộ lệnh.

| Kiểm tra | Kết quả |
|---|---|
| `www.google.com` (trong danh sách, safesearch=on) | trả về `216.239.38.120` = forcesafesearch.google.com |
| `www.wikipedia.org`, `www.youtube.com` (trong danh sách) | trả về địa chỉ thật |
| `example.org`, `www.bing.com` (không trong danh sách, chế độ whitelist) | `0.0.0.0`, Chrome báo "refused to connect" ngay |
| `badsite.test` (tab `blocked`) | `0.0.0.0` |
| `pornhub.com`, `gambling-sample.test` (danh mục adult / gambling) | `0.0.0.0` |
| `sex-videos.example` (từ khoá mặc định) | `0.0.0.0` |
| Mở app YouTube | bị đưa về màn hình chính trong < 1 s, log `blocked com.google.android.youtube` |
| Khởi động lại máy | VPN tự bật lại không cần hỏi (BootReceiver), relay tự kết nối lại |
| Test đơn vị JVM (`./gradlew testReleaseUnitTest`) | 24 vector khung giờ dùng chung với bản Python + test parser Sheet: đạt |

## 4. Số đo

### 4.1 Tải trang: tắt VPN và bật VPN xen kẽ (WebView, cùng trạng thái máy, 5 cặp mỗi trang)

| Trang | Tắt VPN, trung vị (ms) | Bật VPN, trung vị (ms) | Chênh |
|---|---|---|---|
| google.com | 901 | 872 | −29 |
| wikipedia.org | 511 | 786 | +275 |
| ted.com | 2889 | 2637 | −252 |
| youtube.com (trang chủ) | 1485 | 725 | −760 (một lần tắt VPN mất 43 s, nhiễu mạng) |
| bbc.com | 455 | 435 | −20 |

Độ lệch giữa các lần chạy cùng điều kiện là ±300 ms đến ±1 s (emulator dùng GPU phần mềm và
mạng NAT), nên kết luận: **không đo được độ trễ do GreenGate gây ra**, nó nhỏ hơn nhiễu. Về
nguyên lý chỉ có truy vấn DNS đầu tiên của mỗi tên miền đi qua app; dữ liệu trang và video
YouTube đi thẳng, không bị chạm vào.

### 4.2 DNS

| Số đo | Giá trị |
|---|---|
| Thời gian app ra quyết định (whitelist + tab blocked + 7 danh mục + 43 từ khoá) | trung bình 0,4–1,4 ms/truy vấn |
| Vòng đi-về lên 8.8.8.8 từ emulator (phần không do app quyết định) | trung bình 170–186 ms |
| Tên miền bị chặn | trả lời ngay, không ra mạng (0 ms) |
| Resolver của emulator khi không có VPN (có cache của máy host) | trung vị 22–100 ms |

Trên điện thoại thật dùng Wi-Fi gia đình, 8.8.8.8/1.1.1.1 thường 10–40 ms; app hiện chưa có
cache DNS riêng (Android tự cache theo TTL), có thể thêm sau nếu cần.

### 4.3 Thay đổi trên Sheet đến máy con

| Số đo | Giá trị |
|---|---|
| `refreshSeconds` dùng trong test | 30 s |
| Thêm `example.org` vào `websites` → máy con phân giải được | **12,5 s** (một lần đo; kỳ vọng trung bình = refreshSeconds/2 + thời gian đọc Sheet) |
| Thời gian đọc đủ 5 tab từ Google (gviz, từ emulator) | 1,3–5,0 s |

Với mặc định `refreshSeconds = 60` trên Sheet thật: trung bình ~35 s, tối đa ~65 s, cộng độ trễ
Google cập nhật gviz (thường vài giây). Cách nhanh nhất: phụ huynh bấm "Áp dụng ngay" trên web
app → lệnh `refresh` qua relay → máy con đọc lại Sheet trong ~1–5 s (đã test: lệnh `refresh`
trả kết quả sau 15–60 ms, việc đọc Sheet xong sau 1–5 s).

### 4.4 Lệnh qua relay (máy con đã ghép đôi, mã hoá đầu-cuối nacl.box)

Thời gian tính từ lúc phụ huynh gửi đến lúc nhận được kết quả đã giải mã (relay và máy chủ
test cùng một máy, nên đây là chi phí của thiết bị + giao thức, chưa gồm độ trễ Internet thật,
thường thêm 50–300 ms mỗi chiều).

| Lệnh | Mock relay | Relay thật (`server/`, wrangler dev) |
|---|---|---|
| `status` | 58 ms | 298 ms (lần đầu, Durable Object khởi tạo) |
| `screenshot`, app GreenGate ở trước | 157 ms (61 KB JPEG) | 103 ms (37 KB) |
| `screenshot`, Chrome ở trước | 156 ms (28 KB) | 76 ms (53 KB) |
| `screenshot`, **màn hình tắt** | 58 ms, trả về ảnh đen 5 KB (chụp được, nhưng màn hình tắt thì không có gì để xem) | 55 ms |
| `history` (CSV nén, 138–169 dòng) | 56 ms | 37 ms |
| `pause 1` / `resume` / `refresh` | 32–562 ms | 32–70 ms |

Máy **đang tắt** (khởi động lại emulator, gửi lệnh `history` khi máy chưa lên):

| Mốc | Thời gian |
|---|---|
| Gửi lệnh (máy đang tắt) | 0 s, relay trả `delivered=false`, xếp hàng (TTL 24 h với `history`, 10 phút với `screenshot`) |
| Android báo boot xong | +16 s |
| GreenGate tự khởi động, nối lại relay, nhận lệnh trong hàng | +38 s (22 s sau khi boot xong) |
| Phụ huynh nhận kết quả | **+40 s** (24 s sau khi boot xong) |

Nghĩa là: máy tắt thì không có cách nào lấy ảnh (và cũng không có gì để chụp); lệnh chờ trên
relay và được trả lời trong vòng ~25 s sau khi máy bật, không cần ai mở app.

### 4.5 Pin

Không đo được số có ý nghĩa trên emulator (`dumpsys batterystats`: tiến trình GreenGate chiếm
0,6 "đơn vị" so với 81 của hệ thống sau ~4 giờ, nghĩa là không đáng kể). Thiết kế: không có
luồng nào chạy liên tục, chỉ thức khi có truy vấn DNS; WebSocket relay giữ bằng ping 30 s của
OkHttp. Cần đo lại trên máy thật 24 giờ (mục tiêu < 5 %/ngày như PLAN).

## 5. Những gì KHÔNG làm được trên Android, và nên đặt gì trong Sheet

**Lọc kênh YouTube là không thể** với cách này: ứng dụng YouTube và youtube.com trong Chrome
đều dùng TLS; để biết video thuộc kênh nào phải giải mã TLS như proxy trên PC, mà Android
không cho một ứng dụng thường làm vậy với app khác (ứng dụng YouTube ghim chứng chỉ, và proxy
toàn cục chỉ đặt được khi là Device Owner). Vì vậy trên Android:

- `youtube = channels` (mặc định khi tab `youtube` có kênh): ứng dụng YouTube, YouTube Kids,
  YouTube Music **bị chặn**; `youtube.com` trong trình duyệt chỉ mở được nếu nằm trong tab
  `websites` (như Sheet hiện tại), và khi mở thì **không lọc theo kênh**.
- Khuyến nghị cho phụ huynh có con dùng Android: bỏ `youtube.com` khỏi tab `websites` (hoặc
  đặt `youtube = block`) và cho con xem YouTube Kids ở chế độ "chỉ nội dung được phê duyệt"
  (chế độ đó là của Google, cài trong app YouTube Kids, không qua GreenGate; để làm được thì
  thêm `com.google.android.apps.youtube.kids` sẽ cần bỏ khỏi danh sách chặn, hiện app chặn
  cả YouTube Kids khi `youtube = channels`, có thể đổi thành tuỳ chọn trong bản sau).
- `youtube = restricted`: youtube.com được trả về địa chỉ `restrict.youtube.com`, Google bật
  Restricted Mode (ẩn nội dung người lớn, tắt bình luận), app YouTube vẫn bị chặn.
- Các hạn chế khác của lọc DNS: không chặn được **đường dẫn** (`example.com/kids` chỉ còn là
  `example.com`), từ khoá không bắt được **câu tìm kiếm** (SafeSearch bù một phần), và trang
  bị chặn hiện ra lỗi "refused to connect" của trình duyệt chứ không phải trang chặn có lời giải
  thích như trên PC.
- Con có thể bỏ lọc bằng cách tắt VPN trong Cài đặt → app đã chắn trang VPN/Device admin/App
  info của chính nó bằng Trợ năng (đưa về màn hình chính), nhưng chưa thử mọi đường (ví dụ
  khởi động vào chế độ an toàn, hoặc Cài đặt của một số hãng dùng tên lớp khác). Device Owner
  (cài qua QR sau khi khôi phục cài đặt gốc) mới chặn chắc; chưa làm trong bản này.
- Khi cập nhật app (`adb install -r`), Android tự tắt dịch vụ Trợ năng; phụ huynh phải bật
  lại (đây là hành vi của Android, không tránh được ngoài Device Owner).

## 6. Cài đặt trên máy thật

1. Chép `android/dist/GreenGate-0.1.0.apk` vào máy, mở và cho phép "cài ứng dụng không rõ nguồn".
2. Mở GreenGate, dán link Google Sheet, bấm **Kiểm tra** (phải thấy số dòng của `websites`).
3. (Tuỳ chọn) nhập địa chỉ relay, bấm **Ghép đôi với phụ huynh**, nhập mã 6 số trên web app.
4. Bấm **Bật bảo vệ** → đồng ý VPN. Bấm **Trợ năng** → bật "GreenGate: chặn ứng dụng, chụp màn
   hình". Bấm **Quản trị** → Kích hoạt. Màn hình chính của app hiện trạng thái cả ba quyền.
5. Thông báo thường trực "GreenGate đang bảo vệ máy này" là cố ý (minh bạch với con).

Lệnh adb đã dùng khi test (cũng dùng được để cài hàng loạt): xem `android/README.md`.

## 7. Việc còn lại trước khi phát hành thật

| Việc | Ghi chú |
|---|---|
| Relay thật có tên miền (`relay.greengate.vn` đang là chỗ trống trong app, sửa được trong màn hình cài đặt) | app đã chạy đúng với Worker trong `server/` |
| Web app phụ huynh | app đã có đủ lệnh; test bằng `tools/parent_cli.py` |
| Bỏ `ProbeActivity` (chỉ để đo) khỏi bản phát hành hoặc chỉ bật ở bản debug | 10 phút |
| Device Owner qua QR khi thiết lập máy mới | chống gỡ tuyệt đối; cần hướng dẫn khôi phục cài đặt gốc |
| Google Play: khai báo AccessibilityService cho mục đích quản lý của phụ huynh, chính sách quyền riêng tư, chọn lại `targetSdk 35` khi Google yêu cầu | hiện phát hành APK ngoài Play |
| Giới hạn phút/ngày cho ứng dụng (tab `apps` cột B) và cho web (cột C của `websites`) | chưa làm trên Android; có UsageStatsManager cho app, còn web ở mức DNS chỉ đếm được "có truy cập", không đếm được phút chính xác |
| Chụp tự động mỗi giờ (`screenshotEvery`) và tải lên Drive | chưa làm; giá trị đã được đọc và báo trong `status` |
| Trang chặn có lời giải thích thay cho lỗi của trình duyệt | cần một HTTP server cục bộ trên cổng 80 cho tên miền bị chặn; HTTPS thì không làm được nếu không có chứng chỉ |
| Cache DNS trong app, đo pin 24 giờ trên máy thật | tối ưu |
| Chuyển `keystore/` ra khỏi repo công khai | mật khẩu đang nằm trong `keystore/README.md` và `keystore.properties` |

Tệp bằng chứng: `docs/img/android/screenshot-chrome-blocked.png` (bing.com bị chặn),
`docs/img/android/screenshot-chrome-allowed.png` (wikipedia.org), `docs/img/android/screenshot-via-relay.jpg`
(ảnh phụ huynh nhận qua relay).

## 8. Ảnh định kỳ lên Google Drive (bản 0.2.0, SPEC §8)

Cách làm: không có tài khoản Google nào trên máy con. Máy con POST ảnh (JSON, base64 JPEG) lên
`uploadUrl` trong tab `settings` – là Apps Script mà bố mẹ triển khai một lần từ chính Google
Sheet; script chạy dưới tài khoản bố mẹ và chỉ **thêm** file vào thư mục Drive đã chọn. Máy con
không đọc, không liệt kê, không xoá được gì trên Drive.

Điều kiện chụp theo lịch (mỗi `screenshotEvery` phút, mặc định 15; chỉ trong `screenshotHours`
nếu có): **cả bố mẹ và con đã tích đồng ý** trong app (mục 4 của màn hình cài đặt, lưu kèm thời
điểm), màn hình đang **mở và không khoá**, không trong lúc tạm dừng. Mỗi lần chụp – theo lịch hay
do bố mẹ bấm – có thông báo riêng tự tắt sau 8 giây: "GreenGate chụp màn hình theo lịch (mỗi N
phút)" hoặc "Bố mẹ vừa chụp màn hình". Ảnh bố mẹ chụp trực tiếp cũng được gửi một bản lên Drive
(`reason: parent`) để lịch sử trên Drive đầy đủ. Gửi lỗi (mất mạng, script lỗi) → ảnh xếp hàng
trong bộ nhớ riêng của app (tối đa 200), gửi lại ở chu kỳ sau.

Kiểm chứng trên emulator Pixel API 33 với `tools/mock_upload.py` (giả lập Apps Script, kể cả
chuyển hướng 302 của Google), Sheet cục bộ `screenshotEvery=1`, Chrome mở trang wikipedia:

| Kiểm tra | Kết quả |
|---|---|
| Chưa đủ đồng ý (0/2) | Không chụp; log `skip: no consent`; 0 ảnh tới endpoint sau 90 s |
| Đủ đồng ý, màn hình mở | Chụp theo lịch đúng 60 s một lần: 12:39:55, 12:40:55, 12:41:56 |
| Màn hình tắt (`KEYCODE_SLEEP`) | Không chụp; log `skip: screen off or locked`; số ảnh không tăng |
| Thông báo khi chụp | Có, kênh `greengate.shots`, text đúng theo lý do; **tự biến mất sau 8 s** (dumpsys: 0 bản ghi sau 10 s) |
| Bố mẹ chụp qua relay | Ảnh về app phụ huynh sau 157 ms (gửi→nhận), đồng thời `12-40-21-parent.jpg` lên Drive |
| Endpoint hỏng rồi phục hồi | 2 ảnh vào hàng đợi (`queued (2 waiting)`, lỗi ghi vào `drive.lastError`); endpoint trở lại → gửi hết ở chu kỳ kế tiếp sau 19 s, đúng tên file theo giờ chụp gốc (`12-44-05.jpg`, `12-44-17.jpg`), `queued: 0` |
| Tên file / thư mục | `<thư mục>/sdk_gphone64_x86_64/2026-11-01/12-39-43.jpg`, `...-parent.jpg` |

| Số đo | Giá trị (emulator) |
|---|---|
| Chụp + thu nhỏ 1280 px + JPEG q60 | 65 ms |
| Cỡ ảnh | 39–75 KB (màn hình 1080×2400 → 576×1280) |
| Gửi lên endpoint (POST + theo 302 + GET kết quả), phía máy con | 1,94–1,99 s (mạng emulator ~1 s mỗi lượt; server xử lý 5–34 ms) |
| Pin | không đo được có nghĩa trên emulator; một lần chụp + gửi ≈ 2 s CPU nhẹ, 15 phút/lần |

### Nhắc đọc lại Sheet qua relay (frame `hint`, SPEC §5 mở rộng)

Sau khi nối WebSocket, app gửi frame thường `{"t":"register","sheet":"<id>"}` (gửi lại khi đổi
Sheet). Relay gửi `{"t":"hint","kind":"refresh","ts":…}` khi Sheet đổi → app đọc lại Sheet ngay
(tối đa 1 lần/10 s; lệnh thứ hai cách 1 s bị bỏ qua, log `hint ignored (rate limit)`; sheet không
đăng ký → `notified: 0`). Đo với mock relay: hint đến máy và bắt đầu đọc Sheet **< 100 ms**; tổng
hint → `lists loaded` **5,3 s**, gần như toàn bộ là 5 lượt tải CSV qua mạng emulator (~1 s/tab);
trên máy thật với Google khoảng 1–2 s.

Chưa làm trong 0.2.0: `screenshotHours` được đọc và áp dụng nhưng chưa có test riêng trên emulator
(dùng chung bộ kiểm tra khung giờ 24 vector); bản sao mã hoá cục bộ của ảnh (trên PC) không có trên
Android – ảnh chỉ nằm trên Drive và trong hàng đợi tạm khi gửi lỗi.
