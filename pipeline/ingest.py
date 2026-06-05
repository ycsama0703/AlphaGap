"""End-to-end ingest: fetch → filter → persist → L1 → L2.

Run via:
    python -m pipeline.ingest                    # default: today, all sources
    python -m pipeline.ingest --no-arxiv         # skip arxiv (debug)
    python -m pipeline.ingest --max-l1 20        # cap L1 calls for cost
"""
from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

from . import db
from .extract.concepts import extract_l1, extract_l2
from .fetchers import arxiv as arxiv_fetcher
from .fetchers import hf_daily as hf_fetcher
from .filter import compute_signals, filter_candidates
from .llm_client import LLMClient


log = logging.getLogger(__name__)

# Default config — tunable
DEFAULT_ARXIV_CATEGORIES = [
    "cs.LG", "cs.CL", "cs.AI", "cs.MA",
    "q-fin.PM", "q-fin.ST", "q-fin.TR", "q-fin.CP",
]
DEFAULT_LOOKBACK_DAYS = 1
L2_PRIORITY_THRESHOLD = 5.0   # only L2-extract papers with priority >= this


def fetch_all(arxiv_cats: list[str], lookback_days: int, *, include_arxiv: bool = True,
              include_hf: bool = True) -> list[dict]:
    """Fetch from all configured sources, dedupe by arxiv_id, return list of paper dicts."""
    since = date.today() - timedelta(days=lookback_days)
    by_id: dict[str, dict] = {}

    if include_arxiv:
        try:
            for p in arxiv_fetcher.fetch_recent(arxiv_cats, since, max_per_category=200):
                by_id[p.arxiv_id] = _record_to_dict(p)
        except Exception as e:
            log.warning("arXiv fetch failed (non-fatal, continuing with HF only): %s", e)

    if include_hf:
        # HF Daily for each day in the lookback window
        d = since
        while d <= date.today():
            try:
                for p in hf_fetcher.fetch_for_date(d):
                    if p.arxiv_id in by_id:
                        # HF Daily metadata is richer — merge raw_meta and override source
                        existing = by_id[p.arxiv_id]
                        existing["raw_meta"] = {**existing.get("raw_meta", {}), **p.raw_meta}
                        existing["source"] = "hf_daily"  # boost source signal
                    else:
                        by_id[p.arxiv_id] = _record_to_dict(p)
            except Exception as e:
                log.warning("HF Daily fetch failed for %s: %s", d, e)
            d += timedelta(days=1)

    return list(by_id.values())


def persist_papers(papers: list[dict]) -> int:
    """Insert papers + signals. Returns number of candidates."""
    n_candidates = 0
    with db.connect() as conn:
        for p in papers:
            paper_id = _canonical_id_for_trigger(conn, p)
            stored = {**p, "id": paper_id}
            db.upsert_paper(conn, stored)
            source_record_id = p.get("arxiv_id") or paper_id
            db.upsert_paper_source(
                conn,
                paper_id=paper_id,
                source=p["source"],
                source_record_id=source_record_id,
                role="trigger",
                eligible_for_daily_trigger=1,
                raw_meta=p.get("raw_meta", {}),
            )
            if p.get("arxiv_id"):
                db.upsert_external_id(
                    conn,
                    source="arxiv",
                    external_id=p["arxiv_id"],
                    paper_id=paper_id,
                )
            sig = compute_signals(p)
            db.upsert_signals(conn, paper_id, sig.to_dict())
            if sig.is_candidate:
                n_candidates += 1
    return n_candidates


def _canonical_id_for_trigger(conn, paper: dict) -> str:
    """Reuse an evidence-only canonical row when a later trigger observes it."""
    arxiv_id = paper.get("arxiv_id")
    if arxiv_id:
        external_match = db.find_paper_by_external_id(conn, "arxiv", arxiv_id)
        if external_match:
            return external_match
        direct = conn.execute(
            "SELECT id FROM papers WHERE id = ? OR arxiv_id = ? LIMIT 1",
            (paper["id"], arxiv_id),
        ).fetchone()
        if direct:
            return direct["id"]

    evidence_matches = conn.execute(
        """
        SELECT p.id
        FROM papers p
        WHERE lower(trim(p.title)) = lower(trim(?))
          AND EXISTS (
              SELECT 1 FROM paper_sources ps
              WHERE ps.paper_id = p.id
                AND ps.eligible_for_daily_trigger = 0
          )
          AND NOT EXISTS (
              SELECT 1 FROM paper_sources ps
              WHERE ps.paper_id = p.id
                AND ps.eligible_for_daily_trigger = 1
          )
        """,
        (paper["title"],),
    ).fetchall()
    if len(evidence_matches) == 1:
        return evidence_matches[0]["id"]
    return paper["id"]


def extract_pending(
    *,
    max_l1: int = 100,
    max_l2: int = 30,
    include_evidence: bool = False,
    evidence_only: bool = False,
) -> dict:
    """Run L1 on pending candidates, then L2 on top by priority. Both on the cheap default model:
    L1 is coarse triage; L2's content is no longer consumed downstream (the engineering gap line
    that read it is retired) — it only flags 'has L2' for anchor ranking, so cheap is fine."""
    client = LLMClient()
    stats = {"l1_done": 0, "l1_failed": 0, "l2_done": 0, "l2_failed": 0}

    with db.connect() as conn:
        pending = db.fetch_pending_for_l1(
            conn,
            limit=max_l1,
            include_evidence=include_evidence,
            evidence_only=evidence_only,
        )
        log.info("L1 candidates pending: %d (cap=%d)", len(pending), max_l1)

        for row in pending:
            paper_dict = {
                "title": row["title"],
                "abstract": row["abstract"] or "",
                "affiliations": row["affiliations"] or "",
                "arxiv_categories": row["arxiv_categories"] or "",
            }
            try:
                l1 = extract_l1(client, paper_dict)
                db.upsert_extraction_l1(conn, row["id"], l1)
                stats["l1_done"] += 1
            except Exception as e:
                log.error("L1 failed for %s: %s", row["id"], e)
                db.mark_extraction_failed(conn, row["id"], "l1", str(e))
                stats["l1_failed"] += 1
        conn.commit()

        # L2 on high-priority subset
        l2_pending = db.fetch_pending_for_l2(
            conn,
            L2_PRIORITY_THRESHOLD,
            limit=max_l2,
            include_evidence=include_evidence,
            evidence_only=evidence_only,
        )
        log.info("L2 candidates: %d (priority >= %.1f, cap=%d)",
                 len(l2_pending), L2_PRIORITY_THRESHOLD, max_l2)

        for row in l2_pending:
            paper_dict = {"title": row["title"], "abstract": row["abstract"] or ""}
            l1 = {"side": row["side"], "method_primary": row["method_primary"], "domain": row["domain"]}
            try:
                l2 = extract_l2(client, paper_dict, l1)
                db.upsert_extraction_l2(conn, row["id"], l2)
                stats["l2_done"] += 1
            except Exception as e:
                log.error("L2 failed for %s: %s", row["id"], e)
                stats["l2_failed"] += 1

    in_tok, out_tok = client.total_tokens
    stats["tokens_in"] = in_tok
    stats["tokens_out"] = out_tok
    stats["cost_usd"] = round(client.estimate_cost_usd(), 4)
    return stats


def run_ingest(*, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
               max_l1: int = 100, max_l2: int = 30,
               include_arxiv: bool = True, include_hf: bool = True) -> dict:
    log.info("=== AlphaGap ingest start ===")
    papers = fetch_all(DEFAULT_ARXIV_CATEGORIES, lookback_days,
                       include_arxiv=include_arxiv, include_hf=include_hf)
    log.info("Fetched %d unique papers (lookback=%d days)", len(papers), lookback_days)

    n_candidates = persist_papers(papers)
    log.info("Persisted papers; %d candidates", n_candidates)

    extract_stats = extract_pending(max_l1=max_l1, max_l2=max_l2)
    log.info("Extraction: L1 done=%d failed=%d | L2 done=%d failed=%d | $%s",
             extract_stats["l1_done"], extract_stats["l1_failed"],
             extract_stats["l2_done"], extract_stats["l2_failed"],
             extract_stats["cost_usd"])

    final = db.stats_today()
    log.info("=== Done. DB stats: %s ===", final)
    return {**extract_stats, "fetched": len(papers), "candidates": n_candidates, **final}


# ---------- CLI ----------

def _record_to_dict(p) -> dict:
    return {
        "id": p.id,
        "source": p.source,
        "arxiv_id": p.arxiv_id,
        "title": p.title,
        "abstract": p.abstract,
        "authors": p.authors,
        "publication_date": p.publication_date,
        "arxiv_categories": p.arxiv_categories,
        "url": p.url,
        "raw_meta": p.raw_meta,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback", type=int, default=DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--max-l1", type=int, default=20, help="Cap L1 calls (cost control)")
    parser.add_argument("--max-l2", type=int, default=10, help="Cap L2 calls")
    parser.add_argument("--no-arxiv", action="store_true")
    parser.add_argument("--no-hf", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    db.init_schema()
    run_ingest(
        lookback_days=args.lookback,
        max_l1=args.max_l1,
        max_l2=args.max_l2,
        include_arxiv=not args.no_arxiv,
        include_hf=not args.no_hf,
    )
