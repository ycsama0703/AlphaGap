"""P1 readout: (a) inter-judge agreement at scale, (b) does the benchmark separate the agent configs?

  python -m evidence_sufficiency.stats_p1

P1 go/no-go:
  (a) judges agree at scale under the fixed rubric — Fleiss/Cohen κ (≥0.7 within a camp);
  (b) agent configs differ on evidence sufficiency — full should be far less insufficient than numeric_only.
Sufficiency per claim = MAJORITY of the filled judge columns (unknown/tie → not sufficient).
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

from phase0.stats import _cohen, _fleiss

_OUT = Path(__file__).resolve().parent / "out"


def main():
    rows = list(csv.DictReader((_OUT / "annotation_p1.csv").open(encoding="utf-8")))
    qual = [r for r in rows if r["kind"] == "qualitative"]
    judges = [c for c in rows[0] if c.startswith("suff_") and any(r.get(c) for r in qual)]
    jpath = _OUT / "judges_p1.json"
    names = json.loads(jpath.read_text()) if jpath.exists() else {}
    print(f"=== P1 ({len(qual)} qualitative claims · judges: {', '.join(names.get(c, c) for c in judges) or 'NONE'}) ===\n")

    def suff(r):
        v = [r.get(c) for c in judges if r.get(c)]
        return v and sum(1 for x in v if x == "sufficient") * 2 > len(v)

    # (b) per-config differentiation
    print("(b) benchmark separates agent configs?")
    by = defaultdict(lambda: {"q": 0, "insuf": 0, "num_ok": 0, "num_tot": 0})
    for r in qual:
        b = by[r["agent_config"]]
        b["q"] += 1
        if judges and not suff(r):
            b["insuf"] += 1
    # numeric from results
    res = [json.loads(l) for l in (_OUT / "results_p1.jsonl").read_text().splitlines() if l.strip()]
    numby = defaultdict(lambda: [0, 0])
    for r in res:
        g = r["numeric_grade"].get("numeric_correct")
        if g is not None:
            numby[r["agent_config"]][1] += 1
            numby[r["agent_config"]][0] += int(g is True)
    for cfg, b in sorted(by.items()):
        ins_rate = b["insuf"] / b["q"] if (judges and b["q"]) else None
        nc, nt = numby.get(cfg, [0, 0])
        print(f"   {cfg:13}: {b['q']:3} claims | evidence-insufficient "
              f"{(f'{ins_rate:.0%}' if ins_rate is not None else 'n/a')} | numeric {nc}/{nt} correct")
    cfgs = sorted(by)
    if judges and len(cfgs) == 2:
        a, bb = cfgs
        ra = by[a]["insuf"] / by[a]["q"]; rb = by[bb]["insuf"] / by[bb]["q"]
        gap = abs(ra - rb)
        print(f"   → insufficient-rate gap {a} vs {bb} = {gap:.0%}  "
              f"{'GO (clearly separates)' if gap >= 0.2 else 'WEAK (<20pp)'}")
    print()

    # (a) inter-judge agreement at scale
    if len(judges) >= 2:
        print("(a) inter-judge agreement (at scale, fixed rubric):")
        for x, y in combinations(judges, 2):
            print(f"   κ {names.get(x,x)}–{names.get(y,y)} = "
                  f"{_cohen([r.get(x,'') for r in qual], [r.get(y,'') for r in qual])}")
        if len(judges) >= 3:
            f = _fleiss([[r.get(c, '') for c in judges] for r in qual])
            print(f"   Fleiss κ (all {len(judges)}) = {f}")
    else:
        print("(a) need ≥2 judge columns for κ — run judge_p1 for more models")


if __name__ == "__main__":
    main()
