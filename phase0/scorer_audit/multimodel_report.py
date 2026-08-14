"""Cross-model report for scorer-policy and output-format reversals."""
from __future__ import annotations

import json
from itertools import combinations
from pathlib import Path
from typing import Any

from .pilot_report import _exact_binomial_two_sided, _paired_bootstrap

P1 = "exact_p1_syntax"
OFFICIAL = "exact_official"
POLICIES = (P1, OFFICIAL)


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _load_condition(run_dir: Path, exact_dir: str) -> dict[str, Any]:
    root = run_dir / exact_dir
    summary = json.loads((root / "exact_summary.json").read_text(encoding="utf-8"))
    rows = _jsonl(root / "exact_items.jsonl")
    correctness = {
        policy: {
            row["uid"]: int(bool(row["correct"]))
            for row in rows
            if row["policy"] == policy
        }
        for policy in POLICIES
    }
    if set(correctness[P1]) != set(correctness[OFFICIAL]):
        raise ValueError(f"policy UID mismatch in {root}")
    return {
        "summary": summary,
        "correctness": correctness,
        "uids": sorted(correctness[P1]),
    }


def _paired_comparison(left: dict[str, int], right: dict[str, int]) -> dict[str, Any]:
    uids = sorted(set(left) & set(right))
    if len(uids) != len(left) or len(uids) != len(right):
        raise ValueError("paired comparison requires identical UID sets")
    left_values = [left[uid] for uid in uids]
    right_values = [right[uid] for uid in uids]
    transitions = {
        f"{a}->{b}": sum(x == a and y == b for x, y in zip(left_values, right_values))
        for a in (0, 1)
        for b in (0, 1)
    }
    discordant = transitions["0->1"] + transitions["1->0"]
    return {
        "n": len(uids),
        "transitions": transitions,
        "right_minus_left": _paired_bootstrap(left_values, right_values),
        "mcnemar_exact_p": _exact_binomial_two_sided(transitions["0->1"], discordant),
    }


def pairwise_reversals(
    labels: list[str],
    p1_scores: dict[str, float],
    official_scores: dict[str, float],
) -> list[dict[str, Any]]:
    rows = []
    for left, right in combinations(sorted(labels), 2):
        delta_p1 = p1_scores[left] - p1_scores[right]
        delta_official = official_scores[left] - official_scores[right]
        rows.append(
            {
                "left": left,
                "right": right,
                "delta_p1": delta_p1,
                "delta_official": delta_official,
                "strict_reversal": delta_p1 * delta_official < 0,
                "tie_change": (delta_p1 == 0) != (delta_official == 0),
            }
        )
    return rows


def _rank(scores: dict[str, float]) -> list[dict[str, Any]]:
    ordered = sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))
    result = []
    previous_score: float | None = None
    previous_rank = 0
    for index, (label, score) in enumerate(ordered, 1):
        rank = previous_rank if previous_score == score else index
        result.append({"rank": rank, "label": label, "em": score})
        previous_score = score
        previous_rank = rank
    return result


def build_multimodel_report(
    model_runs: dict[str, str | Path],
    *,
    free_exact_dir: str = "exact_free_llm_labeled_low2000",
    json_exact_dir: str = "exact_json_schema",
) -> dict[str, Any]:
    if len(model_runs) < 2:
        raise ValueError("at least two models are required")
    loaded: dict[str, dict[str, Any]] = {}
    reference_uids: list[str] | None = None
    for model, run_path in model_runs.items():
        run_dir = Path(run_path)
        free = _load_condition(run_dir, free_exact_dir)
        json_condition = _load_condition(run_dir, json_exact_dir)
        if free["uids"] != json_condition["uids"]:
            raise ValueError(f"free/json UID mismatch for {model}")
        if reference_uids is None:
            reference_uids = free["uids"]
        elif free["uids"] != reference_uids:
            raise ValueError(f"cross-model UID mismatch for {model}")
        loaded[model] = {"free": free, "json": json_condition}

    report: dict[str, Any] = {
        "n_models": len(loaded),
        "n_items": len(reference_uids or []),
        "models": {},
        "rankings": {},
        "model_rank_reversals": {},
    }
    for model, conditions in loaded.items():
        scores = {
            condition: {
                policy: data["summary"]["scores"][policy]["em"]
                for policy in POLICIES
            }
            for condition, data in conditions.items()
        }
        format_by_policy = {
            policy: _paired_comparison(
                conditions["free"]["correctness"][policy],
                conditions["json"]["correctness"][policy],
            )
            for policy in POLICIES
        }
        free_sca = scores["free"][OFFICIAL] - scores["free"][P1]
        json_sca = scores["json"][OFFICIAL] - scores["json"][P1]
        p1_gap = scores["json"][P1] - scores["free"][P1]
        official_gap = scores["json"][OFFICIAL] - scores["free"][OFFICIAL]
        difference_in_sca = json_sca - free_sca
        report["models"][model] = {
            "scores": scores,
            "format_comparison": format_by_policy,
            "free_sca": free_sca,
            "json_sca": json_sca,
            "difference_in_sca": difference_in_sca,
            "fraction_of_official_format_gap": (
                difference_in_sca / official_gap if official_gap else None
            ),
            "format_gap_p1": p1_gap,
            "format_gap_official": official_gap,
            "strict_format_conclusion_reversal": p1_gap * official_gap < 0,
            "format_tie_change": (p1_gap == 0) != (official_gap == 0),
            "official_itemwise_verified": {
                condition: bool(
                    data["summary"].get("official_verification", {}).get("itemwise_exact")
                )
                for condition, data in conditions.items()
            },
        }

    for condition in ("free", "json"):
        p1_scores = {
            model: report["models"][model]["scores"][condition][P1] for model in loaded
        }
        official_scores = {
            model: report["models"][model]["scores"][condition][OFFICIAL] for model in loaded
        }
        report["rankings"][condition] = {
            P1: _rank(p1_scores),
            OFFICIAL: _rank(official_scores),
        }
        reversal_rows = pairwise_reversals(list(loaded), p1_scores, official_scores)
        for row in reversal_rows:
            left = row["left"]
            right = row["right"]
            row["paired_p1"] = _paired_comparison(
                loaded[right][condition]["correctness"][P1],
                loaded[left][condition]["correctness"][P1],
            )
            row["paired_official"] = _paired_comparison(
                loaded[right][condition]["correctness"][OFFICIAL],
                loaded[left][condition]["correctness"][OFFICIAL],
            )
        report["model_rank_reversals"][condition] = reversal_rows

    pipelines = [f"{model}/{condition}" for model in loaded for condition in ("free", "json")]
    p1_pipeline_scores = {
        f"{model}/{condition}": report["models"][model]["scores"][condition][P1]
        for model in loaded
        for condition in ("free", "json")
    }
    official_pipeline_scores = {
        f"{model}/{condition}": report["models"][model]["scores"][condition][OFFICIAL]
        for model in loaded
        for condition in ("free", "json")
    }
    report["pipeline_rankings"] = {
        P1: _rank(p1_pipeline_scores),
        OFFICIAL: _rank(official_pipeline_scores),
    }
    report["pipeline_rank_reversals"] = pairwise_reversals(
        pipelines, p1_pipeline_scores, official_pipeline_scores
    )
    report["gates"] = {
        "any_model_rank_reversal": any(
            row["strict_reversal"]
            for condition in report["model_rank_reversals"].values()
            for row in condition
        ),
        "any_pipeline_rank_reversal": any(
            row["strict_reversal"] for row in report["pipeline_rank_reversals"]
        ),
        "any_format_conclusion_reversal": any(
            row["strict_format_conclusion_reversal"] for row in report["models"].values()
        ),
    }
    return report
