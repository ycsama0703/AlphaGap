"""Step 1 runner: run the agent over the task set, auto-grade the numeric part, export an annotation sheet.

  python -m phase0.run_phase0                 # all tasks
  python -m phase0.run_phase0 --limit 8       # quick subset
  python -m phase0.run_phase0 --model deepseek-v4-flash

Outputs (phase0/out/):
  results.jsonl     — full agent output + auto numeric grade per task
  annotation.csv    — ONE ROW PER CLAIM for humans to label evidence sufficiency:
                      fill `suff_A` and `suff_B` with one of {sufficient, insufficient, unknown}.
The numeric correctness is graded automatically (ground truth from findata); only sufficiency is manual.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from .agent import run_agent

log = logging.getLogger("phase0.run")
_DIR = Path(__file__).resolve().parent
_OUT = _DIR / "out"
NUM_TOL_PP = 2.0   # ± percentage points to count a numeric answer as correct


def _close(a, b, tol=NUM_TOL_PP):
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return None


def _grade_numeric(task: dict, na: dict) -> dict:
    gt = task.get("ground_truth", {}) or {}
    out = {}
    for k in ("revenue_yoy_pct", "eps_surprise_pct"):
        if gt.get(k) is None:
            out[k] = None  # no ground truth → not gradable
        else:
            out[k] = _close(na.get(k), gt.get(k))
    graded = [v for v in out.values() if v is not None]
    out["numeric_correct"] = (all(graded) if graded else None)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="run only first N tasks")
    ap.add_argument("--model", default="", help="override LLM_MODEL_DEFAULT for the agent")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    import os
    if args.model:
        os.environ["LLM_MODEL_DEFAULT"] = args.model
    from pipeline.llm_client import LLMClient
    client = LLMClient()

    tasks = [json.loads(l) for l in (_DIR / "seed_tasks.jsonl").read_text().splitlines() if l.strip()]
    if args.limit:
        tasks = tasks[:args.limit]
    log.info("running %d tasks on model=%s", len(tasks), client._model_default)

    _OUT.mkdir(exist_ok=True)
    results, anno_rows = [], []
    for i, t in enumerate(tasks, 1):
        r = run_agent(t, client=client)
        grade = _grade_numeric(t, r.get("numeric_answers", {}) or {})
        rec = {**t, "agent": r, "numeric_grade": grade}
        results.append(rec)
        for ci, cl in enumerate(r.get("claims", []) or []):
            anno_rows.append({
                "task_id": t["task_id"], "symbol": t["symbol"], "as_of": t["as_of"],
                "claim_idx": ci, "kind": cl.get("kind", ""),
                "claim_text": cl.get("text", ""), "agent_evidence_ref": cl.get("evidence_ref", ""),
                "auto_numeric_correct": grade.get("numeric_correct"),
                "n_tool_calls": r.get("n_tool_calls"),
                "suff_A": "", "suff_B": "",   # ← humans fill: sufficient | insufficient | unknown
            })
        log.info("[%d/%d] %s numeric=%s claims=%d tools=%d",
                 i, len(tasks), t["task_id"], grade.get("numeric_correct"),
                 len(r.get("claims", []) or []), r.get("n_tool_calls"))

    (_OUT / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8")
    cols = ["task_id", "symbol", "as_of", "claim_idx", "kind", "claim_text",
            "agent_evidence_ref", "auto_numeric_correct", "n_tool_calls", "suff_A", "suff_B"]
    with (_OUT / "annotation.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(anno_rows)

    n_num = sum(1 for r in results if r["numeric_grade"].get("numeric_correct") is True)
    n_gradable = sum(1 for r in results if r["numeric_grade"].get("numeric_correct") is not None)
    print(f"\n=== {len(results)} tasks · {len(anno_rows)} claims ===")
    print(f"auto numeric correct: {n_num}/{n_gradable} gradable")
    print(f"est API cost: ${client.estimate_cost_usd():.4f}  (tokens {client.total_tokens})")
    print(f"-> {_OUT/'results.jsonl'}\n-> {_OUT/'annotation.csv'}  (fill suff_A / suff_B, then run stats)")


if __name__ == "__main__":
    main()
