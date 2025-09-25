import streamlit as st
import datetime as dt
import json
import sqlite3
from ingest import geocode_place, enrich_and_store, query_diaries, ensure_db

st.set_page_config(page_title="日記の補間（デモ）", page_icon="📒", layout="centered")
st.title("📒 日記の補間（デモ）")

# DB 初期化
ensure_db()

tab_fetch, tab_view = st.tabs(["🛠 データ取得", "📗 日記を見る"])

# -------------------------------
# 🛠 データ取得タブ
# -------------------------------
with tab_fetch:
    st.subheader("日付と場所を入力して事実データを取得")

    with st.form("fetch_form", clear_on_submit=False):
        date = st.date_input("日付", value=dt.date.today())
        place = st.text_input("場所（市区町村やランドマーク）", value="富山市")
        lat = st.text_input("緯度（空欄なら地名を使う）", value="")
        lon = st.text_input("経度（空欄なら地名を使う）", value="")
        submitted = st.form_submit_button("取得して保存する")

    if submitted:
        date_str = date.isoformat()

        # 座標または地名を解決
        lat_f = lon_f = None
        if lat.strip() and lon.strip():
            try:
                lat_f = float(lat); lon_f = float(lon)
            except ValueError:
                st.error("緯度・経度は数値で入力してください。")
                st.stop()
        else:
            geo = geocode_place(place)
            if not geo:
                st.error("地名を緯度経度に解決できませんでした。")
                st.stop()
            lat_f, lon_f, resolved = geo
            st.info(f"解決: {resolved} → lat={lat_f}, lon={lon_f}")

        with st.spinner("APIから取得中…"):
            rec = enrich_and_store(date_str, lat_f, lon_f)

        st.success("取得・保存しました（./data/diary_enriched.sqlite）")
        st.code(json.dumps(rec, ensure_ascii=False, indent=2), language="json")

# -------------------------------
# 📗 日記閲覧タブ
# -------------------------------
with tab_view:
    st.subheader("既存の日記を閲覧")

    col1, col2 = st.columns(2)
    with col1:
        df = st.date_input("開始日", value=None)
    with col2:
        dt_ = st.date_input("終了日", value=None)
    kw = st.text_input("キーワード検索", placeholder="例: 雨, 研究, ランニング")

    date_from = df.isoformat() if df else None
    date_to   = dt_.isoformat() if dt_ else None
    rows = query_diaries(date_from, date_to, kw)

    if not rows:
        st.info("条件に合う日記がありません。")
    else:
        for r in rows:
            with st.expander(f"{r['date']} — {r['title'] or '(無題)'} [{r['location'] or '-'}]"):
                st.markdown(f"**タグ**: {r['tags'] or '-'}")
                st.markdown("---")
                st.markdown(r["body"])
                st.caption(f"ID: {r['id']} / 作成: {r['created_at']}")
