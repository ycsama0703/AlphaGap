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


# ---------- Upserts ----------

def upsert_paper(conn: sqlite3.Connection, paper: dict) -> None:
    """Insert or replace one paper. `paper` has keys matching PaperRecord-ish shape."""
    affiliations = "; ".join(
        aff for a in paper.get("authors", []) for aff in (a.get("affiliations") or [])
    )
    pub_date = paper.get("publication_date")
    if isinstance(pub_date, (date, datetime)):
        pub_date = pub_date.isoformat()[:10]

    conn.execute(
        """
        INSERT OR REPLACE INTO papers
            (id, source, arxiv_id, doi, title, abstract, authors_json,
             affiliations, publication_date, arxiv_categories, citations, url,
             fetched_at, raw_meta_json)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def fetch_pending_for_l1(conn: sqlite3.Connection, limit: int = 100) -> list[dict]:
    """Candidate papers without L1 extraction yet, ordered by priority desc."""
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.abstract, p.affiliations, p.arxiv_categories,
               s.priority_score, s.signals_json
        FROM papers p
        JOIN paper_signals s ON s.paper_id = p.id
        LEFT JOIN paper_extractions e ON e.paper_id = p.id
        WHERE s.is_candidate = 1
          AND (e.paper_id IS NULL OR e.extraction_status NOT IN ('l1_done', 'l2_done'))
        ORDER BY s.priority_score DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def fetch_pending_for_l2(conn: sqlite3.Connection, min_priority: float, limit: int = 50) -> list[dict]:
    """Papers with L1 done but no L2, above priority threshold."""
    rows = conn.execute(
        """
        SELECT p.id, p.title, p.abstract,
               e.side, e.method_primary_json, e.domain_json
        FROM papers p
        JOIN paper_signals s ON s.paper_id = p.id
        JOIN paper_extractions e ON e.paper_id = p.id
        WHERE e.extraction_status = 'l1_done'
          AND s.priority_score >= ?
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
    else:
        print("Usage: python -m pipeline.db {init|stats}")
