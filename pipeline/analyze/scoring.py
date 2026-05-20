"""Gap scoring — Prompt 07.

Two dimensions:
  novelty (1-10):       has this gap been explored already?
  actionability (1-10): how easy is it to actually do this research?
Total = avg. Only total >= EMAIL_THRESHOLD makes it to the daily email.
"""
from __future__ import annotations

import json
import logging

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)

EMAIL_THRESHOLD = 8.0


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
    result = client.chat_json(system=system, user=user, temperature=0.0)

    novelty = _clamp_int(result.get("novelty"), 1, 10)
    actionability = _clamp_int(result.get("actionability"), 1, 10)
    total = round((novelty + actionability) / 2.0, 1)

    return {
        "novelty": novelty,
        "novelty_reason": result.get("novelty_reason", "")[:200],
        "actionability": actionability,
        "actionability_reason": result.get("actionability_reason", "")[:200],
        "total": total,
        "passes_email_threshold": total >= EMAIL_THRESHOLD,
    }


def _clamp_int(v, lo: int, hi: int) -> int:
    try:
        n = int(v)
    except (TypeError, ValueError):
        return lo
    return max(lo, min(hi, n))
