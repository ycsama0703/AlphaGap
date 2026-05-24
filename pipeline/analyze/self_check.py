"""Gap self-check — Prompt 06.

For each gap (theoretical or engineering), runs an 11-item checklist and
returns verdict in {accept, reject, downgrade, retry}.

Pipeline routing per verdict:
  accept    → proceed to scoring (Prompt 07)
  reject    → drop (A duplicates / B invalid anchors are fatal)
  downgrade → engineering gap stripped to theoretical (keep hypothesis,
              drop roadmap)
  retry     → regenerate up to 2x with bumped temperature, then downgrade
"""
from __future__ import annotations

import json
import logging

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)


def check_gap(gap: dict, gap_type: str,
              valid_ai_ids: set[str], valid_fin_ids: set[str],
              mappings_brief: list[dict],
              fin_field_boundaries: list[dict] | None = None,
              ai_method_names: list[str] | None = None,
              client: LLMClient | None = None) -> dict:
    """Prompt 06 — returns dict with checks + overall_verdict + verdict_summary."""
    client = client or LLMClient()
    system, user_template = parse_prompt("06_gap_self_check")
    user = render_template(
        user_template,
        type=gap_type,
        gap_json=json.dumps(gap, ensure_ascii=False, indent=2),
        valid_ai_paper_ids=json.dumps(sorted(valid_ai_ids), ensure_ascii=False),
        valid_fin_paper_ids=json.dumps(sorted(valid_fin_ids), ensure_ascii=False),
        mappings_brief_json=json.dumps(mappings_brief, ensure_ascii=False, indent=2),
        fin_field_boundaries_json=json.dumps(fin_field_boundaries or [], ensure_ascii=False, indent=2),
        ai_method_names_json=json.dumps(ai_method_names or [], ensure_ascii=False, indent=2),
    )
    result = client.chat_json(system=system, user=user, temperature=0.0)

    verdict = result.get("overall_verdict", "reject")
    if verdict not in ("accept", "reject", "downgrade", "retry"):
        log.warning("Unexpected verdict %r, defaulting to reject", verdict)
        verdict = "reject"
        result["overall_verdict"] = verdict
    result.setdefault("verdict_summary", "")
    result.setdefault("field_boundary_alignment", gap.get("field_boundary_alignment") or {})
    return result


def downgrade_to_theoretical(eng_gap: dict) -> dict:
    """Strip engineering roadmap, keep hypothesis + anchors as theoretical."""
    return {
        "_id": eng_gap.get("_id", "").replace("ENG-", "TH-DG-"),
        "_type": "theoretical",
        "_downgraded_from": eng_gap.get("_id"),
        "_origin": eng_gap.get("_origin", {}),
        "risk_audit": eng_gap.get("risk_audit", {}),
        "hypothesis": eng_gap.get("hypothesis", ""),
        "field_boundary_alignment": eng_gap.get("field_boundary_alignment", {}),
        "structural_mapping": eng_gap.get("structural_mapping", {}),
        "ai_anchor": eng_gap.get("anchor_papers", {}).get("ai", [{}])[0]
                       if eng_gap.get("anchor_papers", {}).get("ai") else {},
        "fin_anchor": {
            "description": eng_gap.get("motivation", "")[:200],
            "evidence_paper_ids": [
                p.get("id") for p in eng_gap.get("anchor_papers", {}).get("fin", [])
            ],
        },
        "reasoning_chain": [eng_gap.get("motivation", "")],
        "why_open_gap": "Downgraded from engineering; roadmap incomplete",
        "related_mappings": [],
    }
