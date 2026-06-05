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

    # 2. Build context for the mechanism line. The engineering/theoretical gap generation
    # (04A/04/05/06/07) is RETIRED — the mechanism line (Step 2.5) is now the sole gap producer.
    # We still build_gap_context because the mechanism line consumes its ai_recent_papers +
    # fin_field_boundaries, and the email shows top_papers/trends. The dead engineering-gap code
    # (run_gap_pipeline / prompts 04*-07/09) is kept in the tree but no longer called.
    log.info("Step 2/5: build context (mechanism-only; engineering gap generation retired)")
    client = LLMClient()
    ctx = gaps_mod.build_gap_context(
        target_date, include_trends=getattr(s, "daily_include_trends", True), client=client,
    )
    gap_result = {
        "context": ctx,
        "theoretical": [], "engineering": [], "accepted": [], "rejected": [],
        "downgraded": [], "email_ready": [], "theoretical_leads": [],
        "duplicates_suppressed": [], "risk_audit": {"enabled": False},
    }

    # Record every generated gap in the unified ledger (mechanism-level, brand-free):
    # the readable daily record + the cross-day dedup source (O3).
    from .output import gap_log as gap_log_mod
    n_logged = gap_log_mod.append_run(target_date, gap_result)
    log.info("Gap ledger: logged %d gaps → gap_log.jsonl / GAP-LOG.md", n_logged)

    # Refresh the cell coverage heatmap + queue any frontier new-cell proposals for review.
    from . import cells as cells_mod
    cells_mod.render_coverage()
    n_pending = cells_mod.collect_pending(days=30, as_of=target_date)
    cov = cells_mod.coverage()
    log.info("Cell coverage: %d/%d cells used; %d new frontier cell-proposals queued for review",
             cov["used_cells"], cov["total_cells"], n_pending)

    # Step 2.5 — deep research-gap generation (precision-first, low-volume, best-effort).
    # Mines the top-N anchor papers' FULL TEXT → runnable experiment slices gated by the
    # empirical pre-mortem. Additive; never breaks the run. See research_gap_stage.py.
    research_gap_result = {"research_gaps": [], "mined_papers": [], "skipped": []}
    try:
        from .analyze import research_gap_stage
        n_rg = getattr(s, "research_gap_papers", 2)
        if n_rg > 0:
            log.info("Step 2.5: deep research-gap generation (mine top %d papers)", n_rg)
            research_gap_result = research_gap_stage.generate_daily_research_gaps(
                gap_result["context"], n_papers=n_rg, date_tag=target_date.isoformat(), client=client)
            log.info("Research gaps: %d from %d mined paper(s); %d skipped",
                     len(research_gap_result["research_gaps"]),
                     len(research_gap_result["mined_papers"]),
                     len(research_gap_result.get("skipped", [])))
    except Exception as e:
        log.warning("Step 2.5 research-gap stage skipped: %s", e)

    # Engineering deep briefs (Prompt 09) are retired with the engineering gap line; the mechanism
    # line produces its own briefs in Step 2.5. enrich_accepted is a no-op on the empty accepted list.
    enrich_mod.enrich_accepted(gap_result["accepted"])

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
                (ingest_stats.get("cost_usd", 0) or 0) + client.estimate_cost_usd()
                + (research_gap_result.get("cost_usd", 0) or 0), 4
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
        "research_gaps": research_gap_result.get("research_gaps", []),
        "research_gap_meta": {"mined_papers": research_gap_result.get("mined_papers", []),
                              "skipped": research_gap_result.get("skipped", [])},
        "theoretical_leads": gap_result.get("theoretical_leads", []),
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
