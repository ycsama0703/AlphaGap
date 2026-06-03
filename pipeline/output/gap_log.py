"""Gap ledger — a unified, structured record of every gap generated each day.

Two jobs from one artifact:
  1. The record you can actually read (GAP-LOG.md) instead of digging through emails.
  2. The data source for cross-day dedup (O3): so generation doesn't re-propose a
     direction it already proposed a few days ago.

CRITICAL — record at the MECHANISM level, not brand names. The dedup signature is built
from the *functional* description (field boundary + mechanism family + the brand-free
hypothesis / ai_anchor.concept that the prompts already enforce), NEVER from
method_primary brand names (FIPO, Reflexion, ...). Brand names / paper IDs are stored
only as evidence, so two gaps that are the same mechanism transfer with different paper
citations are still caught as duplicates — and so the model, when shown "recently
proposed", reasons about mechanisms it can judge deeply, not labels.

Storage: gap_log.jsonl (one row per generated gap; committed to the repo so it's durable
and locally queryable). Human view: GAP-LOG.md.
"""
from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from ..config import PROJECT_ROOT

LOG = PROJECT_ROOT / "gap_log.jsonl"
INDEX = PROJECT_ROOT / "GAP-LOG.md"

_STOP = {"the", "a", "an", "of", "to", "for", "in", "on", "and", "or", "with", "use",
         "using", "via", "based", "by", "from", "into", "as", "is", "are"}


def _tokens(*texts: str) -> set[str]:
    out: set[str] = set()
    for t in texts:
        for w in re.findall(r"[a-z0-9\-]+", (t or "").lower()):
            if len(w) >= 3 and w not in _STOP:
                out.add(w)
    return out


def _mechanism_fields(gap: dict) -> dict:
    """Extract the MECHANISM-level fields (no brand names) used for the signature."""
    fba = gap.get("field_boundary_alignment") or {}
    ai = gap.get("ai_anchor") or {}
    sm = gap.get("structural_mapping") or {}
    return {
        "field_id": fba.get("field_id", ""),
        "mechanism_family": fba.get("mechanism_family", ""),
        # ai_anchor.concept is brand-free by prompt contract; fall back to the
        # structural AI-side description — NEVER method_primary.
        "ai_mechanism": ai.get("concept", "") or sm.get("ai_data_structure", ""),
        "hypothesis": gap.get("hypothesis", ""),
    }


def signature_tokens(gap: dict) -> list[str]:
    """Mechanism-level dedup signature. Deliberately excludes method_primary brands."""
    m = _mechanism_fields(gap)
    toks = _tokens(m["field_id"], m["mechanism_family"], m["ai_mechanism"], m["hypothesis"])
    return sorted(toks)


def _anchor_ids(gap: dict) -> list[str]:
    """Paper IDs (evidence only — kept OUT of the signature)."""
    ids = []
    ai = gap.get("ai_anchor") or {}
    if ai.get("paper_id"):
        ids.append(ai["paper_id"])
    for p in (gap.get("anchor_papers") or {}).get("ai", []):
        if isinstance(p, dict) and p.get("id"):
            ids.append(p["id"])
    return sorted(set(ids))


def _row(run_date: str, item: dict, verdict: str) -> dict:
    gap = item.get("gap") or {}
    m = _mechanism_fields(gap)
    return {
        "date": run_date,
        "gap_id": gap.get("_id") or gap.get("gap_id") or "?",
        "type": item.get("type", "?"),
        "verdict": verdict,                       # email_ready | accepted | rejected | downgraded
        "field_id": m["field_id"],
        "mechanism_family": m["mechanism_family"],
        "ai_mechanism": m["ai_mechanism"][:160],  # functional, no brand
        "hypothesis": m["hypothesis"][:240],
        "anchor_paper_ids": _anchor_ids(gap),     # evidence only
        "score_total": (item.get("score") or {}).get("total"),
        "signature": signature_tokens(gap),
    }


def append_run(run_date: date, result: dict, log: Path = LOG) -> int:
    """Append every generated gap from a run to the ledger. Records ALL of them
    (email-ready + accepted + rejected + downgraded), not just the emailed few, so
    the record is complete and dedup sees everything proposed."""
    d = run_date.isoformat()
    email_ids = {(it.get("gap") or {}).get("_id") for it in result.get("email_ready", [])}
    rows: list[dict] = []
    for it in result.get("accepted", []):
        gid = (it.get("gap") or {}).get("_id")
        rows.append(_row(d, it, "email_ready" if gid in email_ids else "accepted"))
    for it in result.get("rejected", []):
        rows.append(_row(d, it, "rejected"))
    for it in result.get("downgraded", []):
        rows.append(_row(d, it, "downgraded"))
    with log.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    render_index(log)
    return len(rows)


def _load(log: Path = LOG) -> list[dict]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def recent_anchor_ids(days: int, *, as_of: date | None = None, log: Path = LOG) -> set[str]:
    """Paper IDs anchored in the last `days` days — to exclude from new anchoring (O3)."""
    rows = _load(log)
    cutoff = (as_of or date.today()).toordinal() - days
    out: set[str] = set()
    for r in rows:
        try:
            if date.fromisoformat(r["date"]).toordinal() >= cutoff:
                out.update(r.get("anchor_paper_ids", []))
        except Exception:
            continue
    return out


def recent_signatures(days: int, *, as_of: date | None = None, log: Path = LOG) -> list[dict]:
    """Mechanism-level descriptions proposed in the last `days` days — fed to the
    generation prompt as 'avoid or clearly differentiate'. Brand-free by construction."""
    rows = _load(log)
    cutoff = (as_of or date.today()).toordinal() - days
    out = []
    for r in rows:
        try:
            if date.fromisoformat(r["date"]).toordinal() >= cutoff:
                out.append({
                    "field_id": r.get("field_id"),
                    "mechanism_family": r.get("mechanism_family"),
                    "ai_mechanism": r.get("ai_mechanism"),
                    "hypothesis": r.get("hypothesis"),
                    "verdict": r.get("verdict"),
                    "date": r.get("date"),
                    "_sig": set(r.get("signature", [])),
                })
        except Exception:
            continue
    return out


def render_index(log: Path = LOG, index: Path = INDEX) -> Path:
    """Human-readable record: what mechanisms were proposed, by day."""
    rows = _load(log)
    by_day: dict[str, list[dict]] = {}
    for r in rows:
        by_day.setdefault(r["date"], []).append(r)
    lines = ["# AlphaGap — Daily Gap Log", "",
             "> Every gap generated each day (mechanism-level, brand-free). "
             "The record to read instead of digging through emails; also the cross-day "
             "dedup source.", ""]
    for day in sorted(by_day, reverse=True):
        items = by_day[day]
        n_email = sum(1 for r in items if r["verdict"] == "email_ready")
        lines.append(f"## {day}  ({len(items)} gaps · {n_email} runnable)")
        lines.append("")
        lines.append("| verdict | field | mechanism family | hypothesis (functional) |")
        lines.append("|---|---|---|---|")
        for r in sorted(items, key=lambda x: x["verdict"]):
            lines.append(f"| {r['verdict']} | {r.get('field_id','')} | "
                         f"{r.get('mechanism_family','')} | {r.get('hypothesis','')} |")
        lines.append("")
    index.write_text("\n".join(lines))
    return index
