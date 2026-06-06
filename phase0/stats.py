"""Step 3: the 4 Phase-0 gates, computed from the filled annotation.csv.

  python -m phase0.stats           # reads phase0/out/annotation.csv (with suff_A/suff_B filled)

Prints:
  G1 诊断对象存在 — 2x2 (numeric-correct × evidence-sufficient) on QUALITATIVE claims; want correct-but-insufficient ≥ ~15-20%
  G2 可学习下限   — Cohen's κ between annotator A and B; want κ ≥ 0.6
  G3 主约束(覆盖) — % tasks where the agent retrieved evidence (≥1 tool call); want ≥ 70%
A claim's sufficiency = annotator A's label (B is only for κ). 'unknown' is treated as insufficient for G1.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_OUT = _DIR / "out"


def _kappa(a: list[str], b: list[str]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x and y]
    if not pairs:
        return None
    cats = sorted({x for p in pairs for x in p})
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe != 1 else 1.0


def main():
    csv_path = _OUT / "annotation.csv"
    if not csv_path.exists():
        print(f"no {csv_path} — run `python -m phase0.run_phase0` first, then fill suff_A/suff_B")
        return
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    res_path = _OUT / "results.jsonl"
    results = [json.loads(l) for l in res_path.read_text().splitlines() if l.strip()] if res_path.exists() else []

    filled = [r for r in rows if r.get("suff_A")]
    qual = [r for r in filled if r.get("kind") == "qualitative"]

    print(f"=== Phase-0 gates ===  ({len(rows)} claims, {len(filled)} annotated, {len(qual)} qualitative)\n")

    # G1 — 2x2 on qualitative claims: numeric-correct(task) × evidence-sufficient(claim)
    cell = Counter()
    for r in qual:
        correct = str(r.get("auto_numeric_correct")).lower() == "true"
        suff = r.get("suff_A", "").strip().lower() == "sufficient"
        cell[(correct, suff)] += 1
    tot = sum(cell.values())
    ci = cell[(True, False)]  # correct answer, INSUFFICIENT evidence  ← the phenomenon
    print("G1 诊断对象存在 — 2x2 (numeric_correct × evidence_sufficient), qualitative claims:")
    print(f"     correct & sufficient   : {cell[(True, True)]}")
    print(f"     correct & INSUFFICIENT : {ci}   ← the bug we care about")
    print(f"     wrong   & sufficient   : {cell[(False, True)]}")
    print(f"     wrong   & insufficient : {cell[(False, False)]}")
    if tot:
        share = ci / tot
        print(f"     correct-but-insufficient share = {share:.0%}  -> {'GO (≥15%)' if share >= 0.15 else 'WEAK (<15%)'}")
    print()

    # G2 — Cohen's kappa A vs B
    k = _kappa([r.get("suff_A", "") for r in rows], [r.get("suff_B", "") for r in rows])
    print(f"G2 可学习下限 — Cohen's κ (A vs B) = {k}  -> "
          f"{'GO (≥0.6)' if (k is not None and k >= 0.6) else ('need B labels' if k is None else 'WEAK (<0.6)')}\n")

    # G3 — coverage: % tasks with ≥1 tool call
    if results:
        cov = sum(1 for r in results if (r.get('agent') or {}).get('n_tool_calls', 0) >= 1)
        print(f"G3 主约束(覆盖) — tasks with ≥1 evidence call: {cov}/{len(results)} = {cov/len(results):.0%}"
              f"  -> {'GO (≥70%)' if cov/len(results) >= 0.7 else 'WEAK (<70%)'}")
    # computed verdict (not a hardcoded line)
    g1 = bool(tot and ci / tot >= 0.15)
    g2 = bool(k is not None and k >= 0.6)
    g3 = bool(results and sum(1 for r in results
                              if (r.get('agent') or {}).get('n_tool_calls', 0) >= 1) / len(results) >= 0.7)
    if not g1:
        v = "STOP — the phenomenon is too rare (G1); not worth a paper."
    elif g1 and g2 and g3:
        v = "PROCEED — axis is real AND judges agree → build the merged MECH-1+2 pilot."
    else:
        miss = ", ".join(n for n, ok in [("G1", g1), ("G2", g2), ("G3", g3)] if not ok)
        v = (f"SHARPEN & RE-TEST — phenomenon real (G1 ok) but {miss} not met. "
             "Pin the rubric's ambiguous cases, re-judge with two fresh models, re-check κ.")
    print(f"\nVERDICT: G1={'GO' if g1 else 'NO'} · G2={'GO' if g2 else 'NO'} · G3={'GO' if g3 else 'NO'}\n  {v}")


if __name__ == "__main__":
    main()
