# AlphaGap — Handoff (last updated 2026-06-04)

> Living handoff: where the project is, what shipped, what's pending. Read this first.

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
4. (optional) run a **findata-native light gap** through the full TEST rails (Phase 0→1→holdout
   + Deflated Sharpe), per the lesson that TEST targets must be cheap (see decisions).

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
