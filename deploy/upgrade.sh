#!/usr/bin/env bash
# AlphaGap upgrade script — run after `git pull` to migrate DB + re-extract.
# Idempotent: safe to run multiple times.
#
# Usage:
#   cd ~/workspace/projects/alphagap
#   git pull
#   bash deploy/upgrade.sh
#
# What it does:
#   1. ALTER TABLE to add any new columns (idempotent)
#   2. Detect if existing extractions need re-running (e.g. new field added)
#   3. If yes, clear paper_extractions and re-extract with new prompts

set -euo pipefail

cd "$(dirname "$0")/.."

VENV=.venv/bin/python
DB=db/alphagap.sqlite

if [ ! -f "$DB" ]; then
    echo "✗ DB not found at $DB. Run: $VENV -m pipeline.db init"
    exit 1
fi

echo "=== Step 1/3: Schema migration ==="
$VENV - <<'PY'
import sqlite3
conn = sqlite3.connect("db/alphagap.sqlite")

# All known migrations: (table, column, type)
MIGRATIONS = [
    ("paper_extractions", "mechanism_description_json", "TEXT"),
    # Add future migrations here.
]

for table, col, coltype in MIGRATIONS:
    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    if col not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {coltype}")
        conn.commit()
        print(f"  + added {table}.{col}")
    else:
        print(f"  ✓ {table}.{col} already exists")
PY

echo ""
echo "=== Step 2/3: Check if re-extraction needed ==="
NEED_REEXTRACT=$($VENV - <<'PY'
import sqlite3
conn = sqlite3.connect("db/alphagap.sqlite")
# Heuristic: any extracted paper missing mechanism_description?
n_missing = conn.execute("""
    SELECT COUNT(*) FROM paper_extractions
    WHERE extraction_status IN ('l1_done', 'l2_done')
      AND (mechanism_description_json IS NULL OR mechanism_description_json = '' OR mechanism_description_json = '{}')
""").fetchone()[0]
print(n_missing)
PY
)

if [ "$NEED_REEXTRACT" = "0" ]; then
    echo "  ✓ All extractions have mechanism_description, no re-extract needed."
    echo ""
    echo "=== Done. ==="
    exit 0
fi

echo "  → $NEED_REEXTRACT papers need re-extraction (missing mechanism_description)"
echo ""
read -r -p "Re-extract now (~30-60 min, ~\$1.50 LLM cost)? [y/N] " ans
if [[ ! "$ans" =~ ^[Yy]$ ]]; then
    echo "Skipped. You can re-run later with: bash deploy/upgrade.sh"
    exit 0
fi

echo ""
echo "=== Step 3/3: Re-extract (foreground; tail logs/reextract.log to monitor) ==="
mkdir -p logs

# Clear old extractions and re-run L1 on all candidates
$VENV - <<'PY'
import sqlite3
conn = sqlite3.connect("db/alphagap.sqlite")
n = conn.execute("DELETE FROM paper_extractions").rowcount
conn.commit()
print(f"  cleared {n} extraction rows")
PY

$VENV -u -m pipeline.ingest --no-arxiv --no-hf --max-l1 5000 --max-l2 0 2>&1 | tee logs/reextract.log | grep -E "L1 candidates|L1 done|Total cost|ERROR"

echo ""
echo "=== Upgrade complete. ==="
$VENV -m pipeline.db stats
