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


# O2 — anchor rotation + diversity. Instead of the same static top-N-by-score every
# day, fetch a larger pool, re-rank with a recency boost (so the daily set shifts as
# new papers arrive), and greedily select with per-affiliation / per-topic caps (so a
# day's anchors aren't N variants of one lab/mechanism). Tunables — review freely.
PAPER_POOL_MULT = 6        # fetch top_n × this, then diversify down to top_n
RECENCY_WEIGHT = 0.5       # newest in-window paper gets +50% effective score; oldest +0%
MAX_PER_AFFILIATION = 3    # ≤ this many anchors from the same lead affiliation
MAX_PER_TOPIC = 4          # ≤ this many anchors sharing a coarse topic key
MIN_RECENT_SLOTS = 5       # reserve this many slots for the NEWEST in-window papers
                           # (regardless of score) so fresh anchors enter every day


def _paper_topic_key(d: dict) -> str:
    dom = d.get("domain") or []
    meth = d.get("method_primary") or []
    return (dom[0] if dom else (meth[0] if meth else "other")).strip().lower()


def _select_diverse_recent(pool: list[dict], top_n: int, end_date: date,
                           window_days: int, exclude_ids: set | None = None) -> list[dict]:
    """Recency-weighted, diversity-capped selection from a scored pool.

    O3: papers in `exclude_ids` (anchored in the last few days) are deprioritized —
    held back as last-resort backfill — so daily generation explores fresh papers
    instead of re-anchoring the same ones. Soft, never returns fewer than available.
    """
    exclude_ids = exclude_ids or set()
    for d in pool:
        try:
            pub = date.fromisoformat(str(d.get("publication_date"))[:10])
            age = max(0, (end_date - pub).days)
        except Exception:
            age = window_days
        recency = 1.0 - min(age, window_days) / max(1, window_days)
        d["_eff"] = (d.get("priority_score") or 0.0) * (1.0 + RECENCY_WEIGHT * recency)
    # Prefer not-recently-anchored papers; keep excluded as fallback for backfill.
    fresh = [d for d in pool if d.get("id") not in exclude_ids]
    stale = [d for d in pool if d.get("id") in exclude_ids]
    pool = fresh
    selected: list[dict] = []
    per_aff: dict[str, int] = {}
    per_topic: dict[str, int] = {}

    def _take(d):
        aff = d.get("affiliation_top") or "?"
        tk = _paper_topic_key(d)
        per_aff[aff] = per_aff.get(aff, 0) + 1
        per_topic[tk] = per_topic.get(tk, 0) + 1
        selected.append(d)

    # Reserve a few slots for the NEWEST in-window papers (regardless of score), so
    # fresh anchors enter daily and the set isn't frozen by sticky priority_score.
    if MIN_RECENT_SLOTS > 0 and len(pool) > top_n:
        by_recent = sorted(pool, key=lambda d: str(d.get("publication_date")), reverse=True)
        chosen_ids: set = set()
        for d in by_recent:
            if len(selected) >= min(MIN_RECENT_SLOTS, top_n):
                break
            if per_topic.get(_paper_topic_key(d), 0) >= MAX_PER_TOPIC:
                continue
            _take(d); chosen_ids.add(id(d))
        pool = [d for d in pool if id(d) not in chosen_ids]

    pool.sort(key=lambda d: -d["_eff"])
    for d in pool:
        aff = d.get("affiliation_top") or "?"
        tk = _paper_topic_key(d)
        if per_aff.get(aff, 0) >= MAX_PER_AFFILIATION:
            continue
        if per_topic.get(tk, 0) >= MAX_PER_TOPIC:
            continue
        per_aff[aff] = per_aff.get(aff, 0) + 1
        per_topic[tk] = per_topic.get(tk, 0) + 1
        selected.append(d)
        if len(selected) >= top_n:
            break
    # Backfill (by effective score) if the caps left us short — fresh first, then
    # fall back to recently-anchored (stale) papers only if still short.
    if len(selected) < top_n:
        chosen = {id(x) for x in selected}
        for d in pool + sorted(stale, key=lambda d: -d.get("_eff", 0.0)):
            if id(d) not in chosen:
                selected.append(d)
                chosen.add(id(d))
                if len(selected) >= top_n:
                    break
    for d in selected:
        d.pop("_eff", None)
    return selected


def get_top_papers(side: str, end_date: date, *, top_n: int = 20,
                   window_days: int = 14, exclude_ids: set | None = None) -> list[dict]:
    """Top N papers on `side` within window — recency-weighted + diversity-capped
    (O2). Fetches a larger score-ranked pool, then rotates/diversifies anchors so
    daily generation isn't anchored on the same few papers every run.

    Returns dicts with full extraction (l1 + l2 when available).
    """
    start = end_date - timedelta(days=window_days - 1)
    pool_limit = max(top_n * PAPER_POOL_MULT, top_n)
    cols = """p.id, p.title, p.abstract, p.publication_date, p.affiliations, p.url,
                   p.arxiv_categories,
                   e.side, e.method_primary_json, e.domain_json, e.tags_json,
                   e.mechanism_description_json,
                   e.building_blocks_json, e.claims_json, e.benchmarks_json,
                   s.priority_score, s.signals_json"""
    where = f"""FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND (e.side = ? OR e.side = 'both')
              AND date(p.publication_date) >= ?
              AND date(p.publication_date) <= ?
              AND {db.TRIGGER_ELIGIBILITY_GUARD}"""
    params = (side, start.isoformat(), end_date.isoformat())
    with db.connect() as conn:
        # Pool = high-score candidates ∪ most-recent candidates, so genuinely recent
        # (often lower-scored) papers are eligible for the recency-reserved slots —
        # not just the sticky top-by-score set.
        by_score = conn.execute(
            f"SELECT {cols} {where} ORDER BY s.priority_score DESC LIMIT ?",
            (*params, pool_limit),
        ).fetchall()
        by_recent = conn.execute(
            f"SELECT {cols} {where} ORDER BY date(p.publication_date) DESC LIMIT ?",
            (*params, max(top_n * 2, MIN_RECENT_SLOTS * 4)),
        ).fetchall()
    seen_ids: set = set()
    rows = []
    for r in list(by_score) + list(by_recent):
        if r["id"] in seen_ids:
            continue
        seen_ids.add(r["id"])
        rows.append(r)

    pool = _project_paper_rows(rows)
    return _select_diverse_recent(pool, top_n, end_date, window_days, exclude_ids=exclude_ids)


def _project_paper_rows(rows) -> list[dict]:
    """Row → paper dict (parse JSON columns, normalize mechanism, derive helpers)."""
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


# Conference look-back: every day, blend in a few peer-reviewed conference papers
# (ICLR/NeurIPS via OpenReview) as anchors — high quality + topic breadth the HF-daily
# stream lacks — and MORE of them on thin-inflow days. These are stored as evidence
# (eligible_for_daily_trigger=0), so we deliberately bypass the trigger guard for a
# controlled quota. Tunables — review freely.
CONF_LOOKBACK_BASE = 3        # blended in every day
CONF_LOOKBACK_THIN_BONUS = 6  # extra when fresh inflow is thin
CONF_THIN_FRESH_THRESHOLD = 8 # "thin day" = fewer than this many fresh eligible papers (3d)


def count_fresh_eligible(side: str, end_date: date, *, lookback_days: int = 3) -> int:
    """How many trigger-eligible `side` papers were published in the last few days —
    the signal for whether today is a 'thin' day that needs more conference look-back."""
    start = (end_date - timedelta(days=lookback_days - 1)).isoformat()
    with db.connect() as conn:
        return conn.execute(
            f"""SELECT count(*) FROM papers p
                JOIN paper_extractions e ON e.paper_id = p.id
                LEFT JOIN paper_signals s ON s.paper_id = p.id
                WHERE e.extraction_status IN ('l1_done','l2_done')
                  AND (e.side = ? OR e.side = 'both')
                  AND date(p.publication_date) >= ? AND date(p.publication_date) <= ?
                  AND {db.TRIGGER_ELIGIBILITY_GUARD}""",
            (side, start, end_date.isoformat()),
        ).fetchone()[0]


def get_conference_lookback(end_date: date, n: int, *, side: str = "ai",
                            exclude_ids: set | None = None) -> list[dict]:
    """Peer-reviewed conference papers (OpenReview) as look-back anchors. Bypasses the
    trigger guard (these are evidence-tier), excludes recently-anchored, rotates by
    recency, and diversity-caps by topic."""
    if n <= 0:
        return []
    exclude_ids = exclude_ids or set()
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT p.id, p.title, p.abstract, p.publication_date, p.affiliations, p.url,
                       p.arxiv_categories,
                       e.side, e.method_primary_json, e.domain_json, e.tags_json,
                       e.mechanism_description_json,
                       e.building_blocks_json, e.claims_json, e.benchmarks_json,
                       s.priority_score, s.signals_json
                FROM paper_sources ps
                JOIN papers p ON p.id = ps.paper_id
                JOIN paper_extractions e ON e.paper_id = p.id
                LEFT JOIN paper_signals s ON s.paper_id = p.id
                WHERE ps.source = 'openreview'
                  AND e.extraction_status IN ('l1_done','l2_done')
                  AND (e.side = ? OR e.side = 'both')
                ORDER BY date(p.publication_date) DESC
                LIMIT ?""",
            (side, max(n * 8, 40)),
        ).fetchall()
    pool = [d for d in _project_paper_rows(rows) if d.get("id") not in exclude_ids]
    selected, per_topic = [], {}
    for d in pool:
        tk = _paper_topic_key(d)
        if per_topic.get(tk, 0) >= 2:
            continue
        per_topic[tk] = per_topic.get(tk, 0) + 1
        d["is_conference"] = True  # mark peer-reviewed look-back for downstream/prompt
        selected.append(d)
        if len(selected) >= n:
            break
    return selected


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


def load_experiment_findings(bank_path: Path | None = None) -> list[dict]:
    """ACCUMULATE → DISCOVER feedback: read experiment-derived findings from the
    findings-bank (a kind=agent `bank.jsonl`) and project them into the same mapping
    shape as literature mappings, so DISCOVER dedups against directions WE have
    actually tested (esp. refuted ones). Degrades to [] if no bank is present.

    Sources are MERGED (union by gap_id): the live/env bank (~/.xp/findings/bank.jsonl, freshest
    locally) UNION the committed repo seed db/seed/findings_bank.jsonl (the kill-memory that travels
    via git). Live entries win on conflict; repo-seed-only entries are added. This keeps a deploy
    target like luyao4 — whose ~/.xp bank can be stale or absent — current with the latest kills
    without any scp (it just git-pulls the seed). Degrades to [] if neither source exists.
    """
    import os
    repo_seed = PROJECT_ROOT / "db" / "seed" / "findings_bank.jsonl"
    live = bank_path or Path(
        os.environ.get("ALPHAGAP_FINDINGS_BANK", str(Path.home() / ".xp/findings/bank.jsonl"))
    )
    sources, lines = [], []                      # live first (precedence), then repo seed
    if live.is_file():
        sources.append(live)
    if repo_seed.is_file() and repo_seed.resolve() not in {s.resolve() for s in sources}:
        sources.append(repo_seed)
    for src in sources:
        lines.extend(src.read_text().splitlines())
    if not lines:
        return []
    seen_gap_ids, out = set(), []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
        except Exception:
            continue
        md = e.get("metadata", {})
        status = md.get("status")
        if status in (None, "untested"):   # inconclusive runs aren't findings about the gap
            continue
        gap_id = md.get("gap_id", "?")
        if gap_id in seen_gap_ids:          # union by gap_id; live bank (read first) wins on conflict
            continue
        seen_gap_ids.add(gap_id)
        # mechanism-level (brand-free) keys; fall back to the experiment title only
        # if the bank entry predates the mechanism fields.
        ai_mech = md.get("ai_mechanism") or e.get("title", "")
        fin_mech = md.get("fin_mechanism") or md.get("mechanism_family") or md.get("field_id") or ""
        out.append({
            "id": f"EXP-{gap_id}",
            "status": status,                       # validated / partially_explored / refuted
            "ai_concept": ai_mech,
            "ai_mechanism": ai_mech,
            "fin_concept": fin_mech,
            "fin_structure": fin_mech,
            "field_id": md.get("field_id", ""),
            "mechanism_family": md.get("mechanism_family", ""),
            "cost_level": md.get("cost_level", ""),         # feeds cheap-gap selection
            "findata_native": md.get("findata_native"),
            "notes": (e.get("content", "") or "")[:300],
            "source": "experiment",
            "source_gap_id": gap_id,
            "source_brief": md.get("brief_path", ""),
            "updated_at": md.get("stamped_at", ""),
        })
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
        # peer-reviewed conference look-back — high signal; the model should weight these.
        "peer_reviewed_conference": bool(p.get("is_conference")),
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
