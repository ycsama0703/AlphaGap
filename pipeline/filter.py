"""Candidate filtering — cheap, no LLM.

Computes "candidate signals" for each paper using:
  - source (hf_daily = community signal)
  - arxiv categories (q-fin.* = Fin side, always candidate)
  - author name match (fin big-names list)
  - keyword match (title + abstract)
  - institution match (when affiliations are available — currently from S2 enrichment)

A paper becomes a candidate if ANY signal fires (OR logic). Multiple signals
boost its priority — used downstream to decide L2 extraction and ordering.

This step happens BEFORE LLM extraction to avoid paying to extract noise.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import load_whitelist


@dataclass
class CandidateSignals:
    is_hf_daily: bool = False
    hf_upvotes: int = 0
    is_q_fin: bool = False
    named_author_match: list[str] = field(default_factory=list)
    institution_match: list[str] = field(default_factory=list)
    keyword_matches: list[str] = field(default_factory=list)
    title_keyword_hit: bool = False           # keyword in title (stronger signal than abstract)

    @property
    def is_candidate(self) -> bool:
        return (
            self.is_hf_daily
            or self.is_q_fin
            or bool(self.named_author_match)
            or bool(self.institution_match)
            or bool(self.keyword_matches)
        )

    @property
    def priority_score(self) -> float:
        """Heuristic score for ordering — higher = more important to extract L2."""
        score = 0.0
        if self.is_hf_daily:
            score += 3.0 + min(self.hf_upvotes / 50.0, 5.0)  # cap upvote bonus
        if self.is_q_fin:
            score += 2.0
        score += 4.0 * len(self.named_author_match)
        score += 3.0 * len(self.institution_match)
        score += 0.5 * len(self.keyword_matches)
        if self.title_keyword_hit:
            score += 1.5
        return score

    def to_dict(self) -> dict:
        return {
            "is_hf_daily": self.is_hf_daily,
            "hf_upvotes": self.hf_upvotes,
            "is_q_fin": self.is_q_fin,
            "named_author_match": self.named_author_match,
            "institution_match": self.institution_match,
            "keyword_matches": self.keyword_matches,
            "title_keyword_hit": self.title_keyword_hit,
            "priority_score": round(self.priority_score, 2),
        }


# ---------- Whitelist helpers ----------

def _flat_keywords(whitelist: dict) -> dict[str, list[str]]:
    """Flatten nested keywords into {side: [all keywords]}."""
    out = {"ai": [], "fin": []}
    kw_root = whitelist.get("keywords", {})
    for src_key, side_label in [("ai_side", "ai"), ("fin_side", "fin")]:
        for group in kw_root.get(src_key, {}).values():
            out[side_label].extend(group)
    return out


def _flat_institutions(whitelist: dict) -> list[str]:
    inst = whitelist.get("institutions", {})
    return (
        inst.get("ai_industry", [])
        + inst.get("ai_academia", [])
        + inst.get("fin_industry", [])
        + inst.get("fin_academia", [])
    )


def _named_authors_fin(whitelist: dict) -> set[str]:
    return {n.lower() for n in whitelist.get("named_authors_fin", [])}


# ---------- Signal computation ----------

def compute_signals(paper: dict, whitelist: dict | None = None) -> CandidateSignals:
    """Compute candidate signals for one paper.

    paper expects:
      source, arxiv_categories, title, abstract, authors (list of {name, affiliations}),
      raw_meta (with hf_upvotes when source==hf_daily)
    """
    wl = whitelist or load_whitelist()
    sig = CandidateSignals()

    # 1. HF Daily signal
    if paper.get("source") == "hf_daily":
        sig.is_hf_daily = True
        sig.hf_upvotes = int(paper.get("raw_meta", {}).get("hf_upvotes", 0))

    # 2. q-fin.* arXiv category
    cats = paper.get("arxiv_categories", []) or []
    if any(c.startswith("q-fin") for c in cats):
        sig.is_q_fin = True

    # 3. Named author match (Fin big names)
    named_set = _named_authors_fin(wl)
    paper_author_names = {(a.get("name") or "").lower() for a in paper.get("authors", [])}
    sig.named_author_match = sorted(named_set & paper_author_names)

    # 4. Institution match (requires affiliations — usually after S2 enrichment)
    affil_text = " ".join(
        aff
        for a in paper.get("authors", [])
        for aff in (a.get("affiliations") or [])
    ).lower()
    if affil_text:
        institutions = _flat_institutions(wl)
        sig.institution_match = [
            inst for inst in institutions if inst.lower() in affil_text
        ]

    # 5. Keyword match (title + abstract)
    title = (paper.get("title") or "").lower()
    abstract = (paper.get("abstract") or "").lower()
    haystack = title + "\n" + abstract

    kw_by_side = _flat_keywords(wl)
    all_kws = kw_by_side["ai"] + kw_by_side["fin"]
    matches: list[str] = []
    title_hit = False
    for kw in all_kws:
        kw_l = kw.lower()
        if kw_l in haystack:
            matches.append(kw)
            if kw_l in title:
                title_hit = True
    sig.keyword_matches = matches
    sig.title_keyword_hit = title_hit

    return sig


# ---------- Convenience for batch use ----------

def filter_candidates(papers: list[dict]) -> list[tuple[dict, CandidateSignals]]:
    """Return only candidate papers, paired with their signals, sorted by priority desc."""
    wl = load_whitelist()
    scored = [(p, compute_signals(p, wl)) for p in papers]
    candidates = [(p, s) for (p, s) in scored if s.is_candidate]
    candidates.sort(key=lambda ps: ps[1].priority_score, reverse=True)
    return candidates


# ---------- CLI smoke test ----------

if __name__ == "__main__":
    import logging
    from datetime import date, timedelta

    from .fetchers.arxiv import fetch_recent as fetch_arxiv
    from .fetchers.hf_daily import fetch_for_date

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    since = date.today() - timedelta(days=2)
    arxiv_papers = fetch_arxiv(["cs.LG", "cs.CL", "q-fin.PM"], since, max_per_category=30)
    hf_papers = fetch_for_date(date.today())

    all_papers = []
    seen = set()
    for p in arxiv_papers + hf_papers:
        if p.arxiv_id in seen:
            continue
        seen.add(p.arxiv_id)
        all_papers.append({
            "source": p.source,
            "arxiv_id": p.arxiv_id,
            "title": p.title,
            "abstract": p.abstract,
            "authors": p.authors,
            "arxiv_categories": p.arxiv_categories,
            "raw_meta": p.raw_meta,
        })

    print(f"\nFetched {len(all_papers)} unique papers (arxiv + hf_daily)")
    candidates = filter_candidates(all_papers)
    print(f"Candidates after filter: {len(candidates)}\n")

    print("Top 10 by priority score:")
    for p, s in candidates[:10]:
        print(f"  [score {s.priority_score:5.1f}] {p['arxiv_id']} | {p['title'][:65]}")
        flags = []
        if s.is_hf_daily:
            flags.append(f"HF↑{s.hf_upvotes}")
        if s.is_q_fin:
            flags.append("q-fin")
        if s.named_author_match:
            flags.append(f"author={s.named_author_match}")
        if s.keyword_matches:
            flags.append(f"kw={s.keyword_matches[:3]}")
        if s.title_keyword_hit:
            flags.append("title-kw")
        print(f"      signals: {' | '.join(flags)}")
