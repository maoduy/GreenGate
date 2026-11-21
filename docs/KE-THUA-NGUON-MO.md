# GreenGate – Kế thừa từ các dự án mã nguồn mở

Ghi lại những gì GreenGate nên mượn từ hệ sinh thái mở, kèm giấy phép và cách ghi công.
Nguyên tắc: **không đọ engine lọc** với các dự án đã chín (e2guardian, AdGuard Home); mượn
dữ liệu và ý tưởng của họ, dồn sức vào thứ GreenGate độc đáo (cấu hình qua Sheet/Drive, agent
đa nền tảng, relay quản lý từ xa, cài một nhấp, tiếng Việt).

Ngày lập: 03-11-2026.

## 1. Dữ liệu danh mục nên mượn

Mỗi danh sách giữ **giấy phép riêng**, không theo giấy phép code của GreenGate. Phải kiểm file
`LICENSE` trong repo gốc trước khi lấy (các trang tổng hợp mâu thuẫn nhau).

| Nguồn | Nội dung | Giấy phép (cần xác nhận) | Ưu tiên | Ghi chú |
|---|---|---|---|---|
| **UT1 Toulouse** (dsi.ut-capitole.fr/blacklists) | ~100 danh mục: người lớn, cờ bạc, ma tuý, bạo lực… hàng triệu tên miền | CC BY-SA 4.0 (có nơi ghi public domain) | ★★★ | **Chính là category DB** cho chế độ "chặn danh mục xấu". Mượn là khỏi tự xây |
| **StevenBlack hosts** | Quảng cáo, theo dõi, malware | MIT | ★★ | Dễ, cho phép thoải mái, hợp bản thương mại |
| **Hagezi DNS blocklists** | Nhiều mức chặn (nhẹ/vừa/mạnh), chất lượng cao | Kiểm LICENSE (nơi ghi MIT, nơi ghi GPL-3.0) | ★★ | Cho người dùng chọn mức độ |
| **abuse.ch URLhaus** | Tên miền lừa đảo / malware | Mở | ★ | Tăng phần an toàn, khác biệt với tool chỉ chặn nội dung xấu |

**Tránh:** OISD (gộp list không quan tâm giấy phép gốc, nhiều chỗ ghi "All rights reserved") →
không phân phối lại.

## 2. Ý tưởng thiết kế nên học (không vướng giấy phép)

| Từ dự án | Ý tưởng | Vì sao đáng |
|---|---|---|
| **e2guardian** | Chấm điểm cụm từ **có trọng số**: chặn khi tổng điểm vượt ngưỡng, không chặn/không-chặn nhị phân | Giảm chặn nhầm. Học cách tiếp cận, không copy code GPL |
| **AdGuard / EasyList** | Đọc được **cú pháp filter phổ biến** | Người dùng mang sẵn list của họ sang, không bị khoá vào định dạng riêng |
| **AdGuard Home** | Nhiều mức "parental control" chọn sẵn + DoH/DoT | Gợi ý cho bản "Cơ bản": cấu hình mặc định theo mức, phụ huynh không phải làm gì |
| **Portmaster** | Luật theo **ứng dụng** từng máy | Bổ trợ cho lọc web: chặn app lậu cả khi không qua trình duyệt |

## 3. Cách ghi công, ngắn gọn

1. **Tách dữ liệu khỏi code.** `blocklists/` là vùng riêng, có `blocklists/LICENSE` +
   `blocklists/CREDITS.md`; đừng để chung giấy phép Apache của code → copyleft dữ liệu không "lây"
   sang code.
2. **`blocklists/CREDITS.md`**, mỗi nguồn một dòng: tên, URL, giấy phép, ngày lấy.
3. **Danh sách phái sinh để CC BY-SA** nếu có trộn UT1 (BY-SA buộc share-alike). Code vẫn Apache.
4. **Script tự động ghi nguồn** mỗi khi kéo list về (nguồn + giấy phép + ngày + commit/hash).

## 4. Việc cần làm (checklist)

- [ ] Dựng `blocklists/CREDITS.md` + `blocklists/LICENSE` (CC BY-SA 4.0)
- [ ] Script `blocklists/fetch.sh` ghi lại nguồn/giấy phép/ngày mỗi lần cập nhật
- [ ] Nhập UT1 Toulouse → ánh xạ ~100 danh mục của họ sang danh mục GreenGate
- [ ] Nhập StevenBlack (ads/malware) + abuse.ch (phishing)
- [ ] Prototype chấm điểm cụm từ có trọng số trong `proxy/policy.py`
- [ ] Khảo sát đọc cú pháp filter kiểu AdGuard/EasyList
- [ ] Xác nhận giấy phép Hagezi trong file LICENSE gốc trước khi dùng

## 5. Nguồn tham khảo

- UT1 Toulouse: https://dsi.ut-capitole.fr/blacklists/
- StevenBlack hosts: https://github.com/StevenBlack/hosts
- Hagezi: https://github.com/hagezi/dns-blocklists
- abuse.ch URLhaus: https://urlhaus.abuse.ch/
- e2guardian: https://github.com/e2guardian/e2guardian
- GateSentry: https://github.com/fifthsegment/GateSentry
