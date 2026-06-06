"""Load the teacher's lumid-findata client + PIT-safe `as_of` truncation for Phase-0.

findata is NOT in this repo — it's the published Lumid skill at the path below (auth via
LUMID_PAT env → ~/.lumid/credentials.toml). We load it by file path (like the staged-experiment
harness does) and wrap the few endpoints Phase-0 needs with date-truncation so an agent answering
"as of <report date>" cannot see future rows. Dated lists are filtered; the transcript for a quarter
is only allowed if its call_date <= as_of.
"""
from __future__ import annotations

import importlib.util
import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("phase0.findata")

_CLIENT_PATH = (Path.home()
                / ".xp/skills/a3f48236-ffe9-4fb9-9548-6e044d5cd9c7/lumid-findata/skills/client.py")

# keys that carry a row's effective date, in priority order
_DATE_KEYS = ("period_end_date", "report_date", "fiscal_date", "filing_date",
              "published_at", "call_date", "date")


@lru_cache(maxsize=1)
def load_client():
    """Import the lumid-findata client module by path (cached). Raises a clear error if absent."""
    if not _CLIENT_PATH.exists():
        raise FileNotFoundError(
            f"lumid-findata client not found at {_CLIENT_PATH}. "
            "Phase-0 needs the teacher's published findata skill installed.")
    spec = importlib.util.spec_from_file_location("lumid_findata_client", _CLIENT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def row_date(row: dict) -> str | None:
    for k in _DATE_KEYS:
        if isinstance(row, dict) and row.get(k):
            return str(row[k])[:10]
    return None


def truncate(rows, as_of: str):
    """Keep only dated rows with date <= as_of (undated rows kept). Non-lists pass through."""
    if not isinstance(rows, list):
        return rows
    out = []
    for r in rows:
        d = row_date(r)
        if d is None or d <= as_of:
            out.append(r)
    return out
