# -*- coding: utf-8 -*-
"""
verify.py — Chạy hàng ngày sau collect.py: với mỗi ngày mục tiêu đã qua,
lấy (1) bucket thắng cuộc theo chính Polymarket và (2) nhiệt độ thực đo,
rồi ghi vào data/results.csv.

Nguồn "nhiệt độ thực đo" — theo thứ tự ưu tiên, có ghi rõ nguồn:
 1. resolved_bucket: bucket mà thị trường đã phân giải (outcomePrices -> 1.0).
 2. actual_c: trạm METAR qua IEM (cùng dữ liệu gốc với Wunderground);
    HKO cho Hong Kong; lưới Open-Meteo chỉ là phương án cuối (ghi rõ nguồn).

Ghi chú vận hành (rút ra từ dữ liệu thật ngày đầu):
 - Thị trường thường phân giải sau khi nguồn công bố datapoint đầu tiên của
   ngày hôm sau -> ta CHỜ tối đa RESOLVE_WAIT_DAYS ngày cho đến khi có bucket
   thắng cuộc rồi mới ghi, tránh ghi sớm bị trống cột resolved_bucket.
 - Trạm Mỹ trong IEM dùng mã 3 ký tự + network theo bang (LGA/NY_ASOS),
   không phải ICAO 4 ký tự (KLGA) -> có bước thử lại bỏ chữ K đầu.
"""
import json
import re
from datetime import datetime, timedelta, timezone

import common as C

RESULT_FIELDS = [
    "target_date", "event_slug", "city", "unit", "precision",
    "station_kind", "station_id",
    "resolved_bucket", "actual_c", "actual_native", "actual_source",
    "verify_utc",
]

RESOLVE_WAIT_DAYS = 4   # chờ thị trường phân giải tối đa chừng này ngày
MAX_WAIT_DAYS = 12      # quá hạn này thì ghi nhận UNRESOLVED


def get_resolved_bucket(slug):
    """Sau khi phân giải, market thắng có outcomePrices ~ ["1","0"].
    Trả về (label, closed?)."""
    j = C.http_get_json(f"{C.GAMMA}/events", {"slug": slug})
    if not j:
        return None, False
    ev = j[0] if isinstance(j, list) and j else None
    if not ev:
        return None, False
    closed = bool(ev.get("closed"))
    for mk in ev.get("markets", []):
        try:
            p_yes = float(json.loads(mk.get("outcomePrices") or "[]")[0])
        except (ValueError, IndexError, TypeError):
            continue
        if p_yes >= 0.99 and mk.get("closed"):
            b = C.parse_bucket(mk.get("groupItemTitle"))
            if b:
                return C.bucket_label(b), closed
    return None, closed


def iem_lookup_network(sid):
    j = C.http_get_json(f"{C.IEM}/station/{sid}.json")
    try:
        return j["data"][0]["network"]
    except (TypeError, KeyError, IndexError):
        return None


def actual_from_iem(station_id, network, target_date):
    """IEM daily summary: max_tmpf (°F) tính từ METAR, ngày theo giờ địa
    phương trạm. Trạm Mỹ: thử thêm mã bỏ chữ K (KLGA -> LGA, network NY_ASOS).
    Trả về (°C, °F)."""
    d = C.parse_iso_date(target_date)
    candidates = [(station_id, network)]
    if re.fullmatch(r"K[A-Z0-9]{3}", station_id or ""):
        sid2 = station_id[1:]
        net2 = iem_lookup_network(sid2)
        if net2:
            candidates.append((sid2, net2))
    for sid, net in candidates:
        if not net:
            continue
        j = C.http_get_json(f"{C.IEM}/daily.json", {
            "station": sid, "network": net,
            "year": d.year, "month": d.month,
        })
        try:
            for row in j["data"]:
                if row["date"] == target_date and row["max_tmpf"] is not None:
                    f = float(row["max_tmpf"])
                    return round(C.f_to_c(f), 1), round(f, 1)
        except (TypeError, KeyError):
            pass
    return None, None


def actual_from_hko(target_date):
    """HKO CLMMAXT (°C, 1 chữ số thập phân) — nguồn phân giải chính thức của
    HK; công bố chậm, thường rỗng cho tháng hiện tại."""
    d = C.parse_iso_date(target_date)
    j = C.http_get_json(C.HKO, {
        "dataType": "CLMMAXT", "rformat": "json", "station": "HKO",
        "year": d.year, "month": d.month,
    })
    try:
        for row in j["data"]:
            if int(row[0]) == d.year and int(row[1]) == d.month and int(row[2]) == d.day:
                v = float(row[3])
                return round(v, 1), round(v, 1)
    except (TypeError, KeyError, ValueError, IndexError):
        pass
    return None, None


def actual_from_openmeteo(lat, lon, target_date, unit):
    """Phương án cuối: phân tích lưới Open-Meteo (best_match)."""
    days_ago = (C.today_utc() - C.parse_iso_date(target_date)).days
    if days_ago <= 6:
        j = C.http_get_json(C.OPEN_METEO, {
            "latitude": round(lat, 4), "longitude": round(lon, 4),
            "daily": "temperature_2m_max", "timezone": "auto",
            "past_days": min(days_ago + 1, 7), "forecast_days": 1,
        })
    else:
        j = C.http_get_json(C.OPEN_METEO_ARCHIVE, {
            "latitude": round(lat, 4), "longitude": round(lon, 4),
            "daily": "temperature_2m_max", "timezone": "auto",
            "start_date": target_date, "end_date": target_date,
        })
    try:
        idx = j["daily"]["time"].index(target_date)
        c = j["daily"]["temperature_2m_max"][idx]
        if c is None:
            return None, None
        c = float(c)
        native = C.c_to_f(c) if unit == "F" else c
        return round(c, 1), round(native, 1)
    except (TypeError, KeyError, ValueError):
        return None, None


def station_network(snapshot_row):
    sid = snapshot_row["station_id"]
    cache = C.load_station_cache()
    meta = cache.get(sid)
    if meta and meta.get("network"):
        return meta["network"]
    return iem_lookup_network(sid) or (sid[:2] + "__ASOS")


def main():
    snaps = C.read_csv(C.SNAPSHOTS_CSV)
    done = {r["event_slug"] for r in C.read_csv(C.RESULTS_CSV)}
    today = C.today_utc()

    pending = {}
    for r in snaps:
        if r["event_slug"] in done:
            continue
        if C.parse_iso_date(r["target_date"]) <= today - timedelta(days=1):
            pending[r["event_slug"]] = r
    print(f"Can verify {len(pending)} event.")

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = []
    for slug, r in sorted(pending.items()):
        resolved, closed = get_resolved_bucket(slug)
        age = (today - C.parse_iso_date(r["target_date"])).days

        # Chưa phân giải và còn trong hạn chờ -> để mai verify lại,
        # tránh ghi sớm làm trống cột resolved_bucket vĩnh viễn.
        if resolved is None and age < RESOLVE_WAIT_DAYS:
            print(f"  [CHO] {slug}: thi truong chua phan giai (thu lai sau)")
            continue

        actual_c = actual_native = None
        source = ""
        kind = r["station_kind"]
        if kind == "metar":
            actual_c, actual_f = actual_from_iem(
                r["station_id"], station_network(r), r["target_date"])
            actual_native = actual_f if r["unit"] == "F" else actual_c
            source = "iem_metar" if actual_c is not None else ""
        elif kind == "hko":
            actual_c, actual_native = actual_from_hko(r["target_date"])
            source = "hko_official" if actual_c is not None else ""
            if actual_c is None:
                actual_c, _f = actual_from_iem("VHHH", "HK__ASOS", r["target_date"])
                actual_native = actual_c
                source = "iem_vhhh_proxy" if actual_c is not None else ""
        if actual_c is None:
            actual_c, actual_native = actual_from_openmeteo(
                float(r["lat"]), float(r["lon"]), r["target_date"], r["unit"])
            source = "openmeteo_grid" if actual_c is not None else ""

        if resolved is None and actual_c is None and age < MAX_WAIT_DAYS:
            print(f"  [CHO] {slug}: chua co so lieu thuc do (thu lai sau)")
            continue
        if resolved is None and age >= MAX_WAIT_DAYS and actual_c is None:
            resolved = "UNRESOLVED"

        rows.append({
            "target_date": r["target_date"], "event_slug": slug,
            "city": r["city"], "unit": r["unit"], "precision": r["precision"],
            "station_kind": kind, "station_id": r["station_id"],
            "resolved_bucket": resolved or "",
            "actual_c": actual_c if actual_c is not None else "",
            "actual_native": actual_native if actual_native is not None else "",
            "actual_source": source, "verify_utc": now_utc,
        })
        print(f"  OK {slug}: bucket={resolved} thuc do={actual_c}°C ({source})")

    if rows:
        C.append_csv(C.RESULTS_CSV, RESULT_FIELDS, rows)
    print(f"Da ghi {len(rows)} ket qua.")


if __name__ == "__main__":
    main()
