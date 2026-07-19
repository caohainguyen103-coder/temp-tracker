# -*- coding: utf-8 -*-
"""Mock test CD15 v2: NO nhu CD9 + dao chieu YES x3 khi gia bat nguoc >= 25 diem."""
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


check("nguong dao chieu v2 la 25 diem", P.REVERSAL_JUMP == 0.25)
check("von dao chieu x3 = 30$", P.REVERSAL_STAKE == 30.0)

print("=== Kich ban day du: dinh 55% -> tuot 25% (vao NO) -> bat len 50% (dao chieu YES x3) ===")
trades = []
hist = {}
P.enter(trades, "2026-07-17T10:00:00Z", events=[mk_event("cityA", [(20, 0.55, 0.53, "mkt-a")])], price_hist=hist)
check("scan1 (dinh 55%): chua vao lenh nao", len(trades) == 0)

n2 = P.enter(trades, "2026-07-17T10:30:00Z", events=[mk_event("cityA", [(20, 0.25, 0.23, "mkt-a")])], price_hist=hist)
check("scan2 (tuot 25%): vao 1 lenh NO nhu CD9", n2 == 1 and trades[0]["side"] == "NO")

# gia bat len 46% (+21 diem < 25) -> KHONG dao chieu (v1 cu se dao o day)
n3 = P.enter(trades, "2026-07-17T11:00:00Z", events=[mk_event("cityA", [(20, 0.46, 0.44, "mkt-a")])], price_hist=hist)
check("scan3 (bat len 46%, +21 diem < 25): KHONG dao chieu (v2 chat hon v1)", n3 == 0)

# gia bat len 50% (+25 diem, dung nguong) -> DAO CHIEU YES x3
n4 = P.enter(trades, "2026-07-17T11:30:00Z", events=[mk_event("cityA", [(20, 0.50, 0.48, "mkt-a")])], price_hist=hist)
yes_t = [t for t in trades if t["side"] == "YES"]
check("scan4 (bat len 50%, dung +25 diem): vao 1 lenh YES dao chieu", n4 == 1 and len(yes_t) == 1)
check("scan4: tier 'dao-chieu', cuoc 30$", yes_t and yes_t[0]["tier"] == "dao-chieu" and float(yes_t[0]["stake"]) == 30.0)
check("scan4: peak_ask ghi gia NO goc 0.25", yes_t and float(yes_t[0]["peak_ask"]) == 0.25)

n5 = P.enter(trades, "2026-07-17T12:00:00Z", events=[mk_event("cityA", [(20, 0.60, 0.58, "mkt-a")])], price_hist=hist)
check("scan5 (len tiep 60%): khong dao chieu lan 2", n5 == 0)

print("\n=== Khong co NO mo -> gia tang manh cung KHONG dao chieu ===")
trades2, hist2 = [], {}
P.enter(trades2, "2026-07-17T10:00:00Z", events=[mk_event("cityB", [(21, 0.30, 0.28, "mkt-b")])], price_hist=hist2)
n6 = P.enter(trades2, "2026-07-17T10:30:00Z", events=[mk_event("cityB", [(21, 0.60, 0.58, "mkt-b")])], price_hist=hist2)
check("gia tang 30->60 nhung chua tung vao NO: khong lenh nao", n6 == 0 and len(trades2) == 0)

print("\n=== NO tuot sau van mua them binh thuong ===")
trades4, hist4 = [], {}
P.enter(trades4, "2026-07-17T10:00:00Z", events=[mk_event("cityD", [(23, 0.55, 0.53, "mkt-d")])], price_hist=hist4)
P.enter(trades4, "2026-07-17T10:30:00Z", events=[mk_event("cityD", [(23, 0.25, 0.23, "mkt-d")])], price_hist=hist4)
n8 = P.enter(trades4, "2026-07-17T11:00:00Z", events=[mk_event("cityD", [(23, 0.15, 0.13, "mkt-d")])], price_hist=hist4)
no4 = [t for t in trades4 if t["side"] == "NO"]
check("tuot tiep 15%: mua NO khoang 10-19c (tong 2 NO)", n8 == 1 and len(no4) == 2)

# NO vao o 15% (khoang 10-19c dau tien): nguong dao = 15+25 = 40%
print("\n=== Moc so sanh la lenh NO DAU TIEN: NO1@25% -> nguong 50%, khong phai NO2@15% ===")
n9 = P.enter(trades4, "2026-07-17T11:30:00Z", events=[mk_event("cityD", [(23, 0.42, 0.40, "mkt-d")])], price_hist=hist4)
check("bat len 42% (NO1@25 + 25 = 50 > 42): chua dao chieu", n9 == 0)
n10 = P.enter(trades4, "2026-07-17T12:00:00Z", events=[mk_event("cityD", [(23, 0.52, 0.50, "mkt-d")])], price_hist=hist4)
check("bat len 52% (>= 50): dao chieu YES x3", n10 == 1)

print(f"\n=== TONG: {results['pass']} PASS / {results['fail']} FAIL ===")
if results["fail"]:
    raise SystemExit(1)
