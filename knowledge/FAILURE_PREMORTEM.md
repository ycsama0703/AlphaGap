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
   **ML-#6** (LUPI on returns, oracle gain ~0). **ML-#11** initially looked like it survived (studies the floor →
   controllable hacking-gap) but later died on #8 below — "studies the floor" is necessary, NOT sufficient.

7. **承重区分点先验证 / Verify the load-bearing differentiator FIRST.** If the gap's value rests on a claim
   "**we differ from known work X**" (new mechanism / not-just-Y), that differentiator must have a **direct,
   passed experiment BEFORE** you build the framing/mitigation/positioning on it — never an unverified side-fact
   used as foundation. *Check:* name the single experiment that, if it fails, collapses "we ≠ X"; run it in
   Phase-0. A "we're different" claim with only *indirect/negative* evidence (and no positive falsifiable
   mechanism prediction) is a red flag. — caught **ML-#11** (the whole "active-agent hacking ≠ multiple testing"
   rested on F6 "linear can't hack", an unverified misread — F6's gap≈0 came from *finding the real signal* on
   real labels, never tested on no-signal; once tested, linear hacks → the differentiator collapsed → mechanism
   fell back to the known optimizer's curse, after weeks of building on it).

8. **换皮的低-SNR 选择 / Re-skinned low-SNR selection = the optimizer's curse.** If the gap's core action is
   "**select / search over a return (or low-SNR) objective**," then *no matter how it's packaged* (reward hacking,
   specification gaming, "agent", any AI-safety vocabulary), it will by default **collapse to the classic
   multiple-testing / optimizer's curse**: `gap ∝ √(log N_eff / T)`, where complexity / nonlinearity / agent
   architecture only enlarge N_eff. This is the trap door under #6 — "studying the floor" *via selection* is still
   riding the floor. *Check (strip-down test, do it in Phase-0):* reduce the search space to the **simplest** class
   (e.g. linear) and **shuffle the labels** (kill all real signal); vary ONLY selection intensity N. If the gap
   still rises ∝ log N, the mechanism IS multiple testing → **no novel mechanism**, only an application/testbed
   contribution. — caught **ML-#11** (linear + shuffled + best-of-N → gap ∝ log N, ρ=+0.86; even a single 25-param
   OLS on pure noise hacks 0.038).

9. **诚实的 null：控制必须看得到同样平凡可得的信息 / Fair control — the null must see the same trivially-available
   info.** For any "the model represents/recovers X" claim proven by **probe-beats-control** (interpretability /
   world-model / latent-state probing), the control must have access to **everything trivially available to a
   baseline**, especially **recent history (lags + deltas)**. Beating a *current-snapshot-only* control is NOT
   enough — a sequence model can win merely by **encoding recent trend**, which a cheap lagged regression captures
   too. *Check:* run the probe against a control with k lags + deltas (the fair null) **before** claiming a latent
   representation; require the probe's Δ-over-*lagged*-control CI > 0, not just over the snapshot control. — caught
   **ML-#2** (GRU hidden state beat a snapshot control at predicting next-quarter accounting predicates →
   Phase-0 GO; but once the control got 4 lags+deltas, **0/5 targets survived** — neg_ocf +0.046→−0.023 (lagged
   control *beat* the probe), profitable's CI crossed 0 → the "internal accounting world-model" was just
   trend-encoding. Killed cheaply at Phase-1 step 1 by testing this FAIR control first).

10. **闭式最优 = 无归纳偏置余量;承重对比是 vs LEARNED 不是 vs uniform / Closed-form-optimal ⇒ no
   inductive-bias headroom; the load-bearing baseline is a LEARNED component, not the trivial one.** If the gap's
   mechanism modification is essentially **hard-coding a closed-form / theorem-optimal form** (inverse-variance,
   Kalman gain, BLUE/GLS, analytic filter, optimal-transport map) into a **learnable component** (gate, weight,
   attention, step-size), then a **same-information fair learned baseline will recover it** — there is no
   publishable *inductive-bias* contribution, only "we hardwired the known optimum." *Check (before building):*
   ask "**can a same-inputs learned component trivially learn this form?**" If the form is closed-form-optimal and
   its discriminating feature sits in the learned component's inputs, the answer is yes → drop it. The load-bearing
   comparison is **hand-derived vs LEARNED (same info)** — NOT vs uniform/plug-in (a strawman). To test in Phase-0,
   run three-way: hand-derived vs learned(observable loss) vs **oracle**(trained on the latent ground truth =
   learnability ceiling); require the keyed−learned margin to grow with the activating structure AND clear a real
   threshold. **Sub-rule (fair baseline must actually train):** when the learned baseline is an MLP, **zero-init on
   a tanh layer gives dead gradients** (2nd-layer input = tanh(0)=0 ⇒ weight grads ≡ 0) — it freezes at init and
   *fabricates* a "hand-derived wins." Before any "hand-form > learned" claim, verify the learned baseline's loss
   actually decreased / weights actually moved. — caught **B1 volatility-keyed WLS forget-gate** (Wang et al.
   ICLR'25: linear-attn forget-gate = WLS weight; keyed to 1/σ̂² under GARCH. Mechanism real — keyed > uniform
   +2.7%, scales with persistence, shuffle-dissociated — but a same-info learned gate matched it *exactly*
   (keyed−learned ≈ 0.000), oracle beat it; inverse-variance is just learnable. Effect negligible anyway
   (predictive MSE 0.18%). Nearly mis-called GO due to the zero-init dead-gradient artifact freezing the learned
   baseline; small-random init exposed the tie. Cheap $0 kill).

11. **可滤波潜变量 = 滤波器 incumbent,两头堵死 / Filterable latent ⇒ the classical filter is the incumbent;
   dead on both horns.** If the gap's **target quantity is a filterable latent** — a hidden state / conditional
   variance / posterior belief that has a **known optimal estimator** (Kalman filter, HMM forward algorithm,
   GLS/BLUE, particle filter, EM) — the AI-mechanism modification is **pre-dead**: (horn 1) on the structure that
   makes the latent *computable*, the classical filter already attains the optimum, so the mechanism can at best
   **tie** (no headroom); (horn 2) on the structure where the latent is *not* computable (intractable / infinite
   state), there is **no ground-truth label** to supervise or validate the mechanism. *Check (two $0 paper-stage
   questions, before any build):* ① does the target quantity have a classical optimal filter/estimator? ② does the
   method's supervision label exist on the **real target data**, or only in simulation? If ① yes **or** ② only-in-sim
   → do not green-light. *To confirm empirically:* fit a K-state HMM / Kalman filter and measure how well its
   filtered estimate recovers the true latent (R² > ~0.95 ⇒ incumbent already solves it). **The surviving AI-mechanism
   shape must target something WITHOUT a classical optimum** — open-ended generation / policy / a representation that
   is *itself the product* — NOT "estimate a filterable latent." Same root as #8 (closed-form-optimal ⇒ no
   inductive-bias headroom). — caught **B1** (volatility-keyed forget gate = inverse-variance ≈ Kalman/GLS; a learned
   gate recovered it, margin 0.000) and **A1** (transformer residual belief ≈ HMM forward-algorithm posterior; a
   fitted-HMM forward filter recovered the true belief R²=0.99/0.998, oracle belief predicted the precursor at AUC
   0.50, and real markets have no belief label). This is the **same "filter incumbent" death** as the quant-stats
   line (HAR / GARCH-EVT / Ledoit-Wolf / ACI already solve the target). *(Note: this is the general rule; #10 above —
   numbered 8 in spirit — is the special case of hard-coding the closed form into a learnable gate.)*

12. **AI-agent 版经典病理 = 先用 head-to-head 验证"agent ≠ 静态对应物" / "AI-agent version of a classical
   pathology" — verify "agent ≠ its static counterpart" by a $0 head-to-head FIRST.** If a gap reframes a KNOWN
   statistical pathology (optimizer's curse / multiple testing / data-snooping) as an "active-AGENT" or "dynamic"
   version, the entire novelty rests on the agent's dynamics producing something its STATIC same-size counterpart
   cannot. *Check (decisive, $0, before any build):* run the **agent on a null** (shuffled labels) vs a **static
   counterpart matched to the agent's ACTUAL DISTINCT-trial count** (max over that-many random strategies) — NOT
   its nominal eval count. **FAIRNESS IS LOAD-BEARING:** an agent re-evaluates elites, so it explores far fewer
   DISTINCT formulas than its nominal evals; comparing to a nominal-size random universe gives the static null
   extra distinct draws and FALSELY shows "agent < static." Match the distinct count. Also: reviving a gap whose
   mechanism already turned out KNOWN needs a NEW load-bearing differentiator, head-to-head tested FIRST — never
   stack repositionings on an unverified "it's different because it's an agent."
   **VERIFY THE KILL, not just the GO:** a NO-GO/shelve decision must be adversarially checked (esp. for a fair
   comparison) before distilling rules from it — a buggy kill wrongly discards a direction.
   *Empirical finding (corrected):* at a FAIR matched-DISTINCT comparison, adaptive search slightly OUT-mines a
   same-size random universe (small, marginal — ~+0.01 IC, 90% CI excludes 0 only at higher search intensity, and
   it grows with intensity). This is the **adaptive-data-analysis** effect (adaptive querying finds higher extrema
   than non-adaptive of equal size) — known, and weak; novelty hinges on the #7 lit-gate, not efficacy. — surfaced
   by **ML-#11 revival**: the FIRST head-to-head used the agent's nominal count and WRONGLY concluded "adaptive
   under-inflates / shadow=Reality-Check dominated"; an adversarial fairness re-check (matched distinct count)
   reversed it to a weak positive adaptive edge. Related to #8 (re-skinned selection) and #7 (verify the
   differentiator FIRST).

13. **误归因防火墙:先证"结构之外"work,再谈"结构之处"failure / Mis-attribution firewall — prove it works
   OUTSIDE the blamed structure before claiming it fails AT that structure.** For any **transfer-failure** gap
   that claims a method **specifically fails at some finance structure** (regime switch / jump / non-stationarity /
   fat tail), the whole story requires the method to **actually work OUTSIDE that structure** (in the calm regime).
   *Check ($0, real data):* first show the method beats a **trivial last-value / random-walk baseline** in the
   calm regime; only then test the blamed structure. If it **already loses in calm**, the failure is **general**
   (usually because the finance feature is a **near-martingale with no exploitable smooth structure** = the 族A /
   low-SNR death), and "fails at jumps" is a **mis-attribution** of a general failure to a specific cause → the gap
   doesn't stand. **Sub-rule:** "error concentrated at jumps" is NOT evidence of differential jump-fragility (jumps
   are unpredictable for EVERY method); the bar is **at-jump error WORSE than the trivial baseline**. — caught
   **TDA continuous-evolution transfer failure** (claimed neural-ODE / TDA-evolution works on smooth dynamics but
   fails at finance jumps; real-data test on the rolling-correlation market-mode feature showed last-value beat the
   continuous methods EVERYWHERE — 3.7× better in calm, 1.18-1.23× at jumps — so the calm advantage never existed;
   the feature is a near-martingale, continuity has no smooth velocity to exploit; "fails at jumps" mis-attributed
   a general failure. $0/CPU/findata-native; robust to the stand-in since no smooth-flow model beats last-value on
   a random walk).

14. **同模型 ablation 先行:要证某 LLM 行为是模型内在,决定性对照=同一模型只改可疑诱因 / Same-model ablation —
   to claim an LLM behavior is model-intrinsic (AI-specific), the decisive control is the SAME model with ONLY the
   suspect cause (usually a prompt / convergence instruction / scaffold) changed.** External baselines and
   cross-model replication are **not enough** — replication holds the suspect cause CONSTANT, so it cannot detect a
   prompt/instruction artifact. *Check:* before claiming "model M does X intrinsically," run M with the suspect
   cause removed; if X vanishes → artifact. *Corollary:* an optimizer told to "optimize metric Z" converging to Z
   is universal and normal, **not** mode collapse; and don't use a mutation-driven GP as a "diversity baseline" (it
   is structurally over-dispersed → falsely inflates the gap). — caught **neff mode-collapse loop** (LLM-refine
   spanned fewer effective dims than GP, replicated across qwen-7B + gpt-chat-latest + 3 seeds → looked AI-specific;
   but same model + "maximize diversity" prompt lifted indep 0.02→0.15 ≈ GP → the collapse was the convergence
   INSTRUCTION, not the model).

15. **必须打败"最蠢的基线"(不是稻草人)/ Must beat the DUMBEST baseline, not a strawman.** A constructive
   mechanism gap's whole value is that the borrowed mechanism beats what you'd trivially do. Name the
   dumbest baseline for the exact objective — **last-value / random-walk** (forecasting), **leverage /
   Cook's-distance** (fragility), **DAG-depth / node-count** (graph), **mean-verdict** (verification),
   **unweighted distance** (reweighting), **IS-IC** (OOS degradation), **uniform / plug-in** (weighting) —
   and require the mechanism to beat IT, head-to-head, at matched cost/complexity. *Check (before build):*
   "can I argue it beats the dumbest baseline?" If not, don't build. — general form caught the entire
   2026-06-20/21 sweep: alpha (LLM economic prior < Occam/complexity-matched GP), #2 (spectral radius ≈
   DAG-depth), #5 (continuous-evolution < last-value on a near-martingale), Gap A (influence-concentration
   < leverage; residual was ADA), Gap C (verifier-disagreement < mean-verdict). Subsumes #10/#13.

16. **标准金融任务对强模型已到天花板 → agent 可靠性/验证类 gap 空洞 / Standard financial tasks are AT CEILING
   for frontier models ⇒ agent-reliability / verification / abstention gaps on them are vacuous.** A strong
   model computes standard ratios and selects standard formulas essentially perfectly. So a gap framed as
   "reduce the agent's numerical/logic/verification error on standard financial computation" has **no error
   left to reduce** (decomposition degenerates: A=B=1.0; verifier disagreement = 0). *Check (before build):*
   measure the strong-model baseline on the exact task — if it's already ≈ceiling (acc≈1 / disagreement≈0),
   the gap is vacuous. Real signal requires genuinely HARD / ambiguous tasks (messy extraction, non-standard
   metrics, period matching) — which reintroduce the **subjective-label (κ-collapse, #6/F-evidence) and
   hard-logic** traps; weigh that cost up front. — caught **#4** (evidence-compute separation: A=B=1.0, no
   arithmetic error to offload) and **Gap C** (verifier disagreement = 0.000, mean-verdict AUROC = 1.0).

17. **反叙事"病态-修复" gap:先验信号下限 + 病态须超最简学习器 + 修复须非平凡(≠退回默认策略)/ Counter-narrative
   "pathology-then-fix" gap — establish the signal floor, reproduce the premise in-sample, and verify the fix is
   non-trivial, BEFORE crediting the story.** For a gap shaped "method A exhibits pathology P (value hallucination /
   overfit / live-collapse), conservative method B fixes it," three preconditions must hold: **(i) signal floor** —
   some learner must beat the dumbest baseline (buy&hold / last-value); if not, the "live collapse" is the universal
   low-SNR collapse (族A), not A-specific. **(ii) premise reproduces** — A must beat the simplest learner (supervised)
   **in-sample** before its live collapse is attributable to the mechanism rather than to there being no signal at all.
   **(iii) non-trivial fix** — B's "fixed" policy must DIFFER from simply reverting to the behavior/default policy
   (check: does B's output match the data-generating / behavior policy position-for-position? if yes, B didn't learn,
   it reverted). *Check (Phase-0):* the floor, the in-sample A>supervised premise, and B≠behavior-policy. **VERIFY THE
   KILL:** measure the train/backtest-vs-live GAP (not just OOS level), and roll each policy out on ITS OWN greedy
   trajectory (not behavior-policy states) — a lazy kill can wrongly declare "phenomenon absent." — caught **THEORY-1**
   (offline-RL value hallucination: phenomenon WAS real — naive-DQN train-test gap 2.45 > supervised 1.74, CQL shrinks
   to −0.26 — but buy&hold +0.97 beat every learner (no floor), RL never beat supervised in-sample (0.47≈0.48), and
   CQL's "fix" matched the momentum behavior policy position-for-position (−0.51/−0.25 = trivial revert). Verify-the-kill
   corrected my premature "phenomenon absent" call but the kill stood on cleaner grounds.) Subsumes #6/#13/#14/#15 for
   the counter-narrative shape.

18. **自适应/在线机制 vs 静态基线:承重 incumbent = 静态法的"条件化升级",不是裸静态版 / Adaptive-vs-static — the
   load-bearing incumbent is the static method's obvious CONDITIONAL/SCALED upgrade, not its raw static form.** For a
   gap shaped "adaptive/online mechanism (ACI, online learning, meta-recalibration) beats a static baseline under
   distribution shift," the load-bearing incumbent is **NOT** the raw static method — it's that method's **obvious
   conditional / scaled upgrade** (EWMA-vol-scaled band, GARCH residual scaling, rolling conditional quantiles). The
   "collapse" observed in the static version is usually a **static-parameter artifact** (e.g. width that doesn't scale
   with the volatility level); the conditional upgrade captures most of the recovery for free, and the adaptive
   mechanism's marginal edge OVER that upgrade is the real bar — typically small and riding on a single shift event.
   *Check (Phase-0, $0):* run the three-way {raw static, conditional upgrade, adaptive mechanism}; if the conditional
   upgrade already pulls the metric back near nominal, the adaptive mechanism is vacuous. Also **count the distinct
   shift EVENTS** the GO rests on — one event is not a result. — caught **THEORY-2** (ACI for HAR-RV 90% coverage:
   COVID collapse real — fixed-cal 0.805 (basket-robust, median 0.806) — but a textbook EWMA-vol-scaled band recovered
   70% (0.872); ACI's extra +1.1pp coverage cost +8pp width (+31% vs +23%) and rode on COVID alone; 2022 didn't
   collapse, 2008 uncalibratable since findata starts 2006). Special case of #11 (filter incumbent — conditional
   variance has known solutions) + #15 (the dumbest baseline's *correct* / conditional version).

19. **结构化/低秩"预测某会计/慢变量"类 gap:OOS-verify-the-GO + 平凡平滑器基线 + 结构化-vs-per-firm 的 OOS
   增益 / "Structured/low-rank forecasting" gap — OOS-verify the GO before any mechanism, baseline a
   TRIVIAL smoother, and prove the structural component adds OOS forecasting value over a per-firm baseline.**
   For any gap that proposes a structured / low-rank / cross-sectional mechanism (matrix or tensor completion,
   factor model, robust-PCA, graph) to **forecast** an accounting / slow-moving quantity, run four $0 checks
   **before matching a mechanism**: **(1) OOS not in-sample** — expanding-window OOS skill vs random-walk; the
   in-sample R² massively overstates, and **YoY / seasonal differencing of a persistent series induces
   autocorrelation that is OOS-negative** (a near-RW level looks "forecastable" in differenced in-sample space).
   **(2) Trivial-smoother baseline** — put a trailing-mean / shrink smoother in the baseline; a noisy mean-reverting
   quantity is often denoisable by trivial local averaging that beats RW, so the load-bearing bar is "beat the
   **smoother**", NOT "beat RW" (#15). **(3) Structural-vs-per-firm OOS gain** — the cross-sectional / low-rank
   component must REDUCE OOS error vs a per-firm baseline; **contemporaneous low-rank covariance does NOT imply
   forecasting value** (a panel can be 15–50% low-rank in covariance yet the factor adds ~0 OOS). **(4) No-fill PCA**
   — assess low-rank on a balanced, no-fill panel; `fillna(median)` injects a spurious common component (inflated
   PC1 35% → real 15%). **VERIFY THE KILL too:** "RW unbeatable" can itself be a misread — the true verdict is often
   "a trivial smoother beats RW, but the structural mechanism can't beat the smoother" (#15 ceiling). — caught
   **THEORY-4** (gross-margin structured forecast: in-sample AR R² 0.318 → OOS −0.002, YoY-param −0.380; only a
   trailing-mean smoother beat RW (+0.264); the cross-firm factor added −0.003, losing to the smoother by 0.27; the
   "strong low-rank" was a median-fill artifact 35%→15%). Subsumes #1/#6 (in-sample mirage) + #9 (fair baseline) +
   #15 (dumbest baseline = the ceiling).

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
