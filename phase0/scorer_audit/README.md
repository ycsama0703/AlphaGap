# scorer-audit

`scorer-audit` separates benchmark evaluation into three replayable stages:

```text
generation (paid once) → extraction (offline) → scoring policy (offline)
```

The first adapter is TAT-QA. The generic engine does not import or monkeypatch
the official scorer. Exact official reproduction is a separate command so an
approximation cannot silently be reported as an official score.

## 1. Validate Phase 0.5 without an API call

```bash
pytest -q tests/test_scorer_audit.py
python3 phase0/tatqa_run.py \
  --n 200 \
  --answer-types arithmetic count \
  --dry-run
```

The dry run does not load the API key, create a run directory, or call a model.

## 2. Generate a paid pilot

```bash
python3 phase0/tatqa_run.py \
  --n 200 \
  --answer-types arithmetic count \
  --run-id tatqa_pilot_numeric_v1
```

The JSON condition uses a strict response schema. The free condition has no
response format. Both conditions save raw output before any answer extraction.
Successful requests resume by `(run_fingerprint, uid)`; failed requests remain
eligible for retry.

## 3. Replay extraction

The generation script automatically writes the standard extractor variants.
They can also be rerun explicitly:

```bash
python3 -m phase0.scorer_audit.cli extract-tatqa \
  --raw phase0/tatqa_out/tatqa_pilot_numeric_v1/raw_free.jsonl \
  --extractor free_surface \
  --predictions /tmp/preds_free_surface.json \
  --records /tmp/extraction_free_surface.jsonl
```

Available extractors:

- `schema`: read strict JSON fields;
- `free_regex`: move word scale into the typed scale field while preserving
  accounting parentheses and percent signs;
- `free_typed`: `free_regex` plus an explicit count-word-to-integer permission;
- `free_surface`: preserve the final-answer surface and leave scale untyped.

Semantic LLM extraction is a separate paid replay over the frozen free output:

```bash
python3 phase0/tatqa_extract_llm.py \
  --run-dir phase0/tatqa_out/tatqa_pilot_numeric_v1 \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --provider DeepInfra \
  --max-tokens 2000 \
  --reasoning-effort low \
  --output-mode labeled \
  --tag llm_labeled_low2000
```

## 4. Run the exact permission scorer (primary attribution)

```bash
python3 -m phase0.scorer_audit.cli audit-tatqa-exact \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --predictions phase0/tatqa_out/tatqa_pilot_numeric_v1/preds_free_llm_labeled_low2000.json \
  --selection phase0/tatqa_out/tatqa_pilot_numeric_v1/selection.json \
  --tatqa-repo /private/tmp/tat-qa-inspect \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/exact_free_llm_labeled_low2000
```

The exact policies share one answer preparation, normalization, and matching
path. They cumulatively enable scale handling, accounting/percent semantics,
rounding, and the official percent alternate. With `--tatqa-repo`, the command
runs the unmodified scorer too and exits nonzero unless `exact_official` matches
official EM and F1 for every UID.

The full 1,668-item TagOp dev verification has zero item-level mismatches and
reproduces EM 45.92 / F1 58.88.

## 5. Replay generic diagnostic policies (legacy)

```bash
python3 -m phase0.scorer_audit.cli audit-tatqa \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --predictions phase0/tatqa_out/tatqa_pilot_numeric_v1/preds_free_free_regex.json \
  --mode fixed_gold \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/audit_free_regex_fixed
```

Modes:

- `fixed_gold`: freeze gold under `p4_round2` and vary prediction permissions;
- `symmetric`: apply the same policy to gold and prediction, measuring the
  scoring policy as a whole.

Policies are cumulative:

- `p0_raw`: structured raw equality; no number parsing;
- `p1_syntax`: lowercase, whitespace/articles, and non-semantic punctuation;
- `p2_scale`: word and structured scale interpretation;
- `p3_numeric`: accounting parentheses and percent-symbol interpretation;
- `p4_round2`: two-decimal rounding before structured scale multiplication.

`p4_round2` is intentionally not called `official`: it is an auditable policy
implementation, not a byte-for-byte reimplementation of TAT-QA.

Outputs:

- `summary.json`: EM, effective operations, and adjacent-policy transition counts;
- `item_transitions.jsonl`: every item under every policy with provenance;
- `decision_changes.jsonl`: only `0→1` and `1→0` cases for manual audit.

## 6. Reproduce the unmodified official scorer

```bash
python3 -m phase0.scorer_audit.cli reproduce-tatqa \
  --gold /tmp/tat-qa/dataset_raw/tatqa_dataset_dev.json \
  --predictions /tmp/tat-qa/sample_prediction.json \
  --tatqa-repo /tmp/tat-qa \
  --out-dir phase0/tatqa_out/tagop_official_reproduction
```

Expected TagOp result: EM 45.92, F1 58.88, Scale 90.95.

## 7. Build the randomized blind-audit package

```bash
python3 -m phase0.scorer_audit.cli make-tatqa-blind-audit \
  --run-dir phase0/tatqa_out/tatqa_pilot_numeric_v1 \
  --gold phase0/tatqa_out/tatqa_dataset_dev.json \
  --out-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1 \
  --seed 20260814 \
  --controls-per-cell 20
```

The `reviewer/` directory contains a gold-hidden intent pass, a later gold-visible
adjudication pass, randomized Candidate A/B order, blank CSV label templates, and
an adjacent-edge mechanism packet. The sibling `private/` directory contains the
UID/condition/policy key and must remain hidden until reviewer labels are frozen.
The generator rejects UUIDs, private labels, and private decision fields found in
the public reviewer package.

## 8. Run two blinded LLM judges

```bash
python3 phase0/tatqa_blind_judge.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --output-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gpt56_terra_pro_v1 \
  --model openai/gpt-5.6-terra-pro --provider OpenAI \
  --reasoning-effort medium --max-tokens 2000

python3 phase0/tatqa_blind_judge.py \
  --reviewer-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/reviewer \
  --output-dir phase0/tatqa_out/tatqa_pilot_numeric_v1/blind_audit_v1/judges/gemini37_flash_v1 \
  --model google/gemini-3.7-flash --provider Google \
  --reasoning-effort medium --max-tokens 2000
```

Each request is independent, strict-schema, provider-pinned, fingerprinted, and
resumable. The runner refuses a reviewer path inside `private/`. Use
`tatqa_judge_agreement.py` before `tatqa_judge_unblind.py`; the latter is the only
analysis step that reads the private condition/policy map.
