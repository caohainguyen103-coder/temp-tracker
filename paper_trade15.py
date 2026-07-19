# -*- coding: utf-8 -*-
"""
paper_trade15.py — CHIẾN DỊCH 15: NO theo CD9 + ĐẢO CHIỀU YES x3 KHI GIÁ BẬT NGƯỢC.
KHÔNG dùng tiền thật. Tiền ảo $1500. Chỉ ngày T. Chạy trên VPS mỗi 15-30s.

Ý TƯỞNG (19/07, theo yêu cầu):
  Phía NO copy y hệt CD9 v9 (phía đang lời duy nhất toàn hệ thống: thắng
  93.2%, +39.48$): ô từng đạt đỉnh 40-70% rồi tuột qua 20-29c mua NO 1 lần,
  tuột tiếp qua 10-19c mua thêm 1 lần.

  THÊM LUẬT ĐẢO CHIỀU: nếu đã vào NO trên 1 ô mà thị trường BIẾN ĐỘNG NGƯỢC
  — giá ask bật tăng trở lại >= 25 điểm % so với giá lúc vào lệnh NO — thì
  coi như tín hiệu "tuột giá" đã sai (đám đông đổi ý lần nữa, ô này có thể
  thắng thật), lập tức MUA YES ô đó với vốn GẤP 3 ($30 thay vì $10) để vừa
  bù rủi ro lệnh NO đang kẹt vừa ăn theo đà đảo chiều. Mỗi ô chỉ đảo 1 lần.
  Mốc so sánh = giá trigger của lệnh NO ĐẦU TIÊN trên ô đó.

v1 (19/07): bản đầu tiên, ngưỡng đảo 18 điểm %.
v2 (19/07): nâng ngưỡng đảo 18 -> 25 điểm % theo yêu cầu (chờ đà bật thật
  sự rõ ràng mới đảo, tránh đảo nhầm theo nhiễu lớn). Ví dụ cụ thể: vào NO
  lúc giá 25% -> giá phải bật lên >= 50% mới mua YES x3.
Kết quả: data/trades15.csv | Lịch sử giá: data/cd15_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES15_CSV = C.DATA_DIR + "/trades15.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd15_price_hist.csv"

TRADE_FIELDS15 = [
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
REVERSAL_STAKE = 30.0        # x3 von khi dao chieu YES
REVERSAL_JUMP = 0.25         # v2: gia ask bat tang >= 25 diem % so voi luc vao NO
NO_PEAK_LOW, NO_PEAK_HIGH = 0.40, 0.70
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


def first_no_trigger(trades, market_slug):
    """Gia trigger_ask cua lenh NO DAU TIEN (entry som nhat) tren o nay."""
    nos = [t for t in trades
           if t["market_slug"] == market_slug and (t.get("side") or "").upper() == "NO"]
    if not nos:
        return None
    nos.sort(key=lambda t: t.get("entry_utc") or "")
    try:
        return float(nos[0].get("trigger_ask"))
    except (TypeError, ValueError):
        return None


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

            # --- PHIA NO: y het CD9 v9 ---
            if prev_max is not None and NO_PEAK_LOW <= prev_max <= NO_PEAK_HIGH:
                dlabel = no_drop_range_label(ask)
                if dlabel is not None:
                    key = (b["slug"], "NO", dlabel)
                    if key not in have_keys:
                        price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                        if MIN_PRICE <= price <= MAX_PRICE:
                            candidates.append({
                                "event_slug": slug, "market_slug": b["slug"], "city": city,
                                "target_date": target, "bucket": b["label"], "side": "NO",
                                "tier": dlabel, "price": price, "trigger_ask": ask,
                                "peak_ask": prev_max, "stake": STAKE,
                            })

            # --- DAO CHIEU: co NO mo + gia bat tang >= 18 diem tu luc vao NO ---
            no_trig = first_no_trigger(trades, b["slug"])
            if no_trig is not None and ask >= no_trig + REVERSAL_JUMP:
                key = (b["slug"], "YES", "dao-chieu")
                if key not in have_keys:
                    price = round(ask, 3)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        candidates.append({
                            "event_slug": slug, "market_slug": b["slug"], "city": city,
                            "target_date": target, "bucket": b["label"], "side": "YES",
                            "tier": "dao-chieu", "price": price, "trigger_ask": ask,
                            "peak_ask": no_trig,  # ghi gia NO goc de doi chieu
                            "stake": REVERSAL_STAKE,
                        })

    save_price_hist(price_hist, today)

    # dao chieu (tin hieu khan) vao truoc, roi NO rot sau vao truoc
    order = {("YES", "dao-chieu"): 0, ("NO", "10-19c"): 1, ("NO", "20-29c"): 2}
    candidates.sort(key=lambda x: order.get((x["side"], str(x["tier"])), 9))
    added = 0
    for c in candidates:
        key = (c["market_slug"], c["side"], str(c["tier"]))
        if key in have_keys:
            continue
        price = c["price"]
        stake = c["stake"]
        shares = round(stake / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - stake - fee, 2)
        if cash_available(trades) < stake + fee:
            print("  [HET TIEN AO] (CD15) cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": c["side"],
            "bucket": c["bucket"], "tier": c["tier"], "price": price, "shares": shares,
            "stake": stake, "fee": fee, "trigger_ask": c["trigger_ask"],
            "peak_ask": c["peak_ask"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_keys.add(key)
        if c["tier"] == "dao-chieu":
            info = (f"DAO CHIEU x3: vao NO luc gia {c['peak_ask']*100:.0f}%, "
                    f"gio bat len {c['trigger_ask']*100:.0f}% (+{(c['trigger_ask']-c['peak_ask'])*100:.0f} diem)")
        else:
            info = f"tung dat dinh {c['peak_ask']*100:.0f}%, gio con {c['trigger_ask']*100:.0f}%"
        print(f"  VAO LENH AO (CD15/{c['side']} {c['tier']}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} co phan, cuoc {stake:.0f}$ "
              f"({info} | neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES15_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES15_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS15, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 15 v2 — NO nhu CD9 + dao chieu YES x3 khi gia bat nguoc >= {REVERSAL_JUMP*100:.0f} diem]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
