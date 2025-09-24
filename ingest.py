#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest.py — 「日記の補間」PoC: 無料APIで日付・場所から天気/日の出入を取得し保存
  - Geocoding: Open-Meteo Geocoding API (no key)
  - Historical Weather: Open-Meteo Weather API (no key)
  - Sunrise/Sunset: sunrise-sunset.org (no key)
保存先:
  - ./data/diary_enriched.sqlite (SQLite)

実行方法:
  # 1) CLIモード（従来どおり）
  python ingest.py --cli --date 2025-03-21 --place 富山市
  python ingest.py --cli --date 2025-03-21 --lat 36.695 --lon 137.213

  # 2) UIモード（Streamlit）
  streamlit run ingest.py
"""
import argparse
import datetime as dt
import json
import sqlite3
import time
from typing import Dict, Optional, Tuple
import requests
import os

DB_PATH = "./data/diary_enriched.sqlite"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "DiaryInterpolationPoC/0.1 (+example.org)"})


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
    0: "快晴", 1: "晴れ", 2: "薄曇り", 3: "曇り",
    45: "霧", 48: "霧氷", 51: "霧雨（弱）", 53: "霧雨（中）", 55: "霧雨（強）",
    61: "雨（弱）", 63: "雨（中）", 65: "雨（強）",
    71: "雪（弱）", 73: "雪（中）", 75: "雪（強）",
    95: "雷雨（弱）", 96: "雷雨（雹あり弱）", 99: "雷雨（雹あり強）",
}

def fetch_daily_weather(date_str: str, lat: float, lon: float) -> Optional[Dict]:
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
# Normalize & Persist
# -----------------------------
def enrich_and_store(date_str: str, lat: float, lon: float) -> Dict:
    ensure_db()

    weather = fetch_daily_weather(date_str, lat, lon)
    if weather:
        insert_or_replace("weather_daily", {
            "date": date_str, "lat": lat, "lon": lon,
            "tmax_c": weather["tmax_c"], "tmin_c": weather["tmin_c"],
            "precip_mm": weather["precip_mm"],
            "weather_code": weather["weather_code"],
            "weather_text": weather["weather_text"],
            "source": weather["source"],
        })

    sun = fetch_sunrise_sunset(date_str, lat, lon)
    if sun:
        insert_or_replace("sun_info", {
            "date": date_str, "lat": lat, "lon": lon,
            "sunrise_utc": sun["sunrise_utc"],
            "sunset_utc": sun["sunset_utc"],
            "source": sun["source"],
        })

    return {
        "date": date_str,
        "location": {"lat": lat, "lon": lon},
        "weather": weather,
        "sun": sun
    }


# -----------------------------
# CLI
# -----------------------------
def parse_args():
    p = argparse.ArgumentParser(description="Diary interpolation: free-API ingestion")
    p.add_argument("--cli", action="store_true", help="CLIモードで実行（UIは無効）")
    p.add_argument("--date", help="YYYY-MM-DD")
    p.add_argument("--place", help="地名（例: 富山市）")
    p.add_argument("--lat", type=float, help="緯度")
    p.add_argument("--lon", type=float, help="経度")
    return p.parse_args()

def run_cli(args):
    # date validation
    if not args.date:
        raise SystemExit("ERROR: --date を指定してください。")
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


# -----------------------------
# UI (Streamlit)
# -----------------------------
def render_ui():
    import streamlit as st

    st.set_page_config(page_title="日記の補間 - データ取得", page_icon="📒", layout="centered")
    st.title("📒 日記の補間｜データ取得（PoC）")

    with st.form("fetch_form", clear_on_submit=False):
        d = st.date_input("日付", value=dt.date.today())
        place = st.text_input("場所（市区町村名／ランドマーク名）", value="富山市")
        lat = st.text_input("緯度（未入力なら地名を使用）", value="")
        lon = st.text_input("経度（未入力なら地名を使用）", value="")
        submitted = st.form_submit_button("取得して保存する")

    if submitted:
        # validate date
        date_str = d.isoformat()

        # resolve location
        lat_f = None
        lon_f = None
        if lat.strip() and lon.strip():
            try:
                lat_f = float(lat); lon_f = float(lon)
            except ValueError:
                st.error("緯度・経度は数値で入力してください。"); return
        else:
            geo = geocode_place(place)
            if not geo:
                st.error("地名を緯度経度に解決できませんでした。別の表記を試してください。")
                return
            lat_f, lon_f, resolved = geo
            st.info(f"解決: {resolved} → lat={lat_f}, lon={lon_f}")

        with st.spinner("取得中…"):
            rec = enrich_and_store(date_str, lat_f, lon_f)

        st.success("取得・保存しました（./data/diary_enriched.sqlite）")
        st.code(json.dumps(rec, ensure_ascii=False, indent=2), language="json")

        # 参考: 直近のDB内容をざっくり確認
        if st.checkbox("DBの中身を少し見る（weather_daily 先頭10件）"):
            import pandas as pd, sqlite3
            con = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query("SELECT * FROM weather_daily ORDER BY date DESC LIMIT 10;", con)
            st.dataframe(df)
            con.close()


if __name__ == "__main__":
    args = parse_args()
    if args.cli:
        run_cli(args)
    else:
        # Streamlit実行時はここが呼ばれ、UIを表示
        render_ui()
