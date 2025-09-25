# interpolate.py
"""
補間処理モジュール
- /interpolate API を叩いて結果を返す
- バックエンド不通ならモックデータを返す
"""

import os
import textwrap
import datetime as dt
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

API_BASE = os.getenv("API_BASE", "http://localhost:8000")
INTERPOLATE_ENDPOINT = f"{API_BASE}/interpolate"

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


def call_interpolate(date_iso: str, hint: str):
    """バックエンド /interpolate 呼び出し。失敗時はモックでフォールバック。"""
    payload = {"date": date_iso, "hint": hint}
    try:
        resp = SESSION.post(INTERPOLATE_ENDPOINT, json=payload, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "source_text": data.get("original", ""),
                "interpolated_text": data.get("interpolated", ""),
                "evidence": data.get("evidence", []),
                "meta": data.get("meta", {}),
                "is_mock": False,
            }
    except Exception as e:
        pass  # ログはUI側で出す想定

    # --- モックフォールバック ---
    mock_src = f"[{date_iso}] の原文は未記入です。ヒント: {hint or '（なし）'}"
    mock_interp = textwrap.dedent(f"""\
    {date_iso} の出来事（自動補間）
    - 朝：曇りがち。通学路は静か。
    - 昼：研究を進め、結果を整理。
    - 夕：運動のあと読書でリフレッシュ。
    ※ ヒント: {hint or '特になし'}
    """).strip()

    mock_evidence = [
        {"type": "weather", "summary": "当日の天候は曇りがち（例）", "source": "open-meteo (mock)"},
        {"type": "context", "summary": "前週の研究ログから活動推定（例）", "source": "local diary (mock)"},
    ]
    return {
        "source_text": mock_src,
        "interpolated_text": mock_interp,
        "evidence": mock_evidence,
        "meta": {"mock": True},
        "is_mock": True,
    }
