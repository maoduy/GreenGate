# GreenGate

Bộ lọc Internet cho gia đình. Phụ huynh quản lý mọi thiết bị của con bằng **một Google Sheet** và
**một ứng dụng web** trên điện thoại; không có máy chủ nào giữ dữ liệu của con.

- **Hai cách lọc**, đổi bằng một ô trong Sheet: *chỉ cho phép danh sách* (kể cả kênh YouTube) hoặc
  *cho phép tất cả, chặn danh sách + danh mục xấu + từ khoá*.
- **Chạy trên Windows, Linux, Android.** Bộ cài `.exe`, gói `.deb`, file `.apk`.
- **Thay đổi trên Sheet có hiệu lực trong ≤ 60 giây**, hoặc tức thì khi nhấn "Cập nhật ngay".
- **Chụp màn hình, xem lịch sử từ xa** qua relay mã hoá đầu-cuối; máy tắt thì lệnh chờ tới khi mở.
- **Ảnh màn hình theo lịch lên Google Drive của bố mẹ** (mặc định 15 phút, có thông báo cho con, cần
  bố mẹ và con cùng đồng ý; không cần tài khoản Google Cloud) – xem [drive/README.md](drive/README.md).
- **Sửa Sheet → máy con biết ngay**: Apps Script của Sheet báo relay, relay nhắc máy con đọc lại (1–5 s).
- Giới hạn phút/ngày, khung giờ theo trang và theo ứng dụng, SafeSearch, YouTube Restricted Mode, chặn Shorts.

Tài liệu: [PRD](docs/PRD.md) · [Đặc tả kỹ thuật](docs/SPEC.md) · [Báo cáo đo đạc](docs/REPORT.md) ·
[Relay](server/README.md) · [Ứng dụng phụ huynh](parent-app/README.md) · [Android](android/README.md) ·
[Agent](agent/README.md) · [Proxy (Windows)](proxy/README.md)

## Cài đặt nhanh

| Nền tảng | Cách cài | Ghi chú |
|---|---|---|
| Windows 10/11 | Tải `GreenGate-Setup.zip` ở [Releases](../../releases), giải nén, chạy `GreenGate-Setup.exe` bằng tài khoản quản trị, dán link Google Sheet | Tài khoản của con phải là tài khoản thường. |
| Linux (Ubuntu/Debian) | `sudo apt install ./greengate_2.0.0_all.deb` rồi `sudo greengate-setup --sheet <link> --users <tài khoản con>` | Lệnh `greengate status / update / pause / pair`. |
| Android 11+ | Cài `GreenGate-<ver>.apk`, cấp quyền VPN, Trợ năng, Quản trị thiết bị theo hướng dẫn trong app | Lọc theo tên miền (DNS), chặn app, chụp màn hình. |

Mẫu Google Sheet: tạo bảng tính mới với các tab `websites`, `youtube`, `blocked`, `apps`, `settings`
(xem [SPEC §1–2](docs/SPEC.md)) và chia sẻ "Bất kỳ ai có liên kết: Người xem".

## Google Sheet điều khiển gì

| Tab | Nội dung |
|---|---|
| `websites` | Trang được phép (hoặc có giới hạn): cột A trang, C phút/ngày, D khung giờ. Dòng `*` = tổng thời gian/ngày. |
| `youtube` | Kênh YouTube được phép (`@handle`, id hoặc link). |
| `blocked` | Luôn chặn (tên miền hoặc đường dẫn). |
| `apps` | Ứng dụng chặn/giới hạn (`roblox.exe`, `com.google.android.youtube`). |
| `settings` | `mode`, `categories`, `keywords`, `safesearch`, `youtube`, `shorts`, `schedule`, `refreshSeconds`, `screenshotEvery` (15), `screenshotHours`, `uploadUrl`, `driveFolder`, `retentionDays`, `blockPage`, `deepInspect` (on; `off` = site đã liệt kê đi thẳng, nhanh hơn). |

Danh mục chặn (`adult`, `gambling`, `drugs`, `weapons`, `violence`, `malware`, `bypass`, `dating`,
`social`, `games`, `piracy`, `ads`) được biên dịch mỗi ngày từ Blocklist Project, HaGeZi và UT1 và
phát hành tại release [`lists`](../../releases/tag/lists).

## Cấu trúc kho

| Thư mục | Vai trò |
|---|---|
| `proxy/` | Addon mitmproxy (`greengate.py`, `policy.py`, `timewindow.py`) + script cài Windows |
| `setup/` | Bộ cài Windows có giao diện (`GreenGate-Setup.exe`) |
| `linux/` | Cài đặt Linux: systemd, nftables theo uid, `.deb`, lệnh `greengate` |
| `agent/` | Agent chụp màn hình / lịch sử / chặn app (Windows, Linux) |
| `server/` | Relay Cloudflare Worker + Durable Object (chỉ chuyển gói đã mã hoá) |
| `parent-app/` | PWA cho phụ huynh (ghép đôi, chụp màn hình, lịch sử, cập nhật ngay) |
| `android/` | App Android (VpnService DNS, AccessibilityService, Device Admin) |
| `blocklists/` | Nguồn và trình biên dịch danh mục chặn |
| `drive/` | Apps Script nhận ảnh màn hình vào Drive của bố mẹ + báo relay khi Sheet đổi, kèm hướng dẫn |
| `test/` | Test đơn vị, Playwright, đo độ trễ, test Docker Linux |
| `extension/`, `build.js`, `keys/` | Phiên bản cũ (tiện ích mở rộng Edge/Chrome), giữ để tham chiếu |
| `.github/workflows/` | CI: test Windows (matrix), test Linux, build Setup.exe + Agent.exe, build danh mục |

## Phát triển

```bash
# test đơn vị (chính sách, khung giờ)
python3 test/policy_test.py && python3 test/timewindow_test.py
# proxy cục bộ với một Sheet
.venv-proxy/bin/mitmdump -p 8080 -s proxy/greengate.py --set greengate_sheet=<id>
# đo độ trễ Chrome trực tiếp vs qua proxy
node test/latency.js --proxy http://127.0.0.1:8080 --runs 10
# test tích hợp Linux trong Docker
bash test/linux-docker.sh
# relay cục bộ + e2e
cd server && npm i && npx wrangler dev --port 8787 & node server/test/e2e.mjs
```

## Việc cần chủ dự án làm trước khi dùng thật

1. Deploy relay: `cd server && npx wrangler login && npx wrangler deploy`, rồi điền URL vào
   `setup/greengate_setup.py` (`DEFAULT_RELAY`) và `parent-app/app.js`.
2. Đưa `parent-app/` lên GitHub Pages (hoặc bất kỳ hosting tĩnh nào).
3. Cài Apps Script vào Sheet (3 phút, `drive/README.md`) để nhận ảnh định kỳ và để máy con cập nhật ngay khi bạn sửa Sheet.
4. (Tuỳ chọn) Google OAuth client để sửa Sheet ngay trong app phụ huynh.

Giấy phép: MIT.
