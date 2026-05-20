"""Weekly report generator — writes reports/YYYY-Www.md.

Content:
  - mappings table changes (status transitions, new mappings)
  - top gap candidates (across the week)
  - concept trend velocity (which concepts moved most)
"""
from __future__ import annotations

from datetime import date


def generate_weekly_report(week_end: date) -> str:
    """Returns path to generated report."""
    raise NotImplementedError
