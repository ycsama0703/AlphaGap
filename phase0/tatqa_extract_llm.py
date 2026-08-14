#!/usr/bin/env python3
"""Replay a semantic LLM extractor over frozen free-form TAT-QA outputs."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase0.scorer_audit.adapters.tatqa import predictions_from_raw, write_official_predictions
from phase0.tatqa_run import (
    DEFAULT_MODEL,
    build_request_body,
    call_openrouter,
    load_key,
    stable_hash,
)


EXTRACT_PROMPT = """You are an answer extractor, not a question-solving system.

QUESTION:
{question}

FROZEN MODEL RESPONSE:
{response}

Extract only the final answer asserted by the frozen response. Do not recompute the answer and do not correct factual or arithmetic mistakes. You may interpret ordinary answer language: convert count words such as "three" to "3"; when the response explicitly states a decrease as the answer to an increase/(decrease) question, preserve the negative sign; separate thousand/million/billion/percent into the scale field. Ignore operands, years, thresholds, and explanatory numbers that are not the asserted final answer.

{output_instruction}"""

JSON_OUTPUT_INSTRUCTION = "Return only through the provided JSON schema."
LABELED_OUTPUT_INSTRUCTION = """Return exactly two lines with no explanation:
ANSWER: <single value or a bracketed list of values>
SCALE: <none, thousand, million, billion, or percent>"""


def _latest(path: Path) -> dict[str, dict]:
    records: dict[str, dict] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                records[record["uid"]] = record
    return records


def _question_map(gold_path: Path) -> dict[str, str]:
    data = json.loads(gold_path.read_text(encoding="utf-8"))
    return {
        question["uid"]: question["question"]
        for context in data
        for question in context["questions"]
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default="DeepInfra")
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--max-tokens", type=int, default=800)
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"], default="low")
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--tag", default="llm", help="output label, e.g. llm_low2000")
    parser.add_argument("--output-mode", choices=["json", "labeled"], default="json")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]+", args.tag):
        raise SystemExit("--tag must contain only lowercase letters, digits, and underscores")

    selection = json.loads((args.run_dir / "selection.json").read_text(encoding="utf-8"))
    selected_uids = [item["uid"] for item in selection["items"]]
    source = _latest(args.run_dir / "raw_free.jsonl")
    questions = _question_map(args.gold)
    missing = [uid for uid in selected_uids if source.get(uid, {}).get("status") != "ok"]
    if missing:
        raise SystemExit(f"free generation missing/non-ok for {len(missing)} selected uids")

    config = {
        "source_run_fingerprint": selection["run_fingerprint"],
        "source_raw_sha256": stable_hash({uid: source[uid]["request_hash"] for uid in selected_uids}),
        "model": args.model,
        "provider": args.provider,
        "max_tokens": args.max_tokens,
        "reasoning_effort": args.reasoning_effort,
        "seed": args.seed,
        "prompt_sha256": stable_hash(
            EXTRACT_PROMPT
            + (JSON_OUTPUT_INSTRUCTION if args.output_mode == "json" else LABELED_OUTPUT_INSTRUCTION)
        ),
        "output_mode": args.output_mode,
    }
    fingerprint = stable_hash(config)
    manifest_path = args.run_dir / f"llm_extractor_manifest_{args.tag}.json"
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("fingerprint") != fingerprint:
            raise SystemExit("LLM extractor manifest differs; choose a new output run directory")
    else:
        manifest_path.write_text(
            json.dumps(
                {"created_at": datetime.now(timezone.utc).isoformat(), "fingerprint": fingerprint, **config},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    raw_path = args.run_dir / f"raw_extractor_{args.tag}.jsonl"
    completed: set[str] = set()
    if raw_path.exists():
        for uid, record in _latest(raw_path).items():
            if record.get("extractor_fingerprint") == fingerprint and record.get("status") in {
                "ok",
                "truncated",
            }:
                completed.add(uid)
    todo = [uid for uid in selected_uids if uid not in completed]
    print(f"LLM extractor completed={len(completed)} todo={len(todo)}")
    key = load_key()
    started = time.time()
    counts: Counter[str] = Counter()
    with raw_path.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(args.workers) as pool:
        futures = {}
        for uid in todo:
            output_instruction = (
                JSON_OUTPUT_INSTRUCTION if args.output_mode == "json" else LABELED_OUTPUT_INSTRUCTION
            )
            prompt = EXTRACT_PROMPT.format(
                question=questions[uid],
                response=source[uid]["raw"],
                output_instruction=output_instruction,
            )
            body = build_request_body(
                args.model,
                prompt,
                "json" if args.output_mode == "json" else "free",
                seed=args.seed,
                max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort,
                provider=args.provider,
            )
            futures[pool.submit(call_openrouter, key, body)] = (uid, stable_hash(body))
        for index, future in enumerate(as_completed(futures), 1):
            uid, request_hash = futures[future]
            status, raw, usage, error, response_meta = future.result()
            counts[status] += 1
            record = {
                "uid": uid,
                "cond": f"free_{args.tag}_extractor",
                "status": status,
                "error": error,
                "raw": raw,
                "usage": usage,
                "response_meta": response_meta,
                "model": args.model,
                "request_hash": request_hash,
                "extractor_fingerprint": fingerprint,
                "source_request_hash": source[uid]["request_hash"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            if index % 25 == 0 or index == len(todo):
                print(f"{index}/{len(todo)} {dict(counts)} {time.time() - started:.0f}s", flush=True)

    extractor_name = "schema" if args.output_mode == "json" else "labeled"
    predictions, records = predictions_from_raw(raw_path, extractor_name)
    prediction_path = args.run_dir / f"preds_free_{args.tag}.json"
    extraction_path = args.run_dir / f"extraction_free_{args.tag}.jsonl"
    write_official_predictions(predictions, prediction_path)
    with extraction_path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    print(f"wrote {prediction_path}")


if __name__ == "__main__":
    main()
