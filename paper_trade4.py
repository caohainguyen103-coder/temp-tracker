# -*- coding: utf-8 -*-
"""
paper_trade4.py — CHIẾN DỊCH 4: bản NO của chiến dịch 3, tiền ảo $1000.
KHÔNG dùng tiền thật. Chạy tự động mỗi ngày sau paper_trade.py.

Quy tắc (cố định, khách quan, không chỉnh tay giữa chừng):
  - TÍN HIỆU VÀO LỆNH NHƯ CHIẾN DỊCH 3: trung vị dự báo Tmax của
    5 mô hình chỉ vào ô KHÁC ô thị trường tin nhất (mô hình "cãi" đám đông),
    giá YES của ô đó >= 0.02. KHÁC chiến dịch 3: KHÔNG có trần 30¢ —
    lệnh có YES > 30¢ được gắn nhãn nhóm "mo_rong" (mục riêng để kiểm tra),
    còn lại là nhóm "goc".
  - Vào lệnh ở T+1 hoặc T+2 (snapshot trước ngày mục tiêu 1-2 ngày).
  - KHÔNG vào lệnh nếu ô thị trường tin nhất được định giá > 63%
    (đám đông quá chắc chắn -> không cãi).
  - Khác biệt duy nhất: thay vì mua YES, CƯỢC NO chính ô đó
    (cược rằng ô mô hình chọn sẽ KHÔNG xảy ra). Giá NO = 1 − bid của ô.
  - TỶ LỆ TỐI THIỂU: đặt 10 phải nhận về ít nhất 13.5 khi thắng
    (odds 1.35) → giá NO tối đa = 10/13.5 ≈ 0.7407.
    Giá NO cao hơn (tỷ lệ ăn thấp hơn) → KHÔNG vào lệnh.
  - Mỗi lệnh $10 ảo. Ngân sách $1000. Tối đa 10 lệnh/ngày.
    Phí taker 5% × p × (1−p) tính như thật.
  - Thắng khi ô phân giải KHÁC ô đã cược NO.

Kết quả ghi vào data/trades4.csv (cùng cấu trúc data/trades.csv).
"""
import os
from datetime import datetime, timezone
from statistics import median

import common as C
import paper_trade as P  # dùng lại đúng logic chọn ô của chiến dịch 3

TRADES4_CSV = C.DATA_DIR + "/trades4.csv"

BUDGET = 1000.0
STAKE = 10.0
MIN_ODDS = 13.5 / 10.0            # đặt 10 ăn (nhận về) 13.5
MAX_NO_PRICE = 1.0 / MIN_ODDS     # = 0.7407...
FEE_RATE = 0.05                   # phí taker thời tiết (như chiến dịch 3)

MIN_ASK = P.MIN_ASK   # 0.02 (chong o rac); KHONG co tran — xem nhom "mo_rong"
GOC_MAX_ASK = P.MAX_ASK  # 0.30: ranh gioi phan nhom goc / mo_rong
TRADE_FIELDS4 = P.TRADE_FIELDS + ["nhom"]
MAX_TRADES_PER_DAY = 10
MAX_TOP_PROB = 0.63   # o dam dong tin nhat > 63% -> bo qua thi truong do


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def enter(trades, snaps, full, now):
    """Chọn ứng viên y hệt chiến dịch 3, nhưng vào lệnh NO với odds >= 1.35."""
    have = {t["event_slug"] for t in trades}
    today = now[:10]
    candidates = []
    for s in snaps:
        try:
            lead = int(s["lead_days"])
        except (ValueError, TypeError):
            continue
        if lead < 1 or lead > 2 or s["event_slug"] in have:  # T+1 hoac T+2
            continue
        if s["snapshot_utc"][:10] != today:
            continue  # chỉ vào lệnh từ snapshot mới hôm nay
        fcs = [P.to_float(s.get(c)) for c in P.MODEL_COLS]
        fcs = [x for x in fcs if x is not None]
        if len(fcs) < 3:
            continue
        med_c = median(fcs)
        native = C.c_to_f(med_c) if s["unit"] == "F" else med_c
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
        ask = P.to_float(pick.get("ask"))
        if ask is None or ask < MIN_ASK:
            continue
        if pick["label"] == s.get("pm_top_bucket"):
            continue  # mô hình đồng ý với thị trường -> bỏ qua
        top_p = max((P.to_float(b.get("p")) or 0) for b in buckets)
        if top_p > MAX_TOP_PROB:
            print(f"  BO QUA (dam dong qua chac): {s['city']} {s['target_date']} "
                  f"o '{s.get('pm_top_bucket')}' dang {100*top_p:.0f}% > 63%")
            continue
        candidates.append((ask, s, pick, med_c))

    candidates.sort(key=lambda x: x[0])
    added = 0
    for ask, s, pick, med_c in candidates:
        if added >= MAX_TRADES_PER_DAY:
            break
        # Giá NO = 1 - bid (không có bid thì dùng 1 - ask, thận trọng hơn)
        bid = P.to_float(pick.get("bid"))
        price = round(1 - bid, 3) if bid is not None else round(1 - ask, 3)
        if not (0 < price < 1):
            continue
        odds = 1.0 / price
        if price > MAX_NO_PRICE:
            print(f"  BO QUA (ty le thap): {s['city']} {s['target_date']} "
                  f"NO '{pick['label']}' @{price} -> dat 10 chi an "
                  f"{10*odds:.2f} < 13.50")
            continue
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] cho lenh cu chot da")
            return added
        trades.append({
            "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
            "target_date": s["target_date"], "lead_days": s["lead_days"],
            "side": "NO", "bucket": pick["label"], "ask": price, "shares": shares,
            "stake": STAKE, "fee": fee,
            "model_median_c": round(med_c, 1),
            "pm_top_bucket": s.get("pm_top_bucket", ""),
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
            "nhom": "mo_rong" if ask > GOC_MAX_ASK else "goc",
        })
        print(f"  VAO LENH AO (CD4/{trades[-1]['nhom']}): {s['city']} "
              f"{s['target_date']} NO '{pick['label']}' @{price} x{shares} co phan "
              f"| dat 10 an {10*odds:.2f} "
              f"(mo hinh {med_c:.1f}C vs cho {s.get('pm_top_bucket')})")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES4_CSV)
    for t in trades:
        t.setdefault("status", "open")
        t.setdefault("side", "NO")
        if not t.get("nhom"):
            t["nhom"] = "goc"

    n_settled = P.settle(trades, results)  # settle đã xử lý side NO sẵn
    n_new = enter(trades, snaps, P.load_full_snapshots(), now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES4_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS4, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 4 — NO, odds >= 1.35, $1000 ao]")
    print(f"SO GIAO DICH AO: chot {n_settled}, vao moi {n_new}")
    print(f"Da chot: {won} thang / {lost} thua | Lai/lo da chot: {realized:+.2f} USD")
    print(f"Tien dang nam trong lenh mo: {open_cost:.2f} | "
          f"So du kha dung: {BUDGET + realized - open_cost:.2f} / {BUDGET:.0f} USD")

    # Tổng theo ngày: bao nhiêu lệnh đã cược, bao nhiêu tiền, lãi/lỗ đã chốt
    days = {}
    for t in trades:
        d = (t.get("entry_utc") or "")[:10]
        if not d:
            continue
        day = days.setdefault(d, {"n": 0, "stake": 0.0, "won": 0, "lost": 0,
                                  "open": 0, "pnl": 0.0})
        day["n"] += 1
        day["stake"] += float(t["stake"] or 0)
        if t["status"] == "open":
            day["open"] += 1
        else:
            day["pnl"] += float(t["pnl"] or 0)
            if t["status"] == "won":
                day["won"] += 1
            elif t["status"] == "lost":
                day["lost"] += 1
    if days:
        print("\nTONG TUNG NGAY (theo ngay vao lenh):")
        for d in sorted(days):
            x = days[d]
            print(f"  {d}: {x['n']} lenh, cuoc {x['stake']:.0f}$ | "
                  f"{x['won']} thang / {x['lost']} thua / {x['open']} mo | "
                  f"lai/lo da chot {x['pnl']:+.2f}$")


if __name__ == "__main__":
    main()
