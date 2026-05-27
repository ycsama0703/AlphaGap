"""Maintenance commands for the AI mechanism evidence library.

This module deliberately stays outside ``pipeline.main daily``. A historical
evidence rebuild can issue many LLM calls and modify derived library state; it
must be run explicitly against a backed-up database or a validation clone.

Examples:
    python -m pipeline.mechanism_maintenance audit
    python -m pipeline.mechanism_maintenance clone --out db/validation.sqlite
    python -m pipeline.mechanism_maintenance rebuild \
        --db-path db/validation.sqlite --years 2025 --limit 20 \
        --max-l1 20 --assign-limit 20 --confirm
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path

from . import db
from .config import PROJECT_ROOT, load_settings
from .filter import compute_signals


log = logging.getLogger(__name__)

REBUILDABLE_EVIDENCE_SOURCES = ("openreview",)


def _resolve_path(path: str | Path | None) -> Path:
    if path is None:
        return load_settings().db_path
    resolved = Path(path).expanduser()
    return resolved if resolved.is_absolute() else PROJECT_ROOT / resolved


@contextmanager
def _configured_db_path(path: Path):
    """Route existing pipeline entrypoints to a selected DB for this process."""
    prior = os.environ.get("ALPHAGAP_DB_PATH")
    os.environ["ALPHAGAP_DB_PATH"] = str(path)
    try:
        yield
    finally:
        if prior is None:
            os.environ.pop("ALPHAGAP_DB_PATH", None)
        else:
            os.environ["ALPHAGAP_DB_PATH"] = prior


def clone_database(
    source_path: str | Path | None = None,
    output_path: str | Path | None = None,
) -> Path:
    """Create a transactionally consistent SQLite copy for rebuild testing."""
    source = _resolve_path(source_path)
    if output_path is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        output = PROJECT_ROOT / "db" / "backups" / f"alphagap-mechanism-{stamp}.sqlite"
    else:
        output = _resolve_path(output_path)
    if source.resolve() == output.resolve():
        raise ValueError("backup output path must differ from source database")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"backup output already exists: {output}")

    with sqlite3.connect(source) as source_conn, sqlite3.connect(output) as output_conn:
        source_conn.backup(output_conn)
    return output


def _table_count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def audit_library(db_path: str | Path | None = None) -> dict:
    """Return contamination and distribution checks for the Phase 1 library."""
    selected_db = _resolve_path(db_path)
    with _configured_db_path(selected_db):
        schema = db.verify_phase1_schema()
        with db.connect() as conn:
            source_observations = {
                r["source"]: {
                    "total": r["total"],
                    "trigger_eligible": r["trigger_eligible"],
                }
                for r in conn.execute(
                    """
                    SELECT source, COUNT(*) AS total,
                           SUM(eligible_for_daily_trigger) AS trigger_eligible
                    FROM paper_sources
                    GROUP BY source ORDER BY source
                    """
                ).fetchall()
            }
            evidence_only_papers = conn.execute(
                """
                SELECT COUNT(*) FROM papers p
                WHERE EXISTS (
                    SELECT 1 FROM paper_sources ps
                    WHERE ps.paper_id = p.id AND ps.role = 'evidence'
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM paper_sources ps
                    WHERE ps.paper_id = p.id AND ps.eligible_for_daily_trigger = 1
                )
                """
            ).fetchone()[0]
            orphan_evidence_papers = conn.execute(
                """
                SELECT COUNT(*) FROM papers p
                WHERE p.source IN ('openreview')
                  AND NOT EXISTS (
                      SELECT 1 FROM paper_sources ps WHERE ps.paper_id = p.id
                  )
                """
            ).fetchone()[0]
            duplicate_rows = conn.execute(
                """
                SELECT p1.id AS evidence_id, p2.id AS trigger_id, p1.title
                FROM papers p1
                JOIN papers p2 ON lower(trim(p1.title)) = lower(trim(p2.title))
                              AND p1.id != p2.id
                WHERE p1.source IN ('openreview')
                  AND p2.source IN ('arxiv', 'hf_daily')
                ORDER BY p1.title
                LIMIT 25
                """
            ).fetchall()
            non_ai_rows = conn.execute(
                """
                SELECT COALESCE(e.side, 'missing') AS side, COUNT(*) AS total
                FROM mechanism_memberships m
                LEFT JOIN paper_extractions e ON e.paper_id = m.paper_id
                WHERE m.membership_status = 'accepted'
                  AND COALESCE(e.side, 'missing') != 'ai'
                GROUP BY COALESCE(e.side, 'missing')
                ORDER BY side
                """
            ).fetchall()
            family_status = {
                r["canonical_status"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT canonical_status, COUNT(*) AS total
                    FROM mechanism_families GROUP BY canonical_status
                    """
                ).fetchall()
            }
            membership_status = {
                r["membership_status"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT membership_status, COUNT(*) AS total
                    FROM mechanism_memberships GROUP BY membership_status
                    """
                ).fetchall()
            }
            transfer_review_status = {
                r["relevance_status"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT relevance_status, COUNT(*) AS total
                    FROM mechanism_transfer_reviews GROUP BY relevance_status
                    """
                ).fetchall()
            }
            evidence_decision_status = {
                r["verdict"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT verdict, COUNT(*) AS total
                    FROM ai_evidence_decisions GROUP BY verdict
                    """
                ).fetchall()
            }
            evidence_link_status = {
                r["verdict"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT verdict, COUNT(*) AS total
                    FROM ai_evidence_links GROUP BY verdict
                    """
                ).fetchall()
            }
            counts = {
                table: _table_count(conn, table)
                for table in (
                    "papers",
                    "paper_sources",
                    "paper_external_ids",
                    "mechanism_families",
                    "mechanism_transfer_reviews",
                    "mechanism_memberships",
                    "fin_transfer_cells",
                    "ai_evidence_decisions",
                    "ai_evidence_links",
                )
            }

        from .mechanism_lib import maturity_distribution

        maturity = maturity_distribution()

    return {
        "database": str(selected_db),
        "schema": schema,
        "counts": counts,
        "source_observations": source_observations,
        "evidence_only_papers": evidence_only_papers,
        "orphan_evidence_papers": orphan_evidence_papers,
        "exact_title_cross_source_duplicates": {
            "count": len(duplicate_rows),
            "sample": [dict(r) for r in duplicate_rows],
        },
        "accepted_non_ai_memberships": {r["side"]: r["total"] for r in non_ai_rows},
        "family_status": family_status,
        "transfer_review_status": transfer_review_status,
        "membership_status": membership_status,
        "evidence_decision_status": evidence_decision_status,
        "evidence_link_status": evidence_link_status,
        "maturity": maturity,
    }


def build_progress(
    db_path: str | Path | None = None,
    *,
    total: int | None = None,
    now: datetime | None = None,
) -> dict:
    """Read-only progress and ETA for an evidence-to-family assignment run."""
    selected_db = _resolve_path(db_path)
    with _configured_db_path(selected_db):
        with db.connect() as conn:
            if total is None:
                total = conn.execute(
                    """
                    SELECT COUNT(DISTINCT p.id)
                    FROM papers p
                    JOIN paper_extractions e ON e.paper_id = p.id
                    WHERE e.extraction_status IN ('l1_done', 'l2_done')
                      AND e.side = 'ai'
                      AND e.mechanism_description_json IS NOT NULL
                      AND e.mechanism_description_json != ''
                      AND e.mechanism_description_json != '{}'
                      AND EXISTS (
                          SELECT 1 FROM paper_sources ps
                          WHERE ps.paper_id = p.id AND ps.role = 'evidence'
                      )
                    """
                ).fetchone()[0]
            statuses = {
                r["relevance_status"]: r["total"]
                for r in conn.execute(
                    """
                    SELECT relevance_status, COUNT(*) AS total
                    FROM mechanism_transfer_reviews
                    GROUP BY relevance_status
                    """
                ).fetchall()
            }
            timing = conn.execute(
                """
                SELECT MIN(assessed_at) AS first_assessed,
                       MAX(assessed_at) AS last_assessed,
                       COUNT(*) AS done
                FROM mechanism_transfer_reviews
                """
            ).fetchone()
            families = _table_count(conn, "mechanism_families")
            memberships = _table_count(conn, "mechanism_memberships")

    done = timing["done"]
    remaining = max(total - done, 0)
    result = {
        "database": str(selected_db),
        "total": total,
        "done": done,
        "remaining": remaining,
        "percent": round((done / total * 100) if total else 0.0, 1),
        "transfer_review_status": statuses,
        "families": families,
        "memberships": memberships,
        "first_assessed": timing["first_assessed"],
        "last_assessed": timing["last_assessed"],
        "rate_per_hour": None,
        "eta_seconds": None,
        "estimated_completion": None,
    }
    if done and timing["first_assessed"]:
        as_of = now or datetime.now()
        started = datetime.fromisoformat(timing["first_assessed"])
        elapsed_seconds = max((as_of - started).total_seconds(), 1.0)
        rate_per_hour = done / elapsed_seconds * 3600
        eta_seconds = remaining / rate_per_hour * 3600 if rate_per_hour else None
        result["rate_per_hour"] = round(rate_per_hour, 1)
        result["eta_seconds"] = round(eta_seconds) if eta_seconds is not None else None
        if eta_seconds is not None:
            result["estimated_completion"] = (
                as_of + timedelta(seconds=eta_seconds)
            ).isoformat(timespec="seconds")
    return result


def format_progress(report: dict, *, width: int = 30) -> str:
    """Format a compact terminal progress view from ``build_progress``."""
    total = report["total"]
    done = report["done"]
    filled = round(width * done / total) if total else 0
    bar = "#" * filled + "-" * (width - filled)
    lines = [
        f"Mechanism family build [{bar}] {done}/{total} ({report['percent']:.1f}%)",
        "Reviews: "
        + " | ".join(
            f"{key}={report['transfer_review_status'].get(key, 0)}"
            for key in ("transferable", "ambiguous", "not_relevant")
        ),
        f"Library: families={report['families']} | memberships={report['memberships']}",
    ]
    rate = report.get("rate_per_hour")
    eta_seconds = report.get("eta_seconds")
    if rate is not None and eta_seconds is not None:
        hours, remainder = divmod(eta_seconds, 3600)
        minutes = remainder // 60
        lines.append(
            f"Rate: {rate:.1f} papers/hour | ETA: {hours}h {minutes:02d}m "
            f"| complete around {report['estimated_completion']}"
        )
    return "\n".join(lines)


def _delete_for_papers(conn, table: str, paper_ids: list[str]) -> int:
    if not paper_ids:
        return 0
    placeholders = ",".join("?" for _ in paper_ids)
    result = conn.execute(
        f"DELETE FROM {table} WHERE paper_id IN ({placeholders})",
        tuple(paper_ids),
    )
    return result.rowcount


def _paper_for_signal_recompute(row) -> dict:
    try:
        raw_meta = json.loads(row["raw_meta_json"] or "{}")
    except json.JSONDecodeError:
        raw_meta = {}
    try:
        authors = json.loads(row["authors_json"] or "[]")
    except json.JSONDecodeError:
        authors = []
    return {
        "source": row["source"],
        "title": row["title"],
        "abstract": row["abstract"] or "",
        "authors": authors,
        "arxiv_categories": (row["arxiv_categories"] or "").split(","),
        "raw_meta": raw_meta,
    }


def reset_rebuildable_library(
    db_path: str | Path | None = None,
    *,
    allow_human_confirmed: bool = False,
) -> dict:
    """Remove rebuildable evidence and all automatic family assignments.

    Trigger papers and their extractions remain. Evidence-only OpenReview
    canonical rows are removed because retaining them without their evidence
    observations would cause the migration compatibility guard to treat them
    as legacy daily papers.
    """
    selected_db = _resolve_path(db_path)
    sources = REBUILDABLE_EVIDENCE_SOURCES
    placeholders = ",".join("?" for _ in sources)

    with _configured_db_path(selected_db):
        db.init_schema()
        with db.connect() as conn:
            protected = conn.execute(
                """
                SELECT COUNT(*) FROM mechanism_families
                WHERE canonical_status = 'human_confirmed'
                   OR last_human_review_at IS NOT NULL
                """
            ).fetchone()[0]
            if protected and not allow_human_confirmed:
                raise RuntimeError(
                    f"refusing reset: {protected} family rows show human review; "
                    "rerun with --allow-human-confirmed only after explicit review"
                )

            evidence_rows = conn.execute(
                f"""
                SELECT DISTINCT p.id
                FROM papers p
                LEFT JOIN paper_sources ps ON ps.paper_id = p.id
                WHERE (
                    p.source IN ({placeholders})
                    OR (ps.source IN ({placeholders}) AND ps.role = 'evidence')
                )
                  AND NOT EXISTS (
                      SELECT 1 FROM paper_sources t
                      WHERE t.paper_id = p.id AND t.eligible_for_daily_trigger = 1
                  )
                """,
                tuple(sources) + tuple(sources),
            ).fetchall()
            remove_paper_ids = [r["id"] for r in evidence_rows]
            retained_rows = conn.execute(
                f"""
                SELECT DISTINCT p.*
                FROM papers p
                JOIN paper_sources ps ON ps.paper_id = p.id
                WHERE ps.source IN ({placeholders}) AND ps.role = 'evidence'
                  AND EXISTS (
                      SELECT 1 FROM paper_sources t
                      WHERE t.paper_id = p.id AND t.eligible_for_daily_trigger = 1
                  )
                """,
                tuple(sources),
            ).fetchall()

            deleted_evidence_links = conn.execute("DELETE FROM ai_evidence_links").rowcount
            deleted_evidence_decisions = conn.execute("DELETE FROM ai_evidence_decisions").rowcount
            deleted_memberships = conn.execute("DELETE FROM mechanism_memberships").rowcount
            deleted_families = conn.execute("DELETE FROM mechanism_families").rowcount
            deleted_transfer_reviews = conn.execute(
                "DELETE FROM mechanism_transfer_reviews"
            ).rowcount

            deleted_children = {}
            for table in ("paper_concepts", "citation_snapshots", "paper_extractions", "paper_signals",
                          "paper_external_ids", "paper_sources"):
                deleted_children[table] = _delete_for_papers(conn, table, remove_paper_ids)
            if remove_paper_ids:
                placeholders_ids = ",".join("?" for _ in remove_paper_ids)
                deleted_papers = conn.execute(
                    f"DELETE FROM papers WHERE id IN ({placeholders_ids})",
                    tuple(remove_paper_ids),
                ).rowcount
            else:
                deleted_papers = 0

            removed_retained_observations = conn.execute(
                f"DELETE FROM paper_sources WHERE source IN ({placeholders}) AND role = 'evidence'",
                tuple(sources),
            ).rowcount
            removed_retained_external_ids = conn.execute(
                f"DELETE FROM paper_external_ids WHERE source IN ({placeholders})",
                tuple(sources),
            ).rowcount

            recomputed_signals = 0
            for row in retained_rows:
                db.upsert_signals(conn, row["id"], compute_signals(_paper_for_signal_recompute(row)).to_dict())
                recomputed_signals += 1

    return {
        "database": str(selected_db),
        "deleted_families": deleted_families,
        "deleted_memberships": deleted_memberships,
        "deleted_transfer_reviews": deleted_transfer_reviews,
        "deleted_evidence_decisions": deleted_evidence_decisions,
        "deleted_evidence_links": deleted_evidence_links,
        "deleted_evidence_only_papers": deleted_papers,
        "deleted_evidence_only_children": deleted_children,
        "removed_evidence_observations_on_retained_trigger_papers": removed_retained_observations,
        "removed_external_ids_on_retained_trigger_papers": removed_retained_external_ids,
        "recomputed_trigger_signals": recomputed_signals,
    }


def rebuild_library(
    db_path: str | Path | None,
    *,
    years: list[int],
    decision_filter: list[str],
    limit: int | None,
    max_l1: int,
    assign_limit: int,
    assign_evidence_only: bool = False,
    evidence_snapshot: str | Path | None = None,
    allow_human_confirmed: bool = False,
) -> dict:
    """Back up, reset, reimport conference evidence, and optionally assign families."""
    selected_db = _resolve_path(db_path)
    backup = clone_database(selected_db)
    with _configured_db_path(selected_db):
        reset = reset_rebuildable_library(
            selected_db,
            allow_human_confirmed=allow_human_confirmed,
        )
        from .conf_backfill import backfill_iclr, replay_evidence_snapshot

        if evidence_snapshot:
            backfill = replay_evidence_snapshot(_resolve_path(evidence_snapshot))
            if max_l1 > 0:
                from .ingest import extract_pending

                backfill["l1_extract"] = extract_pending(
                    max_l1=max_l1,
                    max_l2=0,
                    include_evidence=True,
                    evidence_only=True,
                )
        else:
            # Keep stdout reserved for this command's final JSON report; the
            # OpenReview SDK prints rate-limit retry diagnostics directly.
            with redirect_stdout(sys.stderr):
                backfill = backfill_iclr(
                    years=years,
                    decision_filter=decision_filter,
                    limit=limit,
                    run_l1=max_l1 > 0,
                    max_l1=max_l1,
                )
        assignment = None
        if assign_limit > 0:
            from .mechanism_lib import assign_pending

            with redirect_stdout(sys.stderr):
                assignment = assign_pending(
                    limit=assign_limit,
                    evidence_only=assign_evidence_only,
                )
        post_audit = audit_library(selected_db)
    return {
        "database": str(selected_db),
        "backup": str(backup),
        "reset": reset,
        "backfill": backfill,
        "assignment": assignment,
        "post_audit": post_audit,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Maintain the AI mechanism evidence library.")
    sub = parser.add_subparsers(dest="command", required=True)

    audit_cmd = sub.add_parser("audit", help="read-only quality report")
    audit_cmd.add_argument("--db-path")

    progress_cmd = sub.add_parser("progress", help="show assignment progress and ETA")
    progress_cmd.add_argument("--db-path")
    progress_cmd.add_argument("--total", type=int)
    progress_cmd.add_argument("--json", action="store_true")

    clone_cmd = sub.add_parser("clone", help="make a SQLite backup/validation copy")
    clone_cmd.add_argument("--db-path")
    clone_cmd.add_argument("--out", required=True)

    reset_cmd = sub.add_parser("reset", help="clear rebuildable evidence/families")
    reset_cmd.add_argument("--db-path")
    reset_cmd.add_argument("--allow-human-confirmed", action="store_true")
    reset_cmd.add_argument("--confirm", action="store_true")

    rebuild_cmd = sub.add_parser("rebuild", help="backup, reset, reimport, and audit")
    rebuild_cmd.add_argument("--db-path")
    rebuild_cmd.add_argument("--years", nargs="+", type=int, default=[2025])
    rebuild_cmd.add_argument("--decisions", nargs="+", default=["oral", "spotlight"])
    rebuild_cmd.add_argument("--limit", type=int)
    rebuild_cmd.add_argument(
        "--evidence-snapshot",
        help="replay saved OpenReview evidence from this DB instead of refetching it",
    )
    rebuild_cmd.add_argument("--max-l1", type=int, default=0)
    rebuild_cmd.add_argument("--assign-limit", type=int, default=0)
    rebuild_cmd.add_argument(
        "--assign-evidence-only",
        action="store_true",
        help="validation mode: assign only imported evidence papers, not the full AI corpus",
    )
    rebuild_cmd.add_argument("--allow-human-confirmed", action="store_true")
    rebuild_cmd.add_argument("--confirm", action="store_true")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.command == "audit":
        result = audit_library(args.db_path)
    elif args.command == "progress":
        result = build_progress(args.db_path, total=args.total)
        if not args.json:
            print(format_progress(result))
            return
    elif args.command == "clone":
        result = {"clone": str(clone_database(args.db_path, args.out))}
    elif args.command == "reset":
        if not args.confirm:
            parser.error("reset requires --confirm because it deletes derived data")
        result = reset_rebuildable_library(
            args.db_path,
            allow_human_confirmed=args.allow_human_confirmed,
        )
    else:
        if not args.confirm:
            parser.error("rebuild requires --confirm because it deletes derived data")
        result = rebuild_library(
            args.db_path,
            years=args.years,
            decision_filter=args.decisions,
            limit=args.limit,
            max_l1=args.max_l1,
            assign_limit=args.assign_limit,
            assign_evidence_only=args.assign_evidence_only,
            evidence_snapshot=args.evidence_snapshot,
            allow_human_confirmed=args.allow_human_confirmed,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
