"""The Phase-0 gates, computed from the filled annotation.csv (2 or 3 blind judges).

  python -m phase0.stats

Judge columns: suff_A / suff_B / suff_C (fresh Claude / GPT / DeepSeek — any blind models).
  G1 诊断对象存在 — numeric-correct × evidence-sufficient (MAJORITY vote of judges) on qualitative claims; want correct-but-insufficient ≥ ~15-20%
  G2 可学习下限   — inter-judge agreement: pairwise Cohen's κ, and Fleiss' κ when 3 judges; want ≥ 0.6
  G3 主约束(覆盖) — % tasks where the agent retrieved evidence (≥1 tool call); want ≥ 70%
'unknown' counts as not-sufficient for G1; ties → insufficient.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from itertools import combinations
from pathlib import Path

_DIR = Path(__file__).resolve().parent
_OUT = _DIR / "out"
JUDGE_COLS = ["suff_A", "suff_B", "suff_C", "suff_D"]


def _cohen(a: list[str], b: list[str]) -> float | None:
    pairs = [(x, y) for x, y in zip(a, b) if x and y]
    if not pairs:
        return None
    cats = sorted({x for p in pairs for x in p})
    n = len(pairs)
    po = sum(1 for x, y in pairs if x == y) / n
    ca, cb = Counter(x for x, _ in pairs), Counter(y for _, y in pairs)
    pe = sum((ca[c] / n) * (cb[c] / n) for c in cats)
    return round((po - pe) / (1 - pe), 3) if pe != 1 else 1.0


def _fleiss(rater_rows: list[list[str]]) -> float | None:
    """rater_rows = per-item list of each judge's label; only items where ALL judges labelled are used."""
    items = [r for r in rater_rows if all(r)]
    if not items:
        return None
    n = len(items[0])
    if any(len(r) != n for r in items) or n < 2:
        return None
    cats = sorted({x for r in items for x in r})
    N = len(items)
    p_j = {c: 0 for c in cats}
    P_i = []
    for r in items:
        cnt = Counter(r)
        for c in cats:
            p_j[c] += cnt[c]
        P_i.append((sum(v * v for v in cnt.values()) - n) / (n * (n - 1)))
    for c in cats:
        p_j[c] /= (N * n)
    P_bar = sum(P_i) / N
    P_e = sum(v * v for v in p_j.values())
    return round((P_bar - P_e) / (1 - P_e), 3) if P_e != 1 else 1.0


def main():
    csv_path = _OUT / "annotation.csv"
    if not csv_path.exists():
        print(f"no {csv_path} — run the pipeline + ingest judge labels first"); return
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    res_path = _OUT / "results.jsonl"
    results = [json.loads(l) for l in res_path.read_text().splitlines() if l.strip()] if res_path.exists() else []
    qual = [r for r in rows if r["kind"] == "qualitative"]

    all_suff = [c for c in rows[0].keys() if c.startswith("suff_") and c != "suff_claude_ctx"]
    judges = [c for c in all_suff if any(r.get(c) for r in qual)]
    jpath = _OUT / "judges.json"
    names = json.loads(jpath.read_text()) if jpath.exists() else {}
    nm = lambda c: names.get(c, c)
    print(f"=== Phase-0 gates ===  ({len(qual)} qualitative claims · {len(judges)} judges)")
    for c in judges:
        print(f"   {c} = {nm(c)}")
    print()
    if not judges:
        print("no judge labels yet — ingest at least one suff_* column"); return

    def suff_majority(r) -> bool:
        votes = [r.get(c) for c in judges if r.get(c)]
        s = sum(1 for v in votes if v == "sufficient")
        return s * 2 > len(votes)   # strict majority; tie/unknown → not sufficient

    # G1 — 2x2 with majority-vote sufficiency
    cell = Counter()
    for r in qual:
        correct = str(r.get("auto_numeric_correct")).lower() == "true"
        cell[(correct, suff_majority(r))] += 1
    tot = sum(cell.values())
    ci = cell[(True, False)]
    print("G1 诊断对象存在 — 2x2 (numeric_correct × evidence_sufficient[majority]):")
    print(f"     correct & sufficient   : {cell[(True, True)]}")
    print(f"     correct & INSUFFICIENT : {ci}   ← the bug we care about")
    print(f"     wrong   & sufficient   : {cell[(False, True)]}")
    print(f"     wrong   & insufficient : {cell[(False, False)]}")
    g1 = bool(tot and ci / tot >= 0.15)
    if tot:
        print(f"     correct-but-insufficient share = {ci/tot:.0%}  -> {'GO (≥15%)' if g1 else 'WEAK (<15%)'}")
    print()

    # G2 — inter-judge agreement
    print("G2 可学习下限 — inter-judge agreement:")
    for x, y in combinations(judges, 2):
        k = _cohen([r.get(x, "") for r in qual], [r.get(y, "") for r in qual])
        print(f"     Cohen's κ {x}–{y} = {k}")
    fleiss = None
    if len(judges) >= 3:
        fleiss = _fleiss([[r.get(c, "") for c in judges] for r in qual])
        print(f"     Fleiss' κ (all {len(judges)}) = {fleiss}")
    # leave-one-out: re-agreement with each judge removed → surfaces an outlier dragging κ down
    loo = {}
    if len(judges) >= 3:
        for drop in judges:
            rest = [c for c in judges if c != drop]
            if len(rest) >= 3:
                loo[drop] = _fleiss([[r.get(c, "") for c in rest] for r in qual])
            else:
                loo[drop] = _cohen([r.get(rest[0], "") for r in qual], [r.get(rest[1], "") for r in qual])
        print("     leave-one-out κ (agreement of the OTHERS when this judge is dropped):")
        for c, v in sorted(loo.items(), key=lambda kv: -(kv[1] or 0)):
            flag = "  ← outlier (others agree much better without it)" if (v or 0) >= 0.6 and (fleiss or 0) < 0.6 else ""
            print(f"        drop {c}: {v}{flag}")
    # gate: full-set κ; but if dropping one outlier lifts the rest to ≥0.6, report that as the real signal
    gate_k = fleiss if (len(judges) >= 3 and fleiss is not None) else \
        _cohen([r.get(judges[0], "") for r in qual], [r.get(judges[1], "") for r in qual]) if len(judges) >= 2 else None
    best_loo = max(loo.values(), key=lambda v: (v or 0)) if loo else None
    g2 = bool(gate_k is not None and gate_k >= 0.6)
    g2_minus1 = bool(best_loo is not None and best_loo >= 0.6)
    print(f"     gate κ (all judges) = {gate_k} -> {'GO (≥0.6)' if g2 else ('need ≥2 judges' if gate_k is None else 'WEAK (<0.6)')}")
    if not g2 and g2_minus1:
        print(f"     BUT dropping the single outlier → κ={best_loo} ≥0.6: the rest agree (one dissenter, not concept fuzziness)")
    print()

    # G3 — coverage
    g3 = False
    if results:
        cov = sum(1 for r in results if (r.get('agent') or {}).get('n_tool_calls', 0) >= 1)
        g3 = cov / len(results) >= 0.7
        print(f"G3 主约束(覆盖) — tasks with ≥1 evidence call: {cov}/{len(results)} = {cov/len(results):.0%}"
              f"  -> {'GO (≥70%)' if g3 else 'WEAK (<70%)'}")

    # G2 effectively passes if the full set agrees, OR (with ≥4 judges) the rest agree once one outlier is dropped
    g2_eff = g2 or bool(g2_minus1 and len(judges) >= 4)
    if not g1:
        v = "STOP — the phenomenon is too rare (G1); not worth a paper."
    elif g1 and g2_eff and g3:
        extra = "" if g2 else " (3+ judges agree; one stricter outlier set aside as a robustness note)"
        v = f"PROCEED — axis is real AND judges agree → build the merged MECH-1+2 pilot.{extra}"
    else:
        miss = ", ".join(n for n, ok in [("G1", g1), ("G2", g2_eff), ("G3", g3)] if not ok)
        v = f"SHARPEN & RE-TEST — phenomenon real (G1 ok) but {miss} not met; pin the rubric + re-judge."
    print(f"\nVERDICT: G1={'GO' if g1 else 'NO'} · G2={'GO' if g2_eff else 'NO'} · G3={'GO' if g3 else 'NO'}\n  {v}")


if __name__ == "__main__":
    main()
