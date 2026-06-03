"""Daily pipeline entrypoint.

Usage:
    python -m pipeline.main daily              # daily run (production)
    python -m pipeline.main daily --dry-run    # no email send, no commit
    python -m pipeline.main weekly             # weekly report (TODO)

Daily flow:
    1. Ingest: fetch + filter + persist + L1/L2 extract
    2. Gaps: generate experiment candidates → self-check → score
    3. Deep briefs: only for email-ready experiments
    4. Inbox: write inbox/YYYY-MM-DD.md
    5. Email: send daily experiment digest via Resend
    6. (Optional) Git commit + push inbox
"""
from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import traceback
from datetime import date

from rich.logging import RichHandler

from . import db, ingest
from .analyze import brief as brief_mod
from .analyze import enrich as enrich_mod
from .analyze import gaps as gaps_mod
from .config import PROJECT_ROOT, load_settings
from .llm_client import LLMClient
from .output import email as email_mod
from .output import inbox as inbox_mod


log = logging.getLogger(__name__)


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )


def run_daily(target_date: date | None = None,
              *, lookback: int = 1, max_l1: int = 80, max_l2: int = 20,
              git_commit: bool = True) -> dict:
    target_date = target_date or date.today()
    log.info("=== AlphaGap daily run %s ===", target_date)

    s = load_settings()
    db.init_schema()

    # 1. Ingest
    log.info("Step 1/5: ingest")
    ingest_stats = ingest.run_ingest(
        lookback_days=lookback, max_l1=max_l1, max_l2=max_l2,
    )

    # 2. Experiment-first gap pipeline. Trend/citation maintenance is not on the
    # critical path: daily output should spend time on runnable experiments.
    log.info("Step 2/5: experiment-first gap pipeline (04 + 05 + 06 + 07)")
    client = LLMClient()
    gap_result = gaps_mod.run_gap_pipeline(
        target_date, adversarial_review=s.adversarial_gap_review, client=client,
    )

    # Record every generated gap in the unified ledger (mechanism-level, brand-free):
    # the readable daily record + the cross-day dedup source (O3).
    from .output import gap_log as gap_log_mod
    n_logged = gap_log_mod.append_run(target_date, gap_result)
    log.info("Gap ledger: logged %d gaps → gap_log.jsonl / GAP-LOG.md", n_logged)

    # Enrich gaps with full paper details from DB (for rendering)
    enrich_mod.enrich_accepted(gap_result["accepted"])
    # 3. Deep briefs are generated only after an idea reaches runnable engineering form.
    engineering_email_ready = [
        item for item in gap_result["email_ready"]
        if item.get("type") == "engineering"
    ]
    log.info("Step 3/5: deep briefs (Prompt 09) for %d runnable experiments",
             len(engineering_email_ready))
    brief_mod.generate_and_save_briefs(
        target_date,
        engineering_email_ready,
        gap_result["context"]["ai_trends"],
        gap_result["context"]["fin_trends"],
        gap_result["context"]["existing_mappings"],
        client=client,
    )

    # Mapping/taxonomy maintenance is deliberately excluded from daily delivery.
    # Promote a proven experiment into mappings only after human review.
    mapping_drafts: list[dict] = []
    mapping_actions: list[dict] = []

    # Assemble inbox/email payload
    payload = {
        "stats": {
            "fetched": ingest_stats.get("fetched"),
            "candidates": ingest_stats.get("candidates"),
            "l1_done": ingest_stats.get("l1_done"),
            "l2_done": ingest_stats.get("l2_done"),
            "cost_usd": round(
                (ingest_stats.get("cost_usd", 0) or 0) + client.estimate_cost_usd(), 4
            ),
            "window_ai": gap_result["context"].get("window_ai_days"),
            "window_fin": gap_result["context"].get("window_fin_days"),
            "fin_fields_selected": [
                f.get("id") for f in gap_result["context"].get("fin_field_boundaries", [])
            ],
            "fin_fields_available": [
                f.get("id") for f in gap_result["context"].get("fin_field_boundaries_all", [])
            ],
            "historical_ai_mechanisms": len(
                gap_result["context"].get("historical_ai_mechanisms", [])
            ),
            "daily_mode": "experiment_first",
        },
        "top_papers": gap_result["context"]["ai_recent_papers"][:5] +
                      gap_result["context"]["fin_recent_papers"][:3],
        "ai_trends": gap_result["context"]["ai_trends"],
        "fin_trends": gap_result["context"]["fin_trends"],
        "theoretical": gap_result["theoretical"],
        "engineering": gap_result["engineering"],
        "accepted": gap_result["accepted"],
        "rejected": gap_result["rejected"],
        "downgraded": gap_result["downgraded"],
        "email_ready": gap_result["email_ready"],
        "duplicates_suppressed": gap_result.get("duplicates_suppressed", []),
        "risk_audit": gap_result.get("risk_audit", {"enabled": False}),
        "mapping_drafts": mapping_drafts,
        "mapping_actions": mapping_actions,
    }

    # 4. Inbox
    log.info("Step 4/5: write inbox markdown")
    inbox_path = inbox_mod.write_daily_inbox(target_date, payload)

    # 5. Email
    log.info("Step 5/5: send email")
    try:
        email_mod.send_daily_email(target_date, payload)
    except Exception as e:
        log.error("Email send failed: %s", e)

    # Optional persistence (server-side cron may enable)
    if git_commit and not s.dry_run:
        log.info("Persist inbox: git commit + push")
        try:
            _git_commit_inbox(inbox_path, target_date)
        except Exception as e:
            log.warning("Git commit failed (non-fatal): %s", e)

    log.info("=== Done. Total cost: $%.4f ===", payload["stats"]["cost_usd"])
    return payload


def _git_commit_inbox(inbox_path, target_date: date) -> None:
    rel = inbox_path.relative_to(PROJECT_ROOT)
    subprocess.run(["git", "add", str(rel)], cwd=PROJECT_ROOT, check=True)
    msg = f"inbox: {target_date.isoformat()} daily run"
    subprocess.run(["git", "commit", "-m", msg], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "push", "-q", "origin", "main"], cwd=PROJECT_ROOT, check=True)


def run_weekly(week_end: date | None = None) -> None:
    raise NotImplementedError("Weekly report not yet implemented")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["daily", "weekly"])
    parser.add_argument("--date", help="ISO date, default today")
    parser.add_argument("--lookback", type=int, default=1)
    parser.add_argument("--max-l1", type=int, default=80)
    parser.add_argument("--max-l2", type=int, default=20)
    parser.add_argument("--no-commit", action="store_true",
                        help="Skip git commit/push (useful for local testing)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Override DRY_RUN env: no email, no commit")
    args = parser.parse_args()

    if args.dry_run:
        import os
        os.environ["DRY_RUN"] = "true"

    s = load_settings()
    setup_logging(s.log_level)

    target_date = date.fromisoformat(args.date) if args.date else date.today()

    if args.command == "daily":
        try:
            run_daily(target_date,
                      lookback=args.lookback,
                      max_l1=args.max_l1,
                      max_l2=args.max_l2,
                      git_commit=not args.no_commit)
        except Exception:
            log.error("Pipeline crashed:\n%s", traceback.format_exc())
            try:
                email_mod.send_failure_alert(target_date, traceback.format_exc())
            except Exception as e2:
                log.error("Could not even send failure alert: %s", e2)
            sys.exit(1)
    elif args.command == "weekly":
        run_weekly(target_date)


if __name__ == "__main__":
    main()
