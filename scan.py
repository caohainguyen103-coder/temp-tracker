# -*- coding: utf-8 -*-
"""
scan.py — Bot quét cơ hội trên Polymarket (chạy tự động mỗi giờ).
CHỈ QUÉT VÀ BÁO CÁO — không tự đặt lệnh. Kết quả: data/opportunities.csv.

PHIÊN BẢN 2 — TÍNH LÃI RÒNG SAU PHÍ (đã kiểm chứng công thức phí chính thức
tại docs.polymarket.com/trading/fees: phí taker = C × rate × p × (1−p);
Weather/Economics/Culture rate 0.05, Crypto 0.07, Sports 0.03,
Geopolitics MIỄN PHÍ. Maker không mất phí.)

Ngách 1 — ARBITRAGE TỔNG XÁC SUẤT (neg-risk):
  Mua đủ mọi ô của event loại trừ nhau -> chắc chắn nhận $1.
  edge_ròng = 1 − Σask − Σ(rate×ask×(1−ask)). Chỉ báo khi edge_ròng >= 1%.
  Bài học thực tế 09/07: Wellington tổng ask 0.96 nhìn như lãi 4%,
  nhưng phí thời tiết ăn 3.95% -> ròng ~0. Thị trường MIỄN PHÍ (geopolitics)
  mới là nơi ngách này thực sự sống.

Ngách 2 — CRYPTO vs THỊ TRƯỜNG QUYỀN CHỌN (Deribit):
  P(S_T > K) = N(d2), sigma = DVOL, spot = index Deribit.
  edge_ròng = |P_model − giá| − phí taker. Chỉ báo khi >= 8 điểm %.
  (Xấp xỉ bỏ qua skew — tự thẩm định trước khi vào lệnh.)
"""
import json
import math
import re
from datetime import datetime, timezone

import common as C

DERIBIT = "https://www.deribit.com/api/v2/public"
OPP_CSV = C.DATA_DIR + "/opportunities.csv"

OPP_FIELDS = [
    "scan_utc", "kind", "event_slug", "detail",
    "edge", "sum_ask", "sum_bid", "market_prob", "model_prob",
    "volume24hr", "liquidity", "note",
]

NET_EDGE_MIN = 0.01     # lãi ròng >= 1%/bộ mới báo
SUM_BID_MIN = 1.04      # chiều bán (tham khảo)
CRYPTO_EDGE_MIN = 0.05  # 5 điểm % ròng (hạ từ 8% để gom nhiều dữ liệu đo lường
                        # hơn cho chiến dịch TIỀN ẢO; tiền thật nên dùng ngưỡng cao hơn)
MIN_LIQUIDITY = 1000


def market_fee_rate(mk):
    """Phí taker của market: feeSchedule.rate nếu feesEnabled, ngược lại 0.
    (Đã kiểm chứng field trên response thật: feesEnabled, feeSchedule.rate.)"""
    if not mk.get("feesEnabled"):
        return 0.0
    try:
        return float((mk.get("feeSchedule") or {}).get("rate") or 0.05)
    except (TypeError, ValueError):
        return 0.05


def taker_fee(rate, price):
    return rate * price * (1.0 - price)


# ---------------------------------------------------------------------------
def fetch_active_events(max_pages=6):
    events, offset = [], 0
    for _ in range(max_pages):
        page = C.http_get_json(f"{C.GAMMA}/events", {
            "closed": "false", "active": "true",
            "order": "volume24hr", "ascending": "false",
            "limit": 100, "offset": offset,
        })
        if not page:
            break
        events.extend(page)
        if len(page) < 100:
            break
        offset += 100
    return events


def scan_negrisk(events, now):
    rows = []
    for ev in events:
        if not ev.get("negRisk") or not ev.get("enableOrderBook"):
            continue
        if (ev.get("liquidity") or 0) < MIN_LIQUIDITY:
            continue
        asks, bids, fees, n_active = [], [], [], 0
        for mk in ev.get("markets", []):
            if mk.get("closed") or not mk.get("acceptingOrders"):
                continue
            n_active += 1
            a, b = mk.get("bestAsk"), mk.get("bestBid")
            if a is None or b is None:
                asks = []
                break
            a, b = float(a), float(b)
            asks.append(a)
            bids.append(b)
            fees.append(taker_fee(market_fee_rate(mk), a))
        if not asks or n_active < 2:
            continue
        s_ask, s_bid, s_fee = sum(asks), sum(bids), sum(fees)
        net = 1.0 - s_ask - s_fee
        if net >= NET_EDGE_MIN:
            rows.append({
                "scan_utc": now, "kind": "negrisk_buy_all",
                "event_slug": ev.get("slug", ""),
                "detail": (f"{n_active} o | tong mua {s_ask:.3f} + phi {s_fee:.3f} "
                           f"= {s_ask+s_fee:.3f} | nhan 1.000 | RONG {net:+.3f}"),
                "edge": round(net, 4), "sum_ask": round(s_ask, 4),
                "sum_bid": round(s_bid, 4), "market_prob": "", "model_prob": "",
                "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
                "note": ("MIEN PHI (geopolitics)" if s_fee == 0 else
                         "da tru phi taker") + "; kiem tra do sau so lenh + gia con hieu luc",
            })
        elif -0.01 <= net < NET_EDGE_MIN:
            # "cận kề": chưa đáng vào tiền nhưng ghi lại để thấy bot đang săn
            rows.append({
                "scan_utc": now, "kind": "negrisk_gan_dat",
                "event_slug": ev.get("slug", ""),
                "detail": (f"{n_active} o | mua {s_ask:.3f} + phi {s_fee:.3f} "
                           f"-> RONG {net:+.3f} (thieu {NET_EDGE_MIN - net:.3f})"),
                "edge": round(net, 4), "sum_ask": round(s_ask, 4),
                "sum_bid": round(s_bid, 4), "market_prob": "", "model_prob": "",
                "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
                "note": "CHUA DANG VAO - chi theo doi",
            })
        elif s_bid >= SUM_BID_MIN:
            rows.append({
                "scan_utc": now, "kind": "negrisk_sell_all",
                "event_slug": ev.get("slug", ""),
                "detail": f"{n_active} o, tong bid {s_bid:.3f} > 1 (chua tru phi)",
                "edge": round(s_bid - 1, 4), "sum_ask": round(s_ask, 4),
                "sum_bid": round(s_bid, 4), "market_prob": "", "model_prob": "",
                "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
                "note": "can split co phan (nang cao) - chi tham khao",
            })
    return rows


# ---------------------------------------------------------------------------
CRYPTO_RE = re.compile(r"^(bitcoin|ethereum)-above-on-", re.I)
STRIKE_RE = re.compile(r"above \$?([\d,]+(?:\.\d+)?)", re.I)
CCY = {"bitcoin": "BTC", "ethereum": "ETH"}


def norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def deribit_spot_and_vol(ccy):
    idx = C.http_get_json(f"{DERIBIT}/get_index_price",
                          {"index_name": f"{ccy.lower()}_usd"})
    try:
        spot = float(idx["result"]["index_price"])
    except (TypeError, KeyError):
        return None, None
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    vol = C.http_get_json(f"{DERIBIT}/get_volatility_index_data", {
        "currency": ccy, "resolution": 3600,
        "start_timestamp": now_ms - 6 * 3600 * 1000, "end_timestamp": now_ms,
    })
    try:
        sigma = float(vol["result"]["data"][-1][4]) / 100.0
    except (TypeError, KeyError, IndexError):
        return spot, None
    return spot, sigma


def prob_above(spot, strike, sigma, t_years):
    if not spot or not sigma or t_years <= 0:
        return None
    d2 = (math.log(spot / strike) - 0.5 * sigma * sigma * t_years) / (sigma * math.sqrt(t_years))
    return norm_cdf(d2)


def scan_crypto(events, now):
    rows = []
    cache = {}
    for ev in events:
        m = CRYPTO_RE.match(ev.get("ticker") or "")
        if not m:
            continue
        ccy = CCY[m.group(1).lower()]
        end = ev.get("endDate")
        try:
            t_end = datetime.fromisoformat(end.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            continue
        t_years = (t_end - datetime.now(timezone.utc)).total_seconds() / (365.25 * 86400)
        if t_years <= 0:
            continue
        if ccy not in cache:
            cache[ccy] = deribit_spot_and_vol(ccy)
        spot, sigma = cache[ccy]
        if spot is None or sigma is None:
            continue
        for mk in ev.get("markets", []):
            if mk.get("closed"):
                continue
            sm = STRIKE_RE.search(mk.get("question") or "")
            a, b = mk.get("bestAsk"), mk.get("bestBid")
            if not sm or a is None or b is None:
                continue
            strike = float(sm.group(1).replace(",", ""))
            p_model = prob_above(spot, strike, sigma, t_years)
            if p_model is None:
                continue
            ask, bid = float(a), float(b)
            rate = market_fee_rate(mk)
            # mua YES tai ask / mua NO tai (1-bid), tru phi taker tuong ung
            net_yes = p_model - ask - taker_fee(rate, ask)
            q = 1.0 - bid
            net_no = bid - p_model - taker_fee(rate, q)
            net, action = ((net_yes, f"mua YES @{ask:.3f}")
                           if net_yes >= net_no else (net_no, f"mua NO @{q:.3f}"))
            if net >= CRYPTO_EDGE_MIN:
                rows.append({
                    "scan_utc": now, "kind": f"crypto_{ccy.lower()}",
                    "event_slug": mk.get("slug", ""),
                    "side": "YES" if net is net_yes else "NO",
                    "price": round(ask if net is net_yes else q, 4),
                    "end_date": end, "ccy": ccy,
                    "detail": (f"{ccy} > ${strike:,.0f} luc {end}; spot ${spot:,.0f}, "
                               f"DVOL {sigma*100:.0f}%; {action}; RONG {net:+.3f} sau phi"),
                    "edge": round(net, 4), "sum_ask": "", "sum_bid": "",
                    "market_prob": round((ask + bid) / 2, 4),
                    "model_prob": round(p_model, 4),
                    "volume24hr": mk.get("volume24hr"), "liquidity": mk.get("liquidityNum"),
                    "note": "mo hinh bo qua skew - tu tham dinh truoc khi vao lenh",
                })
    return rows


# ---------------------------------------------------------------------------
# GIẢ LẬP ARBITRAGE $200 (tiền ảo): mỗi khi thấy negrisk_buy_all lãi ròng
# dương, "mua trọn bộ" ảo — tối đa $50/cơ hội và 25 bộ (giả định khiêm tốn
# về độ sâu sổ lệnh). Tiền về khi event kết thúc (endDate).
# ---------------------------------------------------------------------------
ARB_CSV = C.DATA_DIR + "/arb_trades.csv"
ARB_FIELDS = ["entry_utc", "event_slug", "end_date", "sets", "cost_per_set",
              "total_cost", "payout_per_set", "locked_profit", "status", "settle_utc"]
ARB_BUDGET = 200.0
ARB_MAX_PER_OP = 50.0
ARB_MAX_SETS = 25


def paper_arb(rows, events, now):
    import csv as _csv
    trades = C.read_csv(ARB_CSV)
    # 1) giải phóng vốn: event đã kết thúc -> settled
    for t in trades:
        if t["status"] == "open" and t["end_date"] and t["end_date"] < now:
            t["status"], t["settle_utc"] = "settled", now
    # 2) tiền khả dụng
    cash = ARB_BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["total_cost"])
        else:
            cash += float(t["locked_profit"])
    ends = {ev.get("slug"): ev.get("endDate", "") for ev in events}
    held = {t["event_slug"] for t in trades if t["status"] == "open"}
    n_new = 0
    for r in rows:
        if r["kind"] != "negrisk_buy_all" or r["event_slug"] in held:
            continue
        cost_per_set = 1.0 - float(r["edge"])  # = sum_ask + phí
        alloc = min(ARB_MAX_PER_OP, cash)
        sets = min(int(alloc // cost_per_set), ARB_MAX_SETS)
        if sets < 1:
            continue
        total = round(sets * cost_per_set, 2)
        trades.append({
            "entry_utc": now, "event_slug": r["event_slug"],
            "end_date": ends.get(r["event_slug"], ""), "sets": sets,
            "cost_per_set": round(cost_per_set, 4), "total_cost": total,
            "payout_per_set": 1.0,
            "locked_profit": round(sets * float(r["edge"]), 2),
            "status": "open", "settle_utc": "",
        })
        cash -= total
        held.add(r["event_slug"])
        n_new += 1
        print(f"  [ARB AO] mua {sets} bo '{r['event_slug']}' @ {cost_per_set:.3f} "
              f"-> loi khoa chat {sets * float(r['edge']):.2f} USD")
    import os as _os
    _os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(ARB_CSV, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=ARB_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)
    realized = sum(float(t["locked_profit"]) for t in trades if t["status"] != "open")
    locked = sum(float(t["locked_profit"]) for t in trades if t["status"] == "open")
    print(f"  [ARB AO] vi the moi: {n_new} | loi da ve: {realized:+.2f} | dang khoa: {locked:+.2f}")


# ---------------------------------------------------------------------------
# GIẢ LẬP CRYPTO $200 (tiền ảo): mỗi tín hiệu lệch >= 8 điểm % so với Deribit
# (sau phí) -> mua ảo $10 đúng phía bot chỉ. Chốt khi thị trường phân giải.
# ---------------------------------------------------------------------------
CRYPTO_TRADES_CSV = C.DATA_DIR + "/crypto_trades.csv"
CT_FIELDS = ["entry_utc", "market_slug", "ccy", "side", "price", "shares",
             "stake", "fee", "model_prob", "edge", "end_date",
             "status", "payout", "pnl", "settle_utc"]
CT_BUDGET = 200.0
CT_STAKE = 10.0
CT_MAX_PER_SCAN = 5


def crypto_resolved_side(slug):
    j = C.http_get_json(f"{C.GAMMA}/markets", {"slug": slug})
    try:
        mk = j[0]
        prices = json.loads(mk.get("outcomePrices") or "[]")
        y = float(prices[0])
        if mk.get("closed") and y >= 0.99:
            return "YES"
        if mk.get("closed") and y <= 0.01:
            return "NO"
    except (TypeError, KeyError, IndexError, ValueError):
        pass
    return None


def paper_crypto(rows, now):
    import csv as _csv, os as _os
    trades = C.read_csv(CRYPTO_TRADES_CSV)
    for t in trades:
        if t["status"] != "open" or not t["end_date"] or t["end_date"] >= now:
            continue
        winner = crypto_resolved_side(t["market_slug"])
        if winner is None:
            continue
        stake, fee, shares = float(t["stake"]), float(t["fee"]), float(t["shares"])
        if winner == t["side"]:
            t["status"], t["payout"] = "won", round(shares, 2)
            t["pnl"] = round(shares - stake - fee, 2)
        else:
            t["status"], t["payout"] = "lost", 0.0
            t["pnl"] = round(-(stake + fee), 2)
        t["settle_utc"] = now
    cash = CT_BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    held = {t["market_slug"] for t in trades}
    n = 0
    for r in rows:
        if not r["kind"].startswith("crypto_") or r["event_slug"] in held:
            continue
        if n >= CT_MAX_PER_SCAN:
            break
        price = float(r["price"])
        shares = round(CT_STAKE / price, 2)
        fee = round(0.07 * price * (1 - price) * shares, 4)
        if cash < CT_STAKE + fee:
            break
        trades.append({
            "entry_utc": now, "market_slug": r["event_slug"], "ccy": r.get("ccy", ""),
            "side": r["side"], "price": price, "shares": shares,
            "stake": CT_STAKE, "fee": fee,
            "model_prob": r.get("model_prob", ""), "edge": r["edge"],
            "end_date": r.get("end_date", ""),
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        cash -= CT_STAKE + fee
        held.add(r["event_slug"])
        n += 1
        print(f"  [CRYPTO AO] {r['side']} {r['event_slug']} @{price} x{shares}")
    _os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(CRYPTO_TRADES_CSV, "w", newline="", encoding="utf-8") as f:
        w = _csv.DictWriter(f, fieldnames=CT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)
    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] not in ("open",))
    print(f"  [CRYPTO AO] vao moi {n} | lai/lo da chot: {realized:+.2f} USD")


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = fetch_active_events()
    print(f"Quet {len(events)} event dang mo (sap theo volume 24h).")

    rows = scan_negrisk(events, now) + scan_crypto(events, now)
    rows.sort(key=lambda r: -(r["edge"] or 0))

    paper_arb(rows, events, now)
    paper_crypto(rows, now)

    if rows:
        C.append_csv(OPP_CSV, OPP_FIELDS, rows)
        print(f"\n=== TIM THAY {len(rows)} co hoi LAI RONG DUONG ===")
        for r in rows[:15]:
            print(f"  [{r['kind']}] rong={r['edge']:+.3f} {r['event_slug']}")
            print(f"      {r['detail']}")
    else:
        print("Khong co co hoi nao co lai RONG (sau phi) o lan quet nay."
              " Day la binh thuong - bot tiep tuc quet moi gio.")


if __name__ == "__main__":
    main()
