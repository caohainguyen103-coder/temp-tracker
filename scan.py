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
CRYPTO_EDGE_MIN = 0.08  # 8 điểm % ròng
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
                    "detail": (f"{ccy} > ${strike:,.0f} luc {end}; spot ${spot:,.0f}, "
                               f"DVOL {sigma*100:.0f}%; {action}; RONG {net:+.3f} sau phi"),
                    "edge": round(net, 4), "sum_ask": "", "sum_bid": "",
                    "market_prob": round((ask + bid) / 2, 4),
                    "model_prob": round(p_model, 4),
                    "volume24hr": mk.get("volume24hr"), "liquidity": mk.get("liquidityNum"),
                    "note": "mo hinh bo qua skew - tu tham dinh truoc khi vao lenh",
                })
    return rows


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = fetch_active_events()
    print(f"Quet {len(events)} event dang mo (sap theo volume 24h).")

    rows = scan_negrisk(events, now) + scan_crypto(events, now)
    rows.sort(key=lambda r: -(r["edge"] or 0))

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
