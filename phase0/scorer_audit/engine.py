from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from typing import Any

from .policies import POLICY_ORDER, canonicalize
from .types import AnswerValue, GoldItem, PredictionItem


def audit(
    gold_items: Sequence[GoldItem],
    predictions: dict[str, PredictionItem],
    policies: Sequence[str] = POLICY_ORDER,
    *,
    mode: str = "fixed_gold",
    gold_policy: str = "p4_round2",
) -> list[dict[str, Any]]:
    """Return one auditable row per item and policy.

    ``fixed_gold`` freezes the gold under ``gold_policy`` and varies only the
    prediction policy. ``symmetric`` applies each policy to both sides and is
    useful for reproducing a benchmark's policy-level behavior.
    """
    if mode not in {"fixed_gold", "symmetric"}:
        raise ValueError("mode must be 'fixed_gold' or 'symmetric'")
    rows: list[dict[str, Any]] = []
    empty = AnswerValue.from_parts(None)
    for gold in gold_items:
        prediction = predictions.get(gold.uid)
        predicted_answer = prediction.answer if prediction else empty
        for policy in policies:
            applied_gold_policy = gold_policy if mode == "fixed_gold" else policy
            gold_result = canonicalize(gold.answer, applied_gold_policy)
            pred_result = canonicalize(predicted_answer, policy)
            rows.append(
                {
                    "uid": gold.uid,
                    "policy": policy,
                    "mode": mode,
                    "correct": bool(pred_result.value and pred_result.value == gold_result.value),
                    "gold": gold.answer.to_json(),
                    "prediction": predicted_answer.to_json(),
                    "gold_canonical": gold_result.value,
                    "pred_canonical": pred_result.value,
                    "trace": [event.to_json() for event in pred_result.trace],
                    "answer_type": gold.answer_type,
                    "extractor": prediction.extractor if prediction else "missing",
                    "raw": prediction.raw if prediction else "",
                    "metadata": gold.metadata,
                }
            )
    return rows


def summarize_audit(rows: Iterable[dict[str, Any]], policies: Sequence[str] = POLICY_ORDER) -> dict[str, Any]:
    rows = list(rows)
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_policy[row["policy"]].append(row)

    scores: dict[str, Any] = {}
    for policy in policies:
        current = by_policy.get(policy, [])
        correct = sum(bool(row["correct"]) for row in current)
        operations = Counter(
            event["operation"]
            for row in current
            for event in row.get("trace", [])
            if event.get("changed")
        )
        scores[policy] = {
            "n": len(current),
            "correct": correct,
            "em": correct / len(current) if current else 0.0,
            "effective_operations": dict(sorted(operations.items())),
        }

    correctness = {
        policy: {row["uid"]: bool(row["correct"]) for row in by_policy.get(policy, [])}
        for policy in policies
    }
    transitions: list[dict[str, Any]] = []
    for low, high in zip(policies, policies[1:]):
        uids = sorted(set(correctness[low]) | set(correctness[high]))
        counts = Counter(
            f"{int(correctness[low].get(uid, False))}->{int(correctness[high].get(uid, False))}"
            for uid in uids
        )
        n = len(uids)
        transitions.append(
            {
                "low": low,
                "high": high,
                "n": n,
                "n00": counts["0->0"],
                "n01": counts["0->1"],
                "n10": counts["1->0"],
                "n11": counts["1->1"],
                "delta_em": (counts["0->1"] - counts["1->0"]) / n if n else 0.0,
            }
        )
    return {"scores": scores, "transitions": transitions}


def decision_changes(
    rows: Iterable[dict[str, Any]], policies: Sequence[str] = POLICY_ORDER
) -> list[dict[str, Any]]:
    """Return item-level 0→1 and 1→0 records for adjacent policies."""
    lookup = {(row["uid"], row["policy"]): row for row in rows}
    uids = sorted({uid for uid, _ in lookup})
    changes: list[dict[str, Any]] = []
    for low, high in zip(policies, policies[1:]):
        for uid in uids:
            low_row = lookup.get((uid, low))
            high_row = lookup.get((uid, high))
            if not low_row or not high_row or low_row["correct"] == high_row["correct"]:
                continue
            changes.append(
                {
                    "uid": uid,
                    "low_policy": low,
                    "high_policy": high,
                    "transition": f"{int(low_row['correct'])}->{int(high_row['correct'])}",
                    "low_pred_canonical": low_row["pred_canonical"],
                    "high_pred_canonical": high_row["pred_canonical"],
                    "gold_canonical": high_row["gold_canonical"],
                    "prediction": high_row["prediction"],
                    "gold": high_row["gold"],
                    "trace": high_row["trace"],
                    "answer_type": high_row["answer_type"],
                    "extractor": high_row["extractor"],
                    "raw": high_row["raw"],
                    "metadata": high_row["metadata"],
                }
            )
    return changes
