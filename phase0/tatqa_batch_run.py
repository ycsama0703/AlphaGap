#!/usr/bin/env python3
"""Run the frozen TAT-QA generation experiment through OpenRouter Batch API.

The scientific design is shared with :mod:`phase0.tatqa_run`; only the
transport changes from synchronous chat completions to an asynchronous batch.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase0.openrouter_batch import (
    TERMINAL_STATUSES,
    base_model_slug,
    build_batch_payload,
    completion_from_batch_result,
    get_batch,
    new_attempt_record,
    poll_batch,
    submit_batch,
    write_json_atomic,
)
from phase0.tatqa_run import (
    ANSWER_SCHEMA,
    DEV,
    OUT,
    PROMPT_FREE,
    PROMPT_JSON,
    _existing_successes,
    _prepare_manifest,
    _write_offline_extractions,
    _write_selection,
    build_request_body,
    flatten_dev,
    load_dev,
    load_key,
    stable_hash,
    stratified_items,
)


def manifest_config(
    *,
    requested_model: str,
    data_path: Path,
    items: list[dict[str, Any]],
    n: int,
    seed: int,
    answer_types: list[str],
    max_tokens: int,
    reasoning_effort: str,
    provider: str,
    drop_parameters: list[str],
) -> dict[str, Any]:
    return {
        "model": base_model_slug(requested_model),
        "requested_model_variant": requested_model,
        "transport": "openrouter_batch_beta",
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
        "dropped_unsupported_parameters": sorted(drop_parameters),
        "answer_types": sorted(answer_types),
        "prompt_free_sha256": stable_hash(PROMPT_FREE),
        "prompt_json_sha256": stable_hash(PROMPT_JSON),
        "answer_schema_sha256": stable_hash(ANSWER_SCHEMA),
    }


def _load_journal(path: Path, run_fingerprint: str) -> dict[str, Any]:
    if not path.exists():
        return {"run_fingerprint": run_fingerprint, "attempts": []}
    journal = json.loads(path.read_text(encoding="utf-8"))
    if journal.get("run_fingerprint") != run_fingerprint:
        sys.exit(f"batch journal fingerprint mismatch: {path}")
    return journal


def _active_attempt(journal: dict[str, Any]) -> dict[str, Any] | None:
    for attempt in reversed(journal["attempts"]):
        if attempt.get("status") not in TERMINAL_STATUSES:
            return attempt
    return None


def _update_attempt(
    journal_path: Path,
    journal: dict[str, Any],
    attempt: dict[str, Any],
    batch: dict[str, Any],
) -> None:
    attempt["status"] = batch.get("status", "unknown")
    attempt["last_response"] = batch
    attempt["updated_at"] = datetime.now(timezone.utc).isoformat()
    write_json_atomic(journal_path, journal)


def _append_results(
    *,
    raw_path: Path,
    condition: str,
    model: str,
    run_fingerprint: str,
    attempt: dict[str, Any],
    selected_by_uid: dict[str, dict[str, Any]],
) -> tuple[int, int, int]:
    batch = attempt["last_response"]
    results = batch.get("results")
    if not isinstance(results, list):
        raise RuntimeError(f"completed batch {attempt['batch_id']} has no results list")
    by_custom_id = {str(result.get("custom_id")): result for result in results}
    expected_ids = set(attempt["request_map"])
    actual_ids = set(by_custom_id)
    if expected_ids != actual_ids:
        raise RuntimeError(
            f"batch custom_id mismatch: missing={len(expected_ids - actual_ids)} "
            f"unexpected={len(actual_ids - expected_ids)}"
        )
    counts = {"ok": 0, "truncated": 0, "error": 0}
    with raw_path.open("a", encoding="utf-8") as handle:
        for custom_id, mapping in attempt["request_map"].items():
            uid = mapping["uid"]
            item = selected_by_uid[uid]
            result = by_custom_id.get(custom_id)
            if result is None:
                status, raw, usage, error, response_meta = (
                    "error",
                    "",
                    {},
                    f"batch result missing custom_id={custom_id}",
                    {"batch_custom_id": custom_id},
                )
            else:
                status, raw, usage, error, response_meta = completion_from_batch_result(result)
            counts[status] += 1
            record = {
                "uid": uid,
                "cond": condition,
                "status": status,
                "error": error,
                "raw": raw,
                "usage": usage,
                "response_meta": {
                    **response_meta,
                    "batch_id": attempt["batch_id"],
                    "transport": "openrouter_batch_beta",
                },
                "model": model,
                "request_hash": mapping["request_hash"],
                "run_fingerprint": run_fingerprint,
                "answer_type": item["answer_type"],
                "gold_scale": item["gold_scale"],
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()
    return counts["ok"], counts["truncated"], counts["error"]


def parse_batch_attachments(specs: list[str]) -> dict[str, str]:
    attachments: dict[str, str] = {}
    for spec in specs:
        if "=" not in spec:
            raise ValueError(f"invalid attachment {spec!r}; expected CONDITION=BATCH_ID")
        condition, batch_id = spec.split("=", 1)
        if condition not in {"free", "json"} or not batch_id.startswith("batch-"):
            raise ValueError(f"invalid attachment {spec!r}")
        if condition in attachments:
            raise ValueError(f"duplicate attachment for {condition}")
        attachments[condition] = batch_id
    return attachments


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=200, help="分层题数，0=全部")
    parser.add_argument("--cond", nargs="+", default=["free", "json"], choices=["free", "json"])
    parser.add_argument("--model", required=True, help="普通 slug 或带 :batch 的展示 slug")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--seed", type=int, default=20260814)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--reasoning-effort", choices=["low", "high", "max"], default="high")
    parser.add_argument("--provider", required=True, help="固定 batch-capable provider")
    parser.add_argument(
        "--drop-parameters",
        nargs="+",
        default=[],
        choices=["temperature", "seed"],
        help="删除 batch endpoint 不支持的采样参数",
    )
    parser.add_argument("--answer-types", nargs="+", default=[])
    parser.add_argument("--dev-path", type=Path, default=DEV)
    parser.add_argument("--poll-seconds", type=float, default=10)
    parser.add_argument(
        "--attach-batch",
        action="append",
        default=[],
        metavar="CONDITION=BATCH_ID",
        help="recover an already submitted batch without making a new model call",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        attachments = parse_batch_attachments(args.attach_batch)
    except ValueError as exc:
        parser.error(str(exc))

    data = load_dev(args.dev_path)
    items = flatten_dev(data)
    if args.answer_types:
        allowed = set(args.answer_types)
        items = [item for item in items if item["answer_type"] in allowed]
    selected = stratified_items(items, args.n, args.seed)
    if not selected:
        sys.exit("筛选后没有题目")
    api_model = base_model_slug(args.model)
    config = manifest_config(
        requested_model=args.model,
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
    print(f"模型 {api_model} | Batch API | 分层题数 {len(selected)} | 条件 {args.cond}")
    print("样本分布:", dict(sorted(distribution.items())))

    example = selected[0]
    example_body = build_request_body(
        api_model,
        PROMPT_FREE.format(ctx=example["context"], q=example["question"]),
        "free",
        seed=args.seed,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort,
        provider=args.provider,
        drop_parameters=tuple(args.drop_parameters),
    )
    if args.dry_run:
        payload = build_batch_payload(args.model, {"dry-run-0001": example_body})
        print(
            f"outer_model={payload['model']} provider={args.provider} "
            f"request_count={len(payload['requests'])}"
        )
        print("dry-run 完成：未读取 API key，未写文件，未提交 batch。")
        return

    OUT.mkdir(parents=True, exist_ok=True)
    run_dir = OUT / args.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run_fingerprint = _prepare_manifest(run_dir, config)
    _write_selection(run_dir, selected, run_fingerprint)
    selected_by_uid = {item["uid"]: item for item in selected}
    key = load_key()

    for condition in args.cond:
        raw_path = run_dir / f"raw_{condition}.jsonl"
        completed = _existing_successes(raw_path, run_fingerprint)
        todo = [item for item in selected if item["uid"] not in completed]
        print(f"[{condition}] 已完成 {len(completed)}；待处理 {len(todo)}")
        if not todo:
            _write_offline_extractions(run_dir, condition, raw_path)
            continue

        journal_path = run_dir / f"batch_{condition}.json"
        journal = _load_journal(journal_path, run_fingerprint)
        attempt = _active_attempt(journal)
        if attempt is None:
            template = PROMPT_FREE if condition == "free" else PROMPT_JSON
            requests_by_id: dict[str, dict[str, Any]] = {}
            request_map: dict[str, dict[str, str]] = {}
            for index, item in enumerate(todo, 1):
                custom_id = f"{condition}-{index:04d}-{stable_hash(item['uid'])[:12]}"
                body = build_request_body(
                    api_model,
                    template.format(ctx=item["context"], q=item["question"]),
                    condition,
                    seed=args.seed,
                    max_tokens=args.max_tokens,
                    reasoning_effort=args.reasoning_effort,
                    provider=args.provider,
                    drop_parameters=tuple(args.drop_parameters),
                )
                requests_by_id[custom_id] = body
                request_map[custom_id] = {
                    "uid": item["uid"],
                    "request_hash": stable_hash(body),
                }
            if condition in attachments:
                submitted = get_batch(key, attachments[condition])
                if submitted.get("id") != attachments[condition]:
                    raise RuntimeError("attached batch response id mismatch")
                print(f"[{condition}] 附着已有 batch {attachments[condition]}；不会重新提交")
            else:
                payload = build_batch_payload(args.model, requests_by_id)
                submitted = submit_batch(key, payload)
            attempt = new_attempt_record(batch=submitted, request_map=request_map)
            journal["attempts"].append(attempt)
            write_json_atomic(journal_path, journal)
            action = "已附着" if condition in attachments else "已提交"
            print(f"[{condition}] {action} {attempt['batch_id']}，共 {len(request_map)} 请求")
        else:
            print(f"[{condition}] 恢复 batch {attempt['batch_id']} ({attempt['status']})")

        final_batch = poll_batch(
            key,
            attempt["batch_id"],
            interval_seconds=args.poll_seconds,
            on_update=lambda batch: _update_attempt(journal_path, journal, attempt, batch),
        )
        if final_batch.get("status") != "completed":
            sys.exit(f"batch {attempt['batch_id']} ended as {final_batch.get('status')}")
        ok, truncated, error = _append_results(
            raw_path=raw_path,
            condition=condition,
            model=api_model,
            run_fingerprint=run_fingerprint,
            attempt=attempt,
            selected_by_uid=selected_by_uid,
        )
        attempt["results_appended_at"] = datetime.now(timezone.utc).isoformat()
        attempt["result_counts"] = {"ok": ok, "truncated": truncated, "error": error}
        write_json_atomic(journal_path, journal)
        print(f"[{condition}] ok={ok} truncated={truncated} error={error}")
        _write_offline_extractions(run_dir, condition, raw_path)

    print(f"冻结输出与离线抽取写入：{run_dir}")


if __name__ == "__main__":
    main()
