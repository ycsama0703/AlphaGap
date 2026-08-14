from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PRIMARY_CONDITIONS = (
    {
        "label": "free_llm_labeled_low2000",
        "exact_dir": "exact_free_llm_labeled_low2000",
        "predictions": "preds_free_llm_labeled_low2000.json",
        "raw": "raw_free.jsonl",
    },
    {
        "label": "json_schema",
        "exact_dir": "exact_json_schema",
        "predictions": "preds_json_schema.json",
        "raw": "raw_json.jsonl",
    },
)

_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.I,
)
_FORBIDDEN_REVIEWER_TEXT = (
    "free_llm_labeled_low2000",
    "json_schema",
    "exact_p1_syntax",
    "exact_p2_scale",
    "exact_p3_numeric",
    "exact_p4_round2",
    "exact_official",
)
_FORBIDDEN_REVIEWER_KEYS = {
    "uid",
    "condition",
    "policy",
    "low_policy",
    "high_policy",
    "correct",
    "em",
    "f1",
    "transition",
    "direct_transition",
    "sample_role",
    "candidate_a_policy",
    "candidate_b_policy",
    "p1",
    "official",
}


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _write_csv(path: Path, fieldnames: list[str], ids: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for blind_id in ids:
            writer.writerow({"blind_id": blind_id})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _latest_raw(path: Path) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in _jsonl(path):
        latest[row["uid"]] = row
    return latest


def _load_contexts(gold_path: Path) -> dict[str, dict[str, Any]]:
    contexts: dict[str, dict[str, Any]] = {}
    for context in json.loads(gold_path.read_text(encoding="utf-8")):
        table = (context.get("table") or {}).get("table", [])
        paragraphs = [
            {"order": paragraph.get("order"), "text": paragraph.get("text", "")}
            for paragraph in context.get("paragraphs", [])
        ]
        for question in context.get("questions", []):
            contexts[question["uid"]] = {
                "question": question.get("question", ""),
                "table": table,
                "paragraphs": paragraphs,
                "gold_answer": question.get("answer"),
                "gold_scale": question.get("scale", ""),
                "answer_type": question.get("answer_type", ""),
                "scale_present": bool(question.get("scale", "")),
            }
    return contexts


def _load_exact(path: Path) -> tuple[dict[tuple[str, str], dict[str, Any]], list[str]]:
    rows = _jsonl(path)
    lookup = {(row["uid"], row["policy"]): row for row in rows}
    policy_order = list(dict.fromkeys(row["policy"] for row in rows))
    return lookup, policy_order


def _prediction_parts(path: Path) -> dict[str, dict[str, Any]]:
    predictions = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for uid, value in predictions.items():
        answer, scale = value if isinstance(value, list) and len(value) == 2 else (None, "")
        if answer is None:
            spans: list[str] = []
        elif isinstance(answer, list):
            spans = [str(item) for item in answer]
        else:
            spans = [str(answer)]
        result[uid] = {"answer": spans, "scale": str(scale or "")}
    return result


def _stratified_controls(
    candidates: list[dict[str, Any]],
    n: int,
    rng: random.Random,
) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        buckets[(candidate["answer_type"], candidate["scale_present"])].append(candidate)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while len(selected) < n:
        progressed = False
        for key in keys:
            if buckets[key] and len(selected) < n:
                selected.append(buckets[key].pop())
                progressed = True
        if not progressed:
            break
    return selected


def _randomized_candidates(
    first: str,
    second: str,
    first_policy: str,
    second_policy: str,
    rng: random.Random,
) -> tuple[dict[str, str], dict[str, str]]:
    if rng.randrange(2):
        return (
            {"candidate_a": second, "candidate_b": first},
            {"candidate_a_policy": second_policy, "candidate_b_policy": first_policy},
        )
    return (
        {"candidate_a": first, "candidate_b": second},
        {"candidate_a_policy": first_policy, "candidate_b_policy": second_policy},
    )


def _review_context(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "question": context["question"],
        "table": context["table"],
        "paragraphs": context["paragraphs"],
    }


def _reviewer_codebook() -> str:
    return """# Blind audit codebook

Do not open the sibling `private/` directory until all reviewer labels are frozen.
Complete Pass 1 before opening Pass 2. Records are randomized, and Candidate A/B
order is independently randomized per record.

This is condition-blind, not a claim of perfect concealment: the response surface
may itself reveal whether a structured format was used. Do not infer provenance or
evaluation outcomes from formatting.

## Pass 1 — intent extraction

Use only `pass1_intent.jsonl`. Record the answer the response actually asserts;
do not repair it using the table, recompute a missing answer, or consult Pass 2.

- `asserted_answer`: verbatim or minimally normalized final answer.
- `asserted_scale`: none/percent/hundred/thousand/million/billion/other.
- `asserted_sign`: positive/negative/magnitude_only/unclear/not_applicable.
- `answer_location`: short supporting excerpt or structural location.
- `single_final_answer`: yes/no/unclear.
- `ambiguity`: none/minor/material.
- `recomputation_required`: yes/no; yes means the label cannot be obtained by
  faithful extraction alone.
- `confidence`: high/medium/low.

## Pass 2 — extraction and scoring adjudication

Only after Pass 1 is frozen, use `pass2_adjudication.jsonl`. Compare the frozen
response, extracted answer, gold annotation, and the two anonymized canonical
candidates. Candidate identity is randomized independently for every record.

- `extraction_faithful`: exact/plausible/unfaithful/ambiguous.
- `more_faithful_candidate`: A/B/both/neither/unclear.
- `benchmark_correct_candidate`: A/B/both/neither/unclear.
- `semantic_transformation_justified`: yes/no/unclear/not_applicable.
- `error_source`: generation/extraction/scoring/gold/none/ambiguous.
- `confidence`: high/medium/low.

## Mechanism-edge audit

`mechanism_edges.jsonl` contains only cases whose decision changes across an
adjacent hidden policy edge. Judge the candidates without guessing which policy
produced them. Duplicate questions can occur because one response may move at
more than one edge.
"""


def assert_reviewer_blind(reviewer_dir: Path) -> dict[str, Any]:
    violations: list[dict[str, str]] = []

    def forbidden_keys(value: Any) -> set[str]:
        found: set[str] = set()
        if isinstance(value, dict):
            found.update(set(value) & _FORBIDDEN_REVIEWER_KEYS)
            for child in value.values():
                found.update(forbidden_keys(child))
        elif isinstance(value, list):
            for child in value:
                found.update(forbidden_keys(child))
        return found

    for path in sorted(reviewer_dir.iterdir()):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        uuid_match = _UUID_RE.search(text)
        if uuid_match:
            violations.append({"file": path.name, "reason": f"UUID leak: {uuid_match.group(0)}"})
        lowered = text.lower()
        for forbidden in _FORBIDDEN_REVIEWER_TEXT:
            if forbidden.lower() in lowered:
                violations.append({"file": path.name, "reason": f"label leak: {forbidden}"})
        if path.suffix == ".jsonl":
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                leaked_keys = forbidden_keys(json.loads(line))
                if leaked_keys:
                    violations.append(
                        {
                            "file": path.name,
                            "reason": f"private keys at line {line_number}: {sorted(leaked_keys)}",
                        }
                    )
        elif path.suffix == ".json":
            leaked_keys = forbidden_keys(json.loads(text))
            if leaked_keys:
                violations.append({"file": path.name, "reason": f"private keys: {sorted(leaked_keys)}"})
    if violations:
        raise ValueError(f"reviewer package leaks private labels: {violations[:5]}")
    return {"files_checked": len([path for path in reviewer_dir.iterdir() if path.is_file()]), "violations": 0}


def build_blind_audit_package(
    run_dir: str | Path,
    gold_path: str | Path,
    out_dir: str | Path,
    *,
    seed: int = 20260814,
    controls_per_cell: int = 20,
) -> dict[str, Any]:
    run = Path(run_dir)
    gold = Path(gold_path)
    out = Path(out_dir)
    reviewer_dir = out / "reviewer"
    private_dir = out / "private"
    reviewer_dir.mkdir(parents=True, exist_ok=True)
    private_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    contexts = _load_contexts(gold)

    condition_data: dict[str, dict[str, Any]] = {}
    all_direct: list[dict[str, Any]] = []
    changed_uids: set[str] = set()
    mechanism_records: list[dict[str, Any]] = []
    source_hashes: dict[str, str] = {str(gold.resolve()): _sha256(gold)}

    for config in PRIMARY_CONDITIONS:
        exact_path = run / config["exact_dir"] / "exact_items.jsonl"
        prediction_path = run / config["predictions"]
        raw_path = run / config["raw"]
        for source in (exact_path, prediction_path, raw_path):
            if not source.exists():
                raise FileNotFoundError(source)
            source_hashes[str(source.resolve())] = _sha256(source)
        lookup, policies = _load_exact(exact_path)
        predictions = _prediction_parts(prediction_path)
        raw = _latest_raw(raw_path)
        uids = sorted(uid for uid, policy in lookup if policy == "exact_official")
        condition_data[config["label"]] = {
            "lookup": lookup,
            "policies": policies,
            "predictions": predictions,
            "raw": raw,
        }
        for uid in uids:
            p1 = lookup[(uid, "exact_p1_syntax")]
            official = lookup[(uid, "exact_official")]
            context = contexts[uid]
            response = raw.get(uid, {})
            prediction = predictions.get(uid, {"answer": [], "scale": ""})
            changed = p1["correct"] != official["correct"]
            record = {
                "condition": config["label"],
                "uid": uid,
                "answer_type": context["answer_type"],
                "scale_present": context["scale_present"],
                "p1": p1,
                "official": official,
                "response": response.get("raw", ""),
                "response_status": response.get("status", "missing"),
                "prediction": prediction,
                "changed": changed,
                "stable_outcome": None if changed else int(p1["correct"]),
            }
            all_direct.append(record)
            if changed:
                changed_uids.add(uid)

            for low, high in zip(policies, policies[1:]):
                low_row = lookup[(uid, low)]
                high_row = lookup[(uid, high)]
                if low_row["correct"] == high_row["correct"]:
                    continue
                mechanism_records.append(
                    {
                        **record,
                        "low_policy": low,
                        "high_policy": high,
                        "low": low_row,
                        "high": high_row,
                    }
                )

    selected = [record for record in all_direct if record["changed"]]
    used_control_uids: set[str] = set(changed_uids)
    control_counts: Counter[str] = Counter()
    for config in PRIMARY_CONDITIONS:
        label = config["label"]
        for outcome in (1, 0):
            candidates = [
                record
                for record in all_direct
                if record["condition"] == label
                and record["stable_outcome"] == outcome
                and record["uid"] not in used_control_uids
                and record["response_status"] == "ok"
                and bool(record["response"].strip())
                and bool(record["prediction"]["answer"])
            ]
            controls = _stratified_controls(candidates, controls_per_cell, rng)
            if len(controls) < controls_per_cell:
                fallback = [
                    record
                    for record in all_direct
                    if record["condition"] == label
                    and record["stable_outcome"] == outcome
                    and record not in controls
                    and record["response_status"] == "ok"
                    and bool(record["response"].strip())
                    and bool(record["prediction"]["answer"])
                ]
                controls.extend(_stratified_controls(fallback, controls_per_cell - len(controls), rng))
            selected.extend(controls)
            used_control_uids.update(record["uid"] for record in controls)
            control_counts[f"{label}:{outcome}"] = len(controls)

    rng.shuffle(selected)
    pass1_rows: list[dict[str, Any]] = []
    pass2_rows: list[dict[str, Any]] = []
    private_rows: list[dict[str, Any]] = []
    for index, record in enumerate(selected, 1):
        blind_id = f"B{index:04d}"
        context = contexts[record["uid"]]
        candidates, candidate_key = _randomized_candidates(
            record["p1"]["pred_canonical"],
            record["official"]["pred_canonical"],
            "exact_p1_syntax",
            "exact_official",
            rng,
        )
        common = {
            "blind_id": blind_id,
            **_review_context(context),
            "model_response": record["response"],
        }
        pass1_rows.append(common)
        pass2_rows.append(
            {
                **common,
                "extracted_answer": record["prediction"]["answer"],
                "extracted_scale": record["prediction"]["scale"],
                "gold_answer": context["gold_answer"],
                "gold_scale": context["gold_scale"],
                **candidates,
            }
        )
        private_rows.append(
            {
                "blind_id": blind_id,
                "uid": record["uid"],
                "condition": record["condition"],
                "sample_role": "direct_change"
                if record["changed"]
                else f"stable_{record['stable_outcome']}",
                "direct_transition": f"{int(record['p1']['correct'])}->{int(record['official']['correct'])}",
                **candidate_key,
                "p1": record["p1"],
                "official": record["official"],
            }
        )

    rng.shuffle(mechanism_records)
    mechanism_rows: list[dict[str, Any]] = []
    mechanism_key: list[dict[str, Any]] = []
    for index, record in enumerate(mechanism_records, 1):
        blind_id = f"M{index:04d}"
        context = contexts[record["uid"]]
        candidates, candidate_key = _randomized_candidates(
            record["low"]["pred_canonical"],
            record["high"]["pred_canonical"],
            record["low_policy"],
            record["high_policy"],
            rng,
        )
        mechanism_rows.append(
            {
                "blind_id": blind_id,
                **_review_context(context),
                "model_response": record["response"],
                "extracted_answer": record["prediction"]["answer"],
                "extracted_scale": record["prediction"]["scale"],
                "gold_answer": context["gold_answer"],
                "gold_scale": context["gold_scale"],
                **candidates,
            }
        )
        mechanism_key.append(
            {
                "blind_id": blind_id,
                "uid": record["uid"],
                "condition": record["condition"],
                "transition": f"{int(record['low']['correct'])}->{int(record['high']['correct'])}",
                "low_policy": record["low_policy"],
                "high_policy": record["high_policy"],
                **candidate_key,
                "low": record["low"],
                "high": record["high"],
            }
        )

    pass1_path = reviewer_dir / "pass1_intent.jsonl"
    pass2_path = reviewer_dir / "pass2_adjudication.jsonl"
    mechanism_path = reviewer_dir / "mechanism_edges.jsonl"
    _write_jsonl(pass1_path, pass1_rows)
    _write_jsonl(pass2_path, pass2_rows)
    _write_jsonl(mechanism_path, mechanism_rows)
    _write_csv(
        reviewer_dir / "pass1_labels.csv",
        [
            "blind_id",
            "asserted_answer",
            "asserted_scale",
            "asserted_sign",
            "answer_location",
            "single_final_answer",
            "ambiguity",
            "recomputation_required",
            "confidence",
            "reviewer_notes",
        ],
        [row["blind_id"] for row in pass1_rows],
    )
    _write_csv(
        reviewer_dir / "pass2_labels.csv",
        [
            "blind_id",
            "extraction_faithful",
            "more_faithful_candidate",
            "benchmark_correct_candidate",
            "semantic_transformation_justified",
            "error_source",
            "confidence",
            "reviewer_notes",
        ],
        [row["blind_id"] for row in pass2_rows],
    )
    _write_csv(
        reviewer_dir / "mechanism_labels.csv",
        [
            "blind_id",
            "more_faithful_candidate",
            "benchmark_correct_candidate",
            "semantic_transformation_justified",
            "decision_change_justified",
            "error_source",
            "confidence",
            "reviewer_notes",
        ],
        [row["blind_id"] for row in mechanism_rows],
    )
    (reviewer_dir / "CODEBOOK.md").write_text(_reviewer_codebook(), encoding="utf-8")
    _write_jsonl(private_dir / "direct_key.jsonl", private_rows)
    _write_jsonl(private_dir / "mechanism_key.jsonl", mechanism_key)

    reviewer_hashes = {
        path.name: _sha256(path)
        for path in sorted(reviewer_dir.iterdir())
        if path.is_file() and path.name != "MANIFEST.json"
    }
    summary = {
        "version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": seed,
        "controls_per_condition_outcome": controls_per_cell,
        "counts": {
            "pass1_pass2_records": len(selected),
            "direct_changed": sum(record["changed"] for record in selected),
            "stable_controls": sum(not record["changed"] for record in selected),
            "stable_correct_controls": sum(
                count for cell, count in control_counts.items() if cell.endswith(":1")
            ),
            "stable_wrong_controls": sum(
                count for cell, count in control_counts.items() if cell.endswith(":0")
            ),
            "mechanism_edges": len(mechanism_records),
            "mechanism_transitions": dict(
                Counter(
                    f"{int(record['low']['correct'])}->{int(record['high']['correct'])}"
                    for record in mechanism_records
                )
            ),
        },
        "blind_check": {"files_checked": 0, "violations": 0},
        "reviewer_sha256": reviewer_hashes,
    }
    (reviewer_dir / "MANIFEST.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary["blind_check"] = assert_reviewer_blind(reviewer_dir)
    (reviewer_dir / "MANIFEST.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    private_manifest = {
        **summary,
        "conditions": list(PRIMARY_CONDITIONS),
        "private_control_cells": dict(control_counts),
        "source_sha256": source_hashes,
        "warning": "Do not expose this directory to reviewers before labels are frozen.",
    }
    (private_dir / "MANIFEST_PRIVATE.json").write_text(
        json.dumps(private_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary
