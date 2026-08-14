#!/usr/bin/env python3
"""Generate frozen TAT-QA outputs for scorer-permission auditing.

Generation is intentionally separate from extraction and scoring. This script
stores raw provider responses plus a reproducibility manifest. Offline
extractors in :mod:`phase0.scorer_audit` create official-format predictions.

Examples::

    # No key and no model call: inspect the stratified pilot and request shape.
    python3 phase0/tatqa_run.py --n 200 --dry-run

    # Paid pilot. Reusing the run id safely resumes successful requests only.
    python3 phase0/tatqa_run.py --n 200 --run-id pilot_v1

    # Full dataset after the pilot gate passes.
    python3 phase0/tatqa_run.py --n 0 --run-id tatqa_full_v1
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase0.scorer_audit.adapters.tatqa import predictions_from_raw, write_official_predictions


OUT = ROOT / "phase0" / "tatqa_out"
DEV = OUT / "tatqa_dataset_dev.json"
DEV_URL = (
    "https://raw.githubusercontent.com/NExTplusplus/tat-qa/master/"
    "dataset_raw/tatqa_dataset_dev.json"
)
DEFAULT_MODEL = "deepseek/deepseek-v4-flash-0731"
SCALES = ["", "thousand", "million", "billion", "percent"]

ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": "Final answer values only. Use one string for a single answer and multiple strings for a multi-span answer. For arithmetic or count questions, each string must be a bare signed numeric value without explanation or scale words.",
        },
        "scale": {"type": "string", "enum": SCALES},
    },
    "required": ["answer", "scale"],
    "additionalProperties": False,
}

PROMPT_FREE = """Answer the question using the table and paragraphs below.

{ctx}

QUESTION: {q}

Answer concisely in one plain-prose sentence without showing your reasoning. The answer may be a number, a text span, or multiple text spans. If a numeric answer has a scale, state it naturally. Do not use JSON."""

PROMPT_JSON = """Answer the question using the table and paragraphs below.

{ctx}

QUESTION: {q}

Return the answer through the provided JSON schema. Put a single answer in a one-element list and a multi-span answer in a multi-element list. Each item must contain only the final answer value, never an explanation. For arithmetic/count questions, use a bare signed numeric string; put thousand/million/billion/percent only in the scale field. Use an empty scale when no scale applies."""


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_key() -> str:
    key = os.environ.get("OPENROUTER_API_KEY")
    if key:
        return key
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    sys.exit("找不到 OPENROUTER_API_KEY（环境变量或项目 .env 都没有）")


def load_dev(path: Path = DEV) -> list[dict[str, Any]]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"下载 dev set → {path}")
        response = requests.get(DEV_URL, timeout=60)
        response.raise_for_status()
        path.write_bytes(response.content)
    return json.loads(path.read_text(encoding="utf-8"))


def render(table: list[list[Any]], paragraphs: list[dict[str, Any]]) -> str:
    rows = ["\t".join(str(cell) for cell in row) for row in table]
    paras = "\n".join(
        f"[{paragraph['order']}] {paragraph['text']}"
        for paragraph in sorted(paragraphs, key=lambda value: value["order"])
    )
    return "TABLE:\n" + "\n".join(rows) + f"\n\nPARAGRAPHS:\n{paras}"


def flatten_dev(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for context in data:
        rendered = render(context["table"]["table"], context["paragraphs"])
        for question in context["questions"]:
            items.append(
                {
                    "uid": question["uid"],
                    "context": rendered,
                    "question": question["question"],
                    "answer_type": question.get("answer_type", ""),
                    "gold_scale": question.get("scale", ""),
                }
            )
    return items


def stratified_items(items: list[dict[str, Any]], n: int, seed: int) -> list[dict[str, Any]]:
    if n <= 0 or n >= len(items):
        return list(items)
    import random

    buckets: dict[tuple[str, bool], list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        buckets[(item["answer_type"], bool(item["gold_scale"]))].append(item)
    rng = random.Random(seed)
    for bucket in buckets.values():
        rng.shuffle(bucket)
    selected: list[dict[str, Any]] = []
    keys = sorted(buckets)
    while len(selected) < n:
        for key in keys:
            if buckets[key] and len(selected) < n:
                selected.append(buckets[key].pop())
    return selected


def build_request_body(
    model: str,
    prompt: str,
    condition: str,
    *,
    seed: int = 0,
    max_tokens: int = 2000,
    reasoning_effort: str = "high",
    provider: str = "",
    drop_parameters: tuple[str, ...] = (),
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "seed": seed,
        "max_tokens": max_tokens,
        "reasoning": {"effort": reasoning_effort, "exclude": True},
    }
    provider_config: dict[str, Any] = {"require_parameters": True}
    if provider:
        provider_config.update({"order": [provider], "allow_fallbacks": False})
    body["provider"] = provider_config
    if condition == "json":
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {
                "name": "tatqa_answer",
                "strict": True,
                "schema": ANSWER_SCHEMA,
            },
        }
    elif condition != "free":
        raise ValueError(f"unknown condition: {condition}")
    for parameter in drop_parameters:
        if parameter in {"model", "messages", "provider", "response_format"}:
            raise ValueError(f"cannot drop required experimental parameter: {parameter}")
        body.pop(parameter, None)
    return body


def call_openrouter(
    key: str,
    body: dict[str, Any],
    *,
    retries: int = 4,
    timeout: int = 120,
) -> tuple[str, str, dict[str, Any], str, dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "AlphaGap-ScorerAudit-TATQA",
    }
    last_error = ""
    response_meta: dict[str, Any] = {}
    last_usage: dict[str, Any] = {}
    for attempt in range(retries):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=body,
                headers=headers,
                timeout=timeout,
            )
            if not response.ok:
                try:
                    provider_error = response.json().get("error", response.text[:500])
                except (ValueError, AttributeError):
                    provider_error = response.text[:500]
                raise RuntimeError(f"HTTP {response.status_code}: {provider_error}")
            payload = response.json()
            choice = payload["choices"][0]
            content = choice["message"].get("content")
            last_usage = payload.get("usage", {})
            response_meta = {
                "response_id": payload.get("id"),
                "response_model": payload.get("model"),
                "provider": payload.get("provider"),
                "finish_reason": choice.get("finish_reason"),
                "native_finish_reason": choice.get("native_finish_reason"),
            }
            if content is None or not str(content).strip():
                if choice.get("finish_reason") == "length":
                    return (
                        "truncated",
                        "",
                        last_usage,
                        "empty content after exhausting max_tokens",
                        response_meta,
                    )
                raise RuntimeError(
                    f"empty content (finish_reason={choice.get('finish_reason')!r}, "
                    f"reasoning_chars={len(choice['message'].get('reasoning') or '')})"
                )
            return "ok", str(content), last_usage, "", response_meta
        except Exception as exc:  # provider/network failures are recorded for retry
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt + 1 < retries:
                time.sleep(2**attempt)
    return "error", "", last_usage, last_error, response_meta


def _existing_successes(path: Path, run_fingerprint: str) -> set[str]:
    completed: set[str] = set()
    if not path.exists():
        return completed
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            raw = str(record.get("raw") or "").strip()
            terminal_status = record.get("status") in {"ok", "truncated"}
            legacy_truncation = (
                record.get("status") == "error"
                and "empty content (finish_reason='length'" in record.get("error", "")
            )
            if (
                (terminal_status or legacy_truncation)
                and record.get("run_fingerprint") == run_fingerprint
                and ((raw and raw != "None") or record.get("status") != "ok")
            ):
                completed.add(record["uid"])
    return completed


def _manifest_config(
    *,
    model: str,
    data_path: Path,
    items: list[dict[str, Any]],
    n: int,
    seed: int,
    answer_types: list[str],
    max_tokens: int,
    reasoning_effort: str,
    provider: str,
    drop_parameters: list[str] | None = None,
) -> dict[str, Any]:
    config = {
        "model": model,
        "dataset_path": str(data_path.resolve()),
        "dataset_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "selected_uid_sha256": stable_hash([item["uid"] for item in items]),
        "selected_n": len(items),
        "requested_n": n,
        "sampling": "stratified_answer_type_x_scale_presence",
        "sampling_seed": seed,
        "max_tokens": max_tokens,
        "reasoning_effort": reasoning_effort,
        "provider_require_parameters": True,
        "pinned_provider": provider,
        "answer_types": sorted(answer_types),
        "prompt_free_sha256": stable_hash(PROMPT_FREE),
        "prompt_json_sha256": stable_hash(PROMPT_JSON),
        "answer_schema_sha256": stable_hash(ANSWER_SCHEMA),
    }
    if drop_parameters:
        config["dropped_unsupported_parameters"] = sorted(drop_parameters)
    return config


def _prepare_manifest(run_dir: Path, config: dict[str, Any]) -> str:
    fingerprint = stable_hash(config)
    path = run_dir / "manifest.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing.get("run_fingerprint") != fingerprint:
            sys.exit(
                f"run-id 已存在但配置不同：{path}\n"
                "请使用新的 --run-id，避免把不同模型/prompt/sample 混在一起。"
            )
        return fingerprint
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_fingerprint": fingerprint,
        **config,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return fingerprint


def _write_selection(run_dir: Path, items: list[dict[str, Any]], run_fingerprint: str) -> None:
    payload = {
        "run_fingerprint": run_fingerprint,
        "items": [
            {
                "uid": item["uid"],
                "answer_type": item["answer_type"],
                "gold_scale": item["gold_scale"],
            }
            for item in items
        ],
    }
    (run_dir / "selection.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_offline_extractions(run_dir: Path, condition: str, raw_path: Path) -> None:
    extractor_names = ("free_regex", "free_typed", "free_surface") if condition == "free" else ("schema",)
    for extractor_name in extractor_names:
        predictions, records = predictions_from_raw(raw_path, extractor_name)
        pred_path = run_dir / f"preds_{condition}_{extractor_name}.json"
        record_path = run_dir / f"extraction_{condition}_{extractor_name}.jsonl"
        write_official_predictions(predictions, pred_path)
        with record_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="分层题数，0=全部")
    parser.add_argument("--cond", nargs="+", default=["free", "json"], choices=["free", "json"])
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--run-id", default="pilot_v1")
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"], default="high")
    parser.add_argument("--provider", default="", help="固定 OpenRouter provider，例如 DeepInfra")
    parser.add_argument(
        "--drop-parameters",
        nargs="+",
        default=[],
        choices=["temperature", "seed"],
        help="删除模型不支持的采样参数；选择会写入 manifest",
    )
    parser.add_argument("--answer-types", nargs="+", default=[])
    parser.add_argument("--dev-path", type=Path, default=DEV)
    parser.add_argument("--dry-run", action="store_true", help="不读取 key、不写文件、不调用 API")
    args = parser.parse_args()

    data = load_dev(args.dev_path)
    items = flatten_dev(data)
    if args.answer_types:
        allowed = set(args.answer_types)
        items = [item for item in items if item["answer_type"] in allowed]
    selected = stratified_items(items, args.n, args.seed)
    if not selected:
        sys.exit("筛选后没有题目")

    config = _manifest_config(
        model=args.model,
        data_path=args.dev_path,
        items=selected,
        n=args.n,
        seed=args.seed,
        answer_types=args.answer_types,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort,
        provider=args.provider,
        drop_parameters=args.drop_parameters,
    )
    distribution = Counter((item["answer_type"], bool(item["gold_scale"])) for item in selected)
    print(f"模型 {args.model} | 分层题数 {len(selected)} | 条件 {args.cond}")
    print("样本分布:", dict(sorted(distribution.items())))

    if args.dry_run:
        example = selected[0]
        for condition in args.cond:
            template = PROMPT_FREE if condition == "free" else PROMPT_JSON
            body = build_request_body(
                args.model,
                template.format(ctx=example["context"], q=example["question"]),
                condition,
                seed=args.seed,
                max_tokens=args.max_tokens,
                reasoning_effort=args.reasoning_effort,
                provider=args.provider,
                drop_parameters=tuple(args.drop_parameters),
            )
            print(
                f"[{condition}] uid={example['uid']} request_keys={sorted(body)} "
                f"response_format={body.get('response_format', {}).get('type', 'none')}"
            )
        print("dry-run 完成：未读取 API key，未调用模型，未创建 run 目录。")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    run_dir = OUT / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_fingerprint = _prepare_manifest(run_dir, config)
    _write_selection(run_dir, selected, run_fingerprint)
    key = load_key()

    for condition in args.cond:
        raw_path = run_dir / f"raw_{condition}.jsonl"
        completed = _existing_successes(raw_path, run_fingerprint)
        todo = [item for item in selected if item["uid"] not in completed]
        print(f"[{condition}] 已成功 {len(completed)}；本次待跑 {len(todo)}")
        template = PROMPT_FREE if condition == "free" else PROMPT_JSON
        started = time.time()
        success_count = 0
        truncated_count = 0
        failure_count = 0
        with raw_path.open("a", encoding="utf-8") as handle, ThreadPoolExecutor(args.workers) as pool:
            futures = {}
            for item in todo:
                prompt = template.format(ctx=item["context"], q=item["question"])
                body = build_request_body(
                    args.model,
                    prompt,
                    condition,
                    seed=args.seed,
                    max_tokens=args.max_tokens,
                    reasoning_effort=args.reasoning_effort,
                    provider=args.provider,
                    drop_parameters=tuple(args.drop_parameters),
                )
                request_hash = stable_hash(body)
                future = pool.submit(call_openrouter, key, body)
                futures[future] = (item, request_hash)
            for index, future in enumerate(as_completed(futures), 1):
                item, request_hash = futures[future]
                status, raw, usage, error, response_meta = future.result()
                success_count += int(status == "ok")
                truncated_count += int(status == "truncated")
                failure_count += int(status == "error")
                record = {
                    "uid": item["uid"],
                    "cond": condition,
                    "status": status,
                    "error": error,
                    "raw": raw,
                    "usage": usage,
                    "response_meta": response_meta,
                    "model": args.model,
                    "request_hash": request_hash,
                    "run_fingerprint": run_fingerprint,
                    "answer_type": item["answer_type"],
                    "gold_scale": item["gold_scale"],
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                if index % 25 == 0 or index == len(todo):
                    print(
                        f"[{condition}] {index}/{len(todo)} ok={success_count} "
                        f"truncated={truncated_count} error={failure_count} "
                        f"{time.time() - started:.0f}s",
                        flush=True,
                    )
        _write_offline_extractions(run_dir, condition, raw_path)

    print(f"冻结输出与离线抽取写入：{run_dir}")
    print("下一步用 python -m phase0.scorer_audit.cli audit-tatqa 运行权限 replay。")


if __name__ == "__main__":
    main()
