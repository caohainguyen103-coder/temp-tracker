# -*- coding: utf-8 -*-
"""
vps_scan_all.py — Gop CD9 + CD11 + CD12 + CD14 vao 1 LAN GOI API DUY NHAT.

TAI SAO CAN FILE NAY (18/07):
Truoc day vps_loop.sh chay 4 file rieng (paper_trade9/11/12/14.py) moi
vong quet, MOI file tu goi collect.fetch_temperature_events() rieng ->
4 lan goi API Polymarket/vong. Muon rut vong quet tu 2 phut xuong 15-30s
ma giu nguyen cach do thi so lan goi API se tang ~8-16 lan/phut -> de bi
Polymarket gioi han/chan IP VPS.

File nay goi fetch_temperature_events() DUNG 1 LAN roi chia du lieu
event dung chung cho ca 4 chien dich -> tong tai len Polymarket gan
nhu khong doi (~tuong duong truoc day) du quet nhanh hon nhieu lan.

CD10 (ensemble GFS, nang, quet ~60 phut/lan) va cac chien dich khac
(1,3-8...) KHONG gop vao day, van chay rieng nhu cu.

Chay: python3 vps_scan_all.py
"""
import csv
import os
from datetime import datetime, timezone

import common as C
import collect
import paper_trade9 as P9
import paper_trade11 as P11
import paper_trade12 as P12
import paper_trade14 as P14


def _write(path, fields, trades):
    os.makedirs(C.DATA_DIR, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(trades)


def _run(mod, csv_path, fields, now, events):
    trades = C.read_csv(csv_path)
    for t in trades:
        t.setdefault("status", "open")
    n_settled = mod.settle(trades)
    n_new = mod.enter(trades, now, events=events)
    _write(csv_path, fields, trades)
    return n_settled, n_new


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = collect.fetch_temperature_events()

    s9, n9 = _run(P9, P9.TRADES9_CSV, P9.TRADE_FIELDS9, now, events)
    s11, n11 = _run(P11, P11.TRADES11_CSV, P11.TRADE_FIELDS11, now, events)
    s12, n12 = _run(P12, P12.TRADES12_CSV, P12.TRADE_FIELDS12, now, events)
    s14, n14 = _run(P14, P14.TRADES14_CSV, P14.TRADE_FIELDS14, now, events)

    print(f"[SCAN ALL] {now} | {len(events)} event nhiet do | "
          f"CD9 chot{s9}/moi{n9} | CD11 chot{s11}/moi{n11} | "
          f"CD12 chot{s12}/moi{n12} | CD14 chot{s14}/moi{n14}")


if __name__ == "__main__":
    main()
