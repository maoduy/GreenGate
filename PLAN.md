# GreenGate: kế hoạch phát triển

Tài liệu này ghi lại kiến trúc và lộ trình để mở rộng GreenGate từ một proxy lọc web trên Windows
thành một hệ thống cho cả gia đình: máy con chạy Windows, Linux, Android (iPhone ở mức hạn chế);
phụ huynh theo dõi trên laptop và điện thoại.

Ngày lập: 2026-10-30. Thời gian ước tính tính cho **một người phát triển**, là ước lượng thô,
cần chỉnh lại sau giai đoạn 1.

---

## 1. Mục tiêu

1. Phụ huynh quản lý mọi thiết bị của con từ **một chỗ**: Google Sheet (danh sách web, kênh YouTube,
   giới hạn phút, khung giờ) và một web app (thiết bị, lịch sử, ảnh màn hình).
2. Máy con: lọc web, lọc YouTube theo kênh, giới hạn thời gian, chặn ứng dụng, chặn theo khung giờ.
3. Phụ huynh xem được **lịch sử truy cập** và **ảnh chụp màn hình** (theo yêu cầu, hoặc tự động mỗi giờ).
4. **Miễn phí hoàn toàn cho phụ huynh.** Chi phí server gần như bằng 0.
5. **Server không lưu dữ liệu của con.** Ảnh và lịch sử nằm trên máy con hoặc Google Drive của phụ huynh,
   luôn được mã hoá đầu-cuối.

## 2. Nguyên tắc thiết kế

| Nguyên tắc | Hệ quả |
|---|---|
| Server chỉ chuyển tin | Server chỉ biết mã thiết bị, khoá công khai, ai quản máy nào, lần cuối online. Không ghi ảnh, lịch sử, danh sách web |
| Mã hoá đầu-cuối | Máy con khoá dữ liệu bằng khoá công khai của phụ huynh; chỉ trình duyệt của phụ huynh mở được |
| Lọc web không phụ thuộc server | Máy con đọc thẳng Google Sheet. Server GreenGate tắt thì việc lọc vẫn chạy |
| Chặn khi lỗi (fail closed) | Giữ như hiện tại: chưa tải được danh sách lần nào thì chặn hết; tải lỗi thì giữ danh sách cũ |
| Minh bạch với con | Không có chế độ ẩn. Con được báo mỗi lần bị chụp màn hình; chụp định kỳ có thông báo thường trực |
| Thiết kế cho "nhóm" | Mô hình dữ liệu dùng *nhóm* (gia đình, lớp học) thay vì chỉ *gia đình*, để làm bản trường học sau này không phải viết lại |

## 3. Kiến trúc tổng thể

```
 ┌────────────────────────┐      ┌──────────────────────────┐      ┌──────────────────────────┐
 │ PHỤ HUYNH               │      │ SERVER CHUYỂN TIN         │      │ MÁY CON                   │
 │ Web app (PWA)           │◄────►│ Cloudflare Worker         │◄────►│ Windows / Linux:          │
 │ laptop, Android, iPhone │ WSS  │ + Durable Object          │ WSS  │   greengate + agent        │
 │ khoá riêng trong        │      │ sổ ghép đôi, online,      │ FCM  │ Android: app GreenGate      │
 │ trình duyệt             │      │ chuyển gói đã khoá        │      │   (VPN/proxy + agent)     │
 └──────────┬─────────────┘      └──────────────────────────┘      └──────────┬───────────────┘
            │ sửa                                                              │ đọc mỗi 15 phút
            ▼                                                                  ▼
 ┌────────────────────────────────────────────────────────────────────────────────────────────┐
 │ GOOGLE (của phụ huynh): Sheet = danh sách web, kênh, giới hạn, khung giờ                     │
 │                         Drive = ảnh và lịch sử theo giờ (đã khoá), tự xoá sau N ngày          │
 └────────────────────────────────────────────────────────────────────────────────────────────┘
```

Sơ đồ từng bước (ghép đôi, chụp màn hình, xem lịch sử, chụp tự động, lọc web):
https://claude.ai/artifact/JAdU9pgMn64qiDErHZygn9

### 3.1 Các luồng chính

| Luồng | Đi qua server? | Dữ liệu nằm ở đâu |
|---|---|---|
| Lọc web, YouTube, giới hạn giờ | Không | Sheet → máy con |
| Ghép đôi (quét QR) | Có, một lần | Server: khoá công khai + quan hệ phụ huynh ↔ máy |
| Chụp màn hình khi bấm | Có, gói đã khoá, không ghi đĩa | Không lưu ở đâu cả, trừ trình duyệt phụ huynh |
| Xem lịch sử khi cần | Có, gói đã khoá | Máy con |
| Chụp và lịch sử tự động mỗi giờ | Không (chỉ chuyển cài đặt một lần) | Drive của phụ huynh |
| Trạng thái online | Có | Server: lần cuối online + IP |

## 4. Thành phần

### 4.1 Server chuyển tin (`server/`, mới)

- Cloudflare Worker (TypeScript) + một Durable Object cho mỗi nhóm, dùng WebSocket hibernation.
- Lưu trữ: Durable Object storage (hoặc D1) chỉ cho: `group`, `device` (id, tên, khoá công khai,
  last_seen, last_ip, nền tảng), `parent` (id, khoá công khai), `pairing_code` (hết hạn sau 10 phút).
- API:
  - `POST /pair/start` (máy con) → mã ghép đôi
  - `POST /pair/claim` (phụ huynh) → gắn phụ huynh vào máy
  - `GET /ws` (cả hai bên) → kênh WebSocket
  - `POST /push` (nội bộ) → đánh thức Android qua FCM
- Mọi lệnh từ phụ huynh có chữ ký; server kiểm tra quyền, máy con kiểm tra lại chữ ký.
- Gói tin quá 1 MB bị từ chối. Không có hàng đợi: máy offline thì trả lỗi ngay.
- Có nút "Deploy to Cloudflare" để gia đình tự host.

### 4.2 Web app phụ huynh (`parent-app/`, mới)

- Trang tĩnh, cài được như app (PWA), host trên Cloudflare Pages.
- Màn hình: danh sách thiết bị (online/offline), chụp màn hình, dòng thời gian (ảnh + lịch sử theo giờ),
  bảng lịch sử tháng, sửa danh sách (mở Google Sheet hoặc sửa trực tiếp), cài đặt chụp tự động.
- Khoá: tạo trong trình duyệt, lưu trong IndexedDB (không xuất được ra ngoài nếu có thể).
- **Khôi phục khoá:** thêm thiết bị phụ huynh thứ hai bằng QR từ thiết bị thứ nhất, và một
  "mã khôi phục" in ra giấy. Mất hết thì phải ghép đôi lại từ máy con.
- Google OAuth với quyền `drive.file` (không phải quyền "nhạy cảm", không cần Google thẩm định lâu).
- Thông báo: Web Push (Android, desktop; iPhone từ iOS 16.4 khi đã thêm vào màn hình chính).

### 4.3 Máy con Windows (đã có, mở rộng)

Đã có: `proxy/greengate.py`, `proxy/sheetlog.py`, `proxy/install.ps1`, watchdog/supervisor,
`setup/greengate_setup.py` (GreenGate Setup.exe), CI `test-matrix.yml`.

Thêm:
- **`greengate-agent.exe`**: chạy trong phiên đăng nhập của con (khởi động lúc đăng nhập bằng Task Scheduler).
  Giữ WebSocket tới server, chụp màn hình (Windows.Graphics.Capture hoặc `mss`), gửi lịch sử,
  hiện thông báo cho con, chụp tự động và tải lên Drive.
  Service SYSTEM hiện tại chạy ở session 0 nên không chụp được màn hình của con.
- Agent đọc lịch sử qua một cổng nội bộ của greengate (đã có `/log`, `/log.csv`), không đọc file trực tiếp.
- Watchdog kiểm tra agent còn sống, giống cách đang kiểm tra proxy.
- Màn hình ghép đôi + đồng ý trong GreenGate Setup.
- `greengate.py`: luôn cho phép tên miền server GreenGate và Google Drive API (cạnh danh sách host cố định
  trong `_publish()`).

### 4.4 Máy con Linux (`linux/`, mới, dùng lại `greengate.py`)

- `greengate.py` đã có sẵn phần nhận diện người dùng trên Linux (`_user_for_port_linux`).
- systemd service chạy root; nftables chuyển hướng traffic của tài khoản con sang proxy
  (`meta skuid`), chế độ transparent của mitmproxy.
- Chính sách trình duyệt: `/etc/opt/edge/policies/managed`, `/etc/opt/chrome/policies/managed`,
  `/usr/lib/firefox/distribution/policies.json` (hoặc `/etc/firefox/policies`).
- Chứng chỉ: kho hệ thống + NSS của tài khoản con.
- Agent: X11 dùng `mss`; Wayland qua xdg-desktop-portal (khuyến nghị cho tài khoản con chạy X11).
- Đóng gói: `.deb` trước, script cài đặt chung cho các distro khác.
- Điều kiện: tài khoản con không có `sudo`.

### 4.5 Máy con Android (`android/`, mới, Kotlin)

Một app duy nhất, tự là DPC (Device Policy Controller):

| Chức năng | Cách làm |
|---|---|
| Chống gỡ | Device Owner (cài bằng QR lúc thiết lập máy sau khi khôi phục gốc). Chế độ nhẹ: Device Admin + PIN |
| Lọc web | Proxy chạy ngay trên máy, đặt bằng `setRecommendedGlobalProxy`; dự phòng bằng VpnService. Các trang khác lọc theo tên miền (SNI) |
| Lọc YouTube theo kênh | Khoá ứng dụng YouTube và YouTube Kids (`setPackagesSuspended`). Con xem qua Chrome; proxy chỉ giải mã `youtube.com` và áp dụng logic của `greengate.py` (viết lại bằng Kotlin/Go). Chrome tin chứng chỉ người dùng cài |
| Khoá Chrome | Managed configurations của Chrome đặt qua DPC: tắt ẩn danh, chặn trang cài đặt proxy, chặn trình duyệt khác |
| Chặn ứng dụng, khung giờ, giới hạn phút | UsageStatsManager để đếm; `setPackagesSuspended` để khoá |
| Chụp màn hình | AccessibilityService `takeScreenshot()` (Android 11+) |
| Nhận lệnh | FCM (không tự giữ kết nối riêng, đỡ tốn pin) |
| Chụp tự động | WorkManager mỗi giờ, chỉ khi màn hình sáng |

- Phát hành: APK tự ký (tải từ trang web) trước; lên Google Play sau khi hoàn thiện phần khai báo
  quyền Accessibility (thông báo thường trực, không ẩn icon).
- Mục tiêu pin: tăng thêm dưới 5% mỗi ngày (đo trên máy thật).

### 4.6 iPhone / iPad (giai đoạn sau, phạm vi hẹp)

- Ngắn hạn: tài liệu hướng dẫn Screen Time (chặn ứng dụng YouTube, YouTube Kids, trình duyệt khác;
  giới hạn phút; Downtime) + YouTube Kids ở chế độ "chỉ nội dung được phê duyệt".
- Dài hạn (tuỳ chọn): app dùng FamilyControls / ManagedSettings / DeviceActivity, đọc giới hạn từ Sheet.
  Cần xin Apple quyền Family Controls. Lọc kênh trong Safari bằng Safari Web Extension (chuyển từ
  `extension/youtube.js`), con tắt được tiện ích nên chỉ phát hiện và báo phụ huynh.
- **Không làm được trên iOS:** chụp màn hình, lọc kênh trong ứng dụng YouTube.

## 5. Giao thức và mã hoá

- Thư viện: libsodium (libsodium.js trong trình duyệt, PyNaCl/`cryptography` trên PC, lazysodium trên Android).
- Khoá: mỗi bên một cặp Ed25519 (ký) + X25519 (mã hoá).
- Lệnh của phụ huynh: `{type, device_id, nonce, ts, params}` ký bằng Ed25519. Máy con từ chối lệnh
  quá 60 giây hoặc trùng nonce.
- Dữ liệu từ máy con: `crypto_box_seal` tới khoá công khai của phụ huynh (mỗi phụ huynh một bản nếu có nhiều phụ huynh).
- Các loại lệnh: `screenshot`, `history.get {month}`, `settings.set {autoCapture, retentionDays}`,
  `status`, `pause {minutes}` (giống `greengate-pause.ps1`).
- File trên Drive: `GreenGate/<device>/<yyyy-mm-dd>/<hh>.shot.bin` và `<hh>.log.bin`.

## 6. Thay đổi trong Google Sheet

| Tab | Cột | Mới? |
|---|---|---|
| `websites` | A tên miền, C phút/ngày | Có sẵn |
| `websites` | D khung giờ, ví dụ `17:00-20:00 T2-T6` | **Mới** |
| `youtube` | A kênh | Có sẵn |
| `apps` | A tên gói Android hoặc tên `.exe`, B `chặn` hoặc số phút, C khung giờ | **Mới** |

Định dạng khung giờ dùng chung cho mọi nền tảng; parser viết một lần, có test.

## 7. Lộ trình

| Giai đoạn | Nội dung | Ước tính | Kết quả để nghiệm thu |
|---|---|---|---|
| **0. Chuẩn bị** | Cấu trúc repo (`server/`, `parent-app/`, `agent/`, `linux/`, `android/`), viết spec giao thức, tài khoản Cloudflare + dự án Google Cloud (OAuth) | 1 tuần | Spec được duyệt; CI chạy cho các thư mục mới |
| **1. Server chuyển tin + ghép đôi** | Worker, Durable Object, ghép đôi bằng QR, trạng thái online, test tự động | 1–2 tuần | Ghép một máy giả lập với một phụ huynh giả lập; server không có trường dữ liệu nào ngoài danh sách ở 4.1 |
| **2. Agent Windows** | Chụp màn hình theo lệnh, thông báo cho con, lấy lịch sử từ greengate, đưa vào GreenGate Setup, mở rộng `test-matrix.yml` | 1–2 tuần | Bấm nút trên web app, ảnh hiện trong dưới 5 giây; con thấy thông báo |
| **3. Web app phụ huynh (bản đầu)** | Danh sách thiết bị, chụp màn hình, bảng lịch sử tháng, khôi phục khoá, Web Push | 2–3 tuần | Dùng được trên Chrome desktop, Android, Safari iPhone |
| **4. Khung giờ + chặn ứng dụng trên PC** | Cột D của `websites`, tab `apps`, agent tắt ứng dụng bị cấm | 1 tuần | Test cho parser khung giờ; YouTube bị chặn ngoài khung giờ |
| **5. Chụp tự động + Drive** | Chụp mỗi giờ, tải lên Drive, tự xoá, dòng thời gian trong web app, cảnh báo khi thiếu ảnh | 1–2 tuần | 24 giờ chạy liên tục, đủ ảnh các giờ máy được dùng, không file nào đọc được nếu không có khoá |
| **6. Linux** | systemd, nftables, chính sách trình duyệt, chứng chỉ, agent X11, gói `.deb`, CI trên Ubuntu | 1–2 tuần | Tài khoản con trên Ubuntu bị lọc như Windows; tài khoản admin không bị lọc |
| **7. Android** | DPC + Device Owner, proxy/VPN, lọc YouTube trong Chrome, chặn ứng dụng, khung giờ, chụp màn hình, FCM, chụp tự động | 6–10 tuần | Chạy trên 3 máy thật (Android 11, 13, 15); pin tăng dưới 5%/ngày; con không gỡ được app |
| **8. Ra mắt** | Tên miền riêng, trang giới thiệu, hướng dẫn cài đặt, nút ủng hộ VietQR, chính sách quyền riêng tư | 1 tuần | Một gia đình không rành công nghệ tự cài được theo hướng dẫn |
| **9. iPhone** (tuỳ chọn) | Tài liệu Screen Time; sau đó app FamilyControls | 1 tuần / 4–6 tuần | |
| **10. Bản trường học** (sau khi có ~100 gia đình) | Nhiều quản lý trong một nhóm, phân quyền giáo viên, báo cáo theo lớp | 3–4 tuần | Một trường hoặc trung tâm dùng thử |

Tổng đến hết giai đoạn 8 (chưa gồm iPhone và bản trường học): khoảng **4–6 tháng** cho một người.

Thứ tự này đưa ra bản dùng được cho máy tính sau khoảng 2 tháng (giai đoạn 0–5), trước khi bắt đầu
phần Android lớn nhất.

## 8. Kiểm thử

- Giữ và mở rộng các test hiện có: `test/smoke.js`, `test/proxy.js`, `test/feed.js`, CI `test-matrix.yml`.
- Server: test đơn vị + test tích hợp với `wrangler dev` (Miniflare).
- Giao thức: bộ test vector dùng chung cho Python, TypeScript, Kotlin (cùng một gói tin, ba bên đều giải mã được).
- Web app: Playwright trên Chromium và WebKit.
- Linux: CI trên Ubuntu với hai tài khoản (con, admin).
- Android: Espresso cho UI; danh sách kiểm thử thủ công trên máy thật (Device Owner không chạy được trên emulator CI một cách tin cậy).
- Kiểm thử "con lách luật": danh sách các cách lách (đổi DNS, VPN khác, trình duyệt khác, chỉnh giờ hệ thống,
  gỡ app, khôi phục gốc) và kết quả mong đợi cho từng cách.

## 9. Bảo mật

- Token Drive trên máy con chỉ có quyền `drive.file`. Con lấy được token thì không đọc được ảnh (đã khoá)
  nhưng xoá được; web app cảnh báo khi thiếu ảnh.
- Thay khoá service account hiện đặt trên máy con (`greengate-sheets.json`) bằng token `drive.file` của phụ huynh.
- Server không có khoá riêng nào; lộ dữ liệu server chỉ lộ danh sách thiết bị và thời điểm online.
- Ký bản cập nhật của agent và app; máy con chỉ nhận bản cập nhật có chữ ký đúng.

## 10. Pháp lý và sự đồng ý

- Nghị định 13/2023/NĐ-CP: trẻ từ 7 tuổi cần sự đồng ý của cả cha mẹ và trẻ. Màn hình đồng ý ghi rõ:
  dữ liệu nào được thu thập, tần suất chụp, thời gian giữ ảnh. Lưu thời điểm đồng ý trên máy con.
- Mặc định tự xoá ảnh sau 30 ngày.
- Không quảng cáo, không bán hay phân tích dữ liệu.
- Google Play: khai báo AccessibilityService cho mục đích quản lý của phụ huynh, thông báo thường trực.
- Chính sách quyền riêng tư công khai trên trang web.

## 11. Chi phí vận hành

| Khoản | Chi phí |
|---|---|
| Cloudflare Workers + Pages | 0 đồng (gói miễn phí); ~5 USD/tháng khi lên hàng nghìn gia đình |
| Tên miền | vài trăm nghìn đến ~1 triệu đồng/năm |
| Google Play | 25 USD một lần |
| Apple Developer (nếu làm iOS) | 99 USD/năm |
| Google Drive | phụ huynh dùng 15 GB miễn phí của mình (~75 MB/tháng/thiết bị khi chụp mỗi giờ) |

## 12. Doanh thu (phụ huynh luôn miễn phí)

1. Ủng hộ tự nguyện (VietQR, MoMo, GitHub Sponsors) ngay từ khi ra mắt.
2. Bản trường học và trung tâm, tính phí theo số máy mỗi năm.
3. Bán bản quyền gắn thương hiệu cho nhà mạng và chuỗi bán lẻ.
4. Dịch vụ cài đặt và hỗ trợ có phí (không bắt buộc).
5. Xin tài trợ từ các chương trình an toàn trẻ em trên mạng.

Không làm: quảng cáo, bán dữ liệu, danh sách kênh có tài trợ không ghi rõ.

## 13. Rủi ro

| Rủi ro | Mức | Cách giảm |
|---|---|---|
| YouTube đổi giao diện hoặc API làm hỏng bộ lọc kênh | Cao | Test `test/feed.js` chạy định kỳ trên CI; logic lọc dùng chung một chỗ |
| Google Play từ chối app (Accessibility, Device Owner) | Trung bình | Phát hành APK ngoài Play trước; chuẩn bị khai báo theo chính sách cho app quản lý của phụ huynh |
| Chrome Android thôi tin chứng chỉ người dùng cài | Thấp–trung bình | Theo dõi bản phát hành Chrome; dự phòng bằng managed configurations (URL allowlist) + chặn YouTube trên web |
| Phụ huynh mất khoá | Trung bình | Nhiều thiết bị phụ huynh, mã khôi phục, ghép đôi lại |
| Apple không cấp quyền Family Controls | Trung bình | iOS chỉ dừng ở mức hướng dẫn Screen Time |
| Pin Android tốn hơn dự kiến | Trung bình | Chỉ giải mã `youtube.com`; đo pin từ bản thử đầu tiên |
| Một người phát triển, khối lượng lớn | Cao | Làm PC trước, ra mắt sớm, Android sau; tìm người đóng góp khi mã nguồn mở |

## 14. Việc cần quyết định

1. Tên miền và tên sản phẩm chính thức (GreenGate?).
2. Có mã nguồn mở toàn bộ không? (giúp xin tài trợ và tạo lòng tin; ảnh hưởng đến bản quyền gắn thương hiệu)
3. Android: Device Owner bắt buộc, hay cho phép cả chế độ nhẹ (Device Admin + PIN)?
4. YouTube trên Android: proxy trong Chrome (đề xuất) hay YouTube Kids "chỉ nội dung được phê duyệt" làm mặc định?
5. Thời hạn giữ ảnh mặc định (đề xuất 30 ngày) và tần suất chụp tối đa cho phép.
6. Có làm app iOS không, hay chỉ dừng ở hướng dẫn Screen Time?
