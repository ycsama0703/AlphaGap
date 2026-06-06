"""P1 (minimal) — scale the evidence-sufficiency probe: ~150 tasks × 2 agent configs.

Reuses the phase0 harness. Two agent configs are the "systems under test":
  - full          : all tools incl. transcript search → can ground driver claims
  - numeric_only  : data tools but NO documents → gets numbers right, can't evidence drivers
The benchmark's job: show it separates them on evidence sufficiency (not just final accuracy).

  python -m evidence_sufficiency.run_p1 --build          # build tasks then run both configs
  python -m evidence_sufficiency.run_p1 --limit 5        # quick smoke test
  python -m evidence_sufficiency.run_p1 --configs full   # run one config

Outputs evidence_sufficiency/out/: tasks_p1.jsonl, results_p1.jsonl, annotation_p1.csv (claims tagged
by agent_config, suff_* empty for the panel).
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
from pathlib import Path

from phase0.agent import CONFIGS, run_agent
from phase0.build_tasks import build as build_tasks
from phase0.run_phase0 import _grade_numeric

log = logging.getLogger("p1")
_DIR = Path(__file__).resolve().parent
_OUT = _DIR / "out"

# ~65 liquid US large/mid caps across sectors (all have earnings-call transcripts in findata)
SYMBOLS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "ORCL", "CRM",
    "ADBE", "AMD", "INTC", "CSCO", "QCOM", "TXN", "IBM", "NOW", "INTU", "NFLX",
    "JPM", "BAC", "WFC", "GS", "MS", "C", "BLK", "AXP", "V", "MA",
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "WMT", "COST", "PG", "KO", "PEP", "MCD", "NKE", "SBUX", "HD", "LOW", "TGT", "DIS",
    "XOM", "CVX", "CAT", "BA", "GE", "HON", "UPS", "LMT", "CMCSA", "T", "VZ",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--build", action="store_true", help="(re)build the P1 task set first")
    ap.add_argument("--per-symbol", type=int, default=3)
    ap.add_argument("--configs", default="full,numeric_only")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--model", default="")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    _OUT.mkdir(exist_ok=True)
    tasks_path = _OUT / "tasks_p1.jsonl"

    if args.build or not tasks_path.exists():
        log.info("building P1 tasks (%d symbols × %d)...", len(SYMBOLS), args.per_symbol)
        build_tasks(symbols=SYMBOLS, per_symbol=args.per_symbol, out=tasks_path)

    tasks = [json.loads(l) for l in tasks_path.read_text().splitlines() if l.strip()]
    if args.limit:
        tasks = tasks[:args.limit]
    configs = [c.strip() for c in args.configs.split(",") if c.strip()]
    log.info("running %d tasks × configs %s", len(tasks), configs)

    import os
    if args.model:
        os.environ["LLM_MODEL_DEFAULT"] = args.model
    from pipeline.llm_client import LLMClient
    client = LLMClient()

    results, anno = [], []
    for cfg in configs:
        allowed = CONFIGS[cfg]
        ncorr = ntot = 0
        for i, t in enumerate(tasks, 1):
            r = run_agent(t, client=client, allowed_tools=allowed)
            grade = _grade_numeric(t, r.get("numeric_answers", {}) or {})
            results.append({**t, "agent_config": cfg, "agent": r, "numeric_grade": grade})
            if grade.get("numeric_correct") is not None:
                ntot += 1; ncorr += int(grade["numeric_correct"] is True)
            for ci, cl in enumerate(r.get("claims", []) or []):
                anno.append({
                    "task_id": t["task_id"], "agent_config": cfg, "symbol": t["symbol"], "as_of": t["as_of"],
                    "claim_idx": ci, "kind": cl.get("kind", ""), "claim_text": cl.get("text", ""),
                    "agent_evidence_ref": cl.get("evidence_ref", ""),
                    "auto_numeric_correct": grade.get("numeric_correct"), "n_tool_calls": r.get("n_tool_calls"),
                    "suff_A": "", "suff_B": "", "suff_C": "",
                })
            if i % 25 == 0:
                log.info("  [%s] %d/%d done", cfg, i, len(tasks))
        nq = sum(1 for a in anno if a["agent_config"] == cfg and a["kind"] == "qualitative")
        log.info("config %s: numeric %d/%d correct | %d qualitative claims | cost so far $%.4f",
                 cfg, ncorr, ntot, nq, client.estimate_cost_usd())

    (_OUT / "results_p1.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8")
    cols = ["task_id", "agent_config", "symbol", "as_of", "claim_idx", "kind", "claim_text",
            "agent_evidence_ref", "auto_numeric_correct", "n_tool_calls", "suff_A", "suff_B", "suff_C"]
    with (_OUT / "annotation_p1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(anno)
    print(f"\n=== {len(tasks)} tasks × {len(configs)} configs · {len(anno)} claims · ${client.estimate_cost_usd():.4f} ===")
    print(f"-> {_OUT/'results_p1.jsonl'}\n-> {_OUT/'annotation_p1.csv'}")


if __name__ == "__main__":
    main()
