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
        f"<h1>AlphaGap Daily — {d.isoformat()}</h1>",
        f"<p>Full audit: <code>inbox/{d.isoformat()}.md</code> (git pull to review)</p>",
        _stats_html(p),
        _papers_html(p),
        _trends_html(p),
        _gaps_html(p),
        _mapping_actions_html(p),
    ]
    return "\n".join(parts)


def _stats_html(p: dict) -> str:
    s = p.get("stats", {})
    return (
        f"<h2>Pipeline</h2><ul>"
        f"<li>Papers: {s.get('fetched','?')} fetched · {s.get('candidates','?')} candidates</li>"
        f"<li>L1: {s.get('l1_done','?')} | L2: {s.get('l2_done','?')}</li>"
        f"<li>Gaps: {len(p.get('theoretical', []))} theoretical + {len(p.get('engineering', []))} engineering</li>"
        f"<li>Accepted: {len(p.get('accepted', []))} | Email-ready: {len(p.get('email_ready', []))}</li>"
        f"<li>LLM cost: ${s.get('cost_usd', 0):.4f}</li></ul>"
    )


def _papers_html(p: dict) -> str:
    papers = p.get("top_papers", [])[:7]
    if not papers:
        return ""
    rows = []
    for paper in papers:
        title = paper.get("title", "?")
        affil = paper.get("affiliation_top", "") or "—"
        score = paper.get("score") or paper.get("priority_score") or 0
        url = paper.get("url") or f"https://arxiv.org/abs/{paper.get('id', '')}"
        method = ", ".join(paper.get("method_primary", [])[:2])
        rows.append(
            f"<li><a href='{url}'>[{paper.get('id','?')}]</a> "
            f"<b>{title}</b><br>"
            f"<small>{affil} · score {score} · method: {method}</small></li>"
        )
    return f"<h2>Top Papers</h2><ul>{''.join(rows)}</ul>"


def _trends_html(p: dict) -> str:
    out = ["<h2>Trends (14d rolling)</h2>"]
    for side, label in [("ai", "AI"), ("fin", "Fin")]:
        trends = p.get(f"{side}_trends", {})
        out.append(f"<h3>{label}</h3>")
        for bucket, title in [
            ("rising", "↑ Rising"),
            ("new_emergence", "★ New"),
            ("stable_hot", "→ Stable Hot"),
            ("falling", "↓ Falling"),
        ]:
            items = trends.get(bucket, []) if isinstance(trends, dict) else []
            if not items:
                continue
            out.append(f"<p><b>{title}</b></p><ul>")
            for it in items:
                out.append(f"<li><code>{it.get('name','?')}</code> — {it.get('comment','')}</li>")
            out.append("</ul>")
    return "\n".join(out)


def _gaps_html(p: dict) -> str:
    eg = p.get("email_ready", [])
    if not eg:
        return "<h2>Gaps (≥8)</h2><p><em>None today.</em></p>"
    out = ["<h2>Gaps (email-ready, score ≥ 8)</h2>"]
    for item in eg:
        g = item["gap"]
        s = item["score"]
        gid = g.get("_id", "?")
        gtype = item["type"]
        hyp = g.get("hypothesis", "?")
        out.append(
            f"<div style='border-left:4px solid #4080ff;padding:8px 12px;margin:12px 0;'>"
            f"<p><b>[{gid}]</b> <span style='color:#888;'>({gtype})</span> "
            f"total={s['total']} · novelty={s['novelty']} · actionability={s['actionability']}</p>"
            f"<p><b>假设</b>: {hyp}</p>"
        )
        if gtype == "engineering":
            roadmap = g.get("experimental_roadmap", {}) or {}
            out.append(f"<p><b>Data</b>: {roadmap.get('data','?')}</p>")
            metrics = roadmap.get("metrics", {}) or {}
            out.append(f"<p><b>Metrics</b>: primary={metrics.get('primary',[])}, secondary={metrics.get('secondary',[])}</p>")
            baselines = roadmap.get("baselines", []) or []
            if baselines:
                out.append("<p><b>Baselines</b>: " +
                           ", ".join(b.get("name", "?") for b in baselines) + "</p>")
            out.append(f"<p><b>Effort</b>: {roadmap.get('estimated_effort','?')}</p>")
        else:
            ai = g.get("ai_anchor", {})
            fin = g.get("fin_anchor", {})
            out.append(f"<p><b>AI anchor</b>: {ai.get('concept','?')}</p>")
            out.append(f"<p><b>Fin anchor</b>: {fin.get('description','?')[:200]}</p>")
        out.append("</div>")
    return "\n".join(out)


def _mapping_actions_html(p: dict) -> str:
    actions = p.get("mapping_actions", [])
    if not actions:
        return ""
    out = ["<h2>Mapping Actions (pending review)</h2><ul>"]
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
