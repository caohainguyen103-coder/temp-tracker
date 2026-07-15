# -*- coding: utf-8 -*-
"""
paper_trade.py — GIẢ LẬP giao dịch thời tiết với ngân sách ảo $200.
KHÔNG dùng tiền thật. Chạy tự động mỗi ngày sau verify.py.

Chiến lược được giả lập (cố định, khách quan, không chỉnh tay giữa chừng):
  - Mỗi event nhiệt độ có snapshot TRƯỚC ngày mục tiêu (lead 1-2 ngày):
    lấy TRUNG VỊ dự báo Tmax của 5 mô hình -> tìm ô (bucket) chứa nó.
  - CHỈ vào lệnh khi: ô của mô hình KHÁC ô thị trường tin nhất
    (tức mô hình "cãi" đám đông) VÀ giá mua ô đó <= $0.30 (ăn được >= 2.3 lần).
  - Mỗi lệnh cược cố định $5 ảo. Tối đa 10 lệnh/ngày. Phí taker 5% x p x (1-p)
    tính như thật. Thắng khi ô mô hình = ô thị trường phân giải.
  - Ngân sách $200; hết tiền ảo thì ngừng vào lệnh đến khi lệnh cũ chốt.

Sau 3-4 tuần, data/trades.csv là bằng chứng khách quan: chiến lược này
lời hay lỗ bao nhiêu trên $200 — TRƯỚC KHI ai đó nghĩ đến tiền thật.
"""
import json
import os
import re
from datetime import datetime, timedelta, timezone
from statistics import median

import common as C

TRADES_CSV = C.DATA_DIR + "/trades.csv"

TRADE_FIELDS = [
    "entry_utc", "event_slug", "city", "target_date", "lead_days",
    "side", "bucket", "ask", "shares", "stake", "fee",
    "model_median_c", "pm_top_bucket",
    "status", "payout", "pnl", "settle_utc",
]

# Phía đặt cược: "YES" = mua bucket mô hình chọn (chiến lược cũ, đã lỗ -139$),
# "NO" = cược bucket đó KHÔNG xảy ra (mô phỏng trên 52 lệnh cũ: chỉ +0.63$),
# "BOTH" = mở song song cả hai để so sánh trực tiếp trên dashboard.
SIDE = "NO"

BUDGET = 200.0
STAKE = 5.0
MAX_ASK = 0.30
MIN_ASK = 0.02
MAX_TRADES_PER_DAY = 10
FEE_RATE = 0.05  # weather taker fee (docs.polymarket.com/trading/fees)

MODEL_COLS = ["fc_ecmwf_ifs025_c", "fc_gfs_seamless_c", "fc_icon_seamless_c",
              "fc_ukmo_seamless_c", "fc_best_match_c"]


def parse_label(label):
    """'<=23°C' / '>=33°C' / '24°C' / '84-85°F' -> bucket dict."""
    label = (label or "").strip()
    kind = None
    if label.startswith("<="):
        kind, label = "le", label[2:]
    elif label.startswith(">="):
        kind, label = "ge", label[2:]
    b = C.parse_bucket(label)
    if b and kind == "le":
        return {"lo": None, "hi": b["hi"], "unit": b["unit"], "kind": "le"}
    if b and kind == "ge":
        return {"lo": b["lo"], "hi": None, "unit": b["unit"], "kind": "ge"}
    return b


def load_full_snapshots():
    """snapshot_utc+event_slug -> list bucket {label,p,bid,ask}."""
    out = {}
    if not os.path.exists(C.SNAPSHOTS_JSONL):
        return out
    with open(C.SNAPSHOTS_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                j = json.loads(line)
                out[(j["snapshot_utc"], j["event_slug"])] = j["buckets"]
            except (ValueError, KeyError):
                continue
    return out


def to_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def settle(trades, results):
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
        side = (t.get("side") or "YES").upper()
        hit = (rb == t["bucket"])
        win = (hit if side == "YES" else not hit)
        if rb == "UNRESOLVED":
            t["status"], t["payout"], t["pnl"] = "void", stake, 0.0
        elif win:
            payout = shares * 1.0
            t["status"], t["payout"] = "won", round(payout, 2)
            t["pnl"] = round(payout - stake - fee, 2)
        else:
            t["status"], t["payout"] = "lost", 0.0
            t["pnl"] = round(-(stake + fee), 2)
        t["settle_utc"] = now
        n += 1
    return n


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
    candidates = []
    for s in snaps:
        try:
            lead = int(s["lead_days"])
        except (ValueError, TypeError):
            continue
        if lead < 1 or lead > 2 or s["event_slug"] in have:
            continue
        if s["snapshot_utc"][:10] != today:
            continue  # chỉ vào lệnh từ snapshot mới hôm nay
        fcs = [to_float(s.get(c)) for c in MODEL_COLS]
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
            bd = parse_label(b["label"])
            if bd and C.bucket_contains(bd, native, s.get("precision") or "whole"):
                pick = b
                break
        if not pick:
            continue
        ask = to_float(pick.get("ask"))
        if ask is None or not (MIN_ASK <= ask <= MAX_ASK):
            continue
        if pick["label"] == s.get("pm_top_bucket"):
            continue  # mô hình đồng ý với thị trường -> không có "cãi nhau" -> bỏ qua
        candidates.append((ask, s, pick, med_c))

    candidates.sort(key=lambda x: x[0])
    added = 0
    sides = ["YES", "NO"] if SIDE == "BOTH" else [SIDE]
    for ask, s, pick, med_c in candidates:
        if added >= MAX_TRADES_PER_DAY:
            break
        for side in sides:
            if side == "NO":
                bid = to_float(pick.get("bid"))
                price = round(1 - bid, 3) if bid is not None else round(1 - ask, 3)
            else:
                price = ask
            if not (0 < price < 1):
                continue
            shares = round(STAKE / price, 2)
            fee = round(FEE_RATE * price * (1 - price) * shares, 4)
            if cash_available(trades) < STAKE + fee:
                print("  [HET TIEN AO] cho lenh cu chot da")
                return added
            trades.append({
                "entry_utc": now, "event_slug": s["event_slug"], "city": s["city"],
                "target_date": s["target_date"], "lead_days": s["lead_days"],
                "side": side, "bucket": pick["label"], "ask": price, "shares": shares,
                "stake": STAKE, "fee": fee,
                "model_median_c": round(med_c, 1), "pm_top_bucket": s.get("pm_top_bucket", ""),
                "status": "open", "payout": "", "pnl": "", "settle_utc": "",
            })
            print(f"  VAO LENH AO: {s['city']} {s['target_date']} {side} '{pick['label']}' "
                  f"@{price} x{shares} co phan (mo hinh {med_c:.1f}C vs cho {s.get('pm_top_bucket')})")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    results = {r.get("event_slug"): r for r in C.read_csv(C.RESULTS_CSV)
               if r.get("event_slug")}
    trades = C.read_csv(TRADES_CSV)
    for t in trades:  # chuẩn hóa kiểu
        t.setdefault("status", "open")

    n_settled = settle(trades, results)
    n_new = enter(trades, snaps, load_full_snapshots(), now)

    # ghi lại toàn bộ (trạng thái thay đổi)
    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\nSO GIAO DICH AO: chot {n_settled}, vao moi {n_new}")
    print(f"Da chot: {won} thang / {lost} thua | Lai/lo da chot: {realized:+.2f} USD")
    print(f"Tien dang nam trong lenh mo: {open_cost:.2f} | "
          f"So du kha dung: {BUDGET + realized - open_cost:.2f} / {BUDGET:.0f} USD")


if __name__ == "__main__":
    main()
