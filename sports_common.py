# -*- coding: utf-8 -*-
"""
sports_common.py — Ham dung chung cho CHIEN DICH 8 (the thao, doi chieu Pinnacle).

Nguon du lieu:
  - gamma-api.polymarket.com : gia YES/NO cac market "doi X thang" / "hoa"
    cua tung tran (da kiem chung cau truc that ngay 2026-07-17, tran
    Phap vs Anh & Tay Ban Nha vs Argentina, World Cup 2026).
  - api.the-odds-api.com     : keo nha cai Pinnacle (nha cai sac, gan nhu
    khong co bien loi cho nguoi choi bat loi), dung lam "mo hinh doi
    chieu" thay cho mo hinh thoi tiet o cac chien dich truoc.

Y tuong giong het cac chien dich thoi tiet: so gia Polymarket (dam dong)
voi mot nguon "chuan" doc lap (Pinnacle, da khu vig) - lech gia = co hoi.
"""
import os

import common as C

ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"

# Danh sach giai dau theo doi (sport_key cua the-odds-api, series_slug cua
# Polymarket). Hien tai moi kiem chung World Cup 2026; them giai khac sau
# khi xac nhan cau truc slug tuong tu.
SPORTS = [
    {"odds_sport_key": "soccer_fifa_world_cup", "pm_series_slug": "soccer-fifwc",
     "label": "FIFA World Cup 2026"},
]

# Alias ten doi giua 2 nguon (phong khi ten khac nhau chut it).
TEAM_ALIAS = {
    "usa": "united states", "south korea": "korea republic",
}


def _norm_team(name):
    n = (name or "").strip().lower()
    return TEAM_ALIAS.get(n, n)


def devig(decimal_odds):
    """Multiplicative devig: implied = 1/odds, chuan hoa tong = 1."""
    implied = [1.0 / o for o in decimal_odds]
    overround = sum(implied)
    return [x / overround for x in implied], overround


def fetch_pinnacle_odds(sport_key):
    """Lay keo Pinnacle (h2h, 3-way voi bong da) cho 1 giai dau.
    Tra ve list dict: home_team, away_team, commence_time,
    p (dict ten doi/'Draw' -> xac suat cong bang da khu vig),
    o (dict ten doi/'Draw' -> ty le decimal goc, de doi chieu)."""
    if not ODDS_API_KEY:
        print("  [LOI CD8] Chua co bien moi truong ODDS_API_KEY")
        return []
    url = f"{ODDS_API_BASE}/sports/{sport_key}/odds"
    j = C.http_get_json(url, {
        "apiKey": ODDS_API_KEY, "regions": "eu,uk", "markets": "h2h",
    })
    if not j:
        return []
    out = []
    for ev in j:
        pin = next((b for b in ev.get("bookmakers", []) if b.get("key") == "pinnacle"), None)
        if not pin:
            continue
        mk = next((m for m in pin.get("markets", []) if m.get("key") == "h2h"), None)
        if not mk:
            continue
        odds_by_name = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
        home, away = ev.get("home_team"), ev.get("away_team")
        o_home, o_away = odds_by_name.get(home), odds_by_name.get(away)
        o_draw = odds_by_name.get("Draw")
        if not o_home or not o_away:
            continue
        names = [home, away] + (["Draw"] if o_draw else [])
        vals = [o_home, o_away] + ([o_draw] if o_draw else [])
        probs, overround = devig(vals)
        p = dict(zip(names, probs))
        o = dict(zip(names, vals))
        out.append({
            "home_team": home, "away_team": away,
            "commence_time": ev.get("commence_time"),
            "p": p, "o": o, "overround": round(overround, 4),
        })
    return out


def find_pinnacle_for_match(pinnacle_odds, team_a, team_b):
    """Tim ban ghi Pinnacle khop voi 2 doi (khong quan tam thu tu nha/khach)."""
    ta, tb = _norm_team(team_a), _norm_team(team_b)
    for rec in pinnacle_odds:
        h, a = _norm_team(rec["home_team"]), _norm_team(rec["away_team"])
        if {h, a} == {ta, tb}:
            return rec
    return None


def list_pm_matches(series_slug, closed=False):
    """Danh sach tran (event) tren Polymarket kem market con (nha/hoa/khach)."""
    j = C.http_get_json(f"{C.GAMMA}/events", {
        "series_slug": series_slug, "closed": str(closed).lower(),
        "limit": 100, "order": "startDate", "ascending": "true",
    })
    return j or []


def market_outcome_key(market):
    """Xac dinh market nay ung voi 'Draw' hay ten doi nao, dua tren
    marketMetadata.opticOddsSelectionLine ('home'/'away'/'draw')."""
    meta = market.get("marketMetadata") or {}
    line = (meta.get("opticOddsSelectionLine") or "").lower()
    if line == "draw":
        return "Draw"
    return market.get("groupItemTitle")


def fetch_market_by_slug(slug):
    j = C.http_get_json(f"{C.GAMMA}/markets", {"slug": slug})
    if not j:
        return None
    return j[0] if isinstance(j, list) and j else None
