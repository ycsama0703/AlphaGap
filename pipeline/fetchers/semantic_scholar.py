"""Semantic Scholar API client — for author enrichment + paper search.

Endpoints used:
  /graph/v1/paper/search           — keyword search
  /graph/v1/paper/{id}             — single paper by id (incl. authors h-index)
  /graph/v1/author/batch           — batch author metadata

Free tier: ~1 RPS without key, higher with S2_API_KEY.

TODO:
  - enrich_authors(paper) — fill h_index, citation_count, affiliations
  - search(query, year_min) — for filling gaps in arxiv/SSRN coverage
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AuthorMeta:
    s2_id: str
    name: str
    h_index: int | None
    citation_count: int | None
    affiliations: list[str]


def enrich_authors(authors: list[dict]) -> list[AuthorMeta]:
    raise NotImplementedError
