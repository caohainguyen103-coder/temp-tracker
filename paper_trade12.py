# -*- coding: utf-8 -*-
"""
paper_trade12.py — CHIẾN DỊCH 12: ARBITRAGE MUA TRỌN BỘ Ô.
KHÔNG dùng tiền thật. Tiền ảo $1500. Chạy trên VPS mỗi 2 phút.

Ý TƯỞNG (ngách duy nhất KHÔNG THỂ LỖ về lý thuyết):
  Mỗi thị trường nhiệt độ có N ô, chắc chắn đúng 1 ô thắng và trả $1/cổ phần.
  Nếu TỔNG giá mua (ask) của cả N ô < $1 thì mua đều mỗi ô cùng số cổ phần:
  dù kết quả ra ô nào cũng nhận về đúng $1/cổ phần -> lời phần chênh lệch,
  KHÔNG có kịch bản thua. Backtest 09-17/07: 14 lần tổng bộ < 0.995 (ảnh chụp
  2 lần/ngày), lời ròng 0.6-5.3%/bộ sau phí. Quét 2 phút kỳ vọng bắt nhiều hơn
  vì cơ hội arbitrage thường chỉ tồn tại vài phút.

LUẬT v1 (18/07):
  - Xét event có lead 0-2 ngày (khóa vốn ngắn để quay vòng).
  - CHỈ vào khi: đủ giá ask cho TẤT CẢ các ô đang active (thiếu 1 ô là bỏ —
    nếu ô thiếu thắng thì mất trắng, không còn là arbitrage), >= 3 ô.
  - ~$100/bộ: mua N = 100/tổng_ask cổ phần MỖI ô. Lời khóa chắc =
    N*(1 - tổng_ask) - tổng phí. Chỉ vào khi lời ròng >= $0.30.
  - Mỗi event chỉ mua 1 bộ (không mua lại khi giá dip lần nữa).
  - Không loại thành phố nào (kể cả Los Angeles) vì kết quả ra sao cũng thắng.
Kết quả: data/trades12.csv (1 dòng = 1 bộ trọn ô, không phải 1 lệnh lẻ)
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES12_CSV = C.DATA_DIR + "/trades12.csv"

TRADE_FIELDS12 = [
    "entry_utc", "event_slug", "city", "target_date", "lead_days",
    "n_buckets", "sum_ask", "shares", "cost", "fee",
    "locked_profit", "status", "payout", "pnl", "settle_utc",
]

BUDGET = 1500.0
SET_STAKE = 100.0   # von bo vao moi bo (xap xi, = shares * sum_ask)
MIN_NET = 0.30      # loi rong toi thieu/bo de dang vao (tranh nhieu vi lam tron)
MAX_LEAD_DAYS = 2
MIN_BUCKETS = 3
FEE_RATE = 0.05


def full_set_asks(event):
    """Tra ve list ask cua TAT CA cac o active trong event, hoac None neu
    thieu bat ky o nao (khong du bo -> khong phai arbitrage)."""
    asks = []
    for mk in event.get("markets", []):
        b = C.parse_bucket(mk.get("groupItemTitle"))
        if b is None:
            return None  # co o khong doc duoc -> khong chac du bo
        if mk.get("closed") or not mk.get("active"):
            return None  # co o da dong -> bo khong con tron ven
        ask = mk.get("bestAsk")
        if ask is None:
            return None
        asks.append(float(ask))
    return asks if len(asks) >= MIN_BUCKETS else None


def set_economics(asks):
    """Tinh (shares, cost, fee, loi_khoa_chac) cho 1 bo."""
    s = sum(asks)
    if s <= 0:
        return None
    shares = round(SET_STAKE / s, 2)
    cost = round(shares * s, 2)
    fee = round(sum(FEE_RATE * a * (1 - a) * shares for a in asks), 4)
    locked = round(shares * 1.0 - cost - fee, 2)  # nhan ve shares*$1 du ket qua nao
    return {"sum_ask": round(s, 4), "shares": shares, "cost": cost,
            "fee": fee, "locked_profit": locked}


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["cost"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def settle(trades):
    """Chot bo khi results.csv co ket qua: 1 o thang -> nhan shares * $1."""
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
        cost, fee, shares = float(t["cost"]), float(t["fee"]), float(t["shares"])
        if rb == "UNRESOLVED":
            t["status"], t["payout"], t["pnl"] = "void", cost, 0.0
        else:
            payout = shares * 1.0  # o nao thang cung the
            t["status"], t["payout"] = "won", round(payout, 2)
            t["pnl"] = round(payout - cost - fee, 2)
        t["settle_utc"] = now
        n += 1
    return n


def enter(trades, now, events=None):
    have = {t["event_slug"] for t in trades}
    today = C.parse_iso_date(now[:10])
    if events is None:
        events = collect.fetch_temperature_events()

    candidates = []
    for ev in events:
        slug = ev.get("slug", "")
        if not slug or slug in have:
            continue
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target:
            continue
        try:
            lead = (C.parse_iso_date(target) - today).days
        except ValueError:
            continue
        if lead < 0 or lead > MAX_LEAD_DAYS:
            continue
        asks = full_set_asks(ev)
        if asks is None:
            continue
        eco = set_economics(asks)
        if eco is None or eco["locked_profit"] < MIN_NET:
            continue
        candidates.append({
            "event_slug": slug, "city": city, "target_date": target,
            "lead_days": lead, "n_buckets": len(asks), **eco,
        })

    candidates.sort(key=lambda x: -x["locked_profit"])  # loi to vao truoc
    added = 0
    for c in candidates:
        if c["event_slug"] in have:
            continue
        if cash_available(trades) < c["cost"] + c["fee"]:
            print("  [HET TIEN AO] (CD12) cho bo cu chot da")
            break
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"], "city": c["city"],
            "target_date": c["target_date"], "lead_days": c["lead_days"],
            "n_buckets": c["n_buckets"], "sum_ask": c["sum_ask"],
            "shares": c["shares"], "cost": c["cost"], "fee": c["fee"],
            "locked_profit": c["locked_profit"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have.add(c["event_slug"])
        print(f"  MUA TRON BO (CD12): {c['city']} {c['target_date']} "
              f"{c['n_buckets']} o, tong gia {c['sum_ask']} x{c['shares']} co phan "
              f"| loi khoa chac +{c['locked_profit']:.2f}$ (khong the thua)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES12_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES12_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS12, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["cost"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    print(f"\n[CHIEN DICH 12 v1 — arbitrage tron bo, ~{SET_STAKE:.0f}$/bo, loi rong >= {MIN_NET}$]")
    print(f"Chot {n_settled}, mua moi {n_new} bo | {won} bo da thang (khong the thua) | "
          f"lai da chot {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
