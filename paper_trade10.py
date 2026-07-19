# -*- coding: utf-8 -*-
"""
paper_trade10.py — CHIẾN DỊCH 10: xác suất ensemble GFS vs giá thị trường.
KHÔNG dùng tiền thật. Tiền ảo $1500.

Ý TƯỞNG (phương pháp đã được nhiều bot có lãi công khai sử dụng):
  Thay vì dùng dự báo ĐIỂM (1 con số) như CD3/CD5, dùng GFS ENSEMBLE
  (~31 kịch bản dự báo chạy song song, model gfs025 của Open-Meteo).
  Đếm bao nhiêu % thành viên ensemble cho Tmax rơi vào từng ô nhiệt độ
  -> đó là XÁC SUẤT mô hình của ô. So với giá Polymarket:

  - P_model - giá_ask_YES >= 8 điểm %  -> mua YES (chợ đánh giá thấp ô này)
  - giá_bid_YES - P_model >= 8 điểm %  -> mua NO  (chợ đánh giá cao ô này)

  Mỗi (ô, phía) chỉ vào 1 lần. Vào ở lead 0-2 ngày. $10/lệnh, phí 5%p(1-p).

LỊCH SỬ SỬA LUẬT:
  v1 (18/07): bản đầu tiên. EDGE_MIN=0.08, MIN_MEMBERS=10, lead 0-2.
  v2 (19/07): bản v1 vào QUÁ NHIỀU lệnh (145 lệnh mở sau ~1 ngày, giam
    1496/1500$ vốn ảo, chưa chốt được lệnh nào). Sửa 2 thứ:
    - Thêm ngân sách: 1500 -> 3000.
    - Thêm giới hạn: tối đa MAX_NEW_PER_RUN=10 lệnh mới/lần quét (ưu tiên
      lệch to nhất) + tối đa MAX_OPEN=120 lệnh đang mở toàn cục — tránh
      rải vốn loãng ra hàng trăm tín hiệu yếu.
"""
import csv
import json
import os
from datetime import datetime, timezone

import common as C
import collect

TRADES10_CSV = C.DATA_DIR + "/trades10.csv"
ENSEMBLE_API = "https://ensemble-api.open-meteo.com/v1/ensemble"
ENSEMBLE_MODEL = "gfs025"   # GFS ensemble 0.25 do, ~31 thanh vien

BUDGET = 3000.0      # v2: them ngan sach (cu 1500, bi giam het von)
STAKE = 10.0
FEE_RATE = 0.05
EDGE_MIN = 0.08      # lech toi thieu giua P_model va gia de vao lenh
MIN_MEMBERS = 10     # it hon 10 thanh vien ensemble -> khong tin, bo qua
MAX_LEAD_DAYS = 2    # chi vao lenh khi con 0-2 ngay toi ngay muc tieu
MAX_NEW_PER_RUN = 10 # v2: toi da 10 lenh moi/lan quet (uu tien lech to nhat)
MAX_OPEN = 120       # v2: toi da 120 lenh dang mo toan cuc
MIN_PRICE, MAX_PRICE = 0.02, 0.98
EXCLUDE_CITIES = {"los-angeles"}  # 18/07: bo hoan toan thi truong nay

TRADE_FIELDS10 = [
    "entry_utc", "event_slug", "market_slug", "city", "target_date", "lead_days",
    "side", "bucket", "price", "shares", "stake", "fee",
    "p_model", "market_prob", "edge", "n_members", "potential_profit",
    "status", "payout", "pnl", "settle_utc",
]


def fetch_ensemble_daily_max(lat, lon):
    """Tra ve dict {ngay_local: [tmax_C cua tung thanh vien]} tu GFS ensemble."""
    j = C.http_get_json(ENSEMBLE_API, {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "hourly": "temperature_2m", "models": ENSEMBLE_MODEL,
        "timezone": "auto", "forecast_days": 4,
    })
    try:
        hourly = j["hourly"]
        times = hourly["time"]
    except (TypeError, KeyError):
        return {}
    member_keys = [k for k in hourly
                   if k == "temperature_2m" or k.startswith("temperature_2m_member")]
    out = {}
    for key in member_keys:
        vals = hourly.get(key)
        if not vals:
            continue
        daily = {}
        for t, v in zip(times, vals):
            if v is None:
                continue
            d = t[:10]
            if d not in daily or v > daily[d]:
                daily[d] = v
        for d, mx in daily.items():
            out.setdefault(d, []).append(mx)
    return out


def bucket_probability(bucket, member_maxes_c, precision):
    """% thanh vien ensemble cho Tmax roi vao o nay (theo dung don vi cua o)."""
    if not member_maxes_c:
        return None
    hit = 0
    for tc in member_maxes_c:
        native = C.c_to_f(tc) if bucket["unit"] == "F" else tc
        if C.bucket_contains(bucket, native, precision):
            hit += 1
    return hit / len(member_maxes_c)


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def settle(trades):
    """Chot lenh dua vao data/results.csv (giong CD9)."""
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
        side = (t.get("side") or "YES").upper()
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


def enter(trades, now, events=None, ensemble_fetcher=None, station_resolver=None):
    have = {(t["market_slug"], (t.get("side") or "").upper()) for t in trades}
    today = C.parse_iso_date(now[:10])
    if events is None:
        events = collect.fetch_temperature_events()
    if ensemble_fetcher is None:
        ensemble_fetcher = fetch_ensemble_daily_max
    station_cache = C.load_station_cache()
    default_resolver = station_resolver is None
    if default_resolver:
        def station_resolver(ev):
            return C.resolve_station(ev, station_cache)

    ens_cache = {}  # (lat4, lon4) -> {ngay: [tmax...]}
    candidates = []
    for ev in events:
        slug = ev.get("slug", "")
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target:
            continue
        if city in EXCLUDE_CITIES:
            continue  # bo qua thi truong bi loai
        try:
            lead = (C.parse_iso_date(target) - today).days
        except ValueError:
            continue
        if lead < 0 or lead > MAX_LEAD_DAYS:
            continue

        station = station_resolver(ev)
        if not station:
            continue
        precision = station.get("precision") or "whole"
        loc = (round(station["lat"], 2), round(station["lon"], 2))
        if loc not in ens_cache:
            ens_cache[loc] = ensemble_fetcher(station["lat"], station["lon"])
        members = ens_cache[loc].get(target)
        if not members or len(members) < MIN_MEMBERS:
            continue

        for mk in ev.get("markets", []):
            b = C.parse_bucket(mk.get("groupItemTitle"))
            if b is None or mk.get("closed") or not mk.get("active"):
                continue
            mslug = mk.get("slug")
            ask = mk.get("bestAsk")
            bid = mk.get("bestBid")
            if not mslug or ask is None:
                continue
            ask = float(ask)
            bid = float(bid) if bid is not None else None
            p_model = bucket_probability(b, members, precision)
            if p_model is None:
                continue

            # YES: mo hinh tin hon cho
            edge_yes = p_model - ask
            if edge_yes >= EDGE_MIN and (mslug, "YES") not in have \
                    and MIN_PRICE <= ask <= MAX_PRICE:
                candidates.append({
                    "event_slug": slug, "market_slug": mslug, "city": city,
                    "target_date": target, "lead_days": lead, "side": "YES",
                    "bucket": C.bucket_label(b), "price": round(ask, 3),
                    "p_model": round(p_model, 3), "market_prob": round(ask, 3),
                    "edge": round(edge_yes, 3), "n_members": len(members),
                })

            # NO: cho tin hon mo hinh (dung bid lam xac suat cho dang "ban")
            if bid is not None:
                edge_no = bid - p_model
                no_price = round(1 - bid, 3)
                if edge_no >= EDGE_MIN and (mslug, "NO") not in have \
                        and MIN_PRICE <= no_price <= MAX_PRICE:
                    candidates.append({
                        "event_slug": slug, "market_slug": mslug, "city": city,
                        "target_date": target, "lead_days": lead, "side": "NO",
                        "bucket": C.bucket_label(b), "price": no_price,
                        "p_model": round(p_model, 3), "market_prob": round(bid, 3),
                        "edge": round(edge_no, 3), "n_members": len(members),
                    })

    if default_resolver:
        C.save_station_cache(station_cache)  # tranh goi lai API tram o lan sau

    candidates.sort(key=lambda x: -x["edge"])  # lech to vao truoc khi het tien
    added = 0
    n_open = sum(1 for t in trades if t["status"] == "open")
    for c in candidates:
        if added >= MAX_NEW_PER_RUN:
            print(f"  [GIOI HAN] (CD10 v2) da vao {MAX_NEW_PER_RUN} lenh/lan quet, dung")
            break
        if n_open + added >= MAX_OPEN:
            print(f"  [GIOI HAN] (CD10 v2) dang mo {n_open + added} lenh >= tran {MAX_OPEN}, dung")
            break
        key = (c["market_slug"], c["side"])
        if key in have:
            continue
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(FEE_RATE * price * (1 - price) * shares, 4)
        potential_profit = round(shares - STAKE - fee, 2)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO] (CD10) cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "event_slug": c["event_slug"],
            "market_slug": c["market_slug"], "city": c["city"],
            "target_date": c["target_date"], "lead_days": c["lead_days"],
            "side": c["side"], "bucket": c["bucket"], "price": price,
            "shares": shares, "stake": STAKE, "fee": fee,
            "p_model": c["p_model"], "market_prob": c["market_prob"],
            "edge": c["edge"], "n_members": c["n_members"],
            "potential_profit": potential_profit,
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have.add(key)
        print(f"  VAO LENH AO (CD10/{c['side']}): {c['city']} {c['target_date']} "
              f"{c['side']} '{c['bucket']}' @{price} x{shares} "
              f"(ensemble {c['p_model']*100:.0f}% vs cho {c['market_prob']*100:.0f}%, "
              f"lech {c['edge']*100:.0f}%, {c['n_members']} thanh vien | "
              f"neu thang +{potential_profit:.2f}$)")
        added += 1
    return added


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES10_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES10_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS10, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 10 v2 — ensemble GFS, lech >= {EDGE_MIN*100:.0f}%, max {MAX_NEW_PER_RUN} lenh/quet, tran {MAX_OPEN} lenh mo, $3000 ao]")
    print(f"Chot {n_settled}, vao moi {n_new} | {won} thang / {lost} thua | "
          f"lai/lo {realized:+.2f} | kha dung {BUDGET + realized - open_cost:.2f}/{BUDGET:.0f}")


if __name__ == "__main__":
    main()
