"""Concept extraction — calls Prompt 01 (L1) and Prompt 02 (L2).

L1: all candidate papers (side / method_primary / domain / tags)
L2: priority papers only (building_blocks / claims / benchmarks)
"""
from __future__ import annotations

from ..config import load_prompt
from ..llm_client import LLMClient


def extract_l1(client: LLMClient, paper: dict) -> dict:
    """Run Prompt 01 on a paper. Returns dict with side/method_primary/domain/tags."""
    prompt_md = load_prompt("01_concept_extract_l1")
    system, user_template = _split_prompt(prompt_md)
    user = user_template.format(
        title=paper["title"],
        abstract=paper["abstract"],
        affiliations=paper.get("affiliations", ""),
        arxiv_categories=paper.get("arxiv_categories", ""),
    )
    return client.chat_json(system=system, user=user, temperature=0.0)


def extract_l2(client: LLMClient, paper: dict, l1: dict) -> dict:
    """Run Prompt 02 on priority papers."""
    prompt_md = load_prompt("02_concept_extract_l2")
    system, user_template = _split_prompt(prompt_md)
    user = user_template.format(
        title=paper["title"],
        abstract=paper["abstract"],
        side=l1["side"],
        method_primary=l1["method_primary"],
        domain=l1["domain"],
    )
    return client.chat_json(system=system, user=user, temperature=0.0)


def _split_prompt(md: str) -> tuple[str, str]:
    """Extract System Prompt and User Prompt Template from a prompt .md file.

    TODO: parse the markdown — sections marked '## System Prompt' and '## User Prompt Template',
    each followed by a ```...``` code block.
    """
    raise NotImplementedError
