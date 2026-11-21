# GreenGate: relay, ứng dụng phụ huynh và agent - báo cáo v1

Ngày đo: 2026-11-01. Toàn bộ chạy trên một máy Linux (Ubuntu 24.04): relay cục bộ bằng
`wrangler dev` (Miniflare, chưa đưa lên Cloudflare), agent thật, ứng dụng phụ huynh thật chạy
trong Chrome. Số liệu vì vậy phản ánh **thời gian xử lý của phần mềm**, chưa gồm độ trễ Internet
giữa nhà và Cloudflare (thường thêm 30–150 ms mỗi chiều ở Việt Nam).

## 1. Kiến trúc (10 dòng)

1. Bố mẹ mở ứng dụng web GreenGate (PWA, `parent-app/`), khoá riêng tạo và giữ trong trình duyệt (IndexedDB).
2. Máy con chạy agent (`agent/greengate_agent.py`), có cặp khoá riêng của máy.
3. Ghép đôi: agent lấy mã 6 số từ relay; bố mẹ nhập mã (hoặc quét QR); relay nối khoá công khai hai bên.
4. Mọi lệnh (chụp màn hình, lịch sử, cập nhật, tạm dừng...) được bố mẹ **mã hoá bằng khoá của máy con** (nacl.box) rồi gửi lên relay.
5. Relay (`server/`, Cloudflare Worker + một Durable Object cho mỗi máy) chỉ chuyển gói đã khoá; máy online thì đẩy ngay qua WebSocket, offline thì giữ trong hàng đợi có hạn (ảnh 10 phút, lịch sử/cập nhật 24 giờ).
6. Agent giải mã, thực hiện, **mã hoá kết quả bằng khoá của bố mẹ**, gửi lại relay.
7. Relay giữ kết quả tối đa 10 phút hoặc đến khi bố mẹ tải về **một lần**, rồi xoá.
8. Trình duyệt bố mẹ giải mã và hiển thị (ảnh, bảng lịch sử, trạng thái) kèm bảng thời gian từng chặng.
9. Cài đặt (danh sách web, kênh, giờ...) vẫn **không đi qua relay**: nằm trong Google Sheet, máy con tự đọc; lệnh "Cập nhật danh sách ngay" chỉ là cú nhắc để máy đọc lại tức thì.
10. Agent lấy lịch sử và lệnh cập nhật từ proxy GreenGate trên chính máy đó (`http://greengate.local/log.csv`, `/update`).

## 2. Relay lưu gì, không lưu gì

| Lưu (mỗi máy) | Không bao giờ có ở relay |
|---|---|
| mã máy, khoá công khai của máy, token của máy | ảnh màn hình (dạng đọc được) |
| tên máy, nền tảng, lần online cuối | lịch sử truy cập (dạng đọc được) |
| khoá công khai của từng phụ huynh + token | danh sách web / kênh / cài đặt |
| lệnh đã mã hoá đang chờ (đến khi máy nhận hoặc hết hạn) | khoá riêng của bất kỳ ai |
| kết quả đã mã hoá (đến khi bố mẹ tải, tối đa 10 phút) | tài khoản Google, mật khẩu |

Kiểm chứng bằng `server/test/e2e.mjs`: 27 kiểm tra (ghép đôi, mã dùng một lần, token sai, khoá lạ,
gói quá cỡ, hàng đợi offline, xoá sau khi tải, gỡ máy) đều đạt.

## 3. Số đo

### 3.1 Máy con đang mở (agent online)

10 lần chụp màn hình liên tiếp, ảnh thật 1920×1080 nhiều chi tiết (thu về 1280×720, JPEG chất lượng 60):

| Chặng | Trung vị | p95 |
|---|---|---|
| Trình duyệt → relay (gửi lệnh) | ~35 ms | |
| Relay → máy con (WebSocket) | 1–5 ms | |
| Máy con chụp + nén + mã hoá | 83 ms | |
| Máy con → relay → trình duyệt + giải mã | ~30 ms | |
| **Tổng, bấm nút đến thấy ảnh** | **153 ms** | **202 ms** |
| Cỡ ảnh gửi đi | 221 KB | |

Lịch sử tháng (CSV nén gzip, qua proxy cục bộ): 5 lần, trung vị **45 ms**.
"Cập nhật danh sách ngay": **47 ms** đến khi máy xác nhận; proxy ghi `lists loaded` lại trong vòng ~1 giây sau đó.
Trạng thái: ~50–65 ms.

Chỉ phần relay (giả lập máy con cùng máy, gói 600 KB, `server/test/e2e.mjs`): trung vị 52–135 ms, p95 ≤ 390 ms tuỳ lần chạy (Miniflare cục bộ).

### 3.2 Máy con đang tắt (agent không chạy)

Lệnh được gửi khi agent đã dừng; relay trả lời ngay "máy offline, lệnh được giữ lại"; ứng dụng
phụ huynh tiếp tục chờ (long-poll 25 giây một lần). Sau đó bật agent:

| Máy tắt trong | Từ lúc bật agent đến khi bố mẹ có ảnh | Tổng từ lúc bấm nút |
|---|---|---|
| 20 giây | **286–840 ms** | 20,3 giây (= 20 s chờ + 0,3 s) |
| 5 giây | **286–806 ms** | 5,4 giây |

Nghĩa là thời gian nhận kết quả khi máy đã tắt = **thời gian máy được bật lại + dưới 1 giây**,
miễn là lệnh chưa hết hạn (ảnh: 10 phút; lịch sử và cập nhật: 24 giờ). Lệnh hết hạn thì ứng dụng
báo "Lệnh hết hạn trước khi máy trả lời". Với Android, bước tiếp theo là FCM để đánh thức máy đang
ngủ (chưa làm trong v1).

### 3.3 Khởi động lạnh

Yêu cầu đầu tiên tới relay cục bộ: 24–141 ms (Miniflare). Trên Cloudflare thật, Worker khởi động
lạnh thường < 10 ms, Durable Object lần đầu thức dậy thêm vài chục ms; sẽ đo lại sau khi deploy.

## 4. Triển khai

Relay chưa lên Cloudflare vì máy này chưa đăng nhập tài khoản Cloudflare. **Bạn cần làm một lần:**

```
cd server
npx wrangler login      # mở trình duyệt, đăng nhập Cloudflare (gói miễn phí đủ dùng)
npx wrangler deploy     # in ra https://greengate-relay.<tài-khoản>.workers.dev
```

Sau đó dán URL đó vào ứng dụng phụ huynh (Thêm máy > "Relay khác?") và vào lệnh `pair` của agent.
Tên miền riêng: xem `server/README.md`. Ứng dụng phụ huynh là tệp tĩnh (`parent-app/`), đưa lên
GitHub Pages (thư mục `docs/app/`) là chạy; nhớ dùng HTTPS để cài được như app và dùng camera quét QR.

## 5. Cách ghép đôi

Máy con (Windows/Linux):
```
python agent/greengate_agent.py pair --relay https://<relay> --name "Máy của An"
python agent/greengate_agent.py run        # chạy nền; Linux: agent/greengate-agent.service
```
Điện thoại/máy bố mẹ: mở ứng dụng > **Thêm máy** > nhập mã 6 số đang hiện trên máy con (hoặc **Quét QR**).
Xong: vào **Thiết bị** > mở máy > bấm **Chụp màn hình** / **Lịch sử tháng này** / **Cập nhật danh sách ngay**.
Trang **Khoá**: xuất "mã khôi phục" ra giấy; nhập lại trên máy khác để đọc được dữ liệu cũ.

## 6. Chạy lại phép đo

```
cd server && npm install && npm run dev                      # relay cục bộ :8787
cd parent-app && python3 -m http.server 8790                 # ứng dụng :8790
# proxy GreenGate chạy ở cổng 8080 (hoặc đặt PROXY_PORT)
RELAY=http://127.0.0.1:8787 APP=http://127.0.0.1:8790/index.html \
AGENT_PY=python3 AGENT_CFG=/tmp/gn-agent.json PROXY_PORT=8080 node parent-app/test/e2e-parent.mjs
```
Kết quả ghi ra JSON (`OUT`). Đặt `GREENGATE_TEST_IMAGE=<ảnh.png>` để dùng ảnh cố định thay màn hình thật.

## 7. Khoảng trống còn lại (v1)

- **Khoá của máy con đọc được bởi tài khoản của con** (agent chạy trong phiên của con để chụp được màn hình). Con rành kỹ thuật có thể giả kết quả. Bước sau: tách phần nối relay chạy dưới SYSTEM/root, chỉ phần chụp ảnh chạy trong phiên của con.
- Android chưa có FCM: máy ngủ sâu không được đánh thức; lệnh chờ đến khi app online lại.
- Chưa có Web Push cho phụ huynh (báo khi máy con lên mạng, khi có ảnh định kỳ).
- Ảnh định kỳ (`screenshotEvery`) mới lưu mã hoá trên máy con, chưa tải lên Google Drive của phụ huynh.
- Sửa cài đặt ngay trong ứng dụng cần Google OAuth client (chủ dự án tạo trong Google Cloud Console); hiện ứng dụng hiển thị cài đặt và mở Sheet để sửa.
- Chụp màn hình Linux dùng X11/XWayland (mss); phiên Wayland thuần có thể cho ảnh đen.
- Số đo trên là cục bộ; cần đo lại qua Internet sau khi deploy để có độ trễ thật.
