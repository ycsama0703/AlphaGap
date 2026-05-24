"""Config loader: whitelist.yaml + .env."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    llm_provider: str
    llm_api_key: str
    llm_base_url: str
    llm_model_default: str
    llm_model_reasoning: str
    llm_http_referer: str | None
    llm_app_title: str | None
    llm_input_cost_per_m: float | None
    llm_output_cost_per_m: float | None
    s2_api_key: str | None
    resend_api_key: str
    email_from: str
    email_to: str
    db_path: Path
    data_dir: Path
    log_level: str
    dry_run: bool
    adversarial_gap_review: bool


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    provider = os.getenv("LLM_PROVIDER", "deepseek").strip().lower()
    llm = _load_llm_settings(provider)
    return Settings(
        llm_provider=provider,
        llm_api_key=llm["api_key"],
        llm_base_url=llm["base_url"],
        llm_model_default=llm["model_default"],
        llm_model_reasoning=llm["model_reasoning"],
        llm_http_referer=llm["http_referer"],
        llm_app_title=llm["app_title"],
        llm_input_cost_per_m=llm["input_cost_per_m"],
        llm_output_cost_per_m=llm["output_cost_per_m"],
        s2_api_key=os.getenv("S2_API_KEY") or None,
        resend_api_key=os.environ["RESEND_API_KEY"],
        email_from=os.environ["EMAIL_FROM"],
        email_to=os.environ["EMAIL_TO"],
        db_path=PROJECT_ROOT / os.getenv("ALPHAGAP_DB_PATH", "db/alphagap.sqlite"),
        data_dir=PROJECT_ROOT / os.getenv("ALPHAGAP_DATA_DIR", "."),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
        adversarial_gap_review=os.getenv("ADVERSARIAL_GAP_REVIEW", "false").lower() == "true",
    )


def _load_llm_settings(provider: str) -> dict:
    generic_default = os.getenv("LLM_MODEL_DEFAULT")
    generic_reasoning = os.getenv("LLM_MODEL_REASONING")

    if provider == "openrouter":
        model_default = generic_default or os.getenv("OPENROUTER_MODEL_DEFAULT")
        if not model_default:
            raise ValueError(
                "Set LLM_MODEL_DEFAULT or OPENROUTER_MODEL_DEFAULT when LLM_PROVIDER=openrouter"
            )
        return {
            "api_key": _required_env("OPENROUTER_API_KEY"),
            "base_url": os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            "model_default": model_default,
            "model_reasoning": generic_reasoning
            or os.getenv("OPENROUTER_MODEL_REASONING")
            or model_default,
            "http_referer": os.getenv("OPENROUTER_HTTP_REFERER") or None,
            "app_title": os.getenv("OPENROUTER_APP_TITLE", "AlphaGap") or None,
            "input_cost_per_m": _optional_float("LLM_INPUT_COST_PER_M"),
            "output_cost_per_m": _optional_float("LLM_OUTPUT_COST_PER_M"),
        }
    if provider == "mimo":
        model_default = generic_default or os.getenv("MIMO_MODEL_DEFAULT", "mimo-v2.5-pro")
        return {
            "api_key": _required_env("MIMO_API_KEY"),
            "base_url": _required_env("MIMO_BASE_URL"),
            "model_default": model_default,
            "model_reasoning": generic_reasoning
            or os.getenv("MIMO_MODEL_REASONING")
            or model_default,
            "http_referer": None,
            "app_title": None,
            "input_cost_per_m": _optional_float("LLM_INPUT_COST_PER_M"),
            "output_cost_per_m": _optional_float("LLM_OUTPUT_COST_PER_M"),
        }
    if provider == "custom":
        model_default = generic_default or _required_env("LLM_MODEL_DEFAULT")
        return {
            "api_key": _required_env("LLM_API_KEY"),
            "base_url": _required_env("LLM_BASE_URL"),
            "model_default": model_default,
            "model_reasoning": generic_reasoning or model_default,
            "http_referer": os.getenv("LLM_HTTP_REFERER") or None,
            "app_title": os.getenv("LLM_APP_TITLE") or None,
            "input_cost_per_m": _optional_float("LLM_INPUT_COST_PER_M"),
            "output_cost_per_m": _optional_float("LLM_OUTPUT_COST_PER_M"),
        }
    if provider != "deepseek":
        raise ValueError(f"Unsupported LLM_PROVIDER={provider!r}")

    return {
        "api_key": _required_env("DEEPSEEK_API_KEY"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "model_default": generic_default or os.getenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-chat"),
        "model_reasoning": generic_reasoning
        or os.getenv("DEEPSEEK_MODEL_REASONING", "deepseek-reasoner"),
        "http_referer": None,
        "app_title": None,
        "input_cost_per_m": _optional_float("LLM_INPUT_COST_PER_M", 0.27),
        "output_cost_per_m": _optional_float("LLM_OUTPUT_COST_PER_M", 1.10),
    }


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def _optional_float(name: str, default: float | None = None) -> float | None:
    value = os.getenv(name)
    return float(value) if value else default


def load_whitelist() -> dict:
    with open(PROJECT_ROOT / "whitelist.yaml") as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> str:
    """Load a prompt markdown file (e.g. '01_concept_extract_l1')."""
    path = PROJECT_ROOT / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")
