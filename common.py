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

# Tag id "Highest temperature" trên Polymarket (kiểm chứng 2026-07-09).
# Nếu tag đổi, collect.py còn lớp dự phòng lọc theo tiêu đề event.
TAG_HIGHEST_TEMPERATURE = "104596"
TAG_DAILY_TEMPERATURE = "103040"

# Các mô hình dự báo lấy từ Open-Meteo (đã kiểm chứng tên biến trả về:
# daily.temperature_2m_max_<model>). best_match = mô hình tốt nhất
# Open-Meteo tự chọn cho từng vị trí.
FORECAST_MODELS = [
    "ecmwf_ifs025",   # ECMWF IFS (châu Âu) - thường chính xác nhất thế giới
    "gfs_seamless",   # NOAA GFS (Mỹ)
    "icon_seamless",  # DWD ICON (Đức)
    "ukmo_seamless",  # UK Met Office (Anh)
    "best_match",     # Open-Meteo tự chọn mô hình tốt nhất cho vị trí
]

UA = "polymarket-temp-tracker/1.0 (nghien cuu do chinh xac du bao; lien he qua GitHub)"


def http_get_json(url, params=None, retries=3, timeout=30):
    """GET JSON với retry + backoff. Trả về None nếu thất bại hẳn."""
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


# ---------------------------------------------------------------------------
# Parse bucket nhiệt độ từ groupItemTitle của market.
# Các dạng đã thấy trên thị trường thật: "24°C", "23°C or below", "33°C or higher",
# "14°C or below", "35°C or higher". Dạng °F (thị trường Mỹ trước đây):
# "84°F", "82°F or below", "84-85°F", "86°F or higher", "86°F+".
# ---------------------------------------------------------------------------
BUCKET_RE = re.compile(
    r"^\s*(-?\d+)\s*(?:[-–]\s*(-?\d+)\s*)?°\s*([CF])\s*(or below|or lower|or higher|or above|\+)?\s*$",
    re.IGNORECASE,
)


def parse_bucket(title):
    """Trả về dict {'lo','hi','unit','kind'} hoặc None.
    kind: 'le' (<=), 'ge' (>=), 'eq' (đúng 1 độ), 'range' (khoảng)."""
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
    """value_native: nhiệt độ thực đo theo ĐƠN VỊ GỐC của thị trường.
    precision: 'whole' (làm tròn nguyên độ - Seoul/°F) hay 'decimal'
    (1 chữ số thập phân, bucket N chứa [N, N+1) - Hong Kong)."""
    if value_native is None or bucket is None:
        return None
    if precision == "decimal":
        v = value_native
        if bucket["kind"] == "le":
            return v < bucket["hi"] + 1
        if bucket["kind"] == "ge":
            return v >= bucket["lo"]
        return bucket["lo"] <= v < bucket["hi"] + 1
    # whole: giá trị phân giải là số nguyên
    v = round(value_native)
    if bucket["kind"] == "le":
        return v <= bucket["hi"]
    if bucket["kind"] == "ge":
        return v >= bucket["lo"]
    return bucket["lo"] <= v <= bucket["hi"]


def bucket_mid_c(bucket, precision="whole"):
    """Điểm giữa bucket, đổi về °C — dùng tính kỳ vọng (EV) của thị trường.
    Bucket mở ('or below'/'or higher') lấy mép ± 0.5 độ (quy ước, có ghi chú)."""
    if bucket is None:
        return None
    if bucket["kind"] == "le":
        mid = bucket["hi"] - 0.5
    elif bucket["kind"] == "ge":
        mid = bucket["lo"] + 0.5
    else:
        mid = (bucket["lo"] + bucket["hi"]) / 2.0
        if precision == "decimal":  # bucket N = [N, N+1)
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


# ---------------------------------------------------------------------------
# Xác định trạm quan trắc từ resolutionSource của event.
# Đã kiểm chứng 2 loại nguồn phân giải:
#  1) Wunderground: https://www.wunderground.com/history/daily/kr/incheon/RKSI
#     -> mã ICAO ở cuối URL; dữ liệu gốc là METAR của trạm — IEM cung cấp
#     đúng dữ liệu này miễn phí (max_tmpf theo °F).
#  2) Hong Kong Observatory: https://www.weather.gov.hk/en/cis/climat.htm
#     -> trạm HKO (22.302N 114.174E), "Absolute Daily Max" 1 chữ số thập phân.
# ---------------------------------------------------------------------------
def resolve_station(event, station_cache):
    src = (event.get("resolutionSource") or "").strip()
    desc = event.get("description") or ""

    if "weather.gov.hk" in src or "Hong Kong Observatory" in desc:
        return {
            "kind": "hko", "id": "HKO", "network": "",
            "lat": 22.302, "lon": 114.174, "tz": "Asia/Hong_Kong",
            "precision": "decimal",
        }

    m = re.search(r"wunderground\.com/history/daily/[^/]+/[^/]+/([A-Za-z0-9]{3,5})", src)
    if m:
        icao = m.group(1).upper()
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

    # Dự phòng: geocode theo tên thành phố trong ticker
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


TICKER_RE = re.compile(r"highest-temperature-in-(.+?)-on-([a-z]+)-(\d{1,2})-(\d{4})")
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def city_from_ticker(ticker):
    m = TICKER_RE.match(ticker or "")
    return m.group(1) if m else None


def date_from_event(event):
    """Ngày mục tiêu của thị trường (theo giờ địa phương thành phố)."""
    if event.get("eventDate"):
        return event["eventDate"]  # đã kiểm chứng: "2026-07-09"
    m = TICKER_RE.match(event.get("ticker") or event.get("slug") or "")
    if m:
        mon = MONTHS.get(m.group(2))
        if mon:
            return f"{int(m.group(4)):04d}-{mon:02d}-{int(m.group(3)):02d}"
    return None


def load_station_cache():
    if os.path.exists(STATIONS_JSON):
        with open(STATIONS_JSON, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_station_cache(cache):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(STATIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=1)


def append_csv(path, fieldnames, rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(path)
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
