# -*- coding: utf-8 -*-
"""
live_trade12_ws.py — BAN REAL-TIME (WebSocket) cua CD12 tien that.

VI SAO CO BAN NAY: ban goc live_trade12.py chay theo kieu "quet dinh ky"
(moi 15-30s goi lai): dung Gamma API (co the tre so voi thi truong that) de
tim ung vien, roi moi goi REST API kiem tra do sau that. Qua 21 tieng chay
that (29-30/07/2026), ~175 lan thu, 0 lan khop -- chan doan cho thay: dung
luc gia ly thuyet (Gamma) trong re, so lenh that thuong CHUA kip co du
nguoi ban o gia do; luc so lenh that du sau tro lai thi gia da doi, co hoi
da mat. Day la van de TOC DO/DO TRE DU LIEU, khong phai bug chon sai token
(da xac minh rieng bang diag_token.py, gia token 'Yes' khop sat voi gia
Gamma o moi o).

BAN NAY sua bang cach: dung WebSocket cua chinh Polymarket CLOB
(wss://ws-subscriptions-clob.polymarket.com/ws/market) de nhan so lenh that
THEO THOI GIAN THUC (book snapshot + price_change) cho tat ca cac o dang
theo doi, roi tu tinh toan co hoi truc tiep tren du lieu that trong bo nho
-- KHONG con phu thuoc gia Gamma cho phan quyet dinh mua/khong mua (Gamma
chi con dung de PHAT HIEN su kien/o nao ton tai, khong dung de dinh gia).

Tai lieu tham khao (30/07/2026): https://docs.polymarket.com/market-data/websocket/market-channel
va https://docs.polymarket.com/market-data/websocket/overview

VAN GIU NGUYEN TOAN BO CO CHE AN TOAN cua ban goc:
  - Mac dinh DRY-RUN (LIVE_TRADING=1 moi that su gui lenh)
  - CD12_LIVE_STAKE, CD12_LIVE_MIN_NET, CD12_LIVE_MAX_TRADES,
    CD12_LIVE_DAILY_LOSS_LIMIT, CD12_LIVE_SLIPPAGE_PCT (dung chung config
    voi ban REST, xem live_trade12.py)
  - data/LIVE_PAUSE kill-switch
  - Ghi vao CUNG FILE data/trades12_live.csv (cung schema) de dashboard
    khong can sua gi them.

CHUA THE TU KIEM TRA (khong the ket noi WebSocket that tu moi trong toi):
  hay CHAY THU O DRY-RUN TRUOC (khong dat LIVE_TRADING=1) mot thoi gian de
  xem log co hop ly khong (ket noi on dinh, book cap nhat dung, tinh toan
  co hoi hop ly) TRUOC KHI bat LIVE_TRADING=1.

Chay tren VPS:
  pip install websockets --break-system-packages   (chi can 1 lan)
  cd /root/temp-tracker
  source /root/live12_secrets.env
  python3 live_trade12_ws.py                # dry-run neu LIVE_TRADING != 1
"""
import asyncio
import json
import os
import sys
import time
import traceback
from datetime import datetime, timezone

import websockets

import common as C
import collect
from paper_trade12 import full_set_asks, set_economics, FEE_RATE
from live_trade12 import (
    get_client, _yes_token_id, BOUGHT_STATUSES,
    LIVE_TRADING, SET_STAKE, MIN_NET_LIVE, MAX_TRADES_PER_RUN,
    DAILY_LOSS_LIMIT, SLIPPAGE_TICKS_PCT, PAUSE_FILE, LIVE_CSV, LIVE_FIELDS,
    daily_realized_pnl,
)

try:
    from py_clob_client.clob_types import OrderArgs, OrderType
    from py_clob_client.order_builder.constants import BUY
except ImportError:
    OrderArgs = OrderType = BUY = None

WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
REFRESH_EVENTS_SEC = 45     # tan suat quet lai Gamma de tim su kien/o moi
PING_INTERVAL_SEC = 8       # < 10s theo yeu cau cua Polymarket
MAX_LEAD_DAYS = 2
MIN_BUCKETS = 3

# ============================== TRANG THAI TRONG BO NHO ======================
books = {}          # token_id -> {"asks": {price_str: size_str}, "bids": {...}}
token_meta = {}     # token_id -> event_slug (o nao thuoc su kien nao)
events_meta = {}    # event_slug -> {"city":, "target_date":, "tokens": [token_id,...]}
subscribed_ids = set()
ws_conn = None      # websocket dang mo (de gui subscribe dong)
n_done_this_process = 0
log_lock = asyncio.Lock()


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# ============================== QUET SU KIEN (Gamma, dinh ky) ================
# LUU Y VE THREAD-SAFETY: ham fetch_new_events_meta() chay trong 1 THREAD
# RIENG (qua run_in_executor, vi no goi mang/blocking), CON events_meta/
# token_meta/books lai duoc doc/ghi tu vong lap asyncio chinh (thread khac).
# NEU sua truc tiep 3 dict do trong ham chay o thread rieng, se co RUI RO
# DUA DU LIEU (race condition) that su: vong lap chinh co the doc du lieu
# dang do dang sua (vd events_meta.clear() xong nhung chua kip .update()).
# CACH SUA: ham fetch_new_events_meta() CHI goi API va TRA VE ket qua (an
# toan chay o thread rieng, khong dong vao du lieu chia se); viec THUC SU
# cap nhat events_meta/token_meta/books do ham apply_events_meta() lam,
# va ham nay LUON duoc goi tren THREAD CHINH (khong qua executor) trong
# refresh_loop() ben duoi -- dam bao chi 1 thread duy nhat (thread chinh
# cua asyncio) dung cham vao 3 dict nay.
def fetch_new_events_meta():
    """CHI goi API (Gamma), KHONG dong vao du lieu chia se. An toan chay
    trong executor thread rieng."""
    have_bought = {r["event_slug"] for r in C.read_csv(LIVE_CSV)
                   if r.get("status") in BOUGHT_STATUSES}
    today = C.today_utc()
    events = collect.fetch_temperature_events() + collect.fetch_lowest_temperature_events()

    new_events_meta = {}
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
        if lead < 0 or lead > MAX_LEAD_DAYS:
            continue
        asks = full_set_asks(ev)
        if asks is None or len(asks) < MIN_BUCKETS:
            continue

        tokens = []
        ok = True
        for mk in ev.get("markets", []):
            b = C.parse_bucket(mk.get("groupItemTitle"))
            if b is None or mk.get("closed") or not mk.get("active"):
                continue
            yes_token = _yes_token_id(mk)
            if yes_token is None:
                ok = False
                break
            tokens.append(yes_token)
        if not ok or len(tokens) < MIN_BUCKETS:
            continue

        new_events_meta[slug] = {"city": city, "target_date": target, "tokens": tokens}

    return new_events_meta


def apply_events_meta(new_events_meta):
    """CHI duoc goi tren THREAD CHINH (khong qua executor) -- xem ghi chu o
    tren. Cap nhat events_meta/token_meta/books, tra ve (to_subscribe,
    to_unsubscribe)."""
    old_ids = set(token_meta.keys())
    new_ids = set()
    new_token_meta = {}
    for slug, meta in new_events_meta.items():
        for tid in meta["tokens"]:
            new_ids.add(tid)
            new_token_meta[tid] = slug

    to_subscribe = new_ids - old_ids
    to_unsubscribe = old_ids - new_ids

    events_meta.clear()
    events_meta.update(new_events_meta)
    token_meta.clear()
    token_meta.update(new_token_meta)
    for tid in to_unsubscribe:
        books.pop(tid, None)

    return list(to_subscribe), list(to_unsubscribe)


# ============================== CAP NHAT SO LENH TU WS =======================
def _pf(price_str):
    """Chuan hoa gia ve float. QUAN TRONG: message 'book' cua Polymarket dung
    dinh dang gia kieu '.52' con message 'price_change' co the dung '0.52' --
    NEU dung nguyen chuoi lam khoa dict, xoa/cap nhat muc gia se bi LECH (vd
    xoa '0.52' nhung book dang luu key '.52' -> khong xoa duoc gi, so lenh
    trong bo nho se dan sai lech thuc te). Luon ep ve float truoc khi dung
    lam khoa de tranh loi nay (da phat hien qua test truoc khi trien khai)."""
    try:
        return round(float(price_str), 6)
    except (TypeError, ValueError):
        return None


def apply_book(msg):
    tid = msg.get("asset_id")
    if not tid:
        return
    bids = {}
    for lvl in msg.get("bids", []):
        p = _pf(lvl.get("price"))
        if p is not None:
            bids[p] = lvl.get("size")
    asks = {}
    for lvl in msg.get("asks", []):
        p = _pf(lvl.get("price"))
        if p is not None:
            asks[p] = lvl.get("size")
    books[tid] = {"bids": bids, "asks": asks}


def apply_price_change(msg):
    touched_slugs = set()
    for ch in msg.get("price_changes", []):
        tid = ch.get("asset_id")
        if not tid:
            continue
        side = "bids" if ch.get("side") == "BUY" else "asks"
        book = books.setdefault(tid, {"bids": {}, "asks": {}})
        price = _pf(ch.get("price"))
        size = ch.get("size")
        if price is None:
            continue
        if size in ("0", 0, 0.0):
            book[side].pop(price, None)
        else:
            book[side][price] = size
        slug = token_meta.get(tid)
        if slug:
            touched_slugs.add(slug)
    return touched_slugs


def best_ask_from_book(tid):
    book = books.get(tid)
    if not book or not book.get("asks"):
        return None
    try:
        return min(book["asks"].keys())
    except ValueError:
        return None


def depth_at_max_price(tid, need_shares, max_price):
    """Giong book_depth_avg_price cua ban REST, nhung doc tu bo nho (khong
    goi API) -- day la diem mau chot giup nhanh hon nhieu so voi ban goc."""
    book = books.get(tid)
    if not book:
        return 0.0, None
    asks = sorted(((p, float(s)) for p, s in book["asks"].items()), key=lambda x: x[0])
    got, cost = 0.0, 0.0
    for price, size in asks:
        if price > max_price or got >= need_shares:
            break
        take = min(size, need_shares - got)
        got += take
        cost += take * price
    avg = (cost / got) if got > 0 else None
    return got, avg


# ============================== VAO LENH (dung lai logic ban goc) ===========
# THREAD-SAFETY: evaluate_event() CHI DOC events_meta/books (khong ghi mang,
# khong cham client) nen PHAI duoc goi tren THREAD CHINH (truc tiep, KHONG
# qua run_in_executor) -- day la thread duy nhat duoc ghi vao books qua
# apply_book/apply_price_change, nen doc o day luon nhat quan, khong dua du
# lieu. Ket qua (1 "plan" dict thuan du lieu, khong con tham chieu toi
# books/events_meta) sau do moi duoc dua sang execute_entry() de chay trong
# executor thread (vi buoc do MOI thuc su goi mang/blocking qua client).
def evaluate_event(slug):
    """Chi tinh toan (nhanh, khong blocking) dua tren du lieu WS dang co
    trong bo nho. Tra ve None neu chua du dieu kien, hoac 1 dict 'plan' neu
    du dieu kien vao lenh (chua thuc su dat lenh)."""
    meta = events_meta.get(slug)
    if not meta:
        return None
    tokens = meta["tokens"]

    real_asks = []
    for tid in tokens:
        a = best_ask_from_book(tid)
        if a is None:
            return None  # chua co du lieu so lenh cho o nay -- cho lan sau
        real_asks.append(a)

    s = sum(real_asks)
    if s <= 0 or s >= 1.0:
        return None
    shares = round(SET_STAKE / s, 2)
    cost_theo = round(shares * s, 2)
    fee_theo = round(sum(FEE_RATE * a * (1 - a) * shares for a in real_asks), 4)
    locked_theo = round(shares * 1.0 - cost_theo - fee_theo, 2)
    if locked_theo < MIN_NET_LIVE:
        return None

    need_shares = shares
    filled = []
    min_filled = need_shares
    for tid, ask in zip(tokens, real_asks):
        max_price = min(ask * (1 + SLIPPAGE_TICKS_PCT), 0.99)
        got, avg = depth_at_max_price(tid, need_shares, max_price)
        filled.append({"token_id": tid, "ask": ask, "got": got, "avg": avg})
        min_filled = min(min_filled, got)

    if min_filled < need_shares * 0.5:
        return None  # khong du do sau that -- cho book cap nhat tiep

    shares_use = round(min_filled, 2)
    real_asks2 = [f["avg"] if f["avg"] is not None else f["ask"] for f in filled]
    real_cost = round(shares_use * sum(real_asks2), 2)
    fee_est = round(sum(FEE_RATE * a * (1 - a) * shares_use for a in real_asks2), 4)
    locked_actual = round(shares_use * 1.0 - real_cost - fee_est, 2)
    sum_ask_actual = round(sum(real_asks2), 4)

    if locked_actual < MIN_NET_LIVE:
        return None

    return {
        "slug": slug, "city": meta["city"], "target_date": meta["target_date"],
        "n_buckets": len(tokens), "sum_ask_theoretical": round(s, 4),
        "shares_theoretical": shares, "filled": filled, "shares_use": shares_use,
        "sum_ask_actual": sum_ask_actual, "real_cost": real_cost,
        "fee_est": fee_est, "locked_actual": locked_actual,
    }


def execute_entry(client, plan):
    """Chay trong executor thread (goi mang: client.create_order/post_order
    neu LIVE_TRADING=1, cong voi ghi CSV). KHONG dong vao books/events_meta
    -- chi dung du lieu da duoc trich xuat san trong 'plan'."""
    slug = plan["slug"]
    shares_use = plan["shares_use"]
    filled = plan["filled"]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    note = "[WS] "
    order_ids = []
    status = "dry_run"

    if not LIVE_TRADING:
        note += "DRY-RUN (WebSocket real-time): se mua nhung KHONG gui lenh that."
    else:
        # Kiem tra lai PAUSE_FILE va DAILY_LOSS_LIMIT ngay truoc khi bam nut
        # that (vi tien trinh nay chay lien tuc, khong phai 1 lan roi thoat
        # nhu ban REST -- trang thai co the doi trong luc chay).
        if os.path.exists(PAUSE_FILE):
            log(f"[TAM DUNG] {PAUSE_FILE} ton tai -> bo qua co hoi cua {slug}.")
            return False
        if daily_realized_pnl() <= -abs(DAILY_LOSS_LIMIT):
            log("[DUNG KHAN] Lo thuc te hom nay da cham gioi han -> bo qua.")
            return False

        incomplete_risk = False
        shortfalls = []
        for f in filled:
            price = round(f["avg"] if f["avg"] is not None else f["ask"], 3)
            args = OrderArgs(price=price, size=shares_use, side=BUY, token_id=f["token_id"])
            signed = client.create_order(args)
            resp = client.post_order(signed, OrderType.FAK)
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
            if filled_size is not None and filled_size < shares_use * 0.99:
                shortfalls.append((f["token_id"], filled_size))
                incomplete_risk = True

        status = "open_CANH_BAO" if incomplete_risk else "open"
        note += "DA GUI LENH THAT (FAK, qua WebSocket real-time) cho tat ca cac o"
        if incomplete_risk:
            note += f" -- CANH BAO: co o khong khop du ({shortfalls}). KIEM TRA VI NGAY."

    row = {
        "entry_utc": now, "event_slug": slug, "city": plan["city"],
        "target_date": plan["target_date"], "n_buckets_theoretical": plan["n_buckets"],
        "sum_ask_theoretical": plan["sum_ask_theoretical"],
        "shares_theoretical": plan["shares_theoretical"],
        "sum_ask_actual": plan["sum_ask_actual"], "shares_filled": shares_use,
        "cost_actual": plan["real_cost"], "fee_est": plan["fee_est"],
        "locked_profit_actual": plan["locked_actual"], "status": status,
        "order_ids": ",".join(order_ids), "note": note,
    }
    C.append_csv(LIVE_CSV, LIVE_FIELDS, [row])
    log(f"[{'MUA THAT' if LIVE_TRADING else 'DRY-RUN'}] {plan['city']} {plan['target_date']} "
        f"({slug}) -- {shares_use:.2f} co phan, loi khoa {plan['locked_actual']:.2f}$")
    return True


# ============================== VONG LAP WEBSOCKET ===========================
async def send_subscribe(ws, token_ids, operation=None):
    if not token_ids:
        return
    msg = {"assets_ids": list(token_ids), "type": "market", "custom_feature_enabled": True}
    if operation:
        msg["operation"] = operation
    await ws.send(json.dumps(msg))


async def ping_loop(ws):
    while True:
        await asyncio.sleep(PING_INTERVAL_SEC)
        try:
            await ws.send("PING")
        except Exception:
            return


async def refresh_loop(ws):
    while True:
        try:
            # fetch (goi mang) chay o executor thread; apply (sua du lieu
            # chia se) chay tren thread chinh -- xem ghi chu thread-safety
            # o dinh nghia apply_events_meta().
            new_events_meta = await asyncio.get_event_loop().run_in_executor(
                None, fetch_new_events_meta)
            to_sub, to_unsub = apply_events_meta(new_events_meta)
            if to_unsub:
                await send_subscribe(ws, to_unsub, operation="unsubscribe")
                log(f"[REFRESH] Bo theo doi {len(to_unsub)} token (su kien dong/da mua/het han).")
            if to_sub:
                await send_subscribe(ws, to_sub, operation="subscribe")
                subscribed_ids.update(to_sub)
                log(f"[REFRESH] Them theo doi {len(to_sub)} token moi. "
                    f"Tong dang theo doi: {len(subscribed_ids)} token / {len(events_meta)} su kien.")
        except Exception as e:
            log(f"[LOI refresh_events] {e}")
        await asyncio.sleep(REFRESH_EVENTS_SEC)


async def main_ws_loop():
    global ws_conn, n_done_this_process
    client = get_client() if LIVE_TRADING else None
    if LIVE_TRADING and client is None:
        log("[LOI] LIVE_TRADING=1 nhung khong khoi tao duoc client (thieu API key?). Dung.")
        return

    # Lan dau: quet su kien truoc khi mo WS, de subscribe ngay tu dau.
    # (Chay tren thread chinh, truoc khi vong lap WS bat dau -- an toan.)
    to_sub, _ = apply_events_meta(fetch_new_events_meta())
    log(f"Khoi dong: {len(events_meta)} su kien, {len(to_sub)} token can theo doi.")

    async for ws in websockets.connect(WS_URL, ping_interval=None):
        try:
            ws_conn = ws
            await send_subscribe(ws, list(token_meta.keys()))
            pinger = asyncio.create_task(ping_loop(ws))
            refresher = asyncio.create_task(refresh_loop(ws))
            log(f"Da ket noi WebSocket {WS_URL}, dang cho du lieu...")

            async for raw in ws:
                if raw == "PONG":
                    continue
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                # Message co the la 1 object hoac 1 list cac object
                msgs = msg if isinstance(msg, list) else [msg]
                touched = set()
                for m in msgs:
                    et = m.get("event_type")
                    if et == "book":
                        apply_book(m)
                        slug = token_meta.get(m.get("asset_id"))
                        if slug:
                            touched.add(slug)
                    elif et == "price_change":
                        touched |= apply_price_change(m)
                    # tick_size_change / last_trade_price / best_bid_ask: bo qua
                    # (khong can cho logic vao lenh, chi can book/price_change).

                for slug in touched:
                    if n_done_this_process >= MAX_TRADES_PER_RUN:
                        continue
                    try:
                        # evaluate_event: nhanh, thuan doc du lieu -- goi
                        # TRUC TIEP tren thread chinh (khong qua executor)
                        # de tranh dua du lieu voi apply_book/price_change.
                        plan = evaluate_event(slug)
                        if plan is None:
                            continue
                        # execute_entry: co the goi mang (dat lenh that) --
                        # day moi la phan can chay o thread rieng de khong
                        # chan vong lap nhan tin nhan WS (va PING/PONG).
                        entered = await asyncio.get_event_loop().run_in_executor(
                            None, execute_entry, client, plan)
                        if entered:
                            n_done_this_process += 1
                    except Exception as e:
                        log(f"[LOI xu ly {slug}] {e}\n{traceback.format_exc()}")

                if n_done_this_process >= MAX_TRADES_PER_RUN:
                    log(f"Da dat MAX_TRADES_PER_RUN={MAX_TRADES_PER_RUN} cho tien trinh nay -- "
                        f"thoat de systemd khoi dong lai (lam moi vong dem).")
                    pinger.cancel()
                    refresher.cancel()
                    await ws.close()
                    return

            pinger.cancel()
            refresher.cancel()
        except websockets.ConnectionClosed:
            log("[WS] Mat ket noi -- tu ket noi lai...")
            continue
        except Exception as e:
            log(f"[LOI vong lap WS] {e}\n{traceback.format_exc()}")
            await asyncio.sleep(3)
            continue


if __name__ == "__main__":
    mode = "LIVE_TRADING=1 (LENH THAT SE DUOC GUI)" if LIVE_TRADING else "DRY-RUN (chi mo phong)"
    print(f"=== CD12 LIVE (WebSocket real-time) — {mode} ===")
    if os.path.exists(PAUSE_FILE):
        print(f"[TAM DUNG] File khoa {PAUSE_FILE} dang ton tai -> khong chay.")
        sys.exit(0)
    try:
        asyncio.run(main_ws_loop())
    except KeyboardInterrupt:
        pass
