from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
import datetime as dt
import re
import textwrap

PROMPTS_DIR = Path(__file__).parent / "prompts"
INTERPOLATE_TEMPLATE_PATH = PROMPTS_DIR / "interpolate.md"
STYLE_GUIDE_PATH = PROMPTS_DIR / "style_guide.md"

BANNED_WORDS = {"超", "マジ", "ヤバい", "ヤベー", "まじで"}
TIME_PREFIX_PATTERN = re.compile(r"^(朝|午前|午前中|昼|午後|夕方|夜|終日)(から|には|には|にかけて|まで|は)?")


def _load_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required prompt file is missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def build_context(passages: Sequence[Any]) -> str:
    """整形済みの文脈文字列を生成する。

    Args:
        passages: string または dict を想定。dict の場合、"text"・"source"・"score"・"date"
                  などがあれば補助情報として括弧内に付記する。

    Returns:
        改行区切りの文脈文字列。
    """
    if not passages:
        return "情報ソースが見つかりませんでした。"

    lines: list[str] = []
    for idx, passage in enumerate(passages, start=1):
        if isinstance(passage, Mapping):
            text = _safe_str(passage.get("text") or passage.get("body") or passage)
            meta_parts = []
            for key in ("date", "source", "metadata", "score"):
                val = passage.get(key)
                if val is None:
                    continue
                meta_parts.append(_safe_str(val))
            meta = " / ".join(filter(None, meta_parts))
        elif isinstance(passage, str):
            text = passage.strip()
            meta = ""
        else:
            text = _safe_str(passage)
            meta = ""

        if not text:
            continue

        numbered = f"{idx:02d}. {text}"
        if meta:
            numbered = f"{numbered}（{meta}）"
        lines.append(numbered)

    if not lines:
        return "情報ソースが見つかりませんでした。"

    return "\n".join(lines)


def _normalize_point(text: str) -> str:
    cleaned = re.sub(r"^[0-9]+[\.)、\-]\s*", "", text)
    cleaned = re.sub(r"（.*?）", "", cleaned)
    cleaned = cleaned.replace("\u3000", " ").strip()
    cleaned = TIME_PREFIX_PATTERN.sub("", cleaned, count=1)
    return cleaned.strip("。．.、,")


def _fallback_generate(date: str, context: str, hint: str | None) -> str:
    """LLM が利用できない場合の deterministic な補間文生成。"""
    date_header = f"{date} の記録"
    context_lines = [line.strip("・ ") for line in context.splitlines() if line.strip()]

    # 主要な出来事候補を最大 3 つまで抽出
    key_points = []
    for line in context_lines:
        normalized = _normalize_point(line)
        if normalized:
            key_points.append(normalized)
        if len(key_points) >= 3:
            break

    if not key_points:
        key_points = ["文脈情報が不足していますが、穏やかな一日だったと記録します"]

    hint_sentence = _safe_str(hint) or "特記事項は記録されていません。"

    paragraphs: list[str] = []
    lead = f"今日の出来事は提供された資料をもとに整理しました。{hint_sentence}".strip()
    if not lead.endswith("。"):
        lead += "。"
    paragraphs.append(lead)

    morning = key_points[0] if key_points else "静かに過ごしました"
    afternoon = key_points[1] if len(key_points) > 1 else "落ち着いた時間が流れました"
    body = f"午前中は{morning}。午後は{afternoon}。"
    paragraphs.append(body)

    if len(key_points) > 2:
        closing_core = key_points[2]
    else:
        closing_core = "一日の終わりに簡単な振り返りを行い、記録を整えました"
    summary = f"一日の締めくくりとして{closing_core}。"
    paragraphs.append(summary)

    return "\n".join([date_header] + paragraphs)


def generate_interpolation(date: str, context: str, hint: str | None) -> str:
    """補間用プロンプトを組み立て、テキストを生成する。"""
    style_guide = _load_text(STYLE_GUIDE_PATH)
    template = _load_text(INTERPOLATE_TEMPLATE_PATH)

    # テンプレートをレンダリング（LLM 呼び出しに渡すプロンプト）
    prompt = template.format(
        date=date,
        context=context.strip() or "文脈情報は提供されませんでした。",
        hint=(hint or "特筆すべきヒントはありません。"),
        style_guide=style_guide,
    )

    # 現段階では deterministic なフォールバックで返す
    generated = _fallback_generate(date, context, hint)
    return generated.strip()


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


def _build_retry_prompt(issues: Sequence[str], facts: Mapping[str, Any]) -> str:
    focus = facts.get("date") or "日付未指定"
    joined = "、".join(issues)
    return f"次の点を修正して再生成: {joined}。対象日: {focus}"


def self_check(text: str, facts: Mapping[str, Any]) -> dict[str, Any]:
    """生成物の簡易検査を行う。

    Returns:
        {
            "passed": bool,
            "checks": list[dict],
            "retry_prompt": str | None,
        }
    """
    checks: list[CheckResult] = []
    issues: list[str] = []

    expected_date_raw = facts.get("date")
    expected_date = _safe_str(expected_date_raw)
    if expected_date:
        expected_date_norm = expected_date.replace("-", "")
        text_norm = text.replace("-", "")
        date_matched = expected_date in text or expected_date_norm in text_norm
        detail = "本文に日付が含まれている" if date_matched else "本文に指定日付が含まれていない"
        checks.append(CheckResult("date_presence", date_matched, detail))
        if not date_matched:
            issues.append("本文に日付を含める")
    else:
        checks.append(CheckResult("date_presence", True, "期待する日付が指定されていないためスキップ"))

    banned_hits = [word for word in BANNED_WORDS if word and word in text]
    banned_passed = not banned_hits
    detail = "禁則語なし" if banned_passed else f"禁則語 {', '.join(banned_hits)} を削除"
    checks.append(CheckResult("banned_words", banned_passed, detail))
    if not banned_passed:
        issues.append("禁則語を除去する")

    passed = not issues
    result = {
        "passed": passed,
        "checks": [check.__dict__ for check in checks],
    }

    if not passed:
        result["retry_prompt"] = _build_retry_prompt(issues, facts)

    return result


__all__ = ["build_context", "generate_interpolation", "self_check"]
