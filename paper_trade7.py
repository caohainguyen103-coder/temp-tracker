# -*- coding: utf-8 -*-
"""
paper_trade7.py — CHIẾN DỊCH 7: NO Ô GFS, GIÁ NO 70-100¢, tiền ảo $1500.
KHÔNG dùng tiền thật. LUẬT ĐÓNG BĂNG từ 16/07/2026 — không chỉnh giữa chừng.

Cơ sở: GFS là mô hình đo tệ nhất (trúng ô ~16%); cược NO ô nó chỉ vào,
CHỈ nhận lệnh giá NO 70-100¢ (ô GFS bị chợ coi nhẹ — vùng NO thắng đều).
Backtest 09-14/07 (227 lệnh): +115$, DƯƠNG CẢ 5/5 NGÀY, dao động ±12$.

Quy tắc:
  - Ô mục tiêu = ô chứa dự báo Tmax của GFS (fc_gfs_seamless_c).
  - Cược NO ô đó khi giá NO = 1 - bid trong [0.70, 0.999]. Ngoài khoảng -> bỏ.
  - Vào ở T+1 hoặc T+2 (KHÔNG vào trong ngày). Mỗi event 1 lần.
  - $10/lệnh, ngân sách $1500, phí taker 5% x p x (1-p) như thật.
  - Thắng khi ô phân giải KHÁC ô GFS chỉ.
Kết quả: data/trades7.csv
"""
import os
from datetime import datetime, timezone

import common as C
import paper_trade as P

TRADES7_CSV = C.DATA_DIR + "/trades7.csv"
BUDGET = 1500.0
STAKE = 10.0
MIN_NO = 0.70
MAX_NO = 0.999
FEE_RATE = 0.05
GFS_COL = "fc_gfs_seamless_c"


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
        if lead < 1 or lead > 2 or s["event_slug"] in have:
            continue
        if s["snapshot_utc"][:10] != today:
            continue
        g = P.to_float(s.get(GFS_COL))
        if g is None:
            continue
        native = C.c_to_f(g) if s["unit"] == "F" else g
        buckets = full.get((s["snapshot_utc"], s["event_slug"]))
        if not buckets:
            continue
        pick = None
        for b in buckets:
            bd = P.parse_label(b["label"])
            if bd and C.bucket_contains(bd, native, s.get("precision") or "whole"):
                pick = b
                break
        if not pick:
            continue
        bid = P.to_float(pick.get("bid"))
        ask = P.to_float(pick.get("ask"))
        price = round(1 - bid, 3) if bid is not None else (round(1 - ask, 3) if ask is not None else None)
        if price is None or not (MIN_NO <= price <= MAX_NO):
            continue
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD7) cho lenh cu chot da")
            break
        have.add(s["event_slug"])
        trades.append({
            "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
            "target_date": s["target_date"], "lead_days": s["lead_days"],
            "side": "NO", "bucket": pick["label"], "ask": price, "shares": shares,
            "stake": STAKE, "fee": fee,
            "model_median_c": round(g, 1),  # du bao GFS
            "pm_top_bucket": s.get("pm_top_bucket", ""),
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        print(f"  VAO LENH AO (CD7): {s['city']} {s['target_date']} NO "
              f"'{pick['label']}' @{price} x{shares} co phan (GFS noi {g:.1f}C)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES7_CSV)
    for t in trades:
        t.setdefault("status", "open")
        t.setdefault("side", "NO")

    n_settled = P.settle(trades, results)
    n_new = enter(trades, snaps, P.load_full_snapshots(), now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES7_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 7 — NO o GFS 70-100c, $1500 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
