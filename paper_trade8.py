# -*- coding: utf-8 -*-
"""
paper_trade8.py — CHIEN DICH 8: the thao, doi chieu Pinnacle vs Polymarket.
Tien ao $500. KHONG dung tien that. Chay tu dong sau cac chien dich thoi tiet.

Y tuong: Pinnacle la nha cai "sac" (gan nhu khong loi cho ai choi), gia cua
ho sau khi khu vig (bo phan loi nha cai) la uoc luong xac suat that chinh
xac nhat co san mien phi. Neu gia Polymarket (dam dong) RE HON xac suat
that cua Pinnacle mot khoang du lon -> mua YES ben do (gia tri ky vong duong).

Quy tac (co dinh, khach quan):
  - Chi ap dung the thao/giai da xac nhan cau truc (xem sports_common.SPORTS).
    Hien tai: World Cup 2026, market "doi X thang" / "hoa" (moneyline 3-way).
  - Voi moi tran chua dau (market con mo, active, chua closed):
      lay keo Pinnacle 3-way, khu vig -> xac suat cong bang cho tung ket qua.
      canh = xac_suat_cong_bang - gia_ask_Polymarket.
      canh >= 0.05 (5 diem %) -> vao lenh YES @ gia ask do.
  - Moi lenh $10 ao. Ngan sach $500. Khong gioi han so lenh/ngay (it tran).
    Phi taker 5% x p x (1-p) (dung feeSchedule.rate that cua market sports).
  - Thang khi market phan giai YES (doi/ket qua da chon xay ra that).
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
FEE_RATE = 0.05          # feeSchedule.rate that cua market the thao (sports_fees_v2)


def cash_available(trades):
    cash = BUDGET
    for t in trades:
        if t["status"] == "open":
            cash -= float(t["stake"]) + float(t["fee"])
        else:
            cash += float(t["pnl"] or 0)
    return cash


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
            team_a, team_b = teams[0]["name"], teams[1]["name"]
            rec = S.find_pinnacle_for_match(pinnacle, team_a, team_b)
            if not rec:
                continue
            for mkt in ev.get("markets", []):
                if mkt.get("closed") or not mkt.get("active"):
                    continue
                # Chi lay market "thang ca tran" (moneyline day du), KHONG lay
                # cac market phu cung trong series co cung ten doi (halftime,
                # second-half, ...) — cac market do da tung bi khop nham vao
                # keo Pinnacle full-match, tao "canh" gia nhung thuc ra la
                # so sai 2 loai xac suat khac nhau.
                if mkt.get("sportsMarketType") != "moneyline":
                    continue
                slug = mkt.get("slug")
                if not slug or slug in have_slugs:
                    continue
                outcome = S.market_outcome_key(mkt)
                fair = rec["p"].get(outcome)
                if fair is None:
                    continue
                ask = mkt.get("bestAsk")
                if ask is None:
                    continue
                ask = float(ask)
                if not (MIN_ASK <= ask <= MAX_ASK):
                    continue
                edge = round(fair - ask, 4)
                if edge < EDGE_MIN:
                    continue
                candidates.append({
                    "slug": slug, "match": ev.get("title", ""),
                    "outcome": outcome, "ask": ask, "fair": fair,
                    "overround": rec["overround"],
                    "commence": rec.get("commence_time") or "",
                    "edge": edge,
                })

    candidates.sort(key=lambda x: -x["edge"])  # canh lon nhat vao truoc
    added = 0
    for c in candidates:
        shares = round(STAKE / c["ask"], 2)
        fee = round(FEE_RATE * c["ask"] * (1 - c["ask"]) * shares, 4)
        if cash_available(trades) < STAKE + fee:
            print("  [HET TIEN AO CD8] cho lenh cu chot da")
            break
        trades.append({
            "entry_utc": now, "market_slug": c["slug"], "match": c["match"],
            "side_team": c["outcome"], "commence_utc": c["commence"],
            "side": "YES", "ask": c["ask"], "shares": shares,
            "stake": STAKE, "fee": fee,
            "pinnacle_fair_prob": round(c["fair"], 4),
            "pinnacle_overround": c["overround"], "edge": c["edge"],
            "status": "open", "payout": "", "pnl": "", "settle_utc": "",
        })
        have_slugs.add(c["slug"])
        print(f"  VAO LENH AO (CD8): {c['match']} - {c['outcome']} "
              f"@{c['ask']} x{shares} co phan | Pinnacle {c['fair']*100:.1f}% "
              f"vs Polymarket {c['ask']*100:.1f}% (canh +{c['edge']*100:.1f}đ%)")
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
        win = yes_price >= 0.5
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
