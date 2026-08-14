from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


STAGE_FILES = {
    "pass1": "pass1_intent.jsonl",
    "pass2": "pass2_adjudication.jsonl",
    "mechanism": "mechanism_edges.jsonl",
}
FIELDS = {
    "pass1": (
        "asserted_answer",
        "asserted_scale",
        "asserted_sign",
        "single_final_answer",
        "ambiguity",
        "recomputation_required",
        "confidence",
    ),
    "pass2": (
        "extraction_faithful",
        "more_faithful_candidate",
        "benchmark_correct_candidate",
        "semantic_transformation_justified",
        "error_source",
        "confidence",
    ),
    "mechanism": (
        "extraction_faithful",
        "more_faithful_candidate",
        "benchmark_correct_candidate",
        "semantic_transformation_justified",
        "decision_change_justified",
        "error_source",
        "confidence",
    ),
}
SUBSTANTIVE_FIELDS = {
    stage: tuple(field for field in fields if field != "confidence") for stage, fields in FIELDS.items()
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _value(value: Any) -> str:
    if isinstance(value, list):
        return json.dumps([str(item).strip().lower() for item in value], ensure_ascii=False)
    return str(value).strip().lower()


def cohen_kappa(left: Iterable[Any], right: Iterable[Any]) -> float | None:
    pairs = [(_value(a), _value(b)) for a, b in zip(left, right)]
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    left_counts = Counter(a for a, _ in pairs)
    right_counts = Counter(b for _, b in pairs)
    expected = sum(left_counts[label] * right_counts[label] for label in set(left_counts) | set(right_counts)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else 0.0
    return (observed - expected) / (1 - expected)


def build_judge_agreement(
    reviewer_dir: str | Path,
    judge_a_dir: str | Path,
    judge_b_dir: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    reviewer = Path(reviewer_dir)
    judge_a = Path(judge_a_dir)
    judge_b = Path(judge_b_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary_a = json.loads((judge_a / "summary.json").read_text(encoding="utf-8"))
    summary_b = json.loads((judge_b / "summary.json").read_text(encoding="utf-8"))
    report: dict[str, Any] = {
        "judge_a": summary_a["model"],
        "judge_b": summary_b["model"],
        "stage_agreement": {},
        "cost_usd": {
            "judge_a": summary_a["recorded_cost_usd"],
            "judge_b": summary_b["recorded_cost_usd"],
            "total": summary_a["recorded_cost_usd"] + summary_b["recorded_cost_usd"],
        },
    }
    total_disagreements = 0
    for stage, source_file in STAGE_FILES.items():
        source = {row["blind_id"]: row for row in _jsonl(reviewer / source_file)}
        left = {row["blind_id"]: row for row in _jsonl(judge_a / f"labels_{stage}.jsonl")}
        right = {row["blind_id"]: row for row in _jsonl(judge_b / f"labels_{stage}.jsonl")}
        shared = sorted(set(left) & set(right))
        fields: dict[str, Any] = {}
        for field in FIELDS[stage]:
            left_values = [left[blind_id][field] for blind_id in shared]
            right_values = [right[blind_id][field] for blind_id in shared]
            fields[field] = {
                "agreement": sum(_value(a) == _value(b) for a, b in zip(left_values, right_values)) / len(shared)
                if shared
                else None,
                "cohen_kappa": cohen_kappa(left_values, right_values),
            }
        disagreements: list[dict[str, Any]] = []
        for blind_id in shared:
            differing = [
                field
                for field in SUBSTANTIVE_FIELDS[stage]
                if _value(left[blind_id][field]) != _value(right[blind_id][field])
            ]
            if not differing:
                continue
            disagreements.append(
                {
                    "blind_id": blind_id,
                    "differing_fields": differing,
                    "record": source[blind_id],
                    "judge_a": left[blind_id],
                    "judge_b": right[blind_id],
                }
            )
        _write_jsonl(out / f"disagreements_{stage}.jsonl", disagreements)
        total_disagreements += len(disagreements)
        report["stage_agreement"][stage] = {
            "n_source": len(source),
            "n_judge_a": len(left),
            "n_judge_b": len(right),
            "n_shared": len(shared),
            "full_substantive_agreement": (len(shared) - len(disagreements)) / len(shared)
            if shared
            else None,
            "n_disagreements": len(disagreements),
            "fields": fields,
        }
    report["total_disagreement_records"] = total_disagreements
    (out / "agreement_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
