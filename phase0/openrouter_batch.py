"""Small, durable helpers for OpenRouter's asynchronous Batch API."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests


BATCHES_URL = "https://openrouter.ai/api/beta/batches"
TERMINAL_STATUSES = {"completed", "failed", "cancelled", "expired"}


def base_model_slug(model: str) -> str:
    """Return the ordinary model slug used inside a Batch API submission."""
    return model.removesuffix(":batch")


def build_batch_payload(
    model: str,
    requests_by_id: dict[str, dict[str, Any]],
    *,
    endpoint: str = "/v1/chat/completions",
) -> dict[str, Any]:
    api_model = base_model_slug(model)
    requests_payload = []
    for custom_id, body in requests_by_id.items():
        request_body = dict(body)
        request_body["model"] = api_model
        requests_payload.append({"custom_id": custom_id, "body": request_body})
    return {
        "endpoint": endpoint,
        "model": api_model,
        "requests": requests_payload,
    }


def batch_headers(key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "X-Title": "AlphaGap-ScorerAudit-TATQA-Batch",
    }


def submit_batch(
    key: str,
    payload: dict[str, Any],
    *,
    timeout: int = 120,
) -> dict[str, Any]:
    response = requests.post(
        BATCHES_URL,
        json=payload,
        headers=batch_headers(key),
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"Batch submit HTTP {response.status_code}: {response.text[:1000]}")
    result = response.json()
    if not result.get("id"):
        raise RuntimeError(f"Batch submit response has no id: {result}")
    return result


def get_batch(key: str, batch_id: str, *, timeout: int = 120) -> dict[str, Any]:
    response = requests.get(
        f"{BATCHES_URL}/{batch_id}",
        headers=batch_headers(key),
        timeout=timeout,
    )
    if not response.ok:
        raise RuntimeError(f"Batch poll HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


def poll_batch(
    key: str,
    batch_id: str,
    *,
    interval_seconds: float = 10,
    on_update: Callable[[dict[str, Any]], None] | None = None,
    not_found_grace_seconds: float = 120,
) -> dict[str, Any]:
    last_status = ""
    started = time.monotonic()
    reported_not_found = False
    while True:
        try:
            batch = get_batch(key, batch_id)
        except RuntimeError as exc:
            # Newly created OpenRouter batches can briefly be absent from the
            # read path even though POST returned a durable id.
            if "Batch poll HTTP 404" not in str(exc) or time.monotonic() - started > not_found_grace_seconds:
                raise
            if not reported_not_found:
                print(f"batch {batch_id}: waiting for read-after-create visibility", flush=True)
                reported_not_found = True
            time.sleep(interval_seconds)
            continue
        status = str(batch.get("status") or "unknown")
        if on_update is not None:
            on_update(batch)
        if status != last_status:
            print(f"batch {batch_id}: {status}", flush=True)
            last_status = status
        if status in TERMINAL_STATUSES:
            return batch
        time.sleep(interval_seconds)


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(path)


def completion_from_batch_result(
    result: dict[str, Any],
) -> tuple[str, str, dict[str, Any], str, dict[str, Any]]:
    """Convert one OpenAI-style batch result to tatqa_run's call tuple."""
    custom_id = str(result.get("custom_id") or "")
    error_value = result.get("error")
    response_wrapper = result.get("response") or {}
    status_code = response_wrapper.get("status_code")
    body = response_wrapper.get("body") or result.get("body") or {}
    if error_value or (status_code is not None and not 200 <= int(status_code) < 300):
        return (
            "error",
            "",
            {},
            f"batch result error custom_id={custom_id}: {error_value or body}",
            {"batch_custom_id": custom_id, "http_status": status_code},
        )
    try:
        choice = body["choices"][0]
        content = choice["message"].get("content")
    except (KeyError, IndexError, TypeError) as exc:
        return (
            "error",
            "",
            body.get("usage", {}) if isinstance(body, dict) else {},
            f"malformed batch completion custom_id={custom_id}: {type(exc).__name__}: {exc}",
            {"batch_custom_id": custom_id, "http_status": status_code},
        )
    usage = body.get("usage", {})
    response_meta = {
        "batch_custom_id": custom_id,
        "http_status": status_code,
        "response_id": body.get("id"),
        "response_model": body.get("model"),
        "provider": body.get("provider"),
        "finish_reason": choice.get("finish_reason"),
        "native_finish_reason": choice.get("native_finish_reason"),
    }
    if content is None or not str(content).strip():
        if choice.get("finish_reason") == "length":
            return (
                "truncated",
                "",
                usage,
                "empty content after exhausting max_tokens",
                response_meta,
            )
        return (
            "error",
            "",
            usage,
            f"empty batch content (finish_reason={choice.get('finish_reason')!r})",
            response_meta,
        )
    return "ok", str(content), usage, "", response_meta


def new_attempt_record(
    *,
    batch: dict[str, Any],
    request_map: dict[str, dict[str, str]],
) -> dict[str, Any]:
    return {
        "batch_id": batch["id"],
        "status": batch.get("status", "validating"),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "request_map": request_map,
        "last_response": batch,
    }
