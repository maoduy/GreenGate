# Video và ảnh chụp các kịch bản kiểm thử

Ngày quay: 02-11-2026 (sáng). Mỗi kịch bản có một video `.mp4` (H.264, 15 fps, ≤ 1 MB) và các ảnh PNG
chụp đúng khoảnh khắc quyết định, cùng tên gốc. Thanh xanh ở đầu mỗi khung hình Linux ghi nền tảng,
kịch bản, bước đang làm, URL và giờ hệ thống; cột "Lúc" là mốc gần đúng trong video.

Môi trường:

| Nền | Thiết bị | Cách quay |
|---|---|---|
| Linux | Máy thật Ubuntu 24.04, Google Chrome (headless) đi qua một bản proxy GreenGate 2.0.0 chạy riêng trên cổng 1808x | Playwright `recordVideo` + `page.screenshot` |
| Android | Emulator Pixel API 33 (Android 13), Chrome, GreenGate 0.2.0 đọc **Sheet thật** của gia đình, ngôn ngữ máy đặt tiếng Việt | `adb shell screenrecord` + `screencap` |
| Windows | chưa có ở thư mục này (quay riêng trên máy ảo) | |

Quy tắc dữ liệu trong video: ô "Google Sheet điều khiển" của app Android được che đen trong mọi khung hình và ảnh
(id của Sheet không xuất hiện). Trên Linux, các kịch bản cần đổi quy tắc dùng **bản CSV cục bộ** chép từ Sheet thật
rồi sửa (ghi rõ "CSV cục bộ" trong tiêu đề); hai kịch bản ghi "Sheet thật" đọc thẳng Sheet của gia đình. Android chỉ
quay những gì quy tắc hiện có trên Sheet thật cho thấy (chưa có dòng `blocked`/`apps` nào có hiệu lực).

## Linux

| # | Video | Dài | Kịch bản | Lúc | Ảnh | Điều thấy được |
|---|---|---|---|---|---|---|
| 1 | `linux-1-whitelist.mp4` | 20 s | Chế độ whitelist (Sheet thật) | 00:07 | `linux-1-whitelist-ted-mo-duoc.png` | ted.com có trong tab `websites` → mở bình thường |
| | | | | 00:12 | `linux-1-whitelist-vnexpress-bi-chan.png` | vnexpress.net không có trong danh sách → trang chặn "không nằm trong danh sách được phép" |
| | | | | 00:18 | `linux-1-whitelist-wikipedia-bi-chan.png` | vi.wikipedia.org → trang chặn |
| 2 | `linux-2-blacklist.mp4` | 19 s | Chế độ blacklist (CSV cục bộ: `mode=blacklist`, tab `blocked` = tiktok.com, vnexpress.net) | 00:07 | `linux-2-blacklist-vnexpress-bi-chan.png` | vnexpress.net nằm trong `blocked` → "Trang này đã bị chặn" |
| | | | | 00:13 | `linux-2-blacklist-tiktok-bi-chan.png` | tiktok.com → trang chặn |
| | | | | 00:19 | `linux-2-blacklist-wikipedia-mo-duoc.png` | vi.wikipedia.org không bị liệt kê → mở bình thường |
| 3 | `linux-3-youtube.mp4` | 30 s | YouTube: kênh trong tab `youtube` chạy, kênh lạ bị chặn, Shorts tắt (Sheet thật; quay lúc 12:00 sau khi YouTube truy cập được trở lại) | 00:08 | `linux-3-youtube-ted-chay.png` | Video của kênh @TED (có trong tab `youtube`) phát bình thường |
| | | | | 00:16 | `linux-3-youtube-kenh-la-bi-chan.png` | Video của kênh @RickAstleyYT (không có trong tab) → trang chặn "Kênh YouTube này chưa được duyệt" |
| | | | | 00:24 | `linux-3-youtube-shorts-bi-chan.png` | URL `/shorts/...` → trang chặn "YouTube Shorts đã bị tắt" |
| 4 | `linux-4-het-gio.mp4` | 53 s | Hạn thời gian: ted.com = 1 phút/ngày (CSV cục bộ) | 00:07 | `linux-4-het-gio-ted-mo-duoc.png` | Phút đầu: ted.com mở được |
| | | | | 00:37 | `linux-4-het-gio-ted-het-gio.png` | Sang phút kế, tải lại → "Hết giờ cho ted.com hôm nay. Đã dùng 1/1 phút" |
| 5 | `linux-5-khung-gio.mp4` | 52 s | Khung giờ `schedule` = `00:00-HH:MM` kết thúc sau 1 phút (CSV cục bộ) | 00:07 | `linux-5-khung-gio-ted-trong-gio.png` | Trong giờ: ted.com mở được |
| | | | | 00:47 | `linux-5-khung-gio-ngoai-gio.png` | Hết giờ, tải lại → "Ngoài giờ sử dụng. Giờ được phép: 00:00-09:34" |
| 6 | `linux-6-safesearch-tukhoa.mp4` | 29 s | SafeSearch + từ khoá (CSV cục bộ: `mode=blacklist`, `keywords=+default,zombie`) | 00:07 | `linux-6-safesearch-tukhoa-safesearch-duckduckgo.png` | DuckDuckGo: proxy sửa yêu cầu thành `kp=1` trước khi gửi đi; trang về là CAPTCHA của DuckDuckGo (IP máy này đang bị nghi là bot) nên chưa thấy kết quả |
| | | | | 00:16 | `linux-6-safesearch-tukhoa-safesearch-google.png` | Google chuyển sang trang `/sorry` (CAPTCHA) nhưng URL `continue=` cho thấy proxy đã thêm `safe=active` |
| | | | | 00:21 | `linux-6-safesearch-tukhoa-tu-khoa-bi-chan.png` | Tìm "zombie game" → "Nội dung không phù hợp, từ khoá: zombie" |
| | | | | 00:26 | `linux-6-safesearch-tukhoa-url-tu-khoa-bi-chan.png` | URL `wikipedia.org/wiki/Zombie` → chặn theo từ khoá |
| 7 | `linux-7-youtube-tat-danh-muc.mp4` | 21 s | `youtube=block` + danh mục (CSV cục bộ: `mode=blacklist`) | 00:07 | `linux-7-youtube-tat-danh-muc-youtube-tat.png` | youtube.com → "YouTube đã bị tắt" |
| | | | | 00:12 | `linux-7-youtube-tat-danh-muc-danh-muc-gambling.png` | bet365.com không có trong Sheet → "Trang thuộc danh mục bị chặn: gambling" |
| | | | | 00:20 | `linux-7-youtube-tat-danh-muc-wikipedia-mo-duoc.png` | vi.wikipedia.org mở bình thường |
| 8 | `linux-8-cap-nhat-ngay.mp4` | 65 s | Bố mẹ thêm vnexpress.net vào `blocked` → máy con gọi `http://greengate.local/update` (như lệnh `greengate update`) | 00:07 | `linux-8-cap-nhat-ngay-truoc-mo-duoc.png` | Trước: vnexpress.net mở được (blacklist, `blocked` trống) |
| | | | | 00:44 | `linux-8-cap-nhat-ngay-sau-bi-chan.png` | Sau khi danh sách nạp lại: mở `/the-gioi` → "Trang này đã bị chặn" |

Ghi chú kịch bản 8: trong lần quay, proxy trả lời `/update` bằng "đang cập nhật ở chế độ nền" và danh sách mới chỉ
nạp sau **46 s** (lần quay trước 37 s). Chạy lại cùng proxy, cùng CSV nhưng không có Chrome đang duyệt thì `/update`
→ "lists loaded" trong **1 s**. Khả năng: lần nạp định kỳ 60 s đang chạy (cờ `update_running`) nên lệnh cập nhật tay
bị bỏ qua thay vì xếp hàng; trong lúc YouTube không truy cập được (xem dưới) lần nạp định kỳ kéo dài hơn bình thường.
Cần xem lại trước khi kết luận số đo.

## Android (emulator Pixel API 33, Sheet thật)

| # | Video | Dài | Kịch bản | Ảnh | Điều thấy được |
|---|---|---|---|---|---|
| A1 | `android-A1-cai-dat.mp4` | 47 s | Cài APK, mở app, kiểm tra Sheet, hai ô đồng ý, bật bảo vệ, cấp quyền | `android-A1-cai-dat-man-hinh-dau.png` | Màn hình đầu sau khi cài (ô Sheet che đen) |
| | | | | `android-A1-cai-dat-kiem-tra-sheet.png` | Bấm KIỂM TRA → đọc được 5 tab: websites 58 dòng, youtube 74, blocked 2, apps 1, settings 10 |
| | | | | `android-A1-cai-dat-dong-y.png` | Hai ô "Bố mẹ đồng ý" / "Con đã được giải thích và đồng ý" được tích |
| | | | | `android-A1-cai-dat-vpn-bat.png` | Bấm BẬT BẢO VỆ → "Đang bảo vệ: chỉ cho phép danh sách, 56 trang web, 74 kênh YouTube…" (quyền VPN đã cấp sẵn bằng `appops` nên không hiện hộp thoại của Android) |
| | | | | `android-A1-cai-dat-du-quyen.png` | Sau khi cấp Trợ năng và Quản trị thiết bị bằng lệnh adb (như README của app): cả 3 quyền "đã cấp" |
| A2 | `android-A2-trang-duoc-phep.mp4` | 25 s | Trang trong tab `websites` | `android-A2-trang-duoc-phep-ted.png`, `android-A2-trang-duoc-phep-nasa.png` | ted.com và nasa.gov mở bình thường trong Chrome |
| A3 | `android-A3-trang-bi-chan.mp4` | 16 s | Trang không có trong danh sách (whitelist) | `android-A3-trang-bi-chan-vnexpress.png`, `android-A3-trang-bi-chan-tiktok.png` | DNS trả 0.0.0.0 → Chrome báo "Không thể truy cập trang web này, ERR_CONNECTION_REFUSED" (Android chỉ lọc DNS nên không có trang chặn có lý do như trên PC) |
| A4 | `android-A4-youtube.mp4` | 60 s | YouTube trên Android: web cho qua, app bị chặn (Sheet thật, `youtube=channels`) | `android-A4-youtube-trang-chu.png` | m.youtube.com mở được trong Chrome (youtube.com có trong tab `websites`; Android chỉ lọc DNS) |
| | | | | `android-A4-youtube-kenh-la-van-chay.png` | Video của kênh lạ (@RickAstleyYT) **vẫn phát** trên web: lọc DNS không phân biệt được kênh → hạn chế đã ghi trong `README.md` của Android |
| | | | | `android-A4-youtube-app-bi-chan.png` | Mở app YouTube → bị đưa về màn hình chính trong ~0,2 s, toast "GreenGate: ứng dụng này bị chặn" (khung 00:56 của video; app chưa kịp vẽ nên trong video chỉ thấy về màn hình chính) |
| A5 | `android-A5-chup-man-hinh.mp4` | 19 s | Chụp màn hình + thông báo cho con (kích hoạt bằng lệnh test `shotNow`, cùng mã với chụp theo lịch) | `android-A5-chup-man-hinh-khay-thong-bao.png` | Khay thông báo: "GreenGate chụp màn hình theo lịch (mỗi 15 phút)" (tự tắt sau vài giây) bên cạnh thông báo thường trực "GreenGate đang bảo vệ máy này" |
| | | | | `android-A5-chup-man-hinh-trang-thai.png` | Trạng thái app: ảnh mỗi 15 phút, Google Drive chưa có `uploadUrl` nên ảnh chỉ giữ trên máy (logcat: `shotNow ok=true no uploadUrl`) |

## Chưa quay được (và vì sao)

- **Linux 3 và Android A4 – YouTube** (đã quay lại lúc 12:00, xem các bảng trên): từ khoảng 09:30 đến 12:00
  ngày 02-11, mọi kết nối HTTPS tới `youtube.com` từ máy này bị **reset ngay sau TLS** (curl, Chrome không qua
  proxy và Chrome qua proxy đều lỗi `ERR_CONNECTION_RESET`). Cùng lúc Google và DuckDuckGo đưa CAPTCHA → nhiều
  khả năng IP bị Google tạm chặn sau các lượt chạy tự động liên tiếp; tự hết sau ~2,5 giờ. Hai lần quay A4 đầu
  phải bỏ: lần 1 app GreenGate bị ANR trên emulator (GPU phần mềm) và màn hình chính (có ô Sheet) lọt vào video;
  lần 2 phát hiện **lỗi thật**: sau khi tiến trình bị giết, Android chỉ khởi động lại dịch vụ chặn app mà không
  khởi động lại VPN, dịch vụ chặn chạy với bộ quy tắc rỗng nên app YouTube không bị chặn → đã sửa
  (`AppBlockerService` đọc quy tắc từ bộ nhớ đệm và tự bật lại VPN), video A4 quay với bản đã sửa.
- **Android – app bị chặn theo tab `apps`**: Sheet thật chưa có dòng `apps` nào có hiệu lực (chỉ dòng ví dụ `#`),
  không sửa Sheet thật trong buổi quay. A4 chỉ cho thấy app YouTube bị chặn (tự động khi `youtube` ≠ `any`).
- **Linux – chụp màn hình từ xa qua relay**: không dựng trong giới hạn thời gian của buổi quay (đã đo ở `REPORT.md` §6).
- **SafeSearch**: proxy sửa yêu cầu đúng (`kp=1`, `safe=active` thấy trong URL), nhưng cả hai công cụ tìm kiếm trả
  CAPTCHA cho IP này nên chưa có ảnh kết quả tìm kiếm an toàn.

## Cách quay lại

- Linux: `NODE_PATH=<repo>/node_modules node vid-linux.js <id>` (script trong scratchpad của phiên; mỗi id tạo một bản
  proxy riêng trong `bench/<id>/` với `greengate.json` trỏ `sitesUrl`/`settingsUrl`/… tới CSV `file://`, mitmdump
  `--mode regular@127.0.0.1:1808x --set confdir=… -s greengate.py -q`, chờ dòng "lists loaded" rồi mở Chrome với
  `--proxy-server`). Bản proxy chạy thử có một sửa đổi so với `proxy/greengate.py`: hàm tra tài khoản theo cổng trên
  Linux chỉ nhận socket ESTABLISHED (xem ghi chú dưới).
- Android: `vid-android.sh A1|A2|A3|A4|A5` (adb + screenrecord; che ô Sheet bằng ffmpeg `drawbox` theo toạ độ lấy
  từ `uiautomator dump`, mật độ màn hình đặt 300 dpi để cả màn hình cài đặt hiện trong một khung).

## Phát hiện trong lúc quay (cần sửa trong mã)

1. **Tra tài khoản theo cổng trên Linux có thể nhận nhầm root** (`_user_for_port_linux`): hàm đọc `/proc/net/tcp`
   và lấy dòng đầu tiên có cùng cổng cục bộ, kể cả socket ở trạng thái TIME_WAIT (uid 0). Khi máy có nhiều kết nối
   ngắn, cổng của trình duyệt trùng với một socket TIME_WAIT → proxy coi kết nối là của root (admin) → **không lọc**,
   trang bị chặn vẫn mở (thấy 2 lần trong 25 lượt mở trang ở lần quay đầu). Sửa: chỉ nhận trạng thái `01`
   (ESTABLISHED) và khớp cả địa chỉ đích (cổng của proxy). Đã vá trong bản chạy thử để quay; chưa sửa trong repo.
2. **`/update` bị bỏ qua khi một lần nạp khác đang chạy** (`update_running`): nên ghi nhớ và chạy lại ngay sau khi
   lần kia xong, thay vì trả lời "đang cập nhật ở chế độ nền" rồi quên.
3. Chrome 142 (headless) không mở được `http://greengate.local/` (ERR_BLOCKED_BY_CLIENT, kể cả khi tắt Local Network
   Access và HTTPS upgrade); `curl -x` vẫn vào được. Chưa thử Chrome có giao diện; nếu lặp lại trên máy thật thì
   trang điều khiển cần cách mở khác (ví dụ `http://127.0.0.1:8081/`).
