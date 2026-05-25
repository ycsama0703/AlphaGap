"""Adversarial candidate review before expensive gap expansion.

The reviewer is intentionally not another idea generator. It challenges each
candidate's financial boundary fit and mechanism-transfer assumptions, then
returns pass/revise/reject decisions for the existing candidate pool.
"""
from __future__ import annotations

import json
import logging

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)

MIN_REVIEW_COVERAGE = 0.8
RISK_AUDIT_MAX_TOKENS = 24576


def audit_candidates(candidates: list[dict], context: dict,
                     client: LLMClient | None = None) -> tuple[list[dict], dict]:
    """Run Prompt 04B and return retained candidates plus audit metadata.

    A failed or incomplete audit is fail-open: affected candidates are retained
    so enabling the optional mode cannot break a daily run due to reviewer
    output drift.
    """
    summary = _new_summary(len(candidates))
    if not candidates:
        return [], summary

    client = client or LLMClient()
    system, user_template = parse_prompt("04B_gap_risk_audit")
    user = render_template(
        user_template,
        candidates_json=json.dumps(candidates, ensure_ascii=False, indent=2),
        ai_recent_papers_json=json.dumps(context.get("ai_recent_papers", []), ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context.get("fin_recent_papers", []), ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context.get("existing_mappings", []), ensure_ascii=False, indent=2),
        fin_field_boundaries_json=json.dumps(context.get("fin_field_boundaries", []), ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
    )
    try:
        result = client.chat_json(
            system=system,
            user=user,
            temperature=0.0,
            reasoning=True,
            max_tokens=RISK_AUDIT_MAX_TOKENS,
        )
    except Exception as exc:
        log.warning("Adversarial risk audit failed: %s (keeping all candidates)", exc)
        summary["fallback"] = True
        summary["fallback_reason"] = str(exc)
        summary["retained"] = len(candidates)
        return candidates, summary

    reviews = result.get("reviews", []) if isinstance(result, dict) else []
    indexed = {
        str(review.get("candidate_idx")): review
        for review in reviews
        if isinstance(review, dict) and review.get("candidate_idx") is not None
    }

    retained: list[dict] = []
    for candidate in candidates:
        idx = str(candidate.get("idx"))
        review = _normalize_review(indexed.get(idx))
        if review is None:
            review = {
                "verdict": "unreviewed",
                "failure_classes": ["schema_omission"],
                "strongest_objection": "reviewer omitted this candidate; retained fail-open",
                "required_revision": "",
                "revised_one_liner": "",
            }
            kept = dict(candidate)
            kept["risk_audit"] = review
            retained.append(kept)
            summary["unreviewed"] += 1
        else:
            summary["reviewed"] += 1
            if review["verdict"] == "reject":
                summary["rejected"] += 1
            else:
                kept = dict(candidate)
                kept["risk_audit"] = review
                if review["verdict"] == "revise":
                    summary["revised"] += 1
                    if review.get("revised_one_liner"):
                        kept["original_one_liner"] = candidate.get("one_liner", "")
                        kept["one_liner"] = review["revised_one_liner"]
                else:
                    summary["passed"] += 1
                retained.append(kept)

        summary["decisions"].append({
            "candidate_idx": candidate.get("idx"),
            "one_liner": candidate.get("one_liner", ""),
            **review,
        })

    summary["retained"] = len(retained)
    summary["coverage"] = round(summary["reviewed"] / len(candidates), 3)
    if summary["coverage"] < MIN_REVIEW_COVERAGE:
        summary["fallback"] = True
        summary["fallback_reason"] = (
            f"incomplete reviewer coverage {summary['reviewed']}/{len(candidates)} "
            f"< {MIN_REVIEW_COVERAGE:.0%}"
        )
        summary["retained"] = len(candidates)
        log.warning(
            "Adversarial risk audit incomplete: %s (using standard mode)",
            summary["fallback_reason"],
        )
        return candidates, summary

    log.info(
        "Adversarial audit: %d candidates → %d retained (%d pass, %d revise, %d reject, %d unreviewed)",
        len(candidates), len(retained), summary["passed"], summary["revised"],
        summary["rejected"], summary["unreviewed"],
    )
    return retained, summary


def _new_summary(input_candidates: int) -> dict:
    return {
        "enabled": True,
        "mode": "adversarial",
        "input_candidates": input_candidates,
        "reviewed": 0,
        "passed": 0,
        "revised": 0,
        "rejected": 0,
        "unreviewed": 0,
        "retained": 0,
        "fallback": False,
        "fallback_reason": "",
        "coverage": 0.0,
        "decisions": [],
    }


def _normalize_review(review: object) -> dict | None:
    if not isinstance(review, dict):
        return None
    verdict = str(review.get("verdict", "")).lower().strip()
    if verdict not in {"pass", "revise", "reject"}:
        return None
    failure_classes = review.get("failure_classes")
    if not isinstance(failure_classes, list):
        legacy = str(review.get("failure_class", "")).strip()
        failure_classes = [legacy] if legacy else []
    return {
        "verdict": verdict,
        "failure_classes": [str(value)[:80] for value in failure_classes if str(value).strip()][:5],
        "strongest_objection": str(review.get("strongest_objection", ""))[:300],
        "required_revision": str(review.get("required_revision", ""))[:300],
        "revised_one_liner": str(review.get("revised_one_liner", ""))[:120],
    }
