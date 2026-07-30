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

# 30/07/2026: thu vien cu "py-clob-client" (0.34.6) da bi Polymarket KHOA --
# moi lenh gui that deu bi tu choi voi loi "invalid order version, please
# use the latest clob-client" (repo cu da bi archive). Da chuyen sang thu
# vien moi chinh thuc "py-clob-client-v2" (xem
# https://github.com/Polymarket/py-clob-client-v2). Tren VPS can:
#   pip install py-clob-client-v2 --break-system-packages
try:
    from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, Side
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
        print("[LOI] Chua cai py-clob-client-v2. Chay: pip install py-clob-client-v2 --break-system-packages")
        sys.exit(1)
    if not PRIVATE_KEY or not FUNDER_ADDRESS:
        print("[LOI] Thieu bien moi truong POLYMARKET_PRIVATE_KEY hoac POLYMARKET_FUNDER.")
        sys.exit(1)
    host = "https://clob.polymarket.com"
    # py-clob-client-v2 tach lam 2 buoc: (1) L1 (chu ky vi) de lay/tao API
    # credentials, (2) L1+L2 (co creds) moi dat/huy lenh duoc. Khac voi ban
    # cu chi can 1 client roi goi set_api_creds() ngay tren no.
    l1_client = ClobClient(
        host=host, chain_id=137, key=PRIVATE_KEY,
        signature_type=SIGNATURE_TYPE, funder=FUNDER_ADDRESS,
    )
    creds = l1_client.create_or_derive_api_key()
    client = ClobClient(
        host=host, chain_id=137, key=PRIVATE_KEY,
        signature_type=SIGNATURE_TYPE, funder=FUNDER_ADDRESS, creds=creds,
    )
    return client


def book_depth_avg_price(client, token_id, need_shares, max_price):
    """Doc SO LENH BAN THAT cua token_id, tra ve (shares_kha_dung, gia_binh_quan,
    debug_info) cho toi da need_shares o gia <= max_price. Day la kiem tra
    THAT qua CLOB API, khac voi bestAsk cua Gamma API (chi la gia hang dau,
    khong noi ro con bao nhieu khoi luong o do).

    debug_info giup phan biet 2 truong hop khi got=0: (a) so lenh THAT SU
    trong (khong ai ban) - thi truong khong co thanh khoan that, khac voi
    (b) co lenh ban that nhung o gia cao hon max_price (bi loai boi truot
    gia cho phep) - hai truong hop nay can xu ly/hieu khac nhau."""
    book = client.get_order_book(token_id)
    # py-clob-client-v2: get_order_book() tra ve dict JSON THUAN (vd
    # book["asks"] la list dict {"price":..,"size":..}), KHONG con la object
    # co thuoc tinh .asks/.price/.size nhu ban cu -- doc ca 2 kieu cho chac.
    if isinstance(book, dict):
        raw_asks = book.get("asks") or []
    else:
        raw_asks = getattr(book, "asks", None) or []

    def _lvl_price(a):
        return a["price"] if isinstance(a, dict) else a.price

    def _lvl_size(a):
        return a["size"] if isinstance(a, dict) else a.size

    asks = sorted(
        ((float(_lvl_price(a)), float(_lvl_size(a))) for a in raw_asks),
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
    debug_info = {
        "n_levels": len(asks),
        "best_price": asks[0][0] if asks else None,
        "best_size": asks[0][1] if asks else None,
    }
    return got, avg, debug_info


def _yes_token_id(mk):
    """Lay dung token_id cua ket qua "Yes" trong clobTokenIds. TRUOC DAY code
    luon gia dinh index [0] la "Yes" -- gia dinh nay co the SAI (neu API tra
    ve thu tu [No, Yes] cho mot so thi truong), khien cac lan kiem tra do sau
    that tra ve luon sai token (thuong la o hoan toan trong -> luon bi BO
    QUA du thi truong that co the co thanh khoan). Ham nay uu tien doi chieu
    voi field "outcomes" (thuong la ["Yes","No"] theo dung thu tu voi
    clobTokenIds) truoc khi phai doan index [0]."""
    try:
        token_ids = json.loads(mk["clobTokenIds"])
    except Exception:
        return None
    if not token_ids:
        return None
    outcomes_raw = mk.get("outcomes")
    outcomes = None
    if isinstance(outcomes_raw, str):
        try:
            outcomes = json.loads(outcomes_raw)
        except Exception:
            outcomes = None
    elif isinstance(outcomes_raw, list):
        outcomes = outcomes_raw
    if outcomes and len(outcomes) == len(token_ids):
        for i, o in enumerate(outcomes):
            if str(o).strip().lower() == "yes":
                return token_ids[i]
    # Khong co field outcomes dang tin cay -> gia dinh nhu cu (index 0).
    # DUOC GHI RO trong debug/note de biet lan nao dang phai doan.
    return token_ids[0]


BOUGHT_STATUSES = {"open", "open_CANH_BAO", "dry_run"}


def scan_candidates(now, today):
    # CHI loai tru event da THUC SU MUA (open/dry_run) -- KHONG loai tru vinh
    # vien cac event bi "skipped" (thieu do sau tai thoi diem kiem tra). Ly
    # do sua (phat hien 29/07): gia so lenh THAT dao dong lien tuc, mot event
    # bi bo qua luc 15:33 hoan toan co the du do sau lai o lan quet 15:34 --
    # truoc day code loai tru ca event bi skip vinh vien, khien co hoi thoang
    # qua khong bao gio duoc thu lai.
    have_bought = {r["event_slug"] for r in C.read_csv(LIVE_CSV)
                   if r.get("status") in BOUGHT_STATUSES}
    events = collect.fetch_temperature_events() + collect.fetch_lowest_temperature_events()
    cands = []
    for ev in events:
        slug = ev.get("slug", "")
        if not slug or slug in have_bought:
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
            yes_token = _yes_token_id(mk)
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
    worst = None
    for t in cand["tokens"]:
        max_price = min(t["ask"] * (1 + SLIPPAGE_TICKS_PCT), 0.99)
        got, avg, dbg = book_depth_avg_price(client, t["token_id"], need_shares, max_price)
        filled.append({**t, "got": got, "avg": avg})
        if worst is None or got < worst["got"]:
            worst = {"got": got, "title": t.get("title"), "ask_gamma": t["ask"],
                      "max_price": max_price, **dbg}
        min_filled_shares = min(min_filled_shares, got)

    if min_filled_shares < need_shares * 0.5:
        if worst and worst["n_levels"] == 0:
            ly_do = "so lenh THAT trong (khong co ai ban thuc su o thi truong nay)"
        elif worst and worst["best_price"] is not None and worst["best_price"] > worst["max_price"]:
            ly_do = (f"co lenh ban that nhung gia thap nhat {worst['best_price']:.3f} "
                     f"> gia toi da chap nhan {worst['max_price']:.3f} (Gamma bao gia "
                     f"{worst['ask_gamma']:.3f} nhung so lenh that dang ban dat hon)")
        else:
            ly_do = "khong ro (xem debug)"
        return None, (f"do sau THAT khong du (o '{worst['title'] if worst else '?'}' "
                       f"chi kha dung {min_filled_shares:.2f}/{need_shares:.2f} co phan) "
                       f"-- ly do: {ly_do} -> BO QUA")

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

    # CANH BAO QUAN TRONG: moi lenh FAK duoi day duoc gui RIENG LE, tuan tu
    # cho tung o. Giua luc kiem tra do sau (book_depth_avg_price o tren) va
    # luc gui lenh that o day co do tre (nhieu lan goi API tuan tu), gia that
    # co the da doi. FAK chi khop duoc bao nhieu la bay nhieu -- neu 1 o
    # khong khop du shares_use trong khi cac o khac khop du, BO O DANG GIU SE
    # KHONG CON TRON VEN -- mat tinh chat "chac thang du ket qua nao", tao ra
    # rui ro that (giu lech huong). Doan code duoi co gang doc lai SO LUONG
    # THAT SU duoc khop tu response de canh bao neu phat hien thieu -- nhung
    # cau truc chinh xac cua response (ten field) CAN DOI CHIEU voi tai lieu
    # py-clob-client hien hanh, khong duoc tin 100% neu chua tu kiem chung.
    order_ids = []
    fill_reports = []
    for f in filled:
        price = round(f["avg"] if f["avg"] is not None else f["ask"], 3)
        args = OrderArgs(price=price, size=shares_use, side=Side.BUY, token_id=f["token_id"])
        # create_and_post_order (py-clob-client-v2) tu resolve tick_size va
        # TU DONG THU LAI 1 lan neu server bao "invalid order version" (dung
        # loi da gap 30/07/2026 voi thu vien cu) -- an toan hon goi
        # create_order()+post_order() rieng le nhu ban cu.
        resp = client.create_and_post_order(order_args=args, order_type=OrderType.FAK)
        order_id = resp.get("orderID") if isinstance(resp, dict) else str(resp)
        order_ids.append(order_id)
        filled_size = None
        if isinstance(resp, dict):
            for key in ("takingAmount", "matchedAmount", "sizeMatched", "filledSize", "size"):
                if key in resp:
                    try:
                        filled_size = float(resp[key])
                    except (TypeError, ValueError):
                        filled_size = None
                    break
        fill_reports.append({"title": f.get("title"), "requested": shares_use, "reported": filled_size})

    # Chi canh bao khi response THUC SU noi ro so luong khop < yeu cau (>1%
    # lech). Neu khong doc duoc field nao (filled_size=None moi lan), KHONG
    # tu suy dien la loi -- chi la chua biet chac (can doi chieu tai lieu).
    shortfalls = [fr for fr in fill_reports
                  if fr["reported"] is not None and fr["reported"] < fr["requested"] * 0.99]
    incomplete_risk = len(shortfalls) > 0
    note = "DA GUI LENH THAT (FAK) cho tat ca cac o"
    if incomplete_risk:
        chi_tiet = "; ".join(f"{s['title']}: khop {s['reported']:.2f}/{s['requested']:.2f}" for s in shortfalls)
        note += (f" -- CANH BAO RUI RO THAT: co o KHONG khop du so luong yeu cau ({chi_tiet}). "
                 f"BO NAY CO THE KHONG CON TRON VEN -- vao Polymarket kiem tra vi thu cong NGAY.")
    elif not any(fr["reported"] is not None for fr in fill_reports):
        note += (" (khong doc duoc so luong khop that tu response API -- can tu kiem tra thu cong "
                  "tren Polymarket de chac chan da mua du tung o, dung tin 100% vao dong nay)")

    return ({"shares_use": shares_use, "cost": real_cost, "fee": fee_est,
              "locked": locked_actual, "sum_ask_actual": sum_ask_actual,
              "order_ids": order_ids, "incomplete_risk": incomplete_risk},
             note)


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
        if result is None:
            status = "skipped"
        elif not LIVE_TRADING:
            status = "dry_run"
        elif result.get("incomplete_risk"):
            status = "open_CANH_BAO"
        else:
            status = "open"
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
