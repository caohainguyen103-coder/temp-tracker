# -*- coding: utf-8 -*-
"""
paper_trade8.py — CHIEN DICH 8: the thao, doi chieu Pinnacle vs Polymarket.
Tien ao $500. KHONG dung tien that. Chay tu dong sau cac chien dich thoi tiet.

Y tuong: Pinnacle la nha cai "sac" (gan nhu khong loi cho ai choi), gia cua
ho sau khi khu vig (bo phan loi nha cai) la uoc luong xac suat that chinh
xac nhat co san mien phi. Neu gia Polymarket (dam dong) RE HON xac suat
that cua Pinnacle mot khoang du lon -> mua ben do (gia tri ky vong duong).

Quy tac (co dinh, khach quan):
  - Chi ap dung giai da xac nhan cau truc (xem sports_common.SPORTS):
    hien tai World Cup 2026 (bong da, co hoa) va MLB (bong chay, khong hoa).
  - Voi moi tran chua dau (market con mo, active, chua closed, sportsMarketType
    == "moneyline" — loai het spread/totals/nrfi/halftime...):
      lay keo Pinnacle, khu vig -> xac suat cong bang cho tung ket qua.
      canh = xac_suat_cong_bang - gia_mua_thuc_te.
      canh >= 0.05 (5 diem %) -> vao lenh.
    * Bong da (moi ket qua la 1 market Yes/No rieng): mua YES @ bestAsk.
    * The thao 2 chieu (1 market, outcomes=[doi A, doi B]): cuoc doi A =
      mua YES @ bestAsk; cuoc doi B = mua NO @ (1 - bestBid) — dung quy
      uoc "NO" giong het cac chien dich thoi tiet truoc.
  - Moi lenh $10 ao. Ngan sach $500 dung chung cho ca campaign (moi giai).
    Phi taker lay THAT tu feeSchedule.rate cua tung market (bong da 5%,
    MLB 3% — da kiem chung khac nhau that).
  - Thang: side YES thi thang khi outcome[0] xay ra; side NO thi thang
    khi outcome[0] KHONG xay ra (tuc doi/ket qua con lai thang).
  - Moi market (slug) chi vao 1 lenh, khong lap.

Ket qua ghi vao data/trades8.csv.
"""
import csv
import json
import os
from datetime import datetime, timezone

import common as C
import sports_common as S

TRADES8_CSV = C.DATA_DIR + "/trades8.csv"

TRADE_FIELDS8 = [
    "entry_utc", "market_slug", "match", "side_team", "commence_utc",
    "side", "ask", "shares", "stake", "fee",
    "pinnacle_fair_prob", "pinnacle_overround", "edge",
    "status", "payout", "pnl", "settle_utc",
]

BUDGET = 500.0
STAKE = 10.0
EDGE_MIN = 0.05          # canh toi thieu 5 diem % giua Pinnacle va Polymarket
MIN_ASK, MAX_ASK = 0.02, 0.95
DEFAULT_FEE_RATE = 0.05  # du phong neu market thieu feeSchedule


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


def _fee_rate(mkt):
    fs = mkt.get("feeSchedule") or {}
    r = fs.get("rate")
    return float(r) if r is not None else DEFAULT_FEE_RATE


def _candidates_soccer_style(moneyline_markets, fair_probs):
    """Bong da: moi market = 1 ket qua (Yes/No rieng)."""
    out = []
    for mkt in moneyline_markets:
        slug = mkt.get("slug")
        if not slug:
            continue
        outcome = S.market_outcome_key(mkt)
        fair = fair_probs.get(outcome)
        if fair is None:
            continue
        ask = mkt.get("bestAsk")
        if ask is None:
            continue
        ask = float(ask)
        if not (MIN_ASK <= ask <= MAX_ASK):
            continue
        edge = round(fair - ask, 4)
        out.append({
            "slug": slug, "outcome": outcome, "side": "YES",
            "price": ask, "fair": fair, "edge": edge,
            "fee_rate": _fee_rate(mkt),
        })
    return out


def _candidates_twoway_style(mkt, fair_probs):
    """The thao 2 chieu: 1 market, outcomes=[doi A, doi B]."""
    slug = mkt.get("slug")
    if not slug:
        return []
    try:
        outcomes = json.loads(mkt.get("outcomes") or "[]")
    except (ValueError, TypeError):
        return []
    if len(outcomes) != 2:
        return []
    team_a, team_b = outcomes
    bid, ask = mkt.get("bestBid"), mkt.get("bestAsk")
    fee_rate = _fee_rate(mkt)
    out = []
    fair_a = fair_probs.get(team_a)
    if fair_a is not None and ask is not None:
        ask = float(ask)
        if MIN_ASK <= ask <= MAX_ASK:
            edge = round(fair_a - ask, 4)
            out.append({"slug": slug, "outcome": team_a, "side": "YES",
                         "price": ask, "fair": fair_a, "edge": edge,
                         "fee_rate": fee_rate})
    fair_b = fair_probs.get(team_b)
    if fair_b is not None and bid is not None:
        price_b = round(1 - float(bid), 3)
        if MIN_ASK <= price_b <= MAX_ASK:
            edge = round(fair_b - price_b, 4)
            out.append({"slug": slug, "outcome": team_b, "side": "NO",
                         "price": price_b, "fair": fair_b, "edge": edge,
                         "fee_rate": fee_rate})
    return out


def enter(trades, now):
    have_slugs = {t["market_slug"] for t in trades}
    candidates = []
    for sport in S.SPORTS:
        pinnacle = S.fetch_pinnacle_odds(sport["odds_sport_key"])
        if not pinnacle:
            print(f"  [CD8] Khong lay duoc keo Pinnacle cho {sport['label']}")
            continue
        pm_events = S.list_pm_matches(sport["pm_series_slug"], closed=False)
        for ev in pm_events:
            teams = ev.get("teams") or []
            if len(teams) != 2:
                continue
            team_a_name, team_b_name = teams[0]["name"], teams[1]["name"]
            rec = S.find_pinnacle_for_match(pinnacle, team_a_name, team_b_name)
            if not rec:
                continue
            moneyline_markets = [
                m for m in ev.get("markets", [])
                if m.get("sportsMarketType") == "moneyline"
                and not m.get("closed") and m.get("active")
            ]
            if len(moneyline_markets) >= 2:
                cs = _candidates_soccer_style(moneyline_markets, rec["p"])
            elif len(moneyline_markets) == 1:
                cs = _candidates_twoway_style(moneyline_markets[0], rec["p"])
            else:
                continue
            for c in cs:
                if c["slug"] in have_slugs or c["edge"] < EDGE_MIN:
                    continue
                candidates.append({
                    **c, "match": ev.get("title", ""),
                    "commence": rec.get("commence_time") or "",
                    "label": sport["label"],
                })

    candidates.sort(key=lambda x: -x["edge"])  # canh lon nhat vao truoc
    added = 0
    for c in candidates:
        if c["slug"] in have_slugs:
            continue  # phong khi ca 2 phia cung market deu vao candidates
        price = c["price"]
        shares = round(STAKE / price, 2)
        fee = round(c["fee_rate"] * price * (1 - price) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO CD8] cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "market_slug": c["slug"], "match": c["match"],
            "side_team": c["outcome"], "commence_utc": c["commence"],
            "side": c["side"], "ask": price, "shares": shares,
            "stake": STAKE, "fee": fee,
            "pinnacle_fair_prob": round(c["fair"], 4),
            "pinnacle_overround": "", "edge": c["edge"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_slugs.add(c["slug"])
        print(f"  VAO LENH AO (CD8/{c['label']}): {c['match']} - "
              f"{c['side']} '{c['outcome']}' @{price} x{shares} co phan | "
              f"Pinnacle {c['fair']*100:.1f}% vs Polymarket {price*100:.1f}% "
              f"(canh +{c['edge']*100:.1f}đ%)")
        added += 1
    return added


def settle(trades):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for t in trades:
        if t["status"] != "open":
            continue
        mkt = S.fetch_market_by_slug(t["market_slug"])
        if not mkt or not mkt.get("closed"):
            continue
        try:
            prices = json.loads(mkt.get("outcomePrices") or "[]")  # ["1","0"] hoac ["0","1"]
            yes_price = float(prices[0])
        except (ValueError, IndexError, TypeError):
            continue
        stake, fee, shares = float(t["stake"]), float(t["fee"]), float(t["shares"])
        side = (t.get("side") or "YES").upper()
        win = (yes_price >= 0.5) if side == "YES" else (yes_price < 0.5)
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


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    trades = C.read_csv(TRADES8_CSV)
    for t in trades:
        t.setdefault("status", "open")

    n_settled = settle(trades)
    n_new = enter(trades, now)

    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(TRADES8_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=TRADE_FIELDS8, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)

    realized = sum(float(t["pnl"] or 0) for t in trades if t["status"] != "open")
    open_cost = sum(float(t["stake"]) + float(t["fee"]) for t in trades
                    if t["status"] == "open")
    won = sum(1 for t in trades if t["status"] == "won")
    lost = sum(1 for t in trades if t["status"] == "lost")
    print(f"\n[CHIEN DICH 8 — The thao, canh Pinnacle >= 5%, $500 ao]")
    print(f"SO GIAO DICH AO: chot {n_settled}, vao moi {n_new}")
    print(f"Da chot: {won} thang / {lost} thua | Lai/lo da chot: {realized:+.2f} USD")
    print(f"Tien trong lenh mo: {open_cost:.2f} | "
          f"So du kha dung: {BUDGET + realized - open_cost:.2f} / {BUDGET:.0f} USD")


if __name__ == "__main__":
    main()
