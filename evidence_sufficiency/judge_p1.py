"""P1 panel judge — label evidence sufficiency of annotation_p1.csv claims, in CHUNKS (the set is too
big for one prompt). Uses the FIXED v2 rubric. Any LLMClient model = one blind judge → one suff_* column.

  python -m evidence_sufficiency.judge_p1 --provider openrouter --model openai/gpt-chat-latest --col suff_B --name GPT
  python -m evidence_sufficiency.judge_p1 --col suff_C --name DeepSeek-pro --model deepseek-v4-pro

Items are numbered by GLOBAL qualitative-claim index so chunk outputs map back directly.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path

from phase0.make_judge_sheet import RUBRIC

_OUT = Path(__file__).resolve().parent / "out"
_LINE = re.compile(r"(?m)^\s*(\d+)\s*[:\.\)]\s*(sufficient|insufficient|unknown)\b", re.I)
_SYS = "你是证据充分性审计员。严格按说明只输出 `序号: 标签` 行,不要解释。"
# rubric minus its trailing markdown header line
_RUBRIC_BODY = RUBRIC.rsplit("---", 1)[0].strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--col", required=True)
    ap.add_argument("--model", default="")
    ap.add_argument("--provider", default="")
    ap.add_argument("--name", default="")
    ap.add_argument("--chunk", type=int, default=50)
    args = ap.parse_args()

    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider
    if args.model:
        os.environ["LLM_MODEL_DEFAULT"] = args.model
        os.environ["LLM_MODEL_REASONING"] = args.model
    from pipeline.llm_client import LLMClient
    client = LLMClient()

    rows = list(csv.DictReader((_OUT / "annotation_p1.csv").open(encoding="utf-8")))
    qidx = [i for i, r in enumerate(rows) if r["kind"] == "qualitative"]
    qrows = [rows[i] for i in qidx]
    print(f"judging {len(qrows)} qualitative claims with {client._model_reasoning} in chunks of {args.chunk}")

    labels = {}
    for s in range(0, len(qrows), args.chunk):
        chunk = list(range(s, min(s + args.chunk, len(qrows))))
        items = "\n".join(f"{g}. 主张: {qrows[g]['claim_text']}\n   证据: {qrows[g]['agent_evidence_ref']}"
                          for g in chunk)
        user = f"{_RUBRIC_BODY}\n\n只判下面这些编号,逐条输出 `序号: 标签`:\n\n{items}"
        def ask(reasoning):
            return client.chat_text(system=_SYS, user=user, temperature=0.0, reasoning=reasoning, max_tokens=4000)
        out = ask(True)
        got = {int(m.group(1)): m.group(2).lower() for m in _LINE.finditer(out)}
        if len([g for g in got if g in chunk]) < len(chunk) * 0.8:
            out = ask(False)
            got = {int(m.group(1)): m.group(2).lower() for m in _LINE.finditer(out)}
        for g in chunk:
            if g in got:
                labels[g] = got[g]
        print(f"  chunk {s}-{chunk[-1]}: {sum(1 for g in chunk if g in got)}/{len(chunk)} parsed")

    if args.col not in rows[0]:
        for r in rows:
            r[args.col] = ""
    cols = list(rows[0].keys())
    if args.col not in cols:
        cols.append(args.col)
    n = 0
    for g, r in enumerate(qrows):
        if g in labels:
            r[args.col] = labels[g]; n += 1
    with (_OUT / "annotation_p1.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    jpath = _OUT / "judges_p1.json"
    reg = json.loads(jpath.read_text()) if jpath.exists() else {}
    reg[args.col] = args.name or client._model_reasoning
    jpath.write_text(json.dumps(reg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ingested {n}/{len(qrows)} into {args.col} ({reg[args.col]}). cost ${client.estimate_cost_usd():.4f}")


if __name__ == "__main__":
    main()
