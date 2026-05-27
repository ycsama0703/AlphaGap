"""Conference paper backfill — write OpenReview records into the DB as evidence.

Per upgrade plan v2 §6 task 1.6: pull peer-reviewed conference papers and
land them as `role='evidence'` observations so they enrich AI mechanism
family maturity without entering daily gap candidate queries.

Pipeline
--------
1. Fetch via pipeline.fetchers.openreview.fetch_evidence(venue, year, ...).
2. For each PaperRecord:
   - Look up by external_id (openreview note id) → dedup re-runs.
   - If new, insert into `papers` (using canonical fields).
   - Always upsert `paper_external_ids` row (openreview → paper_id).
   - Always upsert `paper_sources` row with role='evidence',
     eligible_for_daily_trigger=0, venue, decision, review_scores.
   - Always upsert `paper_signals` with is_candidate=1 + priority_score
     scaled by decision (oral=10, spotlight=8, poster=5). This makes
     the paper eligible for L1 extraction but the TRIGGER_ELIGIBILITY_GUARD
     keeps it out of daily/trend queries.
3. Optionally trigger L1 extraction on newly-ingested rows.

Idempotency
-----------
All inserts use the UNIQUE keys from the Phase 1 schema. Re-running this
backfill is safe — it updates last_observed_at but doesn't duplicate.

CLI
---
    python -m pipeline.conf_backfill iclr 2025 2026                # all oral+spotlight
    python -m pipeline.conf_backfill iclr 2025 --limit 50          # smoke test
    python -m pipeline.conf_backfill iclr 2025 2026 --skip-l1      # ingest only
"""
from __future__ import annotations

import argparse
import json
import logging
import sqlite3
import sys
from contextlib import redirect_stdout
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from . import db
from .fetchers import openreview as openreview_fetcher
from .fetchers.arxiv import PaperRecord


log = logging.getLogger(__name__)


# Map decision → priority_score for paper_signals.
# Higher score = earlier L1 extraction in the queue.
_DECISION_PRIORITY = {
    "oral":      10.0,
    "spotlight":  8.0,
    "poster":     5.0,
    "reject":     0.0,
    "withdraw":   0.0,
    "desk_reject": 0.0,
}


def _record_id_for_storage(rec: PaperRecord) -> str:
    """Canonical id for the `papers` table.

    Prefer arxiv_id when known (lets future HF / arxiv re-fetch merge into
    the same paper row). Fall back to `openreview:<note_id>` otherwise.
    """
    if rec.arxiv_id:
        return rec.arxiv_id
    return rec.id  # already prefixed with 'openreview:' by the fetcher


def _persist_paper_row(conn, rec: PaperRecord, paper_id: str) -> bool:
    """Insert into `papers` if not present. Returns True if a new row inserted."""
    existing = conn.execute(
        "SELECT 1 FROM papers WHERE id = ?", (paper_id,)
    ).fetchone()
    if existing:
        return False

    affiliations = "; ".join(
        aff for a in rec.authors for aff in (a.get("affiliations") or [])
    )
    conn.execute(
        """
        INSERT INTO papers
            (id, source, arxiv_id, doi, title, abstract, authors_json,
             affiliations, publication_date, arxiv_categories, citations, url,
             fetched_at, raw_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            rec.source,
            rec.arxiv_id,
            None,
            rec.title,
            rec.abstract,
            json.dumps(rec.authors, ensure_ascii=False),
            affiliations,
            rec.publication_date.isoformat(),
            ",".join(rec.arxiv_categories or []),
            0,
            rec.url,
            datetime.now().isoformat(timespec="seconds"),
            json.dumps(rec.raw_meta, ensure_ascii=False),
        ),
    )
    return True


def _find_existing_canonical_id(conn, rec: PaperRecord) -> str | None:
    """Find an existing trigger paper that represents an OpenReview record.

    ArXiv identifiers are authoritative. For records where OpenReview does
    not expose one, merge only an unambiguous exact-title match from the
    trigger corpus; ambiguous titles remain separate for manual review.
    """
    if rec.arxiv_id:
        row = conn.execute(
            """
            SELECT id FROM papers
            WHERE id = ? OR arxiv_id = ?
            ORDER BY CASE WHEN source IN ('arxiv', 'hf_daily') THEN 0 ELSE 1 END
            LIMIT 1
            """,
            (rec.arxiv_id, rec.arxiv_id),
        ).fetchone()
        if row:
            return row["id"]

    title_matches = conn.execute(
        """
        SELECT id FROM papers
        WHERE source IN ('arxiv', 'hf_daily')
          AND lower(trim(title)) = lower(trim(?))
        """,
        (rec.title,),
    ).fetchall()
    if len(title_matches) == 1:
        return title_matches[0]["id"]
    return None


def _ensure_signals_row(conn, paper_id: str, decision: str | None) -> None:
    """Add OpenReview priority without discarding existing trigger signals."""
    priority = _DECISION_PRIORITY.get((decision or "").lower(), 1.0)
    existing = conn.execute(
        "SELECT is_candidate, priority_score, signals_json FROM paper_signals WHERE paper_id = ?",
        (paper_id,),
    ).fetchone()
    try:
        signals = json.loads(existing["signals_json"] or "{}") if existing else {}
    except json.JSONDecodeError:
        signals = {}
    signals.update({
        "source_observation_role": "evidence",
        "openreview_decision": decision,
        "openreview_priority": priority,
    })
    is_candidate = max(existing["is_candidate"] if existing else 0, 1 if priority > 0 else 0)
    combined_priority = max(existing["priority_score"] if existing else 0.0, priority)
    conn.execute(
        """
        INSERT INTO paper_signals
            (paper_id, is_candidate, priority_score, signals_json, computed_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(paper_id) DO UPDATE SET
            is_candidate = excluded.is_candidate,
            priority_score = excluded.priority_score,
            signals_json = excluded.signals_json,
            computed_at = excluded.computed_at
        """,
        (
            paper_id,
            is_candidate,
            combined_priority,
            json.dumps(signals, ensure_ascii=False),
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def ingest_records(records: Iterable[PaperRecord]) -> dict:
    """Write OpenReview records into the DB. Returns stats dict."""
    stats = {
        "fetched": 0,
        "inserted_papers": 0,
        "matched_existing": 0,
        "source_observations_written": 0,
        "errors": 0,
    }

    with db.connect() as conn:
        for rec in records:
            stats["fetched"] += 1
            try:
                openreview_id = rec.raw_meta.get("openreview_id")
                if not openreview_id:
                    log.warning("skip rec without openreview_id: %s", rec.title[:50])
                    stats["errors"] += 1
                    continue

                # 1. Dedup by external_id first (re-run safety).
                existing_id = db.find_paper_by_external_id(
                    conn, "openreview", openreview_id
                )
                if existing_id:
                    paper_id = existing_id
                    is_new = False
                else:
                    paper_id = _find_existing_canonical_id(conn, rec)
                    if paper_id:
                        is_new = False
                    else:
                        paper_id = _record_id_for_storage(rec)
                        is_new = _persist_paper_row(conn, rec, paper_id)

                if is_new:
                    stats["inserted_papers"] += 1
                else:
                    stats["matched_existing"] += 1

                # Evidence attached to an old paper must not make it fail the
                # daily-trigger guard simply because its trigger predates the
                # paper_sources table.
                if not is_new:
                    db.ensure_legacy_trigger_observation(conn, paper_id)

                # 2. Register external ids (idempotent).
                db.upsert_external_id(
                    conn,
                    source="openreview",
                    external_id=openreview_id,
                    paper_id=paper_id,
                )
                if rec.arxiv_id:
                    db.upsert_external_id(
                        conn,
                        source="arxiv",
                        external_id=rec.arxiv_id,
                        paper_id=paper_id,
                    )

                # 3. Write source observation as evidence (idempotent).
                db.upsert_paper_source(
                    conn,
                    paper_id=paper_id,
                    source="openreview",
                    source_record_id=openreview_id,
                    role="evidence",
                    eligible_for_daily_trigger=0,
                    venue=rec.raw_meta.get("venue"),
                    decision=rec.raw_meta.get("decision"),
                    review_scores=rec.raw_meta.get("review_scores"),
                    raw_meta={
                        "openreview_url": rec.raw_meta.get("openreview_url"),
                        "venue_short": rec.raw_meta.get("venue_short"),
                        "venue_year": rec.raw_meta.get("venue_year"),
                        "paperhash": rec.raw_meta.get("paperhash"),
                    },
                )
                stats["source_observations_written"] += 1

                # 4. Ensure paper_signals row exists so L1 picks it up.
                _ensure_signals_row(conn, paper_id, rec.raw_meta.get("decision"))

            except Exception as e:
                log.exception("ingest failed for %s: %s", rec.id, e)
                stats["errors"] += 1

    return stats


def records_from_snapshot(
    snapshot_path: str | Path,
    *,
    source: str = "openreview",
) -> list[PaperRecord]:
    """Read saved evidence observations from a prior SQLite database snapshot."""
    conn = sqlite3.connect(Path(snapshot_path).expanduser())
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT p.id, p.arxiv_id, p.title, p.abstract, p.authors_json,
                   p.publication_date, p.arxiv_categories, p.url, p.raw_meta_json,
                   ps.source_record_id, ps.venue, ps.decision, ps.review_scores,
                   ps.raw_meta_json AS observation_meta_json
            FROM paper_sources ps
            JOIN papers p ON p.id = ps.paper_id
            WHERE ps.source = ? AND ps.role = 'evidence'
            ORDER BY ps.id
            """,
            (source,),
        ).fetchall()
    finally:
        conn.close()

    records: list[PaperRecord] = []
    for row in rows:
        try:
            authors = json.loads(row["authors_json"] or "[]")
        except json.JSONDecodeError:
            authors = []
        try:
            paper_meta = json.loads(row["raw_meta_json"] or "{}")
        except json.JSONDecodeError:
            paper_meta = {}
        try:
            observation_meta = json.loads(row["observation_meta_json"] or "{}")
        except json.JSONDecodeError:
            observation_meta = {}
        try:
            review_scores = json.loads(row["review_scores"] or "[]")
        except json.JSONDecodeError:
            review_scores = []
        try:
            publication_date = date.fromisoformat((row["publication_date"] or "")[:10])
        except ValueError:
            publication_date = date.today()
        raw_meta = {
            **paper_meta,
            **observation_meta,
            "openreview_id": row["source_record_id"],
            "venue": row["venue"],
            "decision": row["decision"],
            "review_scores": review_scores,
        }
        records.append(PaperRecord(
            id=row["arxiv_id"] or f"openreview:{row['source_record_id']}",
            source="openreview",
            arxiv_id=row["arxiv_id"],
            title=row["title"],
            abstract=row["abstract"] or "",
            authors=authors,
            publication_date=publication_date,
            arxiv_categories=(row["arxiv_categories"] or "").split(",")
            if row["arxiv_categories"] else [],
            url=row["url"] or raw_meta.get("openreview_url") or "",
            raw_meta=raw_meta,
        ))
    return records


def replay_evidence_snapshot(snapshot_path: str | Path) -> dict:
    """Re-ingest known evidence from a backup without refetching OpenReview."""
    records = records_from_snapshot(snapshot_path)
    log.info("=== replaying %d OpenReview records from %s ===", len(records), snapshot_path)
    ingest_stats = ingest_records(records)
    return {
        "fetch_total": len(records),
        "source": "snapshot",
        "snapshot_path": str(snapshot_path),
        "ingest": ingest_stats,
        "extractions": restore_extractions_from_snapshot(snapshot_path),
    }


def restore_extractions_from_snapshot(
    snapshot_path: str | Path,
    *,
    source: str = "openreview",
) -> dict:
    """Restore L1/L2 extraction output for replayed evidence where not present.

    Family assignment is intentionally not restored because it is the derived
    state being rebuilt. If evidence merged into an existing trigger paper
    that already has an extraction, the trigger paper's extraction wins.
    """
    source_conn = sqlite3.connect(Path(snapshot_path).expanduser())
    source_conn.row_factory = sqlite3.Row
    try:
        rows = source_conn.execute(
            """
            SELECT ps.source_record_id, e.*
            FROM paper_sources ps
            JOIN paper_extractions e ON e.paper_id = ps.paper_id
            WHERE ps.source = ? AND ps.role = 'evidence'
              AND e.extraction_status IN ('l1_done', 'l2_done')
            """,
            (source,),
        ).fetchall()
    finally:
        source_conn.close()

    stats = {"available": len(rows), "restored": 0, "kept_existing": 0, "missing_target": 0}
    with db.connect() as conn:
        for row in rows:
            paper_id = db.find_paper_by_external_id(conn, source, row["source_record_id"])
            if not paper_id:
                stats["missing_target"] += 1
                continue
            existing = conn.execute(
                """
                SELECT extraction_status FROM paper_extractions
                WHERE paper_id = ? AND extraction_status IN ('l1_done', 'l2_done')
                """,
                (paper_id,),
            ).fetchone()
            if existing:
                stats["kept_existing"] += 1
                continue
            l1 = {
                "side": row["side"],
                "method_primary": json.loads(row["method_primary_json"] or "[]"),
                "domain": json.loads(row["domain_json"] or "[]"),
                "tags": json.loads(row["tags_json"] or "[]"),
                "mechanism_description": json.loads(
                    row["mechanism_description_json"] or "{}"
                ),
            }
            db.upsert_extraction_l1(conn, paper_id, l1)
            if row["extraction_status"] == "l2_done":
                db.upsert_extraction_l2(conn, paper_id, {
                    "building_blocks": json.loads(row["building_blocks_json"] or "[]"),
                    "claims": json.loads(row["claims_json"] or "[]"),
                    "benchmarks": json.loads(row["benchmarks_json"] or "[]"),
                })
            stats["restored"] += 1
    return stats


def backfill_iclr(years: list[int],
                  decision_filter: list[str] | None = None,
                  limit: int | None = None,
                  run_l1: bool = True,
                  max_l1: int = 1000) -> dict:
    """End-to-end backfill: fetch + ingest + (optional) L1 extract."""
    decision_filter = decision_filter or ["oral", "spotlight"]

    total_records: list[PaperRecord] = []
    per_year: dict[int, int] = {}
    for y in years:
        log.info("=== fetching ICLR %d %s ===", y, decision_filter)
        recs = openreview_fetcher.fetch_evidence(
            "ICLR", y,
            decision_filter=decision_filter,
            limit=limit,
            fetch_review_scores=True,
        )
        log.info("ICLR %d: %d records", y, len(recs))
        per_year[y] = len(recs)
        total_records.extend(recs)
        if limit and len(total_records) >= limit:
            break

    if limit:
        total_records = total_records[:limit]

    log.info("=== ingesting %d records ===", len(total_records))
    ingest_stats = ingest_records(total_records)

    result = {
        "fetch_total": len(total_records),
        "fetch_per_year": per_year,
        "ingest": ingest_stats,
    }

    if run_l1:
        log.info("=== running L1 extraction (max %d) ===", max_l1)
        from .ingest import extract_pending
        extract_stats = extract_pending(
            max_l1=max_l1,
            max_l2=0,
            include_evidence=True,
            evidence_only=True,
        )
        result["l1_extract"] = extract_stats

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _main():
    p = argparse.ArgumentParser(
        prog="python -m pipeline.conf_backfill",
        description="Backfill conference papers as evidence (no daily trigger).",
    )
    p.add_argument("venue", choices=["iclr"], help="conference name")
    p.add_argument("years", nargs="+", type=int, help="years to backfill")
    p.add_argument("--decisions", nargs="+", default=["oral", "spotlight"],
                   help="decision filter (default: oral spotlight)")
    p.add_argument("--limit", type=int, default=None,
                   help="cap total records (for smoke test)")
    p.add_argument("--skip-l1", action="store_true",
                   help="ingest only, skip L1 extraction")
    p.add_argument("--max-l1", type=int, default=1000,
                   help="max L1 extractions to run (default: 1000)")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.venue != "iclr":
        print(f"ERROR: only 'iclr' supported in this Phase", file=sys.stderr)
        sys.exit(2)

    # openreview-py can print retry diagnostics to stdout; reserve stdout for
    # the machine-readable result emitted below.
    with redirect_stdout(sys.stderr):
        result = backfill_iclr(
            years=args.years,
            decision_filter=args.decisions,
            limit=args.limit,
            run_l1=not args.skip_l1,
            max_l1=args.max_l1,
        )

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    _main()
