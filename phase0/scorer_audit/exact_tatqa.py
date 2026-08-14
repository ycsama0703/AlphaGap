from __future__ import annotations

import math
import re
import string
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from .types import AnswerValue, GoldItem, PredictionItem, TraceEvent


_NUMBER_RE = re.compile(r"([+-]?\d+(\.\d+)?)|([+-]?\.\d+)")
_ACCOUNTING_RE = re.compile(r"(\([\d.\s]+\))")
_PERCENT_RE = re.compile(r"([\d.\s]+%)")
_WORD_SCALE_RE = re.compile(r"([\d.]+\s?[a-zA-Z]+)")
_ARTICLES_RE = re.compile(r"\b(a|an|the)\b", re.UNICODE)
_OFFICIAL_NUM_EXCLUDE = "'\"\\$€£¥%(),[]"


@dataclass(frozen=True)
class ExactPermissions:
    """Switches inside one faithful implementation of the TAT-QA metric path."""

    numeric_normalization: bool = False
    word_scale: bool = False
    structured_scale: bool = False
    accounting_parentheses: bool = False
    percent_conversion: bool = False
    round_two: bool = False
    percent_alternate: bool = False


EXACT_POLICIES: dict[str, ExactPermissions] = {
    "exact_p1_syntax": ExactPermissions(),
    "exact_p2_scale": ExactPermissions(
        numeric_normalization=True,
        word_scale=True,
        structured_scale=True,
    ),
    "exact_p3_numeric": ExactPermissions(
        numeric_normalization=True,
        word_scale=True,
        structured_scale=True,
        accounting_parentheses=True,
        percent_conversion=True,
    ),
    "exact_p4_round2": ExactPermissions(
        numeric_normalization=True,
        word_scale=True,
        structured_scale=True,
        accounting_parentheses=True,
        percent_conversion=True,
        round_two=True,
    ),
    "exact_official": ExactPermissions(
        numeric_normalization=True,
        word_scale=True,
        structured_scale=True,
        accounting_parentheses=True,
        percent_conversion=True,
        round_two=True,
        percent_alternate=True,
    ),
}
EXACT_POLICY_ORDER = tuple(EXACT_POLICIES)
_OFFICIAL = EXACT_POLICIES["exact_official"]


def _scale_to_num(scale: str, *, enabled: bool) -> int | float:
    if not enabled:
        return 1
    scale = scale.lower()
    if "hundred" in scale:
        return 100
    if "thousand" in scale:
        return 1000
    if "million" in scale:
        return 1000000
    if "billion" in scale:
        return 1000000000
    if "percent" in scale:
        return 0.01
    return 1


def _clean_num(text: str) -> str:
    return "".join(ch for ch in str(text) if ch not in _OFFICIAL_NUM_EXCLUDE)


def _contains_disabled_semantics(text: str, permissions: ExactPermissions) -> bool:
    if not permissions.accounting_parentheses and _ACCOUNTING_RE.search(text.strip()):
        return True
    if not permissions.percent_conversion and "%" in text:
        return True
    return False


def _extract_one_num(text: str, permissions: ExactPermissions) -> float | int | None:
    if not permissions.numeric_normalization or _contains_disabled_semantics(text, permissions):
        return None
    groups = _NUMBER_RE.findall(_clean_num(text))
    if not groups or not groups[0][0]:
        return None
    value = groups[0][0]
    return float(value) if "." in value else int(value)


def _is_number(text: str, permissions: ExactPermissions) -> bool:
    if not permissions.numeric_normalization or _contains_disabled_semantics(text, permissions):
        return False
    try:
        words = " ".join(_clean_num(word) for word in str(text).split()).split()
        if not words:
            return False
        value = float(words[0])
        if math.isnan(value):
            return False
        if len(words) >= 2 and _scale_to_num(words[1], enabled=permissions.word_scale) == 1:
            return False
        return True
    except ValueError:
        return False


def _to_number(text: str, permissions: ExactPermissions) -> float | None:
    number = _extract_one_num(text, permissions)
    if number is None:
        return None
    scale: int | float = 1
    if permissions.word_scale:
        match = _WORD_SCALE_RE.search(text)
        if match:
            scale = _scale_to_num(match.group(0).lower(), enabled=True)
    negative = -1 if permissions.accounting_parentheses and _ACCOUNTING_RE.search(text.strip()) else 1
    percent = 0.01 if permissions.percent_conversion and _PERCENT_RE.search(text.strip()) else 1
    return round(number * scale * negative * percent, 4)


def _remove_punc(text: str) -> str:
    # Official TAT-QA preserves punctuation on numeric-looking tokens.  We use
    # the all-on recognizer for that classification at every policy, so P1 does
    # not silently erase a sign, percent symbol, or accounting parentheses.
    if _is_number(text, _OFFICIAL):
        return text
    return "".join(ch for ch in text if ch not in set(string.punctuation))


def _normalize_answer(text: str, permissions: ExactPermissions) -> tuple[str, list[TraceEvent]]:
    parts: list[str] = []
    trace: list[TraceEvent] = []
    for token in re.split(" ", str(text)):
        lowered = token.lower()
        unpunctuated = _remove_punc(lowered)
        normalized = unpunctuated
        if _is_number(unpunctuated, permissions):
            number = _to_number(unpunctuated, permissions)
            if number is not None:
                normalized = str(number)
                trace.append(
                    TraceEvent(
                        "numeric_normalization",
                        unpunctuated,
                        normalized,
                        unpunctuated != normalized,
                    )
                )
        normalized = " ".join(_ARTICLES_RE.sub(" ", normalized).split())
        if normalized.strip():
            parts.append(normalized)
    return " ".join(parts).strip(), trace


def _format_answer_strings(
    answer: AnswerValue, permissions: ExactPermissions
) -> tuple[list[str], list[TraceEvent]]:
    rendered: list[str] = []
    trace: list[TraceEvent] = []
    for span in sorted(answer.spans):
        answer_string = str(span)
        if _is_number(answer_string, permissions):
            number = _to_number(answer_string, permissions)
            if number is None:
                output = f"{answer_string} {answer.scale}" if answer.scale else answer_string
            elif "%" in answer_string and permissions.percent_conversion:
                output = "%.4f" % number
                trace.append(
                    TraceEvent("percent_conversion", answer_string, output, answer_string != output)
                )
            else:
                rounded = round(number, 2) if permissions.round_two else number
                if permissions.round_two:
                    trace.append(
                        TraceEvent("round_two", str(number), str(rounded), rounded != number)
                    )
                if permissions.structured_scale:
                    scaled = rounded * _scale_to_num(answer.scale, enabled=True)
                    output = "%.4f" % scaled
                    if answer.scale:
                        trace.append(
                            TraceEvent(
                                "structured_scale",
                                str(rounded),
                                output,
                                scaled != rounded,
                                {"scale": answer.scale},
                            )
                        )
                else:
                    output = str(rounded)
                    if answer.scale:
                        output = f"{output} {answer.scale}"
                if permissions.word_scale and _WORD_SCALE_RE.search(answer_string):
                    trace.append(
                        TraceEvent("word_scale", answer_string, str(number), answer_string != str(number))
                    )
                if permissions.accounting_parentheses and _ACCOUNTING_RE.search(answer_string):
                    trace.append(
                        TraceEvent(
                            "accounting_parentheses", answer_string, str(number), answer_string != str(number)
                        )
                    )
        else:
            output = f"{answer_string} {answer.scale}" if answer.scale else answer_string
        rendered.append(output)
    return [" ".join(rendered)], trace


def _add_percent_prediction(
    prediction_strings: list[str], prediction: AnswerValue, permissions: ExactPermissions
) -> tuple[list[str], list[TraceEvent]]:
    if not permissions.percent_alternate or len(prediction.spans) != 1:
        return prediction_strings, []
    surface = str(prediction.spans[0])
    if prediction.scale or "%" in surface or not _is_number(surface, permissions):
        return prediction_strings, []
    number = _to_number(surface, permissions)
    if number is None:
        return prediction_strings, []
    alternate = "%.4f" % number
    return prediction_strings + [alternate], [
        TraceEvent("percent_alternate", prediction_strings[0], alternate, alternate != prediction_strings[0])
    ]


def _metrics(predicted: str, gold: str, permissions: ExactPermissions) -> tuple[float, float, str, str, list[TraceEvent]]:
    predicted_normalized, pred_trace = _normalize_answer(predicted, permissions)
    gold_normalized, _ = _normalize_answer(gold, permissions)
    exact_match = float(predicted_normalized == gold_normalized)
    predicted_bag = set(predicted_normalized.split())
    gold_bag = set(gold_normalized.split())
    intersection = len(predicted_bag & gold_bag)
    precision = intersection / len(predicted_bag) if predicted_bag else 1.0
    recall = intersection / len(gold_bag) if gold_bag else 1.0
    f1 = 0.0 if precision == 0.0 and recall == 0.0 else 2 * precision * recall / (precision + recall)
    return exact_match, round(f1, 2), predicted_normalized, gold_normalized, pred_trace


def _gold_answer(gold: GoldItem) -> AnswerValue:
    if gold.answer_type != "count" or not gold.answer.spans:
        return gold.answer
    try:
        count = str(int(float(gold.answer.spans[0])))
    except ValueError:
        count = gold.answer.spans[0]
    return AnswerValue((count,), gold.answer.scale)


def score_exact_item(
    gold: GoldItem,
    prediction: PredictionItem | None,
    policy: str,
) -> dict[str, Any]:
    """Score one item through the permission-controlled official metric path."""
    permissions = EXACT_POLICIES[policy]
    predicted_answer = prediction.answer if prediction else AnswerValue.from_parts(None)
    gold_answer = _gold_answer(gold)
    gold_strings, gold_trace = _format_answer_strings(gold_answer, permissions)
    pred_strings, pred_trace = _format_answer_strings(predicted_answer, permissions)
    pred_strings, alternate_trace = _add_percent_prediction(pred_strings, predicted_answer, permissions)
    pred_trace.extend(alternate_trace)

    best = (0.0, 0.0, "", "", [])
    if predicted_answer.spans and gold_answer.spans:
        candidates = [
            _metrics(pred_string, gold_string, permissions)
            for pred_string in pred_strings
            for gold_string in gold_strings
        ]
        if candidates:
            best = max(candidates, key=lambda result: (result[0], result[1]))
    em, f1, pred_normalized, gold_normalized, normalize_trace = best
    pred_trace.extend(normalize_trace)
    scale_em = float(bool(predicted_answer.spans) and predicted_answer.scale == gold_answer.scale)
    return {
        "uid": gold.uid,
        "policy": policy,
        "correct": bool(em),
        "em": em,
        "f1": f1 if gold.answer_type not in {"arithmetic", "count"} else em,
        "scale_em": scale_em,
        "gold": gold_answer.to_json(),
        "prediction": predicted_answer.to_json(),
        "gold_strings": gold_strings,
        "prediction_strings": pred_strings,
        "gold_canonical": gold_normalized,
        "pred_canonical": pred_normalized,
        "trace": [event.to_json() for event in pred_trace],
        "gold_trace": [event.to_json() for event in gold_trace],
        "answer_type": gold.answer_type,
        "extractor": prediction.extractor if prediction else "missing",
        "raw": prediction.raw if prediction else "",
        "metadata": gold.metadata,
    }


def audit_exact(
    gold_items: Sequence[GoldItem],
    predictions: dict[str, PredictionItem],
    policies: Sequence[str] = EXACT_POLICY_ORDER,
) -> list[dict[str, Any]]:
    return [
        score_exact_item(gold, predictions.get(gold.uid), policy)
        for gold in gold_items
        for policy in policies
    ]


def summarize_exact(
    rows: Iterable[dict[str, Any]], policies: Sequence[str] = EXACT_POLICY_ORDER
) -> dict[str, Any]:
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_policy[row["policy"]].append(row)
    scores: dict[str, Any] = {}
    correctness: dict[str, dict[str, bool]] = {}
    for policy in policies:
        current = by_policy.get(policy, [])
        n = len(current)
        correctness[policy] = {row["uid"]: bool(row["correct"]) for row in current}
        operations = Counter(
            event["operation"]
            for row in current
            for event in row["trace"]
            if event["changed"]
        )
        scores[policy] = {
            "n": n,
            "correct": sum(row["em"] for row in current),
            "em": sum(row["em"] for row in current) / n if n else 0.0,
            "f1": sum(row["f1"] for row in current) / n if n else 0.0,
            "scale": sum(row["scale_em"] for row in current) / n if n else 0.0,
            "effective_operations": dict(sorted(operations.items())),
        }
    transitions: list[dict[str, Any]] = []
    for low, high in zip(policies, policies[1:]):
        uids = sorted(set(correctness.get(low, {})) | set(correctness.get(high, {})))
        counts = Counter(
            f"{int(correctness[low].get(uid, False))}->{int(correctness[high].get(uid, False))}"
            for uid in uids
        )
        transitions.append(
            {
                "low": low,
                "high": high,
                "n": len(uids),
                "n00": counts["0->0"],
                "n01": counts["0->1"],
                "n10": counts["1->0"],
                "n11": counts["1->1"],
                "delta_em": (counts["0->1"] - counts["1->0"]) / len(uids) if uids else 0.0,
            }
        )
    return {"scores": scores, "transitions": transitions}


def exact_decision_changes(
    rows: Iterable[dict[str, Any]], policies: Sequence[str] = EXACT_POLICY_ORDER
) -> list[dict[str, Any]]:
    rows = list(rows)
    lookup = {(row["uid"], row["policy"]): row for row in rows}
    changes: list[dict[str, Any]] = []
    for low, high in zip(policies, policies[1:]):
        for uid in sorted({row["uid"] for row in rows}):
            low_row = lookup[(uid, low)]
            high_row = lookup[(uid, high)]
            if low_row["correct"] == high_row["correct"]:
                continue
            changes.append(
                {
                    "uid": uid,
                    "low_policy": low,
                    "high_policy": high,
                    "transition": f"{int(low_row['correct'])}->{int(high_row['correct'])}",
                    "low": low_row,
                    "high": high_row,
                }
            )
    return changes


def compare_official_rows(
    exact_rows: Iterable[dict[str, Any]], official_rows: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    exact = {row["uid"]: row for row in exact_rows if row["policy"] == "exact_official"}
    official = {row["uid"]: row for row in official_rows}
    shared = sorted(set(exact) & set(official))
    mismatches = [
        {
            "uid": uid,
            "exact_em": exact[uid]["em"],
            "official_em": official[uid]["em"],
            "exact_f1": exact[uid]["f1"],
            "official_f1": official[uid]["f1"],
        }
        for uid in shared
        if exact[uid]["em"] != official[uid]["em"] or exact[uid]["f1"] != official[uid]["f1"]
    ]
    return {
        "n_exact": len(exact),
        "n_official": len(official),
        "n_shared": len(shared),
        "n_mismatches": len(mismatches),
        "itemwise_exact": len(exact) == len(official) == len(shared) and not mismatches,
        "mismatches": mismatches,
    }
