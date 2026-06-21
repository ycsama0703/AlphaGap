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


import re

# Battlefield relevance (topic rebalancing, "b"): our AI×Fin battlefields are NLP/text, agents,
# time-series, retrieval, interpretability, RL-for-reasoning — NOT vision/robotics/bio, which dominate
# arxiv/HF trending (vision ~32% of the corpus) and crowd out on-battlefield papers via upvotes. These
# patterns re-weight priority so battlefield papers get L2-extracted + become anchors, instead of
# high-upvote vision noise. Computed from title+abstract+categories (available pre-L1). Reorders only —
# never drops a paper from candidacy.
# SPECIFIC patterns only — generic terms ("language model", "reasoning", "temporal", "embedding")
# match almost every modern AI paper and give no discrimination, so they're excluded. We want
# text-UNDERSTANDING / agent / retrieval / finance specifically, not "any LLM paper".
_BATTLEFIELD_PATTERNS = {
    "nlp_text": r"text classif|sentiment|summari|information extraction|named entity|entity recognition|"
                r"document understanding|reading comprehension|relation extraction|text mining|"
                r"financial text|10-?k|earnings call|transcript|filing",
    "agent_tool": r"multi-?agent|tool[- ]?use|tool[- ]?call|tool routing|\bReAct\b|agent orchestrat|"
                  r"agentic workflow|function calling",
    "reasoning_credit": r"chain-of-thought|credit assign|process reward|verifier|step-level|inference-time scaling",
    "retrieval": r"retrieval-augmented|\bRAG\b|dense passage|re-?ranking|passage retrieval",
    "time_series": r"time[- ]?series|forecasting|volatility model|regime (?:detect|switch)",
    "interpretability": r"sparse autoencoder|mechanistic interpretab|circuit analysis|feature attribution|probing classifier",
    "finance": r"financ|trading|portfolio|asset pricing|\bstock\b|equity return|\balpha\b|factor model|"
               r"volatilit|credit risk|market microstructure|\bq-fin",
}
# strong off-battlefield modality markers — a paper dominated by these is NOT our battlefield even
# if it also says "reasoning"/"language model" (multimodal LLM papers do). Penalised whenever present
# and the paper has NO finance battlefield hit (finance multimodal would be a rare legit exception).
_OFFFIELD_PATTERN = (r"image generation|diffusion model|\bvideo\b|\b3d\b|point cloud|\brobot|embodied|"
                     r"manipulation|autonomous driving|\bvision\b|visual question|multimodal|\bVLM\b|"
                     r"speech|audio|text-to-image|text-to-video|protein|molecul|drug discovery|\bgenom|"
                     r"image classif|object detection|segmentation|rendering")

# THEORY line — arxiv categories that carry transplantable foundational mechanisms
# (math/stats/optimization/probability/mathematical-finance). A paper in any of these
# is auto-admitted as a candidate (so it survives gate ①), and matching the theory
# mechanism dictionary (whitelist.theory_mechanisms) boosts its priority (gate ③).
_THEORY_CATEGORIES = {"stat.ML", "stat.ME", "math.ST", "math.OC", "math.PR", "q-fin.MF"}


@dataclass
class CandidateSignals:
    is_hf_daily: bool = False
    hf_upvotes: int = 0
    is_q_fin: bool = False
    named_author_match: list[str] = field(default_factory=list)
    institution_match: list[str] = field(default_factory=list)
    keyword_matches: list[str] = field(default_factory=list)
    title_keyword_hit: bool = False           # keyword in title (stronger signal than abstract)
    battlefields: list[str] = field(default_factory=list)   # which AI×Fin battlefields this paper hits
    offfield: bool = False                    # has strong vision/robotics/bio/multimodal modality markers
    is_theory: bool = False                   # THEORY line: in a theory arxiv category (stat/math/q-fin.MF)
    theory_mechanisms: list[str] = field(default_factory=list)  # transplantable-mechanism clusters hit

    @property
    def is_candidate(self) -> bool:
        return (
            self.is_hf_daily
            or self.is_q_fin
            or self.is_theory              # THEORY line: theory-category papers always candidate (gate ①)
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
        # battlefield relevance (topic rebalancing): boost on-battlefield, penalise off-modality noise.
        # finance hits count double (it's the whole point); generic LLM words no longer match (see patterns).
        bf = set(self.battlefields)
        score += 3.0 if "finance" in bf else 0.0
        score += 1.5 * min(len(bf - {"finance"}), 3)       # +1.5 per non-finance battlefield, cap 3
        # vision/robotics/bio/multimodal markers → sink it, UNLESS it's genuinely finance (rare exception)
        # or a mechanism-bearing THEORY paper (a robust estimator demoed on images is still a transplantable
        # mechanism — don't bury it for an incidental vision keyword).
        if self.offfield and "finance" not in bf and not self.is_q_fin \
                and not (self.is_theory and self.theory_mechanisms):
            score -= 6.0
        # THEORY line: a theory-category paper carrying transplantable mechanisms gets boosted into the
        # L2/deep-mine range (same magnitude as the AI×Fin battlefield boost, so it doesn't crowd out
        # the applied line). Base +1.0 for being theory; +1.5 per mechanism cluster (cap 3).
        if self.is_theory:
            score += 1.0
        score += 1.5 * min(len(self.theory_mechanisms), 3)
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
            "battlefields": self.battlefields,
            "offfield": self.offfield,
            "is_theory": self.is_theory,
            "theory_mechanisms": self.theory_mechanisms,
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


def _theory_mechanism_terms(whitelist: dict) -> list[tuple[str, str]]:
    """Flatten whitelist.theory_mechanisms into [(cluster, term_lower), ...].

    THEORY line dictionary: each term is a transplantable foundational mechanism, grouped by the
    finance structure it matches (regime_shift / distribution_shift / nonstationary_ts / ...).
    Editable in whitelist.yaml without touching code (precision-first: start narrow, widen later).
    """
    out: list[tuple[str, str]] = []
    for cluster, terms in (whitelist.get("theory_mechanisms", {}) or {}).items():
        for t in terms or []:
            out.append((cluster, t.lower()))
    return out


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

    # 6. Battlefield relevance (topic rebalancing) — which AI×Fin battlefields the paper hits,
    # and whether it's pure off-battlefield noise (vision/robotics/bio with no battlefield).
    cat_text = " ".join(cats).lower()
    relevance_hay = haystack + "\n" + cat_text
    sig.battlefields = [name for name, pat in _BATTLEFIELD_PATTERNS.items()
                        if re.search(pat, relevance_hay, re.I)]
    sig.offfield = bool(re.search(_OFFFIELD_PATTERN, relevance_hay, re.I))

    # 7. THEORY line — transplantable foundational mechanisms.
    # is_theory: paper is in a theory arxiv category (auto-candidate, gate ①).
    # theory_mechanisms: which mechanism clusters (whitelist.theory_mechanisms) the title/abstract hits.
    sig.is_theory = any(c in _THEORY_CATEGORIES for c in cats)
    hit_clusters: list[str] = []
    for cluster, term in _theory_mechanism_terms(wl):
        if term in haystack and cluster not in hit_clusters:
            hit_clusters.append(cluster)
    sig.theory_mechanisms = hit_clusters

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
