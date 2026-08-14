#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase0.scorer_audit.judge_agreement import build_judge_agreement


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two blinded TAT-QA LLM judges")
    parser.add_argument("--reviewer-dir", required=True)
    parser.add_argument("--judge-a-dir", required=True)
    parser.add_argument("--judge-b-dir", required=True)
    parser.add_argument("--out-dir", required=True)
    args = parser.parse_args()
    report = build_judge_agreement(
        args.reviewer_dir,
        args.judge_a_dir,
        args.judge_b_dir,
        args.out_dir,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
