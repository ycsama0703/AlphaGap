"""Adversarial re-verification of the neff-loop GO (is it a bug / artifact / bad design?).

Four checks, all on the same panel:
  C1 METRIC SANITY (no LLM): K identical z-vecs -> indep_frac ~1/K (~0); K independent random -> ~1.
     Rules out a participation_ratio bug.
  C2 PROMPT ABLATION (the #1 suspicion): run the LLM loop in BOTH modes — "refine" (build on what works)
     AND "diverse" (explicitly maximize diversity, avoid repeating). If the collapse SURVIVES the diverse
     prompt, it is intrinsic, not manufactured by the convergence instruction.
  C3 EXPLOITATIVE BASELINE: hill-climbing (greedy local search, maximally exploitative — no population
     diversity). If even its explored set is MORE diverse than the LLM, the GP wasn't an unfair strawman.
  C4 FORMULA INSPECTION + multi-K: dump the LLM's actual distinct formulas (confirm real semantic clustering,
     not trivial restatements / a dedup bug) and check the LLM<GP gap holds across K in {30,60,90}.

Run:  LLM_PROVIDER=openrouter python -m experiments.neff_loop.verify
"""
from __future__ import annotations

import json
import numpy as np

from experiments.neff_loop.run import (
    Block, ev, canon, rand_tree, parse_formula, participation_ratio, gp_loop, random_stream,
    _mutate, FEATURES, PANEL_CACHE, PANEL_SEED)
from pipeline.rollout.trace import Run
import pandas as pd

SEEDS = 3
ROUNDS = 12
BATCH = 12


# ---------------------------------------------------------------- C1 metric sanity
def metric_sanity():
    rng = np.random.default_rng(0)
    base = rng.normal(size=3000).astype(np.float32)
    identical = [base.copy() for _ in range(60)]
    independent = [rng.normal(size=3000).astype(np.float32) for _ in range(60)]
    _, idf_same = participation_ratio(identical, 60, rng)
    _, idf_ind = participation_ratio(independent, 60, rng)
    print(f"C1 metric sanity: identical indep_frac={idf_same:.3f} (expect ~{1/60:.3f})  | "
          f"independent indep_frac={idf_ind:.3f} (expect ~1.0)")
    return idf_same < 0.05 and idf_ind > 0.8


# ---------------------------------------------------------------- C2 LLM loop (returns formulas too)
def llm_loop2(run, blk, seed, mode):
    feats = ", ".join(FEATURES)
    sys_p = ("You are mining cross-sectional equity alpha factors. Variables are standardized per month. "
             "Output factor formulas as single-line Python expressions using ONLY these variables: "
             f"{feats}; operators + - * / , unary minus, abs(); numeric constants. One per line, no commentary.")
    seen, vecs, formulas, history = set(), [], [], []
    for r in range(ROUNDS):
        run.progress(phase=f"{mode}", seed=seed, round=r, total=ROUNDS, unique=len(vecs))
        if mode == "refine":
            if not history:
                user = f"Propose {BATCH} DIVERSE alpha factor formulas."
            else:
                top = sorted(history, key=lambda x: -x[1])[:8]
                shown = "\n".join(f"  {f}   (rank-IC {ic:+.3f})" for f, ic in top)
                user = (f"Your best factors so far and their in-sample rank-IC:\n{shown}\n\n"
                        f"Propose {BATCH} NEW factor formulas to maximize rank-IC. Build on what works.")
        else:  # diverse: explicitly maximize diversity, avoid repeating
            prev = "\n".join(f"  {f}" for f in formulas[-20:])
            avoid = f"\nFormulas you already proposed (do NOT repeat or trivially restate these):\n{prev}" if prev else ""
            user = (f"Propose {BATCH} alpha factor formulas that are AS DIFFERENT FROM EACH OTHER as possible — "
                    f"maximize structural and economic diversity, cover distinct mechanisms.{avoid}")
        msgs = [{"role": "system", "content": sys_p}, {"role": "user", "content": user}]
        txt = run.chat(msgs, step=f"{mode}-s{seed}r{r}", max_tokens=700)
        if not txt.strip():
            txt = run.chat(msgs, step=f"{mode}-s{seed}r{r}-retry", max_tokens=700)
        for line in txt.splitlines():
            s = line.strip().strip("`").lstrip("0123456789.)-• ").strip()
            node = parse_formula(s)
            if node is None:
                continue
            c = canon(node); ic = blk.ic(ev(node, blk))
            history.append((s, ic))
            if c in seen:
                continue
            v = blk.zvec(ev(node, blk))
            if v is None:
                continue
            seen.add(c); vecs.append(v); formulas.append(s)
    return formulas, vecs


# ---------------------------------------------------------------- C3 hill-climb (max exploit)
def hill_climb(blk, steps, seed):
    rng = np.random.default_rng(7000 + seed)
    cur = max((rand_tree(rng) for _ in range(20)), key=lambda n: blk.ic(ev(n, blk)))
    cur_ic = blk.ic(ev(cur, blk))
    seen, vecs = set(), []
    def rec(node):
        c = canon(node)
        if c not in seen:
            v = blk.zvec(ev(node, blk))
            if v is not None:
                seen.add(c); vecs.append(v)
    rec(cur)
    for _ in range(steps):
        cand = _mutate(cur, rng); rec(cand)
        ic = blk.ic(ev(cand, blk))
        if ic > cur_ic:
            cur, cur_ic = cand, ic
    return vecs


# ---------------------------------------------------------------- main
def main():
    run = Run("neff-verify", params={"seeds": SEEDS, "rounds": ROUNDS, "batch": BATCH})
    print(f"run_id={run.run_id} provider={run.provider} model={run.model}\n")

    ok_metric = metric_sanity()
    src = PANEL_CACHE if PANEL_CACHE.exists() else PANEL_SEED
    P = pd.read_csv(src, dtype={"m": str}); blk = Block(P)
    print(f"panel: {len(P)} rows, {P['sym'].nunique()} syms\n")

    out = {"metric_ok": bool(ok_metric), "seeds": []}
    sample_formulas = None
    for seed in range(SEEDS):
        rng = np.random.default_rng(1000 + seed)
        f_ref, v_ref = llm_loop2(run, blk, seed, "refine")
        f_div, v_div = llm_loop2(run, blk, seed, "diverse")
        v_gp = gp_loop(blk, ROUNDS, pop=60, seed=seed)
        v_hill = hill_climb(blk, ROUNDS * 60, seed)
        v_rand = random_stream(blk, max(len(v_ref), 20), rng)
        if seed == 0:
            sample_formulas = {"refine": f_ref[:12], "diverse": f_div[:12]}
        streams = {"llm_refine": v_ref, "llm_diverse": v_div, "gp": v_gp, "hill": v_hill, "rand": v_rand}
        srow = {"seed": seed, "uniq": {k: len(v) for k, v in streams.items()}, "by_K": {}}
        for K in (30, 60, 90):
            if all(len(v) >= K for v in streams.values()):
                srow["by_K"][K] = {k: round(float(np.mean([participation_ratio(v, K, rng)[1]
                                   for _ in range(20)])), 4) for k, v in streams.items()}
        out["seeds"].append(srow)
        print(f"seed {seed} uniq={srow['uniq']}")
        for K, d in srow["by_K"].items():
            print(f"   K={K}: refine={d['llm_refine']:.3f} diverse={d['llm_diverse']:.3f} "
                  f"gp={d['gp']:.3f} hill={d['hill']:.3f} rand={d['rand']:.3f}")

    # verdicts per check (use K=60, the mid matched size)
    def at60(metric):
        vals = [s["by_K"].get(60, {}).get(metric) for s in out["seeds"] if 60 in s["by_K"]]
        return [v for v in vals if v is not None]
    ref, div, gp, hill = at60("llm_refine"), at60("llm_diverse"), at60("gp"), at60("hill")
    c2 = bool(div and gp and all(d < g for d, g in zip(div, gp)))       # diverse-LLM still < GP
    c3 = bool(ref and hill and all(r < h for r, h in zip(ref, hill)))   # LLM < even hill-climb
    print("\n=== ADVERSARIAL VERDICT (K=60) ===")
    print(f"  C1 metric sane                         : {ok_metric}")
    print(f"  C2 collapse survives DIVERSE prompt    : {c2}  (diverse {[round(x,3) for x in div]} vs gp {[round(x,3) for x in gp]})")
    print(f"  C3 LLM < exploitative hill-climb too   : {c3}  (refine {[round(x,3) for x in ref]} vs hill {[round(x,3) for x in hill]})")
    print(f"\n  sample LLM formulas (seed0):")
    for mode, fs in (sample_formulas or {}).items():
        print(f"    [{mode}] " + " | ".join(fs[:8]))
    robust = ok_metric and c2 and c3
    verdict = ("CONFIRMED — collapse is not a metric bug (C1), survives an explicit DIVERSITY prompt (C2 — so "
               "it's not the 'build on what works' instruction), and the LLM is more clustered than even a "
               "greedy hill-climb (C3 — GP wasn't an unfair strawman). The AI-specific mode collapse is real."
               if robust else
               "NOT FULLY CONFIRMED — at least one adversarial check failed; the GO may be an artifact. See which.")
    print("\nVERDICT:", verdict)
    run.finish(verdict=("confirmed" if robust else "suspect"), metrics=out)
    (run.dir / "verify.json").write_text(json.dumps({**out, "verdict": verdict,
                                          "sample_formulas": sample_formulas}, indent=2), encoding="utf-8")
    print("wrote", run.dir / "verify.json")


if __name__ == "__main__":
    main()
