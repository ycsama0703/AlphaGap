# Failure pre-mortem — empirical-precondition checks for DISCOVER

> **Why this exists.** Our gap-scoring chain (04/05/07) scores whether a transfer is *logically/structurally
> sound* — structural homology, failure-mode match, assumption transferability, identifiable prediction,
> theoretical anchors. But gap *survival* depends on **empirical preconditions** the chain never checks:
> is the signal alive? is this the binding constraint? does the changed quantity move the target metric?
> Every tested gap so far (b027, b017, b012, evidence-sufficiency) failed on an **unstated empirical
> precondition**, NOT on its transfer logic. This file distills those failures into mechanism-level checks
> to run *before* scoring a gap high — i.e. fail predictable losers cheaply, in DISCOVER, not in TEST.
>
> Source: `~/.xp/findings/reflections.jsonl` (mechanism-level post-mortems; keep these checks brand-free —
> the lesson is the computational/statistical condition, not the model name). Living list: add a check when
> a new failure reveals a new precondition. Each is **decision-support shown to the human, never an auto-veto.**

## The checklist (run on every engineering gap before scoring it high)

For the gap's core mechanism, name the **2–3 empirical facts that must be true for it to work**, and give a
**$0 / one-line check** of whether each holds *now, in available data*. Use these recurring checks:

1. **可学习下限 / Learnability floor.** If the mechanism must *learn or separate* something from a signal,
   that signal's **standalone** strength must clear the learnability floor (≈ rank-IC 0.05 / R² 0.003 for
   monthly cross-sectional return signals; analogous floor elsewhere). *Check:* measure each
   signal/supervisory-anchor's standalone predictive strength on recent data. Below floor → unlearnable
   *regardless of architecture*. — caught **b027** (mispricing anchor = reversal ≈0.02 < floor).

2. **诊断对象先存在 / Diagnosed thing must exist.** A detect/audit/diagnose mechanism is vacuous unless the
   thing it inspects **exists out-of-sample first**. *Check:* verify the target phenomenon (e.g. a durable
   OOS edge) is present before building the detector. Also: **attribution/importance share ≠ causal source
   of generalization** — don't equate "model attends to X" with "edge comes from X." — caught **b017**
   (audited a model whose OOS edge was ≈0/negative; momentum got 69% attribution but wasn't the edge).

3. **因果杠杆 ≠ 结构同构 / Causal lever, not just structural homology.** Confirm the **quantity the mechanism
   changes actually controls the target metric** — not merely that the AI and Fin settings share a surface
   structure. *Check:* a derivation or quick sensitivity test that "change A ⇒ move M." — caught **b012**
   (reward-centering moved the advantage *mean*; turnover is set by the *cost-gradient*; A→M coupling ≈0).

4. **主约束体检 / Binding-constraint check.** A mechanism that fixes failure-source A yields ~0 net gain if A
   isn't the **dominant** error source. *Check:* decompose the baseline's errors — what fraction comes from
   A vs other sources? Small share → fixing it can't help much. — caught **evidence-sufficiency** (fixed
   evidence-completeness, but the binding constraint was LLM reasoning over evidence, ~13% on complex).

5. **标签客观性 / Label objectivity (construct validity).** If the gap's **positive result depends on a label
   that is a SUBJECTIVE judgment** (sufficiency / quality / "good enough" / how-well), its inter-annotator
   reliability must hold on **HARD cases at scale** — not a small easy sample. *Check:* on a difficulty-stratified
   scale sample, measure ≥2 independent annotators' (or models') κ. Subjective labels **inflate κ on small/easy
   samples (0.7–0.95) then collapse (~0.4) at scale** — the benchmark won't stand, and only negative/methodology
   framings survive (which don't publish in an innovation+positive venue). Prefer **objective/verifiable or
   ablation-constructed ground truth** over human/LLM adjudication. — caught **agent-evidence-sufficiency-benchmark**
   (sufficiency κ 0.74→0.40 from easy-60 to hard-467; even Qwen/o3/Gemini ≈0.35–0.47 on hard cases; only the
   negative "LLM-judge is unreliable / bimodal" framing survived).

6. **目标信噪比 / Don't ride a low-SNR return target (study the floor, don't fight it).** If the gap's primary
   metric ultimately rides on a **low-SNR return/forecast target** (monthly cross-sectional rank-IC ~0.02–0.05),
   the method's marginal value collapses to ~0 — every relMSE/accuracy ratio → 1.0 against a near-noise ceiling,
   *regardless of architecture*. This is the deepest, most-repeated killer for finance-ML method gaps. *Check:*
   the learnability-floor probe (#1) — best single signal must clear rank-IC ≥0.05 before crediting ANY method win.
   **Prefer gaps whose objective label is NOT a noisy return** — either (a) a deterministic/structural target
   (accounting identities, equivariance residual, intervention deltas, masked-fact reconstruction), or (b) gaps
   that **STUDY the noise floor's consequence** (reward-hacking / backtest-overfitting / mis-calibration) rather
   than try to beat it. — caught **b027/b017/b012** (alpha, sub-floor), **ML-#1** (equivariance, chars floor 0.03),
   **ML-#6** (LUPI on returns, oracle gain ~0). SURVIVED: **ML-#11** (studies the floor → a controllable hacking-gap,
   monotone in reward-spec looseness, Spearman +1.00) — the first live gap of the batch.

## How it feeds back
- **prompt 05** (engineering gap): the gap must output an `empirical_preconditions` block — the 2–3 facts +
  their $0 checks, drawing on the list above.
- **prompt 07** (scoring): a gap whose core empirical precondition is unchecked or likely-violated should not
  score as a confident bet; surface the precondition risk to the human (alongside significance).
- **brief / email**: add a 4th header line — **📉 经验前提 + 现状体检** — so the human sees, at a glance, what
  must be true and whether a cheap check says it is.

## Process — ONE reflection per gap, at the "stop" decision (agent asks; user never re-states the spec)
A reflection is written **per gap, at the moment we decide to STOP it** (after the test results are bad and
we agree to abandon) — NOT auto-fired on every `conclude()` (that would write one per intermediate iteration =
noise; a gap often takes several test iterations before we stop, e.g. b027 mega→small-cap, b017 v1→v2→v3).
The standing protocol:
1. **Agent asks (standing behavior):** when the conversation reaches "stop this gap," the agent proactively
   asks *"write a reflection?"* — the user does NOT have to remember to request it, nor re-explain the spec.
2. **Write to spec (on yes):** the agent drafts a mechanism-level reflection (schema below), synthesizing
   across ALL of the gap's test iterations, optionally via `harness/reflect.py:reflect_on_card()`, then refines.
   Append to `~/.xp/findings/reflections.jsonl`.
3. **Distill (loop closes):** a new precondition → add a rule here + to prompts 05/07 (Desktop + app), so the
   next gap is pre-checked for $0 in DISCOVER. New rules compound; this checklist is the living output.

Reflection schema (per entry, mechanism-level, brand-free): original_thesis(🏦 fin_problem / 🤖 ai_technique /
🔗 transfer_basis) · predicted · actual · broken_link (necessary condition + violated quantity) ·
which_header_claim_failed (🏦/🤖/🔗/"unstated precondition") · failure_category · root_cause ·
early_sign_missed · cheap_precheck · header_gap · distilled_rule.

## Meta-lesson (the systemic fix)
The 04/05/07 chain optimizes *reasoning soundness*; survival needs *empirical preconditions*. These are
orthogonal — a gap can be perfectly reasoned and dead on arrival. This checklist makes the empirical
preconditions a first-class, mechanism-level part of DISCOVER, so predictable failures die for $0 up front
instead of after a TEST build.
