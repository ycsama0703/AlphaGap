"""HuggingFace Daily Papers fetcher.

Uses HF's unofficial API or HTML scrape:
  https://huggingface.co/api/daily_papers?date=YYYY-MM-DD

TODO:
  - implement fetch_for_date(d: date) -> list[PaperRecord]
  - each daily paper has arxiv_id, upvotes, summary — cross-reference with arxiv fetcher
"""
from __future__ import annotations

from datetime import date

from .arxiv import PaperRecord


def fetch_for_date(d: date) -> list[PaperRecord]:
    raise NotImplementedError
