"""Ingest a blind judge's labels (a fresh GPT or fresh Claude) into the annotation sheet's suff column.

Flow:
  1. paste phase0/out/judge_sheet.md into a FRESH model chat, get 60 lines like `12: insufficient`
  2. save that reply to a text file, e.g. phase0/out/gpt_labels.txt
  3. python -m phase0.ingest_labels phase0/out/gpt_labels.txt --col suff_B   # suff_A for fresh Claude
  4. python -m phase0.stats

Accepts lines of the form `<idx>: <label>` (label = sufficient|insufficient|unknown); idx = the
0-based number in judge_sheet.md (i.e. qualitative-claim order). Extra prose is ignored.
"""
from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

_OUT = Path(__file__).resolve().parent / "out"
_LABELS = {"sufficient", "insufficient", "unknown"}
_LINE = re.compile(r"^\s*(\d+)\s*[:\.\)]\s*(sufficient|insufficient|unknown)", re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("labels_file", help="text file with `idx: label` lines (a model's reply)")
    ap.add_argument("--col", default="suff_B", choices=["suff_A", "suff_B", "suff_C"])
    args = ap.parse_args()

    parsed = {}
    for line in Path(args.labels_file).read_text(encoding="utf-8").splitlines():
        m = _LINE.match(line)
        if m:
            parsed[int(m.group(1))] = m.group(2).lower()
    if not parsed:
        print("no `idx: label` lines found — check the file format"); return

    csv_path = _OUT / "annotation.csv"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    qi, n = 0, 0
    for r in rows:
        if r["kind"] == "qualitative":
            if qi in parsed:
                r[args.col] = parsed[qi]; n += 1
            qi += 1
    cols = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
    print(f"wrote {n} labels into {args.col} (of {qi} qualitative claims). Now: python -m phase0.stats")


if __name__ == "__main__":
    main()
