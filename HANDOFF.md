# AlphaGap — Handoff (last updated 2026-06-04)

> Living handoff (updated 2026-06-04, TEST pipeline proven end-to-end). Where the project is, what shipped, what's pending. Read this first.

## TL;DR
AlphaGap is the **DISCOVER** stage of an AI×Fin auto-research loop:
DISCOVER (daily gaps) → DESIGN (deep brief) → TEST (staged-experiment-runner) →
CONCLUDE (honest verdict) → ACCUMULATE (findings bank) → feeds back to DISCOVER.
As of 2026-06-04 the loop is **closed end-to-end and deployed to luyao4**.

Two heads, kept in sync:
- `~/Desktop/alphagap` — **canonical dev repo** (Chinese prompts), remote = GitHub `ycsama0703/AlphaGap`, deploys to **luyao4** (server cron, 07:00 WIB).
- `~/.xp/apps/alphagap` — **LumidOS app** (English), for **xp.io** publishing. Mirrors Desktop.

## What shipped (this work session, all pushed to GitHub)
DISCOVER diversity (the original "gaps repeat / same few papers" complaint):
- O2 rotate+diversify paper anchors · O3 cross-day dedup (gap ledger + exclude recent
  anchors + recently_proposed→04A) · O4 wider funnel + theoretical-lead fallback (no
  zero-gap days) · conference look-back · Fin top-conf fetcher (`fin_frontier.py`).
- Validated: day1∩day2 anchor overlap = **0** on the frozen local DB.

Source-of-truth reconciliation (Desktop ⇐ app-side wins):
- G1/R1/R2 brief pre-registration · D1 diversify_gaps (Proximity collapse) ·
  load_experiment_findings (ACCUMULATE→DISCOVER). prompts 01-08 were pure englishization.

findings bank restructure (`~/.xp/apps/alphagap-findings`, kind=agent):
- real-tests-only (demo filter) · mechanism-level + cost fields · 5 per-direction views
  (`FINDINGS-<field>.md`) · single source of truth (symlink `~/.xp/findings/bank.jsonl`).

Email decision layer (the human-in-the-loop interface):
- **AI×Fin transfer header**: 🏦 Fin problem → 🤖 AI technique + 背书(anchor_evidence +
  clickable paper) → 🔗 transfer basis (结构对应/桥接/为什么成立/可信度).
- **Feasibility verdict** row (🟢/🟡/🔴 findata-native? compute? days-vs-months) — present, never gates.
- **Soundness ordering**: runnable + leads sorted by `theoretical_support` (most-likely-to-pan-out first), NOT novelty/cost.

Distribution / bootstrap:
- Paper corpus DB (~5.2k papers) shipped as a **6MB committed seed** (`db/seed/*.gz`);
  `db.connect()` auto-decompresses when no live DB (idempotent). Both repos (plan A).
- README Quickstart for a fresh deploy.

## TEST pipeline — PROVEN end-to-end on real findata (2026-06-04)
The "把 pipeline 跑通" goal is done. Two drivers in `~/Desktop/staged-experiment-runner/examples/`
(runs/ + cards gitignored):
- **portfolio_dro.py** — the 2026-06-03 ENG-2 Distributionally-Robust Allocation gap (CRC→VaR;
  anchor `openreview:bt4Ahpemmi` via the conf look-back). Faithful-minimal (historical bootstrap
  not GARCH; CVaR LP not soft-sort; 30 large-caps). **REFUTED at Phase-0** — the CVaR-robust
  portfolio was *riskier* OOS than plain MVO (21.7% vs 17.4% breach of −8%/mo); the naive bootstrap
  underestimates the OOS tail (the gap's own flagged risk). LP feasible (infeasible_rate=0 — a real
  result, not a fallback bug). Needs GARCH → that's the cheap Phase-0 kill working as designed.
- **low_vol_anomaly.py** — low-volatility anomaly (inverse-vol vs equal-weight). **Walked the FULL
  rails**: Phase-0 precondition (vol rank-persistence 0.93 ✓) → Phase-1 EW baseline → Phase-2 iv beats
  ew on val (+0.02) → CONCLUDE on the sealed holdout once: iv ann.Sharpe 1.52 vs ew 1.73 → edge −0.22
  (bar +0.20), **DSR 0.82 < 0.95 → REFUTED**. Textbook stable-vs-lucky: the tiny val edge was noise;
  the holdout (consumed once) caught the in-sample mirage.
- Findings bank now has **4 real findings** (confirmed 1 / partial 1 / refuted 2; factor_investing +
  portfolio_optimization). Both runs honest, NO p-hacking (params set on first principles before
  opening the holdout, locked). DEMONSTRATED BOTH rails behaviours: cheap Phase-0 kill (DRO) AND a
  full walk to holdout+DSR (low-vol).
- **Lesson (see feedback_phase0_precondition_not_return):** Phase-0 must be a CHEAP precondition /
  signal-separability check (e.g. "is vol rank-persistent?"), NOT a return/Sharpe bar (that's a
  mini-holdout and spuriously kills runs). Return comparisons belong in Phase-2 (val) and the holdout
  verdict. Write this into the deep-brief prompt §10 guidance.
- findata caveat: the harness accessor defaults to `limit=750` (last ~3y); pass `limit=3000` to get
  full 2015-2024 daily history.

## TEST experiment scaffold — shape-templates (2026-06-04)
Goal: stop hand-writing ~200 lines of rails per experiment. Built a 3-layer design in
`~/Desktop/staged-experiment-runner/harness/templates/` (NB: that repo is NOT git locally;
published to xp.io separately):
- **Layer 1 — harness (`Experiment`)**: universal rigor rails (split discipline, sealed
  holdout consumed once, gates on train/val, DSR, conclusion card). Every experiment uses it.
- **Layer 2 — shape-templates** (a small family, keyed by experiment SHAPE not by gap):
  - `portfolio.run_monthly_portfolio_experiment` — monthly-rebalance findata portfolio gaps
    (returns → weights → Sharpe/return/VaR-violation). Author supplies: universe, splits,
    trailing_window, a Phase-0 PRECONDITION fn, baseline weight fn, intervention weight fn,
    metric + holdout_threshold + n_trials.
  - `predictive.run_predictive_signal_experiment` — does-X-predict-Y gaps (data-AGNOSTIC;
    rank-IC / AUROC). Author supplies: a Phase-0 precondition, an `evaluate(exp, split)->(metric,detail)`,
    metric + holdout_threshold.
- **Layer 3 — `toolbox`**: shared metrics (ann_sharpe/ann_return/var_violation/rank_ic/auroc/
  cohens_d), weight baselines (equal_weight/inverse_vol/mvo), preconditions (vol_rank_persistence),
  findata monthly-panel loader (`load_monthly_panel`, passes limit=3000).
- **Escape hatch**: a structurally-novel gap → write bespoke directly on `Experiment` (Layer 1),
  same as the two original example scripts. Templates are a fast path, not the only path. The
  agent ROUTES per gap (fits a shape → ~25-line config; else → bespoke); structure/data diversity
  is irreducible and is NOT templated.
- A fitting gap is now a **~25-line config** (examples/low_vol_v2_templated.py, momentum_ic_predictive.py).
- Validated: portfolio template reproduced the bespoke low-vol run EXACTLY (refuted, edge -0.2154,
  DSR 0.82); predictive template walked full rails on momentum→return IC → confirmed (holdout IC +0.098).
- Template-validation runs are NOT ingested to the bank (kept clean: bank stays at 4 real findings).
- Pending: the agent-side "read brief → pick shape → fill config" routing is still manual.

## Deployment state
- ✅ GitHub: pushed (`cae986d`, 15 commits this session).
- ✅ luyao4: `git pull` + dry-run validated in the cron venv — $0.0890, **2 runnable
  experiments**, new transfer header renders correctly. Tomorrow's 07:00 cron sends the
  real email. luyao4 keeps its own DB (seed bootstrap doesn't fire — it has a live DB).

## Storage map (banks vs knowledge)
| Asset | Where | Travels how |
|---|---|---|
| Paper corpus DB | `db/alphagap.sqlite` (gitignored, live) + `db/seed/*.gz` (committed) | seed in both repos, auto-bootstrap |
| Fin frontier (5 dirs) | `knowledge/fin_fields/` (5 notes + transfer_cells + sources) | git-tracked, travels with code |
| findings bank | `~/.xp/apps/alphagap-findings/bank.jsonl` (kind=agent repo) | separate agent repo |
| gap_log | `~/Desktop/alphagap/gap_log.jsonl` (gitignored) | rebuilds from zero per machine |

## Pending / next (prioritized)
1. **findings bank not on luyao4** → ACCUMULATE→DISCOVER degrades to `[]` there (no crash).
   To activate on the server: scp `~/.xp/findings/bank.jsonl` over + set `ALPHAGAP_FINDINGS_BANK`.
2. **app → xp.io publish** (deferred): when publishing the LumidOS app for others; do app
   publish + (decided) bundle the seed in-app (plan A, already done) — no separate dataset.
3. **app README** Quickstart mirror (English) — minor.
4. ✅ DONE — ran findata-native gaps through the full TEST rails (see "TEST pipeline" section above).
5. ✅ DONE — Phase-0=precondition lesson written into deep-brief prompt §10 (both repos): Phase-0 must
   be a precondition / separability check (correlation / AUROC / Cohen's d), not a return/Sharpe bar,
   with good/bad examples. (feedback_phase0_precondition_not_return)
6. (optional) GARCH scenario generator for the DRO gap → give it a fair full-rails run (currently a
   Phase-0 kill only because the minimal bootstrap underestimates the OOS tail).

## Key decisions (do not relitigate)
- **Cost/feasibility = decision-support, never auto-veto** a gap. Surface, don't drop.
- **Order by theoretical soundness**, not novelty or cheapness — "能跑出来最重要".
- **TEST targets must be cheap + findata-native** (days, not months). ENG-1 factor-world-model
  rejected as too heavy (2-3mo + bespoke backtest corpus). See `feedback_test_stage_cheap_gaps`.
- **Single findings bank** partitioned by field_id + 5 views — NOT 5 physical banks.
- **DB distribution = plan A both lines** (embed 6MB seed); owner refreshes via `make seed`.
- **luyao4 = plain GitHub + cron server**, NOT a lumid app. Deploy = push + `git pull`.

## Gotchas
- Local dev DB is a **frozen snapshot** (max eligible AI paper ~2026-05-27); consecutive
  same-DB runs exhaust the fresh pool → backfill re-admits some anchors (expected, not a bug).
- luyao4 cron uses `.venv/bin/python` (has deps); base conda lacks `openai` — always use the venv.
- MCP `app_*` tools return a wrapper error (`Input should be a valid dictionary, got str`)
  even on success — verify via `.app-ci/last-report.json` or the xp.io UI, not the tool error.
- `| tail` buffers all output until process exit — a long dry-run looks "stuck" but isn't.

## Run cheatsheet
```bash
make install && cp .env.example .env   # one-time (fill DEEPSEEK_API_KEY + RESEND/EMAIL)
make bootstrap                          # decompress corpus seed (or daily auto-does it)
make dry-run                            # full pipeline, no email/commit (~8-15min, ~$0.08)
make seed                               # refresh the committed corpus snapshot
```
