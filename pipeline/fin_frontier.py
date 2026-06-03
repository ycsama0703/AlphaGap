"""Fin-frontier candidates — finance-relevant top-conference papers for HUMAN curation.

Finance research is slow + noisy, so AlphaGap's Fin frontier is human-curated (the
knowledge/fin_fields notes + transfer_cells), NOT a paper firehose. This module fetches
the finance-relevant slice of peer-reviewed top conferences (ICML / NeurIPS / ICLR /
AAAI) via Semantic Scholar (venue + fieldsOfStudy=Economics/Business) and surfaces them
as a REVIEW LIST — so a human can decide whether to refresh a field note or propose a
new transfer cell (via `python -m pipeline.cells approve`). It deliberately does NOT
auto-feed gap generation: that would reintroduce the noise the curated frontier avoids.

CLI:
  python -m pipeline.fin_frontier fetch [--years N] [--limit N]   # pull + queue new candidates
  python -m pipeline.fin_frontier render                          # rebuild FIN-FRONTIER-CANDIDATES.md
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import date
from pathlib import Path

from .config import PROJECT_ROOT, load_settings
from .fetchers.semantic_scholar import search_fin_conf_papers

log = logging.getLogger(__name__)

CANDIDATES = PROJECT_ROOT / "fin_frontier_candidates.jsonl"
REVIEW_MD = PROJECT_ROOT / "FIN-FRONTIER-CANDIDATES.md"
VENUES = ["ICML", "NeurIPS", "NIPS", "ICLR", "AAAI"]

# Map a paper to one of the 5 curated Fin field notes (best-effort, for review grouping).
_FIELD_KEYWORDS = {
    "factor_investing": ("factor", "alpha", "cross-section", "anomaly", "stock selection"),
    "portfolio_optimization": ("portfolio", "allocation", "rebalanc", "mean-variance", "risk parity"),
    "financial_llm_agents": ("agent", "llm", "tool use", "trading agent", "language model"),
    "financial_nlp": ("nlp", "text", "news", "sentiment", "filing", "earnings call", "document"),
    "asset_pricing_ml": ("asset pricing", "risk premi", "sdf", "return prediction", "expected return"),
}


def _suggest_field(p: dict) -> str:
    text = f"{p.get('title','')} {p.get('abstract','')}".lower()
    best, score = "unmapped", 0
    for field, kws in _FIELD_KEYWORDS.items():
        s = sum(1 for kw in kws if kw in text)
        if s > score:
            best, score = field, s
    return best


# Strong, unambiguous finance signals — anywhere in title/abstract is enough.
# The S2 venue+query search is recall-oriented (generic terms like "return" /
# "market" / "stock" pull in robotics, density estimation, etc.), so this is the
# precision gate: 宁缺毋滥. Substring match so "hedg", "deriv" cover variants.
_STRONG_SIGNALS = (
    "trading strateg", "trading polic", "trading agent", "stock trading",
    "trading system", "pairs trading", "trade execution", "portfolio", "asset pricing",
    "stock market", "stock return", "stock price", "equity return", "equity market",
    "order book", "limit order", "market making", "market microstructur",
    "option pricing", "derivative pricing", "credit risk", "default risk",
    "volatility forecast", "volatility model", "factor model", "factor investing",
    "cross-section of returns", "risk premi", "expected return", "alpha signal",
    "quantitative finance", "algorithmic trading", "high-frequency trading",
    "sharpe", "backtest", "exchange rate", "yield curve", "bond pricing",
    "financial time series", "financial decision", "financial market",
)

# Weak signal: bare "financ"/"hedg"/"deriv" match boilerplate ("...industrial and
# financial sectors"), so they only count when in the TITLE (i.e. central topic).
_WEAK_TITLE_SIGNALS = ("financ", "hedg")


def _is_finance_relevant(p: dict) -> bool:
    """Tiered precision gate over the recall-oriented S2 search. A strong signal
    anywhere passes; a weak signal (bare 'financ'/'hedg') only passes if it's in the
    TITLE — drops papers that merely name-drop 'financial sectors' in the abstract
    (ASP solvers, DatalogMTL, diffusion-model theory)."""
    title = (p.get("title") or "").lower()
    text = f"{title} {(p.get('abstract') or '').lower()}"
    if any(sig in text for sig in _STRONG_SIGNALS):
        return True
    return any(sig in title for sig in _WEAK_TITLE_SIGNALS)


def _cid(p: dict) -> str:
    key = p.get("paperId") or p.get("title", "")
    return hashlib.sha256(str(key).encode()).hexdigest()[:12]


def _to_candidate(p: dict) -> dict:
    return {
        "id": _cid(p),
        "title": p.get("title", ""),
        "venue": p.get("venue", ""),
        "year": p.get("year"),
        "abstract_short": (p.get("abstract") or "")[:400],
        "authors": [a.get("name") for a in (p.get("authors") or [])][:5],
        "url": p.get("url", ""),
        "fields_of_study": p.get("fieldsOfStudy") or [],
        "citation_count": p.get("citationCount"),
        "suggested_field": _suggest_field(p),
        "s2_id": p.get("paperId"),
    }


def _load() -> list[dict]:
    if not CANDIDATES.exists():
        return []
    return [json.loads(l) for l in CANDIDATES.read_text().splitlines() if l.strip()]


def fetch(years_back: int = 2, limit: int = 200) -> int:
    """Pull finance-relevant conf papers and append NEW ones to the candidate queue."""
    load_settings()  # ensure .env (S2_API_KEY) is loaded
    year_from = date.today().year - years_back
    raw = search_fin_conf_papers(VENUES, year_from=year_from, limit=limit)
    existing = {c["id"] for c in _load()}
    added = 0
    dropped_irrelevant = 0
    with CANDIDATES.open("a") as f:
        for p in raw:
            if not p.get("title"):
                continue
            if not _is_finance_relevant(p):
                dropped_irrelevant += 1
                continue
            c = _to_candidate(p)
            if c["id"] in existing:
                continue
            existing.add(c["id"])
            c["first_seen"] = date.today().isoformat()
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
            added += 1
    log.info("fin_frontier: %d raw → %d added, %d dropped (no finance signal)",
             len(raw), added, dropped_irrelevant)
    render()
    return added


def render() -> Path:
    cands = [c for c in _load() if not c.get("_resolved")]
    by_field: dict[str, list[dict]] = {}
    for c in cands:
        by_field.setdefault(c.get("suggested_field", "unmapped"), []).append(c)
    lines = ["# Fin-Frontier Candidates (top-conference, for human curation)", "",
             f"> {len(cands)} finance-relevant peer-reviewed conference papers "
             f"({', '.join(VENUES)}). **Read these to decide whether to refresh a field "
             "note or propose a new transfer cell** (`python -m pipeline.cells approve`). "
             "Not auto-fed to gap generation.", ""]
    for field in sorted(by_field):
        items = by_field[field]
        lines.append(f"## {field}  ({len(items)})")
        for c in sorted(items, key=lambda x: -(x.get("year") or 0)):
            cit = f" · {c['citation_count']} cites" if c.get("citation_count") else ""
            lines.append(f"- **{c['title']}** ({c.get('venue','')} {c.get('year','')}{cit})")
            if c.get("abstract_short"):
                lines.append(f"  - {c['abstract_short']}")
            if c.get("url"):
                lines.append(f"  - {c['url']}")
        lines.append("")
    REVIEW_MD.write_text("\n".join(lines))
    return REVIEW_MD


if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "fetch":
        years = int(sys.argv[sys.argv.index("--years") + 1]) if "--years" in sys.argv else 2
        limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else 200
        n = fetch(years_back=years, limit=limit)
        cands = _load()
        print(f"added {n} new; {len(cands)} total candidates → {render()}")
        from collections import Counter
        print("by suggested field:", dict(Counter(c.get("suggested_field") for c in cands)))
    elif cmd == "render":
        print("wrote", render())
    else:
        print(__doc__)
