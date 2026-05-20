"""Context builder for gap generation.

Gathers everything Prompts 04 / 05 / 08 need from DB + filesystem:
  - top AI/Fin papers (recent, with extractions)
  - existing mappings (from mappings/ markdown files — empty until human approves)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from pathlib import Path

from .. import db
from ..config import PROJECT_ROOT


log = logging.getLogger(__name__)


def get_top_papers(side: str, end_date: date, *, top_n: int = 20,
                   window_days: int = 14) -> list[dict]:
    """Top N papers on `side` within window, sorted by priority_score desc.

    Returns dicts with full extraction (l1 + l2 when available).
    """
    start = end_date - timedelta(days=window_days - 1)
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.abstract, p.publication_date, p.affiliations, p.url,
                   p.arxiv_categories,
                   e.side, e.method_primary_json, e.domain_json, e.tags_json,
                   e.building_blocks_json, e.claims_json, e.benchmarks_json,
                   s.priority_score, s.signals_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
            ORDER BY s.priority_score DESC
            LIMIT ?
            """,
            (side, start.isoformat(), end_date.isoformat(), top_n),
        ).fetchall()

    out = []
    for r in rows:
        d = dict(r)
        for k in ("method_primary", "domain", "tags",
                  "building_blocks", "claims", "benchmarks"):
            jk = k + "_json"
            d[k] = json.loads(d.pop(jk) or "[]")
        d["signals"] = json.loads(d.pop("signals_json") or "{}")
        d["abstract_short"] = (d.get("abstract") or "")[:600]
        d["affiliation_top"] = (d.get("affiliations") or "").split(";")[0].strip()
        out.append(d)
    return out


# ---------- Mappings reader ----------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def load_existing_mappings(mappings_dir: Path | None = None) -> list[dict]:
    """Read all mapping md files from mappings/.

    Each file uses YAML frontmatter:
        ---
        id: M001
        ai_concept: ...
        fin_concept: ...
        status: open_gap | partially_explored | mature | refuted
        ---
        free-form notes...

    Returns list of dicts. Empty list when mappings/ is empty (early days).
    """
    mappings_dir = mappings_dir or (PROJECT_ROOT / "mappings")
    if not mappings_dir.exists():
        return []

    import yaml
    out = []
    for path in sorted(mappings_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            log.warning("No frontmatter in mapping %s, skipping", path.name)
            continue
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            log.warning("YAML parse failed in %s: %s", path.name, e)
            continue
        meta["_path"] = str(path)
        meta["notes"] = text[m.end():].strip()
        out.append(meta)
    return out


# ---------- Compact projections for prompts ----------

def paper_for_prompt(p: dict) -> dict:
    """Trim a paper dict to just what gap-gen prompts need."""
    return {
        "id": p["id"],
        "title": p["title"],
        "abstract_short": p.get("abstract_short") or (p.get("abstract") or "")[:600],
        "method_primary": p.get("method_primary", []),
        "domain": p.get("domain", []),
        "tags": p.get("tags", []),
        "building_blocks": p.get("building_blocks", []),
        "claims": p.get("claims", []),
        "affiliation_top": p.get("affiliation_top") or "",
        "score": round(p.get("priority_score") or 0.0, 1),
    }


def mapping_for_prompt(m: dict) -> dict:
    return {
        "id": m.get("id"),
        "ai_concept": m.get("ai_concept"),
        "fin_concept": m.get("fin_concept"),
        "status": m.get("status"),
        "notes": (m.get("notes") or "")[:300],
    }


def mapping_brief(m: dict) -> dict:
    """Even leaner — for self-check duplication detection."""
    return {
        "id": m.get("id"),
        "ai_concept": m.get("ai_concept"),
        "fin_concept": m.get("fin_concept"),
        "status": m.get("status"),
    }
