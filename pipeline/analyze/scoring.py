"""Gap scoring — Prompt 07.

Two dimensions:
  novelty (1-10):       has this gap been explored already?
  actionability (1-10): how easy is it to actually do this research?
  theoretical_support: how well grounded the transfer mechanism is.
Total currently remains avg(novelty, actionability). Only total >=
ENGINEERING_EMAIL_THRESHOLD makes engineering gaps email-ready. Theoretical gaps
use a separate high-novelty gate so valuable conceptual ideas are not hidden
only because they are less immediately actionable.
"""
from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)

ENGINEERING_EMAIL_THRESHOLD = 8.0
THEORETICAL_EMAIL_TOTAL_THRESHOLD = 6.5
THEORETICAL_EMAIL_NOVELTY_THRESHOLD = 9
THEORETICAL_EMAIL_ACTIONABILITY_THRESHOLD = 4
THEORETICAL_EMAIL_SUPPORT_THRESHOLD = 5.0


def score_gap(gap: dict, gap_type: str,
              mappings_brief: list[dict],
              related_papers_brief: list[dict] | None = None,
              client: LLMClient | None = None) -> dict:
    """Run Prompt 07. Returns dict with novelty / actionability / total + reasons."""
    client = client or LLMClient()
    system, user_template = parse_prompt("07_gap_scoring")
    user = render_template(
        user_template,
        type=gap_type,
        gap_json=json.dumps(gap, ensure_ascii=False, indent=2),
        mappings_brief_json=json.dumps(mappings_brief, ensure_ascii=False, indent=2),
        related_papers_brief_json=json.dumps(
            related_papers_brief or [], ensure_ascii=False, indent=2),
    )
    result = client.chat_json(system=system, user=user, temperature=0.0, reasoning=True)

    novelty = _clamp_int(result.get("novelty"), 1, 10)
    actionability = _clamp_int(result.get("actionability"), 1, 10)
    support_components = _support_components(result.get("theoretical_support_components"))
    theoretical_support = _component_average(support_components)
    cap = mapping_novelty_cap(gap, mappings_brief)
    cap_reason = ""
    if cap:
        original = novelty
        novelty = min(novelty, cap["cap"])
        if novelty < original:
            cap_reason = (
                f"mapping {cap['mapping_id']} status={cap['status']} caps novelty at {cap['cap']}"
            )
    total = round((novelty + actionability) / 2.0, 1)
    email_gate = email_gate_result(
        gap_type,
        novelty=novelty,
        actionability=actionability,
        theoretical_support=theoretical_support,
        total=total,
    )

    return {
        "novelty": novelty,
        "novelty_reason": _append_reason(result.get("novelty_reason", ""), cap_reason),
        "actionability": actionability,
        "actionability_reason": result.get("actionability_reason", "")[:200],
        "theoretical_support": theoretical_support,
        "theoretical_support_reason": result.get("theoretical_support_reason", "")[:200],
        "theoretical_support_components": support_components,
        "total": total,
        "passes_email_threshold": email_gate["passes"],
        "email_gate": email_gate["gate"],
        "email_gate_reason": email_gate["reason"],
        "mapping_overlap": cap,
    }


def email_gate_result(gap_type: str, *, novelty: int, actionability: int,
                      theoretical_support: float, total: float) -> dict:
    """Return email inclusion decision and explanation."""
    if gap_type == "engineering":
        passes = total >= ENGINEERING_EMAIL_THRESHOLD
        return {
            "passes": passes,
            "gate": "engineering_total",
            "reason": (
                f"engineering total {total} "
                f"{'>=' if passes else '<'} {ENGINEERING_EMAIL_THRESHOLD}"
            ),
        }

    passes = (
        total >= THEORETICAL_EMAIL_TOTAL_THRESHOLD
        and novelty >= THEORETICAL_EMAIL_NOVELTY_THRESHOLD
        and actionability >= THEORETICAL_EMAIL_ACTIONABILITY_THRESHOLD
        and theoretical_support >= THEORETICAL_EMAIL_SUPPORT_THRESHOLD
    )
    return {
        "passes": passes,
        "gate": "theoretical_high_novelty",
        "reason": (
            f"theoretical gate: total {total}/{THEORETICAL_EMAIL_TOTAL_THRESHOLD}, "
            f"novelty {novelty}/{THEORETICAL_EMAIL_NOVELTY_THRESHOLD}, "
            f"actionability {actionability}/{THEORETICAL_EMAIL_ACTIONABILITY_THRESHOLD}, "
            f"theory {theoretical_support}/{THEORETICAL_EMAIL_SUPPORT_THRESHOLD}"
        ),
    }


def _clamp_int(v, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))


THEORETICAL_SUPPORT_COMPONENTS = (
    "structural_homology",
    "failure_mode_match",
    "assumption_transferability",
    "identifiable_prediction",
    "theoretical_anchors",
)


def _support_components(raw: object) -> dict[str, int]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        key: _clamp_int(raw.get(key), 1, 10)
        for key in THEORETICAL_SUPPORT_COMPONENTS
    }


def _component_average(components: dict[str, int]) -> float:
    if not components:
        return 1.0
    return round(sum(components.values()) / len(components), 1)


def mapping_novelty_cap(gap: dict, mappings_brief: list[dict]) -> dict | None:
    """Return novelty cap from the most similar official mapping, if any.

    This is deliberately conservative and deterministic. It is not meant to
    decide semantic equivalence perfectly; it prevents already-approved mapping
    directions from repeatedly scoring as brand-new ideas.
    """
    best: tuple[float, dict] | None = None
    gap_text = _gap_text(gap)
    if not gap_text.strip():
        return None

    for mapping in mappings_brief:
        status = (mapping.get("status") or "").strip()
        cap = _cap_for_status(status)
        if cap is None:
            continue
        mapping_text = _mapping_text(mapping)
        if not mapping_text.strip():
            continue
        score = _similarity(gap_text, mapping_text)
        if best is None or score > best[0]:
            best = (score, mapping)

    if best is None:
        return None
    score, mapping = best
    if score < 0.22:
        return None

    status = (mapping.get("status") or "").strip()
    return {
        "mapping_id": mapping.get("id"),
        "status": status,
        "similarity": round(score, 3),
        "cap": _cap_for_status(status),
    }


def _cap_for_status(status: str) -> int | None:
    return {
        "open_gap": 8,
        "partially_explored": 7,
        "mature": 4,
        "refuted": 5,
    }.get(status)


def _gap_text(gap: dict) -> str:
    structural = gap.get("structural_mapping") or {}
    research = gap.get("research_context") or {}
    ai_anchor = gap.get("ai_anchor") or {}
    fin_anchor = gap.get("fin_anchor") or {}
    field_alignment = gap.get("field_boundary_alignment") or {}
    return " ".join(
        str(x)
        for x in [
            gap.get("hypothesis", ""),
            gap.get("motivation", ""),
            field_alignment.get("field_id", ""),
            field_alignment.get("mechanism_family", ""),
            field_alignment.get("open_bottleneck", ""),
            field_alignment.get("good_transfer_target", ""),
            field_alignment.get("bad_target_avoided", ""),
            field_alignment.get("why_aligned", ""),
            ai_anchor.get("concept", ""),
            fin_anchor.get("description", ""),
            structural.get("ai_data_structure", ""),
            structural.get("fin_data_structure", ""),
            structural.get("bridge_required", ""),
            research.get("ai_frontier", ""),
            research.get("fin_current_state", ""),
        ]
        if x
    )


def _mapping_text(mapping: dict) -> str:
    return " ".join(
        str(x)
        for x in [
            mapping.get("ai_concept", ""),
            mapping.get("fin_concept", ""),
            mapping.get("ai_mechanism", ""),
            mapping.get("ai_problem", ""),
            mapping.get("fin_structure", ""),
            mapping.get("fin_problem", ""),
            mapping.get("bridge", ""),
            mapping.get("notes", ""),
        ]
        if x
    )


def _similarity(a: str, b: str) -> float:
    fa = _features(a)
    fb = _features(b)
    jaccard = 0.0
    if fa and fb:
        jaccard = len(fa & fb) / len(fa | fb)
    seq = SequenceMatcher(None, _compact(a), _compact(b)).ratio()
    return max(jaccard, seq * 0.55)


def _features(text: str) -> set[str]:
    text = text.lower()
    features = {m.group(0) for m in re.finditer(r"[a-z0-9][a-z0-9_-]{3,}", text)}
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        features.update(chunk[i:i + 2] for i in range(len(chunk) - 1))
    return features


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def _append_reason(reason: str, extra: str) -> str:
    reason = (reason or "")[:160]
    if not extra:
        return reason[:200]
    if reason:
        return f"{reason}; {extra}"[:200]
    return extra[:200]
