# webui.py
# Streamlit UI: 「日付を選ぶ→補間→根拠と差分を見て承認→保存」を1画面で完結
# - /interpolate を呼び出して原文/補間稿/根拠を表示
# - 左: 原文 / 右: 補間稿（差分表示あり）
# - 「承認して保存」ボタンで /diary/{date} (PUT) → フォールバックで /ingest (POST)
# - 通信失敗時は自動リトライ & トースト表示。最終的にモックでローカル動作を保証

import os
import json
import textwrap
import datetime as dt
import difflib
from html import escape

import streamlit as st
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from orchestrator import orchestrator_instance
from schemas import InterpolationRequest

# =========================
# 設定
# =========================
API_BASE = os.getenv("API_BASE", "http://localhost:8000")

INTERPOLATE_ENDPOINT = f"{API_BASE}/interpolate"
DIARY_PUT_ENDPOINT    = f"{API_BASE}/diary/{{date_iso}}"  # PUT
INGEST_ENDPOINT       = f"{API_BASE}/ingest"               # POST (fallback)

PAGE_TITLE = "日記補間：承認フロー"

# =========================
# HTTP クライアント（リトライ設定）
# =========================
def make_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.6,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "POST", "PUT", "PATCH"])
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s

SESSION = make_session()

# =========================
# ユーティリティ
# =========================
def to_iso(d: dt.date) -> str:
    return d.isoformat()

def html_diff(a: str, b: str) -> str:
    """原文(a)と補間稿(b)の差分をサイドバイサイドで返す（HTML）"""
    diff = difflib.HtmlDiff(wrapcolumn=80)
    # HtmlDiffは内部でエスケープ処理されるが、意図しないタグを避けるため pre-escape
    a = escape(a or "")
    b = escape(b or "")
    html = diff.make_table(a.splitlines(), b.splitlines(),
                           fromdesc="原文", todesc="補間稿",
                           context=True, numlines=2)
    # 余白調整の軽いスタイル
    style = """
    <style>
      table.diff { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
      .diff_header { background: #f3f4f6; }
      .diff_next { background: #fff; }
      .diff_add { background: #ecfdf5; }
      .diff_chg { background: #fff7ed; }
      .diff_sub { background: #fee2e2; }
      td, th { padding: 4px 8px; }
    </style>
    """
    return style + html

def toast(kind: str, msg: str):
    if kind == "ok":
        st.toast(msg, icon="✅")
    elif kind == "warn":
        st.toast(msg, icon="⚠️")
    else:
        st.toast(msg)

def approve_and_save(date_iso: str, text: str, evidence):
    """承認して保存: /diary/{date} -> 失敗したら /ingest"""
    body = {
        "text": text,
        "evidence": evidence,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }

    # 1) PUT /diary/{date}
    try:
        url = DIARY_PUT_ENDPOINT.format(date_iso=date_iso)
        r = SESSION.put(url, json=body, timeout=10)
        if r.status_code in (200, 201):
            toast("ok", "保存しました（/diary）。")
            return True, {"endpoint": url, "status": r.status_code}
        else:
            toast("warn", f"/diary 保存失敗: {r.status_code} {r.text[:120]}")
    except Exception as e:
        toast("warn", f"/diary 通信エラー: {e}")

    # 2) Fallback: POST /ingest
    try:
        r2 = SESSION.post(INGEST_ENDPOINT, json={"date": date_iso, **body}, timeout=10)
        if r2.status_code in (200, 201):
            toast("ok", "保存しました（/ingest）。")
            return True, {"endpoint": INGEST_ENDPOINT, "status": r2.status_code}
        else:
            toast("warn", f"/ingest 保存失敗: {r2.status_code} {r2.text[:120]}")
            return False, {"endpoint": INGEST_ENDPOINT, "status": r2.status_code}
    except Exception as e:
        toast("warn", f"/ingest 通信エラー: {e}")
        return False, {"endpoint": INGEST_ENDPOINT, "error": str(e)}

# =========================
# UI
# =========================
st.set_page_config(page_title=PAGE_TITLE, page_icon="🗓️", layout="wide")
st.title("🗓️ 日記補間：承認フロー")
st.caption("“日付を選ぶ→補間→根拠と差分を見て承認→保存”を1画面で完結")

with st.sidebar:
    st.markdown("### 設定")
    st.text_input("API_BASE", API_BASE, key="api_base_help", help="環境変数 API_BASE で上書き可能。")
    st.caption("通信は自動リトライ。失敗時はモックで動作。")

# 入力欄
col0, col1 = st.columns([1, 2])
with col0:
    date_val = st.date_input("対象日付", value=dt.date.today())
with col1:
    hint_val = st.text_area("ヒント（任意）", placeholder="例：場所・出来事・気分などのメモ")

# 補間アクション
_do_interpolate = st.button("🔮 補間する", use_container_width=True)

if _do_interpolate:
    date_iso = to_iso(date_val)
    with st.spinner("補間中..."):
        try:
            # orchestrator_instanceを使用して補間を実行
            request = InterpolationRequest(date=date_iso, hint=hint_val)
            response = orchestrator_instance.interpolate(request)
            
            # レスポンス形式をWebUIが期待する形式に変換
            result = {
                "source_text": "",  # orchestratorからは元の日記テキストは返らないため空
                "interpolated_text": response.text,
                "evidence": [{"type": "citation", "summary": f"参照: {c.date}", "source": c.snippet} for c in response.citations],
                "meta": {"date": response.date},
                "is_mock": False,
            }
        except Exception as e:
            # エラー時はモックデータを返す
            st.error(f"補間処理でエラーが発生しました: {e}")
            result = {
                "source_text": f"[{date_iso}] の原文は未記入です。ヒント: {hint_val or '（なし）'}",
                "interpolated_text": f"""{date_iso} の出来事（自動補間）
- 朝：曇りがち。通学路は静か。
- 昼：研究を進め、結果を整理。
- 夕：運動のあと読書でリフレッシュ。
※ ヒント: {hint_val or '特になし'}""",
                "evidence": [
                    {"type": "weather", "summary": "当日の天候は曇りがち（例）", "source": "open-meteo (mock)"},
                    {"type": "context", "summary": "前週の研究ログから活動推定（例）", "source": "local diary (mock)"},
                ],
                "meta": {"mock": True, "error": str(e)},
                "is_mock": True,
            }
        
        st.session_state["last_result"] = result
        st.session_state["last_date_iso"] = date_iso

# 結果表示
result = st.session_state.get("last_result")
date_iso = st.session_state.get("last_date_iso")

if result:
    st.divider()
    st.subheader(f"📄 {date_iso} の補間結果")

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**原文（左）**")
        st.text_area("原文", value=result["source_text"], height=260, key="source_text", disabled=True)

    with right:
        st.markdown("**補間稿（右）**")
        st.text_area("補間稿", value=result["interpolated_text"], height=260, key="interp_text", disabled=True)

    with st.expander("🪄 差分（原文 vs 補間稿）を表示"):
        st.components.v1.html(html_diff(result["source_text"], result["interpolated_text"]), height=320, scrolling=True)

    with st.expander("🔎 根拠（evidence）を確認"):
        ev = result.get("evidence") or []
        if isinstance(ev, list):
            for i, e in enumerate(ev, start=1):
                e_json = json.dumps(e, ensure_ascii=False, indent=2)
                st.markdown(f"**[{i}] {e.get('type', 'info')}** — {e.get('summary','')}")
                with st.popover(f"詳細を見る #{i}"):
                    st.code(e_json, language="json")
        else:
            st.code(json.dumps(ev, ensure_ascii=False, indent=2), language="json")

    # 承認・保存
    st.divider()
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        st.markdown("**この内容で保存しますか？**")
    approve_btn = c2.button("✅ 承認して保存", use_container_width=True, type="primary")
    cancel_btn  = c3.button("🗑️ 取り消し", use_container_width=True)

    if approve_btn:
        with st.spinner("保存中..."):
            ok, info = approve_and_save(date_iso, result["interpolated_text"], result.get("evidence", []))
            if ok:
                st.success("保存に成功しました。", icon="✅")
            else:
                st.error("保存に失敗しました。ログを確認してください。", icon="❌")
            st.json(info)

    if cancel_btn:
        st.session_state.pop("last_result", None)
        st.session_state.pop("last_date_iso", None)
        st.info("結果をクリアしました。", icon="🧹")

else:
    st.info("日付を選択し、ヒントを入力して「補間する」を押してください。", icon="🧭")
