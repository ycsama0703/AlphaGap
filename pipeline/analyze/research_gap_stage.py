"""Daily Step 2.5 — deep research-gap generation (precision-first, low-volume, best-effort).

Picks the day's top-N anchor AI papers, deep-mines each (L3 full text → mechanisms/ablations/
boundaries), and generates runnable experiment slices gated by the empirical pre-mortem. Additive to
the existing engineering-gap path; NEVER breaks the daily run (every step guarded). Volume is small by
design (RESEARCH_GAP_PAPERS, default 2) — see feedback_precision_over_breadth.

Returns a list of research_gap dicts, each tagged with its source paper. Headless/cron-safe (mining =
node subprocess + DeepSeek). Mining failures (e.g. PDF unavailable) are skipped, not fatal.
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


def generate_daily_research_gaps(ctx: dict, *, n_papers: int = 2, date_tag: str = "latest", client=None) -> dict:
    """ctx = the gap pipeline context. Mines the top-n anchor papers → research gaps with slices.
    Returns {"research_gaps": [...], "mined_papers": [...], "skipped": [...]}. Best-effort."""
    if n_papers <= 0:
        return {"research_gaps": [], "mined_papers": [], "skipped": []}
    try:
        from ..papermine.mine import mine_paper
        from ..agent_opportunity import (generate_agent_opportunity_map,
                                         generate_agent_gap_brief, render_agent_brief_md)
        from ..llm_client import opus_client, agent_client
    except Exception as e:
        log.warning("research-gap stage unavailable (import): %s", e)
        return {"research_gaps": [], "mined_papers": [], "skipped": [], "error": str(e)}

    # HYBRID model routing for the quality-sensitive steps:
    #   • L3 full-text paper mining (comprehension)          → opus               (opus_client)
    #   • agent mechanism-gap generation + brief (AI side)   → openai/gpt-chat-latest (agent_client)
    # The cheap mechanical work (L1/L2 extract, gap pipeline) stays on the default model (`client`).
    # agent_client degrades to opus (oc), which degrades to `client`, if OpenRouter isn't configured.
    oc = opus_client(default=client)
    ac = agent_client(default=oc)

    fin_fields = ctx.get("fin_field_boundaries") or ctx.get("fin_field_boundaries_all") or []
    candidates = ctx.get("ai_recent_papers", []) or []
    pool, mined_ids, skipped = [], [], []
    for p in candidates:
        if len(pool) >= n_papers:
            break
        aid = _arxiv_id(p)
        if not aid:
            continue
        try:
            rec = mine_paper(aid, client=oc)   # L3 full-text mining → opus
            n_sub = len(rec.get("transferable_sub_mechanisms") or [])
            if n_sub == 0:
                skipped.append({"arxiv_id": aid, "reason": "no sub-mechanisms mined"}); continue
            rec["_title"] = p.get("title", "")
            pool.append(rec); mined_ids.append(aid)
            log.info("research-gap stage: mined %s (%d sub-mechanisms)", aid, n_sub)
        except Exception as e:
            skipped.append({"arxiv_id": aid, "reason": str(e)[:120]})
            log.warning("research-gap stage: mining %s failed: %s", aid, str(e)[:120])

    if not pool:
        log.info("research-gap stage: no papers mined (skipped %d)", len(skipped))
        return {"research_gaps": [], "mined_papers": [], "skipped": skipped}

    try:
        # AI-PROTAGONIST generator: contributions are AI agent mechanisms / reliability / benchmarks,
        # finance is the hard scenario — NOT return prediction. (Replaces the old return-prone generator.)
        gaps = generate_agent_opportunity_map(pool, client=ac)   # agent mechanism-gap generation → gpt-chat-latest
    except Exception as e:
        log.warning("research-gap stage: generation failed: %s", str(e)[:160])
        return {"research_gaps": [], "mined_papers": mined_ids, "skipped": skipped, "error": str(e)}

    for g in gaps:
        g["_source_papers"] = mined_ids

    # Expand the top-N by composite score into downloadable TEST-facing briefs (precision-first:
    # don't brief all of them — opus briefs are ~$0.2 each). Best-effort; a brief failure is non-fatal.
    gaps.sort(key=lambda g: (g.get("scores", {}) or {}).get("composite", 0) or 0, reverse=True)
    n_brief = int(__import__("os").environ.get("RESEARCH_GAP_BRIEFS", "2"))
    from pathlib import Path as _P
    bdir = _P(__file__).resolve().parent.parent.parent / "briefs"
    bdir.mkdir(exist_ok=True)
    for i, g in enumerate(gaps[:n_brief], 1):
        try:
            anchor = pool[0] if pool else None
            brief = generate_agent_gap_brief(g, mined_anchor=anchor, client=ac)   # agent mechanism brief → gpt-chat-latest
            md = render_agent_brief_md(brief, g)
            fname = f"{date_tag}-MECH-{i}.md"
            (bdir / fname).write_text(md, encoding="utf-8")
            g["_brief_file"] = fname
            g["_brief"] = brief
            log.info("research-gap stage: brief written %s (composite %s)", fname,
                     (g.get("scores", {}) or {}).get("composite"))
        except Exception as e:
            log.warning("research-gap stage: brief for gap %d failed: %s", i, str(e)[:120])

    log.info("research-gap stage: %d agent×finance opportunit(ies) from %d paper(s); %d briefs",
             len(gaps), len(mined_ids), sum(1 for g in gaps if g.get("_brief_file")))
    return {"research_gaps": gaps, "mined_papers": mined_ids, "skipped": skipped,
            "mined_records": pool}
