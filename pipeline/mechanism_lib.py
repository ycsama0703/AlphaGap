"""AI mechanism family library — retrieval + LLM adjudication.

Per upgrade plan v2 §3.4: when a new paper's L1 mechanism description
arrives, decide whether it joins an existing family or starts a new one.
Three-step pipeline:

  Step A (transfer screen, LLM):
    Decide whether the paper exposes a reusable mechanism that maps to a
    concrete bottleneck in one of the maintained finance fields. Persist the
    decision and a family-level projection. Domain-specific papers that offer
    no defensible finance bridge are retained as evidence but do not enter
    the family library.

  Step B (retrieval, cheap):
    Embed the paper's mechanism description.
    Cosine-similarity against representative_one_liner of every existing
    family. Return top-K candidates.

  Step C (LLM adjudication, only for transferable evidence):
    Send paper mechanism + top-K family descriptions to LLM.
    LLM picks one of:
      - match: <family_id>     + confidence  → write 'accepted' membership
      - new_family             + name/one_liner for the new family
      - ambiguous              + reason → write 'proposed' for top-1 with needs_review=1

Idempotency
-----------
- Adjudicating the same paper twice is a no-op via the
  UNIQUE(paper_id, family_id, mechanism_slot) constraint on
  mechanism_memberships and the partial unique index on accepted rows.
- New families are created with canonical_status='auto_draft' so a
  human can review/merge them later via the canonical_status state
  machine.

Constraints (per plan §2.1)
---------------------------
- Maturity is *not* used as a gate here; it's computed downstream.
- LLM adjudication uses the configured default model (DeepSeek in
  current setup); see UPGRADE_PLAN §8 open question 2 for upgrade path.
"""
from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Iterable, Sequence

import numpy as np

from . import db
from .llm_client import LLMClient


log = logging.getLogger(__name__)


# --- Embedding model -------------------------------------------------------

# all-MiniLM-L6-v2: 80MB, 384-dim, good retrieval quality for short sentences.
# Locks the model at module load time so repeat calls don't re-load.
_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_embed_model = None  # lazy-init


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer
        log.info("loading embedding model %s ...", _EMBED_MODEL_NAME)
        _embed_model = SentenceTransformer(_EMBED_MODEL_NAME)
    return _embed_model


def _embed(texts: Sequence[str]) -> np.ndarray:
    """Embed a batch of strings. Returns (n, d) float32 array, L2-normalized
    so cosine = dot product.
    """
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = _get_embed_model()
    vecs = model.encode(
        list(texts),
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    return vecs.astype(np.float32)


# --- Family library --------------------------------------------------------

@dataclass
class FamilyRecord:
    family_id: str
    representative_one_liner: str
    what_problem: str
    shared_approach: str
    contrast_to_prior: str
    canonical_status: str
    member_count: int


def _new_family_id() -> str:
    """Generate a stable, human-readable family id."""
    # 'ai-mech-<short-uuid>'. Short uuid avoids collisions; sortable by
    # creation order via 'created_at' column.
    return f"ai-mech-{uuid.uuid4().hex[:10]}"


def load_all_families(conn) -> list[FamilyRecord]:
    """Load every non-deprecated, non-merged family + its current member count."""
    rows = conn.execute("""
        SELECT
            f.family_id, f.representative_one_liner,
            COALESCE(f.what_problem, '')      AS what_problem,
            COALESCE(f.shared_approach, '')   AS shared_approach,
            COALESCE(f.contrast_to_prior, '') AS contrast_to_prior,
            f.canonical_status,
            COALESCE((
                SELECT COUNT(*) FROM mechanism_memberships m
                WHERE m.family_id = f.family_id
                  AND m.membership_status = 'accepted'
            ), 0) AS member_count
        FROM mechanism_families f
        WHERE f.canonical_status NOT IN ('merged', 'deprecated')
        ORDER BY f.created_at
    """).fetchall()
    return [FamilyRecord(**dict(r)) for r in rows]


def family_index(families: list[FamilyRecord]) -> tuple[list[str], np.ndarray]:
    """Compute embedding matrix for current families. Returns (ids, vecs)."""
    if not families:
        return [], np.zeros((0, 384), dtype=np.float32)
    texts = [
        # Concatenate the two strongest fields. shared_approach and
        # contrast are not always present, but representative_one_liner
        # + what_problem capture the gist well.
        f"{fam.representative_one_liner} | problem: {fam.what_problem}".strip()
        for fam in families
    ]
    vecs = _embed(texts)
    return [f.family_id for f in families], vecs


def find_top_k(query_text: str, family_vecs: np.ndarray,
               family_ids: list[str], k: int = 5) -> list[tuple[str, float]]:
    """Return top-K (family_id, cosine_similarity) for a query embedding.

    Uses L2-normalized embeddings so cosine == dot product.
    """
    if family_vecs.shape[0] == 0:
        return []
    q = _embed([query_text])  # (1, d)
    sims = (family_vecs @ q.T).flatten()  # (n,)
    k = min(k, len(family_ids))
    top_idx = np.argpartition(-sims, range(k))[:k]
    top_idx = top_idx[np.argsort(-sims[top_idx])]
    return [(family_ids[i], float(sims[i])) for i in top_idx]


# --- Maturity (venue-weighted) --------------------------------------------
#
# Phase 1 observation (UPGRADE_PLAN v2 §7 task 1.7):
#   1000-paper backfill produced 986 families with 98% singletons.
#   ICLR oral/spotlight papers are inherently distinct contributions, so
#   plain member_count fails as a maturity signal — almost everything
#   would be tagged 'emerging'.
#
# Fix: compute maturity from VENUE-WEIGHTED evidence instead of raw count.
# A single ICLR oral paper is a stronger maturity signal than three random
# arXiv preprints, because peer review filtered noise.
#
# Weights are calibrated so:
#   - 1 ICLR oral alone (weight 3.0) → 'supported'  (not 'emerging')
#   - 1 ICLR spotlight alone (weight 2.0) → 'emerging' (close to supported)
#   - 2 spotlights or 1 oral + 1 spotlight → 'supported' (weight 4-5)
#   - 2 orals OR 3 spotlights → 'mature' (weight 6+)
#   - HF Daily / arXiv preprint contribute 0.5 each (early signal, weak)
#
# These are intentionally simple; tune with Phase 1 task 1.7 findings.
VENUE_WEIGHTS: dict[str, float] = {
    # ICLR
    "ICLR Oral":       3.0,
    "ICLR Spotlight":  2.0,
    "ICLR Poster":     1.0,
    # NeurIPS / ICML / ACL — set when those backfills land
    "NeurIPS Oral":      3.0,
    "NeurIPS Spotlight": 2.0,
    "NeurIPS Poster":    1.0,
    "ICML Oral":         3.0,
    "ICML Spotlight":    2.0,
    "ICML Poster":       1.0,
    "ACL Oral":          3.0,
    "ACL Findings":      0.8,
    # Generic fallbacks
    "hf_daily":          0.5,
    "arxiv":             0.5,
}

# Weight tiers — emerging/supported/mature ranges.
# 'emerging' is intentionally wide so frontier-but-promising work stays
# discoverable in gap detection rather than getting filtered out.
MATURITY_THRESHOLD_SUPPORTED = 2.5   # ≥ this = 'supported'
MATURITY_THRESHOLD_MATURE    = 6.0   # ≥ this = 'mature'


def _weight_for_member(source: str, venue: str | None, decision: str | None) -> float:
    """Map a single paper_sources observation to a venue-weight.

    Resolution order:
      1. Try '<venue_short> <Decision>' key (e.g. 'ICLR Oral')
      2. Try generic source key ('hf_daily', 'arxiv')
      3. Default to 0.3 (unknown source still counts as faint evidence)
    """
    if venue and decision:
        # venue stored as e.g. 'ICLR 2025' → split to 'ICLR'
        venue_short = venue.split()[0] if venue else ""
        decision_cap = (decision or "").capitalize()
        key = f"{venue_short} {decision_cap}"
        if key in VENUE_WEIGHTS:
            return VENUE_WEIGHTS[key]
    if source in VENUE_WEIGHTS:
        return VENUE_WEIGHTS[source]
    return 0.3


def _maturity_tier(total_weight: float) -> str:
    if total_weight >= MATURITY_THRESHOLD_MATURE:
        return "mature"
    if total_weight >= MATURITY_THRESHOLD_SUPPORTED:
        return "supported"
    return "emerging"


def compute_maturity(family_id: str, conn=None) -> dict:
    """Compute venue-weighted maturity for a single family.

    Returns:
      {
        "family_id": str,
        "member_count": int,        # accepted memberships only
        "total_weight": float,
        "tier": "emerging" | "supported" | "mature",
        "venue_breakdown": {"ICLR Oral": 2, "ICLR Spotlight": 1, "hf_daily": 3, ...},
      }

    If conn is None, opens its own connection.
    """
    own_conn = conn is None
    if own_conn:
        ctx = db.connect()
        conn = ctx.__enter__()
    try:
        # A paper can have multiple discovery/venue observations. Those are
        # not independent support for a mechanism; use its strongest evidence
        # once and retain the all-observation count only for diagnostics.
        rows = conn.execute("""
            SELECT m.paper_id, p.source AS legacy_source,
                   ps.source AS obs_source, ps.venue, ps.decision
            FROM mechanism_memberships m
            JOIN papers p ON p.id = m.paper_id
            LEFT JOIN paper_sources ps ON ps.paper_id = m.paper_id
            WHERE m.family_id = ?
              AND m.membership_status = 'accepted'
        """, (family_id,)).fetchall()

        best_by_paper: dict[str, tuple[float, str]] = {}
        observation_breakdown: dict[str, int] = {}
        for r in rows:
            obs_source = r["obs_source"]
            if obs_source:
                w = _weight_for_member(obs_source, r["venue"], r["decision"])
                # Key for breakdown reporting:
                if r["venue"] and r["decision"]:
                    venue_short = (r["venue"] or "").split()[0]
                    key = f"{venue_short} {(r['decision'] or '').capitalize()}"
                else:
                    key = obs_source
            else:
                # No paper_sources observation — use legacy `papers.source`
                w = _weight_for_member(r["legacy_source"], None, None)
                key = f"{r['legacy_source']} (legacy)"
            observation_breakdown[key] = observation_breakdown.get(key, 0) + 1
            current = best_by_paper.get(r["paper_id"])
            if current is None or w > current[0]:
                best_by_paper[r["paper_id"]] = (w, key)

        total = sum(item[0] for item in best_by_paper.values())
        breakdown: dict[str, int] = {}
        for _, key in best_by_paper.values():
            breakdown[key] = breakdown.get(key, 0) + 1

        return {
            "family_id": family_id,
            "member_count": len(best_by_paper),
            "total_weight": round(total, 2),
            "tier": _maturity_tier(total),
            "venue_breakdown": breakdown,
            "observation_breakdown": observation_breakdown,
        }
    finally:
        if own_conn:
            ctx.__exit__(None, None, None)


def maturity_distribution(conn=None) -> dict:
    """Library-wide maturity report.

    Useful to monitor whether tiers are well-distributed. If the entire
    library is 'emerging', thresholds may need lowering.
    """
    own_conn = conn is None
    if own_conn:
        ctx = db.connect()
        conn = ctx.__enter__()
    try:
        families = conn.execute(
            "SELECT family_id FROM mechanism_families "
            "WHERE canonical_status NOT IN ('merged', 'deprecated')"
        ).fetchall()
        tiers = {"emerging": 0, "supported": 0, "mature": 0}
        weights = []
        member_counts = []
        for f in families:
            m = compute_maturity(f[0], conn=conn)
            tiers[m["tier"]] += 1
            weights.append(m["total_weight"])
            member_counts.append(m["member_count"])
        return {
            "total_families": len(families),
            "by_tier": tiers,
            "weight_stats": {
                "min": min(weights) if weights else 0,
                "max": max(weights) if weights else 0,
                "mean": round(sum(weights) / len(weights), 2) if weights else 0,
            },
            "member_count_stats": {
                "min": min(member_counts) if member_counts else 0,
                "max": max(member_counts) if member_counts else 0,
                "mean": round(sum(member_counts) / len(member_counts), 2) if member_counts else 0,
            },
        }
    finally:
        if own_conn:
            ctx.__exit__(None, None, None)


# --- LLM adjudication ------------------------------------------------------

_TRANSFER_SCREEN_SYSTEM = """\
You are screening AI research evidence for a finance gap-detection library.

The library is not a catalogue of every AI paper. It only contains reusable
AI mechanism families that can be tested against a concrete bottleneck in one
or more maintained finance fields.

Given a paper-level mechanism and the maintained finance boundary summary,
return one of:
  - "transferable": the paper contains a reusable technical intervention with
    a defensible bridge to a stated finance bottleneck or transfer target.
  - "not_relevant": the mechanism is domain-specific or has no concrete
    finance-side experimental target in the supplied boundaries.
  - "ambiguous": a bridge is plausible, but the paper mechanism is too vague
    or the finance mapping would currently be speculative.

For "transferable", project the paper one level upward into a reusable
mechanism family. A family must identify BOTH a technical intervention and
the failure/bottleneck it addresses. It must be narrower than themes such as
"representation learning", "agents", "efficiency", or "robustness", but it
must not use a paper/model/dataset brand name. Example family granularity:
"verifier-guided repair of structured outputs after execution failure" or
"uncertainty-calibrated forecasts used to abstain under distribution shift".

The source paper does NOT need to mention finance. Transfer is exactly the
question being tested: accept a general AI mechanism when its intervention
can be evaluated against a supplied finance bottleneck. Operational
verification/evaluation mechanisms also count when they can become a gate,
abstention rule, consistency check, leakage check, or trajectory audit.
Examples that can be transferable when supported by the input:
  - feedback-improved tool use -> financial tool ambiguity or trace reliability
  - process-supervised retrieval/search -> evidence sufficiency or citation audit
  - consistency/calibration checks -> forecast uncertainty or numerical verification
  - adaptive inference budgets -> search-budget or agent cost/latency control

Do not label a paper transferable merely because finance uses ML, text,
time-series data, optimization, or agents. A bridge must name the testable
intervention and finance bottleneck; do not invent either one.

Return STRICT JSON only:
{
  "relevance_status": "transferable" | "not_relevant" | "ambiguous",
  "relevant_fin_fields": [<field id strings>],
  "transferable_one_liner": <string or null>,
  "transfer_problem": <string or null>,
  "shared_approach": <string or null>,
  "rationale": <brief string>
}
"""

_ADJUDICATOR_SYSTEM = """\
You are a careful librarian for a finance-transferable AI mechanism library.

Given:
  - A new paper already projected into a transferable family-level mechanism.
  - Up to 5 candidate existing families with their representative one-liner +
    what_problem fields, retrieved by embedding similarity.

Decide one of three actions:

  1. "match" — the projection uses the same reusable intervention class to
     address the same failure/bottleneck as one candidate. Implementations,
     model architectures, datasets, and domains may differ. A specialized
     deployment surface is evidence for the family, not a new family: for
     example, adaptive inference-budget allocation for RAG versus reasoning
     search should match when both allocate test-time compute under a
     resource/quality tradeoff. Provide:
       - matched_family_id
       - confidence (0..1; >=0.8 means clear match, <0.6 means weak)

  2. "new_family" — no candidate represents the intervention-and-bottleneck
     pair. Shared broad themes are not enough to merge, but do not split
     families solely because one paper applies the mechanism to retrieval,
     generation, tool use, or another downstream surface.
     Provide:
       - new_one_liner (one short sentence describing the mechanism functionally;
         do NOT use paper-specific names like "FIPO" or "Eywa" — describe what
         the mechanism does, not what it is branded)
       - new_what_problem (short)

  3. "ambiguous" — paper plausibly fits multiple candidate families, or
     the description is too vague to confidently assign. Provide:
       - top_family_id (best guess for a soft 'proposed' membership)
       - reason

Output STRICT JSON, no markdown fences:

  { "action": "match" | "new_family" | "ambiguous",
    "matched_family_id": <string or null>,
    "confidence": <float or null>,
    "new_one_liner": <string or null>,
    "new_what_problem": <string or null>,
    "top_family_id": <string or null>,
    "reason": <string, brief, always>
  }
"""


@lru_cache(maxsize=1)
def _fin_transfer_context() -> str:
    """Compact maintained finance boundaries for transfer screening prompts."""
    from .analyze.context import load_fin_field_notes

    compact = []
    for note in load_fin_field_notes():
        compact.append({
            "field_id": note.get("id"),
            "mechanism_families": [
                f.get("name") for f in (note.get("mechanism_families") or [])
                if f.get("name")
            ],
            "open_bottlenecks": [
                b.get("name") for b in (note.get("open_bottlenecks") or [])
                if b.get("name")
            ],
            "good_transfer_targets": note.get("good_transfer_targets") or [],
        })
    return json.dumps(compact, ensure_ascii=False, indent=2)


def _build_transfer_screen_user(paper_id: str, mech: dict) -> str:
    return "\n".join([
        f"## AI paper mechanism (id={paper_id})",
        f"one_liner: {mech.get('one_liner') or '(missing)'}",
        f"what_problem: {mech.get('what_problem') or '(missing)'}",
        f"contrast: {mech.get('contrast') or '(missing)'}",
        f"prerequisites: {mech.get('prerequisites') or '(missing)'}",
        "",
        "## Maintained finance boundary summary",
        _fin_transfer_context(),
        "",
        "Assess transferability and return JSON only.",
    ])


def _read_transfer_review(conn, paper_id: str) -> dict | None:
    row = conn.execute(
        """
        SELECT relevance_status, transferable_one_liner, transfer_problem,
               shared_approach, relevant_fin_fields_json, rationale
        FROM mechanism_transfer_reviews WHERE paper_id = ?
        """,
        (paper_id,),
    ).fetchone()
    if not row:
        return None
    review = dict(row)
    review["relevant_fin_fields"] = json.loads(
        review.pop("relevant_fin_fields_json") or "[]"
    )
    return review


def _write_transfer_review(conn, paper_id: str, assessment: dict) -> None:
    conn.execute(
        """
        INSERT INTO mechanism_transfer_reviews
            (paper_id, relevance_status, transferable_one_liner,
             transfer_problem, shared_approach, relevant_fin_fields_json,
             rationale, assessed_at, assessed_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'llm-transfer-screen-v2')
        ON CONFLICT(paper_id) DO UPDATE SET
            relevance_status = excluded.relevance_status,
            transferable_one_liner = excluded.transferable_one_liner,
            transfer_problem = excluded.transfer_problem,
            shared_approach = excluded.shared_approach,
            relevant_fin_fields_json = excluded.relevant_fin_fields_json,
            rationale = excluded.rationale,
            assessed_at = excluded.assessed_at,
            assessed_by = excluded.assessed_by
        """,
        (
            paper_id,
            assessment["relevance_status"],
            assessment.get("transferable_one_liner") or "",
            assessment.get("transfer_problem") or "",
            assessment.get("shared_approach") or "",
            json.dumps(assessment.get("relevant_fin_fields") or [], ensure_ascii=False),
            assessment.get("rationale") or "",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )


def _assess_transferability(conn, paper_id: str, mech: dict, llm: LLMClient) -> dict:
    existing = _read_transfer_review(conn, paper_id)
    if existing:
        return existing
    raw = llm.chat_json(
        _TRANSFER_SCREEN_SYSTEM,
        _build_transfer_screen_user(paper_id, mech),
        temperature=0.0,
        reasoning=True,
    )
    status = str(raw.get("relevance_status") or "").strip().lower()
    if status not in {"transferable", "not_relevant", "ambiguous"}:
        status = "ambiguous"
    projected = (raw.get("transferable_one_liner") or "").strip()
    if status == "transferable" and not projected:
        status = "ambiguous"
    assessment = {
        "relevance_status": status,
        "transferable_one_liner": projected,
        "transfer_problem": (raw.get("transfer_problem") or "").strip(),
        "shared_approach": (raw.get("shared_approach") or "").strip(),
        "relevant_fin_fields": [
            str(field).strip() for field in (raw.get("relevant_fin_fields") or [])
            if str(field).strip()
        ],
        "rationale": (raw.get("rationale") or "").strip(),
    }
    _write_transfer_review(conn, paper_id, assessment)
    return assessment


def _build_adjudication_user(
    paper_id: str,
    mech: dict,
    candidates: list[tuple[FamilyRecord, float]],
) -> str:
    """Render the prompt body for the LLM adjudicator."""
    lines = [
        f"## New paper (id={paper_id})",
        f"  one_liner:    {mech.get('one_liner') or '(missing)'}",
        f"  what_problem: {mech.get('what_problem') or '(missing)'}",
        f"  contrast:     {mech.get('contrast') or '(missing)'}",
        "",
        "## Candidate families (top-K by embedding similarity)",
    ]
    if not candidates:
        lines.append("  (none — library is empty)")
    for fam, sim in candidates:
        lines.append(f"- {fam.family_id} [sim={sim:.3f}, members={fam.member_count}]")
        lines.append(f"    one_liner:    {fam.representative_one_liner}")
        if fam.what_problem:
            lines.append(f"    what_problem: {fam.what_problem}")
        if fam.shared_approach:
            lines.append(f"    shared_approach: {fam.shared_approach}")
    lines.append("")
    lines.append("Decide: match / new_family / ambiguous. Return JSON only.")
    return "\n".join(lines)


# --- Adjudication thresholds ----------------------------------------------

# Tunable via Phase 1 task 1.7 review:
#   match w/ confidence >= MATCH_CONF_ACCEPT     → write 'accepted'
#   match w/ confidence in [MATCH_CONF_PROPOSE, MATCH_CONF_ACCEPT)
#                                                → write 'proposed' + needs_review
#   match w/ confidence < MATCH_CONF_PROPOSE     → treat as ambiguous
MATCH_CONF_ACCEPT = 0.80
MATCH_CONF_PROPOSE = 0.55


# --- Main entry point -----------------------------------------------------

def assign_paper(
    paper_id: str,
    mech: dict,
    *,
    top_k: int = 5,
    llm: LLMClient | None = None,
) -> dict:
    """End-to-end: retrieve top-K, adjudicate via LLM, write membership.

    Args:
        paper_id: papers.id to assign
        mech: dict with one_liner / what_problem / contrast (from L1 extraction)
        top_k: retrieval breadth
        llm: optional pre-built LLMClient (saves init time for batch calls)

    Returns:
        dict describing the outcome:
            {action, family_id, confidence, membership_status, needs_review, reason}
    """
    one_liner = (mech.get("one_liner") or "").strip()
    if not one_liner:
        return {
            "action": "skipped",
            "reason": "empty mechanism one_liner",
        }

    with db.connect() as conn:
        extraction = conn.execute(
            "SELECT side FROM paper_extractions WHERE paper_id = ?",
            (paper_id,),
        ).fetchone()
        if extraction and extraction["side"] != "ai":
            return {
                "action": "skipped",
                "reason": f"mechanism family assignment is AI-only (side={extraction['side']})",
            }
        llm = llm or LLMClient()
        try:
            assessment = _assess_transferability(conn, paper_id, mech, llm)
        except Exception as e:
            log.warning("transfer screen failed for %s: %s", paper_id, e)
            return {"action": "error-screen", "reason": f"llm: {e}"}
        relevance = assessment["relevance_status"]
        if relevance != "transferable":
            return {
                "action": f"screen-{relevance}",
                "reason": assessment.get("rationale") or "",
                "relevant_fin_fields": assessment.get("relevant_fin_fields") or [],
            }

        projected_mech = {
            "one_liner": assessment["transferable_one_liner"],
            "what_problem": assessment.get("transfer_problem") or "",
            "contrast": assessment.get("shared_approach") or "",
        }
        query = (
            f"{projected_mech['one_liner']} | "
            f"problem: {projected_mech['what_problem']}"
        ).strip()
        # 2. Retrieval over current library.
        families = load_all_families(conn)
        ids, vecs = family_index(families)
        family_by_id = {f.family_id: f for f in families}
        top = find_top_k(query, vecs, ids, k=top_k)
        candidates = [(family_by_id[fid], sim) for fid, sim in top]

        # 3. LLM adjudication.
        if not candidates:
            # Screening has already produced a family-level abstraction.
            decision = _create_first_family(conn, paper_id, projected_mech)
            return decision

        user_prompt = _build_adjudication_user(paper_id, projected_mech, candidates)
        try:
            verdict = llm.chat_json(
                _ADJUDICATOR_SYSTEM,
                user_prompt,
                temperature=0.0,
                reasoning=True,
            )
        except Exception as e:
            log.warning("adjudicator LLM failed for %s: %s", paper_id, e)
            return {"action": "error", "reason": f"llm: {e}"}

        action = verdict.get("action")
        reason = verdict.get("reason") or ""

        # 4. Apply adjudication -> write membership / family.
        if action == "match":
            fam_id = verdict.get("matched_family_id")
            conf = float(verdict.get("confidence") or 0.0)
            if fam_id not in family_by_id:
                # LLM hallucinated a family_id — fall back to ambiguous on top-1.
                log.warning("LLM returned unknown family_id %s; falling back", fam_id)
                fam_id = candidates[0][0].family_id
                action = "ambiguous"

            if action == "match" and conf >= MATCH_CONF_ACCEPT:
                _write_membership(conn, paper_id, fam_id, conf, status="accepted",
                                  needs_review=0, reason=reason)
                return {"action": "match-accepted", "family_id": fam_id,
                        "confidence": conf, "reason": reason}
            elif conf >= MATCH_CONF_PROPOSE:
                _write_membership(conn, paper_id, fam_id, conf, status="proposed",
                                  needs_review=1, reason=reason)
                return {"action": "match-proposed", "family_id": fam_id,
                        "confidence": conf, "reason": reason}
            else:
                # Treat low-confidence match as ambiguous.
                action = "ambiguous"

        if action == "new_family":
            one_liner_new = (
                verdict.get("new_one_liner") or projected_mech["one_liner"]
            ).strip()
            what_problem_new = (verdict.get("new_what_problem")
                                or projected_mech.get("what_problem") or "").strip()
            new_id = _create_family(
                conn,
                representative_one_liner=one_liner_new,
                what_problem=what_problem_new,
                shared_approach=projected_mech.get("contrast", "") or "",
                contrast_to_prior=mech.get("contrast", "") or "",
            )
            _write_membership(conn, paper_id, new_id, 1.0, status="accepted",
                              needs_review=0, reason="founder of new family")
            return {"action": "new_family", "family_id": new_id,
                    "confidence": 1.0, "reason": reason or "founder"}

        if action == "ambiguous":
            fam_id = verdict.get("top_family_id") or candidates[0][0].family_id
            if fam_id not in family_by_id:
                fam_id = candidates[0][0].family_id
            _write_membership(conn, paper_id, fam_id, 0.4, status="proposed",
                              needs_review=1, reason=reason)
            return {"action": "ambiguous-proposed", "family_id": fam_id,
                    "confidence": 0.4, "reason": reason}

        return {"action": "unhandled", "verdict": verdict}


def _create_first_family(conn, paper_id: str, mech: dict) -> dict:
    """Bootstrap an empty library from an already screened family projection."""
    fam_id = _create_family(
        conn,
        representative_one_liner=mech.get("one_liner") or "",
        what_problem=mech.get("what_problem") or "",
        shared_approach=mech.get("contrast") or "",
        contrast_to_prior=mech.get("contrast") or "",
    )
    _write_membership(conn, paper_id, fam_id, 1.0, status="accepted",
                      needs_review=0, reason="library bootstrap")
    return {"action": "bootstrap-new_family", "family_id": fam_id,
            "confidence": 1.0, "reason": "library bootstrap"}


def _create_family(
    conn,
    *,
    representative_one_liner: str,
    what_problem: str = "",
    shared_approach: str = "",
    contrast_to_prior: str = "",
) -> str:
    fam_id = _new_family_id()
    now = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO mechanism_families
            (family_id, representative_one_liner, what_problem, shared_approach,
             contrast_to_prior, created_at, last_updated, canonical_status)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'auto_draft')
        """,
        (
            fam_id,
            representative_one_liner.strip(),
            what_problem.strip(),
            shared_approach.strip(),
            contrast_to_prior.strip(),
            now,
            now,
        ),
    )
    return fam_id


def _write_membership(
    conn,
    paper_id: str,
    family_id: str,
    confidence: float,
    *,
    status: str,
    needs_review: int,
    reason: str,
    slot: str = "primary",
    assigned_by: str = "llm-adjudicator-v2",
) -> None:
    """Idempotent membership write. On conflict, update confidence/status."""
    conn.execute(
        """
        INSERT INTO mechanism_memberships
            (paper_id, family_id, mechanism_slot, confidence,
             assigned_at, assigned_by, membership_status, needs_review)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(paper_id, family_id, mechanism_slot) DO UPDATE SET
            confidence = excluded.confidence,
            assigned_at = excluded.assigned_at,
            assigned_by = excluded.assigned_by,
            membership_status = excluded.membership_status,
            needs_review = excluded.needs_review
        """,
        (
            paper_id,
            family_id,
            slot,
            confidence,
            datetime.now().isoformat(timespec="seconds"),
            assigned_by,
            status,
            needs_review,
        ),
    )
    # Bump the family's last_updated.
    conn.execute(
        "UPDATE mechanism_families SET last_updated = ? WHERE family_id = ?",
        (datetime.now().isoformat(timespec="seconds"), family_id),
    )


# --- Batch driver ---------------------------------------------------------

def assign_pending(limit: int = 100, *, evidence_only: bool = False) -> dict:
    """Assign all papers that have L1 extraction but no membership yet.

    Selects only papers with completed L1 (mechanism_description present)
    and no existing mechanism_memberships row. Re-callable safely thanks
    to membership UNIQUE keys.
    """
    stats = {
        "processed": 0,
        "assigned": 0,
        "screened_out": 0,
        "errors": 0,
        "by_action": {},
        "tokens_in": 0,
        "tokens_out": 0,
        "cost_usd": 0.0,
    }
    # The CLI can run independently of `pipeline.main daily`, which normally
    # applies additive schema migrations at startup.
    db.init_schema()

    evidence_clause = """
              AND EXISTS (
                  SELECT 1 FROM paper_sources _eps
                  WHERE _eps.paper_id = p.id AND _eps.role = 'evidence'
              )
    """ if evidence_only else ""
    with db.connect() as conn:
        # Order by priority DESC so conference-tier papers (ICLR oral=10,
        # spotlight=8) get assigned before legacy HF Daily (~1-5).
        # Without this, assign_pending hits legacy papers in rowid order
        # and exhausts the limit before reaching OpenReview evidence.
        rows = conn.execute(f"""
            SELECT p.id, e.mechanism_description_json
            FROM papers p
            JOIN paper_extractions e ON e.paper_id = p.id
            LEFT JOIN mechanism_memberships m ON m.paper_id = p.id
            LEFT JOIN mechanism_transfer_reviews tr ON tr.paper_id = p.id
            LEFT JOIN paper_signals s ON s.paper_id = p.id
            WHERE e.extraction_status IN ('l1_done', 'l2_done')
              AND e.side = 'ai'
              AND e.mechanism_description_json IS NOT NULL
              AND e.mechanism_description_json != ''
              AND e.mechanism_description_json != '{{}}'
              AND m.paper_id IS NULL
              AND (tr.paper_id IS NULL OR tr.relevance_status = 'transferable')
              {evidence_clause}
            ORDER BY COALESCE(s.priority_score, 0) DESC, p.id
            LIMIT ?
        """, (limit,)).fetchall()

    log.info("assign_pending: %d papers ready for family assignment", len(rows))
    if not rows:
        return stats
    llm = LLMClient()

    for r in rows:
        paper_id = r[0]
        try:
            mech = json.loads(r[1] or "{}")
        except json.JSONDecodeError:
            stats["errors"] += 1
            continue

        result = assign_paper(paper_id, mech, llm=llm)
        stats["processed"] += 1
        action = result.get("action", "unhandled")
        stats["by_action"][action] = stats["by_action"].get(action, 0) + 1
        if action.startswith("error") or action == "skipped":
            stats["errors"] += 1
        elif action.startswith("screen-"):
            stats["screened_out"] += 1
        else:
            stats["assigned"] += 1

        if stats["processed"] % 10 == 0:
            log.info("  progress: %d / %d", stats["processed"], len(rows))

    tokens_in, tokens_out = llm.total_tokens
    stats["tokens_in"] = tokens_in
    stats["tokens_out"] = tokens_out
    stats["cost_usd"] = round(llm.estimate_cost_usd(), 6)
    return stats


# --- CLI ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if len(sys.argv) > 1 and sys.argv[1] == "stats":
        with db.connect() as conn:
            n_families = conn.execute(
                "SELECT COUNT(*) FROM mechanism_families"
            ).fetchone()[0]
            n_accepted = conn.execute(
                "SELECT COUNT(*) FROM mechanism_memberships WHERE membership_status='accepted'"
            ).fetchone()[0]
            n_proposed = conn.execute(
                "SELECT COUNT(*) FROM mechanism_memberships WHERE membership_status='proposed'"
            ).fetchone()[0]
            n_needs_review = conn.execute(
                "SELECT COUNT(*) FROM mechanism_memberships WHERE needs_review=1"
            ).fetchone()[0]
            print(json.dumps({
                "families_total": n_families,
                "memberships_accepted": n_accepted,
                "memberships_proposed": n_proposed,
                "needs_review": n_needs_review,
            }, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1] == "assign":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        evidence_only = "--evidence-only" in sys.argv[2:]
        result = assign_pending(limit=limit, evidence_only=evidence_only)
        print(json.dumps(result, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1] == "maturity":
        # Library-wide maturity distribution under venue-weighted tiers.
        dist = maturity_distribution()
        print(json.dumps(dist, indent=2))

    elif len(sys.argv) > 1 and sys.argv[1] == "maturity-show":
        # Detail one family's maturity computation.
        if len(sys.argv) < 3:
            print("Usage: maturity-show <family_id>", file=sys.stderr)
            sys.exit(2)
        m = compute_maturity(sys.argv[2])
        print(json.dumps(m, indent=2))

    else:
        print("Usage:")
        print("  python -m pipeline.mechanism_lib stats")
        print("  python -m pipeline.mechanism_lib assign [limit] [--evidence-only]")
        print("  python -m pipeline.mechanism_lib maturity")
        print("  python -m pipeline.mechanism_lib maturity-show <family_id>")
