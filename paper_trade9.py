# -*- coding: utf-8 -*-
"""
paper_trade9.py — CHIẾN DỊCH 9: theo đám đông ở 2 đầu, quét liên tục.
Tiền ảo $1500. KHÔNG dùng tiền thật. Chạy ĐỘC LẬP mỗi 30 phút bằng workflow
riêng (cd9.yml) — KHÔNG phụ thuộc snapshot 2 lần/ngày của các chiến dịch
thời tiết khác, tự lấy giá market Polymarket TRỰC TIẾP mỗi lần chạy để bắt
kịp lúc giá vừa chạm ngưỡng.

Cơ sở: favorite-longshot bias — đám đông thường trả THIẾU cho cửa nặng ký
(favorite) và trả THỪA cho cửa nhẹ ký (longshot). CD6 đã khai thác việc này
ở vùng giá vừa phải (30-70c). CD9 khai thác ở 2 đầu cực đoan hơn:
  - Cửa nặng ký RẤT mạnh (đám đông tin >=60c hoặc >=70c) -> mua YES theo,
    vì phần này thường vẫn bị trả thiếu.
  - Cửa đã rớt xuống thành longshot (đám đông chỉ còn tin 10-20c) -> mua NO
    (cược nó KHÔNG xảy ra), vì longshot thường bị trả thừa.
Đây là chiến dịch THỬ NGHIỆM, CHƯA có backtest lịch sử — theo dõi khách
quan, không kết luận sớm.

Quy tắc (cố định từ ngày dựng — không chỉnh giữa chừng):
  - Mỗi lần chạy (mỗi 30 phút): lấy trực tiếp mọi market "Highest
    temperature in ... on ...?" đang mở (active, chưa closed) trên Polymarket.
  - CHỈ xét market có ngày mục tiêu (target_date) SAU ngày hôm nay (UTC).
    Bỏ qua market của NGÀY HÔM NAY — vào cuối ngày, giá đám đông tiến gần
    100% đơn giản vì nhiệt độ thực tế đã gần như biết rồi (sắp phân giải),
    không phải "quá tự tin" thật sự -> vào lệnh lúc đó là rủi ro đuôi (tail
    risk) chứ không kiểm tra đúng giả thuyết. (Lỗi thực tế bắt được ở lần
    chạy thử đầu tiên 2026-07-17: 32 lệnh vào giá cực đoan, x10000 đòn bẩy,
    ăn hết 335$ ngân sách chỉ trong 1 lần quét — đã sửa bằng luật này.)
  - PHÍA YES (theo cửa nặng ký): ô nào giá ask (đám đông tin) >= 0.60 ->
    mua YES 1 lần ở mốc 60c (giá mua = giá ask thật lúc quét). Nếu SAU ĐÓ
    giá lên tiếp >= 0.70 -> mua YES thêm 1 lần nữa ở mốc 70c (giá thật lúc
    đó). Mỗi ô tối đa 2 lệnh YES (1 lệnh/mốc, không mua lại mốc đã mua).
  - PHÍA NO (fade cửa đã thành longshot): ô BẤT KỲ (không cần liên quan gì
    đến ô đã mua YES) có giá ask rơi vào khoảng [0.10, 0.20] -> mua NO 1
    lần duy nhất (giá mua = 1 - bid, hoặc 1 - ask nếu thiếu bid).
  - Giá vào lệnh (YES lẫn NO) phải nằm trong [0.02, 0.98] — loại các trường
    hợp giá cực đoan gần 0 hoặc gần 1 (đòn bẩy vô lý / gần như đã phân giải).
  - $10/lệnh, ngân sách $1500 dùng chung 2 phía, phí taker 5% x p x (1-p).
  - Ghi lại "lợi nhuận dự kiến nếu thắng" (potential_profit) ngay lúc vào
    lệnh, để dễ nhìn không cần đợi chốt mới biết ăn bao nhiêu.
  - Thắng: YES thắng khi ô phân giải ĐÚNG ô đã mua; NO thắng khi ô phân
    giải KHÁC ô đã mua.
Kết quả: data/trades9.csv
"""
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES9_CSV = C.DATA_DIR + "/trades9.csv"

TRADE_FIELDS9 = [
    "entry_utc", "event_slug", "market_slug", "city", "target_date",
    "side", "bucket", "tier", "price", "shares", "stake", "fee",
    "trigger_ask", "potential_profit", "status", "payout", "pnl", "settle_utc",
]

BUDGET = 1500.0
STAKE = 10.0
YES_TIERS = [0.60, 0.70]      # moi moc mua YES rieng 1 lan/o
NO_LOW, NO_HIGH = 0.10, 0.20  # dam dong tut xuong khoang nay -> mua NO 1 lan/o
MIN_PRICE, MAX_PRICE = 0.02, 0.98  # loai gia cuc doan (don bay vo ly)
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


def _mk_candidate(ev_slug, city, target, b, side, tier_label, price, trigger_ask):
    return {
        "event_slug": ev_slug, "market_slug": b["slug"], "city": city,
        "target_date": target, "bucket": b["label"], "side": side,
        "tier": tier_label, "price": price, "trigger_ask": trigger_ask,
    }


def enter(trades, now, events=None):
    # khoa theo (slug, side, moc) - YES co 2 moc rieng, NO chi co 1 "moc" 10-20
    have_keys = {(t["market_slug"], (t.get("side") or "").upper(), str(t.get("tier") or ""))
                 for t in trades}
    today = now[:10]
    if events is None:
        events = collect.fetch_temperature_events()
    candidates = []
    for ev in events:
        slug = ev.get("slug", "")
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target or target <= today:
            continue  # bo qua market cua HOM NAY tro ve truoc (xem docstring)
        for b in parse_buckets(ev):
            if not b["slug"] or b["ask"] is None:
                continue
            ask = b["ask"]

            # --- PHIA YES: theo cua nang ky, 2 moc doc lap 60/70 ---
            for tier in YES_TIERS:
                if ask < tier:
                    continue
                key = (b["slug"], "YES", str(tier))
                if key in have_keys:
                    continue
                price = round(ask, 3)
                if not (MIN_PRICE <= price <= MAX_PRICE):
                    continue
                candidates.append(_mk_candidate(
                    slug, city, target, b, "YES", tier, price, ask))

            # --- PHIA NO: fade cua da thanh longshot 10-20c ---
            if NO_LOW <= ask <= NO_HIGH:
                key = (b["slug"], "NO", "lowconf")
                if key not in have_keys:
                    price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        candidates.append(_mk_candidate(
                            slug, city, target, b, "NO", "lowconf", price, ask))

    # moc/tin hieu manh hon vao truoc khi het tien ao: YES 70 > YES 60 > NO
    order = {("YES", "0.7"): 0, ("YES", "0.6"): 1, ("NO", "lowconf"): 2}
    candidates.sort(key=lambda x: order.get((x["side"], str(x["tier"])), 9))
    added = 0
    for c in candidates:
        key = (c["market_slug"], c["side"], str(c["tier"]))
        if key in have_keys:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - STAKE - fee, 2)  # neu thang
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD9) cho lenh cu chot da")
            break
        tier_txt = (f"{c['tier']*100:.0f}c" if c["side"] == "YES" else "10-20c")
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": c["side"],
            "bucket": c["bucket"], "tier": c["tier"], "price": price, "shares": shares,
            "stake": STAKE, "fee": fee, "trigger_ask": c["trigger_ask"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_keys.add(key)
        print(f"  VAO LENH AO (CD9/{c['side']} {tier_txt}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} co phan "
              f"(dam dong dang tin {c['trigger_ask']*100:.0f}% | neu thang +{potential_profit:.2f}$)")
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
    print(f"\n[CHIEN DICH 9 — YES o 60/70c + NO fade longshot 10-20c, quet moi 30 phut, $1500 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
