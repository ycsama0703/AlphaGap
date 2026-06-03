"""Transfer-cell admin: coverage heatmap + frontier→new-cell approval.

The 30 transfer cells are the opportunity grid that normalizes the loop (every
grounded gap lands on one). Two human-facing tools here:

  1. coverage / CELL-COVERAGE.md — which cells get proposed against (and how often)
     vs which sit untouched. The diversity yard-stick under the curated-frontier design.
  2. frontier→cell approval — frontier_extension gaps propose NEW cells the grid lacks.
     Those proposals queue in pending_cells.jsonl; a human approves the good ones, which
     appends them to transfer_cells.yaml so the grid GROWS (keeps the loop from calcifying).
     transfer_cells.yaml policy is automatic_new_cells:false — growth is human-gated by design.

CLI:
  python -m pipeline.cells coverage            # refresh CELL-COVERAGE.md
  python -m pipeline.cells pending [--days N]   # collect + list pending new-cell proposals
  python -m pipeline.cells approve <n>          # promote pending #n into transfer_cells.yaml
  python -m pipeline.cells reject  <n> [reason]
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path

import yaml

from .config import PROJECT_ROOT

CELLS_YAML = PROJECT_ROOT / "knowledge" / "fin_fields" / "transfer_cells.yaml"
GAP_LOG = PROJECT_ROOT / "gap_log.jsonl"
PENDING = PROJECT_ROOT / "pending_cells.jsonl"
COVERAGE_MD = PROJECT_ROOT / "CELL-COVERAGE.md"


def _load_gap_rows() -> list[dict]:
    if not GAP_LOG.exists():
        return []
    return [json.loads(l) for l in GAP_LOG.read_text().splitlines() if l.strip()]


def active_cells() -> list[dict]:
    if not CELLS_YAML.exists():
        return []
    doc = yaml.safe_load(CELLS_YAML.read_text()) or {}
    return doc.get("cells", []) or []


# ---------- coverage heatmap ----------
def coverage(days: int | None = None, as_of: date | None = None) -> dict:
    cells = active_cells()
    rows = _load_gap_rows()
    if days is not None:
        cutoff = (as_of or date.today()).toordinal() - days
        rows = [r for r in rows if _ord(r.get("date")) >= cutoff]
    used: dict[str, int] = {}
    for r in rows:
        cid = r.get("transfer_cell_id")
        if cid:
            used[cid] = used.get(cid, 0) + 1
    by_field: dict[str, list] = {}
    for c in cells:
        by_field.setdefault(c.get("field_id", "?"), []).append(
            {"cell_id": c["cell_id"], "count": used.get(c["cell_id"], 0)})
    untouched = [c["cell_id"] for c in cells if used.get(c["cell_id"], 0) == 0]
    return {"total_cells": len(cells), "used_cells": len([c for c in cells if used.get(c["cell_id"])]),
            "untouched": untouched, "by_field": by_field, "raw_used": used,
            "unknown_cell_gaps": sum(1 for r in rows if not r.get("transfer_cell_id"))}


def _ord(d) -> int:
    try:
        return date.fromisoformat(str(d)).toordinal()
    except Exception:
        return 0


def render_coverage(days: int | None = None) -> Path:
    cov = coverage(days)
    lines = ["# AlphaGap — Transfer-Cell Coverage", "",
             f"> {cov['used_cells']}/{cov['total_cells']} cells have been proposed against"
             + (f" (last {days}d)" if days else "")
             + f"; {len(cov['untouched'])} untouched. The opportunity grid's coverage = "
               "the diversity yard-stick.", ""]
    for field, cells in sorted(cov["by_field"].items()):
        hot = sum(1 for c in cells if c["count"] > 0)
        lines.append(f"## {field}  ({hot}/{len(cells)} used)")
        for c in sorted(cells, key=lambda x: -x["count"]):
            bar = "█" * min(c["count"], 20)
            mark = "" if c["count"] else "  ← untouched"
            lines.append(f"- `{c['cell_id']}`  {c['count']:>3} {bar}{mark}")
        lines.append("")
    COVERAGE_MD.write_text("\n".join(lines))
    return COVERAGE_MD


# ---------- frontier → new-cell approval ----------
def _proposal_id(p: dict) -> str:
    key = f"{p.get('field_id')}|{p.get('new_failure_mode')}|{p.get('ai_intervention_class')}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def collect_pending(days: int = 30, as_of: date | None = None) -> int:
    """Scan the ledger for frontier_extension proposed_cells → pending queue (dedup)."""
    cutoff = (as_of or date.today()).toordinal() - days
    existing = {p["id"] for p in _load_pending()}
    active_ids = {c["cell_id"] for c in active_cells()}
    added = 0
    with PENDING.open("a") as f:
        for r in _load_gap_rows():
            if r.get("opportunity_mode") != "frontier_extension":
                continue
            if _ord(r.get("date")) < cutoff:
                continue
            pc = r.get("proposed_cell") or {}
            if not pc.get("new_failure_mode"):
                continue
            prop = {
                "field_id": r.get("field_id"), "mechanism_family": r.get("mechanism_family"),
                "new_failure_mode": pc.get("new_failure_mode"),
                "ai_intervention_class": pc.get("ai_intervention_class"),
                "experiment_anchor_sketch": pc.get("experiment_anchor_sketch"),
                "why_existing_cells_insufficient": pc.get("why_existing_cells_insufficient"),
                "from_gap": r.get("gap_id"), "first_seen": r.get("date"),
            }
            prop["id"] = _proposal_id(prop)
            if prop["id"] in existing or prop["id"] in active_ids:
                continue
            existing.add(prop["id"])
            f.write(json.dumps(prop, ensure_ascii=False) + "\n")
            added += 1
    return added


def _load_pending() -> list[dict]:
    if not PENDING.exists():
        return []
    out = []
    for l in PENDING.read_text().splitlines():
        if l.strip():
            r = json.loads(l)
            if not r.get("_resolved"):
                out.append(r)
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")[:30] or "new"


def approve(idx: int) -> str:
    """Promote pending proposal #idx into transfer_cells.yaml (text-append, preserves
    the file's comments/structure). The new cell is a DRAFT — refine the experiment_anchor
    metrics/baseline in the yaml; bottleneck/failure come from the proposal."""
    pend = _load_pending()
    if not (1 <= idx <= len(pend)):
        return f"no pending proposal #{idx} (have {len(pend)})"
    p = pend[idx - 1]
    field = p.get("field_id", "fin")
    cell_id = f"{field.split('_')[0]}.{_slug(p.get('new_failure_mode'))}"
    block = (
        f"\n  - cell_id: {cell_id}\n"
        f"    field_id: {field}\n"
        f"    mechanism_family: {p.get('mechanism_family','')}\n"
        f"    bottleneck: {p.get('new_failure_mode','')}\n"
        f"    ai_intervention_class: {p.get('ai_intervention_class','')}\n"
        f"    experiment_anchor:\n"
        f"      data_object: \"{p.get('experiment_anchor_sketch','') or '(refine)'}\"\n"
        f"      primary_metric: \"(refine)\"\n"
        f"      baseline: \"(refine)\"\n"
        f"      failure_mode: \"{p.get('new_failure_mode','')}\"\n"
        f"    provenance: {{from_gap: {p.get('from_gap')}, approved: {date.today().isoformat()}, needs_refinement: true}}\n"
    )
    text = CELLS_YAML.read_text().rstrip() + "\n" + block
    text = re.sub(r"last_reviewed:.*", f"last_reviewed: {date.today().isoformat()}", text, count=1)
    CELLS_YAML.write_text(text)
    _resolve(p["id"], "approved", cell_id)
    return f"approved → added cell `{cell_id}` to transfer_cells.yaml (refine experiment_anchor metrics)"


def reject(idx: int, reason: str = "") -> str:
    pend = _load_pending()
    if not (1 <= idx <= len(pend)):
        return f"no pending proposal #{idx}"
    _resolve(pend[idx - 1]["id"], "rejected", reason)
    return f"rejected pending #{idx}"


def _resolve(pid: str, status: str, detail: str) -> None:
    rows = [json.loads(l) for l in PENDING.read_text().splitlines() if l.strip()] if PENDING.exists() else []
    for r in rows:
        if r.get("id") == pid:
            r["_resolved"] = status
            r["_detail"] = detail
    PENDING.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "coverage"
    if cmd == "coverage":
        d = int(sys.argv[3]) if "--days" in sys.argv else None
        print("wrote", render_coverage(d))
        print(json.dumps(coverage(d), ensure_ascii=False, indent=2)[:600])
    elif cmd == "pending":
        days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 30
        n = collect_pending(days)
        pend = _load_pending()
        print(f"collected {n} new; {len(pend)} pending:")
        for i, p in enumerate(pend, 1):
            print(f"  [{i}] ({p['field_id']}) {p['new_failure_mode']}  ← {p['ai_intervention_class']}")
    elif cmd == "approve":
        print(approve(int(sys.argv[2])))
    elif cmd == "reject":
        print(reject(int(sys.argv[2]), " ".join(sys.argv[3:])))
    else:
        print(__doc__)
