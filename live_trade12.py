# -*- coding: utf-8 -*-
"""
live_trade12.py — CHIEN DICH 12 BAN TIEN THAT (tu dong hoan toan, khong ai
duyet tung lenh).

##############################################################################
# CANH BAO: FILE NAY DAT LENH MUA THAT BANG TIEN THAT TREN POLYMARKET.       #
# Khong co buoc xac nhan thu cong truoc khi lenh duoc gui.                    #
# Doc het SETUP_LIVE_TRADING.md TRUOC KHI chay file nay lan dau.              #
##############################################################################

Khac voi paper_trade12.py (ban mo phong, khong dung tien that):

1) KIEM TRA DO SAU SO LENH THAT (order book depth) cho tung o truoc khi vao,
   khong chi tin "bestAsk" hang dau nhu ban paper. Ly do: qua theo doi
   paper_trade12.py, nhieu lan "tong gia re" (vi du Wuhan sum_ask=0.089,
   Tokyo 0.331, Ankara 0.319) chi la 1-2 o co bestAsk bi meo ngay sau khi du
   lieu nhiet do that vua cap nhat -- so luong THAT co the mua duoc o muc gia
   do rat mong, phan lon khong khop duoc voi $100 nhu bot tuong. Ban nay chi
   mua dung so co phan THAT SU dang co tren so lenh, dung lenh FAK
   (Fill-And-Kill): khop duoc bao nhieu lay bay nhieu, phan con lai HUY NGAY,
   khong treo so cho gia cu quay lai.

2) MAC DINH DRY-RUN: neu khong dat bien moi truong LIVE_TRADING=1, script chi
   in ra no SE mua gi (da kiem tra do sau that qua API, neu co du API key) ma
   KHONG gui lenh that. Phai chu dong bat LIVE_TRADING=1 moi that su giao dich.

3) GIOI HAN AN TOAN CUNG:
   - CD12_LIVE_STAKE: von moi bo (mac dinh $5, RAT nho so voi $100 cua paper)
   - CD12_LIVE_MAX_TRADES: so bo toi da moi lan chay (mac dinh 1)
   - CD12_LIVE_DAILY_LOSS_LIMIT: neu lo thuc te trong ngay vuot muc nay,
     script tu tao file khoa data/LIVE_PAUSE va dung, phai tu xoa file do
     (sau khi da xem xet ky) moi chay lai duoc.
   - data/LIVE_PAUSE: chi can tao file rong nay bat cu luc nao la bot dung
     vao lenh moi ngay lan chay ke tiep (kill-switch thu cong).

4) BAN PHAI TU LAM (toi khong the lam thay va se KHONG bao gio yeu cau ban
   dan private key vao chat voi toi):
   - Tao vi (MetaMask), chuyen USDC sang mang Polygon, nap vao Polymarket.
   - Lay private key cua vi do, DAT VAO BIEN MOI TRUONG tren may/VPS cua BAN:
       export POLYMARKET_PRIVATE_KEY="0x...."
       export POLYMARKET_FUNDER="0x..."   # dia chi vi nhan/gui cua ban
   - pip install py-clob-client
   - Tu chay: python live_trade12.py   (mac dinh dry-run, an toan de thu)
   - Doc ky SETUP_LIVE_TRADING.md di kem file nay.

LUU Y VE DO CHINH XAC KY THUAT: cac tham so goi ham cua thu vien py-clob-client
(vi du ten enum OrderType.FAK, tham so signature_type, cau truc tra ve cua
get_order_book) duoc viet dua tren tai lieu cong khai cua thu vien nay nhung
CO THE da doi phien ban moi. TRUOC KHI bat LIVE_TRADING=1, hay:
  a) Chay thu o che do dry-run nhieu lan, doc ky log.
  b) Doi chieu voi tai lieu chinh thuc: https://github.com/Polymarket/py-clob-client
  c) Test voi CD12_LIVE_STAKE that nho (vi du $1-2) truoc khi tang len.
"""
import json
import os
import sys
from datetime import datetime, timezone

import common as C
import collect
from paper_trade12 import full_set_asks, set_economics, FEE_RATE

try:
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
except ImportError:
    ClobClient = None  # cho phep dry-run "xem ung vien" ngay ca khi chua cai thu vien


# ============================== CAU HINH AN TOAN ============================
LIVE_TRADING = os.environ.get("LIVE_TRADING") == "1"          # mac dinh False = DRY-RUN
PRIVATE_KEY = os.environ.get("POLYMARKET_PRIVATE_KEY")
FUNDER_ADDRESS = os.environ.get("POLYMARKET_FUNDER")
SIGNATURE_TYPE = int(os.environ.get("POLYMARKET_SIG_TYPE", "1"))  # kiem tra lai tren tai lieu Polymarket truoc khi doi

SET_STAKE = float(os.environ.get("CD12_LIVE_STAKE", "5"))         # $/bo -- BAT DAU RAT NHO
MIN_NET_LIVE = float(os.environ.get("CD12_LIVE_MIN_NET", "0.15"))
MAX_TRADES_PER_RUN = int(os.environ.get("CD12_LIVE_MAX_TRADES", "1"))
DAILY_LOSS_LIMIT = float(os.environ.get("CD12_LIVE_DAILY_LOSS_LIMIT", "20"))
SLIPPAGE_TICKS_PCT = float(os.environ.get("CD12_LIVE_SLIPPAGE_PCT", "0.02"))  # cho phep truot toi da 2% gia

PAUSE_FILE = os.path.join(C.DATA_DIR, "LIVE_PAUSE")
LIVE_CSV = C.DATA_DIR + "/trades12_live.csv"

LIVE_FIELDS = [
    "entry_utc", "event_slug", "city", "target_date",
    "n_buckets_theoretical", "sum_ask_theoretical", "shares_theoretical",
    "sum_ask_actual", "shares_filled", "cost_actual", "fee_est",
    "locked_profit_actual", "status", "order_ids", "note",
]


def get_client():
    if ClobClient is None:
        print("[LOI] Chua cai py-clob-client. Chay: pip install py-clob-client")
        sys.exit(1)
    if not PRIVATE_KEY or not FUNDER_ADDRESS:
        print("[LOI] Thieu bien moi truong POLYMARKET_PRIVATE_KEY hoac POLYMARKET_FUNDER.")
        sys.exit(1)
    client = ClobClient(
        host="https://clob.polymarket.com",
        key=PRIVATE_KEY,
        chain_id=137,
        signature_type=SIGNATURE_TYPE,
        funder=FUNDER_ADDRESS,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    return client


def book_depth_avg_price(client, token_id, need_shares, max_price):
    """Doc SO LENH BAN THAT cua token_id, tra ve (shares_kha_dung, gia_binh_quan)
    cho toi da need_shares o gia <= max_price. Day la kiem tra THAT qua CLOB
    API, khac voi bestAsk cua Gamma API (chi la gia hang dau, khong noi ro
    con bao nhieu khoi luong o do)."""
    book = client.get_order_book(token_id)
    asks = sorted(
        ((float(a.price), float(a.size)) for a in (getattr(book, "asks", None) or [])),
        key=lambda x: x[0],
    )
    got, cost = 0.0, 0.0
    for price, size in asks:
        if price > max_price or got >= need_shares:
            break
        take = min(size, need_shares - got)
        got += take
        cost += take * price
    avg = (cost / got) if got > 0 else None
    return got, avg


def scan_candidates(now, today):
    have_live = {r["event_slug"] for r in C.read_csv(LIVE_CSV)}
    events = collect.fetch_temperature_events() + collect.fetch_lowest_temperature_events()
    cands = []
    for ev in events:
        slug = ev.get("slug", "")
        if not slug or slug in have_live:
            continue
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target:
            continue
        try:
            lead = (C.parse_iso_date(target) - today).days
        except ValueError:
            continue
        if lead < 0 or lead > 2:
            continue
        asks = full_set_asks(ev)
        if asks is None:
            continue
        eco = set_economics(asks)
        if eco is None:
            continue
        # Doi lai economics theo SET_STAKE that (paper_trade12 dung $100 co dinh)
        s = eco["sum_ask"]
        shares = round(SET_STAKE / s, 2)
        cost = round(shares * s, 2)
        fee = round(sum(FEE_RATE * a * (1 - a) * shares for a in asks), 4)
        locked = round(shares * 1.0 - cost - fee, 2)
        if locked < MIN_NET_LIVE:
            continue

        tokens = []
        ok = True
        for mk in ev.get("markets", []):
            b = C.parse_bucket(mk.get("groupItemTitle"))
            if b is None or mk.get("closed") or not mk.get("active"):
                continue
            try:
                yes_token = json.loads(mk["clobTokenIds"])[0]
            except Exception:
                yes_token = None
            if yes_token is None or mk.get("bestAsk") is None:
                ok = False
                break
            tokens.append({"ask": float(mk["bestAsk"]), "token_id": yes_token,
                            "title": mk.get("groupItemTitle")})
        if not ok or not tokens:
            continue

        cands.append({
            "event_slug": slug, "city": city, "target_date": target,
            "n_buckets": len(asks), "sum_ask_theoretical": s,
            "shares_theoretical": shares, "tokens": tokens,
        })
    cands.sort(key=lambda c: c["sum_ask_theoretical"])  # re nhat (nhieu loi nhat) truoc
    return cands


def try_enter_one(client, cand):
    """Kiem tra do sau THAT cho tung o. Chi vao neu SAU KHI tinh lai theo do
    sau that, loi rong van >= MIN_NET_LIVE. Neu khong -> BO QUA, tuyet doi
    khong mua non theo bestAsk hien thi (day la diem khac biet cot loi so
    voi ban paper, ngan chan dung truong hop Wuhan/Tokyo/Ankara)."""
    need_shares = cand["shares_theoretical"]
    filled = []
    min_filled_shares = need_shares
    for t in cand["tokens"]:
        max_price = min(t["ask"] * (1 + SLIPPAGE_TICKS_PCT), 0.99)
        got, avg = book_depth_avg_price(client, t["token_id"], need_shares, max_price)
        filled.append({**t, "got": got, "avg": avg})
        min_filled_shares = min(min_filled_shares, got)

    if min_filled_shares < need_shares * 0.5:
        return None, (f"do sau THAT khong du (o mong nhat chi kha dung "
                       f"{min_filled_shares:.2f}/{need_shares:.2f} co phan) -> BO QUA")

    shares_use = round(min_filled_shares, 2)
    real_asks = [f["avg"] if f["avg"] is not None else f["ask"] for f in filled]
    real_cost = round(shares_use * sum(real_asks), 2)
    fee_est = round(sum(FEE_RATE * a * (1 - a) * shares_use for a in real_asks), 4)
    locked_actual = round(shares_use * 1.0 - real_cost - fee_est, 2)
    sum_ask_actual = round(sum(real_asks), 4)

    if locked_actual < MIN_NET_LIVE:
        return None, f"loi rong sau do sau THAT chi con {locked_actual:.2f}$ (< nguong {MIN_NET_LIVE}$) -> BO QUA"

    if not LIVE_TRADING:
        return ({"shares_use": shares_use, "cost": real_cost, "fee": fee_est,
                  "locked": locked_actual, "sum_ask_actual": sum_ask_actual,
                  "order_ids": []},
                "DRY-RUN: se mua nhung KHONG gui lenh that (dat LIVE_TRADING=1 de bat)")

    order_ids = []
    for f in filled:
        price = round(f["avg"] if f["avg"] is not None else f["ask"], 3)
        args = OrderArgs(price=price, size=shares_use, side=BUY, token_id=f["token_id"])
        signed = client.create_order(args)
        resp = client.post_order(signed, OrderType.FAK)
        order_ids.append(resp.get("orderID") if isinstance(resp, dict) else str(resp))

    return ({"shares_use": shares_use, "cost": real_cost, "fee": fee_est,
              "locked": locked_actual, "sum_ask_actual": sum_ask_actual,
              "order_ids": order_ids},
             "DA GUI LENH THAT (FAK) cho tat ca cac o")


def daily_realized_pnl():
    rows = C.read_csv(LIVE_CSV)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    total = 0.0
    for r in rows:
        if r.get("entry_utc", "")[:10] == today and r.get("locked_profit_actual"):
            try:
                total += float(r["locked_profit_actual"])
            except ValueError:
                pass
    return total


def main():
    mode = "LIVE_TRADING=1 (LENH THAT SE DUOC GUI)" if LIVE_TRADING else "DRY-RUN (chi mo phong, KHONG dat lenh that)"
    print(f"=== CD12 LIVE — {mode} ===")

    if os.path.exists(PAUSE_FILE):
        print(f"[TAM DUNG] File khoa {PAUSE_FILE} dang ton tai -> khong vao lenh moi.")
        print("Xoa file nay (sau khi da xem xet ky) de cho phep chay lai.")
        return

    if daily_realized_pnl() <= -abs(DAILY_LOSS_LIMIT):
        print(f"[DUNG KHAN] Lo thuc te hom nay da cham gioi han {DAILY_LOSS_LIMIT}$.")
        os.makedirs(C.DATA_DIR, exist_ok=True)
        open(PAUSE_FILE, "w").close()
        print(f"Da tu tao file khoa {PAUSE_FILE}. Xoa file do sau khi xem xet de chay lai.")
        return

    client = get_client() if LIVE_TRADING or PRIVATE_KEY else None
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    today = C.today_utc()

    cands = scan_candidates(now, today)
    print(f"Tim thay {len(cands)} ung vien qua loc ly thuyet (chua kiem tra do sau that).")

    rows_out = []
    n_done = 0
    for cand in cands:
        if n_done >= MAX_TRADES_PER_RUN:
            break
        if client is None:
            print(f"  [UNG VIEN, chua kiem tra do sau] {cand['city']} {cand['target_date']} "
                  f"tong ly thuyet {cand['sum_ask_theoretical']} -- can POLYMARKET_PRIVATE_KEY "
                  f"+ POLYMARKET_FUNDER de kiem tra do sau that va dat lenh.")
            rows_out.append({
                "entry_utc": now, "event_slug": cand["event_slug"], "city": cand["city"],
                "target_date": cand["target_date"], "n_buckets_theoretical": cand["n_buckets"],
                "sum_ask_theoretical": cand["sum_ask_theoretical"],
                "shares_theoretical": cand["shares_theoretical"],
                "sum_ask_actual": "", "shares_filled": "", "cost_actual": "",
                "fee_est": "", "locked_profit_actual": "", "status": "no_credentials",
                "order_ids": "", "note": "chua co API key de kiem tra do sau that",
            })
            n_done += 1
            continue

        result, note = try_enter_one(client, cand)
        print(f"  [{cand['city']} {cand['target_date']}] {note}")
        status = "skipped" if result is None else ("open" if LIVE_TRADING else "dry_run")
        rows_out.append({
            "entry_utc": now, "event_slug": cand["event_slug"], "city": cand["city"],
            "target_date": cand["target_date"], "n_buckets_theoretical": cand["n_buckets"],
            "sum_ask_theoretical": cand["sum_ask_theoretical"],
            "shares_theoretical": cand["shares_theoretical"],
            "sum_ask_actual": result["sum_ask_actual"] if result else "",
            "shares_filled": result["shares_use"] if result else "",
            "cost_actual": result["cost"] if result else "",
            "fee_est": result["fee"] if result else "",
            "locked_profit_actual": result["locked"] if result else "",
            "status": status,
            "order_ids": ",".join(result["order_ids"]) if result else "",
            "note": note,
        })
        if result:
            n_done += 1

    if rows_out:
        C.append_csv(LIVE_CSV, LIVE_FIELDS, rows_out)
    print(f"Xong. Ghi {len(rows_out)} dong vao {LIVE_CSV}")


if __name__ == "__main__":
    main()
