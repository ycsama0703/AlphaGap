"""Concept extraction — Prompt 01 (L1) and Prompt 02 (L2).

Workflow:
  L1: run on every candidate paper. Extracts side / method_primary / domain / tags.
  L2: run only on priority papers (whitelist match / high h-index / HF Daily hit).
      Extracts building_blocks / claims / benchmarks.

Prompt files live in prompts/*.md with a fixed structure:
  ## System Prompt
  ```
  <system text>
  ```
  ## User Prompt Template
  ```
  <user template with {placeholders}>
  ```
We parse them once and cache.
"""
from __future__ import annotations

import json
import logging
import re
from functools import lru_cache

from ..config import load_prompt
from ..llm_client import LLMClient


log = logging.getLogger(__name__)


# ---------- Prompt parsing ----------

_SECTION_RE = re.compile(
    r"##\s+(System Prompt|User Prompt Template)\s*\n+```[^\n]*\n(.*?)\n```",
    re.DOTALL,
)


def render_template(template: str, **kwargs) -> str:
    """Safe template rendering — replaces only {explicit_key} placeholders.

    Required because our prompt templates contain JSON schema examples with
    literal { and } that would otherwise break str.format().
    """
    result = template
    for key, value in kwargs.items():
        result = result.replace("{" + key + "}", str(value))
    return result


@lru_cache(maxsize=16)
def parse_prompt(name: str) -> tuple[str, str]:
    """Extract (system_prompt, user_template) from a prompt md file by name.

    Cached: prompt files are static across a run.
    """
    md = load_prompt(name)
    sections = {m.group(1): m.group(2).strip() for m in _SECTION_RE.finditer(md)}

    system = sections.get("System Prompt")
    user = sections.get("User Prompt Template")
    if not system or not user:
        raise ValueError(
            f"Prompt {name!r} missing required sections. Found: {list(sections)}"
        )
    return system, user


# ---------- L1 extraction ----------

def extract_l1(client: LLMClient, paper: dict) -> dict:
    """Run Prompt 01 on a paper.

    paper expects keys: title, abstract, affiliations, arxiv_categories.
    Returns dict: {side, method_primary, domain, tags}.
    """
    system, user_template = parse_prompt("01_concept_extract_l1")
    user = render_template(
        user_template,
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
        affiliations=paper.get("affiliations", ""),
        arxiv_categories=paper.get("arxiv_categories", ""),
    )
    result = client.chat_json(system=system, user=user, temperature=0.0)
    return _normalize_l1(result)


def _normalize_l1(raw: dict) -> dict:
    """Defensive normalization — LLM may drift on schema."""
    side = (raw.get("side") or "").lower().strip()
    if side not in ("ai", "fin", "both"):
        side = "ai"   # default; pipeline can override via arxiv_category rule

    def _as_list(v) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            return [v]
        return [str(x).strip() for x in v if str(x).strip()]

    return {
        "side": side,
        "method_primary": _as_list(raw.get("method_primary"))[:2],
        "domain": _as_list(raw.get("domain"))[:3],
        "tags": _as_list(raw.get("tags"))[:5],
    }


# ---------- L2 extraction ----------

def extract_l2(client: LLMClient, paper: dict, l1: dict) -> dict:
    """Run Prompt 02 on priority papers. Requires L1 result as context."""
    system, user_template = parse_prompt("02_concept_extract_l2")
    user = render_template(
        user_template,
        title=paper.get("title", ""),
        abstract=paper.get("abstract", ""),
        side=l1.get("side", "ai"),
        method_primary=json.dumps(l1.get("method_primary", []), ensure_ascii=False),
        domain=json.dumps(l1.get("domain", []), ensure_ascii=False),
    )
    result = client.chat_json(system=system, user=user, temperature=0.0)
    return _normalize_l2(result)


def _normalize_l2(raw: dict) -> dict:
    def _as_list(v, limit: int) -> list[str]:
        if not v:
            return []
        if isinstance(v, str):
            return [v][:limit]
        return [str(x).strip() for x in v if str(x).strip()][:limit]

    return {
        "building_blocks": _as_list(raw.get("building_blocks"), 5),
        "claims": _as_list(raw.get("claims"), 3),
        "benchmarks": _as_list(raw.get("benchmarks"), 5),
    }


# ---------- CLI for end-to-end smoke test ----------

if __name__ == "__main__":
    """Smoke test: fetch a few arxiv papers and run L1 + L2 on each."""
    import sys
    from datetime import date, timedelta

    from ..fetchers.arxiv import fetch_recent

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    cats = sys.argv[1:] if len(sys.argv) > 1 else ["cs.LG", "q-fin.PM"]
    since = date.today() - timedelta(days=2)
    papers = fetch_recent(cats, since, max_per_category=10)
    log.info("Fetched %d papers; running L1+L2 on first 5", len(papers))

    client = LLMClient()
    for p in papers[:5]:
        paper_dict = {
            "title": p.title,
            "abstract": p.abstract,
            "affiliations": "; ".join(
                a for au in p.authors for a in au.get("affiliations", [])
            ),
            "arxiv_categories": ", ".join(p.arxiv_categories),
        }
        try:
            l1 = extract_l1(client, paper_dict)
        except Exception as e:
            log.error("L1 failed on %s: %s", p.arxiv_id, e)
            continue

        print(f"\n[{p.arxiv_id}] {p.title[:80]}")
        print(f"  side: {l1['side']}")
        print(f"  method_primary: {l1['method_primary']}")
        print(f"  domain: {l1['domain']}")
        print(f"  tags: {l1['tags']}")

        try:
            l2 = extract_l2(client, paper_dict, l1)
            print(f"  building_blocks: {l2['building_blocks']}")
            print(f"  claims: {l2['claims']}")
            print(f"  benchmarks: {l2['benchmarks']}")
        except Exception as e:
            log.error("L2 failed on %s: %s", p.arxiv_id, e)

    in_tok, out_tok = client.total_tokens
    print(f"\nTokens: in={in_tok} out={out_tok} | est cost: ${client.estimate_cost_usd():.4f}")
