# Ảnh màn hình định kỳ lên Google Drive của bố mẹ

Máy con tự chụp màn hình theo lịch (mặc định **mỗi 15 phút**, đổi trong Sheet) và gửi vào thư mục
Google Drive của bạn. Không cần tài khoản Google Cloud, không có mật khẩu Google nào trên máy con:
ảnh đi qua một **Apps Script** nhỏ gắn với chính Google Sheet GreenGate, chạy bằng tài khoản của bạn.
Máy con chỉ có thể *gửi thêm* ảnh, không đọc, không xoá được gì trong Drive.

## Cài một lần (khoảng 3 phút)

1. Mở Google Sheet GreenGate → menu **Tiện ích mở rộng → Apps Script**.
2. Xoá nội dung mẫu, dán toàn bộ file [`GreenGateUploader.gs`](GreenGateUploader.gs).
3. Dòng `var FOLDER = "..."`: dán link thư mục Drive của bạn (dán link bạn đã chia sẻ cho GreenGate).
4. Nút **Triển khai → Triển khai mới** → biểu tượng bánh răng → **Ứng dụng web**:
   - Thực thi với tư cách: **Tôi**
   - Ai có quyền truy cập: **Bất kỳ ai**
   → **Triển khai** → cho phép quyền (Google hỏi 1 lần) → chép **URL ứng dụng web** (kết thúc bằng `/exec`).
5. Trong Sheet, tab `settings`, thêm các dòng:

   | A | B |
   |---|---|
   | `uploadUrl` | *URL vừa chép* |
   | `driveFolder` | `https://drive.google.com/drive/folders/<ID-THU-MUC-CUA-BAN>` |
   | `screenshotEvery` | `15` |
   | `screenshotHours` | `07:00-22:00` *(tuỳ chọn; bỏ dòng này = cả ngày)* |

6. Trên máy con: `greengate update` (hoặc chờ ≤ 60 s) rồi `greengate drive-test` → phải thấy
   `ok: true` và một ảnh `test-…jpg` xuất hiện trong Drive. Trên Android: màn hình Trạng thái → "Gửi ảnh thử".

Ảnh được xếp: `<thư mục của bạn>/<tên máy>/<YYYY-MM-DD>/<HH-MM-SS>.jpg`; ảnh bố mẹ chụp trực tiếp có
đuôi `-bo-me`. Ảnh cũ hơn `retentionDays` (mặc định 30) được script đưa vào Thùng rác.

## Hai cách xem

| | Xem lịch sử trong Drive | Chụp trực tiếp |
|---|---|---|
| Khi nào | Bất cứ lúc nào, kể cả máy con đã tắt | Máy con đang mở, có mạng |
| Độ chi tiết | Mỗi 15 phút (hoặc theo cài đặt) | Ngay lúc đó, 0,2–1 s |
| Ở đâu | App Google Drive / nút "Mở Drive" trong app GreenGate | Nút "Chụp màn hình" trong app GreenGate |

## Minh bạch với con

- Mỗi lần chụp (theo lịch hay bố mẹ bấm) máy con hiện một thông báo tự tắt sau vài giây, ghi rõ
  "GreenGate chụp màn hình theo lịch (mỗi 15 phút)" hoặc "Bố mẹ vừa chụp màn hình".
- Khi cài, cả bố mẹ và con cùng xác nhận đồng ý (hai nút riêng). Chưa có đủ hai xác nhận thì máy không
  tự chụp theo lịch (vẫn ghi vào nhật ký "chưa có đồng ý").
- Không chụp khi màn hình khoá/tắt hoặc ngoài `screenshotHours`.

## Giới hạn và an toàn

- URL `uploadUrl` nằm trong Sheet (ai có link Sheet đều đọc được) nên về lý thuyết người lạ có thể gửi
  ảnh rác vào thư mục: script chỉ nhận JPEG ≤ 1,5 MB, tối đa 30 ảnh/giờ/máy. Nếu lo ngại, bỏ dòng
  `uploadUrl` trong Sheet và điền vào cấu hình máy con (`greengate drive-set <url>`).
- Hạn mức Apps Script tài khoản cá nhân: ~90 phút chạy/ngày – đủ cho vài máy chụp mỗi 15 phút.
- Ảnh lưu dạng thường trong Drive của bạn (để xem được bằng app Drive); hãy giữ thư mục riêng tư.
