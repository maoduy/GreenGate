# GreenGate parent app (PWA)

Static files, no build step: `index.html`, `app.js`, `style.css`, `sw.js`, `manifest.webmanifest`, `icon.svg`.
Crypto: tweetnacl 1.0.3 from cdnjs (pinned, SRI). Keys live in IndexedDB; devices and the relay URL
in localStorage. Everything from a device is decrypted in the browser.

Host it anywhere static (GitHub Pages: copy this folder to `docs/app/`). Local test:
`python3 -m http.server 8790` in this folder, then open http://127.0.0.1:8790/index.html.

Screens: Thiết bị (online/offline), Thêm máy (6-digit code or QR via BarcodeDetector), device page
(Chụp màn hình, Lịch sử tháng này, Cập nhật danh sách ngay, Tạm dừng 30 phút, Tiếp tục, Trạng thái,
each with a timing breakdown), Cài đặt (reads the sheet tabs through the public gviz CSV endpoint,
read-only), Khoá (export/import recovery code).

TODO (needs the project owner): editing the sheet from the app requires a Google OAuth client ID
(Web application, scope `https://www.googleapis.com/auth/spreadsheets`) created in Google Cloud
Console; then `app.js` can use Google Identity Services to write cells. Until then the app links to
the sheet.

End-to-end test with a real agent: `node parent-app/test/e2e-parent.mjs` (see `docs/relay-report.md`).
