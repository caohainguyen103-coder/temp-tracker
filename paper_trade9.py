# -*- coding: utf-8 -*-
"""
paper_trade9.py — CHIẾN DỊCH 9: NO Ô ĐÁM ĐÔNG TIN NHẤT (>=70c), quét liên tục.
Tiền ảo $1500. KHÔNG dùng tiền thật. Chạy ĐỘC LẬP mỗi 30 phút bằng workflow
riêng (cd9.yml) — KHÔNG phụ thuộc snapshot 2 lần/ngày của các chiến dịch
thời tiết khác, tự lấy giá market Polymarket TRỰC TIẾP mỗi lần chạy để bắt
kịp lúc giá vừa chạm ngưỡng 70c.

Cơ sở: giả thuyết NGƯỢC với chiến dịch 6 (CD6 mua YES ô đám đông tin ở mức
vừa phải 30-70c). Khi đám đông tin một ô đến mức cực đoan (>=70c), có thể
bị định giá quá tự tin (overconfidence / longshot ở phía đối nghịch bị bán
tháo) -> FADE bằng NO. Đây là chiến dịch THỬ NGHIỆM, CHƯA có backtest lịch
sử (tin nhắn tự nhiên đám đông >=70% ít khi thấy trong dữ liệu snapshot cũ
vì snapshot chỉ chụp 2 lần/ngày) — theo dõi khách quan, không kết luận sớm.

Quy tắc (cố định từ ngày dựng — không chỉnh giữa chừng):
  - Mỗi lần chạy (mỗi 30 phút): lấy trực tiếp mọi market "Highest
    temperature in ... on ...?" đang mở (active, chưa closed) trên Polymarket.
  - Ô mục tiêu = BẤT KỲ ô nào có giá ask hiện tại (đám đông) >= 0.70.
  - Cược NO ô đó với giá = 1 - bid (không có bid thì 1 - ask).
  - Mỗi Ô (theo market slug riêng của từng ô, không phải event) chỉ vào
    ĐÚNG 1 lần trong suốt vòng đời — quét lại nhiều lần sau đó sẽ bỏ qua.
  - $10/lệnh, ngân sách $1500, phí taker 5% x p x (1-p) như thật.
  - Thắng khi ô phân giải KHÁC ô đã cược NO.
Kết quả: data/trades9.csv
"""
import json
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES9_CSV = C.DATA_DIR + "/trades9.csv"

TRADE_FIELDS9 = [
    "entry_utc", "event_slug", "market_slug", "city", "target_date",
    "side", "bucket", "price", "shares", "stake", "fee",
    "trigger_ask", "status", "payout", "pnl", "settle_utc",
]

BUDGET = 1500.0
STAKE = 10.0
THRESHOLD = 0.70   # nguong dam dong "tin chac" kich hoat fade NO
FEE_RATE = 0.05


def parse_buckets(event):
    """Nhu collect.parse_markets nhung giu them closed/active de loc an toan."""
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
    """Chot lenh dua vao data/results.csv (verify.py sinh ra, dung chung
    voi cac chien dich thoi tiet khac)."""
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
            win = (rb != t["bucket"])  # NO thang khi o phan giai KHAC o da cuoc
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


def enter(trades, now, events=None):
    have_slugs = {t["market_slug"] for t in trades}
    if events is None:
        events = collect.fetch_temperature_events()
    candidates = []
    for ev in events:
        slug = ev.get("slug", "")
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target:
            continue
        for b in parse_buckets(ev):
            if not b["slug"] or b["slug"] in have_slugs:
                continue
            if b["ask"] is None or b["ask"] < THRESHOLD:
                continue
            price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - b["ask"], 3)
            if not (0 < price < 1):
                continue
            candidates.append({
                "event_slug": slug, "market_slug": b["slug"], "city": city,
                "target_date": target, "bucket": b["label"],
                "price": price, "trigger_ask": b["ask"],
            })

    candidates.sort(key=lambda x: -x["trigger_ask"])  # dam dong tin chac nhat truoc
    added = 0
    for c in candidates:
        if c["market_slug"] in have_slugs:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD9) cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": "NO",
            "bucket": c["bucket"], "price": price, "shares": shares,
            "stake": STAKE, "fee": fee, "trigger_ask": c["trigger_ask"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_slugs.add(c["market_slug"])
        print(f"  VAO LENH AO (CD9): {c['city']} {c['target_date']} NO "
              f"'{c['bucket']}' @{price} x{shares} co phan "
              f"(dam dong dang tin {c['trigger_ask']*100:.0f}%)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES9_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    import csv
    with open(TRADES9_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS9, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 9 — NO fade dam dong >=70c, quet moi 30 phut, $1500 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
