#!/usr/bin/env python3
"""Build the preregistered cross-model scorer-policy reversal report."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase0.scorer_audit.multimodel_report import build_multimodel_report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model-run",
        action="append",
        required=True,
        metavar="NAME=RUN_DIR",
        help="repeat once per model",
    )
    parser.add_argument("--free-exact-dir", default="exact_free_llm_labeled_low2000")
    parser.add_argument("--json-exact-dir", default="exact_json_schema")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    model_runs = {}
    for spec in args.model_run:
        if "=" not in spec:
            parser.error(f"invalid --model-run {spec!r}; expected NAME=RUN_DIR")
        name, path = spec.split("=", 1)
        if not name or not path or name in model_runs:
            parser.error(f"invalid or duplicate model-run: {spec!r}")
        model_runs[name] = path
    report = build_multimodel_report(
        model_runs,
        free_exact_dir=args.free_exact_dir,
        json_exact_dir=args.json_exact_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["gates"], ensure_ascii=False, indent=2))
    print(f"report written to {args.output}")


if __name__ == "__main__":
    main()
