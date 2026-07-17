# -*- coding: utf-8 -*-
"""
paper_trade9.py — CHIẾN DỊCH 9: theo đám đông ở 2 đầu, CHỈ trong ngày mục
tiêu là hôm nay (ngày T), quét liên tục mỗi 30 phút. Tiền ảo $1500.
KHÔNG dùng tiền thật. Chạy ĐỘC LẬP bằng workflow riêng (cd9.yml).

Cơ sở: favorite-longshot bias — đám đông thường trả THIẾU cho cửa nặng ký
(favorite) và trả THỪA cho cửa nhẹ ký (longshot).

=== LỊCH SỬ SỬA LUẬT (đọc để hiểu vì sao code như hiện tại) ===
v1 (17/07 sáng): fade NO khi giá >=70c, mọi ngày tương lai. Bị lỗi: vào cả
  market của HÔM NAY, giá gần 100% chỉ vì ngày sắp hết chứ không phải "quá tự
  tin" thật — 32 lệnh cực đoan, x10000 đòn bẩy, ăn 335$ trong 1 lần quét.
v2: sửa bằng cách LOẠI market hôm nay (target > today), thêm chặn giá
  [0.02, 0.98]. Deploy ổn.
v3: nâng cấp 3 mốc NO 50/60/70 riêng biệt — bị thay trước khi deploy.
v4 (17/07 chiều, đã chạy live): 2 phía —
    YES: ô >=60c mua 1 lần, >=70c mua thêm 1 lần (tối đa 2 lệnh/ô), mọi
         ngày tương lai (KHÔNG gồm hôm nay).
    NO:  ô bất kỳ rơi vào [0.10, 0.20] mua 1 lần, mọi ngày tương lai.
  Kết quả thực tế: phía NO bắn ra ồ ạt (121 lệnh mở/1 lần quét, ăn gần hết
  $1500) vì hầu như thị trường nào cũng có vài ô "vai" nằm sẵn trong dải
  10-20c ngay từ đầu — không phải tín hiệu "đám đông vừa đổi ý", chỉ là ô đó
  vốn dĩ đã là longshot.
v5 (17/07, ĐANG DÙNG — theo yêu cầu mới nhất) — thu hẹp lại có chủ đích:
    - CHỈ xét market có target_date == HÔM NAY (ngày T) — cho CẢ 2 phía.
      (Đây là đổi ngược lại so với v4, chấp nhận rủi ro giá cực đoan cuối
      ngày đã nêu ở v1, nhưng bù lại bằng: vẫn giữ chặn [0.02,0.98], và
      luật NO giờ đòi hỏi lịch sử giá cụ thể chứ không chỉ "giá đang thấp".)
    - PHÍA YES: giữ nguyên — ô >=60c mua 1 lần, >=70c mua thêm 1 lần.
    - PHÍA NO: THAY HẲN luật cũ. Không còn ngưỡng cố định 10-20c. Giờ chỉ
      mua NO khi ô đó TỪNG đạt đỉnh giá trong khoảng [0.40, 0.70] ở một lần
      quét trước đó, RỒI SAU ĐÓ tuột xuống dưới 0.40 — tức đám đông từng coi
      là ứng viên nghiêm túc rồi rút lui, không phải vốn dĩ đã là longshot.
      Cần bộ nhớ giá đỉnh từng thấy mỗi ô -> lưu riêng data/cd9_price_hist.csv,
      cập nhật MỌI lần quét cho MỌI market (không giới hạn ngày) để có đủ
      lịch sử ngay khi market bước vào ngày T.
Đây là chiến dịch THỬ NGHIỆM, CHƯA có backtest lịch sử — theo dõi khách
quan, không kết luận sớm, không chỉnh luật giữa chừng nếu không có lý do.
Kết quả: data/trades9.csv | Lịch sử giá: data/cd9_price_hist.csv
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES9_CSV = C.DATA_DIR + "/trades9.csv"
PRICE_HIST_CSV = C.DATA_DIR + "/cd9_price_hist.csv"

TRADE_FIELDS9 = [
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
YES_TIERS = [0.60, 0.70]        # moi moc mua YES rieng 1 lan/o, chi ngay T
NO_PEAK_LOW, NO_PEAK_HIGH = 0.40, 0.70  # dinh gia tung dat de duoc tinh la "ung vien that su"
NO_DROP_BELOW = 0.40            # sau do phai tuot xuong duoi muc nay moi mua NO
MIN_PRICE, MAX_PRICE = 0.02, 0.98  # loai gia cuc doan (don bay vo ly)
FEE_RATE = 0.05
HIST_KEEP_DAYS = 3  # don rac: bo entry lich su cu hon x ngay so voi target_date


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


def load_price_hist():
    return {r["market_slug"]: r for r in C.read_csv(PRICE_HIST_CSV) if r.get("market_slug")}


def save_price_hist(hist, today):
    rows = []
    for r in hist.values():
        td = r.get("target_date") or ""
        try:
            if td and (C.parse_iso_date(today) - C.parse_iso_date(td)).days > HIST_KEEP_DAYS:
                continue  # don rac market da qua han lau
        except Exception:  # noqa: BLE001
            pass
        rows.append(r)
    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(PRICE_HIST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PRICE_HIST_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _mk_candidate(ev_slug, city, target, b, side, tier_label, price, trigger_ask, peak_ask):
    return {
        "event_slug": ev_slug, "market_slug": b["slug"], "city": city,
        "target_date": target, "bucket": b["label"], "side": side,
        "tier": tier_label, "price": price, "trigger_ask": trigger_ask,
        "peak_ask": peak_ask,
    }


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
        is_today = (target == today)

        for b in parse_buckets(ev):
            if not b["slug"] or b["ask"] is None:
                continue
            ask = b["ask"]

            # --- cap nhat lich su gia CHO MOI market (khong gioi han ngay) ---
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
                continue  # chi VAO LENH khi target_date == hom nay (ca 2 phia)

            # --- PHIA YES: theo cua nang ky, 2 moc doc lap 60/70, chi ngay T ---
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
                    slug, city, target, b, "YES", tier, price, ask, ask))

            # --- PHIA NO: tung la ung vien that su (dinh 40-70c) roi tuot xuong duoi 40c ---
            if prev_max is not None and NO_PEAK_LOW <= prev_max <= NO_PEAK_HIGH and ask < NO_DROP_BELOW:
                key = (b["slug"], "NO", "dropped")
                if key not in have_keys:
                    price = round(1 - b["bid"], 3) if b["bid"] is not None else round(1 - ask, 3)
                    if MIN_PRICE <= price <= MAX_PRICE:
                        candidates.append(_mk_candidate(
                            slug, city, target, b, "NO", "dropped", price, ask, prev_max))

    save_price_hist(price_hist, today)

    # moc/tin hieu manh hon vao truoc khi het tien ao: YES 70 > YES 60 > NO
    order = {("YES", "0.7"): 0, ("YES", "0.6"): 1, ("NO", "dropped"): 2}
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
        if c["side"] == "YES":
            tier_txt = f"{c['tier']*100:.0f}c"
            info = f"dam dong dang tin {c['trigger_ask']*100:.0f}%"
        else:
            tier_txt = "tuot < 40c"
            info = f"tung dat dinh {c['peak_ask']*100:.0f}%, gio con {c['trigger_ask']*100:.0f}%"
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "side": c["side"],
            "bucket": c["bucket"], "tier": c["tier"], "price": price, "shares": shares,
            "stake": STAKE, "fee": fee, "trigger_ask": c["trigger_ask"],
            "peak_ask": c["peak_ask"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_keys.add(key)
        print(f"  VAO LENH AO (CD9/{c['side']} {tier_txt}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} co phan "
              f"({info} | neu thang +{potential_profit:.2f}$)")
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
    with open(TRADES9_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS9, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 9 v5 — chi ngay T: YES 60/70c + NO tuot tu dinh 40-70c xuong <40c]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
