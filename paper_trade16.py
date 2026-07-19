# -*- coding: utf-8 -*-
"""
paper_trade16.py — CHIẾN DỊCH 16: MUA NO Ô ĐÁM ĐÔNG TIN NHẤT KHI GIÁ 30-70¢.
KHÔNG dùng tiền thật. Tiền ảo $1500. Chạy trong daily.yml cùng nhịp CD6.

Ý TƯỞNG (19/07, theo yêu cầu): ĐẢO NGƯỢC CD6 v1. CD6 v1 mua YES ô đám đông
tin nhất khi ask 30-70¢ và thua tan nát: thắng chỉ 32.8% (39/119), lỗ
-306.97$ — vì ở vùng giá đó chính đám đông cũng KHÔNG chắc, "ô tin nhất"
van truot toi ~67% so lan. Vay dat cuoc NGUOC lai: mua NO chinh o do.
Neu ty le truot ~67% giu nguyen, NO thang ~67% voi gia NO trung binh
~55c (can ~57% hoa von) -> ky vong duong nhe.

Quy tắc:
  - Ô mục tiêu = ô được thị trường định giá CAO NHẤT (đám đông tin nhất).
  - MUA NO ô đó khi ask của ô trong [0.30, 0.70]. Ngoài khoảng -> bỏ.
  - Giá NO = 1 - bid của ô. Vào ở mọi lần chụp (trong ngày, T+1, T+2).
    Mỗi event chỉ vào 1 lần.
  - $10/lệnh, ngân sách $1500, phí taker 5% x p x (1-p) như thật.
  - Thắng khi ô phân giải KHÁC ô đã NO.
CHƯA có kiểm chứng tiến cứu — suy ra từ nghịch đảo kết quả CD6 v1, cần
theo dõi khách quan (nghịch đảo 1 chiến lược lỗ KHÔNG tự động thành lời
vì còn phí + spread bid/ask).
v1 (19/07): bản đầu tiên.
Kết quả: data/trades16.csv
"""
import os
from datetime import datetime, timezone

import common as C
import paper_trade as P

TRADES16_CSV = C.DATA_DIR + "/trades16.csv"
BUDGET = 1500.0
STAKE = 10.0
MIN_ASK16 = 0.30
MAX_ASK16 = 0.70
FEE_RATE = 0.05


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def enter(trades, snaps, full, now):
    have = {t["event_slug"] for t in trades}
    today = now[:10]
    added = 0
    for s in snaps:
        try:
            lead = int(s["lead_days"])
        except (ValueError, TypeError):
            continue
        if lead < 0 or lead > 2 or s["event_slug"] in have:
            continue
        if s["snapshot_utc"][:10] != today:
            continue
        buckets = full.get((s["snapshot_utc"], s["event_slug"]))
        if not buckets:
            continue
        ranked = sorted([b for b in buckets if P.to_float(b.get("p")) is not None],
                        key=lambda b: -P.to_float(b["p"]))
        if not ranked:
            continue
        pick = ranked[0]
        ask = P.to_float(pick.get("ask"))
        bid = P.to_float(pick.get("bid"))
        if ask is None or not (MIN_ASK16 <= ask <= MAX_ASK16):
            continue
        price = round(1 - bid, 3) if bid is not None else round(1 - ask, 3)
        if not (0 < price < 1):
            continue
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD16) cho lenh cu chot da")
            break
        have.add(s["event_slug"])
        trades.append({
            "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
            "target_date": s["target_date"], "lead_days": s["lead_days"],
            "side": "NO", "bucket": pick["label"], "ask": price, "shares": shares,
            "stake": STAKE, "fee": fee,
            "model_median_c": round(100 * P.to_float(pick.get("p") or 0), 1),  # % dam dong
            "pm_top_bucket": pick["label"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        print(f"  VAO LENH AO (CD16): {s['city']} {s['target_date']} NO "
              f"'{pick['label']}' @{price} x{shares} co phan | dat 10 an {10/price:.2f} "
              f"(dam dong tin {100*P.to_float(pick.get('p') or 0):.0f}%)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES16_CSV)
    for t in trades:
        t.setdefault("status", "open")
        t.setdefault("side", "NO")

    n_settled = P.settle(trades, results)
    n_new = enter(trades, snaps, P.load_full_snapshots(), now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES16_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 16 v1 — NO o dam dong tin nhat khi ask 30-70c, $1500 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
