"""Daily Step 2.5 — deep research-gap generation (precision-first, low-volume, best-effort).

Picks the day's top-N anchor AI papers, deep-mines each (L3 full text → mechanisms/ablations/
boundaries), and generates runnable experiment slices gated by the empirical pre-mortem. Additive to
the existing engineering-gap path; NEVER breaks the daily run (every step guarded). Volume is small by
design (RESEARCH_GAP_PAPERS, default 4) and the anchors are a MIX of fresh-arxiv + peer-reviewed
conference (OpenReview) papers, interleaved — so gaps don't collapse onto agent-heavy recent arxiv.
See feedback_precision_over_breadth.

Returns a list of research_gap dicts, each tagged with its source paper. Headless/cron-safe (mining =
pure-python httpx+pypdf + the gpt deep model). Mining failures (e.g. PDF unavailable) are skipped, not fatal.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _arxiv_id(paper: dict) -> str | None:
    pid = paper.get("arxiv_id") or paper.get("id") or ""
    pid = str(pid).strip()
    # arxiv-format id like 2606.03985 (HF Daily papers store the arxiv id as `id`)
    import re
    return pid if re.fullmatch(r"\d{4}\.\d{4,5}", pid) else None


def _openreview_pdf_url(paper: dict) -> str | None:
    """Conference look-back papers have no arxiv PDF, but their full text IS on OpenReview
    (openreview.net/pdf?id=<note_id>), and fetch_fulltext downloads any http URL — so they ARE
    L3-mineable. id is 'openreview:<note_id>'. This lets the mechanism line anchor on peer-reviewed
    conference work, not only agent-heavy recent arxiv (breaks the repetitive-gap monoculture)."""
    if not paper.get("peer_reviewed_conference"):
        return None
    pid = str(paper.get("id") or "")
    note = pid.split(":", 1)[1] if pid.startswith("openreview:") else ""
    return f"https://openreview.net/pdf?id={note}" if note else None


def _mine_anchor_pool(candidates: list[dict], n_papers: int, *, mine_paper, oc) -> tuple[list, list, list]:
    """Mine up to n_papers anchors from `candidates` (interleaving fresh-arxiv + conference).
    Returns (pool, mined_ids, skipped). Shared by both lines (applied + theory)."""
    if n_papers <= 0 or not candidates:
        return [], [], []
    fresh = [(p, _arxiv_id(p)) for p in candidates if _arxiv_id(p)]
    conf = [(p, _openreview_pdf_url(p)) for p in candidates
            if not _arxiv_id(p) and _openreview_pdf_url(p)]
    order, fi, ci = [], 0, 0
    while fi < len(fresh) or ci < len(conf):
        if fi < len(fresh):
            order.append(fresh[fi]); fi += 1
        if ci < len(conf):
            order.append(conf[ci]); ci += 1
    pool, mined_ids, skipped = [], [], []
    for p, mine_arg in order:
        if len(pool) >= n_papers:
            break
        try:
            rec = mine_paper(mine_arg, client=oc)   # L3 full-text mining (arxiv or OpenReview) → opus
            n_sub = len(rec.get("transferable_sub_mechanisms") or [])
            if n_sub == 0:
                skipped.append({"id": mine_arg, "reason": "no sub-mechanisms mined"}); continue
            rec["_title"] = p.get("title", "")
            rec["_is_conference"] = bool(p.get("peer_reviewed_conference"))
            pool.append(rec); mined_ids.append(rec.get("arxiv_id") or mine_arg)
            log.info("research-gap stage: mined %s (%d sub-mech, conf=%s)",
                     rec.get("arxiv_id") or mine_arg, n_sub, rec["_is_conference"])
        except Exception as e:
            skipped.append({"id": mine_arg, "reason": str(e)[:120]})
            log.warning("research-gap stage: mining %s failed: %s", mine_arg, str(e)[:120])
    return pool, mined_ids, skipped


def generate_daily_research_gaps(ctx: dict, *, n_papers: int = 2, date_tag: str = "latest", client=None) -> dict:
    """ctx = the gap pipeline context. Mines the top-n anchor papers → research gaps with slices.
    Returns {"research_gaps": [...], "mined_papers": [...], "skipped": [...]}. Best-effort."""
    if n_papers <= 0:
        return {"research_gaps": [], "mined_papers": [], "skipped": []}
    try:
        from ..papermine.mine import mine_paper
        from ..agent_opportunity import (generate_agent_opportunity_map,
                                         generate_agent_gap_brief, render_agent_brief_md)
        from ..llm_client import opus_client
    except Exception as e:
        log.warning("research-gap stage unavailable (import): %s", e)
        return {"research_gaps": [], "mined_papers": [], "skipped": [], "error": str(e)}

    # HYBRID: the quality-sensitive deep steps (L3 full-text mining, mechanism-gap generation, brief)
    # run on the OpenRouter deep model (OPENROUTER_MODEL_OPUS = openai/gpt-chat-latest). The cheap
    # mechanical work (L1/L2 extract, gap pipeline) stays on the default model (`client`). The deep
    # client degrades to `client` if OpenRouter isn't configured.
    oc = opus_client(default=client)

    fin_fields = ctx.get("fin_field_boundaries") or ctx.get("fin_field_boundaries_all") or []

    # Two parallel lines, each with its own quota (precision-first; theory must not be crowded out by
    # the high-volume applied stream). Mine a MIX of fresh-arxiv + peer-reviewed conference, INTERLEAVED.
    import os as _os
    n_ai = int(_os.environ.get("RESEARCH_GAP_PAPERS_AI", str(n_papers)))       # APPLIED line (AI×Fin)
    n_theory = int(_os.environ.get("RESEARCH_GAP_PAPERS_THEORY", "2"))         # THEORY line
    ai_candidates = ctx.get("ai_recent_papers", []) or []
    theory_candidates = ctx.get("theory_recent_papers", []) or []
    ai_pool, ai_ids, ai_skip = _mine_anchor_pool(ai_candidates, n_ai, mine_paper=mine_paper, oc=oc)
    th_pool, th_ids, th_skip = _mine_anchor_pool(theory_candidates, n_theory, mine_paper=mine_paper, oc=oc)
    pool = ai_pool + th_pool
    mined_ids = ai_ids + th_ids
    skipped = ai_skip + th_skip
    log.info("research-gap stage: mined %d applied + %d theory anchors", len(ai_pool), len(th_pool))

    # cost of the deep (gpt) client — added to the daily total in main; 0 if it fell back to `client`
    # (then its spend is already inside client.estimate_cost_usd()).
    _oc_cost = lambda: round(oc.estimate_cost_usd() if oc is not client else 0.0, 4)

    if not pool:
        log.info("research-gap stage: no papers mined (skipped %d)", len(skipped))
        return {"research_gaps": [], "mined_papers": [], "skipped": skipped, "cost_usd": _oc_cost()}

    # KILL MEMORY: feed already-tested/shelved gaps so the generator stops re-proposing dead directions
    # (it otherwise never sees the findings bank). Refuted + agent/ml-finance/factor-mining fields.
    try:
        from . import context as _ctx
        _all = _ctx.load_experiment_findings()
        killed = [k for k in _all if k.get("status") in ("refuted", "superseded_by_validation")
                  and k.get("field_id") in ("financial_llm_agents", "ml_finance", "agentic_factor_mining")]
    except Exception as e:
        killed = []
        log.warning("research-gap stage: kill-memory load failed: %s", str(e)[:100])

    # Generate each line with its own track framing. APPLIED = AI-protagonist; THEORY = foundational
    # mechanism × finance-structure (must name the incumbent it beats; frontier-not-classics; self-screen).
    gaps = []
    for label, line_pool, track in (("applied", ai_pool, "ai"), ("theory", th_pool, "theory")):
        if not line_pool:
            continue
        try:
            g_line = generate_agent_opportunity_map(line_pool, client=oc, killed=killed, track=track) or []
            for g in g_line:
                g["_track"] = track
            gaps.extend(g_line)
            log.info("research-gap stage: %s line → %d gaps (fed %d killed)", label, len(g_line), len(killed))
        except Exception as e:
            log.warning("research-gap stage: %s generation failed: %s", label, str(e)[:160])
    if not gaps:
        return {"research_gaps": [], "mined_papers": mined_ids, "skipped": skipped,
                "error": "no gaps generated", "cost_usd": _oc_cost()}

    for g in gaps:
        g["_source_papers"] = mined_ids

    # Expand the top-N by composite score into downloadable TEST-facing briefs (precision-first:
    # don't brief all of them — opus briefs are ~$0.2 each). Best-effort; a brief failure is non-fatal.
    _comp = lambda g: (g.get("scores", {}) or {}).get("composite", 0) or 0
    gaps.sort(key=_comp, reverse=True)
    # Brief budget per line so the theory line is GUARANTEED representation (precision-first: we want
    # theory output visible, not crowded out by higher-scoring applied gaps). Top-by-composite within each.
    n_brief_ai = int(__import__("os").environ.get("RESEARCH_GAP_BRIEFS_AI", "2"))
    n_brief_theory = int(__import__("os").environ.get("RESEARCH_GAP_BRIEFS_THEORY", "1"))
    to_brief = (
        [g for g in gaps if g.get("_track") != "theory"][:n_brief_ai]
        + [g for g in gaps if g.get("_track") == "theory"][:n_brief_theory]
    )
    from pathlib import Path as _P
    bdir = _P(__file__).resolve().parent.parent.parent / "briefs"
    bdir.mkdir(exist_ok=True)
    # index the mined pool by paper id so each brief anchors to ITS OWN source mechanism, not pool[0]
    by_pid = {}
    for rec in pool:
        by_pid[str(rec.get("arxiv_id") or "")] = rec
    ai_i = th_i = 0
    for g in to_brief:
        try:
            track = g.get("_track", "ai")
            if track == "theory":
                th_i += 1; tag = f"THEORY-{th_i}"
            else:
                ai_i += 1; tag = f"AI-{ai_i}"
            anchor_pid = str(((g.get("anchor") or {}).get("paper_id")) or "")
            anchor = by_pid.get(anchor_pid) or (pool[0] if pool else None)
            brief = generate_agent_gap_brief(g, mined_anchor=anchor, client=oc, track=track)   # mechanism brief → deep model
            md = render_agent_brief_md(brief, g)
            fname = f"{date_tag}-MECH-{tag}.md"
            (bdir / fname).write_text(md, encoding="utf-8")
            g["_brief_file"] = fname
            g["_brief"] = brief
            log.info("research-gap stage: brief written %s (composite %s)", fname, _comp(g))
        except Exception as e:
            log.warning("research-gap stage: brief failed: %s", str(e)[:120])

    log.info("research-gap stage: %d agent×finance opportunit(ies) from %d paper(s); %d briefs",
             len(gaps), len(mined_ids), sum(1 for g in gaps if g.get("_brief_file")))
    return {"research_gaps": gaps, "mined_papers": mined_ids, "skipped": skipped,
            "mined_records": pool, "cost_usd": _oc_cost()}
