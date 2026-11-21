# GreenGate - kế hoạch phân cấp người dùng, kiến trúc và giấy phép

Bản đề xuất (chỉ kế hoạch, chưa làm) trả lời ba câu hỏi ngày 02-11-2026:

1. Phân loại mức độ sử dụng từ cơ bản đến nâng cao, và cần sửa/bổ sung gì để ai cũng dùng được.
2. Trường học / công ty có thể dùng relay của chính họ không, và quản trị viên quản lý dữ liệu thế nào.
3. Với mô hình đó, chọn MIT / Apache-2.0 / AGPL-3.0 thì được gì, mất gì.

Ký hiệu: ✅ đã có · 🔧 đã có nhưng cần sửa · ➕ phải làm mới.

---

## 1. Bốn cấp độ (đề xuất lại từ ba cấp của bạn)

Ba cấp bạn nêu là đúng hướng. Tôi tách thêm một cấp "Tổ chức" vì nhu cầu của trường/công ty khác
hẳn gia đình (nhiều máy, người quản trị không phải bố mẹ, dữ liệu phải ở chỗ họ kiểm soát), và gộp
hai phương án "Trung bình" của bạn thành hai *cách vào* của cùng một cấp.

| Cấp | Dành cho | Bố mẹ / quản trị phải làm gì | Máy con làm gì |
|---|---|---|---|
| **0 · Cơ bản** "cài là chạy" | Bố mẹ không rành IT | Tải, bấm Cài, chọn tài khoản con, bấm Đồng ý. **Hết.** Không Sheet, không tài khoản Google, không relay | Chế độ *blacklist mặc định*: chặn danh mục không lành mạnh (adult, gambling, drugs, weapons, violence, malware, bypass - cập nhật tự động từ GitHub), từ khoá cấm (bộ mặc định Việt + Anh) trong URL/tiêu đề/kết quả tìm kiếm, bật SafeSearch + YouTube chế độ hạn chế, MXH tuỳ chọn bật/tắt lúc cài, **không giới hạn giờ**. Lịch sử xem tại `http://greengate.local/log` ngay trên máy con |
| **1 · Gia đình** | Bố mẹ muốn chỉnh | *Cách A:* Setup tạo cho bố mẹ một **bản sao Sheet mẫu** (1 bấm, trên tài khoản Google của họ) rồi họ sửa trong Sheet. *Cách B:* không cần biết Sheet là gì, chỉnh trong **ứng dụng phụ huynh** (điện thoại) hoặc **trang cài đặt cục bộ** `http://greengate.local/settings` trên máy con (có mật khẩu bố mẹ) | Chọn whitelist / blacklist, thêm bớt web và kênh YouTube, giới hạn phút mỗi ngày, khung giờ, bật/tắt từng danh mục |
| **2 · Nâng cao** | Người rành | Mọi thứ của cấp 1 + Drive ảnh định kỳ, relay để chụp màn hình/xem lịch sử từ xa, nhiều thiết bị / nhiều con với cột "Áp dụng cho", từ khoá và danh mục tự định nghĩa, log lên Sheet | Như cấp 1 + agent (chụp màn hình, nhận lệnh) |
| **3 · Tổ chức** | Trường, công ty | Triển khai hàng loạt (Intune/GPO/script), **relay riêng** và **kho dữ liệu riêng**, nhiều quản trị viên, nhóm/lớp, chính sách lưu trữ | Như cấp 2 nhưng cấu hình lấy từ máy chủ của tổ chức, dữ liệu đẩy về kho của tổ chức |

Nguyên tắc: **cấp trên là tập cha của cấp dưới**, cùng một bản cài. Cấp 0 không phải "bản rút gọn";
nó chỉ là bản đầy đủ chạy với cấu hình mặc định và nguồn cấu hình = file trong máy.

### Cấp 0 có làm được "bố mẹ không phải làm gì" không? Có, với ba điều kiện

1. **Cấu hình mặc định phải nằm trong bản cài**, không phải trong Sheet của ai cả. Hiện nay
   `setup/greengate_setup.py` (`DEFAULT_SHEET`) và `proxy/install.ps1` (`-SheetId`) điền sẵn **Sheet
   của chính bạn**: ai cài mà không đổi là đọc danh sách của gia đình bạn, và bạn sửa Sheet là
   đổi luật cho cả người lạ. Đây là việc phải sửa đầu tiên (mục 3, P0) 🔧.
2. Chế độ mặc định là **blacklist + danh mục + từ khoá**, vì whitelist mà không ai điền thì con
   không vào được gì cả. Engine đã hỗ trợ cả hai (`policy.py`) ✅; chỉ cần đổi mặc định.
3. Cần **bộ từ khoá mặc định tiếng Việt** đủ tốt và cập nhật được (hiện có `keywordsDefault`
   ✅ nhưng là danh sách ngắn, chủ yếu tiếng Anh) 🔧.

Giới hạn thật của cấp 0 mà cần nói rõ với bố mẹ: không có kiểm soát giờ, không có báo cáo từ xa,
không chặn app (Android). Muốn những thứ đó thì lên cấp 1-2, không cần cài lại.

---

## 2. Kiến trúc: sửa gì để bốn cấp cùng chạy trên một bản

Hôm nay chuỗi cấu hình là *Sheet → CSV → policy*. Cấp 0 không có Sheet, cấp 3 không muốn Sheet.
Vì vậy đổi một chỗ: tách "**nguồn cấu hình**" khỏi "**luật**".

```
            ┌──────────────── nguồn cấu hình (cắm được) ────────────────┐
            │ (a) mặc định trong bản cài       ✅ một phần (file://)      │
            │ (b) Google Sheet của gia đình     ✅                          │
            │ (c) gói ký số từ app phụ huynh / trang settings qua relay ➕ │
            │ (d) URL của tổ chức (JSON ký số, Git/web nội bộ/MDM)     ➕ │
            └───────────────┬────────────────────────────────────────────┘
                            ▼  gộp theo thứ tự: mặc định < tổ chức < gia đình < thiết bị
                    policy.py (whitelist/blacklist, danh mục, từ khoá, giờ)  ✅ giữ nguyên
                            ▼
      proxy (Windows/Linux)  ·  VPN (Android)  ·  agent (ảnh, lệnh)       ✅
                            ▼
            ┌──────────────── kho dữ liệu (cắm được) ───────────────────┐
            │ cục bộ (urls.jsonl) ✅ · Sheet log ✅ · Drive ảnh 🧪        │
            │ S3/MinIO, SharePoint/Nextcloud, máy chủ tổ chức        ➕ │
            └────────────────────────────────────────────────────────────┘
```

Các việc cụ thể, xếp theo thứ tự nên làm:

| # | Việc | Phục vụ cấp | Cỡ | Ghi chú |
|---|---|---|---|---|
| P0 | Bỏ Sheet mặc định của tác giả; thêm `config/default.json` đóng gói trong Setup/APK/.deb, Setup có nút **"Cài nhanh"** không hỏi Sheet | 0 | nhỏ | Sửa `greengate_setup.py`, `install.ps1`, Android `SheetSync`, `linux/install.sh`. Loại bỏ rủi ro riêng tư cho chính bạn |
| P1 | Một **định dạng cấu hình chung** (JSON: websites, youtube, blocked, settings, apps + `appliesTo`) và bộ chuyển Sheet→JSON; mọi nguồn đều ra JSON này | tất cả | vừa | Engine đã đọc CSV từng tab; thêm một lớp `config_source.py` rồi Sheet chỉ là một nguồn |
| P2 | **Ký số cấu hình** (Ed25519, khoá tạo lúc ghép đôi): máy con chỉ nhận gói ký đúng khoá; áp dụng cho (c) và (d) | 1B, 2, 3 | vừa | Relay đã E2E cho lệnh/ảnh; dùng lại cặp khoá đó |
| P3 | **Trang cài đặt cục bộ** `greengate.local/settings` (mật khẩu bố mẹ, do proxy phục vụ, lưu JSON ký số ở máy con) | 1B | vừa | Cách rẻ nhất để bố mẹ không cần Sheet; cũng là UI của cấp 0 để bật/tắt MXH, đổi từ khoá |
| P4 | **App phụ huynh gửi cấu hình qua relay** (gói JSON ký số như một lệnh) + Setup Sheet mẫu **"Tạo bản sao"** 1 bấm | 1A, 1B | vừa | Phần app phụ huynh đã có pairing + lệnh; thêm loại lệnh `config` |
| P5 | Cột **"Áp dụng cho"** (tên thiết bị / tên con) trong mọi tab, thiết bị tự lọc dòng của mình | 2 | nhỏ | Đã đề xuất trước; làm chung với P1 |
| P6 | **Nguồn cấu hình URL** + **kho dữ liệu S3-compatible** + script triển khai (`install.ps1 -ConfigUrl -Relay -Storage`, Intune/GPO mẫu, `.deb` preseed, Android managed config) | 3 | vừa | Không cần máy chủ GreenGate riêng; tổ chức dùng web server + MinIO/S3 có sẵn |
| P7 | **Console tổ chức** (Docker: relay + API + Postgres + web): nhóm/lớp, quản trị viên, xem lịch sử/ảnh, chụp từ xa, audit log, retention | 3 | lớn | Chỉ làm khi có khách hàng thật; phần "bán giải pháp" nằm ở đây |
| P8 | Setup ba nút **Cài nhanh / Gia đình / Nâng cao** và một trang "Nâng cấp" trong app phụ huynh | 0→2 | nhỏ | Hoàn thiện trải nghiệm sau P0-P4 |

Thứ tự khuyến nghị: **P0 → P1 → P3 → P5 → P2 → P4 → P8**, rồi P6, P7 khi có nhu cầu tổ chức.
P0 + P1 + P3 là đủ để tuyên bố "cài là chạy, chỉnh không cần Sheet".

---

## 3. Tổ chức dùng relay của chính họ - được, và nên là mặc định cho cấp 3

Relay hiện tại (`server/`, Cloudflare Worker + Durable Object) **không giữ gì ngoài gói đã mã
hoá** và chỉ chuyển tiếp; URL relay là một tham số (`-Relay` trong `install.ps1`, ô "Relay" trong
Setup, `relay` trong cấu hình agent và app). Nghĩa là tổ chức đã có thể:

- `npx wrangler deploy` vào **tài khoản Cloudflare của họ** (gói miễn phí đủ cho vài trăm máy), hoặc
- ➕ chạy **bản Docker** của relay (cần port nhỏ từ Worker sang Node + SQLite; Durable Object thay
  bằng một tiến trình, ~1 ngày việc) trên máy chủ nội bộ, không ra Internet.

Để "flexible nhất có thể", tôi đề xuất cố định ba điểm cắm, tất cả là URL/tham số, không hard-code:

| Điểm cắm | Gia đình (mặc định) | Tổ chức |
|---|---|---|
| **Relay** (lệnh, ảnh trực tiếp) | relay công cộng của dự án hoặc của gia đình | relay riêng (Cloudflare của họ / Docker nội bộ) |
| **Nguồn cấu hình** | file mặc định / Sheet / app phụ huynh | URL JSON ký số trên máy chủ của họ, hoặc đẩy từ console |
| **Kho dữ liệu** (ảnh định kỳ, lịch sử) | máy con / Drive của bố mẹ | S3/MinIO/SharePoint của họ, hoặc console |

Máy con không bao giờ cần biết "gia đình hay tổ chức": nó chỉ thấy ba URL và một khoá công khai.

---

## 4. Quản trị viên tổ chức quản lý dữ liệu thế nào (chỉ kế hoạch)

Dữ liệu gồm bốn loại: **cấu hình** (luật), **lịch sử URL**, **ảnh màn hình**, **trạng thái thiết bị**
(online, phiên bản, người đang dùng). Hai phương án, nên đi theo thứ tự:

**Phương án A - "không máy chủ GreenGate", làm trước (P6).**
- Cấu hình: một file JSON ký số đặt trên web nội bộ hoặc Git của tổ chức; mỗi máy tải về theo chu
  kỳ + nhận "đẩy" qua relay riêng. Quản trị viên sửa file (hoặc Sheet của tổ chức rồi xuất ra).
- Lịch sử và ảnh: máy con đẩy thẳng vào **bucket S3-compatible** của tổ chức (MinIO nội bộ, hoặc
  S3/Backblaze), mỗi máy một tiền tố, ảnh mã hoá bằng khoá của tổ chức nếu họ muốn.
- Xem: MinIO Console / Explorer; báo cáo bằng một script xuất CSV. Không có giao diện riêng.
- Được: không có backend nào để vận hành, không rò dữ liệu ra ngoài tổ chức, triển khai trong vài
  ngày. Mất: thao tác thủ công, không có phân quyền chi tiết.

**Phương án B - "GreenGate Console" tự host, làm khi có khách (P7).**
- Một `docker compose`: relay + API + Postgres + web. Quản trị viên tạo **nhóm** (lớp 6A, phòng kế
  toán), gán luật cho nhóm, ghi danh thiết bị bằng mã 6 số (đã có cơ chế pairing), xem lịch sử/ảnh,
  chụp từ xa, xuất báo cáo.
- Dữ liệu nằm ở máy chủ của tổ chức. Vì quản trị viên **phải đọc được** nên không còn E2E như gia
  đình; thay bằng TLS, **phân quyền** (quản trị / giáo viên chỉ xem lớp mình / phụ huynh xem con
  mình), **audit log** (ai xem ảnh của ai, lúc nào), **retention** (ảnh 30 ngày, lịch sử 90 ngày,
  đổi được), xoá theo yêu cầu.
- Pháp lý: phải thông báo cho học sinh/nhân viên và có đồng ý (như màn hình đồng ý của gia đình),
  tuân thủ Nghị định 13/2023 về dữ liệu cá nhân; console nên có sẵn mẫu thông báo.
- Được: sản phẩm bán được cho trường/công ty, có hỗ trợ trả phí. Mất: phải bảo trì một backend,
  bảo mật nghiêm hơn, công sức lớn (ước 4-6 tuần cho bản đầu).

Khuyến nghị: A trước để khách thử miễn phí; B là thứ bán kèm hỗ trợ.

---

## 5. Giấy phép với mô hình này: MIT · Apache-2.0 · AGPL-3.0

Mô hình: client miễn phí mãi mãi, có thể có quảng cáo sau, bán console/hỗ trợ cho tổ chức, nhận tài trợ.

| | MIT | Apache-2.0 | AGPL-3.0 |
|---|---|---|---|
| Người khác lấy mã làm sản phẩm đóng / SaaS cạnh tranh | **Được, không ràng buộc** | Được | Được *nhưng* phải công bố mã của bản họ chạy (kể cả dịch vụ mạng) |
| Bảo vệ bằng sáng chế cho người dùng và cho bạn | Không | **Có** (cấp phép patent + chấm dứt nếu kiện) | Có |
| Pháp chế trường học / doanh nghiệp chấp nhận | Dễ | **Dễ nhất** | Nhiều nơi cấm hoặc phải xin phép |
| Bán giấy phép thương mại kép (dual-license) cho console | Vô nghĩa (ai cũng đã được dùng) | Vô nghĩa | **Có ý nghĩa**: trả tiền để khỏi mở mã |
| Nhận đóng góp cộng đồng | Dễ | Dễ (cần dòng NOTICE) | Dễ; muốn dual-license phải có CLA/DCO |
| Rủi ro có người "đóng gói lại, bán, không ghi công" | Cao | Trung bình (phải giữ NOTICE, không được dùng nhãn hiệu) | Thấp |
| Phù hợp với "miễn phí mãi mãi" | Có | Có | Có, và còn **ép** các bản phái sinh cũng mở |
| Tương thích thư viện đang dùng (mitmproxy MIT, Android AOSP Apache) | Có | Có | Có |

Được / mất nếu chọn **một** giấy phép cho toàn bộ:

- **MIT**: được phổ cập nhanh nhất, không ai ngại. Mất: không có vũ khí gì khi một công ty lấy
  GreenGate đóng gói thành sản phẩm bán cho trường học - đúng mảng bạn định bán; cũng không có
  điều khoản patent. Nhãn hiệu "GreenGate" phải đăng ký riêng mới giữ được tên.
- **Apache-2.0**: như MIT cộng lá chắn patent và yêu cầu giữ NOTICE; trường/doanh nghiệp thích
  nhất. Mất: vẫn cho phép fork đóng cạnh tranh.
- **AGPL-3.0**: bảo vệ mô hình "miễn phí + bán console": ai chạy GreenGate sửa đổi như dịch vụ
  phải mở mã, muốn không mở thì mua giấy phép từ bạn. Mất: một số tổ chức từ chối thẳng AGPL;
  đóng góp phải ký DCO/CLA để bạn còn quyền bán giấy phép kép; app trên Play Store không vấn đề
  pháp lý nhưng người fork ít hơn.

**Khuyến nghị (tách theo thành phần, cách nhiều dự án mở làm):**

- **Client** (proxy, agent, Setup, APK, .deb, extension): **Apache-2.0** - thứ cần phổ cập, cần
  trường và công ty cài không ngại, cần cộng đồng đóng góp.
- **Relay và Console** (server/, P7): **AGPL-3.0** + bán giấy phép thương mại cho tổ chức muốn
  chạy bản sửa đổi kín. Đây là phần tạo doanh thu nên cần bảo vệ.
- **Nhãn hiệu**: đăng ký "GreenGate" (Cục Sở hữu trí tuệ, ~1-1,5 triệu đồng, 12-18 tháng) và
  ghi chính sách nhãn hiệu trong README: fork được, nhưng không được gọi là GreenGate.
- Thêm `LICENSE`, `NOTICE`, `DCO` (Developer Certificate of Origin, nhẹ hơn CLA) ngay từ commit
  đầu có người ngoài đóng góp.

Nếu bạn chỉ muốn một giấy phép duy nhất cho đơn giản: **Apache-2.0** nếu ưu tiên phổ cập trong
trường học, **AGPL-3.0** nếu ưu tiên giữ nguồn thu từ console. Không nên MIT.
