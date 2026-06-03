"""Gap generation — Prompts 04 (theoretical) + 05 (engineering).

Calls 04 first, then 05 with today's theoretical gaps as additional context
so 05 can upgrade weak theoretical proposals to fully-specified engineering ones.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient
from . import context as ctx_builder
from . import risk_audit as risk_audit_mod
from . import scoring as scoring_mod
from . import self_check as sc_mod
from . import trends as trends_mod
from . import uptake as uptake_mod


log = logging.getLogger(__name__)

EMAIL_DUPLICATE_SIMILARITY_THRESHOLD = 0.42
CANDIDATE_ENUMERATION_MAX_TOKENS = 8192
MAX_CANDIDATES_FOR_REFINEMENT = 6   # O4: wider funnel → more field diversity, fewer empty days
MAX_THEORETICAL_GAPS = 6            # O4: let the wider candidate pool flow through to theoretical
THEORETICAL_EXPANSION_MAX_TOKENS = 16384
MAX_ENGINEERING_GAPS = 2           # runnable experiments stay focused (each → an expensive brief)
MAX_THEORETICAL_LEADS = 3          # O4: on thin days, surface up to N theoretical gaps as exploratory leads
ENGINEERING_EXPANSION_MAX_TOKENS = 32768
ENGINEERING_REPAIR_MAX_TOKENS = 32768
MAX_FRONTIER_CANDIDATES_SELECTED = 1
DEDUP_LOOKBACK_DAYS = 7   # O3: exclude anchors / show recent mechanisms from last N days
GROUNDED_TRANSFER = "grounded_transfer"
FRONTIER_EXTENSION = "frontier_extension"


def build_gap_context(end_date: date | None = None,
                      *, ai_top: int = 20, fin_top: int = 10,
                      window_days_ai: int | None = None,
                      window_days_fin: int | None = None,
                      window_days: int | None = None,   # legacy override
                      include_trends: bool = False,
                      client: LLMClient | None = None) -> dict:
    """Gather all context needed for gap generation prompts.

    Default windows are asymmetric: AI 90d, Fin 180d.
    Pass window_days to force same window on both sides (debug only).
    """
    end = end_date or date.today()
    client = client or LLMClient()

    if window_days is not None:
        wd_ai = wd_fin = window_days
    else:
        wd_ai = window_days_ai if window_days_ai is not None else trends_mod.WINDOW_DAYS_AI
        wd_fin = window_days_fin if window_days_fin is not None else trends_mod.WINDOW_DAYS_FIN

    # O3 — don't re-anchor papers used in the last few days' gaps (explore the pool),
    # and show the model the mechanisms already proposed recently (brand-free) so it
    # avoids / differentiates rather than re-proposing the same transfer.
    from ..output import gap_log as gap_log_mod
    recent_anchor_ids = gap_log_mod.recent_anchor_ids(DEDUP_LOOKBACK_DAYS, as_of=end)
    recently_proposed = [
        {k: s.get(k) for k in ("field_id", "mechanism_family", "ai_mechanism",
                               "hypothesis", "verdict", "date")}
        for s in gap_log_mod.recent_signatures(DEDUP_LOOKBACK_DAYS, as_of=end)
    ]
    # Conference look-back: blend in a few peer-reviewed conf papers every day (quality +
    # topic breadth), MORE on thin-inflow days. Replaces some fresh slots, not added on top.
    fresh_recent = ctx_builder.count_fresh_eligible("ai", end)
    conf_n = ctx_builder.CONF_LOOKBACK_BASE + (
        ctx_builder.CONF_LOOKBACK_THIN_BONUS
        if fresh_recent < ctx_builder.CONF_THIN_FRESH_THRESHOLD else 0)
    conf_n = max(0, min(conf_n, ai_top - 5))   # always leave room for fresh anchors
    ai_main = ctx_builder.get_top_papers("ai", end, top_n=ai_top - conf_n, window_days=wd_ai,
                                         exclude_ids=recent_anchor_ids)
    conf_lookback = ctx_builder.get_conference_lookback(
        end, conf_n, side="ai",
        exclude_ids=recent_anchor_ids | {p["id"] for p in ai_main})
    ai_papers = ai_main + conf_lookback
    log.info("AI anchors: %d fresh + %d conference look-back (fresh_recent=%d%s)",
             len(ai_main), len(conf_lookback), fresh_recent,
             " — THIN day" if conf_n > ctx_builder.CONF_LOOKBACK_BASE else "")
    fin_papers = ctx_builder.get_top_papers("fin", end, top_n=fin_top, window_days=wd_fin)
    mappings = ctx_builder.load_existing_mappings()
    all_fin_field_boundaries = ctx_builder.load_fin_field_notes()
    all_fin_transfer_cells = ctx_builder.load_fin_transfer_cells()
    ai_innovation_playbook = ctx_builder.load_ai_innovation_playbook()

    if include_trends:
        ai_trends = trends_mod.summarize_trends("ai", end, client=client, window_days=wd_ai)
        fin_trends = trends_mod.summarize_trends("fin", end, client=client, window_days=wd_fin)
    else:
        ai_trends = _empty_trends("disabled_in_daily_experiment_first_mode")
        fin_trends = _empty_trends("disabled_in_daily_experiment_first_mode")
    fin_field_boundaries = ctx_builder.select_fin_field_notes(
        all_fin_field_boundaries,
        [ctx_builder.paper_for_prompt(p) for p in ai_papers],
        [ctx_builder.paper_for_prompt(p) for p in fin_papers],
        _strip_meta(ai_trends),
        _strip_meta(fin_trends),
        max_fields=3,
    )
    fin_transfer_cells = ctx_builder.select_fin_transfer_cells(
        all_fin_transfer_cells,
        fin_field_boundaries,
    )
    historical_ai_mechanisms = ctx_builder.get_relevant_historical_mechanisms(
        end,
        fin_field_boundaries,
        fin_transfer_cells,
        exclude_ids={p["id"] for p in ai_papers},
        top_n=18,
    )

    # Tier 1.1: quantified Fin-side uptake for AI concepts (algorithmic, not LLM)
    ai_concepts_to_check = uptake_mod.extract_ai_concepts_for_uptake(
        _strip_meta(ai_trends),
        [ctx_builder.paper_for_prompt(p) for p in ai_papers],
        max_concepts=30,
    )
    fin_uptake = uptake_mod.measure_fin_uptake(
        ai_concepts_to_check, end_date=end, window_days=365,
    )

    return {
        "end_date": end,
        "window_ai_days": wd_ai,
        "window_fin_days": wd_fin,
        "ai_recent_papers": [ctx_builder.paper_for_prompt(p) for p in ai_papers],
        "historical_ai_mechanisms": historical_ai_mechanisms,
        "fin_recent_papers": [ctx_builder.paper_for_prompt(p) for p in fin_papers],
        "ai_trends": _strip_meta(ai_trends),
        "fin_trends": _strip_meta(fin_trends),
        "existing_mappings": [ctx_builder.mapping_for_prompt(m) for m in mappings],
        "fin_field_boundaries": fin_field_boundaries,
        "fin_field_boundaries_all": all_fin_field_boundaries,
        "fin_transfer_cells": fin_transfer_cells,
        "fin_transfer_cells_all": all_fin_transfer_cells,
        "ai_innovation_playbook": ai_innovation_playbook,
        "trends_included": include_trends,
        "fin_uptake": fin_uptake,    # ← Tier 1.1: hard negative-evidence ground truth
        "recently_proposed": recently_proposed,  # ← O3: mechanisms proposed in last N days (brand-free)
        # raw refs for downstream validation
        "_valid_ai_ids": {p["id"] for p in ai_papers} | {
            p["id"] for p in historical_ai_mechanisms
        },
        "_valid_fin_ids": {p["id"] for p in fin_papers},
        "_mappings_brief": [ctx_builder.mapping_brief(m) for m in mappings],
        "_valid_transfer_cell_ids": {cell["cell_id"] for cell in fin_transfer_cells},
    }


def _strip_meta(trends: dict) -> dict:
    return {k: v for k, v in trends.items() if k != "_meta"}


def _empty_trends(reason: str) -> dict:
    return {
        "rising": [],
        "falling": [],
        "new_emergence": [],
        "stable_hot": [],
        "_meta": {"reason": reason},
    }


def enumerate_candidates(context: dict, client: LLMClient | None = None) -> list[dict]:
    """Prompt 04A → a small candidate pool, biased toward runnable experiments."""
    client = client or LLMClient()
    system, user_template = parse_prompt("04A_gap_enumerate")
    user = render_template(
        user_template,
        ai_recent_papers_json=json.dumps(context["ai_recent_papers"], ensure_ascii=False, indent=2),
        historical_ai_mechanisms_json=json.dumps(
            context.get("historical_ai_mechanisms", []), ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_field_boundaries_json=json.dumps(context.get("fin_field_boundaries", []), ensure_ascii=False, indent=2),
        fin_transfer_cells_json=json.dumps(context.get("fin_transfer_cells", []), ensure_ascii=False, indent=2),
        ai_innovation_playbook=context.get("ai_innovation_playbook", ""),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
        recently_proposed_json=json.dumps(context.get("recently_proposed", []), ensure_ascii=False, indent=2),
    )
    try:
        result = client.chat_json(
            system=system,
            user=user,
            temperature=0.8,
            reasoning=True,
            max_tokens=CANDIDATE_ENUMERATION_MAX_TOKENS,
        )
    except Exception as e:
        log.warning("Enumerate LLM call failed: %s (returning [])", e)
        return []
    candidates = result.get("candidates", []) if isinstance(result, dict) else []

    # Validate anchor IDs are real
    valid_ai = context.get("_valid_ai_ids", set())
    candidates = [c for c in candidates if c.get("ai_anchor_paper_id") in valid_ai]
    valid_cells = context.get("_valid_transfer_cell_ids", set())
    candidates = [c for c in candidates if _candidate_has_valid_route(c, valid_cells)]
    log.info("Enumerate: %d valid candidates from Prompt 04A", len(candidates))
    return candidates


def select_top_candidates(candidates: list[dict], top_n: int = 8) -> list[dict]:
    """Diversify + pick top N from candidate pool.

    Priority order:
      1. fin_uptake_status = open_gap > partial > explored
      2. field diversity (≤ 3 per field)
      3. ai_category diversity (≤ 2 per category)
    """
    status_order = {"open_gap": 0, "partial": 1, "explored": 2}
    candidates.sort(key=lambda c: (
        0 if _opportunity_mode(c) == GROUNDED_TRANSFER else 1,
        status_order.get(c.get("fin_uptake_status", "explored"), 3),
    ))

    per_cat: dict[str, int] = {}
    per_field: dict[str, int] = {}
    frontier_selected = 0
    selected = []
    for c in candidates:
        cat = c.get("ai_category", "other")
        field_id = _candidate_field_id(c)
        is_frontier = _opportunity_mode(c) == FRONTIER_EXTENSION
        if is_frontier and frontier_selected >= MAX_FRONTIER_CANDIDATES_SELECTED:
            continue
        if per_field.get(field_id, 0) >= 3:
            continue
        if per_cat.get(cat, 0) >= 2:
            continue
        per_field[field_id] = per_field.get(field_id, 0) + 1
        per_cat[cat] = per_cat.get(cat, 0) + 1
        frontier_selected += 1 if is_frontier else 0
        selected.append(c)
        if len(selected) >= top_n:
            break
    return selected


def _candidate_field_id(candidate: dict) -> str:
    alignment = candidate.get("field_boundary_alignment") or {}
    if isinstance(alignment, dict):
        return alignment.get("field_id") or candidate.get("field_id") or "unknown"
    return candidate.get("field_id") or "unknown"


def _opportunity_mode(item: dict) -> str:
    mode = item.get("opportunity_mode")
    if mode in (GROUNDED_TRANSFER, FRONTIER_EXTENSION):
        return mode
    alignment = item.get("field_boundary_alignment") or {}
    return GROUNDED_TRANSFER if alignment.get("transfer_cell_id") else FRONTIER_EXTENSION


def _candidate_has_valid_route(candidate: dict, valid_cells: set[str]) -> bool:
    """Allow bounded frontier proposals while enforcing existing-cell routes."""
    alignment = candidate.get("field_boundary_alignment") or {}
    if _opportunity_mode(candidate) == GROUNDED_TRANSFER:
        cell_id = alignment.get("transfer_cell_id")
        return not valid_cells or cell_id in valid_cells
    proposal = candidate.get("proposed_cell") or {}
    return bool(
        alignment.get("field_id")
        and proposal.get("new_failure_mode")
        and proposal.get("ai_intervention_class")
        and proposal.get("experiment_anchor_sketch")
        and proposal.get("why_existing_cells_insufficient")
    )


def generate_theoretical_gaps(context: dict, client: LLMClient | None = None,
                              candidates: list[dict] | None = None) -> list[dict]:
    """Prompt 04 → 0-5 theoretical gap candidates.

    If `candidates` provided (from enumerate stage), refine only those.
    Otherwise LLM generates from scratch (legacy behavior).
    """
    client = client or LLMClient()
    system, user_template = parse_prompt("04_gap_theoretical")
    user_kwargs = dict(
        ai_recent_papers_json=json.dumps(context["ai_recent_papers"], ensure_ascii=False, indent=2),
        historical_ai_mechanisms_json=json.dumps(
            context.get("historical_ai_mechanisms", []), ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_field_boundaries_json=json.dumps(context.get("fin_field_boundaries", []), ensure_ascii=False, indent=2),
        fin_transfer_cells_json=json.dumps(context.get("fin_transfer_cells", []), ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
    )
    base_user = render_template(user_template, **user_kwargs)
    gaps = _expand_theoretical_gaps_with_recovery(
        system=system,
        base_user=base_user,
        candidates=candidates,
        client=client,
    )
    candidate_alignments = _candidate_alignments(candidates or [])
    candidate_audits = _candidate_audits(candidates or [])
    candidate_origins = _candidate_origins(candidates or [])
    candidate_routes = _candidate_routes(candidates or [])
    for i, g in enumerate(gaps, start=1):
        g["_id"] = f"TH-{i}"
        g["_type"] = "theoretical"
        _ensure_field_alignment(g, candidate_alignments)
        _ensure_risk_audit(g, candidate_audits)
        _ensure_origin(g, candidate_origins)
        _ensure_opportunity_route(g, candidate_routes)
    gaps = gaps[:MAX_THEORETICAL_GAPS]
    log.info("Generated %d theoretical gaps", len(gaps))
    return gaps


def _expand_theoretical_gaps_with_recovery(*, system: str, base_user: str,
                                           candidates: list[dict] | None,
                                           client: LLMClient) -> list[dict]:
    """Expand selected candidates, recovering from long or malformed batch output."""
    try:
        return _request_theoretical_gaps(system, base_user, candidates, client)
    except Exception as e:
        if not candidates or len(candidates) <= 1:
            log.warning("Theoretical gap LLM call failed: %s (returning [])", e)
            return []
        log.warning(
            "Theoretical gap batch expansion failed: %s; retrying %d candidates individually",
            e,
            len(candidates),
        )

    recovered: list[dict] = []
    for candidate in candidates:
        try:
            recovered.extend(_request_theoretical_gaps(system, base_user, [candidate], client))
        except Exception as e:
            log.warning(
                "Theoretical gap recovery failed for candidate %s: %s (skipping candidate)",
                candidate.get("idx", "?"),
                e,
            )
        if len(recovered) >= MAX_THEORETICAL_GAPS:
            break
    return recovered[:MAX_THEORETICAL_GAPS]


def _request_theoretical_gaps(system: str, base_user: str,
                              candidates: list[dict] | None,
                              client: LLMClient) -> list[dict]:
    user = base_user
    if candidates:
        user += (
            "\n\n【已挑选的候选 candidates，请你只精雕这些，每条扩展为完整 gap】\n"
            f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
        )
    result = client.chat_json(
        system=system,
        user=user,
        temperature=0.6,
        reasoning=True,
        max_tokens=THEORETICAL_EXPANSION_MAX_TOKENS,
    )
    return result.get("gaps", []) if isinstance(result, dict) else []


def generate_engineering_gaps(context: dict, theoretical_gaps: list[dict],
                              client: LLMClient | None = None,
                              *, adversarial_mode: bool = False) -> list[dict]:
    """Prompt 05 → 0-3 engineering gap candidates (with full experimental roadmap)."""
    client = client or LLMClient()
    grounded_theoretical_gaps = [
        gap for gap in theoretical_gaps
        if _opportunity_mode(gap) == GROUNDED_TRANSFER
    ]
    if len(grounded_theoretical_gaps) != len(theoretical_gaps):
        log.info(
            "Keeping %d frontier extension theories out of engineering expansion pending review",
            len(theoretical_gaps) - len(grounded_theoretical_gaps),
        )
    if theoretical_gaps and not grounded_theoretical_gaps:
        return []
    system, user_template = parse_prompt("05_gap_engineering")
    user_kwargs = dict(
        ai_recent_papers_json=json.dumps(context["ai_recent_papers"], ensure_ascii=False, indent=2),
        historical_ai_mechanisms_json=json.dumps(
            context.get("historical_ai_mechanisms", []), ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_field_boundaries_json=json.dumps(context.get("fin_field_boundaries", []), ensure_ascii=False, indent=2),
        fin_transfer_cells_json=json.dumps(context.get("fin_transfer_cells", []), ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
    )
    gaps = _expand_engineering_gaps_with_recovery(
        system=system,
        user_template=user_template,
        user_kwargs=user_kwargs,
        theoretical_gaps=grounded_theoretical_gaps,
        client=client,
        adversarial_mode=adversarial_mode,
    )
    gaps = gaps[:MAX_ENGINEERING_GAPS]
    for i, g in enumerate(gaps, start=1):
        g["_id"] = f"ENG-{i}"
        g["_type"] = "engineering"
        g.setdefault("opportunity_mode", GROUNDED_TRANSFER)
        _ensure_field_alignment(g, {})
    _inherit_theoretical_origin(gaps, grounded_theoretical_gaps)
    log.info("Generated %d engineering gaps", len(gaps))
    return gaps


def _expand_engineering_gaps_with_recovery(*, system: str, user_template: str,
                                           user_kwargs: dict,
                                           theoretical_gaps: list[dict],
                                           client: LLMClient,
                                           adversarial_mode: bool) -> list[dict]:
    """Expand engineering gaps, isolating verbose failures by theory source."""
    try:
        return _request_engineering_gaps(
            system=system,
            user_template=user_template,
            user_kwargs=user_kwargs,
            theoretical_gaps=theoretical_gaps,
            client=client,
            adversarial_mode=adversarial_mode,
        )
    except Exception as e:
        if len(theoretical_gaps) <= 1:
            log.warning("Engineering gap LLM call failed: %s (returning [])", e)
            return []
        log.warning(
            "Engineering gap batch expansion failed: %s; retrying %d theories individually",
            e,
            len(theoretical_gaps),
        )

    recovered: list[dict] = []
    for theory in theoretical_gaps:
        try:
            recovered.extend(_request_engineering_gaps(
                system=system,
                user_template=user_template,
                user_kwargs=user_kwargs,
                theoretical_gaps=[theory],
                client=client,
                adversarial_mode=adversarial_mode,
            ))
        except Exception as e:
            log.warning(
                "Engineering gap recovery failed for theory %s: %s (skipping theory)",
                theory.get("_id", "?"),
                e,
            )
        if len(recovered) >= MAX_ENGINEERING_GAPS:
            break
    return recovered[:MAX_ENGINEERING_GAPS]


def _request_engineering_gaps(*, system: str, user_template: str, user_kwargs: dict,
                              theoretical_gaps: list[dict], client: LLMClient,
                              adversarial_mode: bool) -> list[dict]:
    user = render_template(
        user_template,
        **user_kwargs,
        theoretical_gaps_today_json=json.dumps(theoretical_gaps, ensure_ascii=False, indent=2),
    )
    if adversarial_mode:
        user += (
            "\n\n【对抗审计模式已开启】\n"
            "你只能把上方已经通过 risk audit 并产出的理论型 gap 升级为工程型。"
            "不得创建独立于这些理论 gap 的新方向。"
            "每条输出必须填写 upgraded_from_theoretical 为对应理论 gap 的 _id；"
            "无法升级则输出空数组。\n"
        )
    result = client.chat_json(
        system=system,
        user=user,
        temperature=0.4,
        reasoning=True,
        max_tokens=ENGINEERING_EXPANSION_MAX_TOKENS,
    )
    return result.get("gaps", []) if isinstance(result, dict) else []


def repair_engineering_gap(gap: dict, check: dict, context: dict,
                           client: LLMClient | None = None) -> dict | None:
    """Repair an engineering gap whose roadmap drifted away from its transfer cell.

    This is intentionally narrow: it never fixes invalid anchors, duplicates, or
    brand-name errors. It only gives Prompt 05B one chance to re-lock data,
    metrics, baselines, ablations, and empirical controls to the selected cell.
    """
    cell = _selected_transfer_cell(gap, context.get("fin_transfer_cells", []))
    if not cell:
        return None
    client = client or LLMClient()
    system, user_template = parse_prompt("05B_gap_engineering_repair")
    field = _selected_field_boundary(gap, context.get("fin_field_boundaries", []))
    user = render_template(
        user_template,
        gap_json=json.dumps(gap, ensure_ascii=False, indent=2),
        self_check_json=json.dumps(check, ensure_ascii=False, indent=2),
        transfer_cell_json=json.dumps(cell, ensure_ascii=False, indent=2),
        fin_field_boundary_json=json.dumps(field or {}, ensure_ascii=False, indent=2),
    )
    result = client.chat_json(
        system=system,
        user=user,
        temperature=0.2,
        reasoning=True,
        max_tokens=ENGINEERING_REPAIR_MAX_TOKENS,
    )
    repaired = result.get("gap") if isinstance(result, dict) else None
    if not isinstance(repaired, dict):
        return None
    repaired = _preserve_gap_metadata(gap, repaired)
    repaired["_repair"] = {
        "source": "05B_gap_engineering_repair",
        "original_verdict": check.get("overall_verdict", ""),
        "original_summary": check.get("verdict_summary", ""),
        "transfer_cell_id": cell.get("cell_id", ""),
    }
    return repaired


def _preserve_gap_metadata(original: dict, repaired: dict) -> dict:
    keep_keys = (
        "_id", "_type", "_origin", "risk_audit", "opportunity_mode",
        "upgraded_from_theoretical", "proposed_cell",
    )
    out = dict(repaired)
    for key in keep_keys:
        if original.get(key) is not None:
            out[key] = original[key]
    original_alignment = original.get("field_boundary_alignment")
    repaired_alignment = out.get("field_boundary_alignment")
    if isinstance(original_alignment, dict):
        if not isinstance(repaired_alignment, dict):
            repaired_alignment = {}
        out["field_boundary_alignment"] = {
            **original_alignment,
            **{k: v for k, v in repaired_alignment.items() if v},
        }
    return out


def _selected_transfer_cell(gap: dict, cells: list[dict]) -> dict | None:
    alignment = gap.get("field_boundary_alignment") or {}
    if not isinstance(alignment, dict):
        return None
    cell_id = alignment.get("transfer_cell_id")
    if not cell_id:
        return None
    return next((cell for cell in cells if cell.get("cell_id") == cell_id), None)


def _selected_field_boundary(gap: dict, boundaries: list[dict]) -> dict | None:
    alignment = gap.get("field_boundary_alignment") or {}
    if not isinstance(alignment, dict):
        return None
    field_id = alignment.get("field_id")
    if not field_id:
        return None
    return next((field for field in boundaries if field.get("id") == field_id), None)


def _should_repair_engineering_gap(gap_type: str, check: dict) -> bool:
    if gap_type != "engineering":
        return False
    verdict = check.get("overall_verdict")
    if verdict not in {"reject", "downgrade", "retry"}:
        return False
    failed = _failed_check_keys(check)
    if failed & {"A_anchor_validity", "B_duplication", "M_no_brand_in_hypothesis"}:
        return False
    repairable = {
        "O_field_boundary_alignment",
        "F_data_concrete",
        "G_method_detail",
        "H_metrics_quantitative",
        "I_baselines_sufficient",
        "J_ablations_present",
        "K_no_TBD",
        "P_empirical_validity_risk",
        "Q_first_experiment_go_no_go",
    }
    return bool(failed & repairable)


def _failed_check_keys(check: dict) -> set[str]:
    checks = check.get("checks")
    if not isinstance(checks, dict):
        return set()
    failed: set[str] = set()
    for key, value in checks.items():
        if isinstance(value, dict) and value.get("pass") is False:
            failed.add(key)
    return failed


def _candidate_alignments(candidates: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for c in candidates:
        idx = c.get("idx")
        if idx is None:
            continue
        alignment = c.get("field_boundary_alignment")
        if not isinstance(alignment, dict):
            alignment = {
                "field_id": c.get("field_id", ""),
                "mechanism_family": c.get("mechanism_family", ""),
                "open_bottleneck": c.get("open_bottleneck", ""),
                "good_transfer_target": c.get("good_transfer_target", ""),
                "bad_target_avoided": c.get("bad_target_avoided", ""),
                "why_aligned": c.get("why_aligned", ""),
                "transfer_cell_id": c.get("transfer_cell_id", ""),
            }
        out[str(idx)] = {k: v for k, v in alignment.items() if v}
    return out


def _candidate_audits(candidates: list[dict]) -> dict[str, dict]:
    return {
        str(candidate["idx"]): candidate["risk_audit"]
        for candidate in candidates
        if candidate.get("idx") is not None and isinstance(candidate.get("risk_audit"), dict)
    }


def _candidate_origins(candidates: list[dict]) -> dict[str, dict]:
    origins: dict[str, dict] = {}
    for candidate in candidates:
        idx = candidate.get("idx")
        if idx is None:
            continue
        audit = candidate.get("risk_audit") or {}
        origins[str(idx)] = {
            "candidate_idx": idx,
            "candidate_one_liner": candidate.get("one_liner", ""),
            "original_one_liner": candidate.get("original_one_liner", ""),
            "audit_verdict": audit.get("verdict", ""),
            "audit_failure_classes": audit.get("failure_classes", []),
        }
    return origins


def _candidate_routes(candidates: list[dict]) -> dict[str, dict]:
    routes: dict[str, dict] = {}
    for candidate in candidates:
        idx = candidate.get("idx")
        if idx is None:
            continue
        routes[str(idx)] = {
            "opportunity_mode": _opportunity_mode(candidate),
            "proposed_cell": candidate.get("proposed_cell") or {},
        }
    return routes


def _ensure_field_alignment(gap: dict, candidate_alignments: dict[str, dict]) -> None:
    alignment = gap.get("field_boundary_alignment")
    if not isinstance(alignment, dict):
        alignment = {}
    source_idx = gap.get("source_candidate_idx") or gap.get("candidate_idx")
    if source_idx is not None and str(source_idx) in candidate_alignments:
        inherited = candidate_alignments[str(source_idx)]
        gap["field_boundary_alignment"] = {**inherited, **{k: v for k, v in alignment.items() if v}}
        return
    gap["field_boundary_alignment"] = alignment


def _ensure_risk_audit(gap: dict, candidate_audits: dict[str, dict]) -> None:
    source_idx = gap.get("source_candidate_idx") or gap.get("candidate_idx")
    if source_idx is not None and str(source_idx) in candidate_audits:
        gap["risk_audit"] = candidate_audits[str(source_idx)]


def _ensure_origin(gap: dict, candidate_origins: dict[str, dict]) -> None:
    source_idx = gap.get("source_candidate_idx") or gap.get("candidate_idx")
    if source_idx is not None and str(source_idx) in candidate_origins:
        gap["_origin"] = candidate_origins[str(source_idx)]


def _ensure_opportunity_route(gap: dict, candidate_routes: dict[str, dict]) -> None:
    source_idx = gap.get("source_candidate_idx") or gap.get("candidate_idx")
    route = candidate_routes.get(str(source_idx)) if source_idx is not None else None
    if route:
        gap.setdefault("opportunity_mode", route["opportunity_mode"])
        if route["proposed_cell"]:
            gap.setdefault("proposed_cell", route["proposed_cell"])
    else:
        gap.setdefault("opportunity_mode", _opportunity_mode(gap))


def _inherit_theoretical_origin(engineering_gaps: list[dict],
                                theoretical_gaps: list[dict]) -> None:
    theories = {gap.get("_id"): gap for gap in theoretical_gaps}
    for gap in engineering_gaps:
        source_id = gap.get("upgraded_from_theoretical")
        source = theories.get(source_id)
        if not source:
            continue
        origin = dict(source.get("_origin") or {})
        origin["theoretical_gap_id"] = source_id
        gap["_origin"] = origin
        if source.get("risk_audit"):
            gap["risk_audit"] = source["risk_audit"]
        if source.get("opportunity_mode"):
            gap.setdefault("opportunity_mode", source["opportunity_mode"])
        if source.get("proposed_cell"):
            gap.setdefault("proposed_cell", source["proposed_cell"])
        source_alignment = source.get("field_boundary_alignment")
        if isinstance(source_alignment, dict):
            alignment = gap.get("field_boundary_alignment")
            if not isinstance(alignment, dict):
                alignment = {}
            gap["field_boundary_alignment"] = {
                **source_alignment,
                **{k: v for k, v in alignment.items() if v},
            }


def _only_reviewed_theoretical_gaps(gaps: list[dict], candidates: list[dict]) -> list[dict]:
    approved_idxs = {str(c.get("idx")) for c in candidates if c.get("idx") is not None}
    retained = [
        gap for gap in gaps
        if str(gap.get("source_candidate_idx") or gap.get("candidate_idx")) in approved_idxs
    ]
    if len(retained) != len(gaps):
        log.warning(
            "Adversarial mode dropped %d theoretical gaps without an audited candidate source",
            len(gaps) - len(retained),
        )
    return retained


def _only_upgraded_engineering_gaps(gaps: list[dict], theoretical_gaps: list[dict]) -> list[dict]:
    theory_ids = {gap.get("_id") for gap in theoretical_gaps}
    retained = [
        gap for gap in gaps
        if gap.get("upgraded_from_theoretical") in theory_ids
    ]
    if len(retained) != len(gaps):
        log.warning(
            "Adversarial mode dropped %d engineering gaps that bypassed reviewed theory",
            len(gaps) - len(retained),
        )
    return retained


def suppress_theoretical_email_duplicates(email_ready: list[dict]) -> tuple[list[dict], list[dict]]:
    """Suppress theoretical email entries already covered by an engineering one.

    Engineering gaps contain the actionable experiment and therefore win when
    both channels describe the same mechanism transfer. Suppressed theoretical
    gaps remain accepted for audit; downstream delivery and mapping drafting can
    omit them using the suppression marker attached here.
    """
    engineering = [item for item in email_ready if item.get("type") == "engineering"]
    kept: list[dict] = []
    suppressed: list[dict] = []

    for item in email_ready:
        if item.get("type") != "theoretical":
            kept.append(item)
            continue

        duplicate = _find_covering_engineering_gap(item, engineering)
        if duplicate is None:
            kept.append(item)
            continue

        engineering_item, reason = duplicate
        item["_email_suppressed_by"] = engineering_item["gap"].get("_id", "?")
        item["_email_suppressed_reason"] = reason
        suppressed.append(item)

    return kept, suppressed


def _find_covering_engineering_gap(theoretical: dict,
                                   engineering: list[dict]) -> tuple[dict, str] | None:
    theoretical_gap = theoretical.get("gap") or {}
    theory_id = theoretical_gap.get("_id")
    for item in engineering:
        engineering_gap = item.get("gap") or {}
        upgraded_from = (
            engineering_gap.get("upgraded_from_theoretical")
            or engineering_gap.get("upgraded_from_theoretical_id")
        )
        if theory_id and upgraded_from == theory_id:
            return item, f"explicit engineering upgrade of {theory_id}"

        if not _same_field_mechanism_boundary(theoretical_gap, engineering_gap):
            continue
        similarity = scoring_mod._similarity(
            _duplicate_comparison_text(theoretical_gap),
            _duplicate_comparison_text(engineering_gap),
        )
        if similarity >= EMAIL_DUPLICATE_SIMILARITY_THRESHOLD:
            return item, (
                "same Fin mechanism boundary and overlapping transfer hypothesis "
                f"(similarity={similarity:.3f})"
            )
    return None


def _same_field_mechanism_boundary(left: dict, right: dict) -> bool:
    left_field = left.get("field_boundary_alignment") or {}
    right_field = right.get("field_boundary_alignment") or {}
    keys = ("field_id", "mechanism_family")
    return all(
        left_field.get(key)
        and left_field.get(key) == right_field.get(key)
        for key in keys
    )


def _duplicate_comparison_text(gap: dict) -> str:
    ai_anchor = gap.get("ai_anchor") or {}
    fin_anchor = gap.get("fin_anchor") or {}
    structural = gap.get("structural_mapping") or {}
    return " ".join(
        str(value)
        for value in [
            gap.get("hypothesis", ""),
            ai_anchor.get("concept", ""),
            fin_anchor.get("description", ""),
            structural.get("bridge_required", ""),
        ]
        if value
    )


# ---------- Orchestrator: generate → self-check → score ----------

def run_gap_pipeline(end_date: date | None = None,
                     *, ai_top: int = 20, fin_top: int = 10,
                     window_days_ai: int | None = None,
                     window_days_fin: int | None = None,
                     window_days: int | None = None,
                     include_trends: bool = False,
                     adversarial_review: bool | None = None,
                     client: LLMClient | None = None) -> dict:
    """Full daily gap pipeline (asymmetric windows by default).

    Returns:
      {context, theoretical, engineering, accepted, rejected, downgraded, email_ready}
    """
    client = client or LLMClient()
    adversarial_review = (
        os.getenv("ADVERSARIAL_GAP_REVIEW", "false").lower() == "true"
        if adversarial_review is None else adversarial_review
    )
    ctx = build_gap_context(
        end_date, ai_top=ai_top, fin_top=fin_top,
        window_days_ai=window_days_ai, window_days_fin=window_days_fin,
        window_days=window_days, include_trends=include_trends, client=client,
    )

    # Two-stage generation: keep exploration bounded so the daily budget goes to experiments.
    # Stage A: enumerate a short one-liner candidate pool.
    raw_candidates = enumerate_candidates(ctx, client=client)
    if adversarial_review:
        reviewed_candidates, risk_audit = risk_audit_mod.audit_candidates(
            raw_candidates, ctx, client=client,
        )
    else:
        reviewed_candidates = raw_candidates
        risk_audit = {
            "enabled": False,
            "mode": "standard",
            "input_candidates": len(raw_candidates),
            "retained": len(raw_candidates),
            "decisions": [],
        }
    gate_enforced = adversarial_review and not risk_audit.get("fallback", False)
    risk_audit["gate_enforced"] = gate_enforced
    top_candidates = select_top_candidates(
        reviewed_candidates, top_n=MAX_CANDIDATES_FOR_REFINEMENT,
    )
    log.info(
        "Two-stage%s: %d raw → %d post-audit → %d selected candidates for refinement",
        " + adversarial audit" if adversarial_review else "",
        len(raw_candidates), len(reviewed_candidates), len(top_candidates),
    )

    # Stage B: refine selected candidates into full gaps
    if gate_enforced and not top_candidates:
        th_gaps = []
        eng_gaps = []
    else:
        th_gaps = generate_theoretical_gaps(ctx, client=client, candidates=top_candidates)
        if gate_enforced:
            th_gaps = _only_reviewed_theoretical_gaps(th_gaps, top_candidates)
        eng_gaps = generate_engineering_gaps(
            ctx, th_gaps, client=client, adversarial_mode=gate_enforced,
        )
        if gate_enforced:
            eng_gaps = _only_upgraded_engineering_gaps(eng_gaps, th_gaps)
    all_gaps = [(g, "engineering") for g in eng_gaps] + [(g, "theoretical") for g in th_gaps]

    accepted: list[dict] = []
    rejected: list[dict] = []
    downgraded: list[dict] = []

    valid_ai = ctx["_valid_ai_ids"]
    valid_fin = ctx["_valid_fin_ids"]
    mappings_brief = ctx["_mappings_brief"]
    ai_method_names = _ai_method_names(
        ctx["ai_recent_papers"] + ctx.get("historical_ai_mechanisms", [])
    )

    for gap, gtype in all_gaps:
        try:
            check = sc_mod.check_gap(
                gap,
                gtype,
                valid_ai,
                valid_fin,
                mappings_brief,
                fin_field_boundaries=ctx.get("fin_field_boundaries", []),
                fin_transfer_cells=ctx.get("fin_transfer_cells", []),
                ai_method_names=ai_method_names,
                client=client,
            )
        except Exception as e:
            log.warning("Self-check failed for gap %s: %s (skipping)", gap.get("_id", "?"), e)
            rejected.append({"gap": gap, "type": gtype,
                             "check": {"overall_verdict": "error", "error": str(e)}})
            continue
        verdict = check["overall_verdict"]

        repair_attempt: dict | None = None
        if _should_repair_engineering_gap(gtype, check):
            try:
                repaired = repair_engineering_gap(gap, check, ctx, client=client)
            except Exception as e:
                log.warning("Engineering repair failed for gap %s: %s", gap.get("_id", "?"), e)
                repaired = None
                repair_attempt = {"error": str(e)}
            if repaired:
                try:
                    repaired_check = sc_mod.check_gap(
                        repaired,
                        gtype,
                        valid_ai,
                        valid_fin,
                        mappings_brief,
                        fin_field_boundaries=ctx.get("fin_field_boundaries", []),
                        fin_transfer_cells=ctx.get("fin_transfer_cells", []),
                        ai_method_names=ai_method_names,
                        client=client,
                    )
                except Exception as e:
                    log.warning("Self-check failed for repaired gap %s: %s", gap.get("_id", "?"), e)
                    repaired_check = {"overall_verdict": "error", "error": str(e)}
                repair_attempt = {"gap": repaired, "check": repaired_check}
                if repaired_check.get("overall_verdict") == "accept":
                    gap = repaired
                    check = repaired_check
                    verdict = "accept"
                    log.info("Engineering repair accepted gap %s", gap.get("_id", "?"))
                else:
                    log.info(
                        "Engineering repair did not pass gap %s: %s",
                        gap.get("_id", "?"),
                        repaired_check.get("overall_verdict"),
                    )

        if verdict == "accept":
            try:
                score = scoring_mod.score_gap(gap, gtype, mappings_brief, client=client)
            except Exception as e:
                log.warning("Scoring failed for gap %s: %s (skipping)", gap.get("_id", "?"), e)
                rejected.append({"gap": gap, "type": gtype, "check": check,
                                 "score_error": str(e)})
                continue
            item = {"gap": gap, "type": gtype, "check": check, "score": score}
            if repair_attempt:
                item["repair"] = repair_attempt
            accepted.append(item)
        elif verdict == "reject":
            item = {"gap": gap, "type": gtype, "check": check}
            if repair_attempt:
                item["repair"] = repair_attempt
            rejected.append(item)
        elif verdict == "downgrade" and gtype == "engineering":
            tg = sc_mod.downgrade_to_theoretical(gap)
            try:
                re_check = sc_mod.check_gap(tg, "theoretical", valid_ai, valid_fin,
                                             mappings_brief,
                                             fin_field_boundaries=ctx.get("fin_field_boundaries", []),
                                             fin_transfer_cells=ctx.get("fin_transfer_cells", []),
                                             ai_method_names=ai_method_names,
                                             client=client)
            except Exception as e:
                log.warning("Re-check failed for downgraded gap %s: %s", gap.get("_id", "?"), e)
                item = {"gap": gap, "type": gtype, "check": check, "error": str(e)}
                if repair_attempt:
                    item["repair"] = repair_attempt
                downgraded.append(item)
                continue
            if re_check["overall_verdict"] == "accept":
                try:
                    score = scoring_mod.score_gap(tg, "theoretical", mappings_brief, client=client)
                except Exception as e:
                    log.warning("Scoring failed for downgraded gap: %s", e)
                    continue
                accepted.append({"gap": tg, "type": "theoretical",
                                "check": re_check, "score": score,
                                "_downgraded_from": gap.get("_id")})
            else:
                item = {"gap": gap, "type": gtype, "check": check, "recheck": re_check}
                if repair_attempt:
                    item["repair"] = repair_attempt
                downgraded.append(item)
        else:
            item = {"gap": gap, "type": gtype, "check": check}
            if repair_attempt:
                item["repair"] = repair_attempt
            rejected.append(item)

    email_ready = select_email_experiments(accepted)
    theoretical_leads = select_theoretical_leads(accepted, email_ready)
    duplicates_suppressed: list[dict] = []
    log.info(
        "Gap pipeline: %d generated → %d accepted → %d email-ready "
        "+ %d theoretical leads (%d theoretical duplicates suppressed) ($%.4f)",
        len(all_gaps), len(accepted), len(email_ready), len(theoretical_leads),
        len(duplicates_suppressed), client.estimate_cost_usd(),
    )

    return {
        "context": ctx,
        "risk_audit": risk_audit,
        "theoretical": th_gaps,
        "engineering": eng_gaps,
        "accepted": accepted,
        "rejected": rejected,
        "downgraded": downgraded,
        "email_ready": email_ready,
        "theoretical_leads": theoretical_leads,
        "duplicates_suppressed": duplicates_suppressed,
    }


def select_email_experiments(accepted: list[dict],
                             limit: int = MAX_ENGINEERING_GAPS) -> list[dict]:
    """Keep the daily email about immediately runnable, reviewed experiments."""
    return [
        item for item in accepted
        if item.get("type") == "engineering"
        and item.get("score", {}).get("passes_email_threshold")
    ][:limit]


def select_theoretical_leads(accepted: list[dict], email_ready: list[dict],
                             limit: int = MAX_THEORETICAL_LEADS) -> list[dict]:
    """O4: thin-day fallback — surface accepted theoretical gaps as exploratory
    'leads' so the daily output is never empty.

    These are NOT runnable experiments (no go/no-go-gated engineering plan), but
    accepted theoretical gaps are still worth a human glance: they may mature into
    an experiment or seed a new transfer cell. We only surface them when there are
    fewer runnable experiments than the daily target, and we exclude any theoretical
    gap already represented by an email-ready engineering experiment for the same
    candidate (avoid showing a lead and its upgraded experiment side by side).
    """
    if len(email_ready) >= MAX_ENGINEERING_GAPS:
        return []

    def _cand_key(g: dict):
        return g.get("source_candidate_idx") or g.get("candidate_idx")

    promoted = {k for k in (_cand_key(item["gap"]) for item in email_ready) if k is not None}
    leads = [
        item for item in accepted
        if item.get("type") == "theoretical"
        and _cand_key(item["gap"]) not in promoted
    ]
    leads.sort(key=lambda it: it.get("score", {}).get("total", 0), reverse=True)
    return leads[:limit]


def _ai_method_names(ai_recent_papers: list[dict]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for paper in ai_recent_papers:
        for method in paper.get("method_primary") or []:
            name = (method or "").strip()
            key = name.lower()
            if not name or key in seen:
                continue
            seen.add(key)
            out.append(name)
    return out


# ---------- CLI smoke test ----------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--window-ai", type=int, default=None,
                        help="AI side window in days (default 90)")
    parser.add_argument("--window-fin", type=int, default=None,
                        help="Fin side window in days (default 180)")
    parser.add_argument("--window", type=int, default=None,
                        help="Override both windows (debug)")
    parser.add_argument("--end-date", help="ISO date, default today")
    parser.add_argument("--ai-top", type=int, default=20)
    parser.add_argument("--fin-top", type=int, default=10)
    parser.add_argument("--full", action="store_true",
                        help="Run full pipeline (gen → self-check → score)")
    parser.add_argument("--with-trends", action="store_true",
                        help="Include expensive Prompt 03 trend clustering (maintenance/debug only)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    client = LLMClient()

    window_kwargs = {
        "window_days_ai": args.window_ai,
        "window_days_fin": args.window_fin,
    }
    if args.window:
        window_kwargs = {"window_days": args.window}

    if args.full:
        result = run_gap_pipeline(end, ai_top=args.ai_top, fin_top=args.fin_top,
                                  include_trends=args.with_trends, client=client, **window_kwargs)
        print(f"\n=== Pipeline summary ===")
        print(f"Generated: {len(result['theoretical'])} theoretical + {len(result['engineering'])} engineering")
        print(f"Accepted:  {len(result['accepted'])}")
        print(f"Rejected:  {len(result['rejected'])}")
        print(f"Downgraded:{len(result['downgraded'])}")
        print(f"Email-ready (total >= 8): {len(result['email_ready'])}\n")

        for item in result["email_ready"]:
            g = item["gap"]
            print(f"[{g['_id']}] ({item['type']}) total={item['score']['total']} "
                  f"nov={item['score']['novelty']} act={item['score']['actionability']}")
            print(f"   {g.get('hypothesis', '???')}")
            print()

        print(f"\nAll accepted (incl. below threshold):")
        for item in result["accepted"]:
            g = item["gap"]
            print(f"  [{g['_id']}] {item['type']} t={item['score']['total']} | {g.get('hypothesis', '?')[:80]}")
    else:
        ctx = build_gap_context(end, ai_top=args.ai_top, fin_top=args.fin_top,
                                include_trends=args.with_trends, client=client, **window_kwargs)
        print(f"AI papers: {len(ctx['ai_recent_papers'])} | Fin: {len(ctx['fin_recent_papers'])}")

        th_gaps = generate_theoretical_gaps(ctx, client=client)
        for g in th_gaps:
            print(f"\n[{g['_id']}] {g.get('hypothesis', '???')}")
        eng_gaps = generate_engineering_gaps(ctx, th_gaps, client=client)
        for g in eng_gaps:
            print(f"\n[{g['_id']}] {g.get('hypothesis', '???')}")

    in_tok, out_tok = client.total_tokens
    print(f"\nTokens: in={in_tok} out={out_tok} | est cost: ${client.estimate_cost_usd():.4f}")
