"""Run a model (via the AlphaGap LLMClient) as a BLIND judge over judge_sheet.md → write a labels file.

A fresh API call is stateless, so the model only sees the self-contained sheet — a legit independent judge.

  python -m phase0.run_judge_api --col suff_C                     # default model (deepseek), thinking on
  python -m phase0.run_judge_api --model deepseek-v4-pro --col suff_C
  python -m phase0.run_judge_api --provider openrouter --model openai/gpt-chat-latest --col suff_B

Writes phase0/out/<col>_api_labels.txt and ingests into that column. Then: python -m phase0.stats
"""
from __future__ import annotations

import argparse
import os
import re
from pathlib import Path

_OUT = Path(__file__).resolve().parent / "out"
_LINE = re.compile(r"(?m)^\s*(\d+)\s*[:\.\)]\s*(sufficient|insufficient|unknown)\b", re.I)
_SYS = "你是证据充分性审计员。严格按用户给出的说明完成判定,只输出 60 行 `序号: 标签`,不要解释。"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--col", default="suff_C", choices=["suff_A", "suff_B", "suff_C"])
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", default="")
    args = ap.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL_DEFAULT"] = args.model
        os.environ["LLM_MODEL_REASONING"] = args.model

    from pipeline.llm_client import LLMClient
    client = LLMClient()
    sheet = (_OUT / "judge_sheet.md").read_text(encoding="utf-8")

    def _ask(reasoning):
        return client.chat_text(system=_SYS, user=sheet, temperature=0.0,
                                reasoning=reasoning, max_tokens=3000)

    print(f"judging with provider={client.provider} model={client._model_reasoning} (thinking on)...")
    out = _ask(True)
    labels = {int(m.group(1)): m.group(2).lower() for m in _LINE.finditer(out)}
    if len(labels) < 55:   # thinking can exhaust the token budget → empty content; retry plain
        print(f"  only {len(labels)} parsed with thinking — retrying without thinking...")
        out = _ask(False)
        labels = {int(m.group(1)): m.group(2).lower() for m in _LINE.finditer(out)}
    lf = _OUT / f"{args.col}_api_labels.txt"
    lf.write_text("\n".join(f"{i}: {labels[i]}" for i in sorted(labels)), encoding="utf-8")
    print(f"parsed {len(labels)} labels (expected 60) -> {lf}  | cost ${client.estimate_cost_usd():.4f}")
    if len(labels) < 55:
        print("WARNING: <55 labels parsed — check raw output below:\n", out[:800]); return

    # ingest
    import csv
    rows = list(csv.DictReader((_OUT / "annotation.csv").open(encoding="utf-8")))
    qi, n = 0, 0
    for r in rows:
        if r["kind"] == "qualitative":
            if qi in labels:
                r[args.col] = labels[qi]; n += 1
            qi += 1
    cols = list(rows[0].keys())
    with (_OUT / "annotation.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"ingested {n} labels into {args.col}. Now: python -m phase0.stats")


if __name__ == "__main__":
    main()
