# Phase-0 — evidence-sufficiency precondition check

Cheap precondition gate shared by **MECH-1** (Claim-to-Evidence 充分性审计) and **MECH-2** (金融 Agent
失效模式诊断基准). It does **not** prove the method works — it tests whether the *axis* they both rest on
has a foundation, before spending real money on the full experiment. Per
`knowledge/FAILURE_PREMORTEM.md` + the "Phase-0 = cheap precondition, not a return bar" rule.

## The question
Do finance agents produce answers that are **factually correct but evidence-insufficient**, and can two
people **agree** on what "sufficient evidence" means? If yes → the auditor (MECH-1) and the failure-mode
benchmark (MECH-2) both have ground. If the κ is too low → "sufficiency" isn't operationalizable and both
gaps die here, for ~$0.02 + a day of annotation.

## Pipeline
```
build_tasks.py  →  seed_tasks.jsonl   # ~30 earnings-quarter QA, numeric ground truth from findata
run_phase0.py   →  out/results.jsonl  # agent answers w/ claims+citations; numeric part auto-graded
                   out/annotation.csv  # ONE ROW PER CLAIM — humans fill suff_A / suff_B
stats.py        →  the 4 gates        # 2x2, Cohen's κ, coverage
```
- **Agent**: minimal PIT-aware ReAct loop over 4 findata tools (`get_fundamentals`, `get_earnings_history`,
  `search_transcript`, `get_news`), forced to retrieve ≥1 evidence before answering. Runs on the cheap
  default model (deepseek). Each claim carries the evidence it leans on, so sufficiency is judgeable.
- **findata**: the teacher's published `lumid-findata` client (loaded by path; auth via `LUMID_PAT` /
  `~/.lumid/credentials.toml`). US equities only.

## Run
```bash
python -m phase0.build_tasks            # → seed_tasks.jsonl  (regenerate anytime)
python -m phase0.run_phase0             # → out/  (add --limit N for a quick subset)
#   ... open out/annotation.csv, fill suff_A (and suff_B for ~50 claims) with:
#       sufficient | insufficient | unknown      (focus on kind=qualitative rows)
python -m phase0.stats                  # → the 4 gates + GO/STOP verdict
```

## Gates (GO thresholds)
| gate | what | GO |
|---|---|---|
| **G1** 诊断对象存在 | correct-but-insufficient share among qualitative claims | ≥ 15–20% |
| **G2** 可学习下限 | Cohen's κ between annotator A and B | ≥ 0.6 |
| **G3** 主约束(覆盖) | tasks where the agent retrieved evidence | ≥ 70% |

**Verdict:** G1 & G2 both GO → the evidence-sufficiency axis is real → proceed to the merged MECH-1+2 pilot.
G2 fails → both gaps die cheaply here.

## Cost
- **API: ~$0.02** for the full ~30-task agent run (deepseek; ~2–4 tool calls/task).
- **Human: ~1–2 days** — the real cost is annotating sufficiency (~50 qualitative claims double-labeled for κ).
- The "几千美元" in the briefs is the *full experiment*, not this gate.

## Notes
- `out/` is run output (gitignore-able). `seed_tasks.jsonl` is regenerable from findata.
- To enlarge the set: bump `SYMBOLS` / `PER_SYMBOL` in `build_tasks.py`.
- Numeric grading tolerance: ±2 percentage points (`NUM_TOL_PP` in `run_phase0.py`).
