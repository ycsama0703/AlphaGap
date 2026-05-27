"""SQLite schema + queries.

Tables:
  papers          — L3 cache of fetched papers (re-fetchable)
  paper_extractions — L1/L2 LLM extraction results, joined by paper_id
  paper_signals   — filter signals, used for downstream prioritization
  concepts        — normalized concept entities (built incrementally)
  paper_concepts  — many-to-many between papers and concepts
  daily_runs      — pipeline execution log
"""
from __future__ import annotations

import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any

from .config import load_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS papers (
    id              TEXT PRIMARY KEY,             -- arxiv_id or s2 paperId
    source          TEXT NOT NULL,                -- 'arxiv' | 'hf_daily' | 'ssrn' | 's2'
    arxiv_id        TEXT,
    doi             TEXT,
    title           TEXT NOT NULL,
    abstract        TEXT,
    authors_json    TEXT,                         -- [{"name":"...", "affiliations":[...]}, ...]
    affiliations    TEXT,                         -- normalized "; "-joined for FTS
    publication_date TEXT,                        -- ISO date
    arxiv_categories TEXT,
    citations       INTEGER DEFAULT 0,
    url             TEXT,
    fetched_at      TEXT NOT NULL,
    raw_meta_json   TEXT
);

CREATE INDEX IF NOT EXISTS idx_papers_date ON papers(publication_date DESC);
CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);

CREATE TABLE IF NOT EXISTS paper_signals (
    paper_id        TEXT PRIMARY KEY REFERENCES papers(id),
    is_candidate    INTEGER NOT NULL,             -- 0/1
    priority_score  REAL NOT NULL,
    signals_json    TEXT NOT NULL,
    computed_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_signals_priority ON paper_signals(priority_score DESC);

CREATE TABLE IF NOT EXISTS paper_extractions (
    paper_id        TEXT PRIMARY KEY REFERENCES papers(id),
    side            TEXT,                         -- 'ai' | 'fin' | 'both'
    method_primary_json TEXT,                     -- ["..."]
    domain_json     TEXT,
    tags_json       TEXT,
    mechanism_description_json TEXT,              -- L1: {one_liner, what_problem, contrast, prerequisites}
    building_blocks_json TEXT,                    -- L2
    claims_json     TEXT,                         -- L2
    benchmarks_json TEXT,                         -- L2
    l1_extracted_at TEXT,
    l2_extracted_at TEXT,
    extraction_status TEXT DEFAULT 'pending'      -- pending|l1_done|l2_done|failed
);

CREATE TABLE IF NOT EXISTS concepts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,         -- canonical lowercase
    aliases_json    TEXT,
    side            TEXT NOT NULL,
    first_seen      TEXT,
    last_seen       TEXT,
    paper_count_total INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_concepts_side ON concepts(side);

CREATE TABLE IF NOT EXISTS paper_concepts (
    paper_id        TEXT REFERENCES papers(id),
    concept_id      INTEGER REFERENCES concepts(id),
    role            TEXT,                         -- 'method_primary' | 'domain' | 'tag' | 'building_block'
    PRIMARY KEY (paper_id, concept_id, role)
);

CREATE TABLE IF NOT EXISTS citation_snapshots (
    paper_id        TEXT NOT NULL REFERENCES papers(id),
    snapshot_date   TEXT NOT NULL,                -- ISO date 'YYYY-MM-DD'
    citation_count  INTEGER NOT NULL,
    influential_citation_count INTEGER DEFAULT 0,
    PRIMARY KEY (paper_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_cite_snap_date ON citation_snapshots(snapshot_date);
CREATE INDEX IF NOT EXISTS idx_cite_snap_paper ON citation_snapshots(paper_id);

CREATE TABLE IF NOT EXISTS daily_runs (
    run_date        TEXT PRIMARY KEY,
    started_at      TEXT,
    finished_at     TEXT,
    papers_fetched  INTEGER,
    papers_filtered INTEGER,
    gaps_theoretical INTEGER,
    gaps_engineering INTEGER,
    gaps_accepted   INTEGER,
    mapping_actions_proposed INTEGER,
    cost_usd        REAL,
    status          TEXT,                         -- 'success' | 'partial' | 'failed'
    error_log       TEXT
);

-- =========================================================================
-- Phase 1 of mechanism evidence library upgrade (2026-05-26 v2 plan).
-- These tables add multi-source observations and persistent mechanism
-- families WITHOUT modifying the existing `papers` table. Legacy code
-- paths continue to read papers as before; new code paths use the tables
-- below. See UPGRADE_PLAN_2026-05-26_v2.md §3.1.
-- =========================================================================

-- Stable external identifiers for cross-source dedupe / identity merge.
-- e.g. same paper can have arxiv:2401.12345 + openreview:abc123 + doi:10.x/y
CREATE TABLE IF NOT EXISTS paper_external_ids (
    source          TEXT NOT NULL,                -- 'arxiv' | 'openreview' | 'doi' | 's2'
    external_id     TEXT NOT NULL,
    paper_id        TEXT NOT NULL REFERENCES papers(id),
    observed_at     TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_external_ids_paper
    ON paper_external_ids(paper_id);

-- Multi-source observations of the same paper. Idempotent on re-fetch
-- via (paper_id, source, source_record_id) UNIQUE.
-- role + eligible_for_daily_trigger keep historical evidence from
-- silently entering the daily trigger pool.
CREATE TABLE IF NOT EXISTS paper_sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id        TEXT NOT NULL REFERENCES papers(id),
    source          TEXT NOT NULL,                -- 'arxiv' | 'hf_daily' | 'openreview' | 'neurips' | ...
    source_record_id TEXT NOT NULL,               -- stable source-local key (e.g. OpenReview note id)
    role            TEXT NOT NULL DEFAULT 'trigger',  -- 'trigger' | 'evidence' | 'both'
    eligible_for_daily_trigger INTEGER NOT NULL DEFAULT 0,
    venue           TEXT,                         -- 'ICLR 2026' | 'NeurIPS 2024' | null
    decision        TEXT,                         -- 'oral' | 'spotlight' | 'poster' | 'reject' | null
    review_scores   TEXT,                         -- JSON array, if available
    first_observed_at TEXT NOT NULL,              -- when WE first saw this observation
    last_observed_at TEXT NOT NULL,               -- updated on weekly re-fetch
    raw_meta_json   TEXT,                         -- source-specific blob (latest)
    UNIQUE (paper_id, source, source_record_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_sources_paper
    ON paper_sources(paper_id);
CREATE INDEX IF NOT EXISTS idx_paper_sources_source
    ON paper_sources(source);
CREATE INDEX IF NOT EXISTS idx_paper_sources_trigger
    ON paper_sources(eligible_for_daily_trigger);

-- Canonical AI mechanism family records. AI-side only; do NOT create a
-- parallel structure for Fin (knowledge/fin_fields/ stays the authority).
CREATE TABLE IF NOT EXISTS mechanism_families (
    family_id                 TEXT PRIMARY KEY,    -- 'ai-mech-2026-001' style
    representative_one_liner  TEXT NOT NULL,
    what_problem              TEXT,
    shared_approach           TEXT,
    contrast_to_prior         TEXT,
    created_at                TEXT NOT NULL,
    last_updated              TEXT NOT NULL,
    last_human_review_at      TEXT,                -- null if never human-reviewed
    canonical_status          TEXT NOT NULL DEFAULT 'auto_draft',
                              -- 'auto_draft' | 'human_confirmed' | 'merged' | 'split' | 'deprecated'
    merged_into               TEXT,                -- target family_id if status='merged'
    notes                     TEXT
);

CREATE INDEX IF NOT EXISTS idx_families_status
    ON mechanism_families(canonical_status);

-- Evidence-screening record before family assignment. L1 extraction records
-- what the paper itself did; this table records whether that mechanism can
-- support a concrete bridge to one of the maintained finance boundaries and,
-- if so, the reusable family-level abstraction used for clustering.
CREATE TABLE IF NOT EXISTS mechanism_transfer_reviews (
    paper_id                    TEXT PRIMARY KEY REFERENCES papers(id),
    relevance_status            TEXT NOT NULL,       -- 'transferable' | 'not_relevant' | 'ambiguous'
    transferable_one_liner      TEXT,
    transfer_problem            TEXT,
    shared_approach             TEXT,
    relevant_fin_fields_json    TEXT,
    rationale                   TEXT,
    assessed_at                 TEXT NOT NULL,
    assessed_by                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_transfer_reviews_status
    ON mechanism_transfer_reviews(relevance_status);

-- Human-maintained Fin-first transfer taxonomy. AI papers may support these
-- cells, but automated evidence ingestion is not allowed to create new active
-- cells. This avoids an AI-paper-first taxonomy full of speculative bridges.
CREATE TABLE IF NOT EXISTS fin_transfer_cells (
    cell_id                 TEXT PRIMARY KEY,
    field_id                TEXT NOT NULL,
    mechanism_family        TEXT NOT NULL,
    bottleneck              TEXT NOT NULL,
    ai_intervention_class   TEXT NOT NULL,
    experiment_anchor_json  TEXT NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'active',
                            -- 'active' | 'candidate' | 'rejected' | 'deprecated'
    source_path             TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    last_updated            TEXT NOT NULL,
    UNIQUE (field_id, ai_intervention_class)
);

CREATE INDEX IF NOT EXISTS idx_transfer_cells_field
    ON fin_transfer_cells(field_id, status);

-- One terminal audit decision per AI evidence paper. `candidate_extension`
-- captures plausible mechanisms outside the current human-maintained cells;
-- it never activates a new research direction automatically.
CREATE TABLE IF NOT EXISTS ai_evidence_decisions (
    paper_id                    TEXT PRIMARY KEY REFERENCES papers(id),
    verdict                     TEXT NOT NULL,       -- 'support' | 'candidate_extension' | 'reject'
    selected_cell_id            TEXT REFERENCES fin_transfer_cells(cell_id),
    supported_cell_ids_json     TEXT,                -- all accepted support cell ids; selected_cell_id is primary
    candidate_cell_ids_json     TEXT,
    bridge_claim                TEXT,
    experiment_fit_json         TEXT,
    proposed_extension_json     TEXT,
    rationale                   TEXT,
    assessed_at                 TEXT NOT NULL,
    assessed_by                 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_evidence_decisions_verdict
    ON ai_evidence_decisions(verdict);

-- Accepted/candidate paper-to-cell connections. Only `support` links are
-- available as evidence for gap generation; `candidate` links remain review
-- material until a human promotes them.
CREATE TABLE IF NOT EXISTS ai_evidence_links (
    paper_id                TEXT NOT NULL REFERENCES papers(id),
    cell_id                 TEXT NOT NULL REFERENCES fin_transfer_cells(cell_id),
    verdict                 TEXT NOT NULL,       -- 'support' | 'candidate'
    confidence              REAL NOT NULL,
    bridge_claim            TEXT,
    experiment_fit_json     TEXT,
    review_reason           TEXT,
    assessed_at             TEXT NOT NULL,
    assessed_by             TEXT NOT NULL,
    PRIMARY KEY (paper_id, cell_id)
);

CREATE INDEX IF NOT EXISTS idx_evidence_links_cell
    ON ai_evidence_links(cell_id, verdict);

-- Paper → family assignment with confidence and review state.
-- mechanism_slot allows one paper to belong to multiple families
-- (e.g. method=family_A + dataset=family_B). Default 'primary'.
-- Active uniqueness: at most one 'accepted' membership per (paper, slot).
CREATE TABLE IF NOT EXISTS mechanism_memberships (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    paper_id            TEXT NOT NULL REFERENCES papers(id),
    family_id           TEXT NOT NULL REFERENCES mechanism_families(family_id),
    mechanism_slot      TEXT NOT NULL DEFAULT 'primary',
    confidence          REAL NOT NULL,             -- 0..1, from LLM adjudicator
    assigned_at         TEXT NOT NULL,
    assigned_by         TEXT NOT NULL,             -- 'llm-adjudicator-v1' | 'human' | 'embedding-only'
    membership_status   TEXT NOT NULL DEFAULT 'proposed',
                        -- 'proposed' | 'accepted' | 'rejected' | 'superseded'
    needs_review        INTEGER NOT NULL DEFAULT 0,
    UNIQUE (paper_id, family_id, mechanism_slot)
);

CREATE INDEX IF NOT EXISTS idx_memberships_paper
    ON mechanism_memberships(paper_id);
CREATE INDEX IF NOT EXISTS idx_memberships_family
    ON mechanism_memberships(family_id);

-- Enforce: at most ONE 'accepted' family per (paper, mechanism_slot).
-- 'proposed' / 'rejected' / 'superseded' rows are not constrained — multiple
-- proposals can coexist for the same slot until one is accepted.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_membership
    ON mechanism_memberships(paper_id, mechanism_slot)
    WHERE membership_status = 'accepted';
"""


@contextmanager
def connect(path: Path | None = None):
    db_path = path or load_settings().db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ai_evidence_decisions)").fetchall()
        }
        if "supported_cell_ids_json" not in columns:
            conn.execute(
                "ALTER TABLE ai_evidence_decisions ADD COLUMN supported_cell_ids_json TEXT"
            )


# SQL fragment added to daily-trigger paper queries during the Phase 1
# migration. Without this, OpenReview / conference backfill rows (which
# enter `paper_sources` with `eligible_for_daily_trigger=0`) would
# silently appear in trend / context / brief queries that read `papers`
# directly, polluting the daily gap candidate pool.
#
# Semantics:
#   - Legacy paper rows that have NO `paper_sources` observation yet → pass
#     (preserves pre-migration behaviour for the existing 3,128 papers).
#   - Paper rows with at least one observation marked
#     `eligible_for_daily_trigger=1` → pass (HF Daily / arXiv ingest must
#     set this when the observation is a "trigger" or "both" role).
#   - Paper rows with only `evidence`-role observations → excluded.
#
# Usage: SQL queries should reference papers via alias `p`, then append
# `AND " + db.TRIGGER_ELIGIBILITY_GUARD` to the WHERE clause. The guard
# uses correlated subqueries; with the `idx_paper_sources_paper` and
# `idx_paper_sources_trigger` indexes this is cheap.
TRIGGER_ELIGIBILITY_GUARD = """(
    NOT EXISTS (
        SELECT 1 FROM paper_sources _tps WHERE _tps.paper_id = p.id
    )
    OR EXISTS (
        SELECT 1 FROM paper_sources _tps2
        WHERE _tps2.paper_id = p.id AND _tps2.eligible_for_daily_trigger = 1
    )
)"""


# Tables and indexes added by the Phase 1 mechanism evidence library
# migration. verify_phase1_schema() asserts they all exist so deployment
# scripts can fail loudly if init_schema() didn't run.
_PHASE1_TABLES = (
    "paper_external_ids",
    "paper_sources",
    "mechanism_families",
    "mechanism_transfer_reviews",
    "mechanism_memberships",
    "fin_transfer_cells",
    "ai_evidence_decisions",
    "ai_evidence_links",
)

_PHASE1_INDEXES = (
    "idx_external_ids_paper",
    "idx_paper_sources_paper",
    "idx_paper_sources_source",
    "idx_paper_sources_trigger",
    "idx_families_status",
    "idx_transfer_reviews_status",
    "idx_memberships_paper",
    "idx_memberships_family",
    "idx_one_active_membership",  # partial unique index
    "idx_transfer_cells_field",
    "idx_evidence_decisions_verdict",
    "idx_evidence_links_cell",
)


def verify_phase1_schema() -> dict:
    """Check Phase 1 tables and indexes exist. Returns a status dict.

    Raises AssertionError if anything is missing — callable from CI / deploy.
    """
    with connect() as conn:
        existing_tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        existing_indexes = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

        missing_tables = [t for t in _PHASE1_TABLES if t not in existing_tables]
        missing_indexes = [i for i in _PHASE1_INDEXES if i not in existing_indexes]

        # Sanity-check the partial unique index actually has a WHERE clause.
        partial_idx = conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type='index' AND name='idx_one_active_membership'"
        ).fetchone()
        partial_ok = bool(partial_idx and "WHERE" in (partial_idx[0] or "").upper())

        # Sanity-check schema columns on each new table by SELECT pragma.
        column_counts = {}
        required_columns_missing = {}
        for t in _PHASE1_TABLES:
            if t in existing_tables:
                rows = conn.execute(f"PRAGMA table_info({t})").fetchall()
                column_counts[t] = len(rows)
                if t == "ai_evidence_decisions":
                    columns = {row["name"] for row in rows}
                    missing = {"supported_cell_ids_json"} - columns
                    if missing:
                        required_columns_missing[t] = sorted(missing)

        result = {
            "tables_present": sorted(t for t in _PHASE1_TABLES if t in existing_tables),
            "tables_missing": missing_tables,
            "indexes_present": sorted(i for i in _PHASE1_INDEXES if i in existing_indexes),
            "indexes_missing": missing_indexes,
            "partial_unique_index_has_where": partial_ok,
            "column_counts": column_counts,
            "required_columns_missing": required_columns_missing,
        }

        if missing_tables or missing_indexes or not partial_ok or required_columns_missing:
            raise AssertionError(
                f"Phase 1 schema incomplete: missing tables={missing_tables} "
                f"missing indexes={missing_indexes} missing_columns={required_columns_missing} "
                f"partial_ok={partial_ok}"
            )

        return result


# ---------- Upserts ----------

def upsert_paper(conn: sqlite3.Connection, paper: dict) -> None:
    """Insert or update one paper without replacing its referenced parent row."""
    affiliations = "; ".join(
        aff for a in paper.get("authors", []) for aff in (a.get("affiliations") or [])
    )
    pub_date = paper.get("publication_date")
    if isinstance(pub_date, (date, datetime)):
        pub_date = pub_date.isoformat()[:10]

    conn.execute(
        """
        INSERT INTO papers
            (id, source, arxiv_id, doi, title, abstract, authors_json,
             affiliations, publication_date, arxiv_categories, citations, url,
             fetched_at, raw_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            source = excluded.source,
            arxiv_id = COALESCE(excluded.arxiv_id, papers.arxiv_id),
            doi = COALESCE(excluded.doi, papers.doi),
            title = excluded.title,
            abstract = excluded.abstract,
            authors_json = excluded.authors_json,
            affiliations = excluded.affiliations,
            publication_date = excluded.publication_date,
            arxiv_categories = excluded.arxiv_categories,
            citations = excluded.citations,
            url = excluded.url,
            fetched_at = excluded.fetched_at,
            raw_meta_json = excluded.raw_meta_json
        """,
        (
            paper["id"],
            paper["source"],
            paper.get("arxiv_id"),
            paper.get("doi"),
            paper["title"],
            paper.get("abstract"),
            json.dumps(paper.get("authors", []), ensure_ascii=False),
            affiliations,
            pub_date,
            ",".join(paper.get("arxiv_categories", [])),
            paper.get("citations", 0),
            paper.get("url"),
            _now_iso(),
            json.dumps(paper.get("raw_meta", {}), ensure_ascii=False),
        ),
    )


def upsert_signals(conn: sqlite3.Connection, paper_id: str, signals: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO paper_signals
            (paper_id, is_candidate, priority_score, signals_json, computed_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            1 if signals.get("priority_score", 0) > 0 or _any_signal(signals) else 0,
            float(signals.get("priority_score", 0)),
            json.dumps(signals, ensure_ascii=False),
            _now_iso(),
        ),
    )


def upsert_paper_source(
    conn: sqlite3.Connection,
    *,
    paper_id: str,
    source: str,
    source_record_id: str,
    role: str = "trigger",
    eligible_for_daily_trigger: int = 1,
    venue: str | None = None,
    decision: str | None = None,
    review_scores: list | None = None,
    raw_meta: dict | None = None,
    first_observed_at: str | None = None,
) -> None:
    """Idempotent insert/update of a paper source observation.

    Uses the (paper_id, source, source_record_id) UNIQUE key. On re-fetch,
    updates the observation's last_observed_at and raw_meta — keeping the
    first_observed_at, role, and eligibility from the first sighting.

    Use cases:
      - daily fetcher: role='trigger', eligible=1
      - OpenReview / conference backfill: role='evidence', eligible=0
    """
    now = _now_iso()
    first_seen = first_observed_at or now
    scores_json = json.dumps(review_scores) if review_scores is not None else None
    meta_json = json.dumps(raw_meta or {}, ensure_ascii=False)
    conn.execute(
        """
        INSERT INTO paper_sources
            (paper_id, source, source_record_id, role,
             eligible_for_daily_trigger, venue, decision, review_scores,
             first_observed_at, last_observed_at, raw_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(paper_id, source, source_record_id) DO UPDATE SET
            last_observed_at = excluded.last_observed_at,
            venue = COALESCE(excluded.venue, paper_sources.venue),
            decision = COALESCE(excluded.decision, paper_sources.decision),
            review_scores = COALESCE(excluded.review_scores, paper_sources.review_scores),
            raw_meta_json = excluded.raw_meta_json
        """,
        (
            paper_id, source, source_record_id, role,
            eligible_for_daily_trigger, venue, decision, scores_json,
            first_seen, now, meta_json,
        ),
    )


def ensure_legacy_trigger_observation(conn: sqlite3.Connection, paper_id: str) -> None:
    """Backfill a trigger observation before attaching evidence to a legacy paper.

    Rows created before ``paper_sources`` existed encode their provenance only
    in ``papers.source``. Once an evidence observation is attached, the query
    guard requires an explicit eligible trigger row to keep such papers visible.
    """
    row = conn.execute(
        "SELECT source, arxiv_id, raw_meta_json FROM papers WHERE id = ?",
        (paper_id,),
    ).fetchone()
    if not row or row["source"] not in {"arxiv", "hf_daily"}:
        return
    try:
        raw_meta = json.loads(row["raw_meta_json"] or "{}")
    except json.JSONDecodeError:
        raw_meta = {}
    raw_meta["bootstrapped_from_legacy_paper_row"] = True
    upsert_paper_source(
        conn,
        paper_id=paper_id,
        source=row["source"],
        source_record_id=row["arxiv_id"] or paper_id,
        role="trigger",
        eligible_for_daily_trigger=1,
        raw_meta=raw_meta,
    )


def upsert_external_id(
    conn: sqlite3.Connection,
    *,
    source: str,
    external_id: str,
    paper_id: str,
) -> None:
    """Register a stable external identifier for a paper (e.g. openreview note id).

    Idempotent on PRIMARY KEY (source, external_id). Repeat calls just update
    observed_at.
    """
    conn.execute(
        """
        INSERT INTO paper_external_ids (source, external_id, paper_id, observed_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            observed_at = excluded.observed_at
        """,
        (source, external_id, paper_id, _now_iso()),
    )


def find_paper_by_external_id(
    conn: sqlite3.Connection,
    source: str,
    external_id: str,
) -> str | None:
    """Return paper_id (if any) registered for a given external id."""
    row = conn.execute(
        "SELECT paper_id FROM paper_external_ids WHERE source = ? AND external_id = ?",
        (source, external_id),
    ).fetchone()
    return row[0] if row else None


def upsert_extraction_l1(conn: sqlite3.Connection, paper_id: str, l1: dict) -> None:
    conn.execute(
        """
        INSERT INTO paper_extractions
            (paper_id, side, method_primary_json, domain_json, tags_json,
             mechanism_description_json, l1_extracted_at, extraction_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'l1_done')
        ON CONFLICT(paper_id) DO UPDATE SET
            side = excluded.side,
            method_primary_json = excluded.method_primary_json,
            domain_json = excluded.domain_json,
            tags_json = excluded.tags_json,
            mechanism_description_json = excluded.mechanism_description_json,
            l1_extracted_at = excluded.l1_extracted_at,
            extraction_status = CASE
                WHEN paper_extractions.extraction_status = 'l2_done' THEN 'l2_done'
                ELSE 'l1_done'
            END
        """,
        (
            paper_id,
            l1.get("side"),
            json.dumps(l1.get("method_primary", []), ensure_ascii=False),
            json.dumps(l1.get("domain", []), ensure_ascii=False),
            json.dumps(l1.get("tags", []), ensure_ascii=False),
            json.dumps(l1.get("mechanism_description", {}), ensure_ascii=False),
            _now_iso(),
        ),
    )


def upsert_extraction_l2(conn: sqlite3.Connection, paper_id: str, l2: dict) -> None:
    conn.execute(
        """
        UPDATE paper_extractions
        SET building_blocks_json = ?,
            claims_json = ?,
            benchmarks_json = ?,
            l2_extracted_at = ?,
            extraction_status = 'l2_done'
        WHERE paper_id = ?
        """,
        (
            json.dumps(l2.get("building_blocks", []), ensure_ascii=False),
            json.dumps(l2.get("claims", []), ensure_ascii=False),
            json.dumps(l2.get("benchmarks", []), ensure_ascii=False),
            _now_iso(),
            paper_id,
        ),
    )


def upsert_citation_snapshot(conn: sqlite3.Connection, paper_id: str,
                              citation_count: int,
                              influential: int = 0,
                              snapshot_date: str | None = None) -> None:
    snap = snapshot_date or date.today().isoformat()
    conn.execute(
        """
        INSERT OR REPLACE INTO citation_snapshots
            (paper_id, snapshot_date, citation_count, influential_citation_count)
        VALUES (?, ?, ?, ?)
        """,
        (paper_id, snap, citation_count, influential),
    )


def citation_velocity(conn: sqlite3.Connection, paper_id: str,
                       window_days: int = 30,
                       as_of: str | None = None) -> tuple[int | None, int | None]:
    """Returns (velocity, latest_count) for given paper.

    velocity = latest_count - count_at_or_before(as_of - window_days)
    Returns (None, None) if no snapshot history.
    """
    from datetime import timedelta as _td
    as_of_date = date.fromisoformat(as_of) if as_of else date.today()
    cutoff = (as_of_date - _td(days=window_days)).isoformat()

    latest = conn.execute(
        """
        SELECT citation_count FROM citation_snapshots
        WHERE paper_id = ? AND snapshot_date <= ?
        ORDER BY snapshot_date DESC LIMIT 1
        """,
        (paper_id, as_of_date.isoformat()),
    ).fetchone()
    if latest is None:
        return None, None
    latest_count = latest[0]

    prior = conn.execute(
        """
        SELECT citation_count FROM citation_snapshots
        WHERE paper_id = ? AND snapshot_date <= ?
        ORDER BY snapshot_date DESC LIMIT 1
        """,
        (paper_id, cutoff),
    ).fetchone()
    prior_count = prior[0] if prior else 0     # treat unseen as 0
    return (latest_count - prior_count, latest_count)


def mark_extraction_failed(conn: sqlite3.Connection, paper_id: str, level: str, err: str) -> None:
    """level: 'l1' or 'l2'."""
    conn.execute(
        """
        INSERT INTO paper_extractions (paper_id, extraction_status)
        VALUES (?, 'failed')
        ON CONFLICT(paper_id) DO UPDATE SET extraction_status = 'failed'
        """,
        (paper_id,),
    )


def fetch_pending_for_l1(
    conn: sqlite3.Connection,
    limit: int = 100,
    *,
    include_evidence: bool = False,
    evidence_only: bool = False,
) -> list[dict]:
    """Candidate papers without L1 extraction yet, ordered by priority desc.

    Daily runs process trigger-eligible papers only. Conference backfills opt
    in to evidence extraction explicitly so a historical import cannot consume
    the next daily run's LLM budget.
    """
    if evidence_only:
        source_clause = """
          AND EXISTS (
              SELECT 1 FROM paper_sources _eps
              WHERE _eps.paper_id = p.id AND _eps.role = 'evidence'
          )
        """
    else:
        source_clause = "" if include_evidence else f"AND {TRIGGER_ELIGIBILITY_GUARD}"
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.abstract, p.affiliations, p.arxiv_categories,
               s.priority_score, s.signals_json
        FROM papers p
        JOIN paper_signals s ON s.paper_id = p.id
        LEFT JOIN paper_extractions e ON e.paper_id = p.id
        WHERE s.is_candidate = 1
          AND (e.paper_id IS NULL OR e.extraction_status NOT IN ('l1_done', 'l2_done'))
          {source_clause}
        ORDER BY s.priority_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_pending_for_l2(
    conn: sqlite3.Connection,
    min_priority: float,
    limit: int = 50,
    *,
    include_evidence: bool = False,
    evidence_only: bool = False,
) -> list[dict]:
    """Papers with L1 done but no L2, above priority threshold."""
    if evidence_only:
        source_clause = """
          AND EXISTS (
              SELECT 1 FROM paper_sources _eps
              WHERE _eps.paper_id = p.id AND _eps.role = 'evidence'
          )
        """
    else:
        source_clause = "" if include_evidence else f"AND {TRIGGER_ELIGIBILITY_GUARD}"
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.abstract,
               e.side, e.method_primary_json, e.domain_json
        FROM papers p
        JOIN paper_signals s ON s.paper_id = p.id
        JOIN paper_extractions e ON e.paper_id = p.id
        WHERE e.extraction_status = 'l1_done'
          AND s.priority_score >= ?
          {source_clause}
        ORDER BY s.priority_score DESC
        LIMIT ?
        """,
        (min_priority, limit),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["method_primary"] = json.loads(d.pop("method_primary_json") or "[]")
        d["domain"] = json.loads(d.pop("domain_json") or "[]")
        out.append(d)
    return out


def stats_today() -> dict:
    with connect() as conn:
        today = date.today().isoformat()
        return {
            "papers_total": conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0],
            "papers_today": conn.execute(
                "SELECT COUNT(*) FROM papers WHERE date(fetched_at) = ?", (today,)
            ).fetchone()[0],
            "candidates": conn.execute(
                "SELECT COUNT(*) FROM paper_signals WHERE is_candidate = 1"
            ).fetchone()[0],
            "l1_done": conn.execute(
                "SELECT COUNT(*) FROM paper_extractions WHERE extraction_status IN ('l1_done','l2_done')"
            ).fetchone()[0],
            "l2_done": conn.execute(
                "SELECT COUNT(*) FROM paper_extractions WHERE extraction_status = 'l2_done'"
            ).fetchone()[0],
        }


# ---------- Helpers ----------

def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _any_signal(signals: dict) -> bool:
    return bool(
        signals.get("is_hf_daily")
        or signals.get("is_q_fin")
        or signals.get("named_author_match")
        or signals.get("institution_match")
        or signals.get("keyword_matches")
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_schema()
        print(f"Schema initialized at {load_settings().db_path}")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        print(json.dumps(stats_today(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "verify-phase1":
        try:
            result = verify_phase1_schema()
            print(json.dumps(result, indent=2))
            print("\nPhase 1 schema OK")
        except AssertionError as e:
            print(f"FAILED: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("Usage: python -m pipeline.db {init|stats|verify-phase1}")
