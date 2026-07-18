# -*- coding: utf-8 -*-
"""
paper_trade13.py — CHIẾN DỊCH 13: CHỈ phía NO, bắt "hàng nặng ký sụp đổ".
KHÔNG dùng tiền thật. Tiền ảo $1500. Chỉ ngày T. Chạy trên VPS mỗi 2 phút.

KHÁC CD9 Ở CHỖ: CD9 phía NO bắt ô từng là "ứng viên vừa phải" (đỉnh 40-70%)
rồi rút lui — tín hiệu nhẹ, xảy ra thường xuyên. CD13 bắt ô từng là "gần như
chắc chắn" (đỉnh >=80%, đám đông cực kỳ tự tin) rồi SỤP hẳn xuống ~15% — tín
hiệu hiếm hơn nhưng mạnh hơn nhiều lần: một ô đã được định giá gần như thắng
mà bị bỏ rơi thường phản ánh tin tức/dữ liệu mới rất rõ ràng (vd dự báo đổi
đột ngột), không phải nhiễu thông thường.

  - Chỉ MUA NO, không có phía YES.
  - Điều kiện: ô từng đạt đỉnh giá >= 80% (NO_PEAK_MIN) ở 1 lần quét trước đó.
  - Sau đó giá tuột qua khoảng [10,20)% mua NO 1 lần ("tuột về ~15%"), tuột
    tiếp qua khoảng [2,10)% mua thêm NO 1 lần nữa (tín hiệu càng mạnh khi
    càng rớt sâu, giống cách CD9/CD11 mua thêm theo khoảng).
  - Chỉ market có target_date == hôm nay (ngày T). $10/lệnh, phí 5%.

CHƯA có backtest lịch sử cho đúng luật đỉnh>=80% này (khác điều kiện đỉnh
40-70% đã test ở CD9/CD11) — đây là chiến dịch kiểm chứng tiến cứu dựa trên
giả thuyết hợp lý, không phải số liệu đã chứng minh. Theo dõi khách quan.

v1 (18/07): bản đầu tiên.
Kết quả: data/trades13.csv | Lịch sử giá: data/cd13_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES13_CSV = C.DATA_DIR + "/trades13.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd13_price_hist.csv"

TRADE_FIELDS13 = [
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
NO_PEAK_MIN = 0.80  # dinh gia tung dat toi thieu de tinh la "hang nang ky"
# Sau khi dat dinh >=80%, gia phai TUOT QUA cac khoang duoi day.
# Moi khoang mua DUNG 1 LAN/o. [lo, hi) tru khoang cuoi la [lo, hi].
NO_DROP_RANGES = [(0.10, 0.20, "10-19c"), (0.02, 0.10, "02-09c")]
MIN_PRICE, MAX_PRICE = 0.02, 0.98
EXCLUDE_CITIES = {"los-angeles"}
FEE_RATE = 0.05
HIST_KEEP_DAYS = 3


def _range_label(ask, ranges):
    for i, (lo, hi, label) in enumerate(ranges):
        if i == len(ranges) - 1:
            if lo <= ask <= hi:
                return label
        else:
            if lo <= ask < hi:
                return label
    return None


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
        if rb == "UNRESOLVED":
            t["status"], t["payout"], t["pnl"] = "void", stake, 0.0
        else:
            hit = (rb == t["bucket"])
            win = not hit  # chi co NO
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
                continue
        except Exception:  # noqa: BLE001
            pass
        rows.append(r)
    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(PRICE_HIST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRICE_HIST_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def enter(trades, now, events=None, price_hist=None):
    have_keys = {(t["market_slug"], str(t.get("tier") or "")) for t in trades}
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
            continue
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
                continue  # chi VAO LENH khi target_date == hom nay

            # --- CHI PHIA NO: tung dat dinh >=80%, roi TUOT QUA cac khoang gia ---
            if prev_max is not None and prev_max >= NO_PEAK_MIN:
                dlabel = no_drop_range_label(ask)
                if dlabel is not None:
                    key = (b["slug"], dlabel)
                    if key not in have_keys:
                        price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                        if MIN_PRICE <= price <= MAX_PRICE:
                            candidates.append({
                                "event_slug": slug, "market_slug": b["slug"], "city": city,
                                "target_date": target, "bucket": b["label"], "tier": dlabel,
                                "price": price, "trigger_ask": ask, "peak_ask": prev_max,
                            })

    save_price_hist(price_hist, today)

    order = {"02-09c": 0, "10-19c": 1}  # rot cang sau, tin hieu cang manh, vao truoc
    candidates.sort(key=lambda x: order.get(str(x["tier"]), 9))
    added = 0
    for c in candidates:
        key = (c["market_slug"], str(c["tier"]))
        if key in have_keys:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - STAKE - fee, 2)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD13) cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": "NO",
            "bucket": c["bucket"], "tier": c["tier"], "price": price, "shares": shares,
            "stake": STAKE, "fee": fee, "trigger_ask": c["trigger_ask"],
            "peak_ask": c["peak_ask"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_keys.add(key)
        print(f"  VAO LENH AO (CD13/NO {c['tier']}): {c['city']} {c['target_date']} "
              f"NO '{c['bucket']}' @{price} x{shares} co phan "
              f"(tung dat dinh {c['peak_ask']*100:.0f}%, gio con {c['trigger_ask']*100:.0f}% "
              f"| neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES13_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES13_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS13, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 13 v1 — chi NO: dinh tung dat >=80% roi tuot qua 10-19%/2-9%, chi ngay T]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
