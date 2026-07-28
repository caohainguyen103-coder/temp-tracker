# -*- coding: utf-8 -*-
"""
common.py — Hàm dùng chung cho hệ thống theo dõi thị trường nhiệt độ Polymarket.

Toàn bộ chỉ dùng thư viện chuẩn của Python (không cần pip install gì).
Mọi cấu trúc dữ liệu ở đây được viết dựa trên response THẬT đã kiểm chứng
ngày 2026-07-09 từ:
  - gamma-api.polymarket.com  (events, markets, tags)
  - api.open-meteo.com        (daily=temperature_2m_max, models=...)
  - mesonet.agron.iastate.edu (IEM - dữ liệu METAR trạm, nguồn tương đương Wunderground)
  - data.weather.gov.hk       (HKO CLMMAXT - nguồn phân giải của thị trường Hong Kong)
"""
import csv
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SNAPSHOTS_CSV = os.path.join(DATA_DIR, "snapshots.csv")
SNAPSHOTS_JSONL = os.path.join(DATA_DIR, "snapshots_full.jsonl")
RESULTS_CSV = os.path.join(DATA_DIR, "results.csv")
STATIONS_JSON = os.path.join(DATA_DIR, "stations.json")

GAMMA = "https://gamma-api.polymarket.com"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"
IEM = "https://mesonet.agron.iastate.edu/api/1"
HKO = "https://data.weather.gov.hk/weatherAPI/opendata/opendata.php"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"

TAG_HIGHEST_TEMPERATURE = "104596"
TAG_LOWEST_TEMPERATURE = "104597"
TAG_DAILY_TEMPERATURE = "103040"

FORECAST_MODELS = [
    "ecmwf_ifs025",
    "gfs_seamless",
    "icon_seamless",
    "ukmo_seamless",
    "best_match",
]

UA = "polymarket-temp-tracker/1.0 (nghien cuu do chinh xac du bao; lien he qua GitHub)"


def http_get_json(url, params=None, retries=3, timeout=30):
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(2 ** attempt)
    print(f"  [LOI] GET {url} -> {last_err}")
    return None


def f_to_c(f):
    return (f - 32.0) * 5.0 / 9.0


def c_to_f(c):
    return c * 9.0 / 5.0 + 32.0


BUCKET_RE = re.compile(
    r"^\s*(-?\d+)\s*(?:[-–]\s*(-?\d+)\s*)?°\s*([CF])\s*(or below|or lower|or higher|or above|\+)?\s*$",
    re.IGNORECASE,
)


def parse_bucket(title):
    if not title:
        return None
    m = BUCKET_RE.match(title.strip())
    if not m:
        return None
    v1 = int(m.group(1))
    v2 = int(m.group(2)) if m.group(2) else None
    unit = m.group(3).upper()
    suffix = (m.group(4) or "").lower()
    if suffix in ("or below", "or lower"):
        return {"lo": None, "hi": v1, "unit": unit, "kind": "le"}
    if suffix in ("or higher", "or above", "+"):
        return {"lo": v1, "hi": None, "unit": unit, "kind": "ge"}
    if v2 is not None:
        return {"lo": v1, "hi": v2, "unit": unit, "kind": "range"}
    return {"lo": v1, "hi": v1, "unit": unit, "kind": "eq"}


def bucket_contains(bucket, value_native, precision="whole"):
    if value_native is None or bucket is None:
        return None
    if precision == "decimal":
        v = value_native
        if bucket["kind"] == "le":
            return v < bucket["hi"] + 1
        if bucket["kind"] == "ge":
            return v >= bucket["lo"]
        return bucket["lo"] <= v < bucket["hi"] + 1
    v = round(value_native)
    if bucket["kind"] == "le":
        return v <= bucket["hi"]
    if bucket["kind"] == "ge":
        return v >= bucket["lo"]
    return bucket["lo"] <= v <= bucket["hi"]


def bucket_mid_c(bucket, precision="whole"):
    if bucket is None:
        return None
    if bucket["kind"] == "le":
        mid = bucket["hi"] - 0.5
    elif bucket["kind"] == "ge":
        mid = bucket["lo"] + 0.5
    else:
        mid = (bucket["lo"] + bucket["hi"]) / 2.0
        if precision == "decimal":
            mid += 0.5
    return f_to_c(mid) if bucket["unit"] == "F" else mid


def bucket_label(bucket):
    if bucket is None:
        return ""
    u = "°" + bucket["unit"]
    if bucket["kind"] == "le":
        return f"<={bucket['hi']}{u}"
    if bucket["kind"] == "ge":
        return f">={bucket['lo']}{u}"
    if bucket["kind"] == "range":
        return f"{bucket['lo']}-{bucket['hi']}{u}"
    return f"{bucket['lo']}{u}"


def resolve_station(event, station_cache):
    src = (event.get("resolutionSource") or "").strip()
    desc = event.get("description") or ""

    if "weather.gov.hk" in src or "Hong Kong Observatory" in desc:
        return {
            "kind": "hko", "id": "HKO", "network": "",
            "lat": 22.302, "lon": 114.174, "tz": "Asia/Hong_Kong",
            "precision": "decimal",
        }

    icao = None
    if "wunderground.com/history/daily/" in src:
        path = src.split("wunderground.com/history/daily/", 1)[1]
        segs = [s for s in re.split(r"[/?#]", path) if s]
        last = segs[-1] if segs else ""
        if re.fullmatch(r"[A-Z0-9]{4}", last):
            icao = last
    if icao:
        meta = station_cache.get(icao)
        if not meta:
            j = http_get_json(f"{IEM}/station/{icao}.json")
            try:
                row = j["data"][0]
                meta = {
                    "kind": "metar", "id": icao, "network": row["network"],
                    "lat": row["latitude"], "lon": row["longitude"],
                    "tz": row["tzname"],
                }
            except (TypeError, KeyError, IndexError):
                meta = None
            if meta:
                station_cache[icao] = meta
        if meta:
            out = dict(meta)
            out["precision"] = "decimal" if "one decimal" in desc else "whole"
            return out

    city = city_from_ticker(event.get("ticker") or event.get("slug") or "")
    if city:
        j = http_get_json(GEOCODE, {"name": city.replace("-", " "), "count": 1})
        try:
            r = j["results"][0]
            return {
                "kind": "geocode", "id": city, "network": "",
                "lat": r["latitude"], "lon": r["longitude"], "tz": r["timezone"],
                "precision": "decimal" if "one decimal" in desc else "whole",
            }
        except (TypeError, KeyError, IndexError):
            pass
    return None


TICKER_RE = re.compile(
    r"(?:highest|lowest)-temperature-in-(.+?)-on-([a-z]+)-(\d{1,2})-(\d{4})"
)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def city_from_ticker(ticker):
    m = TICKER_RE.match(ticker or "")
    return m.group(1) if m else None


def date_from_event(event):
    if event.get("eventDate"):
        return event["eventDate"]
    m = TICKER_RE.match(event.get("ticker") or event.get("slug") or "")
    if m:
        mon = MONTHS.get(m.group(2))
        if mon:
            return f"{int(m.group(4)):04d}-{mon:02d}-{int(m.group(3)):02d}"
    return None


def load_station_cache():
    try:
        with open(STATIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_station_cache(cache):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def append_csv(path, fieldnames, rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerows(rows)


def read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def today_utc():
    return datetime.now(timezone.utc).date()


def parse_iso_date(s):
    return date.fromisoformat(s)
