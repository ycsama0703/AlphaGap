"""One-time, idempotent importer for the OpenReview conference look-back seed.

Why: luyao4's live DB has only hf_daily + arxiv papers (0 conference), so `get_conference_lookback`
draws nothing and the daily mechanism line keeps anchoring on the same agent-heavy recent arxiv papers.
This loads the 817 peer-reviewed conference papers (+ their L1/L2 extractions and signals) shipped as a
committed seed, so the look-back has real material. Safe to re-run: INSERT OR IGNORE everywhere.

Data arrives via GitHub (committed `db/seed/conf_lookback.sqlite.gz`) + `git pull` — never scp (server rule).

Run from repo root:  python -m pipeline.import_conf_lookback   [--db path]
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import tempfile
from pathlib import Path

SEED = Path(__file__).resolve().parent.parent / "db/seed/conf_lookback.sqlite.gz"
TABLES = ["papers", "paper_extractions", "paper_signals", "paper_sources"]


def _live_conn(db_path: str | None):
    if db_path:
        return sqlite3.connect(db_path)
    from pipeline import db
    return db.connect()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None, help="override live DB path (default: app-configured)")
    args = ap.parse_args()
    if not SEED.exists():
        raise SystemExit(f"seed not found: {SEED} (did you git pull?)")

    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tf:
        seed_path = tf.name
    with gzip.open(SEED, "rb") as g, open(seed_path, "wb") as f:
        shutil.copyfileobj(g, f)

    cm = _live_conn(args.db)
    conn = cm.__enter__() if hasattr(cm, "__enter__") else cm
    try:
        def n_conf():
            return conn.execute("SELECT COUNT(DISTINCT paper_id) FROM paper_sources WHERE source='openreview'").fetchone()[0]
        before = n_conf()
        conn.execute("ATTACH DATABASE ? AS seed", (seed_path,))
        for t in TABLES:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            if t == "paper_sources":
                cols = [c for c in cols if c != "id"]   # let AUTOINCREMENT assign; UNIQUE dedups
            collist = ",".join(cols)
            cur = conn.execute(f"INSERT OR IGNORE INTO {t} ({collist}) SELECT {collist} FROM seed.{t}")
            print(f"  {t}: +{cur.rowcount} rows")
        conn.commit()
        conn.execute("DETACH DATABASE seed")
        after = n_conf()
        print(f"\nopenreview papers: {before} -> {after}  (+{after - before})")
        # dependency-free eligibility check = exactly what get_conference_lookback needs
        elig = conn.execute(
            """SELECT COUNT(DISTINCT p.id) FROM paper_sources ps
               JOIN papers p ON p.id=ps.paper_id
               JOIN paper_extractions e ON e.paper_id=p.id
               WHERE ps.source='openreview' AND e.extraction_status IN ('l1_done','l2_done')
                 AND (e.side='ai' OR e.side='both')""").fetchone()[0]
        print(f"conference look-back ELIGIBLE (ai, l1/l2): {elig}")
        print("OK" if elig > 0 else "WARNING: 0 eligible — look-back still empty")
    finally:
        if hasattr(cm, "__exit__"):
            cm.__exit__(None, None, None)
        else:
            conn.close()
        Path(seed_path).unlink(missing_ok=True)


if __name__ == "__main__":
    main()
