"""Daily pipeline entrypoint.

Usage:
    python -m pipeline.main daily       # daily run (production)
    python -m pipeline.main weekly      # weekly report
    DRY_RUN=true python -m pipeline.main daily   # no email, no inbox writes

Daily flow:
    1. Fetch papers (arxiv + hf_daily + ssrn)
    2. Filter via whitelist (institutions / h-index / hf signal / keywords)
    3. Extract L1 (all filtered) + L2 (priority subset)
    4. Persist to SQLite
    5. Summarize trends (AI + Fin, 14-day rolling)
    6. Generate gaps (theoretical → engineering)
    7. Self-check + score
    8. Propose mapping updates
    9. Write inbox/YYYY-MM-DD.md + git commit
    10. Send email digest
"""
from __future__ import annotations

import logging
import sys
from datetime import date

from rich.logging import RichHandler

from .config import load_settings


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def run_daily(target_date: date | None = None) -> None:
    """Main daily orchestration. target_date defaults to today."""
    target_date = target_date or date.today()
    log = logging.getLogger(__name__)
    log.info("AlphaGap daily run — %s", target_date)

    # TODO: implement orchestration
    # papers = fetch_all(target_date)
    # filtered = filter_by_whitelist(papers)
    # extract_concepts(filtered)
    # trends_ai = summarize_trends("ai", target_date)
    # trends_fin = summarize_trends("fin", target_date)
    # gaps_th = generate_theoretical_gaps(...)
    # gaps_eng = generate_engineering_gaps(...)
    # accepted = [g for g in gaps if self_check(g) == "accept" and score(g).total >= 8]
    # mapping_actions = propose_mapping_updates(...)
    # write_daily_inbox(target_date, payload)
    # send_daily_email(payload)
    raise NotImplementedError


def run_weekly(week_end: date | None = None) -> None:
    raise NotImplementedError


def main() -> None:
    s = load_settings()
    setup_logging(s.log_level)

    if len(sys.argv) < 2:
        print("Usage: python -m pipeline.main {daily|weekly}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "daily":
        run_daily()
    elif cmd == "weekly":
        run_weekly()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
