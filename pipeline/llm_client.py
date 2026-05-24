"""Provider-selectable OpenAI-compatible LLM client.

Centralized wrapper so all prompts go through one place — easier to swap models,
add caching, retry logic, cost tracking.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from typing import Any

from openai import OpenAI

from .config import load_settings


log = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        s = load_settings()
        default_headers = {
            key: value
            for key, value in {
                "HTTP-Referer": s.llm_http_referer,
                "X-OpenRouter-Title": s.llm_app_title,
            }.items()
            if value
        }
        self._client = OpenAI(
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            default_headers=default_headers or None,
        )
        self.provider = s.llm_provider
        self._model_default = s.llm_model_default
        self._model_reasoning = s.llm_model_reasoning
        self._input_cost_per_m = s.llm_input_cost_per_m
        self._output_cost_per_m = s.llm_output_cost_per_m
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._reported_cost_usd = 0.0
        self._has_reported_cost = False

    def chat_json(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        reasoning: bool = False,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """Call LLM and parse JSON output. Raises on parse failure."""
        model = self._model_reasoning if reasoning else self._model_default
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        self._record_usage(resp.usage)

        content = resp.choices[0].message.content
        if not content or not content.strip():
            log.error(
                "LLM returned empty content. finish_reason=%s usage=%s",
                resp.choices[0].finish_reason,
                resp.usage,
            )
            raise ValueError(
                f"LLM returned empty content (finish_reason={resp.choices[0].finish_reason})"
            )
        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            log.error("JSON parse failed: %s\ncontent[:500]=%r", e, content[:500])
            raise

    def chat_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        reasoning: bool = False,
        max_tokens: int = 4096,
    ) -> str:
        """Call an LLM for non-JSON text while preserving usage accounting."""
        model = self._model_reasoning if reasoning else self._model_default
        resp = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._record_usage(resp.usage)
        return resp.choices[0].message.content or ""

    def _record_usage(self, usage: object | None) -> None:
        if not usage:
            return
        self._total_input_tokens += usage.prompt_tokens
        self._total_output_tokens += usage.completion_tokens
        reported_cost = _usage_cost(usage)
        if reported_cost is not None:
            self._reported_cost_usd += reported_cost
            self._has_reported_cost = True

    @property
    def total_tokens(self) -> tuple[int, int]:
        return self._total_input_tokens, self._total_output_tokens

    def estimate_cost_usd(self) -> float:
        if self._has_reported_cost:
            return self._reported_cost_usd
        if self._input_cost_per_m is None or self._output_cost_per_m is None:
            return 0.0
        return (
            (self._total_input_tokens / 1e6) * self._input_cost_per_m
            + (self._total_output_tokens / 1e6) * self._output_cost_per_m
        )


def _usage_cost(usage: object) -> float | None:
    value = getattr(usage, "cost", None)
    if value is None:
        extra = getattr(usage, "model_extra", None) or {}
        value = extra.get("cost")
    return float(value) if value is not None else None


def _main() -> None:
    parser = argparse.ArgumentParser(description="Test configured LLM providers and models")
    subparsers = parser.add_subparsers(dest="command", required=True)

    probe = subparsers.add_parser("probe", help="Send a small structured-output request")
    probe.add_argument("--provider", choices=("deepseek", "mimo", "openrouter", "custom"))
    probe.add_argument("--model", required=True, help="Provider model ID, e.g. provider/model-slug")

    models = subparsers.add_parser("models", help="List model IDs exposed by a provider")
    models.add_argument("--provider", choices=("deepseek", "mimo", "openrouter", "custom"))
    models.add_argument("--contains", default="", help="Only print model IDs containing this text")

    args = parser.parse_args()
    if args.provider:
        os.environ["LLM_PROVIDER"] = args.provider

    if args.command == "probe":
        os.environ["LLM_MODEL_DEFAULT"] = args.model
        client = LLMClient()
        result = client.chat_json(
            system="Return strict JSON only.",
            user='Return {"ok": true, "provider_test": "alphagap"}.',
            temperature=0.0,
            max_tokens=64,
        )
        in_tokens, out_tokens = client.total_tokens
        print(
            f"OK provider={client.provider} model={args.model} "
            f"json_ok={result.get('ok') is True} tokens={in_tokens}/{out_tokens} "
            f"cost_usd={client.estimate_cost_usd():.8f}"
        )
        return

    os.environ.setdefault("LLM_MODEL_DEFAULT", "_models_only_")
    client = LLMClient()
    match = args.contains.lower()
    model_ids = sorted(
        model.id for model in client._client.models.list().data
        if not match or match in model.id.lower()
    )
    print("\n".join(model_ids))


if __name__ == "__main__":
    _main()
