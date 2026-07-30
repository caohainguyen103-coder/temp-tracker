# -*- coding: utf-8 -*-
"""
diag_token.py — CHAN DOAN: kiem tra xem code co chon DUNG token "Yes" khong,
bang cach in ra gia so lenh THAT cua CA 2 phia (token thu 0 va token thu 1)
cho tung o cua 1 su kien dang bi bo qua nhieu nhat gan day.

Khong gui lenh, khong dung private key de ky giao dich that -- chi doc
order book cong khai (get_order_book chi can client object da khoi tao,
day la du lieu cong khai, khong lo private key).

Chay tren VPS (co du moi truong da cai san):
  cd /root/temp-tracker
  source /root/live12_secrets.env
  python3 diag_token.py highest-temperature-in-manila-on-july-30-2026
"""
import json
import sys

import common as C
import collect
from live_trade12 import get_client, _yes_token_id, book_depth_avg_price

SLUG = sys.argv[1] if len(sys.argv) > 1 else "highest-temperature-in-manila-on-july-30-2026"

events = collect.fetch_temperature_events() + collect.fetch_lowest_temperature_events()
ev = next((e for e in events if e.get("slug") == SLUG), None)
if ev is None:
    print(f"KHONG TIM THAY su kien slug={SLUG} (co the da dong hoac doi slug).")
    sys.exit(1)

client = get_client()

print(f"=== Su kien: {SLUG} ===\n")
worst_bucket = None  # (got_cua_token_chon, title, chosen_id, other_id, gamma_ask)
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

    print(f"--- O: {title} ---")
    print(f"  bestAsk (Gamma, hien thi tren web)   : {best_ask_gamma}")
    print(f"  outcomes field                        : {outcomes}")
    print(f"  clobTokenIds                          : {token_ids}")
    print(f"  token duoc chon lam 'Yes' (chosen)    : {chosen}")

    chosen_got = None
    other_id = None
    if token_ids:
        for idx, tid in enumerate(token_ids):
            label = "Yes" if outcomes and idx < len(outcomes) and str(outcomes[idx]).strip().lower() == "yes" else (
                    "No" if outcomes and idx < len(outcomes) and str(outcomes[idx]).strip().lower() == "no" else f"idx{idx}")
            mark = " <== CODE DANG DUNG TOKEN NAY" if tid == chosen else ""
            if tid != chosen:
                other_id = tid
            try:
                got, avg, dbg = book_depth_avg_price(client, tid, need_shares=5.0, max_price=0.99)
                print(f"    token[{idx}] nhan={label} id={tid[:12]}...{mark}")
                print(f"        so lenh that: {dbg['n_levels']} muc gia, gia thap nhat={dbg['best_price']}, "
                      f"khoi luong o gia do={dbg['best_size']}, kha dung <=0.99$ cho 5 co phan={got:.2f} (gia binh quan={avg})")
                if tid == chosen:
                    chosen_got = got
            except Exception as e:
                print(f"    token[{idx}] nhan={label} id={tid[:12]}...{mark} -- LOI khi doc order book: {e}")
    print()

    if chosen_got is not None and (worst_bucket is None or chosen_got < worst_bucket[0]):
        worst_bucket = (chosen_got, title, chosen, other_id, best_ask_gamma)

print("=== KET LUAN CAN TU DOC ===")
print("Neu token duoc CHON (dong co '<== CODE DANG DUNG') co gia thap nhat")
print("CAO HON NHIEU so voi bestAsk hien thi, VA token CON LAI (khong duoc")
print("chon) co gia thap nhat GAN VOI bestAsk hien thi hon -- thi code dang")
print("CHON NHAM PHIA (bug that su). Nguoc lai neu token duoc chon co gia")
print("gan voi bestAsk hon token kia, thi code dang chon dung, va gia cao")
print("la do thi truong that thieu thanh khoan (khong phai bug).")

print()
print("############################################################")
print("### TOM TAT -- O NGHEN CO CHAI (it co phan kha dung nhat) ###")
print("############################################################")
if worst_bucket is None:
    print("Khong tinh duoc (co the tat ca cac o deu loi khi doc order book).")
else:
    got, title, chosen_id, other_id, gamma_ask = worst_bucket
    print(f"O: {title}  (bestAsk Gamma hien thi = {gamma_ask})")
    print(f"Token DANG DUNG (Yes, theo code): {chosen_id}")
    print(f"  -> kha dung {got:.2f} co phan (cang gan 5.00 cang tot, 0.00 = hoan toan khong mua duoc)")
    if other_id:
        try:
            got2, avg2, dbg2 = book_depth_avg_price(client, other_id, need_shares=5.0, max_price=0.99)
            print(f"Token CON LAI (khong dung, gia nhu la 'No'): {other_id}")
            print(f"  -> gia thap nhat={dbg2['best_price']}, kha dung={got2:.2f} co phan")
        except Exception as e:
            print(f"Token CON LAI: LOI khi doc: {e}")
    print()
    print(">>> Neu 'Token DANG DUNG' co gia rat cao/kha dung=0.00 NHUNG 'Token")
    print(">>> CON LAI' lai co gia RAT GAN voi bestAsk Gamma hien thi o tren --")
    print(">>> thi day CHINH LA BUG chon nham token. Neu ca 2 token deu it/khong")
    print(">>> co thanh khoan gan gia hien thi, thi la do thi truong that thieu")
    print(">>> nguoi ban that su o muc gia do (khong phai bug).")
