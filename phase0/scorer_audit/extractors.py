from __future__ import annotations

import ast
import json
import re
from collections.abc import Callable

from .types import AnswerValue, ExtractionResult


SCALES = ("", "thousand", "million", "billion", "percent")
_ANSWER_MARKER = re.compile(
    r"(?:final\s+answer|the\s+answer|answer)\s*(?:is|:|=)\s*", re.I
)
_SCALE_WORD = re.compile(r"\b(thousand|million|billion|percent)\b", re.I)
_NUMERIC_SURFACE = r"\$?\(?[+-]?\d[\d,]*(?:\.\d+)?%?\)?(?=$|\s|[.,;:])"
_NUMERIC_CUES = (
    re.compile(rf"\bequals?\s+(?:approximately\s+)?(?P<number>{_NUMERIC_SURFACE})", re.I),
    re.compile(rf"\b(?:decreased|increased)\s+by\s+(?:approximately\s+)?(?P<number>{_NUMERIC_SURFACE})", re.I),
    re.compile(rf"\b(?:is|was|were)\s+(?:approximately\s+)?(?P<number>{_NUMERIC_SURFACE})", re.I),
    re.compile(rf"\bthere\s+(?:are|were)\s+(?:approximately\s+)?(?P<number>{_NUMERIC_SURFACE})", re.I),
    re.compile(rf"\b(?:increase|decrease)\s+of\s+(?:approximately\s+)?(?P<number>{_NUMERIC_SURFACE})", re.I),
    re.compile(rf"^\s*(?P<number>{_NUMERIC_SURFACE})", re.I),
)
_NUMBER_WORDS = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}
_NUMBER_WORD_PATTERN = "|".join(_NUMBER_WORDS)
_COUNT_WORD_CUES = (
    re.compile(rf"^\s*(?:only\s+)?(?P<number>{_NUMBER_WORD_PATTERN})\b", re.I),
    re.compile(rf"\bthere\s+(?:are|were)\s+(?P<number>{_NUMBER_WORD_PATTERN})\b", re.I),
    re.compile(rf"\buses?\s+(?P<number>{_NUMBER_WORD_PATTERN})\b", re.I),
    re.compile(rf"\bin\s+(?:all\s+)?(?P<number>{_NUMBER_WORD_PATTERN})\s+years?\b", re.I),
    re.compile(rf"\ball\s+(?P<number>{_NUMBER_WORD_PATTERN})\s+years?\b", re.I),
)


def _json_object(text: str) -> dict:
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    obj, _ = json.JSONDecoder().raw_decode(text[start:])
    if not isinstance(obj, dict):
        raise ValueError("JSON response is not an object")
    return obj


def extract_schema(text: str) -> ExtractionResult:
    """Extract the strict JSON condition. The schema always returns a list."""
    if not text or text.startswith("__ERROR__"):
        return ExtractionResult(AnswerValue.from_parts(None), "error", text or "empty response")
    try:
        obj = _json_object(text)
        answer = obj["answer"]
        scale = str(obj.get("scale", "") or "").lower()
        if not isinstance(answer, list) or not answer:
            raise ValueError("answer must be a non-empty list")
        if scale not in SCALES:
            raise ValueError(f"invalid scale: {scale!r}")
        return ExtractionResult(AnswerValue.from_parts(answer, scale))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        return ExtractionResult(AnswerValue.from_parts(None), "error", str(exc))


def _candidate(text: str) -> str:
    matches = list(_ANSWER_MARKER.finditer(text.strip()))
    candidate = text.strip()[matches[-1].end():] if matches else text.strip()
    return candidate.strip().strip("` \n\t")


def _maybe_list(candidate: str) -> list[str] | str:
    compact = candidate.strip().rstrip(".").strip()
    if compact.startswith("[") and compact.endswith("]"):
        try:
            value = ast.literal_eval(compact)
            if isinstance(value, (list, tuple)) and value:
                return [str(v) for v in value]
        except (SyntaxError, ValueError):
            pass
    return compact


def _focus_numeric_answer(candidate: str) -> str:
    """Select a cue-linked final number without blindly taking the last number."""
    for pattern in _NUMERIC_CUES:
        matches = list(pattern.finditer(candidate))
        if not matches:
            continue
        match = matches[-1]
        number = match.group("number")
        suffix = candidate[match.end():]
        scale = re.match(r"\s*(thousand|million|billion|percent)\b", suffix, re.I)
        return f"{number} {scale.group(1)}" if scale else number
    return candidate


def extract_free_regex(text: str) -> ExtractionResult:
    """Typed regex extraction from free prose.

    Word scales are moved to the structured scale field. Percent signs and
    accounting parentheses remain in the answer surface so later scorer
    policies, rather than the extractor, decide their semantics.
    """
    if not text or text.startswith("__ERROR__"):
        return ExtractionResult(AnswerValue.from_parts(None), "error", text or "empty response")
    candidate = _focus_numeric_answer(_candidate(text))
    scale_match = _SCALE_WORD.search(candidate)
    scale = scale_match.group(1).lower() if scale_match else ""
    if "%" in candidate:
        scale = "percent"
    if scale_match and scale != "percent":
        candidate = _SCALE_WORD.sub("", candidate)
        candidate = re.sub(r"\s+", " ", candidate).strip()
    answer = _maybe_list(candidate)
    return ExtractionResult(AnswerValue.from_parts(answer, scale))


def extract_free_surface(text: str) -> ExtractionResult:
    """Preserve the final-answer surface and leave scale untyped."""
    if not text or text.startswith("__ERROR__"):
        return ExtractionResult(AnswerValue.from_parts(None), "error", text or "empty response")
    return ExtractionResult(AnswerValue.from_parts(_maybe_list(_candidate(text)), ""))


def extract_free_typed(text: str) -> ExtractionResult:
    """Regex extraction plus a declared count-word-to-integer permission."""
    base = extract_free_regex(text)
    if base.status != "ok":
        return base
    candidate = _candidate(text)
    for pattern in _COUNT_WORD_CUES:
        matches = list(pattern.finditer(candidate))
        if matches:
            word = matches[-1].group("number").lower()
            return ExtractionResult(AnswerValue.from_parts(str(_NUMBER_WORDS[word]), ""))
    return base


def extract_labeled(text: str) -> ExtractionResult:
    """Parse two labeled lines without adding any semantic conversion."""
    if not text or text.startswith("__ERROR__"):
        return ExtractionResult(AnswerValue.from_parts(None), "error", text or "empty response")
    answer_match = re.search(
        r"^\s*ANSWER\s*:\s*(.+?)(?=\n\s*SCALE\s*:|\Z)", text, re.I | re.S
    )
    scale_match = re.search(r"^\s*SCALE\s*:\s*([^\n]+)", text, re.I | re.M)
    if not answer_match:
        return ExtractionResult(AnswerValue.from_parts(None), "error", "missing ANSWER label")
    answer = _maybe_list(answer_match.group(1).strip())
    scale = scale_match.group(1).strip().lower() if scale_match else ""
    if scale in {"none", "null", "n/a"}:
        scale = ""
    if scale not in SCALES:
        return ExtractionResult(AnswerValue.from_parts(answer), "error", f"invalid scale: {scale!r}")
    return ExtractionResult(AnswerValue.from_parts(answer, scale))


EXTRACTORS: dict[str, Callable[[str], ExtractionResult]] = {
    "schema": extract_schema,
    "labeled": extract_labeled,
    "free_regex": extract_free_regex,
    "free_surface": extract_free_surface,
    "free_typed": extract_free_typed,
}


def get_extractor(name: str) -> Callable[[str], ExtractionResult]:
    try:
        return EXTRACTORS[name]
    except KeyError as exc:
        raise ValueError(f"unknown extractor {name!r}; choose from {sorted(EXTRACTORS)}") from exc
