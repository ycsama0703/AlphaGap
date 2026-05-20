"""Per-gap Deep Brief generator — Prompt 09.

Only runs for email-ready gaps (score >= EMAIL_THRESHOLD).
Outputs markdown directly to briefs/YYYY-MM-DD-GAPID.md.

The brief is self-contained: hand it to an AI engineer or paste into Claude
and they should fully grasp the idea without any other context.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from pathlib import Path

from .. import db
from ..config import PROJECT_ROOT, load_prompt
from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient


log = logging.getLogger(__name__)


def find_neighbor_papers(gap: dict, side: str, top_k: int = 5) -> list[dict]:
    """Find papers in DB that share concepts with the gap.

    Used to enrich the 'Benchmark Landscape' section of the brief.
    """
    gap_concepts = set()
    for f in ("hypothesis", "motivation"):
        v = gap.get(f)
        if v:
            gap_concepts.update(_extract_keywords(v))

    ai_anchor = gap.get("ai_anchor", {})
    if ai_anchor.get("concept"):
        gap_concepts.add(ai_anchor["concept"].lower())
    if gap.get("research_context"):
        for v in gap["research_context"].values():
            if v:
                gap_concepts.update(_extract_keywords(v))

    if not gap_concepts:
        return []

    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT p.id, p.title, p.url, p.affiliations, p.publication_date,
                   e.method_primary_json, e.domain_json, e.tags_json, e.side
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = ? OR e.side = 'both')
            ORDER BY p.publication_date DESC
            LIMIT 500
            """,
            (side,),
        ).fetchall()

    scored: list[tuple[float, dict]] = []
    for r in rows:
        text_corpus = " ".join([
            r["title"] or "",
            r["method_primary_json"] or "",
            r["domain_json"] or "",
            r["tags_json"] or "",
        ]).lower()
        overlap = sum(1 for kw in gap_concepts if kw in text_corpus)
        if overlap >= 2:
            scored.append((overlap, dict(r)))

    scored.sort(reverse=True, key=lambda x: x[0])
    out = []
    for _, r in scored[:top_k]:
        affil = (r.get("affiliations") or "").split(";")[0].strip()
        out.append({
            "id": r["id"],
            "title": (r.get("title") or "")[:150],
            "url": r.get("url") or f"https://arxiv.org/abs/{r['id']}",
            "affiliation": affil,
            "method_primary": json.loads(r["method_primary_json"] or "[]"),
            "tags": json.loads(r["tags_json"] or "[]"),
        })
    return out


def _extract_keywords(text: str) -> set[str]:
    """Cheap keyword extraction — words ≥ 4 chars, lowercase, dedup."""
    if not text:
        return set()
    words = re.findall(r"[a-zA-Z][a-zA-Z\-]{3,}", text.lower())
    # Filter common stopwords
    stop = {"this", "that", "with", "from", "have", "been", "will", "more",
            "such", "into", "than", "also", "their", "these", "those", "what",
            "when", "where", "which", "would", "could", "should"}
    return {w for w in words if w not in stop}


def generate_brief(gap_item: dict, ai_trends: dict, fin_trends: dict,
                    existing_mappings: list[dict],
                    client: LLMClient | None = None) -> str:
    """Run Prompt 09 → returns markdown string."""
    client = client or LLMClient()
    gap = gap_item["gap"]
    score = gap_item["score"]
    gtype = gap_item["type"]

    related = gap.get("_related_papers", {"ai": [], "fin": []})

    # Neighbor papers: which side to look at depends on gap nature
    # For now, search both sides and merge
    ai_neighbors = find_neighbor_papers(gap, "ai", top_k=5)
    fin_neighbors = find_neighbor_papers(gap, "fin", top_k=5)
    neighbors = {"ai": ai_neighbors, "fin": fin_neighbors}

    # Filter related mappings to keep prompt lean
    related_mappings = existing_mappings[:10]   # cap

    system, user_template = parse_prompt("09_gap_deep_brief")
    user = render_template(
        user_template,
        type=gtype,
        gap_full_json=json.dumps(gap, ensure_ascii=False, indent=2),
        novelty=str(score["novelty"]),
        actionability=str(score["actionability"]),
        total=str(score["total"]),
        related_papers_json=json.dumps(related, ensure_ascii=False, indent=2),
        neighbor_papers_json=json.dumps(neighbors, ensure_ascii=False, indent=2),
        related_mappings_json=json.dumps(related_mappings, ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(ai_trends, ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(fin_trends, ensure_ascii=False, indent=2),
    )

    # Call LLM — markdown output, not JSON. Bypass json mode.
    resp = client._client.chat.completions.create(
        model=client._model_default,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
        max_tokens=4096,
    )
    if resp.usage:
        client._total_input_tokens += resp.usage.prompt_tokens
        client._total_output_tokens += resp.usage.completion_tokens
    md = resp.choices[0].message.content or ""

    # Add frontmatter
    return _wrap_with_frontmatter(gap_item, md)


def _wrap_with_frontmatter(item: dict, md: str) -> str:
    g = item["gap"]
    s = item["score"]
    front = (
        "---\n"
        f"gap_id: {g.get('_id', '?')}\n"
        f"type: {item['type']}\n"
        f"score_total: {s['total']}\n"
        f"score_novelty: {s['novelty']}\n"
        f"score_actionability: {s['actionability']}\n"
        f"hypothesis: \"{(g.get('hypothesis') or '').replace(chr(34), chr(39))}\"\n"
        f"---\n\n"
    )
    head = f"# {g.get('hypothesis', g.get('_id', '?'))}\n\n"
    return front + head + md.strip() + "\n"


def write_brief(d: date, gap_item: dict, markdown: str,
                briefs_dir: Path | None = None) -> Path:
    briefs_dir = briefs_dir or (PROJECT_ROOT / "briefs")
    briefs_dir.mkdir(parents=True, exist_ok=True)
    gid = gap_item["gap"].get("_id", "GAP")
    safe_gid = re.sub(r"[^A-Za-z0-9_\-]", "_", gid)
    path = briefs_dir / f"{d.isoformat()}-{safe_gid}.md"
    path.write_text(markdown, encoding="utf-8")
    log.info("Brief written to %s", path)
    return path


def generate_and_save_briefs(d: date, email_ready: list[dict],
                              ai_trends: dict, fin_trends: dict,
                              existing_mappings: list[dict],
                              client: LLMClient | None = None) -> list[Path]:
    """For each email-ready gap, generate a deep brief markdown and save.

    Returns list of paths in same order as email_ready.
    """
    client = client or LLMClient()
    paths: list[Path] = []
    for item in email_ready:
        gid = item["gap"].get("_id", "?")
        log.info("Generating brief for %s ...", gid)
        try:
            md = generate_brief(item, ai_trends, fin_trends, existing_mappings,
                                 client=client)
            path = write_brief(d, item, md)
            paths.append(path)
            # Attach the brief path to the gap item for downstream rendering
            item["_brief_path"] = str(path.relative_to(PROJECT_ROOT))
        except Exception as e:
            log.error("Brief generation failed for %s: %s", gid, e)
            paths.append(None)   # keep alignment
    return paths
