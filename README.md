# Theo dõi độ chính xác dự báo nhiệt độ: Polymarket vs mô hình thời tiết

Hệ thống tự động, chạy miễn phí trên GitHub, mỗi ngày:

1. Chụp lại mọi thị trường **"Highest temperature in [thành phố] on [ngày]?"** đang mở trên Polymarket (xác suất từng mức nhiệt độ, bucket được định giá cao nhất, kỳ vọng °C).
2. Lấy dự báo Tmax cùng ngày, **tại đúng tọa độ trạm quan trắc dùng để phân giải thị trường**, từ 5 mô hình: ECMWF IFS, NOAA GFS, DWD ICON, UK Met Office, và best_match của Open-Meteo.
3. Khi ngày mục tiêu đã qua: tự lấy **bucket thắng cuộc theo chính Polymarket** + **nhiệt độ thực đo của trạm**, tính sai số cho từng nguồn.
4. Hiển thị tất cả trên dashboard web (bảng xếp hạng MAE, bias theo thành phố, tỉ lệ trúng bucket). Toàn bộ hiển thị bằng °C.

Sau 3–4 tuần, chạy `python analyze.py` để tìm pattern định giá lệch và (chỉ khi đạt ngưỡng thống kê) in khung kế hoạch test 100 USD.

---

## 1. Các quyết định thiết kế và lý do

Mọi cấu trúc dữ liệu dưới đây đã được **kiểm chứng bằng response thật** ngày 09/07/2026, không dựa trên giả định.

**Vì sao khám phá thị trường qua tag thay vì danh sách thành phố cứng?**
Polymarket gắn tag `Highest temperature` (id 104596) và `Daily Temperature` (id 103040) cho các event này. Hiện tại có Seoul, Hong Kong, Jinan, Trịnh Châu — nhưng danh sách thay đổi theo mùa (trước đây có cả thành phố Mỹ tính bằng °F). Quét theo tag + lọc tiêu đề bằng regex nghĩa là thành phố mới được bắt tự động, không cần sửa code. Giới hạn rate của Gamma API là 500 request/10 giây cho `/events` — một lần chạy của ta dùng vài request, không đáng kể.

**Vì sao lấy dự báo tại tọa độ trạm, không phải "thành phố"?**
Mỗi thị trường phân giải bằng MỘT trạm cụ thể ghi trong mô tả event. Ví dụ "Seoul" thực chất là **sân bay Incheon (RKSI)** — cách trung tâm Seoul ~50 km, sát biển. Hệ thống parse URL Wunderground trong `resolutionSource` để lấy mã ICAO, tra tọa độ + múi giờ trạm qua API của Iowa Environmental Mesonet (IEM), và cache vào `data/stations.json`.

**Vì sao "thực đo" phải lấy từ METAR trạm chứ không phải Open-Meteo?**
Đã kiểm chứng thực tế: ngày 07/07/2026 tại Incheon, phân tích lưới của Open-Meteo cho 24.8°C trong khi trạm METAR (nguồn Wunderground dùng để phân giải) ghi **30.0°C** — lệch hơn 5°C do hiệu ứng vị trí ven biển. Vì vậy thứ tự nguồn thực đo là:
1. **Bucket phân giải của chính Polymarket** (đọc từ `outcomePrices` khi market đóng — chân lý tuyệt đối về việc thị trường trả tiền cho ai);
2. **IEM METAR** (`mesonet.agron.iastate.edu`) — cùng dữ liệu gốc với Wunderground, miễn phí, có API JSON;
3. Với Hong Kong: nguồn phân giải là **Hong Kong Observatory** (không phải sân bay). API CLMMAXT chính thức công bố chậm, nên hệ thống thử CLMMAXT trước, chưa có thì dùng METAR sân bay VHHH làm proxy (ghi rõ trong cột `actual_source`);
4. Lưới Open-Meteo chỉ là phương án cuối và luôn bị đánh dấu `openmeteo_grid`.

**Vì sao lưu CSV commit thẳng vào repo?**
Đơn giản, bền vững, có version history miễn phí, dashboard tĩnh đọc trực tiếp được, và bạn xem được bằng Excel. Không cần database.

**Vì sao chạy 12:10 UTC và 00:10 UTC?**
12:10 UTC = tối hôm trước theo giờ các thành phố Đông Á — snapshot có **lead 1–2 ngày** (dự báo trước khi ngày diễn ra), là dữ liệu đúng để so sánh công bằng. 00:10 UTC chủ yếu để verify sớm các ngày vừa kết thúc. Cột `lead_days` ghi lại độ trễ, và mọi phân tích chỉ dùng lead ≥ 1.

**Đơn vị và độ chính xác:** thị trường °F (nếu xuất hiện lại) được quy đổi sang °C khi hiển thị; việc so bucket luôn làm ở đơn vị gốc. Seoul phân giải theo **độ nguyên** (làm tròn), Hong Kong theo **1 chữ số thập phân** (bucket 26°C = [26.0, 27.0)) — hệ thống đọc quy tắc này từ mô tả event.

**Giới hạn rate:** Open-Meteo miễn phí ~10.000 request/ngày (ta dùng < 20/ngày); Gamma API 500 req/10s; IEM không cần key. Đều dư địa rất lớn.

---

## 2. Cài đặt từng bước (chưa từng dùng GitHub cũng làm được)

**Bước 1 — Tạo tài khoản GitHub.** Vào [github.com](https://github.com), bấm **Sign up**, làm theo hướng dẫn (miễn phí).

**Bước 2 — Tạo repository (kho chứa code).**
1. Sau khi đăng nhập, bấm dấu **+** góc trên phải → **New repository**.
2. Đặt tên, ví dụ `temp-tracker`. Chọn **Public** (bắt buộc để có dashboard miễn phí).
3. Bấm **Create repository**.

**Bước 3 — Tải code lên.**
1. Trong trang repo vừa tạo, bấm **uploading an existing file**.
2. Kéo-thả TOÀN BỘ nội dung thư mục `polymarket-temp-tracker` này vào (gồm cả thư mục `data`).
   ⚠️ Thư mục `.github/workflows/daily.yml` là phần tự động hóa — trình duyệt đôi khi không kéo-thả được thư mục ẩn bắt đầu bằng dấu chấm. Nếu sau khi upload bạn không thấy thư mục `.github` trong repo: bấm **Add file → Create new file**, gõ đúng tên `.github/workflows/daily.yml` vào ô tên file, rồi dán nội dung file `daily.yml` vào và bấm **Commit changes**.
3. Bấm **Commit changes**.

**Bước 4 — Cho phép Actions ghi dữ liệu.**
1. Trong repo: **Settings → Actions → General**.
2. Kéo xuống **Workflow permissions**, chọn **Read and write permissions** → **Save**.

**Bước 5 — Chạy thử lần đầu.**
1. Vào tab **Actions** (nếu hỏi thì bấm nút enable/`I understand my workflows`).
2. Chọn workflow **"Thu thap du lieu nhiet do hang ngay"** → bấm **Run workflow** → **Run workflow**.
3. Chờ ~1 phút, biểu tượng chuyển xanh ✓ là thành công. Vào thư mục `data/` trong repo sẽ thấy `snapshots.csv` xuất hiện.

**Bước 6 — Bật dashboard.**
1. **Settings → Pages**.
2. Mục **Source**: chọn **Deploy from a branch**; Branch: **main**, thư mục **/(root)** → **Save**.
3. Sau 1–2 phút, dashboard sẽ ở địa chỉ: `https://<tên-tài-khoản>.github.io/<tên-repo>/`.

Từ đây hệ thống **tự chạy 2 lần mỗi ngày, không cần bật máy**. Không cần làm gì thêm.

> Lưu ý: GitHub đôi khi tự tắt lịch chạy nếu repo không có hoạt động nào trong 60 ngày — chỉ cần vào tab Actions bấm nút chạy tay một lần là bật lại.

---

## 3. Sau 3–4 tuần: phân tích pattern

Trên máy tính có Python (hoặc dùng GitHub Codespaces: bấm nút **Code → Codespaces → Create codespace** ngay trên repo, mở Terminal):

```
python analyze.py
```

Báo cáo trả lời đúng các câu hỏi nghiên cứu:
- Thành phố nào Polymarket sai nhiều nhất (MAE, tỉ lệ trúng bucket)?
- Sai theo hướng nào (bias dương = thị trường định giá nóng hơn thực tế)?
- Mô hình nào thắng Polymarket, ở thành phố nào, chênh bao nhiêu?

Script **tự từ chối đề xuất giao dịch** khi chưa đạt ngưỡng: n ≥ 15 quan sát lead ≥ 1, nhất quán hướng ≥ 70%, |bias| ≥ 1.0°C hoặc mô hình hơn Polymarket ≥ 15 điểm % tỉ lệ trúng bucket. Khi đạt ngưỡng, nó in khung test 100 USD: 10 lệnh × 10 USD, điều kiện vào lệnh cụ thể (giá ≤ 0.35, spread ≤ 0.05, thanh khoản ≥ 500 USD), quy tắc dừng (thua 5/10 lệnh đầu hoặc pattern tụt dưới 60% nhất quán), và nhắc tính phí taker ~5% của thị trường thời tiết.

**Quan trọng:** đây là công cụ nghiên cứu thống kê, không phải lời khuyên đầu tư. Thị trường nhiệt độ có người chơi chuyên nghiệp dùng chính các mô hình này; pattern tìm được có thể biến mất bất cứ lúc nào. Chỉ dùng số tiền chấp nhận mất toàn bộ, và kiểm tra quy định pháp lý về prediction market tại nơi bạn cư trú trước khi giao dịch.

---

## 4. Cấu trúc file

| File | Vai trò |
|---|---|
| `collect.py` | Chụp snapshot thị trường + dự báo 5 mô hình (chạy tự động) |
| `verify.py` | Đối chiếu ngày đã qua: bucket phân giải + thực đo trạm (chạy tự động) |
| `analyze.py` | Báo cáo pattern + khung test 100 USD (chạy tay sau 3–4 tuần) |
| `common.py` | Hàm dùng chung: parse bucket, quy đổi °F→°C, tra trạm, CSV |
| `index.html` | Dashboard (GitHub Pages tự phục vụ) |
| `.github/workflows/daily.yml` | Lịch chạy tự động 2 lần/ngày |
| `data/snapshots.csv` | Mỗi dòng = 1 event × 1 lần chụp (dữ liệu chính) |
| `data/snapshots_full.jsonl` | Vector xác suất đầy đủ của mọi bucket |
| `data/results.csv` | Kết quả phân giải + thực đo của từng event |
| `data/stations.json` | Cache tọa độ/múi giờ trạm quan trắc |

Nguồn dữ liệu: Polymarket Gamma API (công khai, không cần key) · [Weather data by Open-Meteo.com](https://open-meteo.com/) (CC BY 4.0) · Iowa Environmental Mesonet · Hong Kong Observatory.
