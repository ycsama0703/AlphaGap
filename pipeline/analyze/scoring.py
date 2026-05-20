"""Gap scoring — Prompt 07.

Two dimensions: novelty (1-10) + actionability (1-10), total = avg.
Only total >= 8 makes it to email.
"""
from __future__ import annotations


EMAIL_THRESHOLD = 8.0


def score_gap(gap: dict, gap_type: str, context: dict) -> dict:
    """Returns {novelty, novelty_reason, actionability, actionability_reason, total}."""
    raise NotImplementedError
