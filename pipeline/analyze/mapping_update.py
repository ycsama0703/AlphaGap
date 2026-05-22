"""Mapping table update — Prompt 08.

Proposes status_change / add_mapping / add_evidence actions based on:
  - today's newly extracted papers (signals about Fin uptake of AI concepts)
  - existing mappings (current state of the knowledge map)
  - today's accepted gaps (candidates to add as new mappings)

All actions go to inbox/ for human approval — NEVER auto-applied to mappings/.
"""
from __future__ import annotations

import json
import logging

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)

VALID_TRANSITIONS = {
    ("open_gap", "partially_explored"),
    ("partially_explored", "mature"),
    ("partially_explored", "refuted"),
    ("open_gap", "refuted"),
}


def propose_mapping_updates(today_papers: list[dict],
                             existing_mappings: list[dict],
                             today_accepted_gaps: list[dict],
                             client: LLMClient | None = None) -> list[dict]:
    """Run Prompt 08. Returns list of validated actions."""
    client = client or LLMClient()
    system, user_template = parse_prompt("08_mapping_update")
    user = render_template(
        user_template,
        today_papers_json=json.dumps(today_papers, ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(existing_mappings, ensure_ascii=False, indent=2),
        today_accepted_gaps_json=json.dumps(today_accepted_gaps, ensure_ascii=False, indent=2),
    )
    try:
        result = client.chat_json(system=system, user=user, temperature=0.2)
    except Exception as e:
        log.warning("Mapping update LLM call failed: %s (returning [])", e)
        return []

    actions = result.get("actions", []) if isinstance(result, dict) else []
    today_paper_ids = {p.get("id") for p in today_papers}
    accepted_gap_ids = {g.get("gap", {}).get("_id") for g in today_accepted_gaps}
    drafted_gap_ids = {
        g.get("gap", {}).get("_id")
        for g in today_accepted_gaps
        if g.get("_mapping_draft_path")
    }
    mapping_ids = {m.get("id") for m in existing_mappings}

    validated: list[dict] = []
    for a in actions:
        atype = a.get("type")
        if atype == "status_change":
            if a.get("mapping_id") not in mapping_ids:
                log.debug("Drop status_change for unknown mapping_id %s", a.get("mapping_id"))
                continue
            if (a.get("from_status"), a.get("to_status")) not in VALID_TRANSITIONS:
                log.debug("Drop illegal transition %s → %s", a.get("from_status"), a.get("to_status"))
                continue
            ev_ids = [p for p in (a.get("evidence_paper_ids") or []) if p in today_paper_ids]
            if not ev_ids:
                log.debug("Drop status_change with no valid evidence: %s", a.get("mapping_id"))
                continue
            a["evidence_paper_ids"] = ev_ids
            validated.append(a)
        elif atype == "add_mapping":
            if a.get("from_gap_id") not in accepted_gap_ids:
                log.debug("Drop add_mapping with unknown gap_id %s", a.get("from_gap_id"))
                continue
            if a.get("from_gap_id") in drafted_gap_ids:
                log.debug("Drop add_mapping for gap with mapping draft %s", a.get("from_gap_id"))
                continue
            if a.get("initial_status") not in ("open_gap", "partially_explored"):
                a["initial_status"] = "open_gap"
            validated.append(a)
        elif atype == "add_evidence":
            if a.get("mapping_id") not in mapping_ids:
                continue
            ev_ids = [p for p in (a.get("paper_ids") or []) if p in today_paper_ids]
            if not ev_ids:
                continue
            a["paper_ids"] = ev_ids
            validated.append(a)
        else:
            log.debug("Drop unknown action type %r", atype)

    log.info("Mapping update: %d raw → %d validated actions", len(actions), len(validated))
    return validated[:10]    # cap at 10 per design
