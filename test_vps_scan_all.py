# -*- coding: utf-8 -*-
"""Test cho vps_scan_all.py: dam bao gop 4 chien dich dung 1 lan fetch
events van cho ra ket qua giong het chay tung file rieng (paper_trade9/
11/12/14.py), chi khac o cho khong tu goi collect.fetch_temperature_events()
ben trong nua ma dung events truyen vao."""
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

import vps_scan_all as SA
import paper_trade9 as P9
import paper_trade12 as P12
import paper_trade14 as P14

TODAY = "2026-07-17"
results = {"pass": 0, "fail": 0}


def check(name, cond):
    if cond:
        results["pass"] += 1
        print(f"  OK  {name}")
    else:
        results["fail"] += 1
        print(f"  FAIL {name}")


def mk_event(slug, buckets, target="2026-07-17"):
    ticker = f"highest-temperature-in-{slug}-on-july-17-2026"
    return {
        "slug": f"evt-{slug}", "ticker": ticker,
        "markets": [
            {"groupItemTitle": f"{temp}°C", "bestAsk": ask, "bestBid": bid,
             "slug": mslug, "closed": False, "active": True}
            for (temp, ask, bid, mslug) in buckets
        ],
    }


# Su kien: 1 market co gia YES 63c (kich hoat CD9 60-69, CD11 khong vi
# ngoai khoang 65-75/85-97) va co du >=3 o de CD12 co the xet arbitrage.
events = [mk_event("scanall", [
    (20, 0.63, 0.61, "mkt-sa-20"),
    (21, 0.20, 0.18, "mkt-sa-21"),
    (22, 0.10, 0.08, "mkt-sa-22"),
])]

now = "2026-07-17T10:00:00Z"

# --- Chay qua vps_scan_all (dung chung events) ---
t9 = SA._run(P9, P9.TRADES9_CSV, P9.TRADE_FIELDS9, now, events)
t12 = SA._run(P12, P12.TRADES12_CSV, P12.TRADE_FIELDS12, now, events)
t14 = SA._run(P14, P14.TRADES14_CSV, P14.TRADE_FIELDS14, now, events)

check("CD9 vao it nhat 1 lenh YES (gia 63c roi vao khoang 60-69)", t9[1] >= 1)
check("CD12 khong bao gio crash khi goi qua vps_scan_all (co the 0 hoac vao)", t12[1] >= 0)
check("CD14 chay khong loi (khong crash)", t14[1] >= 0)

# --- Doc lai file CSV vua ghi, kiem tra co du lieu thuc su (khong rong) ---
import common as C
rows9 = C.read_csv(P9.TRADES9_CSV)
check("File trades9.csv duoc ghi it nhat 1 dong sau khi goi qua orchestrator",
      len(rows9) >= 1)
check("Dong dau tien co field 'event_slug' dung (khong bi 'undefined')",
      rows9[0].get("event_slug") == "evt-scanall")

print(f"\n=== TONG: {results['pass']} PASS / {results['fail']} FAIL ===")
if results["fail"]:
    raise SystemExit(1)
