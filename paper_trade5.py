# -*- coding: utf-8 -*-
"""
paper_trade5.py — CHIẾN DỊCH 5: cược NO theo mô hình GFS, tiền ảo $1000.
KHÔNG dùng tiền thật. Chạy tự động mỗi ngày sau paper_trade4.py.

Ý tưởng: GFS là mô hình đo TỆ NHẤT trong 4 nguồn (lệch TB 1.89°C, chỉ trúng ô
~16%, và là mô hình lệch xa thực tế nhất trong 36% số lần đối đầu).
Vậy cược NGƯỢC nó: ô nào GFS chỉ vào thì cược NO ô đó.

Quy tắc (cố định, khách quan):
  - Ô mục tiêu = ô nhiệt độ chứa dự báo Tmax của GFS (fc_gfs_seamless_c).
  - Vào lệnh ở T+1 hoặc T+2 (snapshot trước ngày mục tiêu 1-2 ngày).
  - ĐÁNH TẤT CẢ lệnh có lời khi thắng >= $3 cho mỗi $10 đặt
    (nhận về >= $13 -> giá NO <= 10/13 ≈ 0.769). Thấp hơn thì bỏ.
  - KHÔNG lọc gì thêm: không cần GFS cãi đám đông, không chặn 63%,
    không giới hạn số lệnh/ngày (chỉ dừng khi hết tiền ảo).
  - Mỗi lệnh $10 ảo. Ngân sách $1000. Giá NO = 1 − bid của ô.
    Phí taker 5% × p × (1−p) tính như thật.
  - Thắng khi ô phân giải KHÁC ô GFS chỉ vào (tức GFS trượt).

Kết quả ghi vào data/trades5.csv (cùng cấu trúc data/trades.csv).
"""
import os
from datetime import datetime, timezone

import common as C
import paper_trade as P  # dùng lại parse_label, settle, load_full_snapshots

TRADES5_CSV = C.DATA_DIR + "/trades5.csv"

BUDGET = 1000.0
STAKE = 10.0
MIN_PROFIT = 3.0                        # thắng phải lời >= $3 cho $10 đặt
MAX_NO_PRICE = STAKE / (STAKE + MIN_PROFIT)  # = 10/13 ≈ 0.7692
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
        if bid is None and ask is None:
            continue
        price = round(1 - bid, 3) if bid is not None else round(1 - ask, 3)
        if not (0 < price < 1):
            continue
        if price > MAX_NO_PRICE:
            continue  # thang loi < $3 -> bo
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD5) cho lenh cu chot da")
            break
        have.add(s["event_slug"])
        trades.append({
            "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
            "target_date": s["target_date"], "lead_days": s["lead_days"],
            "side": "NO", "bucket": pick["label"], "ask": price, "shares": shares,
            "stake": STAKE, "fee": fee,
            "model_median_c": round(g, 1),  # o day ghi du bao GFS
            "pm_top_bucket": s.get("pm_top_bucket", ""),
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        print(f"  VAO LENH AO (CD5): {s['city']} {s['target_date']} NO "
              f"'{pick['label']}' @{price} x{shares} co phan | dat 10 an "
              f"{10/price:.2f} (GFS noi {g:.1f}C, cho tin {s.get('pm_top_bucket')})")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES5_CSV)
    for t in trades:
        t.setdefault("status", "open")
        t.setdefault("side", "NO")

    n_settled = P.settle(trades, results)
    n_new = enter(trades, snaps, P.load_full_snapshots(), now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES5_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 5 — NO theo GFS, loi >= $3, $1000 ao]")
    print(f"SO GIAO DICH AO: chot {n_settled}, vao moi {n_new}")
    print(f"Da chot: {won} thang / {lost} thua | Lai/lo da chot: {realized:+.2f} USD")
    print(f"Tien trong lenh mo: {open_cost:.2f} | "
          f"So du kha dung: {BUDGET + realized - open_cost:.2f} / {BUDGET:.0f} USD")


if __name__ == "__main__":
    main()
