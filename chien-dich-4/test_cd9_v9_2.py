# -*- coding: utf-8 -*-
"""Mock test cho paper_trade9.py v9.2 (bo tier 90-97c neu da co ca 70-79c va 80-89c)."""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import paper_trade9 as P

TODAY = "2026-07-17"


def mk_event(slug, is_today, buckets):
    date_str = "july-17-2026" if is_today else "july-18-2026"
    ticker = f"highest-temperature-in-{slug}-on-{date_str}"
    return {
        "slug": f"evt-{slug}", "ticker": ticker,
        "eventDate": TODAY if is_today else "2026-07-18",
        "markets": [
            {"groupItemTitle": f"{temp}°C", "bestAsk": ask, "bestBid": bid,
             "slug": mslug, "closed": False, "active": True}
            for (temp, ask, bid, mslug) in buckets
        ],
    }


results = {"pass": 0, "fail": 0}


def check(name, cond):
    if cond:
        results["pass"] += 1
        print(f"  OK  {name}")
    else:
        results["fail"] += 1
        print(f"  FAIL {name}")


print("=== Ca Madrid: gia leo 63 -> 84 -> 92, moi lan 1 scan rieng ===")
trades = []
hist = {}
now1 = "2026-07-17T10:00:00Z"
P.enter(trades, now1, events=[mk_event("madrid", True, [(35, 0.63, 0.61, "mkt-madrid-35")])], price_hist=hist)
now2 = "2026-07-17T10:30:00Z"
P.enter(trades, now2, events=[mk_event("madrid", True, [(35, 0.84, 0.82, "mkt-madrid-35")])], price_hist=hist)
yes_before = {t["tier"] for t in trades if t["side"] == "YES"}
check("truoc scan3: da mua 60-69c va 80-89c (chua co 70-79c)",
      yes_before == {"60-69c", "80-89c"})
now3 = "2026-07-17T11:00:00Z"
added3 = P.enter(trades, now3, events=[mk_event("madrid", True, [(35, 0.92, 0.90, "mkt-madrid-35")])], price_hist=hist)
check("scan3 (gia 92%): thieu 70-79c nen chan v9.2 KHONG ap dung -> VAN mua 90-97c", added3 == 1)

print("\n=== Ca dung tam chan: leo qua CA 70-79c VA 80-89c truoc, roi toi 90-97c ===")
trades2 = []
hist2 = {}
n1 = "2026-07-17T10:00:00Z"
P.enter(trades2, n1, events=[mk_event("cityx", True, [(20, 0.72, 0.70, "mkt-x-20")])], price_hist=hist2)
n2 = "2026-07-17T10:30:00Z"
P.enter(trades2, n2, events=[mk_event("cityx", True, [(20, 0.85, 0.83, "mkt-x-20")])], price_hist=hist2)
n3 = "2026-07-17T11:00:00Z"
added_top = P.enter(trades2, n3, events=[mk_event("cityx", True, [(20, 0.93, 0.91, "mkt-x-20")])], price_hist=hist2)
yes2 = [t for t in trades2 if t["side"] == "YES"]
check("da co ca 70-79c va 80-89c", {t["tier"] for t in yes2} == {"70-79c", "80-89c"})
check("scan3 (gia 93%): KHONG mua them 90-97c nua (chan moi v9.2)", added_top == 0)
check("tong so lenh YES van la 2 (khong tang len 3)", len(yes2) == 2)

print("\n=== Doi chung: chi co 80-89c (KHONG co 70-79c) -> van duoc mua 90-97c ===")
trades3 = []
hist3 = {}
m1 = "2026-07-17T10:00:00Z"
P.enter(trades3, m1, events=[mk_event("cityy", True, [(21, 0.88, 0.86, "mkt-y-21")])], price_hist=hist3)
m2 = "2026-07-17T10:30:00Z"
added_top3 = P.enter(trades3, m2, events=[mk_event("cityy", True, [(21, 0.95, 0.93, "mkt-y-21")])], price_hist=hist3)
check("chi co 80-89c, chua co 70-79c -> 90-97c VAN duoc mua binh thuong", added_top3 == 1)

print("\n=== Doi chung: chi co 70-79c (KHONG co 80-89c) -> van duoc mua 90-97c ===")
trades4 = []
hist4 = {}
k1 = "2026-07-17T10:00:00Z"
P.enter(trades4, k1, events=[mk_event("cityz", True, [(22, 0.75, 0.73, "mkt-z-22")])], price_hist=hist4)
k2 = "2026-07-17T10:30:00Z"
added_top4 = P.enter(trades4, k2, events=[mk_event("cityz", True, [(22, 0.95, 0.93, "mkt-z-22")])], price_hist=hist4)
check("chi co 70-79c, chua co 80-89c -> 90-97c VAN duoc mua binh thuong", added_top4 == 1)

print("\n=== NO logic khong bi anh huong (giu nguyen v9) ===")
trades5 = []
hist5 = {}
q1 = "2026-07-17T10:00:00Z"
P.enter(trades5, q1, events=[mk_event("cityq", True, [(20, 0.55, 0.53, "mkt-q-20")])], price_hist=hist5)
q2 = "2026-07-17T10:30:00Z"
added_no = P.enter(trades5, q2, events=[mk_event("cityq", True, [(20, 0.25, 0.23, "mkt-q-20")])], price_hist=hist5)
check("NO van mua binh thuong (khoang 20-29c sau dinh 55%)", added_no == 1)

print(f"\n=== TONG: {results['pass']} PASS / {results['fail']} FAIL ===")
if results["fail"]:
    raise SystemExit(1)
