"""Experiment ① — N_eff / mode-collapse, ITERATIVE loop version.

Question: does an ITERATIVE LLM factor-proposal loop (propose batch → see its own factors + their
in-sample rank-IC → propose the next batch, N rounds) span FEWER effective-independent dimensions
(lower participation-ratio N_eff) than a mechanical baseline (RANDOM search) over the SAME expression
space and SAME panel, at MATCHED distinct count? = AI-specific mode collapse.

The LLM side runs on the local GPU engine (free, fully traced via pipeline.rollout.trace.Run). The
mechanical baseline is uniform random formula sampling — the diversity upper bound. We match the distinct
count and compare the independent fraction (participation_ratio / K).

READ-RULE (the usual asymmetry): LLM indep_frac materially < baseline, consistent across seeds → GO
(mode collapse has a pulse). No difference → INCONCLUSIVE (not a kill).

Run on luyao4:   LLM_PROVIDER=local python -m experiments.neff_loop.run
Local dry-run:   LLM_PROVIDER=deepseek python -m experiments.neff_loop.run --smoke
"""
from __future__ import annotations

import argparse
import ast
import glob
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
FEATURES = ["mom", "rev1", "vol", "size", "maxret"]   # the char vocabulary both streams build on
PANEL_CACHE = Path(__file__).resolve().parent / "panel.csv"

# ----------------------------------------------------------------- findata (reuse the committed adapter)
def _findata_client():
    import sys
    sys.path.insert(0, str(ROOT / "phase0"))
    from findata_adapter import load_client   # returns the lumid-findata MODULE (module-level get_*)
    return load_client()


# ----------------------------------------------------------------- panel
UNIVERSE = ["AAPL","MSFT","NVDA","GOOGL","AMZN","META","TSLA","JPM","WMT","KO","JNJ","PG","XOM","NFLX",
            "AMD","DIS","INTC","CSCO","ORCL","IBM","BA","CAT","GE","MMM","HON","UNH","PFE","MRK","ABBV",
            "BAC","WFC","GS","MS","V","MA","HD","LOW","NKE","SBUX","MCD","COST","PEP","T","VZ","CMCSA",
            "ADBE","CRM","QCOM","TXN","AVGO","MU","C","AXP","BLK","SCHW","CVX","COP","SLB","XLF","SPY"]


def build_panel(client, start="2016-01-01") -> pd.DataFrame:
    rows = []
    for sym in UNIVERSE:
        try:
            r = None
            for attempt in range(4):                  # retry/backoff: findata rate-limits (429)
                try:
                    r = client.get_ohlc(sym, "1d", start, "")
                except Exception:
                    r = None
                if isinstance(r, dict) and r.get("bars"):
                    break
                time.sleep(2.0 * (attempt + 1))
            bars = (r or {}).get("bars") if isinstance(r, dict) else None
            if not bars:
                continue
            df = pd.DataFrame(bars)            # bars: {ts, open, high, low, close, volume}
            if "ts" not in df or "close" not in df:
                continue
            df["d"] = pd.to_datetime(df["ts"]); df = df.sort_values("d")
            df["ret"] = df["close"].pct_change()
            df["dv"] = df["close"] * df.get("volume", 0)
            df["m"] = df["d"].dt.to_period("M").astype(str)
            g = df.groupby("m")
            mc = g["close"].last()
            feat = pd.DataFrame({
                "rev1": mc.pct_change(1),
                "mom": mc.pct_change(12).shift(1),       # ~12-1 momentum (monthly approx)
                "vol": g["ret"].std() * np.sqrt(21),
                "size": np.log(g["dv"].mean() + 1.0),
                "maxret": g["ret"].max(),
            })
            feat["fwd"] = mc.pct_change(1).shift(-1)      # next-month return
            feat["sym"] = sym; feat = feat.reset_index()
            rows.append(feat)
            time.sleep(0.4)                           # throttle: be polite to shared findata
        except Exception as e:
            print(f"  panel: {sym} skipped ({str(e)[:60]})")
            continue
    if not rows:
        raise SystemExit("build_panel: no usable symbols (findata down?)")
    P = pd.concat(rows, ignore_index=True).dropna(subset=["fwd"])
    # z-score each feature within month
    for c in FEATURES:
        P[c] = P.groupby("m")[c].transform(lambda s: (s - s.mean()) / (s.std() or 1.0))
    P[FEATURES] = P[FEATURES].fillna(0.0)
    return P


# ----------------------------------------------------------------- expression eval (cross-sectional IC)
BIN = {"add": np.add, "sub": np.subtract, "mul": np.multiply,
       "div": lambda a, b: np.divide(a, b, out=np.zeros_like(a), where=np.abs(b) > 1e-6)}
UN = {"neg": np.negative, "abs": np.abs}


class Block:
    def __init__(self, P):
        self.cols = {f: P[f].to_numpy(float) for f in FEATURES}
        codes, _ = pd.factorize(P["m"].to_numpy()); self.codes = codes
        self.ng = codes.max() + 1
        self.counts = np.bincount(codes, minlength=self.ng).astype(float)
        self.n = len(P)
        self.y = self._dem(P["fwd"].to_numpy(float)); self.yn = np.linalg.norm(self.y) + 1e-12

    def _dem(self, v):
        means = np.bincount(self.codes, weights=v, minlength=self.ng) / self.counts
        return v - means[self.codes]

    def ic(self, sig):
        s = self._dem(np.nan_to_num(sig)); sn = np.linalg.norm(s)
        return 0.0 if sn < 1e-12 else float((s @ self.y) / (sn * self.yn))

    def zvec(self, sig):
        s = self._dem(np.nan_to_num(sig)); sd = s.std()
        return None if sd < 1e-9 else (s / sd).astype(np.float32)


def ev(node, blk):
    t = node[0]
    if t == "f":
        return blk.cols[node[1]]
    if t == "c":
        return np.full(blk.n, node[1])
    if t == "u":
        return UN[node[1]](ev(node[2], blk))
    return BIN[node[1]](ev(node[2], blk), ev(node[3], blk))


def canon(node):
    t = node[0]
    if t == "f": return node[1]
    if t == "c": return f"c{round(node[1],2)}"
    if t == "u": return f"({node[1]} {canon(node[2])})"
    return f"({node[1]} {canon(node[2])} {canon(node[3])})"


def rand_tree(rng, depth=0, max_depth=4):
    if depth >= max_depth or (depth > 0 and rng.random() < 0.35):
        if rng.random() < 0.85:
            return ("f", FEATURES[rng.integers(len(FEATURES))])
        return ("c", float(round(rng.normal(), 2)))
    if rng.random() < 0.25:
        return ("u", list(UN)[rng.integers(len(UN))], rand_tree(rng, depth + 1, max_depth))
    op = list(BIN)[rng.integers(len(BIN))]
    return ("b", op, rand_tree(rng, depth + 1, max_depth), rand_tree(rng, depth + 1, max_depth))


_BINOP = {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div"}


def parse_formula(expr):
    try:
        tree = ast.parse(expr.strip(), mode="eval").body
    except Exception:
        return None

    def rec(n):
        if isinstance(n, ast.Name):
            if n.id not in FEATURES: raise ValueError("unknown feat")
            return ("f", n.id)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return ("c", float(n.value))
        if isinstance(n, ast.UnaryOp):
            if isinstance(n.op, ast.USub): return ("u", "neg", rec(n.operand))
            if isinstance(n.op, ast.UAdd): return rec(n.operand)
            raise ValueError("bad unary")
        if isinstance(n, ast.BinOp) and type(n.op) in _BINOP:
            return ("b", _BINOP[type(n.op)], rec(n.left), rec(n.right))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "abs" and len(n.args) == 1:
            return ("u", "abs", rec(n.args[0]))
        raise ValueError("unsupported")
    try:
        return rec(tree)
    except (ValueError, RecursionError):
        return None


# ----------------------------------------------------------------- N_eff
def participation_ratio(vecs, K, rng):
    if len(vecs) > K:
        vecs = [vecs[i] for i in rng.choice(len(vecs), K, replace=False)]
    X = np.vstack(vecs); C = (X @ X.T) / X.shape[1]
    e = np.clip(np.linalg.eigvalsh(C), 0, None); s = e.sum()
    pr = float(s * s / (np.square(e).sum() + 1e-12))
    return pr, pr / len(vecs)


# ----------------------------------------------------------------- the two streams
def random_stream(blk, n_unique, rng):
    seen, vecs = set(), []
    tries = 0
    while len(vecs) < n_unique and tries < n_unique * 50:
        tries += 1
        node = rand_tree(rng)
        c = canon(node)
        if c in seen: continue
        v = blk.zvec(ev(node, blk))
        if v is None: continue
        seen.add(c); vecs.append(v)
    return vecs


def llm_loop(run, blk, rounds, batch, seed):
    """Iterative: each round the LLM sees its prior factors + their in-sample rank-IC and proposes a
    new batch aimed at maximizing IC. We collect all UNIQUE valid formulas across the trajectory."""
    feats = ", ".join(FEATURES)
    sys_p = ("You are mining cross-sectional equity alpha factors. Each variable is standardized "
             "cross-sectionally per month. Propose factor formulas as single-line Python expressions "
             f"using ONLY these variables: {feats}; operators + - * / , unary minus, abs(); numeric "
             "constants. One formula per line, no commentary.")
    seen, vecs, history = set(), [], []
    for r in range(rounds):
        run.progress(phase="llm_loop", seed=seed, round=r, total=rounds, unique=len(vecs))
        if not history:
            user = f"Propose {batch} DIVERSE alpha factor formulas."
        else:
            top = sorted(history, key=lambda x: -x[1])[:8]
            shown = "\n".join(f"  {f}   (rank-IC {ic:+.3f})" for f, ic in top)
            user = (f"Your best factors so far and their in-sample rank-IC:\n{shown}\n\n"
                    f"Propose {batch} NEW factor formulas to maximize rank-IC. Build on what works.")
        txt = run.chat([{"role": "system", "content": sys_p}, {"role": "user", "content": user}],
                       step=f"s{seed}r{r}", max_tokens=700)
        for line in txt.splitlines():
            s = line.strip().strip("`").lstrip("0123456789.)-• ").strip()
            node = parse_formula(s)
            if node is None: continue
            c = canon(node)
            ic = blk.ic(ev(node, blk))
            history.append((s, ic))                  # history can repeat (that's the point of a loop)
            if c in seen: continue
            v = blk.zvec(ev(node, blk))
            if v is None: continue
            seen.add(c); vecs.append(v)
    return vecs


# ----------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--rounds", type=int, default=12)
    ap.add_argument("--batch", type=int, default=12)
    args = ap.parse_args()
    if args.smoke:
        args.seeds, args.rounds, args.batch = 1, 4, 8

    from pipeline.rollout.trace import Run
    run = Run("neff-loop", params=vars(args))
    print(f"run_id={run.run_id} provider={run.provider} model={run.model}")

    # panel (cache so re-runs are instant)
    if PANEL_CACHE.exists():
        P = pd.read_csv(PANEL_CACHE, dtype={"m": str})
    else:
        run.progress(phase="build_panel")
        P = build_panel(_findata_client())
        try: P.to_csv(PANEL_CACHE, index=False)
        except Exception: pass
    blk = Block(P)
    print(f"panel: {len(P)} rows, {P['sym'].nunique()} syms, {P['m'].nunique()} months")

    rows = []
    for seed in range(args.seeds):
        rng = np.random.default_rng(1000 + seed)
        llm_vecs = llm_loop(run, blk, args.rounds, args.batch, seed)
        rand_vecs = random_stream(blk, max(len(llm_vecs), 20), rng)
        if len(llm_vecs) < 5 or len(rand_vecs) < 5:
            rows.append({"seed": seed, "error": "too few", "llm": len(llm_vecs), "rand": len(rand_vecs)})
            continue
        K = min(len(llm_vecs), len(rand_vecs))
        llm_if = float(np.mean([participation_ratio(llm_vecs, K, rng)[1] for _ in range(20)]))
        rnd_if = float(np.mean([participation_ratio(rand_vecs, K, rng)[1] for _ in range(20)]))
        rows.append({"seed": seed, "K": K, "llm_unique": len(llm_vecs), "rand_unique": len(rand_vecs),
                     "llm_indep_frac": round(llm_if, 4), "rand_indep_frac": round(rnd_if, 4),
                     "gap_rand_minus_llm": round(rnd_if - llm_if, 4)})
        print(f"  seed {seed}: K={K} llm_indep={llm_if:.3f} rand_indep={rnd_if:.3f} "
              f"gap={rnd_if-llm_if:+.3f} (llm_uniq={len(llm_vecs)})")

    ok = [r for r in rows if "error" not in r]
    gaps = [r["gap_rand_minus_llm"] for r in ok]
    mean_gap = float(np.mean(gaps)) if gaps else 0.0
    consistent = bool(ok) and all(g > 0 for g in gaps)
    margin = 0.05
    if not ok:
        verdict = "NO USABLE ROWS — fix proposer/parse."
    elif consistent and mean_gap >= margin:
        verdict = (f"GO — the iterative LLM loop spans materially FEWER independent dimensions than random "
                   f"search at matched distinct count (mean gap +{mean_gap:.2f}, consistent) → AI-specific "
                   f"mode collapse has a pulse in the loop.")
    else:
        verdict = (f"INCONCLUSIVE (not a kill) — mean(rand_indep - llm_indep)={mean_gap:+.2f}, consistent="
                   f"{consistent}. The LLM loop is not measurably more clustered than random here. Caveat: "
                   f"local {run.model} is one model; weaker/stronger models may differ.")
    print("\nVERDICT:", verdict)
    m = run.finish(verdict=("go" if (consistent and mean_gap >= margin) else "inconclusive"),
                   metrics={"mean_gap": mean_gap, "rows": rows})
    print(f"calls={m['n_calls']} elapsed={m['elapsed_s']}s -> {run.dir}")
    (run.dir / "result.json").write_text(json.dumps({"rows": rows, "mean_gap": mean_gap,
                                                      "verdict": verdict}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
