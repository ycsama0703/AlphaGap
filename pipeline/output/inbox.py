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
        _section_risk_audit(payload),
        _section_research_gaps(payload),
        _section_gaps_email(payload),
        _section_leads(payload),
        _section_suppressed_duplicates(payload),
        _section_gaps_all(payload),
        _section_self_check_ledger(payload),
        _section_trends(payload),
        _section_top_papers(payload),
        _section_mapping_drafts(payload),
        _section_mapping_actions(payload),
        _section_review_instructions(),
    ]
    path.write_text("\n\n".join(p for p in parts if p), encoding="utf-8")
    log.info("Inbox written to %s", path)
    return path


def _section_research_gaps(p: dict) -> str:
    """AI-agent × finance opportunities (full-text mined from agent papers) — AI-paper angles where the
    contribution is an agent mechanism / reliability-audit / benchmark, finance is the hard scenario.
    Unvalidated candidates: novelty/feasibility still to be checked, none tested."""
    rgs = p.get("research_gaps", []) or []
    meta = p.get("research_gap_meta") or {}
    if not rgs and not meta.get("mined_papers"):
        return ""
    lines = [f"\n## 🤖 AI-Agent × Finance Opportunities ({len(rgs)})",
             f"_Mined from full text: {', '.join(meta.get('mined_papers', [])) or '—'}"
             f"{('; skipped ' + str(len(meta.get('skipped', [])))) if meta.get('skipped') else ''}. "
             f"AI is the protagonist (mechanism/reliability/benchmark), finance is the scenario — NOT return "
             f"prediction. UNVALIDATED candidates: novelty + feasibility still to check; none tested._"]
    for g in rgs:
        sc = g.get("scores", {}) or {}
        lines.append(f"\n### [{g.get('ai_contribution_type','?')}] {g.get('subtask','?')}  ·  mechanism: {g.get('mechanism_source','?')}")
        if sc:
            lines.append(f"- **scores**: composite **{sc.get('composite','?')}** (nov {sc.get('novelty','?')} · "
                         f"ai_contribution {sc.get('ai_contribution','?')} · positive {sc.get('positive_attainability','?')} · "
                         f"feasibility {sc.get('feasibility','?')} · publishability {sc.get('publishability','?')}) — "
                         f"_{sc.get('verdict_line','')}_")
        if g.get("_brief_file"):
            lines.append(f"- **📖 deep brief**: attached `{g.get('_brief_file')}`")
        lines.append(f"- **why finance makes it hard**: {g.get('why_finance_makes_it_hard','')}")
        lines.append(f"- **mechanism**: {g.get('candidate_mechanism','')}")
        lines.append(f"- **vs baseline**: {g.get('classical_baseline','')}")
        lines.append(f"- **prior work**: {g.get('prior_work','')}")
        lines.append(f"- **why AI wins**: {g.get('why_ai_wins','')}")
        lines.append(f"- **✅ positive result (AI-level)**: {g.get('positive_result_shape','')}")
        lines.append(f"- **novelty**: {g.get('novelty_angle','')}")
        lines.append(f"- **findata env**: {g.get('findata_env','')}")
        lines.append(f"- **publishability / feasibility**: {g.get('publishability','')} · {g.get('feasibility','')}")
    return "\n".join(lines)


def _section_stats(p: dict) -> str:
    s = p.get("stats", {})
    selected = s.get("fin_fields_selected") or []
    available = s.get("fin_fields_available") or []
    suppressed = p.get("duplicates_suppressed") or []
    audit = p.get("risk_audit") or {}
    audit_line = (
        f"\n- Adversarial research audit: **on** | retained "
        f"{audit.get('retained', 0)}/{audit.get('input_candidates', 0)} | "
        f"revised {audit.get('revised', 0)} | rejected {audit.get('rejected', 0)}"
        if audit.get("enabled")
        else "\n- Adversarial research audit: **off**"
    )
    field_line = ""
    if selected:
        field_line = (
            f"\n- Fin field boundaries selected: **{', '.join(selected)}**"
            f" ({len(selected)}/{len(available) or len(selected)})"
        )
    suppressed_line = (
        f"- Near-duplicate gaps suppressed for diversity (D1): {len(suppressed)}\n"
        if suppressed else ""
    )
    return (
        f"## Pipeline\n\n"
        f"- Papers fetched: **{s.get('fetched', '?')}** | candidates: **{s.get('candidates', '?')}**\n"
        f"- L1 extracted: {s.get('l1_done', '?')} | L2 extracted: {s.get('l2_done', '?')}\n"
        f"- Hypotheses screened: {len(p.get('theoretical', []))} | Experiments designed: {len(p.get('engineering', []))}\n"
        f"- Accepted for record: {len(p.get('accepted', []))} | Runnable experiments emailed: {len(p.get('email_ready', []))}\n"
        f"- Historical AI mechanisms retrieved: {s.get('historical_ai_mechanisms', 0)}\n"
        f"{suppressed_line}"
        f"- Daily mode: experiment-first; citation/trend/mapping maintenance off critical path\n"
        f"{field_line}\n"
        f"{audit_line}\n"
        f"- LLM cost: ${s.get('cost_usd', 0):.4f}"
    )


def _section_risk_audit(p: dict) -> str:
    audit = p.get("risk_audit") or {}
    if not audit.get("enabled"):
        return ""
    lines = ["## Adversarial Research Audit (full ledger)"]
    if audit.get("fallback"):
        lines.append(
            f"\n_Audit failed open; standard mode used for this run: "
            f"{audit.get('fallback_reason', '?')}_"
        )

    decisions = audit.get("decisions", [])
    if not decisions:
        lines.append("\n_No candidate decisions returned._")
        return "\n".join(lines)

    for decision in decisions:
        idx = decision.get("candidate_idx", "?")
        verdict = decision.get("verdict", "?").upper()
        candidate = decision.get("one_liner", "?")
        lines.append(f"\n### Candidate {idx} — {verdict}\n")
        lines.append(f"- Proposal: {candidate}")
        failure_classes = decision.get("failure_classes") or []
        if failure_classes:
            lines.append(f"- Risk classes: {', '.join(failure_classes)}")
        lines.append(f"- Objection: {decision.get('strongest_objection', '?')}")
        if decision.get("required_revision"):
            lines.append(f"- Required revision: {decision['required_revision']}")
        if decision.get("revised_one_liner"):
            lines.append(f"- Revised proposal: {decision['revised_one_liner']}")
        lines.append(f"- Downstream outcome: {_audit_outcome(p, idx)}")
    return "\n".join(lines)


def _audit_outcome(p: dict, candidate_idx: object) -> str:
    statuses: list[str] = []
    email_ids = {
        item.get("gap", {}).get("_id") for item in p.get("email_ready", [])
    }
    for state, items in [
        ("accepted", p.get("accepted", [])),
        ("rejected", p.get("rejected", [])),
        ("downgraded", p.get("downgraded", [])),
    ]:
        for item in items:
            gap = item.get("gap") or {}
            origin = gap.get("_origin") or {}
            if origin.get("candidate_idx") != candidate_idx:
                continue
            gid = gap.get("_id", "?")
            suffix = " / email-ready" if gid in email_ids else ""
            statuses.append(f"{gid}: {state}{suffix}")
    if statuses:
        return "; ".join(statuses)
    return "not expanded or not selected for refinement"


def _section_self_check_ledger(p: dict) -> str:
    """Explain why generated gaps failed before scoring/email."""
    rows: list[str] = []
    for state, items in [
        ("rejected", p.get("rejected", [])),
        ("downgraded", p.get("downgraded", [])),
    ]:
        for item in items:
            rows.append(_self_check_item_markdown(state, item))
    if not rows:
        return ""
    return "\n".join([
        "## Rejected / Downgraded Self-check Ledger",
        "",
        "These items were generated but did not enter the accepted scoring pool. "
        "Use this section to diagnose whether Prompt 04/05 is underspecified or "
        "Prompt 06 is too strict.",
        "",
        *rows,
    ])


def _self_check_item_markdown(state: str, item: dict) -> str:
    gap = item.get("gap") or {}
    check = item.get("check") or {}
    lines = [
        f"### {_gap_label(gap, item.get('type'))} — {state}",
        "",
        f"- Hypothesis: {gap.get('hypothesis', '?')}",
        f"- Verdict: `{check.get('overall_verdict', 'unknown')}` — {check.get('verdict_summary', '')}",
    ]
    if item.get("score_error"):
        lines.append(f"- Scoring error: {item['score_error']}")
    if item.get("error"):
        lines.append(f"- Error: {item['error']}")
    origin = gap.get("_origin") or {}
    if origin.get("candidate_idx") is not None:
        lines.append(
            f"- Origin: candidate {origin.get('candidate_idx')} "
            f"({origin.get('audit_verdict') or 'standard'})"
        )
    failed = _failed_checks(check)
    if failed:
        lines.extend(["", "| Failed check | Reason |", "|---|---|"])
        for name, reason in failed:
            lines.append(f"| `{name}` | {_table_text(reason)} |")
    else:
        lines.append("- Failed checks: none reported")

    recheck = item.get("recheck")
    if recheck:
        lines.append("")
        lines.append(
            f"- Downgrade recheck: `{recheck.get('overall_verdict', 'unknown')}` "
            f"— {recheck.get('verdict_summary', '')}"
        )
        failed_recheck = _failed_checks(recheck)
        if failed_recheck:
            lines.extend(["", "| Recheck failed check | Reason |", "|---|---|"])
            for name, reason in failed_recheck:
                lines.append(f"| `{name}` | {_table_text(reason)} |")
    return "\n".join(lines)


def _gap_label(gap: dict, gap_type: str | None) -> str:
    gid = gap.get("_id", "?")
    return f"[{gid}] ({gap_type or gap.get('_type') or '?'})"


def _failed_checks(check: dict) -> list[tuple[str, str]]:
    checks = check.get("checks") if isinstance(check, dict) else {}
    if not isinstance(checks, dict):
        return []
    failed = []
    for name, result in checks.items():
        if not isinstance(result, dict):
            continue
        if result.get("pass") is False:
            failed.append((name, result.get("reason") or "failed"))
    return failed


def _table_text(value: object) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ").strip()


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
    if not any(
        (p.get(f"{side}_trends", {}) or {}).get(bucket)
        for side in ("ai", "fin")
        for bucket in ("rising", "new_emergence", "stable_hot", "falling")
    ):
        return ""
    out = [f"## Optional Mechanism Trends (AI {wa}d · Fin {wf}d rolling)"]
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
        return "## Runnable Experiments (emailed)\n\n_None cleared the go/no-go gate today._"
    out = ["## Runnable Experiments (emailed)"]
    for item in eg:
        out.append(_render_gap_detail(item, full=True))
    return "\n".join(out)


def _section_leads(p: dict) -> str:
    """O4: exploratory leads — accepted theoretical gaps surfaced on thin days."""
    leads = p.get("theoretical_leads", []) or []
    if not leads:
        return ""
    out = ["## Exploratory Leads (theoretical)",
           "_Accepted theoretical gaps — not a gated experiment. Candidates to mature "
           "into a runnable test or to seed a new transfer cell._"]
    for item in leads:
        out.append(_render_gap_detail(item, full=True))
    return "\n".join(out)


def _lead_ids(p: dict) -> set:
    return {
        (it["gap"].get("_id"))
        for it in (p.get("theoretical_leads", []) or [])
    }


def _section_suppressed_duplicates(p: dict) -> str:
    suppressed = p.get("duplicates_suppressed") or []
    if not suppressed:
        return ""
    lines = ["## Diversity-Suppressed Near-Duplicates",
             "_Runnable gaps collapsed because they share a Fin mechanism boundary "
             "and an overlapping hypothesis (D1); the higher-scored one was kept._"]
    for item in suppressed:
        gap = item.get("gap") or {}
        gid = gap.get("_id", "?")
        covered_by = item.get("_diversity_suppressed_by") or item.get("_email_suppressed_by", "?")
        reason = item.get("_diversity_suppressed_reason", "")
        hypothesis = gap.get("hypothesis", "?")
        suffix = f"  _({reason})_" if reason else ""
        lines.append(f"- `{gid}` folded into `{covered_by}`: {hypothesis}{suffix}")
    return "\n".join(lines)


def _section_gaps_all(p: dict) -> str:
    accepted = p.get("accepted", [])
    lead_ids = _lead_ids(p)  # O4: avoid double-listing leads already shown above
    below = [a for a in accepted
             if not a["score"]["passes_email_threshold"]
             and a["gap"].get("_id") not in lead_ids]
    if not below:
        return ""
    out = ["## Discussion Queue (not emailed)"]
    for item in below:
        out.append(_render_gap_detail(item, full=False))
    return "\n".join(out)


def _ai_anchor_link_md(g: dict, gtype: str) -> str:
    pid = title = ""
    if gtype == "engineering":
        ais = (g.get("anchor_papers") or {}).get("ai") or []
        if ais:
            pid = ais[0].get("id") or ais[0].get("paper_id") or ""
            title = ais[0].get("title") or ""
    else:
        aa = g.get("ai_anchor") or {}
        pid = aa.get("paper_id") or aa.get("id") or ""
        title = aa.get("concept") or aa.get("title") or ""
    if not pid:
        return title
    if str(pid)[:1].isdigit():
        url = f"https://arxiv.org/abs/{pid}"
    elif str(pid).startswith("openreview"):
        url = f"https://openreview.net/forum?id={str(pid).split(':')[-1]}"
    else:
        url = ""
    return (f"[`{pid}`]({url})" if url else f"`{pid}`") + (f" {title}" if title else "")


def _feasibility_verdict_md(g: dict) -> str:
    """Crisp triage verdict in AI-executor units — API$ + compute + data-exists
    (not person-time). Empty when no roadmap."""
    rm = g.get("experimental_roadmap") or {}
    cp = rm.get("compute_profile") or {}
    native = cp.get("findata_native")
    tier = (cp.get("tier") or "").lower()
    api = cp.get("api_cost_usd")
    wall = cp.get("run_wallclock") or cp.get("estimated_runtime") or ""
    build = cp.get("data_build") or ""
    if native is None and not tier and api is None and not wall:
        return ""
    big_api = isinstance(api, (int, float)) and api >= 200
    mid_api = isinstance(api, (int, float)) and api >= 20
    emoji = "🔴" if (native is False or tier in ("high", "very_high") or big_api) else (
        "🟡" if (tier == "medium" or mid_api) else "🟢")
    bits = []
    if api is not None:
        bits.append(f"💰 ~${api} API")
    if tier:
        bits.append(f"🖥 {tier}" + (f" · {wall}" if wall else ""))
    elif wall:
        bits.append(f"🖥 {wall}")
    if native is True:
        bits.append("📊 findata 原生")
    elif native is False:
        bits.append("📊 需先建数据: " + (build or "外部语料"))
    return f"{emoji} {' · '.join(bits) or '?'}"


def _transfer_header_md(g: dict, gtype: str) -> str:
    """Decision header (markdown): 🏦 Fin problem → 🤖 AI technique (+backing) → 🔗 transfer basis."""
    field = g.get("field_boundary_alignment") or {}
    ctx = g.get("research_context") or {}
    sm = g.get("structural_mapping") or {}
    method = g.get("method_primary")
    if isinstance(method, list):
        method = ", ".join(str(m) for m in method)
    sev = sm.get("mismatch_severity", "")
    sev_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sev, "⚪")
    loc = " · ".join(x for x in [field.get("field_id", ""), field.get("mechanism_family", ""),
                                 (f"瓶颈={field['open_bottleneck']}" if field.get("open_bottleneck") else "")] if x)
    out = []
    if ctx.get("fin_current_state"):
        out.append(f"\n**🏦 Fin 问题** · {ctx['fin_current_state']}")
    if loc:
        out.append(f"  \n_{loc}_")
    tech = " — ".join(x for x in [method or "", ctx.get("ai_frontier", "")] if x)
    if tech:
        out.append(f"\n\n**🤖 AI 技术** · {tech}")
    backing = " · ".join(x for x in [ctx.get("anchor_evidence", ""), _ai_anchor_link_md(g, gtype)] if x)
    if backing:
        out.append(f"  \n**背书**: {backing}")
    out.append("\n\n**🔗 迁移依据**")
    if sm.get("ai_data_structure") or sm.get("fin_data_structure"):
        out.append(f"- 结构对应 — AI: {sm.get('ai_data_structure', '?')} ／ Fin: {sm.get('fin_data_structure', '?')}")
    if sm.get("bridge_required"):
        out.append(f"- 桥接 — {sm['bridge_required']}")
    if field.get("why_aligned"):
        out.append(f"- 为什么成立 — {field['why_aligned']}")
    if sev:
        out.append(f"- 可信度 — {sev_emoji} {sm.get('match_status', '?')} · mismatch {sev}")
    feas = _feasibility_verdict_md(g)
    if feas:
        out.append(f"- 🧪 可行性 — {feas}")
    return "\n".join(out) + "\n"


def _render_gap_detail(item: dict, *, full: bool) -> str:
    g = item["gap"]
    s = item["score"]
    gid = g.get("_id", "?")
    gtype = item["type"]
    hypothesis = g.get("hypothesis", "?")

    sig = s.get("significance")
    sig_flag = " ⚠低重要性" if isinstance(sig, (int, float)) and sig <= 5 else ""
    head = (
        f"\n### [{gid}] ({gtype}) total={s['total']} · "
        f"novelty={s['novelty']} · actionability={s['actionability']} · "
        f"theory={s.get('theoretical_support', '?')} · 🎯significance={sig if sig is not None else '?'}{sig_flag}\n\n"
        f"**假设**: {hypothesis}\n"
    )
    # Decision header: Fin problem → AI technique (+backing) → transfer basis.
    head += _transfer_header_md(g, gtype)
    mode = g.get("opportunity_mode")
    if mode == "frontier_extension":
        head += "- opportunity_mode: `frontier_extension` — proposed new cell; human review required\n"
    elif mode == "grounded_transfer":
        head += "- opportunity_mode: `grounded_transfer` — anchored to an active cell\n"
    head += f"- novelty: {s.get('novelty_reason', '')}\n"
    head += f"- actionability: {s.get('actionability_reason', '')}\n"
    head += f"- theoretical_support: {s.get('theoretical_support_reason', '')}\n"
    head += f"- 🎯 significance: {s.get('significance_reason', '')}\n"
    components = s.get("theoretical_support_components") or {}
    if components:
        comp_text = ", ".join(f"{k}={v}" for k, v in components.items())
        head += f"- theoretical_support_components: {comp_text}\n"
    if s.get("email_gate"):
        head += f"- email_gate: {s.get('email_gate')} — {s.get('email_gate_reason', '')}\n"
    origin = g.get("_origin") or {}
    if origin.get("audit_verdict"):
        head += (
            f"- origin: candidate {origin.get('candidate_idx', '?')} "
            f"({origin['audit_verdict']})"
        )
        if origin.get("original_one_liner"):
            head += f" revised from: {origin['original_one_liner']}"
        head += "\n"

    # field_id / mechanism / bottleneck / why_aligned are in the transfer header;
    # keep only the audit-specific good/bad transfer targets here.
    field = g.get("field_boundary_alignment") or {}
    if field.get("good_transfer_target") or field.get("bad_target_avoided"):
        head += "\n**Transfer targeting**:\n"
        if field.get("good_transfer_target"):
            head += f"- ✅ Good transfer target: {field['good_transfer_target']}\n"
        if field.get("bad_target_avoided"):
            head += f"- 🚫 Bad target avoided: {field['bad_target_avoided']}\n"
    proposed = g.get("proposed_cell") or {}
    if g.get("opportunity_mode") == "frontier_extension" and proposed:
        head += "\n**Proposed new transfer cell (not active)**:\n"
        if proposed.get("new_failure_mode"):
            head += f"- New failure mode: {proposed['new_failure_mode']}\n"
        if proposed.get("ai_intervention_class"):
            head += f"- Intervention: {proposed['ai_intervention_class']}\n"
        if proposed.get("experiment_anchor_sketch"):
            head += f"- Experiment anchor sketch: {proposed['experiment_anchor_sketch']}\n"
        if proposed.get("why_existing_cells_insufficient"):
            head += f"- Why existing cells are insufficient: {proposed['why_existing_cells_insufficient']}\n"

    # Structural mapping + research context (Fin/AI) are folded into the transfer
    # header above; keep only the impact one-liner here.
    why = (g.get("research_context") or {}).get("why_this_matters")
    if why:
        head += f"\n**⭐ 为什么值得做**: {why}\n"

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
            head += _roadmap_tables_markdown(roadmap)
            method = roadmap.get("method", []) or []
            if method:
                head += "\n**Method**:\n"
                for m in method:
                    head += f"  - {m}\n"
            compute = roadmap.get("compute_profile") or {}
            compute_summary = compute_profile_summary(compute)
            if compute_summary:
                head += f"\n**Cost (AI-executor: API$ · compute · data)**: {compute_summary}\n"
                if compute.get("fallback"):
                    head += f"- fallback: {compute['fallback']}\n"
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


def _roadmap_tables_markdown(roadmap: dict) -> str:
    first = roadmap.get("first_experiment") or {}
    out = "\n**First Experiment (go/no-go)**:\n\n| Item | Design |\n|---|---|\n"
    for label, value in [
        ("Question", first.get("question") or "?"),
        ("Minimal setup", first.get("minimal_setup") or "?"),
        ("Go", first.get("go_criterion") or "?"),
        ("Stop / pivot", first.get("stop_criterion") or "?"),
        ("Runtime", first.get("estimated_runtime") or "?"),
    ]:
        out += f"| {label} | {value} |\n"
    data = roadmap.get("data", "?")
    out += "\n**Dataset**:\n\n| Item | Design |\n|---|---|\n"
    if isinstance(data, dict):
        sources = data.get("sources") or data.get("datasets") or "?"
        if isinstance(sources, list):
            sources = "; ".join(_markdown_item_text(item) for item in sources)
        data_rows = [
            ("Sources", sources),
            ("Sample / unit", data.get("sample") or data.get("universe") or data.get("unit_of_observation") or "?"),
            ("Period / frequency", data.get("period_frequency") or data.get("time_range") or data.get("frequency") or "?"),
            ("Evaluation split", data.get("split_protocol") or data.get("split") or "?"),
            ("Leakage controls", _markdown_inline_items(data.get("leakage_controls") or [])),
        ]
    else:
        data_rows = [("Dataset & protocol", data)]
    for label, value in data_rows:
        out += f"| {label} | {value} |\n"

    metrics = roadmap.get("metrics", {}) or {}
    out += "\n**Metrics**:\n\n| Tier | Measure | Decision use |\n|---|---|---|\n"
    metric_rows = []
    for tier, items in (("Primary", metrics.get("primary") or []),
                        ("Secondary", metrics.get("secondary") or [])):
        for item in items:
            if isinstance(item, dict):
                metric_rows.append((
                    tier,
                    item.get("name") or item.get("metric") or "?",
                    item.get("success_criterion") or item.get("purpose") or item.get("definition") or "-",
                ))
            else:
                metric_rows.append((tier, item, "-"))
    for tier, name, purpose in metric_rows or [("-", "Not specified", "-")]:
        out += f"| {tier} | {name} | {purpose} |\n"

    out += "\n**Baselines & Ablations**:\n\n| Class | Comparator / variant | Purpose | Source |\n|---|---|---|---|\n"
    comparison_rows = []
    for baseline in roadmap.get("baselines", []) or []:
        if isinstance(baseline, dict):
            citation = baseline.get("citation") or baseline.get("ref") or "-"
            url = str(baseline.get("url") or "")
            source = f"[{citation}]({url})" if url.startswith("https://") else citation
            comparison_rows.append((
                baseline.get("type") or baseline.get("category") or "Baseline",
                baseline.get("name", "?"),
                baseline.get("purpose") or baseline.get("role") or "Comparison baseline",
                source,
            ))
        else:
            comparison_rows.append(("Baseline", baseline, "Comparison baseline", "-"))
    for ablation in roadmap.get("ablations", []) or []:
        if isinstance(ablation, dict):
            comparison_rows.append((
                "Ablation",
                ablation.get("name") or ablation.get("variant") or "?",
                ablation.get("tests_component") or ablation.get("purpose") or "Component contribution",
                "-",
            ))
        else:
            comparison_rows.append(("Ablation", ablation, "Component contribution", "-"))
    for values in comparison_rows or [("-", "Not specified", "-", "-")]:
        out += f"| {' | '.join(str(value) for value in values)} |\n"
    return out


def _markdown_item_text(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("dataset") or item.get("source") or "?")
    return str(item)


def _markdown_inline_items(items: object) -> str:
    if isinstance(items, list):
        return "; ".join(_markdown_item_text(item) for item in items) or "?"
    return str(items or "?")


def _section_mapping_actions(p: dict) -> str:
    actions = p.get("mapping_actions", [])
    if not actions:
        return ""
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
        return ""
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
        "1. Review runnable experiments first; approve one only when its first go/no-go test is worth running.\n"
        "2. Review discussion items only when they expose a plausible new control point; they do not alter mappings automatically.\n"
        "3. After an experiment is selected or validated, update the official mapping manually in a separate review step.\n"
        "4. `git add . && git commit -m \"review YYYY-MM-DD\" && git push`\n"
    )
