# -*- coding: utf-8 -*-
"""
paper_trade11.py — CHIẾN DỊCH 11: bản tinh gọn của CD9 theo backtest 8 ngày.
KHÔNG dùng tiền thật. Tiền ảo $1500. Chỉ ngày T. Chạy trên VPS mỗi 2 phút.

KHÁC CD9 DUY NHẤT Ở PHÍA YES: backtest 09-17/07 cho thấy mua YES ô đám đông
tin nhất chỉ LỜI THẬT ở 2 khoảng giá 65-75c (93% thắng) và 85-97c (100%
thắng), còn khoảng giữa 75-85c LỖ ("tự tin nhưng chưa chắc chắn" — vùng dễ
sai nhất). CD9 mua cả 4 bậc 60-97c nên 1 ô sai leo đủ thang mất ~40$;
CD11 chỉ mua 2 khoảng đã kiểm chứng, lỗ tối đa/ô phía YES còn ~20$.

  - YES: giá vào khoảng [0.65, 0.75) mua 1 lần/ô, [0.85, 0.97] mua 1 lần/ô.
  - NO : giữ nguyên v9 của CD9 — ô từng đạt đỉnh 40-70c rồi tuột qua
         [0.20, 0.30) mua 1 lần, tuột tiếp qua [0.10, 0.20) mua thêm 1 lần.
  - Chỉ market có target_date == hôm nay. Loại Los Angeles. $10/lệnh, phí 5%.

v1 (18/07): bản đầu tiên, tách từ CD9 v9.1 để so sánh song song — CD9 giữ
nguyên luật cũ làm nhóm đối chứng.
Kết quả: data/trades11.csv | Lịch sử giá: data/cd11_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES11_CSV = C.DATA_DIR + "/trades11.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd11_price_hist.csv"

TRADE_FIELDS11 = [
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
# PHIA YES: CHI 2 khoang gia da kiem chung bang backtest. [lo, hi) tru khoang cuoi [lo, hi].
YES_RANGES = [(0.65, 0.75, "65-74c"), (0.85, 0.97, "85-97c")]
NO_PEAK_LOW, NO_PEAK_HIGH = 0.40, 0.70  # dinh gia tung dat de tinh la "ung vien that su"
# PHIA NO: giu nguyen v9 cua CD9.
NO_DROP_RANGES = [(0.20, 0.30, "20-29c"), (0.10, 0.20, "10-19c")]
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
    """Chot lenh dua vao data/results.csv (dung chung voi cac chien dich khac)."""
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
                continue
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
                continue  # chi VAO LENH khi target_date == hom nay (ca 2 phia)

            # --- PHIA YES: chi 2 khoang gia da kiem chung, 1 lan/khoang/o ---
            rlabel = yes_range_label(ask)
            if rlabel is not None:
                key = (b["slug"], "YES", rlabel)
                if key not in have_keys:
                    price = round(ask, 3)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        candidates.append(_mk_candidate(
                            slug, city, target, b, "YES", rlabel, price, ask, ask))

            # --- PHIA NO: giu nguyen v9 — dinh 40-70c roi tuot qua 20-29c/10-19c ---
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

    # tin hieu manh hon vao truoc khi het tien ao
    order = {("YES", "85-97c"): 0, ("YES", "65-74c"): 1,
             ("NO", "10-19c"): 2, ("NO", "20-29c"): 3}
    candidates.sort(key=lambda x: order.get((x["side"], str(x["tier"])), 9))
    added = 0
    for c in candidates:
        key = (c["market_slug"], c["side"], str(c["tier"]))
        if key in have_keys:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - STAKE - fee, 2)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD11) cho lenh cu chot da")
            break
        if c["side"] == "YES":
            info = f"dam dong dang tin {c['trigger_ask']*100:.0f}%"
        else:
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
        print(f"  VAO LENH AO (CD11/{c['side']} {c['tier']}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} co phan "
              f"({info} | neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES11_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES11_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS11, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 11 v1 — chi ngay T: YES 2 khoang 65-74/85-97c (theo backtest) + NO (sau dinh 40-70c) 2 khoang 20-29/10-19c]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
