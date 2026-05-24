"""Send daily email via Resend.

Email contains:
  1. 今日重点论文 top 5-10（高价值作者/机构）
  2. AI 方向 trends（14 天滚动）
  3. Fin 方向 trends
  4. Email-ready gaps — engineering uses total gate; theoretical uses high-novelty gate

NOT a paper digest — full audit lives in inbox/YYYY-MM-DD.md.
"""
from __future__ import annotations

import logging
from datetime import date
from html import escape

import resend

from ..config import load_settings


log = logging.getLogger(__name__)


def send_daily_email(d: date, payload: dict) -> None:
    s = load_settings()

    subject = (
        f"[AlphaGap] {d.isoformat()} · "
        f"{len(payload.get('email_ready', []))} gaps · "
        f"{len(payload.get('mapping_actions', []))} mapping actions"
    )
    html = _render_html(d, payload)

    if s.dry_run:
        log.info("[DRY-RUN] Would send email: %s", subject)
        print("--- email preview (html truncated) ---")
        print(subject)
        print(html[:2000] + ("..." if len(html) > 2000 else ""))
        return

    resend.api_key = s.resend_api_key
    resp = resend.Emails.send({
        "from": s.email_from,
        "to": s.email_to,
        "subject": subject,
        "html": html,
    })
    log.info("Email sent: id=%s", resp.get("id"))


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
        _gaps_html(p),                # ⭐ moved to top
        _trends_html(p),
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
    duplicate_count = len(p.get("duplicates_suppressed", []))
    duplicate_text = (
        f" · {duplicate_count} theory duplicates folded"
        if duplicate_count else ""
    )
    audit = p.get("risk_audit") or {}
    audit_text = (
        f" · adversarial audit on ({audit.get('rejected', 0)} rejected)"
        if audit.get("enabled") else ""
    )
    return (
        f"<p style='color:#888;font-size:13px;margin-top:0;'>"
        f"{s.get('fetched','?')} papers · {s.get('l1_done','?')} extracted · "
        f"{len(p.get('theoretical',[]))} theoretical + {len(p.get('engineering',[]))} engineering gaps · "
        f"<b style='color:#000;'>{len(p.get('email_ready',[]))} email-ready</b> · "
        f"${s.get('cost_usd', 0):.4f}{duplicate_text}{audit_text}</p>"
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


def _gaps_html(p: dict) -> str:
    eg = p.get("email_ready", [])
    if not eg:
        return "<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>Gaps</h2><p><em>No email-ready gaps today.</em></p>"
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>"
           f"⭐ Gaps ({len(eg)} email-ready)</h2>"]
    for item in eg:
        out.append(_gap_card_html(item))
    return "\n".join(out)


def _gap_card_html(item: dict) -> str:
    g = item["gap"]
    s = item["score"]
    gid = _e(g.get("_id", "?"))
    gtype = item["type"]
    hyp = _e(g.get("hypothesis", "?"))
    type_color = "#0a6e3d" if gtype == "engineering" else "#5a3b8c"
    type_bg = "#e6f4ea" if gtype == "engineering" else "#ede7f6"

    out = [
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px 18px;"
        f"margin:14px 0;background:#fff;'>",
        # Header bar
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;'>",
        f"<span style='font-size:13px;color:#888;'>[{gid}] "
        f"<span style='color:{type_color};background:{type_bg};padding:2px 8px;"
        f"border-radius:3px;font-size:11px;'>{_e(gtype.upper())}</span></span>",
        f"<span style='font-size:13px;color:#444;'>"
        f"<b>{_e(s['total'])}</b> "
        f"<span style='color:#888;'>(nov {_e(s['novelty'])} · act {_e(s['actionability'])} · "
        f"theory {_e(s.get('theoretical_support', '?'))})</span></span>",
        f"</div>",
        # Hypothesis
        f"<h3 style='margin:8px 0 4px 0;font-size:16px;line-height:1.35;'>{hyp}</h3>",
    ]
    if s.get("email_gate"):
        out.append(
            f"<p style='margin:4px 0;font-size:12px;color:#777;'>"
            f"Gate: {_e(s.get('email_gate'))} · {_e(s.get('email_gate_reason', ''))}</p>"
        )

    field = g.get("field_boundary_alignment") or {}
    if field:
        bits = []
        if field.get("field_id"):
            bits.append(f"Field: <b>{_e(field['field_id'])}</b>")
        if field.get("mechanism_family"):
            bits.append(f"Boundary: {_e(field['mechanism_family'])}")
        if field.get("open_bottleneck"):
            bits.append(f"Bottleneck: {_e(field['open_bottleneck'])}")
        if bits:
            out.append(
                f"<p style='margin:6px 0;font-size:13px;color:#555;'>"
                f"{' · '.join(bits)}</p>"
            )
        if field.get("why_aligned"):
            out.append(
                f"<p style='margin:4px 0 8px 0;font-size:12px;color:#777;'>"
                f"{_e(field['why_aligned'])}</p>"
            )

    # Structural mapping (Tier 1.2)
    sm = g.get("structural_mapping") or {}
    if sm:
        sev = sm.get("mismatch_severity", "?")
        sev_color = {"low": "#0a6e3d", "medium": "#b07000", "high": "#c0392b"}.get(sev, "#888")
        sev_emoji = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(sev, "⚪")
        out.append(
            f"<div style='background:#fff8e6;padding:10px 14px;border-radius:6px;margin:10px 0;font-size:14px;'>"
            f"<p style='margin:4px 0;'><b>🔗 Structural mapping</b> · "
            f"<span style='color:{sev_color};'>{sev_emoji} {_e(sm.get('match_status', '?'))} · mismatch {_e(sev)}</span></p>"
            f"<p style='margin:4px 0;'><b>AI</b>: {_e(sm.get('ai_data_structure', '?'))}</p>"
            f"<p style='margin:4px 0;'><b>Fin</b>: {_e(sm.get('fin_data_structure', '?'))}</p>"
        )
        if sm.get("bridge_required"):
            out.append(f"<p style='margin:4px 0;'><b>Bridge</b>: {_e(sm['bridge_required'])}</p>")
        out.append("</div>")

    # Research context block
    ctx = g.get("research_context") or {}
    if ctx:
        out.append("<div style='background:#f6f8fa;padding:10px 14px;border-radius:6px;margin:10px 0;font-size:14px;'>")
        if ctx.get("fin_current_state"):
            out.append(f"<p style='margin:4px 0;'><b>🏦 Fin 当前</b>: {_e(ctx['fin_current_state'])}</p>")
        if ctx.get("ai_frontier"):
            out.append(f"<p style='margin:4px 0;'><b>🤖 AI 前沿</b>: {_e(ctx['ai_frontier'])}</p>")
        if ctx.get("why_this_matters"):
            out.append(f"<p style='margin:4px 0;'><b>⭐ Why this matters</b>: {_e(ctx['why_this_matters'])}</p>")
        out.append("</div>")

    # Type-specific details
    if gtype == "engineering":
        roadmap = g.get("experimental_roadmap", {}) or {}
        out.append(_engineering_roadmap_html(roadmap))
    else:
        ai = g.get("ai_anchor", {})
        fin = g.get("fin_anchor", {})
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>AI anchor concept</b>: {_e(ai.get('concept','?'))}</p>")
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>Fin anchor</b>: {_e(fin.get('description','?')[:300])}</p>")

    # Deep brief link
    brief_path = item.get("_brief_path") or g.get("_brief_path")
    if brief_path:
        github_url = f"https://github.com/ycsama0703/AlphaGap/blob/main/{brief_path}"
        out.append(
            f"<p style='margin:12px 0 8px 0;font-size:14px;'>"
            f"<b>📖 Deep brief</b>: "
            f"<a href='{_e(github_url)}' style='color:#0066cc;text-decoration:none;'>{_e(brief_path)}</a>"
            f"</p>"
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
    data = roadmap.get("data", "?")
    metrics = roadmap.get("metrics") or {}
    baselines = roadmap.get("baselines") or []
    ablations = roadmap.get("ablations") or []
    compute = roadmap.get("compute_profile") or {}
    risks = roadmap.get("key_risks") or []
    effort = roadmap.get("estimated_effort", "?")

    out = [
        "<div style='margin:16px 0 8px;border-top:1px solid #e5e7eb;padding-top:14px;'>",
        "<p style='margin:0 0 10px;font-size:12px;font-weight:700;color:#475569;"
        "text-transform:uppercase;'>Experimental setup</p>",
        _dataset_panel(data),
        _metrics_panel(metrics),
        _comparison_panel(baselines, ablations),
    ]
    out.append(_feasibility_strip(effort, compute, risks))
    out.append("</div>")
    return "\n".join(out)


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


def _feasibility_strip(effort: object, compute: dict, risks: list) -> str:
    requirements = compute.get("requirements") or []
    if isinstance(requirements, str):
        requirements = [requirements]
    resource = ", ".join(str(value) for value in requirements) or "?"
    risk_text = "; ".join(str(value) for value in list(risks)[:2]) or "?"
    return (
        "<div style='margin:10px 0 0;padding:9px 12px;border-left:3px solid #94a3b8;"
        "background:#f8fafc;color:#475569;font-size:12px;line-height:1.55;'>"
        "<b style='color:#334155;'>Feasibility</b>"
        f" · effort {_e(effort)} · compute {_e(compute.get('tier', '?'))}"
        f" ({_e(resource)}) · runtime {_e(compute.get('estimated_runtime', '?'))}"
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
