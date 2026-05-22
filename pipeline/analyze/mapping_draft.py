"""Create human-reviewable mapping drafts from accepted gaps.

Drafts live under mappings/drafts/ and are intentionally not read by
load_existing_mappings(), which only scans mappings/*.md. A draft becomes part
of the durable knowledge base only after a human promotes it to mappings/.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from ..config import PROJECT_ROOT


def generate_and_save_mapping_drafts(
    d: date,
    accepted: list[dict],
    *,
    out_dir: Path | None = None,
) -> list[dict]:
    """Write one mapping draft per accepted gap.

    Returns compact draft metadata for inbox rendering.
    """
    out_dir = out_dir or (PROJECT_ROOT / "mappings" / "drafts")
    out_dir.mkdir(parents=True, exist_ok=True)

    drafts: list[dict] = []
    for item in accepted:
        draft = draft_from_gap_item(d, item)
        path = out_dir / _draft_filename(d, draft["source_gap_id"])
        path.write_text(render_mapping_draft(draft), encoding="utf-8")
        draft["_path"] = _display_path(path)
        item["_mapping_draft_path"] = draft["_path"]
        drafts.append(draft)
    return drafts


def draft_from_gap_item(d: date, item: dict) -> dict:
    gap = item["gap"]
    score = item.get("score", {})
    structural = gap.get("structural_mapping") or {}
    research = gap.get("research_context") or {}
    field = gap.get("field_boundary_alignment") or {}
    ai_ids, fin_ids = _collect_evidence_ids(gap)

    return {
        "id": None,
        "status": "partially_explored" if fin_ids else "open_gap",
        "created_at": d.isoformat(),
        "updated_at": d.isoformat(),
        "source_gap_id": gap.get("_id", ""),
        "source_gap_type": item.get("type", ""),
        "source_brief": item.get("_brief_path") or gap.get("_brief_path") or "",
        "field_id": field.get("field_id", ""),
        "field_mechanism_family": field.get("mechanism_family", ""),
        "field_open_bottleneck": field.get("open_bottleneck", ""),
        "field_alignment": field.get("why_aligned", ""),
        "score_total": score.get("total"),
        "score_novelty": score.get("novelty"),
        "score_actionability": score.get("actionability"),
        "score_theoretical_support": score.get("theoretical_support"),
        "hypothesis": gap.get("hypothesis", ""),
        "ai_mechanism": _ai_mechanism(gap, research, structural),
        "ai_problem": _first_nonempty(
            _anchor_value(gap, "ai_anchor", "problem"),
            structural.get("ai_data_structure"),
            research.get("ai_frontier"),
        ),
        "ai_prerequisites": _first_nonempty(
            structural.get("ai_prerequisites"),
            structural.get("ai_data_structure"),
        ),
        "fin_structure": structural.get("fin_data_structure", ""),
        "fin_problem": _first_nonempty(
            _anchor_value(gap, "fin_anchor", "description"),
            research.get("fin_current_state"),
        ),
        "bridge": structural.get("bridge_required", ""),
        "match_status": structural.get("match_status", ""),
        "mismatch_severity": structural.get("mismatch_severity", ""),
        "evidence_ai_papers": sorted(ai_ids),
        "evidence_fin_papers": sorted(fin_ids),
        "decision_log": [
            {
                "date": d.isoformat(),
                "decision": "drafted",
                "source": "daily_pipeline",
                "notes": "Auto-generated from accepted gap; requires human review before promotion.",
            }
        ],
    }


def render_mapping_draft(draft: dict) -> str:
    frontmatter_keys = [
        "id",
        "status",
        "created_at",
        "updated_at",
        "source_gap_id",
        "source_gap_type",
        "source_brief",
        "field_id",
        "field_mechanism_family",
        "field_open_bottleneck",
        "field_alignment",
        "score_total",
        "score_novelty",
        "score_actionability",
        "score_theoretical_support",
        "hypothesis",
        "ai_mechanism",
        "ai_problem",
        "ai_prerequisites",
        "fin_structure",
        "fin_problem",
        "bridge",
        "match_status",
        "mismatch_severity",
        "evidence_ai_papers",
        "evidence_fin_papers",
        "decision_log",
    ]
    frontmatter = {k: draft.get(k) for k in frontmatter_keys}
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    title = draft.get("hypothesis") or draft.get("source_gap_id") or "Mapping Draft"
    body = [
        "---",
        yaml_text.strip(),
        "---",
        "",
        f"# {title}",
        "",
        "## Review Notes",
        "",
        "- [ ] promote to mappings/",
        "- [ ] reject",
        "- [ ] modify fields above before promotion",
        "",
        "## Rationale",
        "",
        f"- Field: {draft.get('field_id') or ''}",
        f"- Field mechanism family: {draft.get('field_mechanism_family') or ''}",
        f"- Field bottleneck: {draft.get('field_open_bottleneck') or ''}",
        f"- AI mechanism: {draft.get('ai_mechanism') or ''}",
        f"- Fin structure: {draft.get('fin_structure') or ''}",
        f"- Bridge: {draft.get('bridge') or ''}",
        f"- Source gap: {draft.get('source_gap_id') or ''}",
        "",
    ]
    return "\n".join(body)


def _draft_filename(d: date, gap_id: str) -> str:
    safe_gap = re.sub(r"[^A-Za-z0-9_-]", "_", gap_id or "GAP")
    return f"{d.isoformat()}-{safe_gap}.md"


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _collect_evidence_ids(gap: dict) -> tuple[set[str], set[str]]:
    ai_ids: set[str] = set()
    fin_ids: set[str] = set()

    ai = gap.get("ai_anchor") or {}
    if ai.get("paper_id"):
        ai_ids.add(ai["paper_id"])

    fin = gap.get("fin_anchor") or {}
    for pid in fin.get("evidence_paper_ids") or []:
        if pid:
            fin_ids.add(pid)

    anchors = gap.get("anchor_papers") or {}
    for p in anchors.get("ai", []) or []:
        if p.get("id"):
            ai_ids.add(p["id"])
    for p in anchors.get("fin", []) or []:
        if p.get("id"):
            fin_ids.add(p["id"])

    return ai_ids, fin_ids


def _ai_mechanism(gap: dict, research: dict, structural: dict) -> str:
    return _first_nonempty(
        _anchor_value(gap, "ai_anchor", "concept"),
        structural.get("ai_mechanism"),
        research.get("ai_frontier"),
        gap.get("hypothesis"),
    )


def _anchor_value(gap: dict, anchor_name: str, field_name: str) -> str:
    anchor = gap.get(anchor_name) or {}
    value = anchor.get(field_name)
    return value if isinstance(value, str) else ""


def _first_nonempty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
