"""DeepSeek LLM client (OpenAI-compatible).

Centralized wrapper so all prompts go through one place — easier to swap models,
add caching, retry logic, cost tracking.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import OpenAI

from .config import load_settings


log = logging.getLogger(__name__)


class LLMClient:
    def __init__(self) -> None:
        s = load_settings()
        self._client = OpenAI(api_key=s.deepseek_api_key, base_url=s.deepseek_base_url)
        self._model_default = s.deepseek_model_default
        self._model_reasoning = s.deepseek_model_reasoning
        self._total_input_tokens = 0
        self._total_output_tokens = 0

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
        # Track usage
        if resp.usage:
            self._total_input_tokens += resp.usage.prompt_tokens
            self._total_output_tokens += resp.usage.completion_tokens

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

    @property
    def total_tokens(self) -> tuple[int, int]:
        return self._total_input_tokens, self._total_output_tokens

    def estimate_cost_usd(self) -> float:
        # DeepSeek V3.5 pricing (subject to change)
        # input $0.27/M, output $1.10/M
        return (self._total_input_tokens / 1e6) * 0.27 + (self._total_output_tokens / 1e6) * 1.10
