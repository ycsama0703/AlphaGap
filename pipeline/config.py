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
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model_default: str
    deepseek_model_reasoning: str
    s2_api_key: str | None
    resend_api_key: str
    email_from: str
    email_to: str
    db_path: Path
    data_dir: Path
    log_level: str
    dry_run: bool


def load_settings() -> Settings:
    load_dotenv(PROJECT_ROOT / ".env")
    return Settings(
        deepseek_api_key=os.environ["DEEPSEEK_API_KEY"],
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        deepseek_model_default=os.getenv("DEEPSEEK_MODEL_DEFAULT", "deepseek-chat"),
        deepseek_model_reasoning=os.getenv("DEEPSEEK_MODEL_REASONING", "deepseek-reasoner"),
        s2_api_key=os.getenv("S2_API_KEY") or None,
        resend_api_key=os.environ["RESEND_API_KEY"],
        email_from=os.environ["EMAIL_FROM"],
        email_to=os.environ["EMAIL_TO"],
        db_path=PROJECT_ROOT / os.getenv("RADAR_DB_PATH", "db/radar.sqlite"),
        data_dir=PROJECT_ROOT / os.getenv("RADAR_DATA_DIR", "."),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        dry_run=os.getenv("DRY_RUN", "false").lower() == "true",
    )


def load_whitelist() -> dict:
    with open(PROJECT_ROOT / "whitelist.yaml") as f:
        return yaml.safe_load(f)


def load_prompt(name: str) -> str:
    """Load a prompt markdown file (e.g. '01_concept_extract_l1')."""
    path = PROJECT_ROOT / "prompts" / f"{name}.md"
    return path.read_text(encoding="utf-8")
