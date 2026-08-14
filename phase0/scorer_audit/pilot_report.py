from __future__ import annotations

import json
import math
import random
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _latest(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        latest[row["uid"]] = row
    return latest


def _normalized_status(row: dict[str, Any]) -> str:
    if row.get("status") == "error" and "empty content (finish_reason='length'" in row.get("error", ""):
        return "truncated"
    return row.get("status", "unknown")


def _exact_binomial_two_sided(successes: int, trials: int) -> float:
    if trials == 0:
        return 1.0
    observed = math.comb(trials, successes) / (2**trials)
    return min(
        1.0,
        sum(
            math.comb(trials, value) / (2**trials)
            for value in range(trials + 1)
            if math.comb(trials, value) / (2**trials) <= observed + 1e-15
        ),
    )


def _paired_bootstrap(
    free: list[int], json_values: list[int], *, iterations: int = 10000, seed: int = 20260814
) -> dict[str, float]:
    rng = random.Random(seed)
    n = len(free)
    effects = []
    for _ in range(iterations):
        sample = [rng.randrange(n) for _ in range(n)]
        effects.append(sum(json_values[i] - free[i] for i in sample) / n)
    effects.sort()
    return {
        "estimate": sum(j - f for f, j in zip(free, json_values)) / n,
        "ci95_low": effects[int(iterations * 0.025)],
        "ci95_high": effects[int(iterations * 0.975)],
        "iterations": iterations,
    }


def build_pilot_report(run_dir: str | Path) -> dict[str, Any]:
    run = Path(run_dir)
    report: dict[str, Any] = {"run_dir": str(run.resolve()), "generation": {}}
    raw_patterns = {
        "accounting_parentheses": re.compile(r"\([\d,.\s]+\)"),
        "word_scale": re.compile(r"\b\d[\d,.]*\s+(?:thousand|million|billion)\b", re.I),
        "percent_symbol": re.compile(r"\d[\d,.]*\s*%"),
    }
    for condition in ("free", "json"):
        all_rows = _jsonl(run / f"raw_{condition}.jsonl")
        latest = _latest(all_rows)
        statuses = Counter(_normalized_status(row) for row in latest.values())
        providers = Counter(
            (row.get("response_meta") or {}).get("provider") or "unknown"
            for row in latest.values()
            if _normalized_status(row) in {"ok", "truncated"}
        )
        raw_triggers = {
            name: sum(bool(pattern.search(row.get("raw", ""))) for row in latest.values())
            for name, pattern in raw_patterns.items()
        }
        report["generation"][condition] = {
            "n": len(latest),
            "status": dict(statuses),
            "providers": dict(providers),
            "raw_triggers": raw_triggers,
            "recorded_cost_usd": sum(
                float((row.get("usage") or {}).get("cost", 0) or 0) for row in all_rows
            ),
            "prompt_tokens": sum(
                int((row.get("usage") or {}).get("prompt_tokens", 0) or 0) for row in all_rows
            ),
            "completion_tokens": sum(
                int((row.get("usage") or {}).get("completion_tokens", 0) or 0) for row in all_rows
            ),
        }

    labels = (
        "free_surface",
        "free_regex",
        "free_typed",
        "free_llm_low2000",
        "free_llm_labeled_low2000",
        "json_schema",
    )
    report["official"] = {}
    report["permission_audits"] = {}
    report["exact_permission_audits"] = {}
    official_rows: dict[str, dict[str, dict[str, Any]]] = {}
    exact_rows: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
    for label in labels:
        summary_path = run / f"official_{label}" / "official_summary.json"
        items_path = run / f"official_{label}" / "official_items.jsonl"
        if summary_path.exists():
            report["official"][label] = json.loads(summary_path.read_text(encoding="utf-8"))
            official_rows[label] = _latest(_jsonl(items_path))
        report["permission_audits"][label] = {}
        for mode in ("fixed_gold", "symmetric"):
            path = run / f"audit_{label}_{mode}" / "summary.json"
            if path.exists():
                report["permission_audits"][label][mode] = json.loads(path.read_text(encoding="utf-8"))
        exact_summary_path = run / f"exact_{label}" / "exact_summary.json"
        exact_items_path = run / f"exact_{label}" / "exact_items.jsonl"
        if exact_summary_path.exists() and exact_items_path.exists():
            report["exact_permission_audits"][label] = json.loads(
                exact_summary_path.read_text(encoding="utf-8")
            )
            exact_rows[label] = {
                (row["uid"], row["policy"]): row for row in _jsonl(exact_items_path)
            }

    report["format_comparisons"] = {}
    report["attributions"] = {}
    report["legacy_attributions"] = {}
    if "json_schema" in official_rows:
        for free_label in labels:
            if not free_label.startswith("free_") or free_label not in official_rows:
                continue
            uids = sorted(set(official_rows[free_label]) & set(official_rows["json_schema"]))
            free = [int(official_rows[free_label][uid]["em"]) for uid in uids]
            json_values = [int(official_rows["json_schema"][uid]["em"]) for uid in uids]
            pairs = Counter(f"{f}->{j}" for f, j in zip(free, json_values))
            discordant = pairs["0->1"] + pairs["1->0"]
            report["format_comparisons"][free_label] = {
                "n": len(uids),
                "transitions": dict(pairs),
                "json_minus_free": _paired_bootstrap(free, json_values),
                "mcnemar_exact_p": _exact_binomial_two_sided(pairs["0->1"], discordant),
            }
            free_audit = report["permission_audits"].get(free_label, {}).get("symmetric")
            json_audit = report["permission_audits"].get("json_schema", {}).get("symmetric")
            if not free_audit or not json_audit:
                continue
            free_p1 = free_audit["scores"]["p1_syntax"]["em"]
            json_p1 = json_audit["scores"]["p1_syntax"]["em"]
            free_official = report["official"][free_label]["em"]
            json_official = report["official"]["json_schema"]["em"]
            total_gap = json_official - free_official
            scorer_gap_component = (json_official - json_p1) - (free_official - free_p1)
            report["legacy_attributions"][free_label] = {
                "free_p1_to_official": free_official - free_p1,
                "json_p1_to_official": json_official - json_p1,
                "official_format_gap": total_gap,
                "difference_in_sca": scorer_gap_component,
                "fraction_of_format_gap": scorer_gap_component / total_gap if total_gap else None,
                "warning": "P1 is the independent audit engine; official is the unmodified TAT-QA scorer.",
            }

            free_exact = report["exact_permission_audits"].get(free_label)
            json_exact = report["exact_permission_audits"].get("json_schema")
            if not free_exact or not json_exact:
                continue
            free_p1 = free_exact["scores"]["exact_p1_syntax"]["em"]
            json_p1 = json_exact["scores"]["exact_p1_syntax"]["em"]
            free_official = free_exact["scores"]["exact_official"]["em"]
            json_official = json_exact["scores"]["exact_official"]["em"]
            total_gap = json_official - free_official
            scorer_gap_component = (json_official - json_p1) - (free_official - free_p1)
            free_lookup = exact_rows[free_label]
            exact_uids = sorted(
                uid for uid, policy in free_lookup if policy == "exact_official"
            )
            p1_official_pairs = Counter(
                f"{int(free_lookup[(uid, 'exact_p1_syntax')]['correct'])}->"
                f"{int(free_lookup[(uid, 'exact_official')]['correct'])}"
                for uid in exact_uids
            )
            report["attributions"][free_label] = {
                "engine": "exact_tatqa_single_path",
                "free_p1_to_official": free_official - free_p1,
                "json_p1_to_official": json_official - json_p1,
                "official_format_gap": total_gap,
                "difference_in_sca": scorer_gap_component,
                "fraction_of_format_gap": scorer_gap_component / total_gap if total_gap else None,
                "free_p1_to_official_transitions": dict(p1_official_pairs),
                "free_official_itemwise_verified": free_exact.get("official_verification", {}).get(
                    "itemwise_exact", False
                ),
                "json_official_itemwise_verified": json_exact.get("official_verification", {}).get(
                    "itemwise_exact", False
                ),
            }

    report["llm_extractors"] = {}
    for path in sorted(run.glob("raw_extractor_*.jsonl")):
        tag = path.stem.removeprefix("raw_extractor_")
        rows = _jsonl(path)
        latest = _latest(rows)
        report["llm_extractors"][tag] = {
            "n": len(latest),
            "status": dict(Counter(_normalized_status(row) for row in latest.values())),
            "providers": dict(
                Counter((row.get("response_meta") or {}).get("provider") or "unknown" for row in latest.values())
            ),
            "recorded_cost_usd": sum(
                float((row.get("usage") or {}).get("cost", 0) or 0) for row in rows
            ),
        }
    return report
