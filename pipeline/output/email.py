"""Send daily email via Resend.

Email contains:
  1. 今日重点论文 top 5-10（高价值作者/机构）
  2. AI 方向 trends（14 天滚动）
  3. Fin 方向 trends
  4. 高分 Gap（total >= 8）— 理论型 + 工程型并列展示

NOT a paper digest — full audit lives in inbox/YYYY-MM-DD.md.
"""
from __future__ import annotations

import logging
from datetime import date

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
    return (
        f"<p style='color:#888;font-size:13px;margin-top:0;'>"
        f"{s.get('fetched','?')} papers · {s.get('l1_done','?')} extracted · "
        f"{len(p.get('theoretical',[]))} theoretical + {len(p.get('engineering',[]))} engineering gaps · "
        f"<b style='color:#000;'>{len(p.get('email_ready',[]))} email-ready</b> · "
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
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;margin-top:24px;'>"
           f"📈 Trends (14d rolling)</h2>"]
    for side, label, emoji in [("ai", "AI", "🤖"), ("fin", "Fin", "🏦")]:
        trends = p.get(f"{side}_trends", {})
        all_items = []
        for bucket, marker in [
            ("rising", "↑"),
            ("new_emergence", "★"),
            ("stable_hot", "→"),
            ("falling", "↓"),
        ]:
            for it in (trends.get(bucket, []) or []):
                all_items.append((marker, it.get("name", "?"), it.get("comment", "")))
        if not all_items:
            continue
        out.append(f"<p style='margin:8px 0 4px 0;'><b>{emoji} {label}</b></p>")
        out.append("<ul style='font-size:13px;padding-left:20px;margin:4px 0;'>")
        for marker, name, comment in all_items[:8]:
            out.append(f"<li><span style='color:#888;'>{marker}</span> "
                       f"<code style='background:#f0f0f0;padding:1px 4px;border-radius:3px;'>{name}</code> "
                       f"— {comment}</li>")
        out.append("</ul>")
    return "\n".join(out)


def _gaps_html(p: dict) -> str:
    eg = p.get("email_ready", [])
    if not eg:
        return "<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>Gaps</h2><p><em>No email-ready gaps today.</em></p>"
    out = [f"<h2 style='border-bottom:1px solid #ddd;padding-bottom:4px;'>"
           f"⭐ Gaps ({len(eg)} email-ready, score ≥ 8)</h2>"]
    for item in eg:
        out.append(_gap_card_html(item))
    return "\n".join(out)


def _gap_card_html(item: dict) -> str:
    g = item["gap"]
    s = item["score"]
    gid = g.get("_id", "?")
    gtype = item["type"]
    hyp = g.get("hypothesis", "?")
    type_color = "#0a6e3d" if gtype == "engineering" else "#5a3b8c"
    type_bg = "#e6f4ea" if gtype == "engineering" else "#ede7f6"

    out = [
        f"<div style='border:1px solid #ddd;border-radius:8px;padding:14px 18px;"
        f"margin:14px 0;background:#fff;'>",
        # Header bar
        f"<div style='display:flex;justify-content:space-between;align-items:baseline;'>",
        f"<span style='font-size:13px;color:#888;'>[{gid}] "
        f"<span style='color:{type_color};background:{type_bg};padding:2px 8px;"
        f"border-radius:3px;font-size:11px;'>{gtype.upper()}</span></span>",
        f"<span style='font-size:13px;color:#444;'>"
        f"<b>{s['total']}</b> "
        f"<span style='color:#888;'>(nov {s['novelty']} · act {s['actionability']})</span></span>",
        f"</div>",
        # Hypothesis
        f"<h3 style='margin:8px 0 4px 0;font-size:16px;line-height:1.35;'>{hyp}</h3>",
    ]

    # Research context block
    ctx = g.get("research_context") or {}
    if ctx:
        out.append("<div style='background:#f6f8fa;padding:10px 14px;border-radius:6px;margin:10px 0;font-size:14px;'>")
        if ctx.get("fin_current_state"):
            out.append(f"<p style='margin:4px 0;'><b>🏦 Fin 当前</b>: {ctx['fin_current_state']}</p>")
        if ctx.get("ai_frontier"):
            out.append(f"<p style='margin:4px 0;'><b>🤖 AI 前沿</b>: {ctx['ai_frontier']}</p>")
        if ctx.get("why_this_matters"):
            out.append(f"<p style='margin:4px 0;'><b>⭐ Why this matters</b>: {ctx['why_this_matters']}</p>")
        out.append("</div>")

    # Type-specific details
    if gtype == "engineering":
        roadmap = g.get("experimental_roadmap", {}) or {}
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>Data</b>: {roadmap.get('data','?')}</p>")
        metrics = roadmap.get("metrics", {}) or {}
        out.append(
            f"<p style='margin:8px 0;font-size:14px;'><b>Metrics</b>: "
            f"primary={metrics.get('primary',[])} · "
            f"secondary={metrics.get('secondary',[])}</p>"
        )
        baselines = roadmap.get("baselines", []) or []
        if baselines:
            out.append("<p style='margin:8px 0;font-size:14px;'><b>Baselines</b>: " +
                       " · ".join(b.get("name", "?") for b in baselines) + "</p>")
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>Effort</b>: {roadmap.get('estimated_effort','?')}</p>")
    else:
        ai = g.get("ai_anchor", {})
        fin = g.get("fin_anchor", {})
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>AI anchor concept</b>: {ai.get('concept','?')}</p>")
        out.append(f"<p style='margin:8px 0;font-size:14px;'><b>Fin anchor</b>: {fin.get('description','?')[:300]}</p>")

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


def _paper_li(paper: dict) -> str:
    title = (paper.get("title") or "?")[:120]
    url = paper.get("url", "")
    affil = paper.get("affiliation") or ""
    method = paper.get("method") or ""
    extra = " · ".join(x for x in [affil, method] if x)
    extra_html = f"<br><span style='color:#888;font-size:11px;'>{extra}</span>" if extra else ""
    return f"<li><a href='{url}' style='color:#0066cc;text-decoration:none;'>[{paper.get('id','?')}]</a> {title}{extra_html}</li>"


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
