# -*- coding: utf-8 -*-
"""
paper_trade14.py — CHIẾN DỊCH 14: CHỈ phía NO, mở rộng luật CD9 thành
NHIỀU TẦNG theo độ cao đỉnh giá từng đạt. KHÔNG dùng tiền thật. Tiền ảo
$1500. Chỉ ngày T. Chạy trên VPS mỗi 2 phút. CD9 giữ nguyên luật cũ chạy
song song làm đối chứng — CD14 không thay thế, chỉ mở rộng thêm.

Ý TƯỞNG: CD9 chỉ có 1 tầng đỉnh (40-70%) với ngưỡng tuột cố định (20-29%/
10-19%). CD14 chia thành 3 TẦNG theo đỉnh, đỉnh càng cao thì ngưỡng vào
lệnh càng "rộng tay" (không cần đợi tuột quá sâu, vì đỉnh cao hơn tự nó
đã là tín hiệu mạnh hơn):

  - Tầng C — đỉnh từng đạt [40%, 50%): tuột xuống DƯỚI 32% mới vào (1 lệnh).
    Đỉnh thấp nên đòi hỏi tuột sâu hơn để chắc chắn không phải nhiễu.
  - Tầng B — đỉnh từng đạt [50%, 70%): tuột xuống DƯỚI 35% thì vào (1 lệnh).
  - Tầng A — đỉnh từng đạt >= 70%: 2 lệnh độc lập, không cần đợi cái này
    xong mới tới cái kia (nếu giá rớt rất nhanh, có thể vào cả 2 cùng lúc):
      + "Mất mốc 70": giá hiện tại <= 60% (phải tuột ĐỦ 10 điểm % dưới mốc
        70, không tính tuột nhẹ 1-2% là nhiễu) -> vào lệnh 1.
      + "Mất mốc 50": giá hiện tại <= 40% (cùng đệm 10 điểm % dưới mốc 50)
        -> vào lệnh 2.
    Đỉnh càng cao, mất mốc tròn số càng sớm đã là tín hiệu đám đông rút lui
    rõ ràng, nhưng cần đệm đủ sâu để không bắt nhầm dao động giá bình thường.

Mỗi (ô, nhãn tầng) chỉ mua 1 lần. 1 ô có thể nhận tối đa: 1 lệnh (tầng B
hoặc C) hoặc 2 lệnh (tầng A), tùy đỉnh nó từng đạt được.

CHƯA có backtest cho đúng cấu trúc nhiều tầng này — chiến dịch kiểm chứng
tiến cứu dựa trên giả thuyết hợp lý (mở rộng độ nhạy CD9 lên các đỉnh cao
hơn), không phải số liệu đã chứng minh.

v1 (18/07): bản đầu tiên.
Kết quả: data/trades14.csv | Lịch sử giá: data/cd14_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES14_CSV = C.DATA_DIR + "/trades14.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd14_price_hist.csv"

TRADE_FIELDS14 = [
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
# Nguong dinh cho tung tang (thap -> cao)
TIER_C_PEAK = (0.40, 0.50)   # dinh [40,50)
TIER_B_PEAK = (0.50, 0.70)   # dinh [50,70)
TIER_A_PEAK_MIN = 0.70       # dinh >=70
# Nguong gia vao lenh cho tung tang
TIER_C_TRIGGER = 0.32   # tang C: gia hien tai < 32%
TIER_B_TRIGGER = 0.35   # tang B: gia hien tai < 35%
TIER_A_MARK1 = 0.60     # tang A lenh 1: "mat moc 70" nhung phai tuot toi <=60%
                         # (dem 10 diem % duoi moc 70, tuot 1-2% la nhieu, khong tinh)
TIER_A_MARK2 = 0.40     # tang A lenh 2: "mat moc 50" phai tuot toi <=40% (dem 10%)
MIN_PRICE, MAX_PRICE = 0.02, 0.98
EXCLUDE_CITIES = {"los-angeles"}
FEE_RATE = 0.05
HIST_KEEP_DAYS = 3


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


def find_triggers(ask, peak):
    """Tra ve list nhan tang da kich hoat cho (ask, peak) hien tai."""
    labels = []
    if TIER_A_PEAK_MIN <= peak:
        if ask <= TIER_A_MARK1:
            labels.append("A-mat-moc-70")
        if ask <= TIER_A_MARK2:
            labels.append("A-mat-moc-50")
    elif TIER_B_PEAK[0] <= peak < TIER_B_PEAK[1]:
        if ask < TIER_B_TRIGGER:
            labels.append("B-duoi-35")
    elif TIER_C_PEAK[0] <= peak < TIER_C_PEAK[1]:
        if ask < TIER_C_TRIGGER:
            labels.append("C-duoi-32")
    return labels


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
                continue

            if prev_max is None or prev_max < TIER_C_PEAK[0]:
                continue

            for tlabel in find_triggers(ask, prev_max):
                key = (b["slug"], tlabel)
                if key in have_keys:
                    continue
                price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                candidates.append({
                    "event_slug": slug, "market_slug": b["slug"], "city": city,
                    "target_date": target, "bucket": b["label"], "tier": tlabel,
                    "price": price, "trigger_ask": ask, "peak_ask": prev_max,
                })

    save_price_hist(price_hist, today)

    order = {"A-mat-moc-50": 0, "A-mat-moc-70": 1, "B-duoi-35": 2, "C-duoi-32": 3}
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
            print("  [HET TIEN AO] (CD14) cho lenh cu chot da")
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
        print(f"  VAO LENH AO (CD14/NO {c['tier']}): {c['city']} {c['target_date']} "
              f"NO '{c['bucket']}' @{price} x{shares} co phan "
              f"(tung dat dinh {c['peak_ask']*100:.0f}%, gio con {c['trigger_ask']*100:.0f}% "
              f"| neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES14_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES14_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS14, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 14 v1 — chi NO, 3 tang theo dinh: 40-50%->duoi32 | 50-70%->duoi35 | >=70%->mat moc 70/50]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
