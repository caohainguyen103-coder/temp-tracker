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

v2 (26/07) — SUA LOI "lenh treo mai khong chot":
  - Nguyen nhan cu: ghep tran Pinnacle <-> Polymarket CHI theo ten 2 doi,
    khong so NGAY DAU. MLB 2 doi gap nhau 3-4 tran lien tiep trong 1 series,
    lai co ca event cu bi hoan tu nhieu thang truoc con "mo" tren Polymarket
    (vd mlb-stl-cin-2026-05-24). Ket qua: mua nham market cua tran khac ngay
    / tran hoan — nhung market nay khong bao gio dong -> khong settle duoc.
  - Sua 1: chi ghep khi gio dau Polymarket (event.startTime/gameStartTime)
    lech gio dau Pinnacle (commence_time) <= MATCH_WINDOW_H (12h).
  - Sua 2: settle() them luat VOID — lenh ma market khong tra ve tu API,
    hoac qua VOID_AFTER_H (72h) sau gio dau ma van chua dong (tran hoan/
    market mo coi) -> huy lenh, hoan von (pnl = 0), status = "void".
  - Sua 3: xu ly resolve 50-50 (tran huy/hoa theo mo ta market): moi share
    tra 0.5 cho ca 2 phia.

Ket qua ghi vao data/trades8.csv.
"""
import csv
import json
import os
from datetime import datetime, timezone, timedelta

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
MATCH_WINDOW_H = 12      # v2: gio dau 2 nguon phai lech <= 12h moi coi la cung tran
VOID_AFTER_H = 72        # v2: qua 72h sau gio dau ma market chua dong -> void


def _parse_utc(s):
    """Parse chuoi thoi gian ISO ve datetime UTC; tra ve None neu hong."""
    if not s:
        return None
    s = str(s).strip().replace(" ", "T")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def same_game(ev_start, pinnacle_commence, window_h=MATCH_WINDOW_H):
    """v2: 2 moc gio dau phai lech <= window_h gio moi coi la cung 1 tran."""
    a, b = _parse_utc(ev_start), _parse_utc(pinnacle_commence)
    if a is None or b is None:
        return False  # thieu gio dau -> KHONG ghep (an toan, tranh mua nham)
    return abs((a - b).total_seconds()) <= window_h * 3600


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
            # v2: bat buoc trung ngay/gio dau — tranh mua market tran khac
            # ngay trong cung series, hoac event hoan cu con treo.
            ev_start = ev.get("startTime") or ev.get("gameStartTime") or ""
            if not same_game(ev_start, rec.get("commence_time")):
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


def _void(t, now, reason):
    """v2: huy lenh, hoan von ao (pnl = 0)."""
    t["status"], t["payout"], t["pnl"] = "void", "", 0.0
    t["settle_utc"] = now
    print(f"  [CD8 VOID] {t.get('match','')} ({t['market_slug']}): {reason}")


def settle(trades):
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    n = 0
    for t in trades:
        if t["status"] != "open":
            continue
        commence = _parse_utc(t.get("commence_utc"))
        stale = (commence is not None
                 and now_dt - commence > timedelta(hours=VOID_AFTER_H))
        mkt = S.fetch_market_by_slug(t["market_slug"])
        if not mkt:
            # API khong tra ve market nay. Neu tran da qua lau -> mo coi, huy.
            if stale:
                _void(t, now, f"market bien mat, tran da qua >{VOID_AFTER_H}h")
                n += 1
            continue
        if not mkt.get("closed"):
            # Market van mo. Neu qua lau sau gio dau -> tran hoan / market
            # mo coi khong ai resolve -> huy lenh cho sach so.
            if stale:
                _void(t, now, f"qua {VOID_AFTER_H}h sau gio dau van chua dong")
                n += 1
            continue
        try:
            prices = json.loads(mkt.get("outcomePrices") or "[]")  # ["1","0"] / ["0","1"] / ["0.5","0.5"]
            yes_price = float(prices[0])
        except (ValueError, IndexError, TypeError):
            continue
        stake, fee, shares = float(t["stake"]), float(t["fee"]), float(t["shares"])
        side = (t.get("side") or "YES").upper()
        if abs(yes_price - 0.5) < 0.01:
            # v2: tran huy/hoa -> resolve 50-50, moi share tra 0.5 ca 2 phia
            payout = shares * 0.5
            t["status"], t["payout"] = "tie", round(payout, 2)
            t["pnl"] = round(payout - stake - fee, 2)
        else:
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
    voided = sum(1 for t in trades if t["status"] == "void")
    print(f"\n[CHIEN DICH 8 — The thao, canh Pinnacle >= 5%, $500 ao]")
    print(f"SO GIAO DICH AO: chot {n_settled}, vao moi {n_new}")
    print(f"Da chot: {won} thang / {lost} thua / {voided} huy | "
          f"Lai/lo da chot: {realized:+.2f} USD")
    print(f"Tien trong lenh mo: {open_cost:.2f} | "
          f"So du kha dung: {BUDGET + realized - open_cost:.2f} / {BUDGET:.0f} USD")


if __name__ == "__main__":
    main()
