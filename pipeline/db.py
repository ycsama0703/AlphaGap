"""SQLite schema + queries.

Tables:
  papers       — L3 cache, re-fetchable
  concepts     — L2 derived from papers, normalized
  paper_concepts — many-to-many
  daily_runs   — pipeline execution log
"""
from __future__ import annotations

import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

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

CREATE TABLE IF NOT EXISTS paper_extractions (
    paper_id        TEXT PRIMARY KEY REFERENCES papers(id),
    side            TEXT,                         -- 'ai' | 'fin' | 'both'
    method_primary_json TEXT,                     -- ["..."]
    domain_json     TEXT,
    tags_json       TEXT,
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


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        init_schema()
        print("Schema initialized.")
