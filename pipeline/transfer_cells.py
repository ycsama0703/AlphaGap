"""Fin-first transfer cells and AI evidence linking.

The formal gap-detection taxonomy is maintained in
``knowledge/fin_fields/transfer_cells.yaml``. AI evidence can support an
existing cell or be retained as a candidate extension, but it cannot create a
new active research direction automatically.
"""
from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime
from pathlib import Path

import yaml

from . import db
from .config import PROJECT_ROOT
from .llm_client import LLMClient


log = logging.getLogger(__name__)

TRANSFER_CELLS_PATH = PROJECT_ROOT / "knowledge" / "fin_fields" / "transfer_cells.yaml"
TRANSFER_EVAL_PATH = PROJECT_ROOT / "knowledge" / "fin_fields" / "transfer_cell_eval.yaml"

_EVIDENCE_AUDIT_SYSTEM = """\
You are the strict evidence auditor for AlphaGap. The formal taxonomy is a
human-maintained list of finance transfer cells. You may attach an AI paper to
one or more existing cells, suggest a candidate extension for later human
review, or reject it. You must never create or activate a new cell.

A "support" decision requires all of the following:
1. The paper provides a reusable technical intervention, not merely a topic,
   benchmark, dataset, domain analogy, or theory result.
2. The paper demonstrates the intervention in its native AI task, and the
   selected finance cell exposes the same operational control point or failure
   branch. The paper is not required to contain financial data; this auditor
   exists to judge AI-to-finance transfer.
3. The proposed financial bridge is implementable using the selected cell's
   experiment anchor:
   data_object, primary_metric, baseline, and failure_mode must each remain
   meaningful after the intervention is applied.
4. In the mapped financial experiment, the intervention would detect, reduce,
   or control a named branch of that failure mode, rather than merely using
   similar mathematical vocabulary.
5. The paper's intervention and the selected cell's ai_intervention_class
   must perform the same operation. Do not reframe an evaluation metric as a
   representation-learning method, a benchmark as a verification mechanism,
   or a general analogy as an intervention. If an adjacent but different
   intervention appears valuable, use candidate_extension.

Use "candidate_extension" only when an intervention is concrete and plausibly
valuable but no supplied active cell expresses its experiment. These items are
for human review and cannot feed daily gap generation. A candidate extension
may address the same broad bottleneck as an active cell when it introduces a
different operation and therefore a different baseline or failure-control
experiment; do not reject it merely because a nearby cell exists. A concrete
generic AI intervention such as memory updating, robustness control, or
training-time augmentation may be a candidate even when the original paper
does not use finance data, provided a financial experiment can be specified.
Use "reject" for distant analogy, missing experimental fit, a benchmark with
no intervention, or a task-specific mechanism with no operationally equivalent
financial anchor.

Be particularly strict with attractive near-matches:
- A training environment or general agent workflow optimizer does not support
  a trace-audit cell unless it actually detects or blocks incorrect trace
  actions; improving planning or retrieval quality alone is not an audit.
- A generic predictive architecture does not support pricing or factor cells
  unless its intervention controls the named financial failure mode.
- Internal-activation hallucination diagnosis is not external-source citation
  or timestamp verification unless a cell explicitly includes that operation.
- A domain-specific use of words such as retrieval, constraints, agents,
  causality, robustness, or diversity is not by itself a transfer.
- A general AI intervention may support more than one finance cell when it
  independently satisfies every rule for each cell. Return no more than three
  support links and do not force a single "best" cell across distinct fields.

Return strict JSON only:
{
  "verdict": "support" | "candidate_extension" | "reject",
  "supported_cells": [
    {
      "cell_id": <active cell id>,
      "confidence": <number from 0 to 1>,
      "bridge_claim": <one concrete sentence>,
      "experiment_fit": {
        "data_object": <how the intervention applies to this cell>,
        "primary_metric": <what changes in evaluation>,
        "baseline": <comparison affected by the intervention>,
        "failure_mode": <failure the intervention detects or reduces>
      }
    }
  ],
  "proposed_extension": {
    "field_id": <string or "">,
    "bottleneck": <string or "">,
    "intervention_class": <string or "">,
    "required_experiment_anchor": <string or "">
  },
  "rationale": <brief critical explanation>
}
"""

_SUPPORT_CONFIRM_SYSTEM = """\
You are the conservative confirmation reviewer for AlphaGap automatic evidence
links. Another auditor proposed one or more AI-paper-to-finance-cell support
links. You may only confirm or reject those proposed links; you may not propose
new cells or substitute nearby cells.

Confirm a link only if the paper's actual intervention performs the same
operation as the cell's ai_intervention_class and the supplied experiment fit
is a defensible instantiation of the cell's anchor. Reject a nearby-but-
different method, a generic architecture, a domain keyword analogy, or an
experiment fit that invents capability the paper did not demonstrate.
The paper is not required to have run on financial data: changing the native
data object to the cell's financial data object is the purpose of transfer and
is allowed when the intervention and controlled failure branch remain the
same. It is sufficient for an intervention to control one explicitly named
branch of a compound cell failure mode; it need not solve every branch.
When uncertain, reject the automatic support link; it can remain for later
human review as a candidate extension.

Return strict JSON only:
{
  "accepted_cell_ids": [<zero or more proposed cell ids>],
  "rationale": <brief critical explanation>
}
"""


def load_cell_specs(path: Path | None = None) -> list[dict]:
    """Load the human-reviewed transfer-cell asset."""
    selected = path or TRANSFER_CELLS_PATH
    raw = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    cells = raw.get("cells") or []
    required = {
        "cell_id", "field_id", "mechanism_family", "bottleneck",
        "ai_intervention_class", "experiment_anchor",
    }
    result = []
    for cell in cells:
        missing = required - set(cell)
        if missing:
            raise ValueError(f"transfer cell {cell.get('cell_id')} missing {sorted(missing)}")
        normalized = dict(cell)
        normalized.setdefault("status", "active")
        normalized["_source_path"] = str(selected)
        result.append(normalized)
    return result


def seed_cells(path: Path | None = None) -> dict:
    """Upsert the structured taxonomy into the selected database."""
    db.init_schema()
    specs = load_cell_specs(path)
    now = datetime.now().isoformat(timespec="seconds")
    inserted = 0
    with db.connect() as conn:
        for cell in specs:
            existed = conn.execute(
                "SELECT 1 FROM fin_transfer_cells WHERE cell_id = ?",
                (cell["cell_id"],),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO fin_transfer_cells
                    (cell_id, field_id, mechanism_family, bottleneck,
                     ai_intervention_class, experiment_anchor_json, status,
                     source_path, created_at, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cell_id) DO UPDATE SET
                    field_id = excluded.field_id,
                    mechanism_family = excluded.mechanism_family,
                    bottleneck = excluded.bottleneck,
                    ai_intervention_class = excluded.ai_intervention_class,
                    experiment_anchor_json = excluded.experiment_anchor_json,
                    status = excluded.status,
                    source_path = excluded.source_path,
                    last_updated = excluded.last_updated
                """,
                (
                    cell["cell_id"],
                    cell["field_id"],
                    cell["mechanism_family"],
                    cell["bottleneck"],
                    cell["ai_intervention_class"],
                    json.dumps(cell["experiment_anchor"], ensure_ascii=False),
                    cell["status"],
                    cell["_source_path"],
                    now,
                    now,
                ),
            )
            inserted += 0 if existed else 1
    return {"cells_total": len(specs), "inserted": inserted, "updated": len(specs) - inserted}


def load_active_cells(conn=None) -> list[dict]:
    """Load active cells from DB in prompt-ready form."""
    own_conn = conn is None
    if own_conn:
        ctx = db.connect()
        conn = ctx.__enter__()
    try:
        rows = conn.execute(
            """
            SELECT cell_id, field_id, mechanism_family, bottleneck,
                   ai_intervention_class, experiment_anchor_json
            FROM fin_transfer_cells
            WHERE status = 'active'
            ORDER BY field_id, cell_id
            """
        ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["experiment_anchor"] = json.loads(item.pop("experiment_anchor_json"))
            out.append(item)
        return out
    finally:
        if own_conn:
            ctx.__exit__(None, None, None)


def cells_for_prompt(field_ids: set[str] | None = None) -> list[dict]:
    """Load the YAML asset for daily prompts without requiring seeded DB state."""
    cells = load_cell_specs()
    return [
        {k: v for k, v in cell.items() if not k.startswith("_")}
        for cell in cells
        if cell.get("status") == "active"
        and (not field_ids or cell["field_id"] in field_ids)
    ]


def load_evaluation_cases(path: Path | None = None) -> list[dict]:
    """Load a manually curated acceptance set for the evidence auditor."""
    selected = path or TRANSFER_EVAL_PATH
    raw = yaml.safe_load(selected.read_text(encoding="utf-8")) or {}
    cases = raw.get("cases") or []
    allowed_verdicts = {"support", "candidate_extension", "reject"}
    for case in cases:
        missing = {"paper_id", "title", "expected_verdict", "rationale"} - set(case)
        if missing:
            raise ValueError(f"evaluation case missing {sorted(missing)}: {case.get('paper_id')}")
        if case["expected_verdict"] not in allowed_verdicts:
            raise ValueError(f"invalid expected verdict for {case['paper_id']}")
        if case["expected_verdict"] == "support" and not case.get("expected_cell_id"):
            raise ValueError(f"support case requires expected_cell_id: {case['paper_id']}")
    return cases


def _audit_user(paper_id: str, mechanism: dict, cells: list[dict]) -> str:
    return "\n".join([
        f"## AI evidence paper id={paper_id}",
        json.dumps(mechanism, ensure_ascii=False, indent=2),
        "",
        "## Active finance transfer cells",
        json.dumps(cells, ensure_ascii=False, indent=2),
        "",
        "Choose support, candidate_extension, or reject. Return JSON only.",
    ])


def _normalize_fit(value: object) -> dict:
    value = value if isinstance(value, dict) else {}
    return {
        key: str(value.get(key) or "").strip()
        for key in ("data_object", "primary_metric", "baseline", "failure_mode")
    }


def judge_evidence(
    paper_id: str,
    mechanism: dict,
    cells: list[dict],
    *,
    llm: LLMClient | None = None,
) -> dict:
    """Classify evidence against supplied cells without writing database state."""
    llm = llm or LLMClient()
    valid_cell_ids = {cell["cell_id"] for cell in cells}
    raw = llm.chat_json(
        _EVIDENCE_AUDIT_SYSTEM,
        _audit_user(paper_id, mechanism, cells),
        temperature=0.0,
        reasoning=True,
    )
    support_links = []
    seen_cell_ids = set()
    raw_supported_cells = raw.get("supported_cells")
    if isinstance(raw_supported_cells, list):
        for link in raw_supported_cells[:3]:
            if not isinstance(link, dict):
                continue
            cell_id = str(link.get("cell_id") or "").strip() or None
            fit = _normalize_fit(link.get("experiment_fit"))
            confidence = max(0.0, min(float(link.get("confidence") or 0.0), 1.0))
            if (
                cell_id in valid_cell_ids
                and cell_id not in seen_cell_ids
                and confidence >= 0.75
                and all(fit.values())
            ):
                support_links.append({
                    "cell_id": cell_id,
                    "confidence": confidence,
                    "bridge_claim": str(link.get("bridge_claim") or "").strip(),
                    "experiment_fit": fit,
                })
                seen_cell_ids.add(cell_id)
        if support_links:
            return {
                "action": "support",
                "cell_id": support_links[0]["cell_id"],
                "cell_ids": [link["cell_id"] for link in support_links],
                "support_links": support_links,
                "confidence": support_links[0]["confidence"],
                "bridge_claim": support_links[0]["bridge_claim"],
                "experiment_fit": support_links[0]["experiment_fit"],
                "proposed_extension": {},
                "rationale": str(raw.get("rationale") or "").strip(),
            }
    verdict = str(raw.get("verdict") or "reject").strip().lower()
    if verdict not in {"support", "candidate_extension", "reject"}:
        verdict = "reject"
    selected_cell = str(raw.get("selected_cell_id") or "").strip() or None
    fit = _normalize_fit(raw.get("experiment_fit"))
    confidence = max(0.0, min(float(raw.get("confidence") or 0.0), 1.0))
    complete_fit = all(fit.values())
    if verdict == "support" and (
        selected_cell not in valid_cell_ids or confidence < 0.75 or not complete_fit
    ):
        verdict = "candidate_extension" if selected_cell in valid_cell_ids else "reject"
    if selected_cell not in valid_cell_ids:
        selected_cell = None
    proposed_extension = raw.get("proposed_extension")
    if not isinstance(proposed_extension, dict):
        proposed_extension = {}
    return {
        "action": verdict,
        "cell_id": selected_cell,
        "cell_ids": [selected_cell] if selected_cell and verdict == "support" else [],
        "support_links": [],
        "confidence": confidence,
        "bridge_claim": str(raw.get("bridge_claim") or "").strip(),
        "experiment_fit": fit,
        "proposed_extension": proposed_extension,
        "rationale": str(raw.get("rationale") or "").strip(),
    }


def confirm_support_links(
    paper_id: str,
    mechanism: dict,
    cells: list[dict],
    decision: dict,
    *,
    llm: LLMClient | None = None,
) -> dict:
    """Require a second, narrowly scoped review before automatic support."""
    if decision["action"] != "support":
        return decision
    llm = llm or LLMClient()
    proposed_links = decision["support_links"] or [{
        "cell_id": decision["cell_id"],
        "confidence": decision["confidence"],
        "bridge_claim": decision["bridge_claim"],
        "experiment_fit": decision["experiment_fit"],
    }]
    proposed_ids = {link["cell_id"] for link in proposed_links if link.get("cell_id")}
    proposed_cells = [cell for cell in cells if cell["cell_id"] in proposed_ids]
    user = "\n".join([
        f"## AI evidence paper id={paper_id}",
        json.dumps(mechanism, ensure_ascii=False, indent=2),
        "",
        "## Proposed automatic support links",
        json.dumps(proposed_links, ensure_ascii=False, indent=2),
        "",
        "## Proposed target cell definitions",
        json.dumps(proposed_cells, ensure_ascii=False, indent=2),
        "",
        "Confirm only operationally identical support links. Return JSON only.",
    ])
    raw = llm.chat_json(
        _SUPPORT_CONFIRM_SYSTEM,
        user,
        temperature=0.0,
        reasoning=True,
    )
    accepted = {
        str(cell_id).strip()
        for cell_id in (raw.get("accepted_cell_ids") or [])
        if str(cell_id).strip() in proposed_ids
    }
    confirmed_links = [link for link in proposed_links if link["cell_id"] in accepted]
    confirmation_rationale = str(raw.get("rationale") or "").strip()
    if not confirmed_links:
        return {
            "action": "candidate_extension",
            "cell_id": None,
            "cell_ids": [],
            "support_links": [],
            "confidence": decision["confidence"],
            "bridge_claim": "",
            "experiment_fit": _normalize_fit({}),
            "proposed_extension": {},
            "rationale": f"Automatic support unconfirmed: {confirmation_rationale or decision['rationale']}",
        }
    result = dict(decision)
    result.update({
        "cell_id": confirmed_links[0]["cell_id"],
        "cell_ids": [link["cell_id"] for link in confirmed_links],
        "support_links": confirmed_links,
        "confidence": confirmed_links[0]["confidence"],
        "bridge_claim": confirmed_links[0]["bridge_claim"],
        "experiment_fit": confirmed_links[0]["experiment_fit"],
        "rationale": f"{decision['rationale']} Confirmation: {confirmation_rationale}".strip(),
    })
    return result


def stage_support_for_human_review(decision: dict) -> dict:
    """Prevent confirmed links from becoming automatic evidence before sign-off."""
    if decision["action"] != "support":
        return decision
    result = dict(decision)
    result.update({
        "action": "candidate_extension",
        "cell_ids": [],
        "rationale": (
            "Automatic support disabled pending acceptance-gate sign-off. "
            f"Confirmed candidate links retained for review. {decision['rationale']}"
        ),
    })
    return result


def audit_evidence(
    paper_id: str,
    mechanism: dict,
    *,
    llm: LLMClient | None = None,
    confirm_support: bool = True,
    allow_automatic_support: bool = False,
) -> dict:
    """Audit one AI paper against fixed active cells and persist its decision."""
    llm = llm or LLMClient()
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT verdict, selected_cell_id, supported_cell_ids_json FROM ai_evidence_decisions WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
        if existing:
            return {"action": "already-reviewed", **dict(existing)}
        cells = load_active_cells(conn)
        if not cells:
            return {"action": "error", "reason": "no active fin transfer cells seeded"}
        decision = judge_evidence(paper_id, mechanism, cells, llm=llm)
        if confirm_support:
            decision = confirm_support_links(paper_id, mechanism, cells, decision, llm=llm)
        if not allow_automatic_support:
            decision = stage_support_for_human_review(decision)
        verdict = decision["action"]
        selected_cell = decision["cell_id"]
        fit = decision["experiment_fit"]
        confidence = decision["confidence"]
        proposed_extension = decision["proposed_extension"]
        supported_cell_ids = decision["cell_ids"]
        candidate_cell_ids = (
            [link["cell_id"] for link in decision["support_links"]]
            if verdict == "candidate_extension" else []
        )
        now = datetime.now().isoformat(timespec="seconds")
        rationale = decision["rationale"]
        bridge_claim = decision["bridge_claim"]
        conn.execute(
            """
            INSERT INTO ai_evidence_decisions
                (paper_id, verdict, selected_cell_id, supported_cell_ids_json, candidate_cell_ids_json,
                 bridge_claim, experiment_fit_json, proposed_extension_json,
                 rationale, assessed_at, assessed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'llm-cell-auditor-v2')
            """,
            (
                paper_id,
                verdict,
                selected_cell,
                json.dumps(supported_cell_ids, ensure_ascii=False),
                json.dumps(candidate_cell_ids, ensure_ascii=False),
                bridge_claim,
                json.dumps(fit, ensure_ascii=False),
                json.dumps(proposed_extension, ensure_ascii=False),
                rationale,
                now,
            ),
        )
        links = decision["support_links"] or ([{
            "cell_id": selected_cell,
            "confidence": confidence,
            "bridge_claim": bridge_claim,
            "experiment_fit": fit,
        }] if selected_cell and verdict in {"support", "candidate_extension"} else [])
        for link in links:
            conn.execute(
                """
                INSERT INTO ai_evidence_links
                    (paper_id, cell_id, verdict, confidence, bridge_claim,
                     experiment_fit_json, review_reason, assessed_at, assessed_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'llm-cell-auditor-v2')
                """,
                (
                    paper_id,
                    link["cell_id"],
                    "support" if verdict == "support" else "candidate",
                    link["confidence"],
                    link["bridge_claim"],
                    json.dumps(link["experiment_fit"], ensure_ascii=False),
                    rationale,
                    now,
                ),
            )
    return decision


def link_pending(
    limit: int = 50,
    *,
    evidence_only: bool = True,
    allow_automatic_support: bool = False,
) -> dict:
    """Link previously extracted AI evidence to the fixed cell taxonomy."""
    seed = seed_cells()
    evidence_clause = """
              AND EXISTS (
                  SELECT 1 FROM paper_sources ps
                  WHERE ps.paper_id = p.id AND ps.role = 'evidence'
              )
    """ if evidence_only else ""
    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, e.mechanism_description_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN ai_evidence_decisions d ON d.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.side = 'ai'
              AND e.extraction_status IN ('l1_done', 'l2_done')
              AND e.mechanism_description_json IS NOT NULL
              AND e.mechanism_description_json NOT IN ('', '{{}}')
              AND d.paper_id IS NULL
              {evidence_clause}
            ORDER BY COALESCE(s.priority_score, 0) DESC, p.id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    stats = {
        "cells": seed,
        "processed": 0,
        "by_action": {},
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
    }
    if not rows:
        return stats
    llm = LLMClient()
    for row in rows:
        mechanism = json.loads(row["mechanism_description_json"] or "{}")
        mechanism["paper_title"] = row["title"]
        result = audit_evidence(
            row["id"],
            mechanism,
            llm=llm,
            allow_automatic_support=allow_automatic_support,
        )
        action = result.get("action", "error")
        stats["processed"] += 1
        stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
        if stats["processed"] % 10 == 0:
            log.info("transfer cell linking progress: %d / %d", stats["processed"], len(rows))
    stats["tokens_in"], stats["tokens_out"] = llm.total_tokens
    stats["cost_usd"] = round(llm.estimate_cost_usd(), 6)
    return stats


def evaluate_benchmark(
    *,
    path: Path | None = None,
    cases: list[dict] | None = None,
    limit: int | None = None,
    llm: LLMClient | None = None,
    confirm_support: bool = True,
) -> dict:
    """Run the auditor on curated cases without persisting decisions or links."""
    selected_cases = list(cases if cases is not None else load_evaluation_cases(path))
    if limit is not None:
        selected_cases = selected_cases[:limit]
    cells = cells_for_prompt()
    llm = llm or LLMClient()
    results = []
    missing = []
    with db.connect() as conn:
        for case in selected_cases:
            row = conn.execute(
                """
                SELECT p.title, e.mechanism_description_json
                FROM papers p
                JOIN paper_extractions e ON e.paper_id = p.id
                WHERE p.id = ? AND e.side = 'ai'
                """,
                (case["paper_id"],),
            ).fetchone()
            if not row:
                missing.append(case["paper_id"])
                continue
            mechanism = json.loads(row["mechanism_description_json"] or "{}")
            mechanism["paper_title"] = row["title"]
            actual = judge_evidence(case["paper_id"], mechanism, cells, llm=llm)
            if confirm_support:
                actual = confirm_support_links(
                    case["paper_id"], mechanism, cells, actual, llm=llm
                )
            verdict_ok = actual["action"] == case["expected_verdict"]
            cell_ok = (
                case.get("expected_cell_id") in actual["cell_ids"]
                if case["expected_verdict"] == "support"
                else True
            )
            results.append({
                "paper_id": case["paper_id"],
                "title": row["title"],
                "difficulty": case.get("difficulty", ""),
                "expected_verdict": case["expected_verdict"],
                "expected_cell_id": case.get("expected_cell_id"),
                "actual_verdict": actual["action"],
                "actual_cell_id": actual["cell_id"],
                "actual_cell_ids": actual["cell_ids"],
                "verdict_ok": verdict_ok,
                "cell_ok": cell_ok,
                "rationale": actual["rationale"],
            })
            if len(results) % 10 == 0:
                log.info(
                    "transfer cell evaluation progress: %d / %d",
                    len(results),
                    len(selected_cases),
                )
    evaluated = len(results)
    expected_supports = [r for r in results if r["expected_verdict"] == "support"]
    predicted_supports = [r for r in results if r["actual_verdict"] == "support"]
    correct_verdicts = sum(1 for r in results if r["verdict_ok"])
    correct_support_cells = sum(1 for r in expected_supports if r["verdict_ok"] and r["cell_ok"])
    correct_predicted_supports = sum(
        1 for r in predicted_supports
        if r["expected_verdict"] == "support" and r["cell_ok"]
    )
    confusion: dict[str, dict[str, int]] = {}
    for row in results:
        confusion.setdefault(row["expected_verdict"], {})
        confusion[row["expected_verdict"]][row["actual_verdict"]] = (
            confusion[row["expected_verdict"]].get(row["actual_verdict"], 0) + 1
        )
    tokens_in, tokens_out = getattr(llm, "total_tokens", (0, 0))
    return {
        "dataset": str(path or TRANSFER_EVAL_PATH) if cases is None else "<provided-cases>",
        "cases_requested": len(selected_cases),
        "evaluated": evaluated,
        "missing": missing,
        "expected_counts": {
            verdict: sum(1 for r in results if r["expected_verdict"] == verdict)
            for verdict in ("support", "candidate_extension", "reject")
        },
        "confusion": confusion,
        "verdict_accuracy": round(correct_verdicts / evaluated, 4) if evaluated else 0.0,
        "support_cell_recall": (
            round(correct_support_cells / len(expected_supports), 4)
            if expected_supports else 0.0
        ),
        "automatic_support_precision": (
            round(correct_predicted_supports / len(predicted_supports), 4)
            if predicted_supports else 0.0
        ),
        "disagreements": [r for r in results if not r["verdict_ok"] or not r["cell_ok"]],
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": round(llm.estimate_cost_usd(), 6) if hasattr(llm, "estimate_cost_usd") else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintain Fin-first transfer cells.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed", help="seed the human-maintained cell taxonomy into the database")
    link = sub.add_parser("link", help="audit AI evidence against active cells")
    link.add_argument("--limit", type=int, default=50)
    link.add_argument("--include-trigger", action="store_true")
    link.add_argument(
        "--allow-auto-support",
        action="store_true",
        help="persist confirmed support links; use only after acceptance-gate sign-off",
    )
    evaluate = sub.add_parser("evaluate", help="evaluate the auditor without writing decisions")
    evaluate.add_argument("--dataset", type=Path, default=TRANSFER_EVAL_PATH)
    evaluate.add_argument("--limit", type=int)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if args.command == "seed":
        result = seed_cells()
    elif args.command == "link":
        result = link_pending(
            args.limit,
            evidence_only=not args.include_trigger,
            allow_automatic_support=args.allow_auto_support,
        )
    else:
        result = evaluate_benchmark(path=args.dataset, limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
