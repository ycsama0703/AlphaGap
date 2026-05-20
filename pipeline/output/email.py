"""Send daily email via Resend.

Email content (per design):
  1. 今日重点论文 top 5-10（高价值作者/机构）
  2. AI 方向 trends（14 天滚动）
  3. Fin 方向 trends
  4. 高分 Gap（total >= 8）— 理论型 + 工程型并列展示

NOT a paper digest — full audit lives in inbox/YYYY-MM-DD.md.
"""
from __future__ import annotations

import resend

from ..config import load_settings


def send_daily_email(payload: dict) -> None:
    """payload = {date, papers_top, ai_trends, fin_trends, gaps_high_score}."""
    s = load_settings()
    if s.dry_run:
        print("[DRY-RUN] Would send email with payload:", payload.keys())
        return
    raise NotImplementedError


def send_failure_alert(error: str) -> None:
    """Short email when pipeline fails."""
    raise NotImplementedError
