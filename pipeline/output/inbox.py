"""Write daily inbox markdown — the file you git pull and review.

Format:
  inbox/YYYY-MM-DD.md            — gap proposals + mapping update proposals
  inbox/YYYY-MM-DD-summary.md    — full digest (papers, trends, gaps)

After git pull, you edit the file with accept/reject/modify markers,
then commit & push.
"""
from __future__ import annotations

from datetime import date


def write_daily_inbox(d: date, payload: dict) -> str:
    """payload = {papers, trends, gaps, mapping_actions}. Returns file path."""
    raise NotImplementedError
