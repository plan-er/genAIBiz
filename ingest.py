#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py — 「日記の補間」PoC用: 無料APIで日付・場所から天気/日の出入を取得し、正規化して保存
  - Geocoding: Open-Meteo Geocoding API (no key)
  - Historical Weather: Open-Meteo Weather API (no key)
  - Sunrise/Sunset: sunrise-sunset.org (no key)
保存先:
  - ./data/diary_enriched.sqlite (SQLite)
実行例:
  python ingest.py --date 2025-03-21 --place 富山市
  python ingest.py --date 2025-03-21 --lat 36.695 --lon 137.213
"""

import argparse
import datetime as dt
import json
import sqlite3
import time
from typing import Dict, Optional, Tuple

import requests

DB_PATH = "./data/diary_enriched.sqlite"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "DiaryInterpolationPoC/0.1 (+github.com/yourorg)"})

# -----------------------------
# Utilities
# -----------------------------
def retry_get(url: str, params: Dict, tries=3, backoff=(0.5, 1, 2)) -> Optional[requests.Response]:
    for i in range(tries):
        try:
            r = SESSION.get(url, params=params, timeout=15)
            if r.status_code == 200:
                return r
        except requests.RequestException:
            pass
        time.sleep(backoff[min(i, len(backoff)-1)])
    return None

def ensure_db():
    import os
    os.makedirs("./data", exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS weather_daily (
        date TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        tmax_c REAL,
        tmin_c REAL,
        precip_mm REAL,
        weather_code INTEGER,
        weather_text TEXT,
        source TEXT,
        PRIMARY KEY(date, lat, lon)
    );
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS sun_info (
        date TEXT NOT NULL,
        lat REAL NOT NULL,
        lon REAL NOT NULL,
        sunrise_utc TEXT,
        sunset_utc TEXT,
        source TEXT,
        PRIMARY KEY(date, lat, lon)
    );
    """)
    con.commit()
    con.close()

def insert_or_replace(table: str, row: Dict):
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cols = ",".join(row.keys())
    placeholders = ",".join(["?"] * len(row))
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders});"
    cur.execute(sql, list(row.values()))
    con.commit()
    con.close()

# -----------------------------
# Geocoding (place -> lat/lon)
# -----------------------------
def geocode_place(place: str) -> Optional[Tuple[float, float, str]]:
    """
    Returns (lat, lon, resolved_name)
    Open-Meteo Geocoding: https://geocoding-api.open-meteo.com/v1/search
    """
    r = retry_get(
        "https://geocoding-api.open-meteo.com/v1/search",
        {"name": place, "count": 1, "language": "ja", "format": "json"}
    )
    if not r:
        return None
    data = r.json()
    if not data.get("results"):
        return None
    res = data["results"][0]
    lat = float(res["latitude"])
    lon = float(res["longitude"])
    name = res.get("name") or place
    admin1 = res.get("admin1") or ""
    country = res.get("country") or ""
    resolved = " ".join([x for x in [name, admin1, country] if x])
    return lat, lon, resolved

# -----------------------------
# Historical Weather (daily)
# -----------------------------
WEATHER_CODE_MAP = {
    0: "快晴",
    1: "晴れ",
    2: "薄曇り",
    3: "曇り",
    45: "霧",
    48: "霧氷",
    51: "霧雨（弱）",
    53: "霧雨（中）",
    55: "霧雨（強）",
    61: "雨（弱）",
    63: "雨（中）",
    65: "雨（強）",
    71: "雪（弱）",
    73: "雪（中）",
    75: "雪（強）",
    95: "雷雨（弱）",
    96: "雷雨（雹あり弱）",
    99: "雷雨（雹あり強）",
}

def fetch_daily_weather(date_str: str, lat: float, lon: float) -> Optional[Dict]:
    """
    Open-Meteo Historical daily: https://api.open-meteo.com/v1/forecast
    For past days: use start_date=end_date with 'daily' params (Open-Meteo provides reanalysis/historical).
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "start_date": date_str,
        "end_date": date_str,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weathercode",
        "timezone": "UTC",
    }
    r = retry_get("https://api.open-meteo.com/v1/forecast", params)
    if not r:
        return None
    js = r.json()
    daily = js.get("daily")
    if not daily:
        return None
    try:
        tmax = daily["temperature_2m_max"][0]
        tmin = daily["temperature_2m_min"][0]
        precip = daily["precipitation_sum"][0]
        code = int(daily["weathercode"][0])
        text = WEATHER_CODE_MAP.get(code, f"天気コード{code}")
        return {
            "tmax_c": tmax,
            "tmin_c": tmin,
            "precip_mm": precip,
            "weather_code": code,
            "weather_text": text,
            "source": "open-meteo",
        }
    except Exception:
        return None

# -----------------------------
# Sunrise / Sunset
# -----------------------------
def fetch_sunrise_sunset(date_str: str, lat: float, lon: float) -> Optional[Dict]:
    """
    Sunrise-Sunset.org: https://sunrise-sunset.org/api
    Returns times in UTC.
    """
    r = retry_get(
        "https://api.sunrise-sunset.org/json",
        {"lat": lat, "lng": lon, "date": date_str, "formatted": 0}
    )
    if not r:
        return None
    js = r.json()
    if js.get("status") != "OK":
        return None
    res = js.get("results", {})
    return {
        "sunrise_utc": res.get("sunrise"),
        "sunset_utc": res.get("sunset"),
        "source": "sunrise-sunset.org"
    }

# -----------------------------
# Normalization & Persist
# -----------------------------
def enrich_and_store(date_str: str, lat: float, lon: float) -> Dict:
    ensure_db()

    weather = fetch_daily_weather(date_str, lat, lon)
    if weather:
        insert_or_replace("weather_daily", {
            "date": date_str,
            "lat": lat,
            "lon": lon,
            "tmax_c": weather["tmax_c"],
            "tmin_c": weather["tmin_c"],
            "precip_mm": weather["precip_mm"],
            "weather_code": weather["weather_code"],
            "weather_text": weather["weather_text"],
            "source": weather["source"],
        })

    sun = fetch_sunrise_sunset(date_str, lat, lon)
    if sun:
        insert_or_replace("sun_info", {
            "date": date_str,
            "lat": lat,
            "lon": lon,
            "sunrise_utc": sun["sunrise_utc"],
            "sunset_utc": sun["sunset_utc"],
            "source": sun["source"],
        })

    # 統合レコード（LLMに渡す想定の正規化スキーマ）
    record = {
        "date": date_str,
        "location": {"lat": lat, "lon": lon},
        "weather": weather,   # None になりうる
        "sun": sun            # None になりうる
    }
    return record

# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Diary interpolation: free-API ingestion")
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--place", help="地名（例: 富山市）")
    p.add_argument("--lat", type=float, help="緯度")
    p.add_argument("--lon", type=float, help="経度")
    return p.parse_args()

def main():
    args = parse_args()

    # date validation
    try:
        _ = dt.date.fromisoformat(args.date)
    except ValueError:
        raise SystemExit("ERROR: --date は YYYY-MM-DD 形式で指定してください。")

    # resolve location
    if args.place:
        geo = geocode_place(args.place)
        if not geo:
            raise SystemExit("ERROR: 地名を緯度経度に解決できませんでした。別の表記を試してください。")
        lat, lon, resolved = geo
        print(f"[INFO] Resolved place: {resolved} -> lat={lat}, lon={lon}")
    else:
        if args.lat is None or args.lon is None:
            raise SystemExit("ERROR: --place か --lat/--lon のいずれかを指定してください。")
        lat, lon = args.lat, args.lon
        print(f"[INFO] Using coordinates: lat={lat}, lon={lon}")

    record = enrich_and_store(args.date, lat, lon)
    print(json.dumps(record, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
