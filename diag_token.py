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

    if token_ids:
        for idx, tid in enumerate(token_ids):
            label = "Yes" if outcomes and idx < len(outcomes) and str(outcomes[idx]).strip().lower() == "yes" else (
                    "No" if outcomes and idx < len(outcomes) and str(outcomes[idx]).strip().lower() == "no" else f"idx{idx}")
            mark = " <== CODE DANG DUNG TOKEN NAY" if tid == chosen else ""
            try:
                got, avg, dbg = book_depth_avg_price(client, tid, need_shares=5.0, max_price=0.99)
                print(f"    token[{idx}] nhan={label} id={tid[:12]}...{mark}")
                print(f"        so lenh that: {dbg['n_levels']} muc gia, gia thap nhat={dbg['best_price']}, "
                      f"khoi luong o gia do={dbg['best_size']}, kha dung <=0.99$ cho 5 co phan={got:.2f} (gia binh quan={avg})")
            except Exception as e:
                print(f"    token[{idx}] nhan={label} id={tid[:12]}...{mark} -- LOI khi doc order book: {e}")
    print()

print("=== KET LUAN CAN TU DOC ===")
print("Neu token duoc CHON (dong co '<== CODE DANG DUNG') co gia thap nhat")
print("CAO HON NHIEU so voi bestAsk hien thi, VA token CON LAI (khong duoc")
print("chon) co gia thap nhat GAN VOI bestAsk hien thi hon -- thi code dang")
print("CHON NHAM PHIA (bug that su). Nguoc lai neu token duoc chon co gia")
print("gan voi bestAsk hon token kia, thi code dang chon dung, va gia cao")
print("la do thi truong that thieu thanh khoan (khong phai bug).")
