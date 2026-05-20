"""Trend summary — Prompt 03.

Aggregates concept counts over 14-day windows (recent vs prior), then asks LLM
to classify into rising / falling / new_emergence / stable_hot with commentary.
"""
from __future__ import annotations

from datetime import date


def aggregate_concept_counts(side: str, recent_end: date) -> dict:
    """Returns concept frequency stats for LLM prompt. SQL query against papers + paper_concepts."""
    raise NotImplementedError


def summarize_trends(side: str, recent_end: date) -> dict:
    """Run Prompt 03. Returns {rising, falling, new_emergence, stable_hot}."""
    raise NotImplementedError
