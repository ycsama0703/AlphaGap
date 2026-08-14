from __future__ import annotations

import re
import string
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from .types import AnswerValue, CanonicalAnswer, TraceEvent


POLICY_ORDER = ("p0_raw", "p1_syntax", "p2_scale", "p3_numeric", "p4_round2")
SCALE_MULTIPLIERS = {
    "": Decimal("1"),
    "hundred": Decimal("100"),
    "thousand": Decimal("1000"),
    "million": Decimal("1000000"),
    "billion": Decimal("1000000000"),
    "percent": Decimal("0.01"),
}
_ARTICLE = re.compile(r"\b(a|an|the)\b", re.I)
_WORD_SCALE = re.compile(r"\s*(hundred|thousand|million|billion|percent)\s*$", re.I)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)$")
_CURRENCY = str.maketrans("", "", "$€£¥,")


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _join(spans: list[str], scale: str = "") -> str:
    body = " ␟ ".join(sorted(spans))
    return f"{body} ⟪scale:{scale}⟫" if scale else body


def _syntax(text: str, *, preserve_semantic_punctuation: bool = True) -> str:
    text = _ARTICLE.sub(" ", text.lower())
    out: list[str] = []
    semantic = set("()+-%.")
    for index, char in enumerate(text):
        if char in string.punctuation or char in "‘’´`":
            previous = text[index - 1] if index else ""
            following = text[index + 1] if index + 1 < len(text) else ""
            numeric_punctuation = char in semantic and (previous.isdigit() or following.isdigit())
            if preserve_semantic_punctuation and numeric_punctuation:
                out.append(char)
            elif char == ",":
                continue
            else:
                out.append(" ")
        else:
            out.append(char)
    return " ".join("".join(out).split())


@dataclass(frozen=True)
class _NumericParts:
    value_before_structured_scale: Decimal
    structured_scale: Decimal
    events: tuple[TraceEvent, ...]


def _numeric_parts(
    surface: str,
    structured_scale: str,
    *,
    allow_parentheses: bool,
    allow_percent_symbol: bool,
) -> _NumericParts | None:
    raw = surface.strip()
    text = raw
    events: list[TraceEvent] = []
    negative = False
    if text.startswith("(") and text.endswith(")"):
        if not allow_parentheses:
            return None
        before = text
        text = text[1:-1].strip()
        negative = True
        events.append(TraceEvent("accounting_parentheses", before, f"-{text}", True))

    percent_symbol = "%" in text
    if percent_symbol:
        if not allow_percent_symbol:
            return None
        before = text
        text = text.replace("%", "").strip()
        events.append(TraceEvent("percent_symbol", before, text, True))

    word_scale = ""
    match = _WORD_SCALE.search(text)
    if match:
        word_scale = match.group(1).lower()
        before = text
        text = text[:match.start()].strip()
        events.append(TraceEvent("word_scale", before, text, True, {"scale": word_scale}))

    text = text.translate(_CURRENCY).strip()
    if not _NUMBER.fullmatch(text):
        return None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if negative:
        value *= -1
    if word_scale:
        before = value
        value *= SCALE_MULTIPLIERS[word_scale]
        events.append(TraceEvent("word_scale_multiply", str(before), str(value), value != before))
    if percent_symbol:
        before = value
        value *= Decimal("0.01")
        events.append(TraceEvent("percent_multiply", str(before), str(value), value != before))

    scale = structured_scale if structured_scale in SCALE_MULTIPLIERS else ""
    multiplier = SCALE_MULTIPLIERS[scale]
    # TAT-QA avoids multiplying the percent field twice when the answer itself
    # contains a percent sign.
    if percent_symbol and scale == "percent":
        multiplier = Decimal("1")
    if scale:
        events.append(
            TraceEvent(
                "structured_scale",
                _decimal_text(value),
                _decimal_text(value * multiplier),
                multiplier != 1,
                {"scale": scale},
            )
        )
    return _NumericParts(value, multiplier, tuple(events))


def _numeric_or_text(
    answer: AnswerValue,
    *,
    allow_parentheses: bool,
    allow_percent_symbol: bool,
    round_two_before_scale: bool,
) -> CanonicalAnswer:
    transformed: list[str] = []
    trace: list[TraceEvent] = []
    for span in answer.spans:
        parts = _numeric_parts(
            span,
            answer.scale,
            allow_parentheses=allow_parentheses,
            allow_percent_symbol=allow_percent_symbol,
        )
        if parts is None:
            normalized = _syntax(span)
            if answer.scale:
                normalized = f"{normalized} ⟪scale:{answer.scale}⟫"
            transformed.append(normalized)
            trace.append(TraceEvent("syntax", span, normalized, span != normalized))
            continue
        value = parts.value_before_structured_scale
        trace.extend(parts.events)
        if round_two_before_scale:
            rounded = round(value, 2)
            trace.append(
                TraceEvent("round_two", _decimal_text(value), _decimal_text(rounded), rounded != value)
            )
            value = rounded
        value *= parts.structured_scale
        transformed.append(_decimal_text(value))
    return CanonicalAnswer(_join(transformed), tuple(trace))


def canonicalize(answer: AnswerValue, policy: str) -> CanonicalAnswer:
    if policy == "p0_raw":
        spans = [span.strip() for span in answer.spans]
        return CanonicalAnswer(_join(spans, answer.scale))
    if policy == "p1_syntax":
        spans = [_syntax(span) for span in answer.spans]
        events = tuple(
            TraceEvent("syntax", before, after, before != after)
            for before, after in zip(answer.spans, spans)
        )
        return CanonicalAnswer(_join(spans, answer.scale), events)
    if policy == "p1_strip_punctuation":
        spans = [_syntax(span, preserve_semantic_punctuation=False) for span in answer.spans]
        events = tuple(
            TraceEvent("syntax_strip_punctuation", before, after, before != after)
            for before, after in zip(answer.spans, spans)
        )
        return CanonicalAnswer(_join(spans, answer.scale), events)
    if policy == "p2_scale":
        return _numeric_or_text(
            answer,
            allow_parentheses=False,
            allow_percent_symbol=False,
            round_two_before_scale=False,
        )
    if policy == "p3_numeric":
        return _numeric_or_text(
            answer,
            allow_parentheses=True,
            allow_percent_symbol=True,
            round_two_before_scale=False,
        )
    if policy == "p4_round2":
        return _numeric_or_text(
            answer,
            allow_parentheses=True,
            allow_percent_symbol=True,
            round_two_before_scale=True,
        )
    raise ValueError(f"unknown policy {policy!r}")
