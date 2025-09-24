import streamlit as st
import requests

st.title("📒 日記の補間（デモ）")
place = st.text_input("場所", "富山市")
date  = st.date_input("日付").isoformat()

if st.button("取得"):
    st.write(f"場所: {place}, 日付: {date}")
    # ここで ingest 関数やAPI呼び出しを行う
    st.success("ダミー：ここに取得データや補間結果を表示")
