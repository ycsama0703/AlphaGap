"""Write daily inbox markdown — the file you git pull and review.

Structure:
  inbox/YYYY-MM-DD.md           — full audit: papers, trends, all gaps + mapping proposals

Workflow:
  - server cron runs daily, commits inbox/yyyy-mm-dd.md, pushes to GitHub
  - you `git pull`, open the file, mark approvals/rejections inline
  - move approved mapping actions into mappings/ as separate .md files
  - commit & push; server reads latest mappings next run
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from ..config import PROJECT_ROOT
from .compute import compute_profile_summary


log = logging.getLogger(__name__)


def write_daily_inbox(d: date, payload: dict, *, out_dir: Path | None = None) -> Path:
    """Render markdown for one day's run. Returns path."""
    out_dir = out_dir or (PROJECT_ROOT / "inbox")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{d.isoformat()}.md"

    parts = [
        f"# AlphaGap Daily — {d.isoformat()}",
        "",
        _section_stats(payload),
        _section_gaps_email(payload),       # ⭐ moved to top
        _section_gaps_all(payload),
        _section_trends(payload),
        _section_top_papers(payload),
        _section_mapping_drafts(payload),
        _section_mapping_actions(payload),
        _section_review_instructions(),
    ]
    path.write_text("\n\n".join(p for p in parts if p), encoding="utf-8")
    log.info("Inbox written to %s", path)
    return path


def _section_stats(p: dict) -> str:
    s = p.get("stats", {})
    selected = s.get("fin_fields_selected") or []
    available = s.get("fin_fields_available") or []
    field_line = ""
    if selected:
        field_line = (
            f"\n- Fin field boundaries selected: **{', '.join(selected)}**"
            f" ({len(selected)}/{len(available) or len(selected)})"
        )
    return (
        f"## Pipeline\n\n"
        f"- Papers fetched: **{s.get('fetched', '?')}** | candidates: **{s.get('candidates', '?')}**\n"
        f"- L1 extracted: {s.get('l1_done', '?')} | L2 extracted: {s.get('l2_done', '?')}\n"
        f"- Gaps generated: {len(p.get('theoretical', []))} theoretical + {len(p.get('engineering', []))} engineering\n"
        f"- Accepted: {len(p.get('accepted', []))} | Email-ready: {len(p.get('email_ready', []))}\n"
        f"- Mapping actions proposed: {len(p.get('mapping_actions', []))}\n"
        f"{field_line}\n"
        f"- LLM cost: ${s.get('cost_usd', 0):.4f}"
    )


def _section_top_papers(p: dict) -> str:
    papers = p.get("top_papers", [])
    if not papers:
        return ""
    lines = ["## Top Papers (今日重点)"]
    for paper in papers[:10]:
        title = paper.get("title", "?")[:100]
        affil = paper.get("affiliation_top", "") or "—"
        score = paper.get("score") or paper.get("priority_score") or 0
        url = paper.get("url") or f"https://arxiv.org/abs/{paper.get('id', '')}"
        methods = ", ".join(paper.get("method_primary", [])[:2])
        lines.append(f"\n### [{paper.get('id', '?')}] {title}")
        lines.append(f"- **affiliation**: {affil} · **score**: {score} · [arXiv]({url})")
        if methods:
            lines.append(f"- **method**: {methods}")
        tags = paper.get("tags") or []
        if tags:
            lines.append(f"- **tags**: {', '.join(tags[:5])}")
    return "\n".join(lines)


def _section_trends(p: dict) -> str:
    wa = p.get("stats", {}).get("window_ai", 90)
    wf = p.get("stats", {}).get("window_fin", 180)
    out = [f"## Mechanism Trends (AI {wa}d · Fin {wf}d rolling)"]
    for side, label in [("ai", "AI"), ("fin", "Fin")]:
        trends = p.get(f"{side}_trends", {})
        out.append(f"\n### {label}")
        for bucket, title in [
            ("rising", "↑ Rising"),
            ("new_emergence", "★ New emergence"),
            ("stable_hot", "→ Stable hot"),
            ("falling", "↓ Falling"),
        ]:
            items = trends.get(bucket, []) if isinstance(trends, dict) else []
            if not items:
                continue
            out.append(f"\n**{title}**\n")
            for it in items:
                name = it.get("name", "?")
                problem = it.get("what_problem", "")
                contrast = it.get("contrast_to_prior", "")
                rep = it.get("representative_one_liner", "")
                members = it.get("member_papers", []) or []
                cv = it.get("citation_velocity_30d", 0)
                affs = it.get("representative_affiliations", []) or []
                out.append(f"#### {name}\n")
                if rep:
                    out.append(f"- **代表性表述**: {rep}")
                if problem:
                    out.append(f"- **问题**: {problem}")
                if contrast:
                    out.append(f"- **vs prior**: {contrast}")
                stats_bits = []
                if members:
                    stats_bits.append(f"{len(members)} papers ({', '.join(members[:5])})")
                if cv:
                    stats_bits.append(f"+{cv} cites/30d")
                if affs:
                    stats_bits.append(", ".join(affs[:3]))
                if stats_bits:
                    out.append(f"- _{ ' · '.join(stats_bits)}_\n")
    return "\n".join(out)


def _section_gaps_email(p: dict) -> str:
    eg = p.get("email_ready", [])
    if not eg:
        return "## Gaps (email-ready)\n\n_None today._"
    out = ["## Gaps (email-ready)"]
    for item in eg:
        out.append(_render_gap_detail(item, full=True))
    return "\n".join(out)


def _section_gaps_all(p: dict) -> str:
    accepted = p.get("accepted", [])
    below = [a for a in accepted if not a["score"]["passes_email_threshold"]]
    if not below:
        return ""
    out = ["## Other Accepted Gaps (below email threshold but worth keeping)"]
    for item in below:
        out.append(_render_gap_detail(item, full=False))
    return "\n".join(out)


def _render_gap_detail(item: dict, *, full: bool) -> str:
    g = item["gap"]
    s = item["score"]
    gid = g.get("_id", "?")
    gtype = item["type"]
    hypothesis = g.get("hypothesis", "?")

    head = (
        f"\n### [{gid}] ({gtype}) total={s['total']} · "
        f"novelty={s['novelty']} · actionability={s['actionability']} · "
        f"theory={s.get('theoretical_support', '?')}\n\n"
        f"**假设**: {hypothesis}\n"
    )
    head += f"- novelty: {s.get('novelty_reason', '')}\n"
    head += f"- actionability: {s.get('actionability_reason', '')}\n"
    head += f"- theoretical_support: {s.get('theoretical_support_reason', '')}\n"
    components = s.get("theoretical_support_components") or {}
    if components:
        comp_text = ", ".join(f"{k}={v}" for k, v in components.items())
        head += f"- theoretical_support_components: {comp_text}\n"
    if s.get("email_gate"):
        head += f"- email_gate: {s.get('email_gate')} — {s.get('email_gate_reason', '')}\n"

    field = g.get("field_boundary_alignment") or {}
    if field:
        head += "\n**Fin field boundary**:\n"
        if field.get("field_id"):
            head += f"- Field: `{field['field_id']}`\n"
        if field.get("mechanism_family"):
            head += f"- Mechanism family: {field['mechanism_family']}\n"
        if field.get("open_bottleneck"):
            head += f"- Bottleneck: {field['open_bottleneck']}\n"
        if field.get("good_transfer_target"):
            head += f"- Good transfer target: {field['good_transfer_target']}\n"
        if field.get("bad_target_avoided"):
            head += f"- Bad target avoided: {field['bad_target_avoided']}\n"
        if field.get("why_aligned"):
            head += f"- Why aligned: {field['why_aligned']}\n"

    sm = g.get("structural_mapping") or {}
    if sm:
        sev = sm.get("mismatch_severity", "?")
        status = sm.get("match_status", "?")
        sev_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sev, "⚪")
        head += f"\n**🔗 Structural mapping** ({status} · {sev_emoji} mismatch={sev}):\n"
        head += f"- AI: {sm.get('ai_data_structure', '?')}\n"
        head += f"- Fin: {sm.get('fin_data_structure', '?')}\n"
        if sm.get("bridge_required"):
            head += f"- Bridge: {sm['bridge_required']}\n"

    ctx = g.get("research_context") or {}
    if ctx:
        head += "\n**Research context**:\n"
        if ctx.get("fin_current_state"):
            head += f"- 🏦 *Fin 当前进展*: {ctx['fin_current_state']}\n"
        if ctx.get("ai_frontier"):
            head += f"- 🤖 *AI 前沿*: {ctx['ai_frontier']}\n"
        if ctx.get("why_this_matters"):
            head += f"- ⭐ *为什么这个 gap 值得做*: {ctx['why_this_matters']}\n"

    if gtype == "theoretical":
        ai = g.get("ai_anchor", {})
        fin = g.get("fin_anchor", {})
        head += f"\n**AI 锚点**: {ai.get('concept', '?')} (paper: {ai.get('paper_id', '?')})\n"
        head += f"\n**Fin 锚点**: {fin.get('description', '?')}\n"
        if full:
            chain = g.get("reasoning_chain", []) or []
            if chain:
                head += "\n**推理**:\n"
                for step in chain:
                    head += f"  - {step}\n"
            head += f"\n**Why open gap**: {g.get('why_open_gap', '?')}\n"
    else:   # engineering
        roadmap = g.get("experimental_roadmap", {}) or {}
        head += f"\n**Motivation**: {g.get('motivation', '?')}\n"
        if full:
            head += f"\n**Data**: {roadmap.get('data', '?')}\n"
            method = roadmap.get("method", []) or []
            if method:
                head += "\n**Method**:\n"
                for m in method:
                    head += f"  - {m}\n"
            metrics = roadmap.get("metrics", {}) or {}
            head += f"\n**Metrics**: primary={metrics.get('primary', [])}, secondary={metrics.get('secondary', [])}\n"
            compute = roadmap.get("compute_profile") or {}
            compute_summary = compute_profile_summary(compute)
            if compute_summary:
                head += f"\n**Compute**: {compute_summary}\n"
                if compute.get("summary"):
                    head += f"- summary: {compute['summary']}\n"
                if compute.get("fallback"):
                    head += f"- fallback: {compute['fallback']}\n"
            baselines = roadmap.get("baselines", []) or []
            if baselines:
                head += "\n**Baselines**:\n"
                for b in baselines:
                    head += f"  - {b.get('name', '?')} ({b.get('ref', '')})\n"
            ablations = roadmap.get("ablations", []) or []
            if ablations:
                head += "\n**Ablations**:\n"
                for a in ablations:
                    head += f"  - {a}\n"
            head += f"\n**Effort**: {roadmap.get('estimated_effort', '?')}\n"
            risks = roadmap.get("key_risks", []) or []
            if risks:
                head += "\n**Risks**:\n"
                for r in risks:
                    head += f"  - {r}\n"

    brief_path = item.get("_brief_path") or g.get("_brief_path")
    if brief_path:
        head += f"\n**📖 Deep brief**: [`{brief_path}`]({brief_path})\n"

    related = g.get("_related_papers") or {}
    if related.get("ai") or related.get("fin"):
        head += "\n**📚 Related work**:\n"
        if related.get("ai"):
            head += "\n*AI side*:\n"
            for paper in related["ai"]:
                t = (paper.get("title") or "?")[:100]
                extra = " · ".join(
                    x for x in [paper.get("affiliation"), paper.get("method")] if x
                )
                head += f"  - [[{paper.get('id', '?')}]({paper.get('url', '')})] {t}"
                if extra:
                    head += f"  _{extra}_"
                head += "\n"
        if related.get("fin"):
            head += "\n*Fin side*:\n"
            for paper in related["fin"]:
                t = (paper.get("title") or "?")[:100]
                extra = " · ".join(
                    x for x in [paper.get("affiliation"), paper.get("method")] if x
                )
                head += f"  - [[{paper.get('id', '?')}]({paper.get('url', '')})] {t}"
                if extra:
                    head += f"  _{extra}_"
                head += "\n"

    head += "\n> Decision: [ ] accept  [ ] reject  [ ] modify (edit above, save)\n"
    return head


def _section_mapping_actions(p: dict) -> str:
    actions = p.get("mapping_actions", [])
    if not actions:
        return "## Mapping Updates\n\n_No proposed actions today._"
    out = ["## Mapping Updates (require approval)\n"]
    for i, a in enumerate(actions, 1):
        out.append(f"\n### Action {i}: {a.get('type')}")
        for k, v in a.items():
            if k.startswith("_"):
                continue
            out.append(f"- **{k}**: {v}")
        out.append("\n> Decision: [ ] accept  [ ] reject  [ ] modify\n")
    return "\n".join(out)


def _section_mapping_drafts(p: dict) -> str:
    drafts = p.get("mapping_drafts", [])
    if not drafts:
        return "## Mapping Drafts\n\n_No mapping drafts today._"
    out = ["## Mapping Drafts (review before promotion)\n"]
    for draft in drafts:
        path = draft.get("_path", "")
        source = draft.get("source_gap_id", "?")
        status = draft.get("status", "?")
        out.append(f"\n### Draft: {source} · {status}")
        if path:
            out.append(f"- **file**: [`{path}`]({path})")
        out.append(f"- **hypothesis**: {draft.get('hypothesis', '')}")
        out.append(f"- **AI mechanism**: {draft.get('ai_mechanism', '')}")
        out.append(f"- **Fin structure**: {draft.get('fin_structure', '')}")
        out.append(f"- **Bridge**: {draft.get('bridge', '')}")
        out.append("\n> Decision: [ ] promote  [ ] reject  [ ] modify draft\n")
    return "\n".join(out)


def _section_review_instructions() -> str:
    return (
        "---\n\n"
        "## How to review\n\n"
        "1. For each gap, mapping draft, and mapping action, fill in `[x]` on the chosen decision\n"
        "2. For approved drafts, review `mappings/drafts/*.md`, edit frontmatter if needed, "
        "then promote by moving the file to `mappings/` and assigning a stable `id: Mxxxx`\n"
        "3. For approved `status_change` / `add_evidence`, edit the relevant `mappings/*.md`\n"
        "4. `git add . && git commit -m \"review YYYY-MM-DD\" && git push`\n"
        "5. Server will use updated official mappings as context for tomorrow's run; drafts are ignored until promoted\n"
    )
