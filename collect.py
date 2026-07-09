# -*- coding: utf-8 -*-
"""
collect.py — Chạy hàng ngày (GitHub Actions): chụp "snapshot" mọi thị trường
"Highest temperature in <thành phố> on <ngày>?" đang mở trên Polymarket,
kèm dự báo Tmax cùng ngày từ 5 mô hình thời tiết qua Open-Meteo.

Mỗi lần chạy ghi thêm:
  data/snapshots.csv        — 1 dòng / event / lần chạy (dữ liệu phẳng, dễ phân tích)
  data/snapshots_full.jsonl — toàn bộ vector xác suất bucket (chi tiết đầy đủ)

Thiết kế quan trọng:
- Khám phá event qua tag "Highest temperature" (id 104596) + lưới an toàn là
  lọc tiêu đề bằng regex, nên khi Polymarket thêm thành phố mới thì tự bắt được.
- Dự báo lấy tại TỌA ĐỘ TRẠM PHÂN GIẢI (sân bay/HKO), không phải trung tâm
  thành phố — vì thị trường phân giải bằng số đo của trạm đó.
- lead_days = ngày mục tiêu − ngày hiện tại tại trạm (theo múi giờ trạm).
  Phân tích pattern chủ yếu dùng lead_days >= 1 (dự báo trước ít nhất 1 ngày).
"""
import json
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # Python < 3.9
    ZoneInfo = None

import common as C

SNAPSHOT_FIELDS = [
    "snapshot_utc", "event_slug", "city", "target_date", "lead_days",
    "unit", "precision", "station_kind", "station_id", "lat", "lon", "tz",
    "n_buckets", "pm_top_bucket", "pm_top_prob", "pm_top_bid", "pm_top_ask",
    "pm_ev_c", "volume24hr", "liquidity",
    "fc_ecmwf_ifs025_c", "fc_gfs_seamless_c", "fc_icon_seamless_c",
    "fc_ukmo_seamless_c", "fc_best_match_c",
]

TITLE_RE = "Highest temperature in"


def fetch_temperature_events():
    """Lấy toàn bộ event nhiệt độ đang mở, phân trang đầy đủ."""
    events, seen = [], set()
    for tag in (C.TAG_HIGHEST_TEMPERATURE, C.TAG_DAILY_TEMPERATURE):
        offset = 0
        while True:
            page = C.http_get_json(f"{C.GAMMA}/events", {
                "tag_id": tag, "closed": "false", "active": "true",
                "limit": 100, "offset": offset,
            })
            if not page:
                break
            for ev in page:
                if ev.get("slug") in seen:
                    continue
                if TITLE_RE.lower() in (ev.get("title") or "").lower():
                    seen.add(ev["slug"])
                    events.append(ev)
            if len(page) < 100:
                break
            offset += 100
    return events


def parse_markets(event):
    """Trích bucket + xác suất từ các market con. outcomePrices là chuỗi JSON
    (đã kiểm chứng): '["0.0005", "0.9995"]' với index 0 = Yes."""
    buckets = []
    for mk in event.get("markets", []):
        b = C.parse_bucket(mk.get("groupItemTitle"))
        if b is None:
            continue
        try:
            prices = json.loads(mk.get("outcomePrices") or "[]")
            p_yes = float(prices[0])
        except (ValueError, IndexError, TypeError):
            p_yes = None
        buckets.append({
            "bucket": b,
            "label": C.bucket_label(b),
            "p_yes": p_yes,
            "bid": mk.get("bestBid"),
            "ask": mk.get("bestAsk"),
            "volume": mk.get("volumeNum"),
            "slug": mk.get("slug"),
        })
    return buckets


def get_forecasts(lat, lon, target_date):
    """Tmax (°C) cho target_date từ 5 mô hình. Đã kiểm chứng cấu trúc:
    daily.time + daily.temperature_2m_max_<model>."""
    j = C.http_get_json(C.OPEN_METEO, {
        "latitude": round(lat, 4), "longitude": round(lon, 4),
        "daily": "temperature_2m_max",
        "models": ",".join(C.FORECAST_MODELS),
        "timezone": "auto", "forecast_days": 8,
    })
    out = {m: None for m in C.FORECAST_MODELS}
    try:
        times = j["daily"]["time"]
        idx = times.index(target_date)
    except (TypeError, KeyError, ValueError):
        return out
    for m in C.FORECAST_MODELS:
        key = f"temperature_2m_max_{m}"
        if key not in j["daily"] and len(C.FORECAST_MODELS) == 1:
            key = "temperature_2m_max"
        vals = j["daily"].get(key)
        if vals and idx < len(vals) and vals[idx] is not None:
            out[m] = round(float(vals[idx]), 1)
    return out


def local_today(tzname):
    if ZoneInfo and tzname:
        try:
            return datetime.now(ZoneInfo(tzname)).date()
        except Exception:  # noqa: BLE001
            pass
    return C.today_utc()


def main():
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    station_cache = C.load_station_cache()
    events = fetch_temperature_events()
    print(f"Tim thay {len(events)} event nhiet do dang mo.")

    # chống ghi trùng: mỗi event chỉ 1 snapshot / ngày UTC
    existing = {(r["event_slug"], r["snapshot_utc"][:10]) for r in C.read_csv(C.SNAPSHOTS_CSV)}

    rows, full_rows = [], []
    for ev in events:
        slug = ev.get("slug", "")
        target = C.date_from_event(ev)
        city = C.city_from_ticker(ev.get("ticker") or slug) or ""
        if not target or (slug, now_utc[:10]) in existing:
            continue
        station = C.resolve_station(ev, station_cache)
        if not station:
            print(f"  [BO QUA] khong xac dinh duoc tram: {slug}")
            continue
        # Bỏ qua event "rác" còn sót: ngày mục tiêu đã qua từ trước khi ta theo dõi
        if (C.parse_iso_date(target) - local_today(station["tz"])).days < 0:
            continue
        buckets = parse_markets(ev)
        if not buckets:
            print(f"  [BO QUA] khong parse duoc bucket: {slug}")
            continue

        unit = buckets[0]["bucket"]["unit"]
        precision = station["precision"]
        lead = (C.parse_iso_date(target) - local_today(station["tz"])).days

        # EV = trung bình có trọng số xác suất của điểm giữa các bucket (°C)
        wsum = sum(b["p_yes"] for b in buckets if b["p_yes"] is not None)
        ev_c = None
        if wsum and wsum > 0.5:  # bỏ qua nếu giá quá thiếu (thị trường mới mở)
            ev_c = round(sum(
                (b["p_yes"] or 0) * C.bucket_mid_c(b["bucket"], precision)
                for b in buckets if b["p_yes"] is not None) / wsum, 2)

        top = max(buckets, key=lambda b: (b["p_yes"] or 0))
        fc = get_forecasts(station["lat"], station["lon"], target)

        rows.append({
            "snapshot_utc": now_utc, "event_slug": slug, "city": city,
            "target_date": target, "lead_days": lead,
            "unit": unit, "precision": precision,
            "station_kind": station["kind"], "station_id": station["id"],
            "lat": station["lat"], "lon": station["lon"], "tz": station["tz"],
            "n_buckets": len(buckets),
            "pm_top_bucket": top["label"], "pm_top_prob": top["p_yes"],
            "pm_top_bid": top["bid"], "pm_top_ask": top["ask"],
            "pm_ev_c": ev_c,
            "volume24hr": ev.get("volume24hr"), "liquidity": ev.get("liquidity"),
            "fc_ecmwf_ifs025_c": fc["ecmwf_ifs025"],
            "fc_gfs_seamless_c": fc["gfs_seamless"],
            "fc_icon_seamless_c": fc["icon_seamless"],
            "fc_ukmo_seamless_c": fc["ukmo_seamless"],
            "fc_best_match_c": fc["best_match"],
        })
        full_rows.append({
            "snapshot_utc": now_utc, "event_slug": slug, "target_date": target,
            "buckets": [{"label": b["label"], "p": b["p_yes"],
                         "bid": b["bid"], "ask": b["ask"], "vol": b["volume"]}
                        for b in buckets],
            "forecasts_c": fc,
        })
        print(f"  OK {slug} (lead {lead}d, top {top['label']} @ {top['p_yes']})")

    if rows:
        C.append_csv(C.SNAPSHOTS_CSV, SNAPSHOT_FIELDS, rows)
        with open(C.SNAPSHOTS_JSONL, "a", encoding="utf-8") as f:
            for r in full_rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    C.save_station_cache(station_cache)
    print(f"Da ghi {len(rows)} snapshot.")


if __name__ == "__main__":
    main()
