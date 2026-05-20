"""Enrich gaps with full paper details from DB.

LLM outputs reference arxiv_ids only. To make the inbox/email readable, we
look up title + url + affiliation for each referenced paper and attach as
a `_related_papers` field on the gap.
"""
from __future__ import annotations

from .. import db


def _collect_paper_ids(gap: dict) -> tuple[set[str], set[str]]:
    """Extract (ai_ids, fin_ids) from various gap fields."""
    ai_ids: set[str] = set()
    fin_ids: set[str] = set()

    ai = gap.get("ai_anchor") or {}
    if ai.get("paper_id"):
        ai_ids.add(ai["paper_id"])

    fin = gap.get("fin_anchor") or {}
    for pid in fin.get("evidence_paper_ids") or []:
        if pid:
            fin_ids.add(pid)

    anchors = gap.get("anchor_papers") or {}
    for p in anchors.get("ai", []) or []:
        if p.get("id"):
            ai_ids.add(p["id"])
    for p in anchors.get("fin", []) or []:
        if p.get("id"):
            fin_ids.add(p["id"])

    return ai_ids, fin_ids


def _lookup(conn, paper_ids: set[str]) -> dict[str, dict]:
    if not paper_ids:
        return {}
    placeholders = ",".join("?" * len(paper_ids))
    rows = conn.execute(
        f"""
        SELECT p.id, p.title, p.url, p.affiliations, p.arxiv_categories,
               e.method_primary_json, e.side
        FROM papers p
        LEFT JOIN paper_extractions e ON e.paper_id = p.id
        WHERE p.id IN ({placeholders})
        """,
        tuple(paper_ids),
    ).fetchall()
    import json as _json
    out = {}
    for r in rows:
        d = dict(r)
        d["affiliation_top"] = (d.get("affiliations") or "").split(";")[0].strip()
        d["method_primary"] = _json.loads(d.pop("method_primary_json") or "[]")
        out[d["id"]] = d
    return out


def enrich_gap(gap: dict) -> dict:
    """Attach `_related_papers` field with AI/Fin paper details from DB."""
    ai_ids, fin_ids = _collect_paper_ids(gap)
    with db.connect() as conn:
        ai_papers = _lookup(conn, ai_ids)
        fin_papers = _lookup(conn, fin_ids)

    gap["_related_papers"] = {
        "ai": [
            {
                "id": pid,
                "title": p.get("title", "?"),
                "url": p.get("url") or f"https://arxiv.org/abs/{pid}",
                "affiliation": p.get("affiliation_top", ""),
                "method": ", ".join(p.get("method_primary", [])[:2]),
            }
            for pid, p in ai_papers.items()
        ],
        "fin": [
            {
                "id": pid,
                "title": p.get("title", "?"),
                "url": p.get("url") or f"https://arxiv.org/abs/{pid}",
                "affiliation": p.get("affiliation_top", ""),
                "method": ", ".join(p.get("method_primary", [])[:2]),
            }
            for pid, p in fin_papers.items()
        ],
    }
    return gap


def enrich_accepted(accepted: list[dict]) -> list[dict]:
    for item in accepted:
        enrich_gap(item["gap"])
    return accepted
