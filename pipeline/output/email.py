"""Send daily email via Resend.

Email contains:
  1. Email-ready runnable experiments with structured experimental setup
  2. Today's anchor papers
  3. Optional trend maintenance output, only when explicitly generated

NOT a paper digest — full audit lives in inbox/YYYY-MM-DD.md.
"""
from __future__ import annotations

import base64
import logging
from datetime import date
from html import escape

import resend

from ..config import PROJECT_ROOT, load_settings


log = logging.getLogger(__name__)


def send_daily_email(d: date, payload: dict) -> None:
    s = load_settings()

    n_mech = len(payload.get("research_gaps", []))
    subject = f"[AlphaGap] {d.isoformat()} · {n_mech} mechanism gaps"
    attachments = _brief_attachments(payload)
    html = _render_html(d, payload)

    if s.dry_run:
        log.info("[DRY-RUN] Would send email: %s (%d brief attachments)",
                 subject, len(attachments))
        print("--- email preview (html truncated) ---")
        print(subject)
        print(html[:2000] + ("..." if len(html) > 2000 else ""))
        return

    resend.api_key = s.resend_api_key
    params = {
        "from": s.email_from,
        "to": s.email_to,
        "subject": subject,
        "html": html,
    }
    if attachments:
        params["attachments"] = attachments
    resp = resend.Emails.send(params)
    log.info("Email sent: id=%s (%d brief attachments)", resp.get("id"), len(attachments))


def _brief_attachments(payload: dict) -> list[dict]:
    """Load generated engineering briefs as email attachments, without exposing paths."""
    attachments = []
    briefs_root = (PROJECT_ROOT / "briefs").resolve()
    for item in payload.get("email_ready", []) or []:
        brief_path = item.get("_brief_path") or item.get("gap", {}).get("_brief_path")
        if not brief_path:
            continue
        path = (PROJECT_ROOT / str(brief_path)).resolve()
        if path.parent != briefs_root or not path.is_file():
            item["_brief_attached"] = False
            log.warning("Brief attachment unavailable: %s", brief_path)
            continue
        attachments.append({
            "filename": path.name,
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "content_type": "text/markdown; charset=utf-8",
        })
        item["_brief_attached"] = True
    # mechanism-gap briefs (agent×finance) — same briefs/ dir, tagged _brief_file on each gap
    for g in payload.get("research_gaps", []) or []:
        bf = g.get("_brief_file")
        if not bf:
            continue
        path = (PROJECT_ROOT / "briefs" / str(bf)).resolve()
        if path.parent != briefs_root or not path.is_file():
            log.warning("Mechanism brief attachment unavailable: %s", bf)
            continue
        attachments.append({
            "filename": path.name,
            "content": base64.b64encode(path.read_bytes()).decode("ascii"),
            "content_type": "text/markdown; charset=utf-8",
        })
    return attachments


def send_failure_alert(d: date, error: str) -> None:
    s = load_settings()
    subject = f"[AlphaGap] {d.isoformat()} · ❌ pipeline FAILED"
    html = f"<h2>AlphaGap pipeline failed on {d.isoformat()}</h2><pre>{error}</pre>"

    if s.dry_run:
        log.info("[DRY-RUN] Would send failure email")
        return

    resend.api_key = s.resend_api_key
    resend.Emails.send({
        "from": s.email_from,
        "to": s.email_to,
        "subject": subject,
        "html": html,
    })


def _render_html(d: date, p: dict) -> str:
    parts = [
        "<div style='font-family:-apple-system,BlinkMacSystemFont,sans-serif;max-width:720px;'>",
        f"<h1 style='margin-bottom:4px;'>AlphaGap — {d.isoformat()}</h1>",
        _stats_compact_html(p),
        _research_gaps_html(p),
        _trends_html(p) if _has_trend_content(p) else "",
        _papers_html(p),
        _mapping_actions_html(p),
        f"<p style='color:#888;font-size:12px;margin-top:24px;'>"
        f"Full audit: <code>inbox/{d.isoformat()}.md</code> · "
        f"<code>git pull</code> to review</p>",
        "</div>",
    ]
    return "\n".join(parts)


def _stats_compact_html(p: dict) -> str:
    s = p.get("stats", {})
    n_mech = len(p.get("research_gaps", []))
    meta = p.get("research_gap_meta") or {}
    n_mined = len(meta.get("mined_papers", []))
    return (
        f"<p style='color:#888;font-size:13px;margin-top:0;'>"
        f"{s.get('fetched','?')} papers · {s.get('l1_done','?')} extracted · "
        f"{n_mined} mined → <b style='color:#000;'>{n_mech} mechanism gaps</b> · "
        f"${s.get('cost_usd', 0):.4f}</p>"
    )


def _stats_html(p: dict) -> str:
    return _stats_compact_html(p)


def _papers_html(p: dict) -> str:
    papers = p.get("top_papers", [])[:5]
    if not papers:
        return ""
    rows = []
    for paper in papers:
        title = paper.get("title", "?")[:100]
        affil = paper.get("affiliation_top", "") or "—"
        url = paper.get("url") or f"https://arxiv.org/abs/{paper.get('id', '')}"
        rows.append(
            f"<li style='margin:4px 0;'><a href='{url}' style='color:#0066cc;text-decoration:none;'>"
            f"[{paper.get('id','?')}]</a> {title} "
            f"<span style='color:#888;font-size:12px;'>· {affil}</span></li>"
        )
    return (
        f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px;'>"
        f"📄 Top Papers (today)</h2>"
        f"<ul style='font-size:13px;padding-left:20px;'>{''.join(rows)}</ul>"
    )


def _trends_html(p: dict) -> str:
    wa = p.get("stats", {}).get("window_ai", 90)
    wf = p.get("stats", {}).get("window_fin", 180)
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px;'>"
           f"📈 Mechanism Trends (AI {wa}d · Fin {wf}d rolling)</h2>"]
    for side, label, emoji in [("ai", "AI", "🤖"), ("fin", "Fin", "🏦")]:
        trends = p.get(f"{side}_trends", {})
        any_content = False
        out.append(f"<p style='margin:12px 0 4px 0;'><b>{emoji} {label}</b></p>")
        for bucket, marker, bcolor in [
            ("rising", "↑ Rising", "#0a6e3d"),
            ("new_emergence", "★ New emergence", "#0066cc"),
            ("stable_hot", "→ Stable hot", "#888"),
            ("falling", "↓ Falling", "#c0392b"),
        ]:
            items = trends.get(bucket, []) or []
            if not items:
                continue
            any_content = True
            out.append(f"<p style='margin:8px 0 4px 0;font-size:13px;color:{bcolor};'><b>{marker}</b></p>")
            for it in items[:6]:
                name = it.get("name", "?")
                problem = it.get("what_problem", "")
                contrast = it.get("contrast_to_prior", "")
                members = it.get("member_papers", []) or []
                cv = it.get("citation_velocity_30d", 0)
                affs = it.get("representative_affiliations", []) or []
                growth = it.get("growth_pct", 0)
                out.append(
                    f"<div style='border-left:3px solid {bcolor};padding:6px 12px;margin:6px 0;background:#fafbfc;'>"
                    f"<p style='margin:2px 0;font-size:14px;'><b>{name}</b></p>"
                )
                if problem:
                    out.append(f"<p style='margin:2px 0;font-size:12px;color:#555;'><b>问题</b>: {problem}</p>")
                if contrast:
                    out.append(f"<p style='margin:2px 0;font-size:12px;color:#555;'><b>vs prior</b>: {contrast}</p>")
                stats_bits = []
                if members:
                    stats_bits.append(f"{len(members)} papers")
                if cv:
                    stats_bits.append(f"+{cv} cites/30d")
                if growth:
                    stats_bits.append(f"{growth:+.0f}%")
                if affs:
                    stats_bits.append(", ".join(affs[:3]))
                if stats_bits:
                    out.append(f"<p style='margin:2px 0;font-size:11px;color:#888;'>{' · '.join(stats_bits)}</p>")
                out.append("</div>")
        if not any_content:
            out.append(f"<p style='font-size:13px;color:#999;'><em>No data in window yet.</em></p>")
    return "\n".join(out)


def _has_trend_content(p: dict) -> bool:
    return any(
        (p.get(f"{side}_trends", {}) or {}).get(bucket)
        for side in ("ai", "fin")
        for bucket in ("rising", "new_emergence", "stable_hot", "falling")
    )


def _research_gaps_html(p: dict) -> str:
    """AI-agent × finance opportunities (mined from full-text agent papers) — AI is the protagonist:
    the contribution is an agent mechanism / reliability-audit / benchmark, finance is the hard scenario,
    NOT return prediction. Each entry carries the publishable-positive lens."""
    rgs = p.get("research_gaps", []) or []
    if not rgs:
        return ""
    mined = (p.get("research_gap_meta") or {}).get("mined_papers", [])
    src_color = {"mined": "#0a6e3d", "general": "#57606a", "gap": "#b3261e"}
    out = [f"<h2 style='border-bottom:2px solid #1f4e79;padding-bottom:4px;color:#1f4e79;'>"
           f"🤖 AI-Agent × Finance Opportunities ({len(rgs)}) "
           f"<span style='font-size:12px;color:#888;font-weight:normal;'>— mined from "
           f"{', '.join(mined) or 'agent papers'}; AI-paper angles (unvalidated)</span></h2>"]
    for g in rgs:
        out.append(_mechanism_gap_html(g, src_color))
    return "\n".join(out)


def _mechanism_score_line(g: dict) -> str:
    sc = g.get("scores", {}) or {}
    ms = g.get("mechanism_source", "?")
    src_color = {"mined": "#0a6e3d", "general": "#57606a", "gap": "#b3261e"}
    score_html = ""
    if sc:
        score_html = (f"<span style='float:right;font-size:13px;color:#444;'><b>{_e(sc.get('composite','?'))}</b> "
                      f"<span style='color:#888;'>(nov {_e(sc.get('novelty','?'))} · ai {_e(sc.get('ai_contribution','?'))} · "
                      f"pos {_e(sc.get('positive_attainability','?'))} · feas {_e(sc.get('feasibility','?'))} · "
                      f"pub {_e(sc.get('publishability','?'))})</span></span>")
    return (f"<div style='font-size:11px;color:#1f4e79;'><b>{_e(g.get('ai_contribution_type','?').upper())}</b>"
            f" · mechanism: <span style='color:{src_color.get(ms,'#888')};'>{_e(ms)}</span>{score_html}</div>")


def _mechanism_gap_html(g: dict, src_color: dict) -> str:
    """Render one mechanism gap. If it has a deep brief (top-N), use the SAME rich layout as the
    engineering gap (transfer header 🏦/🤖/🔗 + EXPERIMENTAL SETUP tables); else a compact card."""
    sc = g.get("scores", {}) or {}
    brief = g.get("_brief") or {}
    out = ["<div style='border:1px solid #cdd9e5;border-radius:8px;padding:12px 16px;margin:12px 0;background:#f8fbff;'>"]
    out.append(_mechanism_score_line(g))
    out.append(f"<h3 style='margin:6px 0 4px 0;font-size:16px;line-height:1.35;'>"
               f"{_e(brief.get('title') or g.get('subtask','?'))}</h3>")
    if sc.get("verdict_line"):
        out.append(f"<p style='margin:2px 0;font-size:12px;color:#9a6700;'>⚖ {_e(sc.get('verdict_line'))}</p>")

    if not brief:
        # compact card (no brief expanded for this one)
        out.append(f"<p style='margin:2px 0;font-size:12px;color:#888;'>金融为何更难: {_e(g.get('why_finance_makes_it_hard',''))}</p>")
        out.append(f"<p style='margin:2px 0;font-size:13px;'>🧩 <b>机制</b>: {_e(g.get('candidate_mechanism',''))}</p>")
        out.append(f"<p style='margin:2px 0;font-size:12px;color:#555;'>vs baseline: {_e(g.get('classical_baseline',''))} · prior: {_e(g.get('prior_work',''))[:140]}</p>")
        out.append(f"<p style='margin:2px 0;font-size:13px;color:#0a6e3d;'>✅ <b>正向结果(AI层面)</b>: {_e(g.get('positive_result_shape',''))}</p>")
        out.append(f"<p style='margin:2px 0;font-size:12px;color:#444;'>🆕 novelty: {_e(g.get('novelty_angle',''))}</p>")
        out.append(f"<p style='margin:2px 0;font-size:11px;color:#777;'>📄 {_e(g.get('publishability',''))} · {_e(g.get('feasibility',''))}</p>")
        out.append("</div>")
        return "\n".join(out)

    # RICH layout (mirrors engineering): transfer header + experimental setup
    tr = brief.get("transfer_rationale", {}) or {}
    fe = brief.get("first_experiment", {}) or {}
    de = brief.get("dataset_env", {}) or {}
    mt = brief.get("metrics", {}) or {}
    fz = brief.get("feasibility", {}) or {}
    # 🏦 Fin problem · 🤖 AI technique · 🔗 transfer rationale
    out.append(f"<p style='margin:8px 0 2px;font-size:13px;'>🏦 <b>Fin 问题</b> · {_e(g.get('why_finance_makes_it_hard',''))}</p>")
    out.append(f"<p style='margin:2px 0;font-size:13px;'>🤖 <b>AI 贡献</b> · {_e(brief.get('ai_contribution') or g.get('candidate_mechanism',''))}</p>")
    out.append(f"<p style='margin:2px 0;font-size:13px;'>🧩 <b>机制</b> · {_e(g.get('candidate_mechanism',''))}</p>")
    out.append("<div style='margin:6px 0;font-size:12px;color:#334155;'><b>🔗 迁移依据</b>"
               f"<br>· 结构对应 — {_e(tr.get('structural',''))}"
               f"<br>· 为什么成立 — {_e(tr.get('why_holds',''))}"
               f"<br>· 可信度 — {_e(tr.get('credibility',''))}</div>")
    out.append(f"<p style='margin:4px 0;font-size:12px;color:#444;'>🆕 <b>novelty</b> · {_e(brief.get('novelty_positioning') or g.get('novelty_angle',''))}</p>")
    out.append(f"<p style='margin:4px 0;font-size:13px;color:#0a6e3d;'>✅ <b>正向结果(AI层面)</b> · {_e(g.get('positive_result_shape',''))}</p>")
    if g.get("_brief_file"):
        out.append(f"<p style='margin:4px 0;font-size:12px;color:#1f4e79;'>📖 Deep brief: attached <code>{_e(g.get('_brief_file'))}</code></p>")
    # EXPERIMENTAL SETUP (reuse the engineering _design_table)
    out.append("<div style='margin:14px 0 6px;border-top:1px solid #e5e7eb;padding-top:12px;'>"
               "<p style='margin:0 0 8px;font-size:12px;font-weight:700;color:#475569;text-transform:uppercase;'>Experimental setup</p>")
    out.append(_design_table("00", "First Experiment", "The smallest go/no-go test to run now", [
        ("Question", fe.get("question") or "?"),
        ("Minimal setup", fe.get("minimal_setup") or "?"),
        ("Go", fe.get("go") or "?"),
        ("Stop / pivot", fe.get("stop_pivot") or "?"),
        ("Runtime", fe.get("runtime") or "?"),
    ]))
    out.append(_design_table("01", "Dataset / environment", "What is observed and how evaluation stays valid", [
        ("Sources", de.get("sources") or "?"),
        ("Sample / unit", de.get("unit") or "?"),
        ("Evaluation split", de.get("split") or "?"),
        ("Leakage controls", de.get("leakage_controls") or "?"),
    ]))
    metric_rows = [("Primary", m, "-") for m in (mt.get("primary") or [])] + \
                  [("Secondary", m, "-") for m in (mt.get("secondary") or [])]
    out.append(_design_table("02", "Metrics", "What determines success (AI-level, not Sharpe)",
                             metric_rows or [("-", "Not specified", "-")], headers=("Tier", "Measure", "Use")))
    ba_rows = [(b.get("class", "?"), b.get("comparator", "?"), b.get("purpose", "-"))
               for b in (brief.get("baselines_ablations") or []) if isinstance(b, dict)]
    out.append(_design_table("03", "Baselines & ablations", "What the mechanism must beat or justify",
                             ba_rows or [("-", "Not specified", "-")], headers=("Class", "Comparator / variant", "Purpose")))
    p0 = brief.get("phase0_preconditions") or []
    if p0:
        bits = "<br>".join(f"· [{_e(p.get('risk','?'))}] {_e(p.get('rule',''))}: {_e(p.get('must_be_true',''))} — $0 check: {_e(p.get('cheap_check',''))}"
                           for p in p0 if isinstance(p, dict))
        out.append(f"<div style='margin:8px 0;font-size:12px;color:#334155;'><b>🧪 Phase-0 前提体检(真门槛)</b><br>{bits}</div>")
    out.append(f"<p style='margin:6px 0;font-size:11px;color:#777;'>💰 {_e(fz.get('api_cost','?'))} · 🖥 {_e(fz.get('compute','?'))} · 📊 build: {_e(fz.get('data_build','?'))} · bottleneck: {_e(fz.get('main_bottleneck','?'))}</p>")
    out.append("</div></div>")
    return "\n".join(out)


def _gaps_html(p: dict) -> str:
    eg = p.get("email_ready", [])
    if not eg:
        # Defer the empty-state to _leads_html: if there are theoretical leads we
        # surface those instead of a bare "nothing today" message.
        if p.get("theoretical_leads"):
            return (
                "<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>"
                "Runnable Experiments</h2>"
                "<p style='color:#888;'><em>No engineering experiment cleared the "
                "go/no-go gate today — exploratory leads below.</em></p>"
            )
        return (
            "<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>"
            "Runnable Experiments</h2>"
            "<p><em>No engineering experiment cleared the go/no-go gate today. "
            "Discussion ideas remain in the inbox audit.</em></p>"
        )
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>"
           f"Runnable Experiments ({len(eg)})</h2>"]
    for item in eg:
        out.append(_gap_card_html(item))
    return "\n".join(out)


def _leads_html(p: dict) -> str:
    """O4 thin-day fallback: render accepted theoretical gaps as exploratory leads.

    Not runnable experiments — accepted hypotheses worth a human glance that may
    mature into an experiment or seed a new transfer cell. Reuses _gap_card_html
    (cards already render the theoretical type/score), so this is just a header + cards.
    """
    leads = p.get("theoretical_leads", []) or []
    if not leads:
        return ""
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px;'>"
           f"💡 Exploratory Leads ({len(leads)})</h2>"
           f"<p style='color:#888;font-size:13px;margin-top:0;'>Accepted theoretical "
           f"gaps — not yet a gated experiment. Worth a glance: a candidate to mature "
           f"into a runnable test or to seed a new transfer cell.</p>"]
    for item in leads:
        out.append(_gap_card_html(item))
    return "\n".join(out)


def _ai_anchor_link(g: dict, gtype: str) -> str:
    """Clickable AI anchor paper (the backing). Engineering uses anchor_papers.ai;
    theoretical uses ai_anchor."""
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
        return _e(title)
    if pid[:1].isdigit():
        url = f"https://arxiv.org/abs/{pid}"
    elif str(pid).startswith("openreview"):
        url = f"https://openreview.net/forum?id={str(pid).split(':')[-1]}"
    else:
        url = ""
    label = f"[{_e(pid)}]"
    link = (f"<a href='{url}' style='color:#2563eb;text-decoration:none;'>{label} ↗</a>"
            if url else label)
    return link + (f" {_e(title)}" if title else "")


def _feasibility_verdict(g: dict):
    """Crisp triage verdict in AI-EXECUTOR units — API$ + compute + does-the-data-exist
    (NOT person-time; the executor is an agent, wall-clock is minutes). Returns
    (emoji, color, text) or None when there's no roadmap (e.g. theoretical leads).
    Purely human-facing at-a-glance — never gates or scores."""
    rm = g.get("experimental_roadmap") or {}
    cp = rm.get("compute_profile") or {}
    native = cp.get("findata_native")
    tier = (cp.get("tier") or "").lower()
    api = cp.get("api_cost_usd")
    wall = cp.get("run_wallclock") or cp.get("estimated_runtime") or ""
    build = cp.get("data_build") or ""
    if native is None and not tier and api is None and not wall:
        return None
    big_api = isinstance(api, (int, float)) and api >= 200
    mid_api = isinstance(api, (int, float)) and api >= 20
    # heavy = needs a bespoke data/infra build, or high compute, or big API spend
    if native is False or tier in ("high", "very_high") or big_api:
        emoji, color = "🔴", "#c0392b"
    elif tier == "medium" or mid_api:
        emoji, color = "🟡", "#b07000"
    else:
        emoji, color = "🟢", "#0a6e3d"
    bits = []
    if api is not None:
        bits.append(f"💰 ~${_e(api)} API")
    if tier:
        bits.append(f"🖥 {_e(tier)}" + (f" · {_e(wall)}" if wall else ""))
    elif wall:
        bits.append(f"🖥 {_e(wall)}")
    if native is True:
        bits.append("📊 findata 原生")
    elif native is False:
        bits.append("📊 需先建数据: " + _e(build or "外部语料"))
    return emoji, color, " · ".join(bits) or "?"


def _transfer_header_html(g: dict, gtype: str) -> str:
    """The decision header: 🏦 Fin problem → 🤖 AI technique (+backing) → 🔗 transfer basis.
    Folds in field_boundary_alignment, research_context and structural_mapping so the
    human sees what problem / what new technique / why it transfers at a glance."""
    field = g.get("field_boundary_alignment") or {}
    ctx = g.get("research_context") or {}
    sm = g.get("structural_mapping") or {}
    method = g.get("method_primary")
    if isinstance(method, list):
        method = ", ".join(str(m) for m in method)
    sev = sm.get("mismatch_severity", "")
    sev_color = {"low": "#0a6e3d", "medium": "#b07000", "high": "#c0392b"}.get(sev, "#888")
    sev_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sev, "⚪")
    loc = " · ".join(x for x in [
        _e(field.get("field_id", "")), _e(field.get("mechanism_family", "")),
        (f"瓶颈={_e(field['open_bottleneck'])}" if field.get("open_bottleneck") else ""),
    ] if x)

    out = ["<div style='background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;"
           "padding:12px 16px;margin:10px 0;font-size:13px;line-height:1.55;'>"]
    # 1 — Fin problem first
    if ctx.get("fin_current_state"):
        out.append(f"<p style='margin:4px 0;'><b>🏦 Fin 问题</b> · {_e(ctx['fin_current_state'])}</p>")
    if loc:
        out.append(f"<p style='margin:2px 0 10px;color:#888;font-size:12px;'>{loc}</p>")
    # 2 — AI technique + backing
    tech = " — ".join(x for x in [_e(method) if method else "", _e(ctx.get("ai_frontier", ""))] if x)
    if tech:
        out.append(f"<p style='margin:4px 0;'><b>🤖 AI 技术</b> · {tech}</p>")
    evid, link = _e(ctx.get("anchor_evidence", "")), _ai_anchor_link(g, gtype)
    if evid or link:
        backing = " · ".join(x for x in [evid, link] if x)
        out.append(f"<p style='margin:2px 0 10px;color:#475569;font-size:12px;'><b>背书</b>: {backing}</p>")
    # 3 — transfer basis (expanded)
    out.append("<p style='margin:8px 0 2px;'><b>🔗 迁移依据</b></p>")
    if sm.get("ai_data_structure") or sm.get("fin_data_structure"):
        out.append(f"<p style='margin:2px 0;'>· <b>结构对应</b> — AI: {_e(sm.get('ai_data_structure', '?'))}"
                   f" ／ Fin: {_e(sm.get('fin_data_structure', '?'))}</p>")
    if sm.get("bridge_required"):
        out.append(f"<p style='margin:2px 0;'>· <b>桥接</b> — {_e(sm['bridge_required'])}</p>")
    if field.get("why_aligned"):
        out.append(f"<p style='margin:2px 0;'>· <b>为什么成立</b> — {_e(field['why_aligned'])}</p>")
    if sev:
        out.append(f"<p style='margin:2px 0;color:{sev_color};'>· <b>可信度</b> — "
                   f"{sev_emoji} {_e(sm.get('match_status', '?'))} · mismatch {_e(sev)}</p>")
    feas = _feasibility_verdict(g)
    if feas:
        emoji, color, text = feas
        out.append(f"<p style='margin:8px 0 2px;color:{color};'><b>🧪 可行性</b> — "
                   f"{emoji} {_e(text)}</p>")
    out.append("</div>")
    return "\n".join(out)


def _significance_color(sig) -> str:
    if sig is None:
        return "#888"
    if sig >= 7:
        return "#0a6e3d"   # green — matters
    if sig >= 5:
        return "#9a6700"   # amber — marginal
    return "#b3261e"        # red — likely clever-but-minor


def _significance_badge(s: dict) -> str:
    sig = s.get("significance")
    if sig is None:
        return "sig ?"
    return f"<b style='color:{_significance_color(sig)};'>sig {_e(sig)}</b>"


def _significance_line(s: dict) -> str:
    """🎯 the would-it-matter-if-confirmed axis + reason; flags 'sound but minor' gaps.
    Display-only decision-support — never gates or reorders past soundness."""
    sig = s.get("significance")
    if sig is None:
        return ""
    reason = _e(s.get("significance_reason", ""))
    flag = ("&nbsp;<span style='color:#b3261e;font-weight:600;'>⚠ 低重要性 · sound 但可能鸡肋</span>"
            if sig <= 5 else "")
    return (f"<p style='margin:4px 0 2px 0;font-size:12px;color:#555;'>"
            f"🎯 <b style='color:{_significance_color(sig)};'>significance {_e(sig)}/10</b>"
            f"{(' · ' + reason) if reason else ''}{flag}</p>")


def _gap_card_html(item: dict) -> str:
    g = item["gap"]
    s = item["score"]
    gid = _e(g.get("_id", "?"))
    gtype = item["type"]
    hyp = _e(g.get("hypothesis", "?"))
    type_color = "#0a6e3d" if gtype == "engineering" else "#5a3b8c"
    type_bg = "#e6f4ea" if gtype == "engineering" else "#ede7f6"
    mode = g.get("opportunity_mode")
    if mode == "frontier_extension":
        mode_label, mode_color, mode_bg = "FRONTIER EXTENSION", "#9a6700", "#fff8c5"
    elif mode == "grounded_transfer":
        mode_label, mode_color, mode_bg = "GROUNDED", "#57606a", "#f0f2f4"
    else:
        mode_label = mode_color = mode_bg = ""
    mode_badge = (
        f" <span style='color:{mode_color};background:{mode_bg};padding:2px 8px;"
        f"border-radius:3px;font-size:11px;'>{_e(mode_label)}</span>"
        if mode_label else ""
    )

    out = [
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px 18px;"
        f"margin:14px 0;background:#fff;'>",
        # Header bar
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;'>",
        f"<span style='font-size:13px;color:#888;'>[{gid}] "
        f"<span style='color:{type_color};background:{type_bg};padding:2px 8px;"
        f"border-radius:3px;font-size:11px;'>{_e(gtype.upper())}</span>"
        f"{mode_badge}</span>",
        f"<span style='font-size:13px;color:#444;'>"
        f"<b>{_e(s['total'])}</b> "
        f"<span style='color:#888;'>(nov {_e(s['novelty'])} · act {_e(s['actionability'])} · "
        f"theory {_e(s.get('theoretical_support', '?'))} · {_significance_badge(s)})</span></span>",
        f"</div>",
        # Hypothesis
        f"<h3 style='margin:8px 0 4px 0;font-size:16px;line-height:1.35;'>{hyp}</h3>",
        _significance_line(s),
    ]
    if s.get("email_gate"):
        out.append(
            f"<p style='margin:4px 0;font-size:12px;color:#777;'>"
            f"Gate: {_e(s.get('email_gate'))} · {_e(s.get('email_gate_reason', ''))}</p>"
        )

    # Decision header: Fin problem → AI technique (+backing) → transfer basis.
    out.append(_transfer_header_html(g, gtype))

    proposed = g.get("proposed_cell") or {}
    if mode == "frontier_extension" and proposed:
        out.append(
            "<div style='background:#fff8c5;border-left:3px solid #bf8700;"
            "padding:10px 14px;border-radius:4px;margin:10px 0;font-size:13px;'>"
            "<p style='margin:3px 0;'><b>Proposed new transfer cell</b> "
            "(human review required; not active)</p>"
            f"<p style='margin:3px 0;'><b>Failure mode</b>: {_e(proposed.get('new_failure_mode', '?'))}</p>"
            f"<p style='margin:3px 0;'><b>Intervention</b>: {_e(proposed.get('ai_intervention_class', '?'))}</p>"
            f"<p style='margin:3px 0;'><b>Experiment anchor</b>: {_e(proposed.get('experiment_anchor_sketch', '?'))}</p>"
            f"<p style='margin:3px 0;'><b>Why not existing cells</b>: {_e(proposed.get('why_existing_cells_insufficient', '?'))}</p>"
            "</div>"
        )

    # Why this matters (impact one-liner; structural mapping + research context are
    # folded into the transfer header above).
    why = (g.get("research_context") or {}).get("why_this_matters")
    if why:
        out.append(f"<p style='margin:8px 0;font-size:12px;color:#777;'><b>⭐ Why this matters</b> · {_e(why)}</p>")

    # Type-specific details
    if gtype == "engineering":
        roadmap = g.get("experimental_roadmap", {}) or {}
        out.append(_engineering_roadmap_html(roadmap))
    else:
        ai = g.get("ai_anchor", {})
        fin = g.get("fin_anchor", {})
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>AI anchor concept</b>: {_e(ai.get('concept','?'))}</p>")
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>Fin anchor</b>: {_e(fin.get('description','?')[:300])}</p>")

    # Deep brief delivery status; generated files are attached by send_daily_email.
    brief_path = item.get("_brief_path") or g.get("_brief_path")
    if brief_path:
        filename = str(brief_path).rsplit("/", 1)[-1]
        if item.get("_brief_attached"):
            delivery = f"Attached markdown: <code>{_e(filename)}</code>"
        else:
            delivery = f"Generated in run workspace: <code>{_e(brief_path)}</code>"
        out.append(
            f"<p style='margin:12px 0 8px 0;font-size:14px;'>"
            f"<b>📖 Deep brief</b>: {delivery}</p>"
        )

    # Related papers (the main addition)
    related = g.get("_related_papers", {})
    if related.get("ai") or related.get("fin"):
        out.append("<div style='margin-top:12px;padding-top:10px;border-top:1px dashed #ccc;'>")
        out.append("<p style='margin:4px 0;font-size:13px;color:#444;'><b>📚 Related work</b></p>")
        if related.get("ai"):
            out.append("<p style='margin:6px 0 2px 0;font-size:12px;color:#666;'>AI side</p><ul style='margin:2px 0;padding-left:20px;font-size:13px;'>")
            for paper in related["ai"]:
                out.append(_paper_li(paper))
            out.append("</ul>")
        if related.get("fin"):
            out.append("<p style='margin:6px 0 2px 0;font-size:12px;color:#666;'>Fin side</p><ul style='margin:2px 0;padding-left:20px;font-size:13px;'>")
            for paper in related["fin"]:
                out.append(_paper_li(paper))
            out.append("</ul>")
        out.append("</div>")

    out.append("</div>")
    return "\n".join(out)


def _engineering_roadmap_html(roadmap: dict) -> str:
    first = roadmap.get("first_experiment") or {}
    data = roadmap.get("data", "?")
    metrics = roadmap.get("metrics") or {}
    baselines = roadmap.get("baselines") or []
    ablations = roadmap.get("ablations") or []
    compute = roadmap.get("compute_profile") or {}
    risks = roadmap.get("key_risks") or []

    out = [
        "<div style='margin:16px 0 8px;border-top:1px solid #e5e7eb;padding-top:14px;'>",
        "<p style='margin:0 0 10px;font-size:12px;font-weight:700;color:#475569;"
        "text-transform:uppercase;'>Experimental setup</p>",
        _first_experiment_panel(first),
        _dataset_panel(data),
        _metrics_panel(metrics),
        _comparison_panel(baselines, ablations),
    ]
    out.append(_feasibility_strip(compute, risks))
    out.append("</div>")
    return "\n".join(out)


def _first_experiment_panel(first: dict) -> str:
    rows = [
        ("Question", first.get("question") or "?"),
        ("Minimal setup", first.get("minimal_setup") or "?"),
        ("Go", first.get("go_criterion") or "?"),
        ("Stop / pivot", first.get("stop_criterion") or "?"),
        ("Runtime", first.get("estimated_runtime") or "?"),
    ]
    return _design_table(
        "00",
        "First Experiment",
        "The smallest go/no-go test to run now",
        rows,
    )


def _dataset_panel(data: object) -> str:
    if isinstance(data, dict):
        sources = data.get("sources") or data.get("datasets") or "?"
        if isinstance(sources, list):
            sources = "; ".join(_item_text(x) for x in sources)
        rows = [
            ("Sources", sources),
            ("Sample / unit", data.get("sample") or data.get("universe") or data.get("unit_of_observation") or "?"),
            ("Period / frequency", data.get("period_frequency") or data.get("time_range") or data.get("frequency") or "?"),
            ("Evaluation split", data.get("split_protocol") or data.get("split") or "?"),
            ("Leakage controls", _inline_items(data.get("leakage_controls") or [])),
        ]
    else:
        rows = [("Dataset & protocol", data)]
    return _design_table("01", "Dataset", "What is observed and how evaluation remains valid", rows)


def _metrics_panel(metrics: dict) -> str:
    rows = []
    for tier, items in (("Primary", metrics.get("primary") or []),
                        ("Secondary", metrics.get("secondary") or [])):
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or item.get("metric") or "?"
                use = item.get("success_criterion") or item.get("purpose") or item.get("definition") or "-"
            else:
                name, use = item, "-"
            rows.append((tier, name, use))
    if not rows:
        rows = [("-", "Not specified", "-")]
    return _design_table(
        "02",
        "Metrics",
        "What determines success and what diagnoses trade-offs",
        rows,
        headers=("Tier", "Measure", "Decision use"),
    )


def _comparison_panel(baselines: list, ablations: list) -> str:
    rows: list[tuple[object, object, object, object]] = []
    for baseline in baselines:
        if isinstance(baseline, dict):
            category = baseline.get("type") or baseline.get("category") or "Baseline"
            name = baseline.get("name", "?")
            purpose = baseline.get("purpose") or baseline.get("role") or "Comparison baseline"
            citation = baseline.get("citation") or baseline.get("ref") or "-"
            evidence = _linked_citation(citation, baseline.get("url"))
        else:
            category, name, purpose, evidence = "Baseline", baseline, "Comparison baseline", "-"
        rows.append((category, name, purpose, evidence))
    for ablation in ablations:
        if isinstance(ablation, dict):
            name = ablation.get("name") or ablation.get("variant") or "?"
            purpose = ablation.get("tests_component") or ablation.get("purpose") or "Component contribution"
        else:
            name, purpose = ablation, "Component contribution"
        rows.append(("Ablation", name, purpose, "-"))
    if not rows:
        rows = [("-", "Not specified", "-", "-")]
    return _design_table(
        "03",
        "Baselines & Ablations",
        "What the proposed mechanism must beat or justify",
        rows,
        headers=("Class", "Comparator / variant", "Purpose", "Source"),
        html_columns={3},
    )


def _design_table(number: str, title: str, subtitle: str, rows: list[tuple],
                  *, headers: tuple[str, ...] = ("Item", "Design"),
                  html_columns: set[int] | None = None) -> str:
    html_columns = html_columns or set()
    header_cells = "".join(
        f"<th align='left' style='padding:7px 9px;border-bottom:1px solid #dbe2ea;"
        f"color:#64748b;font-size:11px;font-weight:700;text-transform:uppercase;'>{_e(header)}</th>"
        for header in headers
    )
    row_html = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            body = str(value) if index in html_columns else _e(value)
            cells.append(
                "<td valign='top' style='padding:8px 9px;border-bottom:1px solid #eef2f6;"
                f"font-size:13px;line-height:1.45;color:#27364b;'>{body}</td>"
            )
        row_html.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<div style='margin:10px 0;border:1px solid #dbe2ea;background:#fff;border-radius:6px;overflow:hidden;'>"
        "<div style='padding:10px 12px 8px;background:#f8fafc;border-bottom:1px solid #e2e8f0;'>"
        f"<span style='display:inline-block;color:#2563eb;font-size:11px;font-weight:700;margin-right:7px;'>{_e(number)}</span>"
        f"<b style='color:#1e293b;font-size:14px;'>{_e(title)}</b>"
        f"<p style='margin:3px 0 0;font-size:11px;color:#64748b;'>{_e(subtitle)}</p></div>"
        "<table role='presentation' cellpadding='0' cellspacing='0' width='100%' style='border-collapse:collapse;'>"
        f"<tr>{header_cells}</tr>{''.join(row_html)}</table></div>"
    )


def _linked_citation(citation: object, url: object) -> str:
    text = _e(citation)
    safe_url = str(url or "").strip()
    if safe_url.startswith("https://"):
        return (
            f"<a href='{_e(safe_url)}' style='color:#2563eb;text-decoration:none;'>"
            f"{text} ↗</a>"
        )
    return text


def _item_text(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("name") or item.get("dataset") or item.get("source") or "?")
    return str(item)


def _inline_items(items: object) -> str:
    if isinstance(items, list):
        return "; ".join(_item_text(item) for item in items) or "?"
    return str(items or "?")


def _feasibility_strip(compute: dict, risks: list) -> str:
    """Detailed cost line in AI-executor units (API$ + compute + data), not person-time."""
    requirements = compute.get("requirements") or []
    if isinstance(requirements, str):
        requirements = [requirements]
    resource = ", ".join(str(value) for value in requirements) or "?"
    risk_text = "; ".join(str(value) for value in list(risks)[:2]) or "?"
    api = compute.get("api_cost_usd")
    wall = compute.get("run_wallclock") or compute.get("estimated_runtime", "?")
    native = compute.get("findata_native")
    data = ("findata-native" if native is True
            else (f"needs build: {compute.get('data_build', 'external corpus')}" if native is False
                  else "?"))
    return (
        "<div style='margin:10px 0 0;padding:9px 12px;border-left:3px solid #94a3b8;"
        "background:#f8fafc;color:#475569;font-size:12px;line-height:1.55;'>"
        "<b style='color:#334155;'>Feasibility</b>"
        f" · 💰 ~${_e(api) if api is not None else '?'} API · 🖥 {_e(compute.get('tier', '?'))}"
        f" ({_e(resource)}) · {_e(wall)} · 📊 {_e(data)}"
        f"<br><b style='color:#334155;'>Watch-outs</b> · {_e(risk_text)}"
        "</div>"
    )


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _paper_li(paper: dict) -> str:
    title = (paper.get("title") or "?")[:120]
    url = paper.get("url", "")
    affil = paper.get("affiliation") or ""
    method = paper.get("method") or ""
    extra = " · ".join(x for x in [affil, method] if x)
    extra_html = f"<br><span style='color:#888;font-size:11px;'>{_e(extra)}</span>" if extra else ""
    return (
        f"<li><a href='{_e(url)}' style='color:#0066cc;text-decoration:none;'>"
        f"[{_e(paper.get('id','?'))}]</a> {_e(title)}{extra_html}</li>"
    )


def _mapping_actions_html(p: dict) -> str:
    actions = p.get("mapping_actions", [])
    if not actions:
        return ""
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px;'>"
           f"🗺 Mapping Actions ({len(actions)} pending)</h2>"
           f"<ul style='font-size:13px;padding-left:20px;'>"]
    for a in actions[:8]:
        atype = a.get("type", "?")
        reason = a.get("reason", "")
        if atype == "status_change":
            desc = f"{a.get('mapping_id')}: {a.get('from_status')} → {a.get('to_status')}"
        elif atype == "add_mapping":
            desc = f"NEW: {a.get('ai_concept')} ↔ {a.get('fin_concept')}"
        elif atype == "add_evidence":
            desc = f"+evidence on {a.get('mapping_id')}: {len(a.get('paper_ids',[]))} papers"
        else:
            desc = atype
        out.append(f"<li><b>{atype}</b>: {desc}<br><small>{reason}</small></li>")
    out.append("</ul>")
    return "\n".join(out)
