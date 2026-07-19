# -*- coding: utf-8 -*-
"""
paper_trade6.py — CHIẾN DỊCH 6: MUA YES Ô ĐÁM ĐÔNG TIN NHẤT, tiền ảo $3000.
KHÔNG dùng tiền thật.

Cơ sở: hiện tượng favorite-longshot bias — đám đông có xu hướng trả thiếu
cho "cửa nặng ký". Backtest 09-15/07 (243 lệnh): +273$, ngày tệ nhất -0.35$.

Quy tắc v1 (16/07, đóng băng): mua YES ô đám đông tin nhất khi ask trong
[0.30, 0.70]. KẾT QUẢ THỰC TẾ đến 19/07: thắng chỉ 32.8% (39/119), lỗ
-306.97$ — tệ nhất toàn hệ thống. Lý do: vùng 30-70c với ask trung bình
~45c cần thắng >=45% mới hòa, nhưng ô "tin nhất" ở vùng giá thấp nghĩa là
đám đông cũng KHÔNG chắc — không có favorite thật sự để hưởng bias.

v2 (19/07): CHỈ TIN CHỢ KHI CHỢ TỰ TIN THẬT — nâng ngưỡng vào lệnh lên
ask >= 0.62 (tối đa 0.97 để tránh giá cực đoan). Thêm ngân sách $1500 ->
$3000 vì bản cũ hết vốn ảo (115 lệnh mở giam gần hết tiền).

  - Vào ở mọi lần chụp (trong ngày, T+1, T+2). Mỗi event chỉ vào 1 lần.
  - $10/lệnh, phí taker 5% x p x (1-p) như thật.
  - Thắng khi ô phân giải = ô đã mua.
Kết quả: data/trades6.csv
"""
import os
from datetime import datetime, timezone

import common as C
import paper_trade as P

TRADES6_CSV = C.DATA_DIR + "/trades6.csv"
BUDGET = 3000.0   # v2: them ngan sach (cu 1500, het von vi 115 lenh mo)
STAKE = 10.0
MIN_ASK6 = 0.62   # v2: chi tin cho khi cho tu tin that (cu 0.30)
MAX_ASK6 = 0.97   # v2: mo tran len 97c, van chan gia cuc doan (cu 0.70)
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
        if ask is None or not (MIN_ASK6 <= ask <= MAX_ASK6):
            continue
        shares = round(STAKE / ask, 2)
        fee = round(FEE_RATE * ask * (1 - ask) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD6) cho lenh cu chot da")
            break
        have.add(s["event_slug"])
        trades.append({
            "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
            "target_date": s["target_date"], "lead_days": s["lead_days"],
            "side": "YES", "bucket": pick["label"], "ask": ask, "shares": shares,
            "stake": STAKE, "fee": fee,
            "model_median_c": round(100 * P.to_float(pick.get("p") or 0), 1),  # ghi % dam dong
            "pm_top_bucket": pick["label"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        print(f"  VAO LENH AO (CD6): {s['city']} {s['target_date']} YES "
              f"'{pick['label']}' @{ask} x{shares} co phan | dat 10 an {10/ask:.2f}")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES6_CSV)
    for t in trades:
        t.setdefault("status", "open")
        t.setdefault("side", "YES")

    n_settled = P.settle(trades, results)
    n_new = enter(trades, snaps, P.load_full_snapshots(), now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES6_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=P.TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 6 v2 — YES o dam dong 62-97c, $3000 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
