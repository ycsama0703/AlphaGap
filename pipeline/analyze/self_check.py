"""Gap self-check — Prompt 06.

For each gap (theoretical or engineering), runs 11-item checklist and returns
verdict in {accept, reject, downgrade, retry}.
"""
from __future__ import annotations


def check_gap(gap: dict, gap_type: str, context: dict) -> dict:
    """Returns {checks: {...}, overall_verdict: str, verdict_summary: str}."""
    raise NotImplementedError
