from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _lookup(path: Path) -> dict[str, dict[str, Any]]:
    return {row["blind_id"]: row for row in _jsonl(path)}


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _consensus(left: dict[str, Any], right: dict[str, Any], field: str) -> Any | None:
    return left[field] if left[field] == right[field] else None


def _field_summary(
    ids: list[str],
    left: dict[str, dict[str, Any]],
    right: dict[str, dict[str, Any]],
    fields: tuple[str, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field in fields:
        values = [
            left[blind_id][field]
            if left[blind_id][field] == right[blind_id][field]
            else "DISAGREE"
            for blind_id in ids
        ]
        result[field] = dict(Counter(str(value) for value in values))
    return result


def build_unblinded_judge_report(
    reviewer_dir: str | Path,
    private_dir: str | Path,
    judge_a_dir: str | Path,
    judge_b_dir: str | Path,
    out_dir: str | Path,
) -> dict[str, Any]:
    reviewer = Path(reviewer_dir)
    private = Path(private_dir)
    judge_a = Path(judge_a_dir)
    judge_b = Path(judge_b_dir)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    direct_key = _lookup(private / "direct_key.jsonl")
    mechanism_key = _lookup(private / "mechanism_key.jsonl")
    reviewer_rows = {
        "pass1": _lookup(reviewer / "pass1_intent.jsonl"),
        "pass2": _lookup(reviewer / "pass2_adjudication.jsonl"),
        "mechanism": _lookup(reviewer / "mechanism_edges.jsonl"),
    }
    labels_a = {
        stage: _lookup(judge_a / f"labels_{stage}.jsonl")
        for stage in ("pass1", "pass2", "mechanism")
    }
    labels_b = {
        stage: _lookup(judge_b / f"labels_{stage}.jsonl")
        for stage in ("pass1", "pass2", "mechanism")
    }
    model_a = json.loads((judge_a / "summary.json").read_text(encoding="utf-8"))["model"]
    model_b = json.loads((judge_b / "summary.json").read_text(encoding="utf-8"))["model"]

    direct_fields = (
        "extraction_faithful",
        "benchmark_correct_candidate",
        "semantic_transformation_justified",
        "error_source",
    )
    direct_groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for blind_id, key in direct_key.items():
        direct_groups[(key["sample_role"], key["condition"])].append(blind_id)
    direct_summary = {
        f"{role}:{condition}": {
            "n": len(ids),
            "fields": _field_summary(ids, labels_a["pass2"], labels_b["pass2"], direct_fields),
        }
        for (role, condition), ids in sorted(direct_groups.items())
    }

    mechanism_fields = (
        "extraction_faithful",
        "benchmark_correct_candidate",
        "semantic_transformation_justified",
        "decision_change_justified",
        "error_source",
    )
    mechanism_groups: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for blind_id, key in mechanism_key.items():
        edge = f"{key['low_policy']}->{key['high_policy']}"
        mechanism_groups[(key["condition"], edge, key["transition"])].append(blind_id)
    mechanism_summary = {
        f"{condition}:{edge}:{transition}": {
            "n": len(ids),
            "fields": _field_summary(
                ids, labels_a["mechanism"], labels_b["mechanism"], mechanism_fields
            ),
        }
        for (condition, edge, transition), ids in sorted(mechanism_groups.items())
    }

    queue_fields = {
        "pass1": (
            "asserted_answer",
            "asserted_sign",
            "single_final_answer",
            "recomputation_required",
        ),
        "pass2": (
            "extraction_faithful",
            "benchmark_correct_candidate",
            "semantic_transformation_justified",
            "error_source",
        ),
        "mechanism": (
            "benchmark_correct_candidate",
            "semantic_transformation_justified",
            "decision_change_justified",
            "error_source",
        ),
    }
    queue: list[dict[str, Any]] = []
    for stage, fields in queue_fields.items():
        key_lookup = direct_key if stage != "mechanism" else mechanism_key
        for blind_id in sorted(set(labels_a[stage]) & set(labels_b[stage])):
            differing = [
                field
                for field in fields
                if labels_a[stage][blind_id][field] != labels_b[stage][blind_id][field]
            ]
            if not differing:
                continue
            key = key_lookup[blind_id]
            queue.append(
                {
                    "stage": stage,
                    "blind_id": blind_id,
                    "uid": key["uid"],
                    "condition": key["condition"],
                    "sample_role": key.get("sample_role"),
                    "low_policy": key.get("low_policy"),
                    "high_policy": key.get("high_policy"),
                    "automatic_transition": key.get("transition", key.get("direct_transition")),
                    "differing_fields": differing,
                    "record": reviewer_rows[stage][blind_id],
                    "judge_a": labels_a[stage][blind_id],
                    "judge_b": labels_b[stage][blind_id],
                }
            )
    _write_jsonl(out / "adjudication_queue.jsonl", queue)
    core_queue = [
        row
        for row in queue
        if (
            row["stage"] == "pass2"
            and bool(
                {"extraction_faithful", "benchmark_correct_candidate"}
                & set(row["differing_fields"])
            )
        )
        or (
            row["stage"] == "mechanism"
            and bool(
                {"benchmark_correct_candidate", "decision_change_justified"}
                & set(row["differing_fields"])
            )
        )
    ]
    _write_jsonl(out / "core_adjudication_queue.jsonl", core_queue)

    mechanism_decisions = Counter()
    for blind_id in mechanism_key:
        left = labels_a["mechanism"][blind_id]["decision_change_justified"]
        right = labels_b["mechanism"][blind_id]["decision_change_justified"]
        mechanism_decisions[left if left == right else "DISAGREE"] += 1
    direct_changes = [
        blind_id for blind_id, key in direct_key.items() if key["sample_role"] == "direct_change"
    ]
    direct_change_consensus = {
        field: dict(
            Counter(
                labels_a["pass2"][blind_id][field]
                if labels_a["pass2"][blind_id][field] == labels_b["pass2"][blind_id][field]
                else "DISAGREE"
                for blind_id in direct_changes
            )
        )
        for field in direct_fields
    }

    source_paths = [
        private / "direct_key.jsonl",
        private / "mechanism_key.jsonl",
        *[judge_a / f"labels_{stage}.jsonl" for stage in labels_a],
        *[judge_b / f"labels_{stage}.jsonl" for stage in labels_b],
    ]
    report = {
        "warning": "UNBLINDED: contains condition, policy, transition, and UID mappings.",
        "judge_a": model_a,
        "judge_b": model_b,
        "direct_change_n": len(direct_changes),
        "direct_change_consensus": direct_change_consensus,
        "mechanism_decision_consensus": dict(mechanism_decisions),
        "direct_groups": direct_summary,
        "mechanism_groups": mechanism_summary,
        "adjudication_queue_records": len(queue),
        "adjudication_queue_unique_uids": len({row["uid"] for row in queue}),
        "core_adjudication_queue_records": len(core_queue),
        "core_adjudication_queue_unique_uids": len({row["uid"] for row in core_queue}),
        "source_sha256": {str(path.resolve()): _sha256(path) for path in source_paths},
    }
    (out / "unblinded_summary.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return report
