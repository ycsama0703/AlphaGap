# AlphaGap — Handoff (last updated 2026-06-05)

> Living handoff (updated 2026-06-05). Where the project is, what shipped, what's pending. Read this first.

## 2026-06-05 — TEST reframed: per-gap collaboration, NOT a template pipeline (READ THIS)

**Decision (do not relitigate):** TEST is **not** an automated routing/template pipeline. Forcing real gaps
through shape-templates (portfolio/predictive) or an auto-router **deforms the gap** — every real gap's
experiment shape is irreducible. So: **DISCOVER→DESIGN→email stays automated** (it finds & frames gaps);
**TEST is per-gap, in conversation** — pick a gap, design the experiment IT actually needs, hand-write it on
the rigor rails, run, honest verdict. The `Experiment` rails (sealed holdout, train/val gates, DSR, honest
conclusion card) STAY — those are universal discipline, not a template. **Retired** (kept only as copyable
snippets, not auto-invoked): `test_author` auto-router, portfolio/predictive shape-templates, batch routing.

**findata catalog + discipline:** `knowledge/FINDATA_CATALOG.md` (copies in staged-experiment-runner/ + app)
is the authoritative data reference — **judge every gap's data needs against it, never from memory** (a
from-memory "findata = price only" judgment refuted a gap on a bad proxy). findata = ~67 endpoints, 7,851 US
equities: price + fundamentals(statements/ratios) + macro + analyst + ownership + text(filings/transcripts/news).
FF/characteristic factors are CONSTRUCTIBLE. Genuinely NOT native: text-with-labels/agent-trajectories,
generate-a-corpus, non-US/options/tick. Prompt 05 (both repos) now references it for `findata_native`.
**Data gotchas found the hard way (all in the catalog):** `get_key_metrics` pe/roe are null + shallow → build
value/quality from `get_fundamentals_history` (income eps + balance equity/assets, deep to ~2011);
`get_market_cap_history` only ~2022+ (don't divide by it historically — use EPS/price, log(total_assets));
the harness ohlc accessor truncates to ~750 bars unless `limit=` passed; `load_monthly_panel` is a BALANCED
panel (collapses with heterogeneous history) — use an unbalanced panel for cross-sectional work.

**significance (4th scoring dim):** added to scoring.py + prompt 07 + email/inbox (both repos). 1-10, "if
confirmed, would it MATTER" — orthogonal to novelty/actionability/theoretical_support; display-only, never
gates (like cost); secondary sort key after theoretical_support. Penalises circular criteria / crowded-arena
tweaks / soft-metric payoffs / decayed signals. Motivation: pipeline was surfacing sound-but-minor gaps.

**Per-gap experiments run this session (all in findings bank, all refuted/null — honest):**
- **b017** (Complexity Shortcut Audit, REAL data): full model over-relies on momentum/vol (69% attribution) but
  fundamentals-only predicts BETTER in-sample (IC 0.085 > 0.057) → "edge is a momentum/vol shortcut" REFUTED;
  AND nothing generalizes OOS (holdout IC −0.04, both full & fund negative — 2021-22 regime break). Took 3
  data-plumbing iterations; the coverage guard blocked a false "confirmed" off empty fundamentals.
- **b027** (Risk-Premia Decomposition, REAL data): Phase-0 reversal precondition too weak (0.006 mega-cap →
  0.019 small/mid, vs the gap's 0.08 bar) → no separable mispricing for the MoE → no-go before building it.
- **b012** (Multi-Period Rebalancing, GBM testbed): reward-centering did NOT cut turnover (ratio 1.04 vs ≤0.80)
  → refuted; low significance anyway.
- **evidence-sufficiency** (Evidence-Sufficient Agentic Retrieval, REAL DeepSeek agent — highest-significance gap):
  initial run looked **CONFIRMED (+0.64)** but **validation killed it** — a model example of why we validate.
  E1 (LLM-computed answers, not deterministic) + E2 (fair baseline that can say "unknown") → de-inflated lift
  **+0.04, 95% CI [−0.08,+0.16] (spans 0)**. E5 (complex multi-evidence queries) → decompose vs ad-hoc evidence-
  completeness gap **+0.00** (both 1.00); answer accuracy **13%** even with complete evidence. Net: no measurable
  benefit on the testable proxy; the binding constraint is **LLM financial reasoning (~13%)**, which decomposition
  doesn't touch. Bank entry corrected to `partial/superseded`. Harnesses: `evidence_sufficiency{,_ablation,_e5}.py`.
- **Session scorecard (9 findings banked):** **all 4 tested gaps refuted/null** under fair tests (b012 null,
  b017/b027 refuted, evidence-sufficiency deflated). Sobering but honest — nothing in the pool cleanly survived.
  **Lesson:** cheap-to-test gaps tend to be low-significance; the high-significance ones need a built harness.
  The auto-gradable-findata trick (compute gold from structured data, grade evidence from the tool-call log)
  makes agent gaps testable without humans. **Over-claiming "confirmed" off one inflated run is the failure mode
  to avoid** — call preliminary results preliminary; only fair-tested + powered results are "confirmed."

## 2026-06-05 — Deep research-gap layer (treat shallow gaps at the ROOT: mine papers deeper)

**Root cause of shallow gaps:** L1/L2 extraction read only the ABSTRACT → one mechanism/paper → gaps
can't be deeper than a sentence. Fixed by reading FULL TEXT and mining the experiment structure.

**Built (precision-first / low-volume — see `feedback_precision_over_breadth`):**
- **L3 paper mining** `pipeline/papermine/` (PDF scripts lifted from MIT github.com/alaliqing/claude-paper
  + `pdf-parse` npm; headless, cron-safe). `mine.py:mine_paper(arxiv_id)` → full text → DeepSeek mines
  {main_claim, transferable_sub_mechanisms[] (PLURAL), ablations_why[], boundary_conditions, failure_modes,
  key_quant_results}. ~50k chars vs 1377 abstract; FIPO → 1 mechanism became 3 + ablation "why".
  NOTE: corpus arxiv IDs (2026, HF Daily) DO resolve on real arxiv → mining works on our actual corpus.
- **Research-gap generation** `pipeline/research_gap.py` — consumes mined fuel (a LIST enables cross-paper
  composition) → research gaps whose PRODUCT is runnable experiment slices (hypothesis + findata data +
  go/no-go + cost), gated by the empirical pre-mortem. Generation modes: composition / problem_first /
  reframe / frontier > 1:1 transfer. **Depth/novelty are decided by EXPERIMENTS, not a reviewer score** —
  so NO revise-to-impress-a-critic loop (over-fits paper-narrative). `research_gap_critic.py` is OPTIONAL
  display only (fabrication check: predicted numbers as fact / unverifiable benchmarks vs corpus), NEVER gates.
- **Wired into daily** `pipeline/analyze/research_gap_stage.py` = Step 2.5 in `main.py`: mine top-N anchor
  papers (`RESEARCH_GAP_PAPERS`, default 2) → research gaps → payload `research_gaps`. Best-effort (mining
  failures skipped, never breaks the run). Email + inbox render a 🔬 Research Gaps section (slice-centric).
- **Lazy corpus deepening** (`paper_mines` table + `mine.py` cache): every on-demand L3 mine persists its
  deep record; re-requests hit cache (0.3s vs 73s, no PDF/LLM). The corpus deepens WHERE IT'S USED — no
  $200 full 5k re-mine (deliberately rejected: contradicts precision-first; cheap L1/L2 stays the broad
  funnel, L3 is deep-on-demand). `connect()` now sets PRAGMA busy_timeout=8000 for concurrent-access safety.
- **End-to-end validated**: mined arxiv 2604.22748 → generated gap#1 slice → recalibrated to a real cost-
  survival test → ran on findata with sealed holdout → Phase-0 learnability-floor refuted (30 mega-caps too
  clean, same universe artifact as b027). Chain is honest at every hop.
- **Honest limit:** mechanism-transfer gaps plateau around "needs_work" by a strict reviewer (single-paper
  1:1 → low novelty; nearest prior IS the mined paper). That's fine — depth is TEST's call, not the score's.

## 2026-06-05 — Redirect to PUBLISHABLE AI-agent×finance gaps (the goal is papers, not boundary maps)

**Goal clarified by the user:** find "small breakthroughs / new angles" that can become AI+finance PAPERS —
**innovation + POSITIVE result** (negative/debunk results don't publish in this field). NOT boundary-mapping,
NOT return-prediction. Where AI genuinely wins in finance = unstructured/language tasks (NLP) + agents, where
the bottleneck is comprehension not predicting efficient prices. Liquid large-cap return prediction = graveyard
(all our TEST negatives came from there). And our mined mechanisms are LLM/agent/RL — they fit text/agent, not
cross-sectional return regression. So: **battlefields = NLP + Agent (main), event + crypto (supporting).**

**AI-protagonist framing (key):** a publishable AI+fin paper here has an AI skeleton (new agent mechanism /
reliability-audit / benchmark / multi-agent), with finance as the demanding scenario — target AI venues
(NeurIPS/ICML/ACL). The earlier "financial NLP" generator drifted to finance-driven return-prediction with AI as
a feature extractor (wrong); the agent generator fixes the framing.

**Built + wired into the pipeline:**
- **Battlefield rebalancing** (`filter.py`): priority_score now boosts on-battlefield papers (NLP/agent/retrieval/
  time-series/interpretability/finance, SPECIFIC patterns — generic "LLM/reasoning" excluded) and sinks pure
  vision/robotics/bio/multimodal noise (was 32% of corpus, crowding out battlefield papers via HF upvotes).
  Re-scored all 5,297 existing papers → anchors/L2 now favor battlefield papers (FinToolBench/Nexus/etc. on top).
- **`agent_opportunity.py`** — AI-agent×finance opportunity generator: AI-protagonist, mechanism task-driven
  (no forced-fit; marks `(mechanism_gap)` when nothing fits), publishable-positive lens (contribution = AI win
  not Sharpe). `fin_opportunity.py` (NLP map) kept as the non-agent prototype.
- **Wired as Step 2.5** (`research_gap_stage.py` now calls `generate_agent_opportunity_map`): daily run mines top-N
  agent anchors (cache-aware) → AI-agent×finance opportunities → payload `research_gaps` → email 🤖 section +
  inbox. Replaces the old return-prone generator. Renderers updated to the agent-opportunity schema, explicitly
  labeled UNVALIDATED (novelty/feasibility unchecked, untested).
- **Status of opportunities:** front-of-funnel candidate angles — NOT validated/tested. Next gates (not yet built):
  novelty verification (is the cited prior real / has it been done) → research arc + runnable slice → TEST → result.
- **Honest open issue:** mechanism diversity is bounded by the anchor pool (2-4 papers/run → mechanisms cluster on
  those, e.g. RecursiveMAS internal-link reused). Mining more/diverse agent anchors widens it.

## 2026-06-05 — Failure-reflection loop (close DISCOVER↔TEST: learn WHY gaps die)

**Systemic finding:** the gap-scoring chain (04/05/07) optimizes *reasoning soundness* (structural homology,
failure-mode match, theoretical anchors), but survival depends on *empirical preconditions* the chain never
checks. **All 4 tested gaps failed on an UNSTATED empirical precondition, not on their transfer logic.**

**Built (3 artifacts + a loop):**
- **Reflection bank** `~/.xp/findings/reflections.jsonl` (in alphagap-findings repo; symlinked) — one
  MECHANISM-LEVEL post-mortem per stopped gap. Each embeds the brief's 🏦/🤖/🔗 thesis + names the exact
  computational/statistical condition that broke + the violated quantity (brand-free) + a distilled rule.
- **Pre-mortem checklist** `knowledge/FAILURE_PREMORTEM.md` (Desktop + app) — 4 distilled, model-agnostic
  empirical-precondition checks: **① Learnability floor** (signal a mechanism learns from needs standalone
  strength > floor, rank-IC ~0.05) **② Diagnosed-thing-exists** (a detector needs its target to exist OOS;
  attribution-share ≠ edge-source) **③ Causal-lever ≠ structural-homology** (the changed quantity must move the
  target metric) **④ Binding-constraint** (fix the dominant error source, not a sub-step).
- **Wired into prompts 05 (`empirical_preconditions` output) + 07 (precondition-risk → caps significance)**,
  both Desktop + app. Closes the loop: TEST failure → reflection → distilled rule → DISCOVER pre-checks for $0.
- **`harness/reflect.py`** = on-demand drafting helper (NOT auto-fired).

**Process (standing behavior, in memory `feedback_test_failure_reflection`):** a reflection is ONE per gap,
written at the conversational **"stop this gap" decision** (after bad results — NOT per test run; gaps take
several iterations). The agent **proactively asks** "write a reflection?"; on yes, writes to the spec above,
synthesizing across all iterations — the **user never re-states the spec**. New precondition → add a rule to
FAILURE_PREMORTEM + prompts (loop compounds).

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
