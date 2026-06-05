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


def opus_client(default: "LLMClient | None" = None):
    """Build the OpenRouter client for the quality-sensitive deep steps (L3 full-text mining,
    mechanism-gap generation, mechanism brief), regardless of the default provider. Falls back to
    `default` (or a fresh default client) if OpenRouter isn't configured — so the hybrid degrades
    gracefully to the cheap model rather than crashing. Model via OPENROUTER_MODEL_OPUS env (default
    openai/gpt-chat-latest). [Factory name is historical — it now serves whatever the env points at.]"""
    # ensure .env is loaded into os.environ before reading the key (robust to call order —
    # otherwise this depends on some other LLMClient() having triggered load_dotenv first).
    try:
        load_settings()
    except Exception:
        pass
    key = os.getenv("OPENROUTER_API_KEY")
    if not key:
        log.warning("opus_client: no OPENROUTER_API_KEY — falling back to default model")
        return default or LLMClient()
    model = os.getenv("OPENROUTER_MODEL_OPUS", "openai/gpt-chat-latest")
    base = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    return LLMClient(api_key=key, base_url=base, model=model, provider="openrouter")


def _strip_json_fences(content: str) -> str:
    """Some models (e.g. Claude via OpenRouter) wrap JSON in ```json ... ``` fences; DeepSeek doesn't.
    Strip a leading/trailing markdown code fence so json.loads works across providers."""
    s = content.strip()
    if s.startswith("```"):
        s = s[3:]
        if s[:4].lower() == "json":
            s = s[4:]
        if s.endswith("```"):
            s = s[:-3]
        s = s.strip()
        # also handle a stray leading 'json\n' without backticks
    return s


class LLMClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, provider: str | None = None) -> None:
        """Defaults come from settings (.env). Pass overrides to point one client at a different
        provider/model — used for the hybrid (cheap default model for mechanical work, opus for
        the quality-sensitive steps: L3 mining + mechanism-gap generation + brief). See opus_client()."""
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
            api_key=api_key or s.llm_api_key,
            base_url=base_url or s.llm_base_url,
            default_headers=default_headers or None,
        )
        self.provider = provider or s.llm_provider
        self._model_default = model or s.llm_model_default
        self._model_reasoning = model or s.llm_model_reasoning
        self._model_brief = model or s.llm_model_brief
        self._input_cost_per_m = s.llm_input_cost_per_m
        self._output_cost_per_m = s.llm_output_cost_per_m
        self._reasoning_input_cost_per_m = s.llm_reasoning_input_cost_per_m
        self._reasoning_output_cost_per_m = s.llm_reasoning_output_cost_per_m
        self._brief_input_cost_per_m = s.llm_brief_input_cost_per_m
        self._brief_output_cost_per_m = s.llm_brief_output_cost_per_m
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._reported_cost_usd = 0.0
        self._unreported_cost_usd = 0.0

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
        try:
            return self._chat_json_once(
                model=model,
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=reasoning,
            )
        except (ValueError, json.JSONDecodeError) as exc:
            if not reasoning:
                raise
            log.warning(
                "Reasoning JSON response unusable (%s); retrying non-thinking with default model %s",
                exc,
                self._model_default,
            )
            return self._chat_json_once(
                model=self._model_default,
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                reasoning=False,
            )

    def _chat_json_once(self, *, model: str, system: str, user: str,
                        temperature: float, max_tokens: int,
                        reasoning: bool) -> dict[str, Any]:
        request = self._request_args(model, system, user, temperature, max_tokens, reasoning)
        request["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(
            **request,
        )
        self._record_usage(resp.usage, reasoning=reasoning)

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
            return json.loads(_strip_json_fences(content))
        except json.JSONDecodeError as e:
            log.error("JSON parse failed: %s\ncontent[:500]=%r", e, content[:500])
            raise

    def _request_args(
        self, model: str, system: str, user: str, temperature: float,
        max_tokens: int, reasoning: bool,
    ) -> dict[str, Any]:
        request: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": max_tokens,
        }
        if self.provider == "deepseek":
            request["extra_body"] = {
                "thinking": {"type": "enabled" if reasoning else "disabled"}
            }
            if not reasoning:
                request["temperature"] = temperature
        else:
            request["temperature"] = temperature
        return request

    def chat_text(
        self,
        system: str,
        user: str,
        *,
        temperature: float = 0.0,
        reasoning: bool = False,
        brief: bool = False,
        max_tokens: int = 4096,
    ) -> str:
        """Call an LLM for non-JSON text while preserving usage accounting."""
        model = self._model_brief if brief else self._model_reasoning if reasoning else self._model_default
        thinking_enabled = reasoning or brief
        resp = self._client.chat.completions.create(
            **self._request_args(model, system, user, temperature, max_tokens, thinking_enabled),
        )
        self._record_usage(resp.usage, reasoning=reasoning, brief=brief)
        return resp.choices[0].message.content or ""

    def _record_usage(self, usage: object | None, *, reasoning: bool, brief: bool = False) -> None:
        if not usage:
            return
        self._total_input_tokens += usage.prompt_tokens
        self._total_output_tokens += usage.completion_tokens
        reported_cost = _usage_cost(usage)
        if reported_cost is not None:
            self._reported_cost_usd += reported_cost
            return
        if brief:
            input_cost = self._brief_input_cost_per_m
            output_cost = self._brief_output_cost_per_m
        elif reasoning:
            input_cost = self._reasoning_input_cost_per_m
            output_cost = self._reasoning_output_cost_per_m
        else:
            input_cost = self._input_cost_per_m
            output_cost = self._output_cost_per_m
        if input_cost is not None and output_cost is not None:
            self._unreported_cost_usd += (
                (usage.prompt_tokens / 1e6) * input_cost
                + (usage.completion_tokens / 1e6) * output_cost
            )

    @property
    def total_tokens(self) -> tuple[int, int]:
        return self._total_input_tokens, self._total_output_tokens

    def estimate_cost_usd(self) -> float:
        return self._reported_cost_usd + self._unreported_cost_usd


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
