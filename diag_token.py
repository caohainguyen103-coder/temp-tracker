# -*- coding: utf-8 -*-
"""
diag_token.py — CHAN DOAN: cho 1 su kien, kiem tra TUNG O:
  - Token nao dang duoc code chon lam "Yes" (clobTokenIds vs outcomes).
  - Gia sozeer lenh THAT (CLOB) cua token do, so voi bestAsk hien thi (Gamma).
  - Co du co phan de mua o nguong gia bot THAT SU chap nhan (ask*(1+slippage))
    hay khong.

In ra 1 BANG TOM TAT o CUOI CUNG, sap xep tu o NGHEN nhat (it co phan kha
dung nhat) len dau -- khong can cuon man hinh de tim.

Khong gui lenh that, chi doc order book cong khai.

Chay tren VPS:
  cd /root/temp-tracker
  source /root/live12_secrets.env
  python3 diag_token.py highest-temperature-in-manila-on-july-30-2026
"""
import json
import sys

import common as C
import collect
from live_trade12 import get_client, _yes_token_id, book_depth_avg_price, SLIPPAGE_TICKS_PCT

SLUG = sys.argv[1] if len(sys.argv) > 1 else "highest-temperature-in-manila-on-july-30-2026"

events = collect.fetch_temperature_events() + collect.fetch_lowest_temperature_events()
ev = next((e for e in events if e.get("slug") == SLUG), None)
if ev is None:
    print(f"KHONG TIM THAY su kien slug={SLUG} (co the da dong hoac doi slug).")
    sys.exit(1)

client = get_client()

print(f"=== Su kien: {SLUG} ===\n")
results = []  # moi phan tu: dict voi cac truong ben duoi

for mk in ev.get("markets", []):
    title = mk.get("groupItemTitle")
    b = C.parse_bucket(title)
    if b is None or mk.get("closed") or not mk.get("active"):
        continue
    try:
        token_ids = json.loads(mk["clobTokenIds"])
    except Exception:
        token_ids = None
    outcomes_raw = mk.get("outcomes")
    outcomes = None
    if isinstance(outcomes_raw, str):
        try:
            outcomes = json.loads(outcomes_raw)
        except Exception:
            outcomes = None
    elif isinstance(outcomes_raw, list):
        outcomes = outcomes_raw

    chosen = _yes_token_id(mk)
    best_ask_gamma = mk.get("bestAsk")
    real_max_price = None
    if best_ask_gamma is not None:
        real_max_price = min(float(best_ask_gamma) * (1 + SLIPPAGE_TICKS_PCT), 0.99)

    row = {"title": title, "gamma_ask": best_ask_gamma, "max_price": real_max_price,
           "chosen": chosen, "chosen_best_price": None, "chosen_got": None,
           "chosen_avg": None, "other_id": None, "other_best_price": None,
           "other_got": None, "error": None}

    if not token_ids or real_max_price is None:
        row["error"] = "thieu clobTokenIds hoac bestAsk"
        results.append(row)
        print(f"--- O: {title} --- LOI: {row['error']}")
        continue

    for idx, tid in enumerate(token_ids):
        if tid != chosen:
            row["other_id"] = tid
        try:
            got, avg, dbg = book_depth_avg_price(client, tid, need_shares=5.0, max_price=real_max_price)
        except Exception as e:
            if tid == chosen:
                row["error"] = f"loi doc order book token chosen: {e}"
            continue
        if tid == chosen:
            row["chosen_got"] = got
            row["chosen_avg"] = avg
            row["chosen_best_price"] = dbg["best_price"]
        else:
            row["other_got"] = got
            row["other_best_price"] = dbg["best_price"]

    results.append(row)
    print(f"--- O: {title} --- bestAsk={best_ask_gamma} max_price={real_max_price:.4f} "
          f"chosen_best_price={row['chosen_best_price']} chosen_got={row['chosen_got']} "
          f"other_best_price={row['other_best_price']}")

print()
print("############################################################")
print("### BANG TOM TAT -- sap xep tu O NGHEN nhat len dau        ###")
print("############################################################")
print(f"{'O (bucket)':<20}{'bestAsk':>9}{'max_chap_nhan':>15}{'gia_yes_that':>14}{'kha_dung':>10}{'gia_no_that':>13}")
valid = [r for r in results if r["error"] is None]
valid.sort(key=lambda r: (r["chosen_got"] if r["chosen_got"] is not None else 999))
for r in valid:
    print(f"{str(r['title'])[:19]:<20}{str(r['gamma_ask']):>9}{r['max_price']:>15.4f}"
          f"{str(r['chosen_best_price']):>14}{(r['chosen_got'] if r['chosen_got'] is not None else -1):>10.2f}"
          f"{str(r['other_best_price']):>13}")
errs = [r for r in results if r["error"] is not None]
if errs:
    print()
    print("O co loi khi doc:")
    for r in errs:
        print(f"  {r['title']}: {r['error']}")

print()
print("############################################################")
print("### KET LUAN CAN TU DOC (dua vao dong DAU BANG tren)        ###")
print("############################################################")
if valid:
    worst = valid[0]
    print(f"O nghen nhat: {worst['title']} -- kha dung {worst['chosen_got']:.2f}/5.00 co phan "
          f"o gia <= {worst['max_price']:.4f} (bestAsk hien thi = {worst['gamma_ask']})")
    print(f"  Gia THAT thap nhat cua token 'Yes' dang dung  : {worst['chosen_best_price']}")
    print(f"  Gia THAT thap nhat cua token con lai ('No')   : {worst['other_best_price']}")
    print()
    print(">>> Neu gia token 'Yes' dang dung cao/None NHUNG token 'No' con lai")
    print(">>> lai co gia RAT GAN voi bestAsk hien thi -- day la BUG chon nham")
    print(">>> token. Nguoc lai (gia Yes dang dung da gan voi bestAsk, chi la")
    print(">>> cao hon nguong slippage cho phep, hoac token No khong co gia/that")
    print(">>> xa) -- thi la do thi truong THAT thieu thanh khoan, khong phai bug.")
else:
    print("Khong co o nao doc duoc du lieu.")
