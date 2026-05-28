"""Context builder for gap generation.

Gathers everything Prompts 04 / 05 / 08 need from DB + filesystem:
  - top AI/Fin papers (recent, with extractions)
  - existing mappings (from mappings/ markdown files — empty until human approves)
  - human-maintained Fin field boundary notes
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
AI_INNOVATION_PLAYBOOK_PATH = PROJECT_ROOT / "knowledge" / "ai_innovation_playbook.md"


def get_top_papers(side: str, end_date: date, *, top_n: int = 20,
                   window_days: int = 14) -> list[dict]:
    """Top N papers on `side` within window, sorted by priority_score desc.

    Returns dicts with full extraction (l1 + l2 when available).
    """
    start = end_date - timedelta(days=window_days - 1)
    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.abstract, p.publication_date, p.affiliations, p.url,
                   p.arxiv_categories,
                   e.side, e.method_primary_json, e.domain_json, e.tags_json,
                   e.mechanism_description_json,
                   e.building_blocks_json, e.claims_json, e.benchmarks_json,
                   s.priority_score, s.signals_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
              AND {db.TRIGGER_ELIGIBILITY_GUARD}
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
        d["mechanism"] = _normalize_mechanism(
            json.loads(d.pop("mechanism_description_json") or "{}")
        )
        d["signals"] = json.loads(d.pop("signals_json") or "{}")
        d["abstract_short"] = (d.get("abstract") or "")[:600]
        d["affiliation_top"] = (d.get("affiliations") or "").split(";")[0].strip()
        out.append(d)
    return out


def get_relevant_historical_mechanisms(
    end_date: date,
    field_notes: list[dict],
    transfer_cells: list[dict],
    *,
    exclude_ids: set[str] | None = None,
    top_n: int = 18,
    candidate_limit: int = 500,
) -> list[dict]:
    """Retrieve reusable AI mechanisms from the existing local paper library.

    This is intentionally cheap and deterministic: no external scan and no LLM
    call. It lets daily generation use accumulated mechanism memory without
    re-processing thousands of papers.
    """
    exclude_ids = exclude_ids or set()
    query_text = _historical_query_text(field_notes, transfer_cells)
    query_tokens = _tokenize(query_text)
    if not query_tokens:
        return []

    with db.connect() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.abstract, p.publication_date, p.affiliations, p.url,
                   p.arxiv_categories,
                   e.side, e.method_primary_json, e.domain_json, e.tags_json,
                   e.mechanism_description_json,
                   e.building_blocks_json, e.claims_json, e.benchmarks_json,
                   COALESCE(s.priority_score, 0) AS priority_score,
                   COALESCE(s.signals_json, '{{}}') AS signals_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = 'ai' OR e.side = 'both')
              AND date(p.publication_date) <= ?
            ORDER BY priority_score DESC, date(p.publication_date) DESC
            LIMIT ?
            """,
            (end_date.isoformat(), candidate_limit),
        ).fetchall()

    scored: list[tuple[float, dict]] = []
    for r in rows:
        if r["id"] in exclude_ids:
            continue
        paper = _row_to_paper_dict(r)
        text = _paper_retrieval_text(paper)
        overlap = query_tokens & _tokenize(text)
        phrase_hits = _phrase_hits(text, field_notes)
        relevance = (
            len(overlap)
            + 2.0 * phrase_hits
            + 0.25 * float(paper.get("priority_score") or 0.0)
            + (0.5 if paper.get("building_blocks") else 0.0)
        )
        if relevance <= 0:
            continue
        prompt_item = historical_mechanism_for_prompt(
            paper,
            matched_keywords=sorted(overlap)[:10],
            relevance_score=round(relevance, 2),
        )
        scored.append((relevance, prompt_item))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [item for _, item in scored[:top_n]]


def _normalize_mechanism(v: dict | None) -> dict:
    if not isinstance(v, dict):
        v = {}
    return {
        "one_liner": (v.get("one_liner") or "").strip(),
        "what_problem": (v.get("what_problem") or "").strip(),
        "contrast": (v.get("contrast") or "").strip(),
        "prerequisites": (v.get("prerequisites") or "").strip(),
    }


def _row_to_paper_dict(row) -> dict:
    d = dict(row)
    for k in ("method_primary", "domain", "tags",
              "building_blocks", "claims", "benchmarks"):
        jk = k + "_json"
        d[k] = json.loads(d.pop(jk) or "[]")
    d["mechanism"] = _normalize_mechanism(
        json.loads(d.pop("mechanism_description_json") or "{}")
    )
    d["signals"] = json.loads(d.pop("signals_json") or "{}")
    d["abstract_short"] = (d.get("abstract") or "")[:600]
    d["affiliation_top"] = (d.get("affiliations") or "").split(";")[0].strip()
    return d


def _historical_query_text(field_notes: list[dict], transfer_cells: list[dict]) -> str:
    parts: list[str] = []
    for note in field_notes or []:
        parts.extend([
            note.get("id") or "",
            note.get("name") or "",
            " ".join(note.get("related_keywords") or []),
            " ".join(note.get("canonical_tasks") or []),
            note.get("frontier") or "",
            " ".join(note.get("good_transfer_targets") or []),
            " ".join(note.get("bad_transfer_targets") or []),
        ])
        for family in note.get("mechanism_families") or []:
            parts.extend([
                family.get("name", ""),
                family.get("mechanism", ""),
                family.get("current_boundary", ""),
                family.get("gap_relevance", ""),
            ])
        for bottleneck in note.get("open_bottlenecks") or []:
            parts.extend([bottleneck.get("name", ""), bottleneck.get("description", "")])
    for cell in transfer_cells or []:
        parts.extend([
            cell.get("cell_id", ""),
            cell.get("field_id", ""),
            cell.get("failure_mode", ""),
            cell.get("ai_intervention_class", ""),
            json.dumps(cell.get("experiment_anchor") or {}, ensure_ascii=False),
        ])
    return " ".join(parts).lower()


def _paper_retrieval_text(paper: dict) -> str:
    return " ".join([
        paper.get("title", ""),
        paper.get("abstract_short", ""),
        " ".join(paper.get("method_primary") or []),
        " ".join(paper.get("domain") or []),
        " ".join(paper.get("tags") or []),
        json.dumps(paper.get("mechanism") or {}, ensure_ascii=False),
        json.dumps(paper.get("building_blocks") or [], ensure_ascii=False),
    ]).lower()


def _phrase_hits(text: str, field_notes: list[dict]) -> int:
    hits = 0
    for note in field_notes or []:
        phrases = []
        phrases.extend(note.get("related_keywords") or [])
        phrases.extend(note.get("canonical_tasks") or [])
        phrases.extend(f.get("name", "") for f in note.get("mechanism_families") or [])
        phrases.extend(b.get("name", "") for b in note.get("open_bottlenecks") or [])
        for phrase in phrases:
            phrase = (phrase or "").lower().strip()
            if len(phrase) >= 4 and phrase in text:
                hits += 1
    return hits


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


# ---------- Fin field boundary notes ----------

def load_fin_field_notes(fields_dir: Path | None = None) -> list[dict]:
    """Read mechanism-level Fin field notes from knowledge/fin_fields/.

    These notes are human-maintained domain-boundary assets. They are separate
    from mappings: mappings track specific AI->Fin bridges, while field notes
    tell generation prompts what the Fin-side frontier, mature areas, and
    low-value transfer targets look like.
    """
    fields_dir = fields_dir or (PROJECT_ROOT / "knowledge" / "fin_fields")
    if not fields_dir.exists():
        return []

    import yaml
    notes = []
    for path in sorted(fields_dir.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        text = path.read_text(encoding="utf-8")
        m = _FRONTMATTER_RE.match(text)
        if not m:
            log.warning("No frontmatter in Fin field note %s, skipping", path.name)
            continue
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError as e:
            log.warning("YAML parse failed in Fin field note %s: %s", path.name, e)
            continue
        if meta.get("status") not in (None, "active"):
            continue
        body = text[m.end():].strip()
        note = fin_field_for_prompt(meta, body)
        note["_path"] = str(path)
        notes.append(note)
    return notes


def load_fin_transfer_cells(cells_path: Path | None = None) -> list[dict]:
    """Read the human-maintained, experiment-anchored transfer taxonomy."""
    cells_path = cells_path or (PROJECT_ROOT / "knowledge" / "fin_fields" / "transfer_cells.yaml")
    if not cells_path.exists():
        return []
    import yaml

    raw = yaml.safe_load(cells_path.read_text(encoding="utf-8")) or {}
    return [
        cell for cell in (raw.get("cells") or [])
        if cell.get("status", "active") == "active"
    ]


def load_ai_innovation_playbook(playbook_path: Path | None = None) -> str:
    """Read the compact runtime digest from the full calibration asset."""
    path = playbook_path or AI_INNOVATION_PLAYBOOK_PATH
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8")
    start = text.find("## Runtime Prompt Digest")
    if start < 0:
        return text
    end = text.find("\n## ", start + len("## Runtime Prompt Digest"))
    return text[start:] if end < 0 else text[start:end].strip()


def select_fin_transfer_cells(cells: list[dict], field_notes: list[dict]) -> list[dict]:
    """Keep cells belonging to the selected daily field boundary context."""
    selected_fields = {note.get("id") for note in field_notes}
    return [cell for cell in cells if cell.get("field_id") in selected_fields]


def fin_field_for_prompt(meta: dict, body: str) -> dict:
    """Compact a Fin field note into prompt-ready mechanism boundaries."""
    return {
        "id": meta.get("id"),
        "name": meta.get("name"),
        "maturity": meta.get("maturity"),
        "last_reviewed": str(meta.get("last_reviewed") or ""),
        "related_keywords": meta.get("related_keywords", []),
        "canonical_tasks": meta.get("canonical_tasks", []),
        "mechanism_families": _extract_mechanism_families(body),
        "frontier": _section_text(body, "Mechanism-Level Frontier", max_chars=450),
        "mature_mechanisms": _section_bullets(body, "Mature Mechanisms", limit=5, max_chars=130),
        "open_bottlenecks": _section_numbered_items(body, "Open Bottlenecks", limit=7),
        "good_transfer_targets": _section_bullets(body, "Good AI Transfer Targets", limit=7, max_chars=130),
        "bad_transfer_targets": _section_bullets(body, "Bad Or Overcrowded Transfer Targets", limit=7, max_chars=130),
        "gap_construction_rules": _section_bullets(body, "Gap Construction Rules", limit=7, max_chars=130),
    }


def select_fin_field_notes(field_notes: list[dict],
                           ai_papers: list[dict],
                           fin_papers: list[dict],
                           ai_trends: dict | None = None,
                           fin_trends: dict | None = None,
                           *,
                           max_fields: int = 3) -> list[dict]:
    """Pick the most relevant Fin field notes for today's prompt context.

    This is intentionally deterministic and cheap. It prevents daily prompts
    from growing linearly with every maintained field note.
    """
    if max_fields <= 0 or len(field_notes) <= max_fields:
        return field_notes

    context_text = _selection_context_text(ai_papers, fin_papers, ai_trends, fin_trends)
    context_tokens = _tokenize(context_text)
    scored = []
    for idx, note in enumerate(field_notes):
        query = _field_selection_text(note)
        field_tokens = _tokenize(query)
        phrase_score = _phrase_score(context_text, note)
        token_score = len(context_tokens & field_tokens)
        score = phrase_score * 3 + token_score
        scored.append((score, -idx, note))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    positive = [note for score, _, note in scored if score > 0]
    selected = positive[:max_fields]
    if len(selected) < max_fields:
        selected_ids = {note.get("id") for note in selected}
        for note in field_notes:
            if note.get("id") in selected_ids:
                continue
            selected.append(note)
            if len(selected) >= max_fields:
                break
    return selected


def _selection_context_text(ai_papers: list[dict], fin_papers: list[dict],
                            ai_trends: dict | None, fin_trends: dict | None) -> str:
    parts: list[str] = []
    for paper in list(ai_papers or []) + list(fin_papers or []):
        parts.extend([
            paper.get("title", ""),
            paper.get("abstract_short", ""),
            " ".join(paper.get("method_primary") or []),
            " ".join(paper.get("domain") or []),
            " ".join(paper.get("tags") or []),
            json.dumps(paper.get("mechanism") or {}, ensure_ascii=False),
        ])
    parts.append(json.dumps(ai_trends or {}, ensure_ascii=False))
    parts.append(json.dumps(fin_trends or {}, ensure_ascii=False))
    return " ".join(parts).lower()


def _field_selection_text(note: dict) -> str:
    parts = [
        note.get("id") or "",
        note.get("name") or "",
        " ".join(note.get("related_keywords") or []),
        " ".join(note.get("canonical_tasks") or []),
        note.get("frontier") or "",
        " ".join(note.get("good_transfer_targets") or []),
        " ".join(note.get("bad_transfer_targets") or []),
    ]
    for family in note.get("mechanism_families") or []:
        parts.extend([
            family.get("name", ""),
            family.get("mechanism", ""),
            family.get("current_boundary", ""),
            family.get("gap_relevance", ""),
        ])
    for bottleneck in note.get("open_bottlenecks") or []:
        parts.extend([bottleneck.get("name", ""), bottleneck.get("description", "")])
    return " ".join(parts).lower()


def _phrase_score(context_text: str, note: dict) -> int:
    score = 0
    phrases = []
    phrases.extend(note.get("related_keywords") or [])
    phrases.extend(note.get("canonical_tasks") or [])
    phrases.extend(f.get("name", "") for f in note.get("mechanism_families") or [])
    for phrase in phrases:
        phrase = (phrase or "").lower().strip()
        if len(phrase) >= 4 and phrase in context_text:
            score += 1
    return score


_STOPWORDS = {
    "and", "for", "with", "the", "that", "this", "from", "into", "over",
    "under", "using", "model", "models", "financial", "finance", "learning",
    "machine", "large", "language", "analysis", "benchmark", "benchmarks",
}


def _tokenize(text: str) -> set[str]:
    return {
        t for t in re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{2,}", text.lower())
        if t not in _STOPWORDS
    }


def _section_text(body: str, heading: str, *, max_chars: int = 2000) -> str:
    section = _section_body(body, heading)
    return _clean_markdown_text(section)[:max_chars]


def _section_body(body: str, heading: str) -> str:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*\n(.*?)(?=^##\s+|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    m = pattern.search(body)
    return (m.group(1).strip() if m else "")


def _extract_mechanism_families(body: str) -> list[dict]:
    section = _section_body(body, "Mechanism Families")
    if not section:
        return []
    blocks = re.finditer(
        r"^###\s+(.*?)\s*\n(.*?)(?=^###\s+|\Z)",
        section,
        flags=re.DOTALL | re.MULTILINE,
    )
    families = []
    for block in blocks:
        title = block.group(1).strip()
        text = block.group(2).strip()
        families.append({
            "name": title,
            "mechanism": _clip(_label_paragraph(text, "Mechanism"), 220),
            "current_boundary": _clip(_label_paragraph(text, "Current boundary"), 180),
            "gap_relevance": _clip(_label_paragraph(text, "Gap relevance"), 160),
        })
    return families


def _label_paragraph(text: str, label: str) -> str:
    pattern = re.compile(
        rf"{re.escape(label)}:\s*(.*?)(?=\n\n[A-Z][A-Za-z -]+:\s*|\Z)",
        re.DOTALL,
    )
    m = pattern.search(text)
    return _clean_markdown_text(m.group(1)) if m else ""


def _section_bullets(body: str, heading: str, *, limit: int = 10,
                     max_chars: int | None = None) -> list[str]:
    section = _section_body(body, heading)
    bullets = []
    current = []
    for line in section.splitlines():
        if line.startswith("- "):
            if current:
                bullets.append(_clip(_clean_markdown_text(" ".join(current)), max_chars))
            current = [line[2:].strip()]
        elif current and (line.startswith("  ") or not line.strip()):
            if line.strip():
                current.append(line.strip())
        elif current:
            bullets.append(_clip(_clean_markdown_text(" ".join(current)), max_chars))
            current = []
    if current:
        bullets.append(_clip(_clean_markdown_text(" ".join(current)), max_chars))
    return bullets[:limit]


def _section_numbered_items(body: str, heading: str, *, limit: int = 10) -> list[dict]:
    section = _section_body(body, heading)
    pattern = re.compile(
        r"^\d+\.\s+\*\*(.*?)\*\*\s*\n(.*?)(?=^\d+\.\s+\*\*|\Z)",
        re.DOTALL | re.MULTILINE,
    )
    items = []
    for m in pattern.finditer(section):
        items.append({
            "name": _clean_markdown_text(m.group(1)),
            "description": _clip(_clean_markdown_text(m.group(2)), 150),
        })
        if len(items) >= limit:
            break
    return items


def _clean_markdown_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value or "").strip()
    value = value.replace("**", "").replace("`", "")
    return value


def _clip(value: str, max_chars: int | None) -> str:
    if max_chars is None or len(value) <= max_chars:
        return value
    return value[:max_chars].rsplit(" ", 1)[0].rstrip() + "..."


# ---------- Compact projections for prompts ----------

def paper_for_prompt(p: dict) -> dict:
    """Trim a paper dict to just what gap-gen prompts need."""
    return {
        "id": p["id"],
        "title": p["title"],
        "abstract_short": p.get("abstract_short") or (p.get("abstract") or "")[:600],
        "method_primary": p.get("method_primary", []),
        "mechanism": _normalize_mechanism(p.get("mechanism")),
        "domain": p.get("domain", []),
        "tags": p.get("tags", []),
        "building_blocks": p.get("building_blocks", []),
        "claims": p.get("claims", []),
        "affiliation_top": p.get("affiliation_top") or "",
        "score": round(p.get("priority_score") or 0.0, 1),
    }


def historical_mechanism_for_prompt(
    p: dict,
    *,
    matched_keywords: list[str] | None = None,
    relevance_score: float | None = None,
) -> dict:
    """Compact historical AI mechanism memory for daily generation prompts."""
    return {
        "id": p["id"],
        "title": p["title"],
        "publication_date": str(p.get("publication_date") or ""),
        "method_primary": p.get("method_primary", []),
        "mechanism": _normalize_mechanism(p.get("mechanism")),
        "domain": p.get("domain", []),
        "tags": p.get("tags", []),
        "building_blocks": (p.get("building_blocks") or [])[:5],
        "claims": (p.get("claims") or [])[:3],
        "score": round(p.get("priority_score") or 0.0, 1),
        "matched_keywords": matched_keywords or [],
        "retrieval_score": relevance_score,
    }


def mapping_for_prompt(m: dict) -> dict:
    """Compact official mapping projection for generation prompts.

    Supports both the legacy schema (ai_concept/fin_concept) and the newer
    mechanism-level schema generated by mapping drafts.
    """
    return {
        "id": m.get("id"),
        "status": m.get("status"),
        "ai_concept": m.get("ai_concept") or m.get("ai_mechanism"),
        "fin_concept": m.get("fin_concept") or m.get("fin_structure"),
        "ai_mechanism": m.get("ai_mechanism") or m.get("ai_concept"),
        "ai_problem": m.get("ai_problem"),
        "ai_prerequisites": m.get("ai_prerequisites"),
        "fin_structure": m.get("fin_structure") or m.get("fin_concept"),
        "fin_problem": m.get("fin_problem"),
        "bridge": m.get("bridge"),
        "match_status": m.get("match_status"),
        "mismatch_severity": m.get("mismatch_severity"),
        "evidence_ai_papers": m.get("evidence_ai_papers", []),
        "evidence_fin_papers": m.get("evidence_fin_papers", []),
        "source_gap_id": m.get("source_gap_id"),
        "source_brief": m.get("source_brief"),
        "updated_at": m.get("updated_at") or m.get("last_updated"),
        "notes": (m.get("notes") or "")[:300],
    }


def mapping_brief(m: dict) -> dict:
    """Even leaner — for self-check duplication detection."""
    return {
        "id": m.get("id"),
        "status": m.get("status"),
        "ai_concept": m.get("ai_concept") or m.get("ai_mechanism"),
        "fin_concept": m.get("fin_concept") or m.get("fin_structure"),
        "ai_mechanism": m.get("ai_mechanism") or m.get("ai_concept"),
        "fin_structure": m.get("fin_structure") or m.get("fin_concept"),
        "bridge": m.get("bridge"),
    }
