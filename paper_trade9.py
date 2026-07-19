# -*- coding: utf-8 -*-
"""
paper_trade9.py — CHIẾN DỊCH 9: theo đám đông ở 2 đầu, CHỈ trong ngày mục
tiêu là hôm nay (ngày T), quét liên tục mỗi 30 phút. Tiền ảo $1500.
KHÔNG dùng tiền thật. Chạy ĐỘC LẬP bằng workflow riêng (cd9.yml).

Cơ sở: favorite-longshot bias — đám đông thường trả THIẾU cho cửa nặng ký
(favorite) và trả THỪA cho cửa nhẹ ký (longshot).

=== LỊCH SỬ SỬA LUẬT (đọc để hiểu vì sao code như hiện tại) ===
v1 (17/07 sáng): fade NO khi giá >=70c, mọi ngày tương lai. Bị lỗi: vào cả
  market của HÔM NAY, giá gần 100% chỉ vì ngày sắp hết chứ không phải "quá tự
  tin" thật — 32 lệnh cực đoan, x10000 đòn bẩy, ăn 335$ trong 1 lần quét.
v2: sửa bằng cách LOẠI market hôm nay (target > today), thêm chặn giá
  [0.02, 0.98]. Deploy ổn.
v3: nâng cấp 3 mốc NO 50/60/70 riêng biệt — bị thay trước khi deploy.
v4 (17/07 chiều, đã chạy live): 2 phía —
    YES: ô >=60c mua 1 lần, >=70c mua thêm 1 lần (tối đa 2 lệnh/ô), mọi
         ngày tương lai (KHÔNG gồm hôm nay).
    NO:  ô bất kỳ rơi vào [0.10, 0.20] mua 1 lần, mọi ngày tương lai.
  Kết quả thực tế: phía NO bắn ra ồ ạt (121 lệnh mở/1 lần quét, ăn gần hết
  $1500) vì hầu như thị trường nào cũng có vài ô "vai" nằm sẵn trong dải
  10-20c ngay từ đầu — không phải tín hiệu "đám đông vừa đổi ý", chỉ là ô đó
  vốn dĩ đã là longshot.
v5 (17/07) — thu hẹp lại có chủ đích:
    - CHỈ xét market có target_date == HÔM NAY (ngày T) — cho CẢ 2 phía.
      (Đây là đổi ngược lại so với v4, chấp nhận rủi ro giá cực đoan cuối
      ngày đã nêu ở v1, nhưng bù lại bằng: vẫn giữ chặn [0.02,0.98], và
      luật NO giờ đòi hỏi lịch sử giá cụ thể chứ không chỉ "giá đang thấp".)
    - PHÍA YES: ô >=60c mua 1 lần, >=70c mua thêm 1 lần (mốc rời rạc).
    - PHÍA NO: THAY HẲN luật cũ. Không còn ngưỡng cố định 10-20c. Giờ chỉ
      mua NO khi ô đó TỪNG đạt đỉnh giá trong khoảng [0.40, 0.70] ở một lần
      quét trước đó, RỒI SAU ĐÓ tuột xuống dưới 0.40 — tức đám đông từng coi
      là ứng viên nghiêm túc rồi rút lui, không phải vốn dĩ đã là longshot.
      Cần bộ nhớ giá đỉnh từng thấy mỗi ô -> lưu riêng data/cd9_price_hist.csv,
      cập nhật MỌI lần quét cho MỌI market (không giới hạn ngày) để có đủ
      lịch sử ngay khi market bước vào ngày T.
  Lỗi phát sinh: 2 mốc 60/70 độc lập nên nếu 1 ô mới thấy lần đầu đã ở giá
  74c, bot mua CẢ 2 mốc cùng lúc (vì 74>=60 VÀ 74>=70) — ra 2 lệnh cho cùng
  1 ô ngay trong 1 lần quét (vd Madrid). Không đúng ý muốn "mỗi khoảng giá
  chỉ mua 1 lần".
v6 (17/07) — PHÍA YES đổi từ "mốc rời rạc" sang "khoảng giá",
  mỗi khoảng chỉ mua ĐÚNG 1 LẦN/ô bất kể quét bao nhiêu lần hay giá nhích
  bao nhiêu trong khoảng đó: [60,70) mua 1 lần, [70,80) mua 1 lần,
  [80,90) mua 1 lần, [90,97] mua 1 lần (tối đa 4 lệnh/ô nếu giá leo hết
  các khoảng qua nhiều lần quét). PHÍA NO không đổi.
v7 (17/07) — PHÍA NO thêm 1 điều kiện: phải tuột cách đỉnh từng
  đạt ÍT NHẤT 5 điểm % (không chỉ cần <40c). Lý do: ô Mexico City đỉnh vừa
  chạm 40% rồi tuột còn 39% đã kích hoạt mua NO — tuột 1 điểm % gần như
  không có ý nghĩa gì (nhiễu bình thường), không phải tín hiệu "đám đông
  đổi ý" thật sự. Giờ ví dụ đỉnh 40% phải tuột về 35% trở xuống mới mua.
v8 (18/07) — PHÍA NO thêm 1 sàn: giá sau khi tuột phải CÒN TRÊN
  10% (chỉ nhận khoảng 10%<giá<40%). Dưới 10% coi như đã gần chắc chắn bị
  loại, mua NO lúc đó gần như không còn lời (giá NO đã quá cao, gần $1),
  không đáng bù rủi ro/phí — bỏ qua để tiết kiệm ngân sách cho tín hiệu
  còn giá trị hơn.
v9 (18/07, ĐANG DÙNG) — PHÍA NO đổi từ "1 lần duy nhất khi tuột <40c" sang
  KHOẢNG GIÁ giống hệt PHÍA YES: sau khi từng đạt đỉnh 40-70c, giá tuột qua
  khoảng [20,30) mua NO 1 lần, tuột tiếp qua khoảng [10,20) mua thêm NO
  1 lần nữa (tối đa 2 lệnh/ô cho phía NO). Lý do: "chỉ cần tuột" quá dễ xảy
  ra, không phân biệt được mức độ — chia khoảng giúp bot mua thêm khi tín
  hiệu càng lúc càng mạnh (giá càng rớt sâu), giống cách phía YES mua thêm
  khi giá càng lúc càng cao. Đã bỏ NO_MIN_DROP_GAP/NO_DROP_FLOOR (2 khoảng
  20-29c/10-19c đã tự nhiên đảm bảo cách đỉnh 40-70 ít nhất 10 điểm % và có
  sàn 10% sẵn trong định nghĩa khoảng).
v9.1 (18/07) — loại thị trường Los Angeles theo yêu cầu (EXCLUDE_CITIES).
v9.2 (18/07) — PHÍA YES thêm 1 chặn: nếu 1 ô ĐÃ mua ở CẢ 2 khoảng 70-79c
  VÀ 80-89c (tức giá đã leo nhanh, đám đông cực kỳ tự tin) thì KHÔNG mua
  thêm ở khoảng 90-97c nữa. Lý do: ca Madrid 35°C leo 60-69 -> 80-89 -> 90-97
  (3 lệnh chồng cùng 1 ô) rồi sụp về 0% — mốc 90-97 vừa đắt nhất (lời tiềm
  năng thấp nhất) vừa là lệnh chồng thêm rủi ro lên 1 ô đã cược 2 lần rồi,
  không giúp tăng thêm gì đáng kể ngoài rủi ro tập trung.
Đây là chiến dịch THỬ NGHIỆM, CHƯA có backtest lịch sử — theo dõi khách
quan, không kết luận sớm, không chỉnh luật giữa chừng nếu không có lý do.

*** NOTE 19/07: GIỮ LẠI TEST THÊM 2 NGÀY (đến hết 21/07) rồi đánh giá.
Số liệu đến 19/07 (159 lệnh chốt): NO thắng 93.2% (41/44), LỜI +39.48$ —
phía duy nhất toàn hệ thống vượt ngưỡng hòa vốn rõ. YES thắng 73% nhưng
lỗ -90.85$, thủ phạm chính là khoảng 60-69c (thắng 51.4%, lỗ -68$).
Hướng sau 21/07: cân nhắc bỏ khoảng YES 60-69c, giữ nguyên phía NO. ***
Kết quả: data/trades9.csv | Lịch sử giá: data/cd9_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES9_CSV = C.DATA_DIR + "/trades9.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd9_price_hist.csv"

TRADE_FIELDS9 = [
    "entry_utc", "event_slug", "market_slug", "city", "target_date",
    "side", "bucket", "tier", "price", "shares", "stake", "fee",
    "trigger_ask", "peak_ask", "potential_profit", "status", "payout", "pnl", "settle_utc",
]
PRICE_HIST_FIELDS = [
    "market_slug", "event_slug", "city", "target_date",
    "first_seen_utc", "max_ask", "last_ask", "last_scan_utc",
]

BUDGET = 1500.0
STAKE = 10.0
# PHIA YES: khoang gia, moi khoang mua DUNG 1 LAN/o bat ke quet may lan hay
# gia nhich bao nhieu trong khoang do. [lo, hi) tru khoang cuoi la [lo, hi].
YES_RANGES = [(0.60, 0.70, "60-69c"), (0.70, 0.80, "70-79c"),
              (0.80, 0.90, "80-89c"), (0.90, 0.97, "90-97c")]
NO_PEAK_LOW, NO_PEAK_HIGH = 0.40, 0.70  # dinh gia tung dat de duoc tinh la "ung vien that su"
# PHIA NO: sau khi dat dinh 40-70c, gia phai TUOT QUA cac khoang duoi day.
# Giong YES: moi khoang mua DUNG 1 LAN/o. [lo, hi) tru khoang cuoi la [lo, hi].
NO_DROP_RANGES = [(0.20, 0.30, "20-29c"), (0.10, 0.20, "10-19c")]
MIN_PRICE, MAX_PRICE = 0.02, 0.98  # loai gia cuc doan (don bay vo ly)
EXCLUDE_CITIES = {"los-angeles"}  # v9.1: bo hoan toan thi truong nay
FEE_RATE = 0.05
HIST_KEEP_DAYS = 3  # don rac: bo entry lich su cu hon x ngay so voi target_date


def _range_label(ask, ranges):
    """Tra ve nhan khoang gia ma ask dang roi vao trong danh sach ranges, hoac None."""
    for i, (lo, hi, label) in enumerate(ranges):
        if i == len(ranges) - 1:
            if lo <= ask <= hi:
                return label
        else:
            if lo <= ask < hi:
                return label
    return None


def yes_range_label(ask):
    return _range_label(ask, YES_RANGES)


def no_drop_range_label(ask):
    return _range_label(ask, NO_DROP_RANGES)


def parse_buckets(event):
    out = []
    for mk in event.get("markets", []):
        b = C.parse_bucket(mk.get("groupItemTitle"))
        if b is None:
            continue
        if mk.get("closed") or not mk.get("active"):
            continue
        ask = mk.get("bestAsk")
        bid = mk.get("bestBid")
        out.append({
            "label": C.bucket_label(b),
            "slug": mk.get("slug"),
            "ask": float(ask) if ask is not None else None,
            "bid": float(bid) if bid is not None else None,
        })
    return out


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def settle(trades):
    """Chot lenh dua vao data/results.csv (verify.py sinh ra, dung chung
    voi cac chien dich thoi tiet khac)."""
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for t in trades:
        if t["status"] != "open":
            continue
        r = results.get(t["event_slug"])
        if not r or not r.get("resolved_bucket"):
            continue
        rb = r["resolved_bucket"]
        stake, fee, shares = float(t["stake"]), float(t["fee"]), float(t["shares"])
        side = (t.get("side") or "NO").upper()
        if rb == "UNRESOLVED":
            t["status"], t["payout"], t["pnl"] = "void", stake, 0.0
        else:
            hit = (rb == t["bucket"])
            win = hit if side == "YES" else (not hit)
            if win:
                payout = shares * 1.0
                t["status"], t["payout"] = "won", round(payout, 2)
                t["pnl"] = round(payout - stake - fee, 2)
            else:
                t["status"], t["payout"] = "lost", 0.0
                t["pnl"] = round(-(stake + fee), 2)
        t["settle_utc"] = now
        n += 1
    return n


def load_price_hist():
    return {r["market_slug"]: r for r in C.read_csv(PRICE_HIST_CSV) if r.get("market_slug")}


def save_price_hist(hist, today):
    rows = []
    for r in hist.values():
        td = r.get("target_date") or ""
        try:
            if td and (C.parse_iso_date(today) - C.parse_iso_date(td)).days > HIST_KEEP_DAYS:
                continue  # don rac market da qua han lau
        except Exception:  # noqa: BLE001
            pass
        rows.append(r)
    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(PRICE_HIST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRICE_HIST_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _mk_candidate(ev_slug, city, target, b, side, tier_label, price, trigger_ask, peak_ask):
    return {
        "event_slug": ev_slug, "market_slug": b["slug"], "city": city,
        "target_date": target, "bucket": b["label"], "side": side,
        "tier": tier_label, "price": price, "trigger_ask": trigger_ask,
        "peak_ask": peak_ask,
    }


def enter(trades, now, events=None, price_hist=None):
    have_keys = {(t["market_slug"], (t.get("side") or "").upper(), str(t.get("tier") or ""))
                 for t in trades}
    today = now[:10]
    if events is None:
        events = collect.fetch_temperature_events()
    if price_hist is None:
        price_hist = load_price_hist()

    candidates = []
    for ev in events:
        slug = ev.get("slug", "")
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target:
            continue
        if city in EXCLUDE_CITIES:
            continue  # v9.1: bo qua thi truong bi loai
        is_today = (target == today)

        for b in parse_buckets(ev):
            if not b["slug"] or b["ask"] is None:
                continue
            ask = b["ask"]

            # --- cap nhat lich su gia CHO MOI market (khong gioi han ngay) ---
            h = price_hist.get(b["slug"])
            prev_max = float(h["max_ask"]) if h else None
            if h is None:
                price_hist[b["slug"]] = {
                    "market_slug": b["slug"], "event_slug": slug, "city": city,
                    "target_date": target, "first_seen_utc": now,
                    "max_ask": ask, "last_ask": ask, "last_scan_utc": now,
                }
            else:
                h["max_ask"] = max(prev_max, ask)
                h["last_ask"] = ask
                h["last_scan_utc"] = now

            if not is_today:
                continue  # chi VAO LENH khi target_date == hom nay (ca 2 phia)

            # --- PHIA YES: theo cua nang ky, khoang gia, 1 lan/khoang/o, chi ngay T ---
            rlabel = yes_range_label(ask)
            if rlabel is not None:
                # v9.2: da mua ca 70-79c va 80-89c roi thi khong mua them 90-97c
                # (gia leo qua nhanh -> da chong 2 lenh, mua them chi tang rui ro
                # tap trung ma loi tiem nang lai thap nhat trong 4 khoang)
                skip_top = (
                    rlabel == "90-97c"
                    and (b["slug"], "YES", "70-79c") in have_keys
                    and (b["slug"], "YES", "80-89c") in have_keys
                )
                key = (b["slug"], "YES", rlabel)
                if key not in have_keys and not skip_top:
                    price = round(ask, 3)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        candidates.append(_mk_candidate(
                            slug, city, target, b, "YES", rlabel, price, ask, ask))

            # --- PHIA NO: tung la ung vien that su (dinh 40-70c), roi TUOT QUA tung
            # khoang gia [20,30) va [10,20), moi khoang mua DUNG 1 LAN/o (giong YES) ---
            if prev_max is not None and NO_PEAK_LOW <= prev_max <= NO_PEAK_HIGH:
                dlabel = no_drop_range_label(ask)
                if dlabel is not None:
                    key = (b["slug"], "NO", dlabel)
                    if key not in have_keys:
                        price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                        if MIN_PRICE <= price <= MAX_PRICE:
                            candidates.append(_mk_candidate(
                                slug, city, target, b, "NO", dlabel, price, ask, prev_max))

    save_price_hist(price_hist, today)

    # tin hieu manh hon vao truoc khi het tien ao: YES 90-97>80-89>70-79>60-69, roi NO 10-19>20-29
    order = {("YES", "90-97c"): 0, ("YES", "80-89c"): 1, ("YES", "70-79c"): 2,
             ("YES", "60-69c"): 3, ("NO", "10-19c"): 4, ("NO", "20-29c"): 5}
    candidates.sort(key=lambda x: order.get((x["side"], str(x["tier"])), 9))
    added = 0
    for c in candidates:
        key = (c["market_slug"], c["side"], str(c["tier"]))
        if key in have_keys:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - STAKE - fee, 2)  # neu thang
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD9) cho lenh cu chot da")
            break
        if c["side"] == "YES":
            tier_txt = c["tier"]  # da la nhan khoang gia san, vd "60-79c"
            info = f"dam dong dang tin {c['trigger_ask']*100:.0f}%"
        else:
            tier_txt = c["tier"]  # da la nhan khoang gia san, vd "20-29c"
            info = f"tung dat dinh {c['peak_ask']*100:.0f}%, gio con {c['trigger_ask']*100:.0f}%"
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": c["side"],
            "bucket": c["bucket"], "tier": c["tier"], "price": price, "shares": shares,
            "stake": STAKE, "fee": fee, "trigger_ask": c["trigger_ask"],
            "peak_ask": c["peak_ask"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_keys.add(key)
        print(f"  VAO LENH AO (CD9/{c['side']} {tier_txt}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} co phan "
              f"({info} | neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES9_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES9_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS9, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 9 v9.2 — chi ngay T: YES 4 khoang 60-69/70-79/80-89/90-97c (bo 90-97c neu da co ca 70-79+80-89) + NO (sau dinh 40-70c) 2 khoang 20-29/10-19c]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
