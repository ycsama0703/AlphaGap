from __future__ import annotations

import argparse
import json
from pathlib import Path

from .adapters import tatqa
from .blind_audit import build_blind_audit_package
from .engine import audit, decision_changes, summarize_audit
from .exact_tatqa import (
    EXACT_POLICY_ORDER,
    audit_exact,
    compare_official_rows,
    exact_decision_changes,
    summarize_exact,
)
from .pilot_report import build_pilot_report
from .policies import POLICY_ORDER


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _selection_uids(path: str | None) -> set[str] | None:
    if not path:
        return None
    selection = json.loads(Path(path).read_text(encoding="utf-8"))
    return {
        item["uid"] if isinstance(item, dict) else str(item)
        for item in selection.get("items", selection)
    }


def cmd_extract_tatqa(args: argparse.Namespace) -> None:
    predictions, records = tatqa.predictions_from_raw(args.raw, args.extractor)
    tatqa.write_official_predictions(predictions, args.predictions)
    if args.records:
        _write_jsonl(Path(args.records), records)
    failures = sum(record["status"] != "ok" for record in records)
    print(f"extracted={len(records)} failures={failures} predictions={args.predictions}")


def cmd_audit_tatqa(args: argparse.Namespace) -> None:
    gold = tatqa.load_gold(args.gold)
    predictions = tatqa.load_predictions(args.predictions)
    selected_uids = _selection_uids(args.selection)
    if selected_uids is not None:
        gold = [item for item in gold if item.uid in selected_uids]
    policies = tuple(args.policies)
    rows = audit(gold, predictions, policies, mode=args.mode, gold_policy=args.gold_policy)
    summary = summarize_audit(rows, policies)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "item_transitions.jsonl", rows)
    _write_jsonl(out / "decision_changes.jsonl", decision_changes(rows, policies))
    (out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for policy, score in summary["scores"].items():
        print(f"{policy:<22} EM={score['em'] * 100:6.2f} n={score['n']}")
    print(f"wrote {out}")


def cmd_reproduce_tatqa(args: argparse.Namespace) -> None:
    summary, rows = tatqa.run_official_evaluation(
        args.gold,
        args.predictions,
        args.tatqa_repo,
        selected_uids=_selection_uids(args.selection),
    )
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "official_items.jsonl", rows)
    (out / "official_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"official EM={summary['em'] * 100:.2f} F1={summary['f1'] * 100:.2f} "
        f"Scale={summary['scale'] * 100:.2f} n={summary['n']}"
    )


def cmd_audit_tatqa_exact(args: argparse.Namespace) -> None:
    gold = tatqa.load_gold(args.gold)
    predictions = tatqa.load_predictions(args.predictions)
    selected_uids = _selection_uids(args.selection)
    if selected_uids is not None:
        gold = [item for item in gold if item.uid in selected_uids]
    policies = tuple(args.policies)
    rows = audit_exact(gold, predictions, policies)
    summary = summarize_exact(rows, policies)
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl(out / "exact_items.jsonl", rows)
    _write_jsonl(out / "exact_decision_changes.jsonl", exact_decision_changes(rows, policies))

    verification_failed = False
    if args.tatqa_repo:
        official_summary, official_rows = tatqa.run_official_evaluation(
            args.gold,
            args.predictions,
            args.tatqa_repo,
            selected_uids=selected_uids,
        )
        verification = compare_official_rows(rows, official_rows)
        verification_failed = not verification["itemwise_exact"]
        verification["official_summary"] = official_summary
        summary["official_verification"] = verification
        _write_jsonl(out / "official_items.jsonl", official_rows)
        if not verification["itemwise_exact"]:
            print(f"WARNING exact_official mismatches={verification['n_mismatches']}")

    (out / "exact_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for policy, score in summary["scores"].items():
        print(
            f"{policy:<24} EM={score['em'] * 100:6.2f} "
            f"F1={score['f1'] * 100:6.2f} n={score['n']}"
        )
    if "official_verification" in summary:
        verification = summary["official_verification"]
        print(
            f"official itemwise exact={verification['itemwise_exact']} "
            f"mismatches={verification['n_mismatches']}"
        )
    print(f"wrote {out}")
    if verification_failed:
        raise SystemExit("exact_official does not match the unmodified official scorer itemwise")


def cmd_report_pilot(args: argparse.Namespace) -> None:
    report = build_pilot_report(args.run_dir)
    output = Path(args.output) if args.output else Path(args.run_dir) / "pilot_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    comparisons = report.get("format_comparisons", {})
    attributions = report.get("attributions", {})
    for label, comparison in comparisons.items():
        effect = comparison["json_minus_free"]
        print(
            f"JSON-{label}={effect['estimate'] * 100:+.2f}pp "
            f"95% CI [{effect['ci95_low'] * 100:+.2f}, {effect['ci95_high'] * 100:+.2f}] "
            f"McNemar p={comparison['mcnemar_exact_p']:.4g}"
        )
    for label, attribution in attributions.items():
        print(
            f"SCA {label}={attribution['free_p1_to_official'] * 100:+.2f}pp "
            f"json={attribution['json_p1_to_official'] * 100:+.2f}pp "
            f"gap fraction={attribution['fraction_of_format_gap']:.1%}"
        )
    print(f"wrote {output}")


def cmd_make_blind_audit(args: argparse.Namespace) -> None:
    summary = build_blind_audit_package(
        args.run_dir,
        args.gold,
        args.out_dir,
        seed=args.seed,
        controls_per_cell=args.controls_per_cell,
    )
    counts = summary["counts"]
    print(
        f"blind records={counts['pass1_pass2_records']} "
        f"changed={counts['direct_changed']} controls={counts['stable_controls']} "
        f"mechanism_edges={counts['mechanism_edges']}"
    )
    print(f"blind check violations={summary['blind_check']['violations']}")
    print(f"wrote {args.out_dir}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Permission-controlled scorer audit")
    sub = parser.add_subparsers(dest="command", required=True)

    extract = sub.add_parser("extract-tatqa", help="extract frozen TAT-QA generations")
    extract.add_argument("--raw", required=True)
    extract.add_argument(
        "--extractor",
        required=True,
        choices=("schema", "labeled", "free_regex", "free_typed", "free_surface"),
    )
    extract.add_argument("--predictions", required=True)
    extract.add_argument("--records")
    extract.set_defaults(func=cmd_extract_tatqa)

    score = sub.add_parser("audit-tatqa", help="run a TAT-QA permission ladder")
    score.add_argument("--gold", required=True)
    score.add_argument("--predictions", required=True)
    score.add_argument("--out-dir", required=True)
    score.add_argument("--selection", help="run selection.json; limits the audit denominator")
    score.add_argument("--mode", choices=("fixed_gold", "symmetric"), default="fixed_gold")
    score.add_argument("--gold-policy", default="p4_round2")
    score.add_argument("--policies", nargs="+", default=list(POLICY_ORDER))
    score.set_defaults(func=cmd_audit_tatqa)

    exact = sub.add_parser(
        "audit-tatqa-exact",
        help="run one exact TAT-QA metric path with permission switches",
    )
    exact.add_argument("--gold", required=True)
    exact.add_argument("--predictions", required=True)
    exact.add_argument("--out-dir", required=True)
    exact.add_argument("--selection", help="run selection.json; limits the audit denominator")
    exact.add_argument("--policies", nargs="+", default=list(EXACT_POLICY_ORDER))
    exact.add_argument(
        "--tatqa-repo",
        help="also run the unmodified official scorer and require item-level comparison",
    )
    exact.set_defaults(func=cmd_audit_tatqa_exact)

    reproduce = sub.add_parser("reproduce-tatqa", help="run the unmodified official TAT-QA scorer")
    reproduce.add_argument("--gold", required=True)
    reproduce.add_argument("--predictions", required=True)
    reproduce.add_argument("--tatqa-repo", required=True)
    reproduce.add_argument("--out-dir", required=True)
    reproduce.add_argument("--selection", help="run selection.json; limits the official denominator")
    reproduce.set_defaults(func=cmd_reproduce_tatqa)

    report = sub.add_parser("report-tatqa-pilot", help="summarize a completed TAT-QA pilot run")
    report.add_argument("--run-dir", required=True)
    report.add_argument("--output")
    report.set_defaults(func=cmd_report_pilot)

    blind = sub.add_parser(
        "make-tatqa-blind-audit",
        help="build a de-identified randomized two-pass audit package from exact transitions",
    )
    blind.add_argument("--run-dir", required=True)
    blind.add_argument("--gold", required=True)
    blind.add_argument("--out-dir", required=True)
    blind.add_argument("--seed", type=int, default=20260814)
    blind.add_argument("--controls-per-cell", type=int, default=20)
    blind.set_defaults(func=cmd_make_blind_audit)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
