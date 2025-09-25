from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping, Sequence
import re
import logging

from config import (
    INTERPOLATION_MAX_NEW_TOKENS,
    INTERPOLATION_MODEL_NAME,
    INTERPOLATION_TEMPERATURE,
    INTERPOLATION_TOP_P,
)

try:
    from transformers import pipeline  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - ランタイム環境による
    pipeline = None

try:  # pragma: no cover - optional dependency
    import torch  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - ランタイム環境による
    torch = None

PROMPTS_DIR = Path(__file__).parent / "prompts"
INTERPOLATE_TEMPLATE_PATH = PROMPTS_DIR / "interpolate.md"
STYLE_GUIDE_PATH = PROMPTS_DIR / "style_guide.md"

BANNED_WORDS = {"超", "マジ", "ヤバい", "ヤベー", "まじで"}
TIME_PREFIX_PATTERN = re.compile(r"^(朝|午前|午前中|昼|午後|夕方|夜|終日)(から|には|にかけて|まで|は|に)?")

_logger = logging.getLogger(__name__)


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


@lru_cache(maxsize=1)
def _get_generation_pipeline(model_name: str):
    if pipeline is None:
        raise ImportError(
            "transformers is not installed. Install the optional dependencies to enable LLM generation."
        )

    device = 0 if (torch is not None and torch.cuda.is_available()) else -1
    model_kwargs = {}
    if torch is not None and torch.cuda.is_available():
        model_kwargs["torch_dtype"] = torch.float16

    text_gen = pipeline(
        task="text-generation",
        model=model_name,
        device=device,
        model_kwargs=model_kwargs,
    )

    tokenizer = text_gen.tokenizer
    pad_token_id = tokenizer.pad_token_id
    if pad_token_id is None and tokenizer.eos_token_id is not None:
        pad_token_id = tokenizer.eos_token_id
    if pad_token_id is None:
        pad_token_id = 0

    return text_gen, pad_token_id


def _call_llm(prompt: str) -> str:
    generator, pad_token_id = _get_generation_pipeline(INTERPOLATION_MODEL_NAME)
    outputs = generator(
        prompt,
        max_new_tokens=INTERPOLATION_MAX_NEW_TOKENS,
        temperature=INTERPOLATION_TEMPERATURE,
        top_p=INTERPOLATION_TOP_P,
        do_sample=True,
        return_full_text=False,
        pad_token_id=pad_token_id,
    )
    if not outputs:
        return ""
    return outputs[0].get("generated_text", "")


def _normalize_point(text: str) -> str:
    cleaned = re.sub(r"^[0-9]+[\.)、\-]\s*", "", text)
    cleaned = re.sub(r"（.*?）", "", cleaned)
    cleaned = cleaned.replace("\u3000", " ").strip()
    cleaned = TIME_PREFIX_PATTERN.sub("", cleaned, count=1)
    cleaned = re.sub(r"^(?:には|に|は|で|を|と|が|へ|も)\s*", "", cleaned)
    cleaned = re.sub(r"^[、。,.\s]+", "", cleaned)
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

    def _ensure_sentence(prefix: str, fragment: str, fallback_phrase: str) -> str:
        normalized = fragment.strip().strip("。．. ")
        if not normalized:
            normalized = fallback_phrase
        return f"{prefix}{normalized}。"

    paragraphs: list[str] = []
    lead = f"今日の出来事は提供された資料をもとに整理しました。{hint_sentence}".strip()
    if not lead.endswith("。"):
        lead += "。"
    paragraphs.append(lead)

    morning = key_points[0] if key_points else "静かに過ごしました"
    afternoon = key_points[1] if len(key_points) > 1 else "落ち着いた時間が流れました"
    body = (
        _ensure_sentence("午前中は", morning, "静かに過ごしました")
        + _ensure_sentence("午後は", afternoon, "落ち着いた時間が流れました")
    )
    paragraphs.append(body)

    if len(key_points) > 2:
        closing_core = key_points[2]
    else:
        closing_core = "一日の終わりに簡単な振り返りを行い、記録を整えました"
    summary = _ensure_sentence("一日の締めくくりとして", closing_core, "記録を整えました")
    paragraphs.append(summary)

    filler_sentence = "全体として落ち着いた雰囲気で、記録の整理と次の準備に時間を充てました。"
    body_text = "".join(paragraphs)
    while len(body_text) < 210 and len(body_text) + len(filler_sentence) <= 280:
        paragraphs[-1] = paragraphs[-1].rstrip("。") + "。" + filler_sentence
        body_text = "".join(paragraphs)

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

    generated_text = ""

    try:
        generated_text = _call_llm(prompt)
    except Exception as exc:  # pragma: no cover - LLM依存のため
        _logger.warning("LLM generation failed (%s). Falling back to rule-based output.", exc)

    if not generated_text.strip():
        generated_text = _fallback_generate(date, context, hint)
    else:
        check = self_check(generated_text, {"date": date})
        if not check.get("passed", False):
            _logger.info("Self-check failed: %s", check)
            fallback = _fallback_generate(date, context, hint)
            if fallback:
                generated_text = fallback

    return generated_text.strip()


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

    lines = [line.rstrip() for line in text.splitlines()]
    if lines:
        header = lines[0].strip()
        if expected_date:
            expected_header = f"{expected_date} の記録"
            header_ok = header == expected_header
            header_detail = "見出し行が規定形式" if header_ok else f"見出しを『{expected_header}』に合わせる"
            checks.append(CheckResult("header_format", header_ok, header_detail))
            if not header_ok:
                issues.append("見出し形式を修正する")

        body_lines = lines[1:]
        blank_line_found = any(not line.strip() for line in body_lines)
        non_empty_count = sum(1 for line in body_lines if line.strip())
        structure_passed = not blank_line_found and non_empty_count == 3
        structure_detail = (
            "本文3段落・空行なし" if structure_passed else "本文の段落数・空行を見直す"
        )
        checks.append(CheckResult("structure", structure_passed, structure_detail))
        if not structure_passed:
            issues.append("本文構成を整える")

        if body_lines:
            body_text = "".join(body_lines)
            body_len = len(body_text)
            len_passed = 200 <= body_len <= 280
            len_detail = "本文文字数が規定範囲" if len_passed else f"本文文字数を200〜280字に調整する (現在{body_len}字)"
            checks.append(CheckResult("length", len_passed, len_detail))
            if not len_passed:
                issues.append("本文文字数を調整する")

            punctuation_ok = not any(ch in body_text for ch in "!?！？")
            punctuation_detail = "禁則記号なし" if punctuation_ok else "感嘆符・疑問符などを削除"
            checks.append(CheckResult("punctuation", punctuation_ok, punctuation_detail))
            if not punctuation_ok:
                issues.append("禁則記号を削除する")

    passed = not issues
    result = {
        "passed": passed,
        "checks": [check.__dict__ for check in checks],
    }

    if not passed:
        result["retry_prompt"] = _build_retry_prompt(issues, facts)

    return result


__all__ = ["build_context", "generate_interpolation", "self_check"]
