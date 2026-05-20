"""Gap generation — Prompts 04 (theoretical) + 05 (engineering).

Calls 04 first, then 05 with theoretical_gaps_today_json as additional context
(so 05 can upgrade theoretical→engineering).
"""
from __future__ import annotations


def generate_theoretical_gaps(context: dict) -> list[dict]:
    """Prompt 04. context = {ai_recent_papers, fin_recent_papers, ai_trends, fin_trends, existing_mappings}."""
    raise NotImplementedError


def generate_engineering_gaps(context: dict, theoretical_gaps: list[dict]) -> list[dict]:
    """Prompt 05. Same context + today's theoretical gaps as upgrade candidates."""
    raise NotImplementedError
