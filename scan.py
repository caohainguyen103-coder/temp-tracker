# -*- coding: utf-8 -*-
"""
scan.py — Bot quét cơ hội trên Polymarket (chạy tự động mỗi 4 giờ).
CHỈ QUÉT VÀ BÁO CÁO — không tự đặt lệnh. Kết quả ghi vào data/opportunities.csv.

Ngách 1 — ARBITRAGE TỔNG XÁC SUẤT (neg-risk):
  Event nhiều kết cục loại trừ nhau (negRisk=true) phải có tổng xác suất = 100%.
  Nếu tổng giá MUA (best ask) của tất cả các ô < $1: mua mỗi ô 1 cổ phần
  -> chắc chắn nhận về $1 dù kết quả thế nào. Lãi = 1 − tổng giá mua − phí.
  Ngưỡng báo: tổng ask <= 0.97 (chừa chỗ cho phí + trượt giá).
  Chiều ngược (tổng bid >= 1.03) cũng báo, nhưng bán cần sẵn cổ phần/split.

Ngách 2 — CRYPTO vs THỊ TRƯỜNG QUYỀN CHỌN (Deribit):
  Thị trường "Bitcoin/Ethereum above $X on [ngày]" phân giải bằng nến Binance
  16:00 UTC (đã kiểm chứng mô tả event). Xác suất "chuyên nghiệp" của cùng
  sự kiện tính từ Deribit: P(S_T > K) = N(d2) với spot = index Deribit,
  sigma = chỉ số DVOL (vol kỳ vọng 30 ngày, %/năm), T = thời gian đến 16:00 UTC.
  Xấp xỉ này BỎ QUA skew/term-structure -> chỉ báo khi lệch >= 8 điểm %.
  Đây là tín hiệu để BẠN xem xét, không phải lệnh tự động.

Chỉ dùng thư viện chuẩn Python. Nguồn: gamma-api.polymarket.com,
www.deribit.com/api/v2/public (đều công khai, không cần key).
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

SUM_ASK_MAX = 0.97      # ngưỡng báo arb mua toàn bộ
SUM_BID_MIN = 1.03      # ngưỡng báo chiều bán
CRYPTO_EDGE_MIN = 0.08  # 8 điểm % lệch mới báo (vì mô hình bỏ qua skew)
MIN_LIQUIDITY = 1000    # bỏ qua event thanh khoản quá mỏng


# ---------------------------------------------------------------------------
# Ngách 1: quét neg-risk sum
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
        asks, bids, n_active = [], [], 0
        for mk in ev.get("markets", []):
            if mk.get("closed") or not mk.get("acceptingOrders"):
                continue
            n_active += 1
            a, b = mk.get("bestAsk"), mk.get("bestBid")
            if a is None or b is None:
                asks, bids = [], []
                break  # thiếu báo giá 1 ô -> tổng không còn ý nghĩa
            asks.append(float(a))
            bids.append(float(b))
        if not asks or n_active < 2:
            continue
        s_ask, s_bid = sum(asks), sum(bids)
        if s_ask <= SUM_ASK_MAX:
            rows.append({
                "scan_utc": now, "kind": "negrisk_buy_all",
                "event_slug": ev.get("slug", ""),
                "detail": f"{n_active} o, mua het = {s_ask:.3f}, tra ve 1.000",
                "edge": round(1 - s_ask, 4), "sum_ask": round(s_ask, 4),
                "sum_bid": round(s_bid, 4), "market_prob": "", "model_prob": "",
                "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
                "note": "kiem tra do sau so lenh truoc khi vao; phi lam giam lai",
            })
        elif s_bid >= SUM_BID_MIN:
            rows.append({
                "scan_utc": now, "kind": "negrisk_sell_all",
                "event_slug": ev.get("slug", ""),
                "detail": f"{n_active} o, ban het = {s_bid:.3f} > 1.000",
                "edge": round(s_bid - 1, 4), "sum_ask": round(s_ask, 4),
                "sum_bid": round(s_bid, 4), "market_prob": "", "model_prob": "",
                "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
                "note": "can split co phan (nang cao) - chi tham khao",
            })
    return rows


# ---------------------------------------------------------------------------
# Ngách 2: crypto vs Deribit
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
        sigma = float(vol["result"]["data"][-1][4]) / 100.0  # close, %/nam
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
        end = ev.get("endDate")  # da kiem chung: 16:00:00Z ngay muc tieu
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
            edge_buy_yes = p_model - ask   # model noi xac suat cao hon gia mua Yes
            edge_buy_no = bid - p_model    # model noi xac suat thap hon gia ban Yes
            edge, action = ((edge_buy_yes, f"mua YES @{ask:.3f}")
                            if edge_buy_yes >= edge_buy_no
                            else (edge_buy_no, f"mua NO @{1-bid:.3f}"))
            if edge >= CRYPTO_EDGE_MIN:
                rows.append({
                    "scan_utc": now, "kind": f"crypto_{ccy.lower()}",
                    "event_slug": mk.get("slug", ""),
                    "detail": f"{ccy} > ${strike:,.0f} luc {end}; spot ${spot:,.0f}, "
                              f"DVOL {sigma*100:.0f}%; {action}",
                    "edge": round(edge, 4), "sum_ask": "", "sum_bid": "",
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
        print(f"\n=== TIM THAY {len(rows)} co hoi (xem data/opportunities.csv) ===")
        for r in rows[:15]:
            print(f"  [{r['kind']}] edge={r['edge']:+.3f} {r['event_slug']}")
            print(f"      {r['detail']}")
    else:
        print("Khong co co hoi nao vuot nguong o lan quet nay (binh thuong —"
              " cac lech gia ro rang thuong bi bot chuyen nghiep hot trong vai giay).")


if __name__ == "__main__":
    main()
