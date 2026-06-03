"""Semantic Scholar API — citation counts + author enrichment.

Used primarily for citation velocity signal (snapshot citations daily,
compute delta over 30d for trend signal).

Endpoints:
  POST /graph/v1/paper/batch?fields=...    — up to 500 papers per call

Rate limits:
  No key: ~1 RPS
  With S2_API_KEY env: higher
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass

import requests


log = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
BATCH_SIZE = 500
RATE_LIMIT_SLEEP = 1.1
DEFAULT_FIELDS = "citationCount,referenceCount,influentialCitationCount,publicationDate"


@dataclass
class S2Paper:
    arxiv_id: str
    s2_id: str | None
    citation_count: int
    influential_citation_count: int
    reference_count: int
    publication_date: str | None


def _headers() -> dict[str, str]:
    key = os.environ.get("S2_API_KEY")
    return {"x-api-key": key} if key else {}


def fetch_citation_counts(arxiv_ids: list[str]) -> dict[str, S2Paper]:
    """Batch-lookup citation counts for many arxiv ids.

    Returns dict arxiv_id → S2Paper. Missing papers silently absent.
    """
    out: dict[str, S2Paper] = {}
    if not arxiv_ids:
        return out

    for start in range(0, len(arxiv_ids), BATCH_SIZE):
        chunk = arxiv_ids[start: start + BATCH_SIZE]
        ids = [f"ARXIV:{a}" for a in chunk]

        try:
            resp = requests.post(
                f"{S2_BASE}/paper/batch",
                params={"fields": DEFAULT_FIELDS},
                json={"ids": ids},
                headers=_headers(),
                timeout=60,
            )
        except (requests.Timeout, requests.ConnectionError) as e:
            log.warning("S2 network error chunk %d: %s", start, e)
            time.sleep(RATE_LIMIT_SLEEP * 3)
            continue

        if resp.status_code == 429:
            log.warning("S2 rate limited; back off 30s")
            time.sleep(30)
            continue
        if resp.status_code != 200:
            log.warning("S2 HTTP %d: %s", resp.status_code, resp.text[:200])
            time.sleep(RATE_LIMIT_SLEEP)
            continue

        for arxiv_id, item in zip(chunk, resp.json()):
            if not item:
                continue
            out[arxiv_id] = S2Paper(
                arxiv_id=arxiv_id,
                s2_id=item.get("paperId"),
                citation_count=item.get("citationCount") or 0,
                influential_citation_count=item.get("influentialCitationCount") or 0,
                reference_count=item.get("referenceCount") or 0,
                publication_date=item.get("publicationDate"),
            )

        log.info("S2 chunk %d-%d: %d/%d found", start, start + len(chunk),
                 sum(1 for x in chunk if x in out), len(chunk))
        time.sleep(RATE_LIMIT_SLEEP)

    return out


_SEARCH_FIELDS = ("title,abstract,venue,year,authors,externalIds,url,"
                  "fieldsOfStudy,citationCount")


def search_fin_conf_papers(venues: list[str], *, year_from: int,
                           query: str = "financial|finance|trading|portfolio|"
                           "\"asset pricing\"|\"stock market\"|\"order book\"|"
                           "\"option pricing\"|\"credit risk\"|\"market making\"",
                           fields_of_study: str = "",
                           limit: int = 200) -> list[dict]:
    """Search Semantic Scholar for finance-relevant papers at given conference venues.

    Uses /paper/search/bulk with a venue filter + a finance `query` (S2 bulk OR syntax
    uses `|`). NOTE: do NOT filter by fieldsOfStudy=Economics here — ML-for-finance conf
    papers are tagged 'Computer Science' by S2, so an Economics filter drops them; the
    finance query is what selects the relevant slice. Paginates via the continuation
    token up to `limit`. Returns raw S2 paper dicts.
    """
    out: list[dict] = []
    params = {
        "query": query,
        "venue": ",".join(venues),
        "year": f"{year_from}-",
        "fields": _SEARCH_FIELDS,
    }
    if fields_of_study:
        params["fieldsOfStudy"] = fields_of_study
    token: str | None = None
    while len(out) < limit:
        if token:
            params["token"] = token
        try:
            resp = requests.get(f"{S2_BASE}/paper/search/bulk", params=params,
                                headers=_headers(), timeout=60)
        except (requests.Timeout, requests.ConnectionError) as e:
            log.warning("S2 search network error: %s", e)
            time.sleep(RATE_LIMIT_SLEEP * 3)
            break
        if resp.status_code == 429:
            log.warning("S2 search rate limited; back off 30s")
            time.sleep(30)
            continue
        if resp.status_code != 200:
            log.warning("S2 search HTTP %s: %s", resp.status_code, resp.text[:200])
            break
        data = resp.json()
        out.extend(data.get("data") or [])
        token = data.get("token")
        if not token:
            break
        time.sleep(RATE_LIMIT_SLEEP)
    return out[:limit]


# CLI quick test
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    test_ids = sys.argv[1:] if len(sys.argv) > 1 else [
        "1706.03762",  # Transformer
        "2303.11366",  # Reflexion
    ]
    res = fetch_citation_counts(test_ids)
    for aid in test_ids:
        p = res.get(aid)
        if p:
            print(f"  {aid}: {p.citation_count} cites ({p.influential_citation_count} influential)")
        else:
            print(f"  {aid}: not found")
