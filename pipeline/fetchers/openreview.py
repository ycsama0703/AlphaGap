"""OpenReview fetcher — conference papers with venue / decision / review_scores.

Primary use: pull ICLR oral/spotlight/poster submissions and their review
metadata to populate the AI mechanism evidence library. Per the v2 upgrade
plan (§2.6), OpenReview observations are tagged `role='evidence'` and
`eligible_for_daily_trigger=0` — they enrich AI mechanism family maturity
but never trigger daily gap candidates.

API: uses `openreview-py` v2+ client. ICLR 2024+ uses the api2 endpoint
(`https://api2.openreview.net`). Earlier years may need the legacy
`https://api.openreview.net` client; we try api2 first and fall back.

Functions
---------
discover(venue, year)
    Quick smoke test: returns count of submissions, decision breakdown,
    review-score availability, and a small sample. Used during Phase 1
    task 1.4 probe before committing to a full backfill.

fetch_evidence(venue, year, decision_filter=None, limit=None)
    Full fetch. Returns PaperRecord objects with raw_meta populated with
    venue / decision / review_scores so the ingest layer can route them
    into `paper_sources`.
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import Iterator

from .arxiv import PaperRecord


log = logging.getLogger(__name__)


_API2_URL = "https://api2.openreview.net"
_API_LEGACY_URL = "https://api.openreview.net"


# Invitation templates by venue. Tweak per year as OpenReview changes them.
# Verified for ICLR 2024-2026 — older years may need different IDs.
_SUBMISSION_INVITATION = {
    "ICLR": "ICLR.cc/{year}/Conference/-/Submission",
}

# In the api2 schema (ICLR 2024+), decisions are NOT separate notes.
# They're encoded in each submission's content.venue + content.venueid.
# Observed venue labels (probed 2026-05-26 against ICLR 2025):
#   "ICLR 2025 Oral"                                  → oral
#   "ICLR 2025 Spotlight"                             → spotlight
#   "ICLR 2025 Poster"                                → poster
#   "ICLR 2025 Conference Withdrawn Submission"       → withdraw
#   "ICLR 2025 Conference Desk Rejected Submission"   → desk_reject
#   "Submitted to ICLR 2025"                          → pending/unknown outcome


def _get_client(use_api2: bool = True):
    """Return an OpenReview client. api2 for ICLR 2024+, legacy for older."""
    import openreview
    if use_api2:
        return openreview.api.OpenReviewClient(baseurl=_API2_URL)
    return openreview.Client(baseurl=_API_LEGACY_URL)


def _submission_invitation(venue: str, year: int) -> str:
    tpl = _SUBMISSION_INVITATION.get(venue.upper())
    if not tpl:
        raise ValueError(f"unknown venue '{venue}' (supported: {list(_SUBMISSION_INVITATION)})")
    return tpl.format(year=year)


# ---------------------------------------------------------------------------
# Decision extraction
# ---------------------------------------------------------------------------

def _normalize_decision(raw: str | None) -> str | None:
    """Map venue labels / decision strings to a canonical set.

    Accepts both api2 venue labels (ICLR 2025+) and legacy decision text.
    """
    if not raw:
        return None
    s = raw.lower()
    # Order matters: 'oral' / 'spotlight' before generic 'accept' / 'poster'.
    if "oral" in s:
        return "oral"
    if "spotlight" in s:
        return "spotlight"
    if "desk" in s and "reject" in s:
        return "desk_reject"
    if "withdraw" in s:
        return "withdraw"
    if "rejected_submission" in s or "rejected submission" in s:
        return "reject"
    if "submitted to" in s:
        # This label is also present before decisions are released. Treat it
        # as pending rather than manufacturing negative evidence.
        return "pending"
    if "poster" in s:
        return "poster"
    # Legacy fallbacks for older venue formats.
    if s.startswith("accept") and "reject" not in s:
        return "poster"
    if "reject" in s:
        return "reject"
    return None


def _decision_from_submission(note) -> str | None:
    """Read decision from a submission's content.venue / content.venueid (api2)."""
    c = _content_dict(note)
    # Prefer the human-readable label; fall back to venueid path.
    label = _value(c, "venue") or _value(c, "venueid") or ""
    return _normalize_decision(str(label))


def _content_dict(note) -> dict:
    """Get the content dict from a note, handling both api2 and legacy shapes."""
    c = getattr(note, "content", None)
    if isinstance(c, dict):
        return c
    return {}


def _value(content: dict, key: str, default=None):
    """Read a field from api2 content (wrapped in {'value': X}) or legacy (raw)."""
    v = content.get(key, default)
    if isinstance(v, dict) and "value" in v:
        return v["value"]
    return v


# ---------------------------------------------------------------------------
# Review scores
# ---------------------------------------------------------------------------

_RATING_RE = re.compile(r"^\s*(\d+)")


def _parse_rating(s: str | None) -> int | None:
    """Extract leading integer from a rating string like '7: Strong Accept'."""
    if not s:
        return None
    m = _RATING_RE.match(s)
    return int(m.group(1)) if m else None


def _review_scores_for_paper(client, paper_id: str) -> list[int]:
    """Fetch official review notes for a submission and return numeric ratings.

    Returns empty list if reviews are private or no reviews found.
    """
    try:
        # api2: reviews are notes whose `forum` == paper_id and invitation matches reviewer
        notes = client.get_all_notes(forum=paper_id)
    except Exception as e:
        log.debug("review fetch failed for %s: %s", paper_id, e)
        return []
    scores: list[int] = []
    for n in notes:
        inv = (getattr(n, "invitations", None) or [getattr(n, "invitation", "")])
        inv_str = " ".join(inv) if isinstance(inv, list) else str(inv)
        if "Official_Review" not in inv_str and "Reviewer" not in inv_str:
            continue
        c = _content_dict(n)
        # api2 uses 'rating'; some venues use 'recommendation'
        for field in ("rating", "recommendation", "score"):
            v = _value(c, field)
            r = _parse_rating(str(v) if v is not None else None)
            if r is not None:
                scores.append(r)
                break
    return scores


# ---------------------------------------------------------------------------
# Discovery probe (Phase 1 task 1.4)
# ---------------------------------------------------------------------------

def discover(venue: str, year: int, *, max_review_probe: int = 5) -> dict:
    """Quick probe: count submissions, decision breakdown, review availability.

    Returns
    -------
    {
      "venue": "ICLR",
      "year": 2026,
      "submission_invitation": "ICLR.cc/2026/Conference/-/Submission",
      "submissions_found": int,
      "decisions_found": int,
      "decision_breakdown": {"oral": 50, "spotlight": 100, "poster": 800, "reject": 5000, None: 100},
      "with_review_scores": int / max_review_probe,
      "sample_papers": [{title, decision, n_reviews, ...}, ...],
      "errors": [...],
    }
    """
    client = _get_client(use_api2=True)
    inv = _submission_invitation(venue, year)
    out: dict = {
        "venue": venue,
        "year": year,
        "submission_invitation": inv,
        "errors": [],
    }

    try:
        submissions = client.get_all_notes(invitation=inv)
    except Exception as e:
        out["errors"].append(f"submissions fetch failed: {e}")
        submissions = []
    out["submissions_found"] = len(submissions)

    # Decision now read directly from each submission's content.venue field.
    breakdown: dict[str, int] = {}
    submissions_with_decision = []  # (note, decision)
    for n in submissions:
        decision = _decision_from_submission(n)
        key = decision or "unknown"
        breakdown[key] = breakdown.get(key, 0) + 1
        submissions_with_decision.append((n, decision))
    out["decisions_found"] = sum(v for k, v in breakdown.items() if k != "unknown")
    out["decision_breakdown"] = breakdown

    # Sample N accepted (oral/spotlight/poster) papers and probe their reviews.
    sample = []
    with_scores = 0
    review_probe_count = 0
    accepted_decisions = {"oral", "spotlight", "poster"}
    for n, decision in submissions_with_decision:
        if review_probe_count >= max_review_probe:
            break
        if decision not in accepted_decisions:
            continue
        nid = getattr(n, "id", None)
        c = _content_dict(n)
        title = _value(c, "title") or ""
        scores = _review_scores_for_paper(client, nid) if nid else []
        if scores:
            with_scores += 1
        sample.append({
            "id": nid,
            "title": str(title)[:120],
            "decision": decision,
            "n_reviews": len(scores),
            "review_scores": scores,
        })
        review_probe_count += 1

    # If no accepted papers were sampled (e.g. year still under review),
    # fall back to first N submissions so the probe always shows shape.
    if not sample and submissions_with_decision:
        for n, decision in submissions_with_decision[:max_review_probe]:
            c = _content_dict(n)
            sample.append({
                "id": getattr(n, "id", None),
                "title": str(_value(c, "title") or "")[:120],
                "decision": decision,
                "n_reviews": None,
                "review_scores": [],
            })

    out["with_review_scores"] = with_scores
    out["review_probe_attempts"] = review_probe_count
    out["sample_papers"] = sample
    return out


# ---------------------------------------------------------------------------
# Full evidence fetch
# ---------------------------------------------------------------------------

def fetch_evidence(venue: str, year: int,
                   decision_filter: list[str] | None = None,
                   *,
                   limit: int | None = None,
                   fetch_review_scores: bool = True) -> list[PaperRecord]:
    """Fetch OpenReview submissions as PaperRecord objects.

    Parameters
    ----------
    venue : str
        e.g. 'ICLR'
    year : int
        e.g. 2026
    decision_filter : list[str] or None
        If provided, only return papers whose normalized decision is in this
        list. E.g. `['oral', 'spotlight']` for the Phase 1 backfill.
    limit : int or None
        Hard cap on number of records returned (Phase 1 budget guard).
    fetch_review_scores : bool
        If True, fetch review notes for each kept paper (slow). Disable for
        the discovery probe.

    Returns
    -------
    list[PaperRecord]
        Each record has raw_meta populated with:
          openreview_id, venue, decision, review_scores, year,
          openreview_url, source_observation_role='evidence',
          eligible_for_daily_trigger=0
        so the ingest layer can write a `paper_sources` row.
    """
    client = _get_client(use_api2=True)
    inv = _submission_invitation(venue, year)

    log.info("OpenReview: fetching submissions for %s %d", venue, year)
    submissions = client.get_all_notes(invitation=inv)
    log.info("OpenReview: %d submissions found", len(submissions))

    results: list[PaperRecord] = []
    for n in submissions:
        if limit is not None and len(results) >= limit:
            break
        nid = getattr(n, "id", None)
        if not nid:
            continue

        # Read decision from the submission itself (api2 schema).
        decision = _decision_from_submission(n)
        if decision_filter and decision not in decision_filter:
            continue

        rec = _submission_to_record(n, venue, year, decision)
        if rec is None:
            continue

        # Fetch review scores only for accepted papers (rejects rarely have
        # public reviews and aren't useful evidence).
        if fetch_review_scores and decision in ("oral", "spotlight", "poster"):
            scores = _review_scores_for_paper(client, nid)
            rec.raw_meta["review_scores"] = scores

        results.append(rec)

    log.info("OpenReview: returning %d records (decision_filter=%s, limit=%s)",
             len(results), decision_filter, limit)
    return results


def _submission_to_record(note, venue: str, year: int, decision: str | None) -> PaperRecord | None:
    """Convert an OpenReview note to a PaperRecord."""
    nid = getattr(note, "id", None)
    if not nid:
        return None
    c = _content_dict(note)
    title = (_value(c, "title") or "").strip()
    abstract = (_value(c, "abstract") or "").strip()
    if not title:
        return None

    authors_field = _value(c, "authors")
    if isinstance(authors_field, list):
        authors = [{"name": str(a).strip(), "affiliations": []} for a in authors_field if a]
    else:
        authors = []

    paperhash = _value(c, "paperhash")
    arxiv_id = _extract_arxiv_id(c)

    # Publication date: notes have cdate (created) / mdate (modified) timestamps in ms.
    cdate_ms = getattr(note, "cdate", None) or getattr(note, "tcdate", None)
    pub_date = date.today()
    if isinstance(cdate_ms, (int, float)):
        try:
            pub_date = datetime.fromtimestamp(cdate_ms / 1000, tz=timezone.utc).date()
        except Exception:
            pass

    venue_label = f"{venue} {year}"
    openreview_url = f"https://openreview.net/forum?id={nid}"

    return PaperRecord(
        id=arxiv_id or f"openreview:{nid}",
        source="openreview",
        arxiv_id=arxiv_id,
        title=" ".join(title.split()),
        abstract=" ".join(abstract.split()),
        authors=authors,
        publication_date=pub_date,
        arxiv_categories=[],
        url=openreview_url,
        raw_meta={
            "openreview_id": nid,
            "openreview_url": openreview_url,
            "venue": venue_label,
            "venue_short": venue,
            "venue_year": year,
            "decision": decision,
            "paperhash": paperhash,
            # Observation contract for the ingest layer (per v2 §3.1):
            #   role='evidence', eligible_for_daily_trigger=0 means this
            #   paper enriches AI mechanism family maturity but does NOT
            #   appear in daily gap candidate queries.
            "source_observation_role": "evidence",
            "eligible_for_daily_trigger": 0,
        },
    )


def _extract_arxiv_id(content: dict) -> str | None:
    """Best-effort extraction of an arXiv id from common OpenReview fields."""
    for field in ("arxiv_id", "arxiv", "_bibtex", "bibtex", "pdf", "html", "url"):
        value = _value(content, field)
        if value is None:
            continue
        text = str(value)
        if field not in {"arxiv_id", "arxiv"} and "arxiv" not in text.lower():
            continue
        match = re.search(
            r"(?:arxiv(?:\.org/(?:abs|pdf)/|:)\s*)?(\d{4}\.\d{4,5})(?:v\d+)?",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return None


# ---------------------------------------------------------------------------
# CLI: small probe entry
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import json as _json

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) >= 3 and sys.argv[1] == "discover":
        venue = sys.argv[2]
        year = int(sys.argv[3]) if len(sys.argv) > 3 else date.today().year
        result = discover(venue, year, max_review_probe=5)
        print(_json.dumps(result, indent=2, default=str))
    elif len(sys.argv) >= 3 and sys.argv[1] == "fetch":
        venue = sys.argv[2]
        year = int(sys.argv[3]) if len(sys.argv) > 3 else date.today().year
        records = fetch_evidence(
            venue, year,
            decision_filter=["oral", "spotlight"],
            limit=5,
            fetch_review_scores=True,
        )
        for r in records:
            print(f"[{r.raw_meta.get('decision')}] {r.title[:80]}")
            print(f"   scores={r.raw_meta.get('review_scores')} url={r.url}")
        print(f"\nTotal: {len(records)} records")
    else:
        print("Usage:")
        print("  python -m pipeline.fetchers.openreview discover ICLR 2026")
        print("  python -m pipeline.fetchers.openreview fetch ICLR 2026")
