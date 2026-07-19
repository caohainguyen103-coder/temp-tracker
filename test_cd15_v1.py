# -*- coding: utf-8 -*-
"""Mock test CD15: NO nhu CD9 + dao chieu YES x3 khi gia bat nguoc >= 18 diem."""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import paper_trade15 as P

TODAY = "2026-07-17"
results = {"pass": 0, "fail": 0}


def check(name, cond):
    if cond:
        results["pass"] += 1
        print(f"  OK  {name}")
    else:
        results["fail"] += 1
        print(f"  FAIL {name}")


def mk_event(slug, buckets):
    ticker = f"highest-temperature-in-{slug}-on-july-17-2026"
    return {
        "slug": f"evt-{slug}", "ticker": ticker,
        "markets": [
            {"groupItemTitle": f"{temp}°C", "bestAsk": ask, "bestBid": bid,
             "slug": mslug, "closed": False, "active": True}
            for (temp, ask, bid, mslug) in buckets
        ],
    }


print("=== Kich ban day du: dinh 55% -> tuot 25% (vao NO) -> bat len 46% (dao chieu YES x3) ===")
trades = []
hist = {}
P.enter(trades, "2026-07-17T10:00:00Z", events=[mk_event("cityA", [(20, 0.55, 0.53, "mkt-a")])], price_hist=hist)
check("scan1 (dinh 55%): chua vao lenh nao", len(trades) == 0)

n2 = P.enter(trades, "2026-07-17T10:30:00Z", events=[mk_event("cityA", [(20, 0.25, 0.23, "mkt-a")])], price_hist=hist)
check("scan2 (tuot 25%): vao 1 lenh NO nhu CD9", n2 == 1 and trades[0]["side"] == "NO")
check("scan2: trigger_ask ghi 0.25", float(trades[0]["trigger_ask"]) == 0.25)

# gia nhich nhe len 35% (chi +10 diem, chua du 18) -> KHONG dao chieu
n3 = P.enter(trades, "2026-07-17T11:00:00Z", events=[mk_event("cityA", [(20, 0.35, 0.33, "mkt-a")])], price_hist=hist)
check("scan3 (bat len 35%, +10 diem < 18): KHONG dao chieu", n3 == 0)

# gia bat manh len 46% (+21 diem >= 18) -> DAO CHIEU YES x3
n4 = P.enter(trades, "2026-07-17T11:30:00Z", events=[mk_event("cityA", [(20, 0.46, 0.44, "mkt-a")])], price_hist=hist)
yes_t = [t for t in trades if t["side"] == "YES"]
check("scan4 (bat len 46%, +21 diem): vao 1 lenh YES dao chieu", n4 == 1 and len(yes_t) == 1)
check("scan4: tier la 'dao-chieu'", yes_t[0]["tier"] == "dao-chieu")
check("scan4: cuoc GAP 3 (30$)", float(yes_t[0]["stake"]) == 30.0)
check("scan4: peak_ask ghi gia NO goc 0.25 de doi chieu", float(yes_t[0]["peak_ask"]) == 0.25)

# quet lai gia van cao -> khong dao chieu lan 2
n5 = P.enter(trades, "2026-07-17T12:00:00Z", events=[mk_event("cityA", [(20, 0.50, 0.48, "mkt-a")])], price_hist=hist)
check("scan5: khong dao chieu lan 2 (moi o chi 1 lan)", n5 == 0)

print("\n=== Khong co NO mo -> gia tang manh cung KHONG dao chieu ===")
trades2, hist2 = [], {}
P.enter(trades2, "2026-07-17T10:00:00Z", events=[mk_event("cityB", [(21, 0.30, 0.28, "mkt-b")])], price_hist=hist2)
n6 = P.enter(trades2, "2026-07-17T10:30:00Z", events=[mk_event("cityB", [(21, 0.60, 0.58, "mkt-b")])], price_hist=hist2)
check("gia tang 30->60 nhung chua tung vao NO: khong lenh nao", n6 == 0 and len(trades2) == 0)

print("\n=== Bien: bat len dung +18 diem (25 -> 43) -> DUOC dao chieu ===")
trades3, hist3 = [], {}
P.enter(trades3, "2026-07-17T10:00:00Z", events=[mk_event("cityC", [(22, 0.55, 0.53, "mkt-c")])], price_hist=hist3)
P.enter(trades3, "2026-07-17T10:30:00Z", events=[mk_event("cityC", [(22, 0.25, 0.23, "mkt-c")])], price_hist=hist3)
n7 = P.enter(trades3, "2026-07-17T11:00:00Z", events=[mk_event("cityC", [(22, 0.43, 0.41, "mkt-c")])], price_hist=hist3)
check("bat len dung 43% (=25+18): DUOC dao chieu (>= chu khong phai >)", n7 == 1)

print("\n=== NO tuot sau van mua them binh thuong (khong anh huong boi luat moi) ===")
trades4, hist4 = [], {}
P.enter(trades4, "2026-07-17T10:00:00Z", events=[mk_event("cityD", [(23, 0.55, 0.53, "mkt-d")])], price_hist=hist4)
P.enter(trades4, "2026-07-17T10:30:00Z", events=[mk_event("cityD", [(23, 0.25, 0.23, "mkt-d")])], price_hist=hist4)
n8 = P.enter(trades4, "2026-07-17T11:00:00Z", events=[mk_event("cityD", [(23, 0.15, 0.13, "mkt-d")])], price_hist=hist4)
no4 = [t for t in trades4 if t["side"] == "NO"]
check("tuot tiep 15%: mua NO khoang 10-19c (tong 2 NO)", n8 == 1 and len(no4) == 2)

print(f"\n=== TONG: {results['pass']} PASS / {results['fail']} FAIL ===")
if results["fail"]:
    raise SystemExit(1)
