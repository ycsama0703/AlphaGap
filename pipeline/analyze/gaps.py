"""Gap generation — Prompts 04 (theoretical) + 05 (engineering).

Calls 04 first, then 05 with today's theoretical gaps as additional context
so 05 can upgrade weak theoretical proposals to fully-specified engineering ones.
"""
from __future__ import annotations

import json
import logging
from datetime import date

from ..extract.concepts import parse_prompt, render_template
from ..llm_client import LLMClient
from . import context as ctx_builder
from . import scoring as scoring_mod
from . import self_check as sc_mod
from . import trends as trends_mod
from . import uptake as uptake_mod


log = logging.getLogger(__name__)


def build_gap_context(end_date: date | None = None,
                      *, ai_top: int = 20, fin_top: int = 10,
                      window_days_ai: int | None = None,
                      window_days_fin: int | None = None,
                      window_days: int | None = None,   # legacy override
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

    ai_papers = ctx_builder.get_top_papers("ai", end, top_n=ai_top, window_days=wd_ai)
    fin_papers = ctx_builder.get_top_papers("fin", end, top_n=fin_top, window_days=wd_fin)
    mappings = ctx_builder.load_existing_mappings()

    ai_trends = trends_mod.summarize_trends("ai", end, client=client, window_days=wd_ai)
    fin_trends = trends_mod.summarize_trends("fin", end, client=client, window_days=wd_fin)

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
        "fin_recent_papers": [ctx_builder.paper_for_prompt(p) for p in fin_papers],
        "ai_trends": _strip_meta(ai_trends),
        "fin_trends": _strip_meta(fin_trends),
        "existing_mappings": [ctx_builder.mapping_for_prompt(m) for m in mappings],
        "fin_uptake": fin_uptake,    # ← Tier 1.1: hard negative-evidence ground truth
        # raw refs for downstream validation
        "_valid_ai_ids": {p["id"] for p in ai_papers},
        "_valid_fin_ids": {p["id"] for p in fin_papers},
        "_mappings_brief": [ctx_builder.mapping_brief(m) for m in mappings],
    }


def _strip_meta(trends: dict) -> dict:
    return {k: v for k, v in trends.items() if k != "_meta"}


def enumerate_candidates(context: dict, client: LLMClient | None = None) -> list[dict]:
    """Prompt 04A → 15-25 one-liner candidates with diversity constraints."""
    client = client or LLMClient()
    system, user_template = parse_prompt("04A_gap_enumerate")
    user = render_template(
        user_template,
        ai_recent_papers_json=json.dumps(context["ai_recent_papers"], ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
    )
    try:
        result = client.chat_json(system=system, user=user, temperature=0.8, max_tokens=3000)
    except Exception as e:
        log.warning("Enumerate LLM call failed: %s (returning [])", e)
        return []
    candidates = result.get("candidates", []) if isinstance(result, dict) else []

    # Validate anchor IDs are real
    valid_ai = context.get("_valid_ai_ids", set())
    candidates = [c for c in candidates if c.get("ai_anchor_paper_id") in valid_ai]
    log.info("Enumerate: %d valid candidates from Prompt 04A", len(candidates))
    return candidates


def select_top_candidates(candidates: list[dict], top_n: int = 8) -> list[dict]:
    """Diversify + pick top N from candidate pool.

    Priority order:
      1. fin_uptake_status = open_gap > partial > explored
      2. ai_category diversity (≤ 2 per category)
    """
    status_order = {"open_gap": 0, "partial": 1, "explored": 2}
    candidates.sort(key=lambda c: status_order.get(c.get("fin_uptake_status", "explored"), 3))

    per_cat: dict[str, int] = {}
    selected = []
    for c in candidates:
        cat = c.get("ai_category", "other")
        if per_cat.get(cat, 0) >= 2:
            continue
        per_cat[cat] = per_cat.get(cat, 0) + 1
        selected.append(c)
        if len(selected) >= top_n:
            break
    return selected


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
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
    )
    if candidates:
        # Refine mode: tell LLM to expand THESE specific candidates
        prefix = (
            f"\n\n【已挑选的候选 candidates，请你只精雕这些，每条扩展为完整 gap】\n"
            f"{json.dumps(candidates, ensure_ascii=False, indent=2)}\n"
        )
        user = render_template(user_template, **user_kwargs) + prefix
    else:
        user = render_template(user_template, **user_kwargs)
    try:
        result = client.chat_json(system=system, user=user, temperature=0.6, max_tokens=4096)
    except Exception as e:
        log.warning("Theoretical gap LLM call failed: %s (returning [])", e)
        return []
    gaps = result.get("gaps", []) if isinstance(result, dict) else []
    for i, g in enumerate(gaps, start=1):
        g.setdefault("_id", f"TH-{i}")
        g["_type"] = "theoretical"
    log.info("Generated %d theoretical gaps", len(gaps))
    return gaps


def generate_engineering_gaps(context: dict, theoretical_gaps: list[dict],
                              client: LLMClient | None = None) -> list[dict]:
    """Prompt 05 → 0-3 engineering gap candidates (with full experimental roadmap)."""
    client = client or LLMClient()
    system, user_template = parse_prompt("05_gap_engineering")
    user = render_template(
        user_template,
        ai_recent_papers_json=json.dumps(context["ai_recent_papers"], ensure_ascii=False, indent=2),
        fin_recent_papers_json=json.dumps(context["fin_recent_papers"], ensure_ascii=False, indent=2),
        ai_trends_json=json.dumps(context["ai_trends"], ensure_ascii=False, indent=2),
        fin_trends_json=json.dumps(context["fin_trends"], ensure_ascii=False, indent=2),
        existing_mappings_json=json.dumps(context["existing_mappings"], ensure_ascii=False, indent=2),
        fin_uptake_json=json.dumps(context.get("fin_uptake", {}), ensure_ascii=False, indent=2),
        theoretical_gaps_today_json=json.dumps(theoretical_gaps, ensure_ascii=False, indent=2),
    )
    try:
        result = client.chat_json(system=system, user=user, temperature=0.4, max_tokens=6144)
    except Exception as e:
        log.warning("Engineering gap LLM call failed: %s (returning [])", e)
        return []
    gaps = result.get("gaps", []) if isinstance(result, dict) else []
    for i, g in enumerate(gaps, start=1):
        g.setdefault("_id", f"ENG-{i}")
        g["_type"] = "engineering"
    log.info("Generated %d engineering gaps", len(gaps))
    return gaps


# ---------- Orchestrator: generate → self-check → score ----------

def run_gap_pipeline(end_date: date | None = None,
                     *, ai_top: int = 20, fin_top: int = 10,
                     window_days_ai: int | None = None,
                     window_days_fin: int | None = None,
                     window_days: int | None = None,
                     client: LLMClient | None = None) -> dict:
    """Full daily gap pipeline (asymmetric windows by default).

    Returns:
      {context, theoretical, engineering, accepted, rejected, downgraded, email_ready}
    """
    client = client or LLMClient()
    ctx = build_gap_context(
        end_date, ai_top=ai_top, fin_top=fin_top,
        window_days_ai=window_days_ai, window_days_fin=window_days_fin,
        window_days=window_days, client=client,
    )

    # Tier 1.3: Two-stage generation
    # Stage A: enumerate 15-25 one-liner candidates (cheap, diverse)
    raw_candidates = enumerate_candidates(ctx, client=client)
    top_candidates = select_top_candidates(raw_candidates, top_n=8)
    log.info("Two-stage: %d raw → %d selected candidates for refinement",
             len(raw_candidates), len(top_candidates))

    # Stage B: refine selected candidates into full gaps
    th_gaps = generate_theoretical_gaps(ctx, client=client, candidates=top_candidates)
    eng_gaps = generate_engineering_gaps(ctx, th_gaps, client=client)
    all_gaps = [(g, "engineering") for g in eng_gaps] + [(g, "theoretical") for g in th_gaps]

    accepted: list[dict] = []
    rejected: list[dict] = []
    downgraded: list[dict] = []

    valid_ai = ctx["_valid_ai_ids"]
    valid_fin = ctx["_valid_fin_ids"]
    mappings_brief = ctx["_mappings_brief"]

    for gap, gtype in all_gaps:
        try:
            check = sc_mod.check_gap(gap, gtype, valid_ai, valid_fin, mappings_brief, client=client)
        except Exception as e:
            log.warning("Self-check failed for gap %s: %s (skipping)", gap.get("_id", "?"), e)
            rejected.append({"gap": gap, "type": gtype,
                             "check": {"overall_verdict": "error", "error": str(e)}})
            continue
        verdict = check["overall_verdict"]

        if verdict == "accept":
            try:
                score = scoring_mod.score_gap(gap, gtype, mappings_brief, client=client)
            except Exception as e:
                log.warning("Scoring failed for gap %s: %s (skipping)", gap.get("_id", "?"), e)
                rejected.append({"gap": gap, "type": gtype, "check": check,
                                 "score_error": str(e)})
                continue
            accepted.append({"gap": gap, "type": gtype, "check": check, "score": score})
        elif verdict == "reject":
            rejected.append({"gap": gap, "type": gtype, "check": check})
        elif verdict == "downgrade" and gtype == "engineering":
            tg = sc_mod.downgrade_to_theoretical(gap)
            try:
                re_check = sc_mod.check_gap(tg, "theoretical", valid_ai, valid_fin,
                                             mappings_brief, client=client)
            except Exception as e:
                log.warning("Re-check failed for downgraded gap %s: %s", gap.get("_id", "?"), e)
                downgraded.append({"gap": gap, "type": gtype, "check": check, "error": str(e)})
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
                downgraded.append({"gap": gap, "type": gtype, "check": check,
                                   "recheck": re_check})
        else:
            rejected.append({"gap": gap, "type": gtype, "check": check})

    email_ready = [a for a in accepted if a["score"]["passes_email_threshold"]]
    log.info("Gap pipeline: %d generated → %d accepted → %d email-ready ($%.4f)",
             len(all_gaps), len(accepted), len(email_ready), client.estimate_cost_usd())

    return {
        "context": ctx,
        "theoretical": th_gaps,
        "engineering": eng_gaps,
        "accepted": accepted,
        "rejected": rejected,
        "downgraded": downgraded,
        "email_ready": email_ready,
    }


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
                                  client=client, **window_kwargs)
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
                                client=client, **window_kwargs)
        print(f"AI papers: {len(ctx['ai_recent_papers'])} | Fin: {len(ctx['fin_recent_papers'])}")

        th_gaps = generate_theoretical_gaps(ctx, client=client)
        for g in th_gaps:
            print(f"\n[{g['_id']}] {g.get('hypothesis', '???')}")
        eng_gaps = generate_engineering_gaps(ctx, th_gaps, client=client)
        for g in eng_gaps:
            print(f"\n[{g['_id']}] {g.get('hypothesis', '???')}")

    in_tok, out_tok = client.total_tokens
    print(f"\nTokens: in={in_tok} out={out_tok} | est cost: ${client.estimate_cost_usd():.4f}")
