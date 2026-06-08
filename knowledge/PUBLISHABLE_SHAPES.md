# Publishable Shapes in AI×Finance

*Distilled from 250 anatomized papers (ICLR / NeurIPS / ICML / ICAIF / AAAI, 2023–2026).*
*Purpose: a map of what actually gets accepted, so our gap search aims at live targets instead of dead ones.*

---

## 1. The Publishable-Shape Distribution

What kind of contribution earns a slot, by `contribution_type` (n=250):

| Shape | Count | Share |
|---|---|---|
| new_architecture | 81 | 32.4% |
| empirical_study | 31 | 12.4% |
| constrained_optimization | 27 | 10.8% |
| mechanism_transfer | 27 | 10.8% |
| application_pipeline | 25 | 10.0% |
| benchmark_dataset | 25 | 10.0% |
| agent_system | 15 | 6.0% |
| theory | 14 | 5.6% |
| other (surveys, etc.) | 5 | 2.0% |

**The headline surprise: only 31% (77/250) papers ride return prediction at all.** The other ~69% earn acceptance on objectives that are *not* "predict returns / Sharpe": fraud/credit detection, volatility, LLM reasoning/QA, benchmarks, hallucination, bias, calibration, imputation, market simulation realism, hedging tails, fairness. The field's publication surface is far wider than alpha.

**Second surprise — the "novel architecture" majority is mostly NOT a finance contribution.** A large share of the 81 `new_architecture` papers are generic ML methods where *finance is merely one evaluation domain* (e.g. Times2D general forecasting, Focal-SAM long-tailed classification, FIC-TSC TS classification under shift). The defensible novelty lives in the *method*, not in any finance property. This means "new architecture" is a crowded, ML-conference-grade bar, not a soft finance bar.

**Third surprise — `finance_property_used` is dominated by `none-generic` (141/250 = 56%).** Most accepted papers do **not** lean on a distinctive finance property at all. The properties that *do* show up, when they show up:
- microstructure: 33 (13%)
- non-stationarity: 35 (14%)
- heavy-tails: 22 (9%)
- no-arbitrage / accounting: 16 (6%)
- PIT / restatement: 3 (1%) — almost untouched, a genuine white space

So "use a real finance property" is the *minority* path — but it is exactly the path that makes a contribution hard to scoop by a generic ML lab.

---

## 2. Mechanism-Transfer Reality Check

**How many are genuine "modify an AI mechanism, transfer to finance"? 27/250 = 10.8%.** It is a real, recurring, *accepted* shape — neither dominant nor rare. About one paper in nine.

**Which finance property did the successful ones lean on?** Of the 27, the property mix is the key signal:

| Property leaned on | ~Count in the 27 | Read |
|---|---|---|
| heavy-tails | ~7 | The single most productive vein |
| microstructure | ~6 | Second most productive |
| non-stationarity / regime | ~7 | Productive but often soft (regime = label) |
| none-generic | ~7 | Weakest sub-class (see below) |

**The pattern that works:** the transfer is defensible precisely when it *grafts an AI mechanism onto a hard, named finance property the mechanism was not built for*, and the property creates the failure the mechanism fixes:
- **heavy-tails** → EX-DRL grafts EVT/GPD onto distributional-RL quantiles to fix *imprecise tail quantiles* in hedging; GARCH-LSTM / GINN inject volatility clustering & fat tails into NNs; AlphaQCM uses distributional RL for fat-tailed alpha; diffusion denoiser lifts low-SNR series.
- **microstructure** → statistical-physics order-book "momentum" for spoofing detection; AIRL to recover market-making reward; Koopman-PINN constrained by the SDE generator for Heston recovery; neural density estimators to calibrate LOB simulators.

**The anti-pattern (the `none-generic` transfers) is the weak class.** When the "finance property" is absent, the paper survives only on *direction of transfer* or *novel application*: Black-Litterman pushed *out* to supply chains; Hopfield nets "first applied to" portfolios; GAN charts for CNNs; federated-learning DeFi token incentives. These earn novelty by **first-application** or **cross-domain export**, not by finance depth — and they are the easiest to dismiss as "just an application."

**Why is the shape only moderately common?** Because the *good* version requires a rare conjunction: (a) an AI mechanism with a known limitation, (b) a finance property that *is exactly that limitation* (fat tails ↔ quantile imprecision; LOB discreteness ↔ non-differentiability), and (c) headroom over the obvious baseline. When (b) is fudged to `none-generic`, the paper degrades into a thin "we tried X on finance" note. **The finance property is the load-bearing wall of a transfer paper.**

---

## 3. The Recurring Novelty Structures

Six distinct "shapes" of *how* these papers earned their novelty. Each has a defensibility test and an exemplar.

### Shape A — New-benchmark-shows-the-frontier-fails
Build a dataset/eval that exposes a *named failure* of current SOTA (usually LLMs).
- **Defensible because:** the dataset is the contribution; the failure is reproducible; contamination-resistance / expert annotation is the moat.
- **Examples:** FinMathBench (contamination-resistant formula math), FAITH (intrinsic tabular hallucination from S&P 500), "Can AI Read Like a Financial Analyst?" (retrieval, not reasoning, is the bottleneck), LOB-Bench (generative-LOB realism), FinDER (terse/ambiguous expert RAG).
- **Moat strength:** high if annotation is hard to replicate; low if it's a relabel of public corpora.

### Shape B — Constrained / decision-aware optimization
Bake a real constraint or the *downstream decision loss* into the objective instead of a proxy.
- **Defensible because:** the constraint is economically real (regulatory rate grids, leverage, GMVP variance) and the gain is *attributable to the constraint*, not the model size.
- **Examples:** decision-loss gradient *through* GMVP (optimize realized variance, not covariance MSE); retail-lending uplift under rate-grid/regulatory/budget constraints; volatility-drag mitigation under leverage; certified/verified allocation NNs.
- **Moat strength:** high — proxy-vs-decision gap is a clean, ownable story.

### Shape C — Mechanism-transfer onto a hard finance property
(See §2.) Graft an AI mechanism onto fat-tails / microstructure / regime so the property *causes* the win.
- **Defensible because:** the baseline mechanism provably fails on the property; ablating the finance-aware piece collapses performance.
- **Examples:** EX-DRL (EVT+distributional RL for tail hedging), Koopman-PINN Heston recovery, statistical-physics manipulation detection.
- **Moat strength:** high when property is load-bearing; collapses to "application" when `none-generic`.

### Shape D — LLM-behavior empirical study (audit / bias / look-ahead)
Measure a *latent pathology* of LLMs in a finance decision context and localize it mechanistically.
- **Defensible because:** it's a measurement nobody published, with a method to detect/localize, and a safety/governance hook.
- **Examples:** positional bias in LLM financial decisions (mechanistic localization), "Your AI, Not Your View" (intrinsic sector/size/momentum bias + confirmation bias), "Do LLMs Understand Chronology?" (look-ahead-bias risk in backtesting).
- **Moat strength:** medium-high — first-to-measure is durable; but easy to follow once the framing exists.

### Shape E — Structure-aware representation for a finance data pathology
Design a representation that respects a structural defect of finance data (missingness, evolving graphs, look-ahead, lead-lag).
- **Defensible because:** the structure (firm/time/variable tensor; static+dynamic graph; PIT embeddings) is finance-specific and ablatable.
- **Examples:** ACT-Tensor (firm/time/variable tensor completion for severe missingness), dynamic+static credit-risk graphs, narrative-volatility net using *point-in-time* LLM embeddings to kill look-ahead, role-aware fraud graphs.
- **Moat strength:** high — the data pathology is hard for generic ML to even see.

### Shape F — Agentic system / pipeline with a measured deployment or eval claim
Compose LLM agents into a finance workflow and earn the slot on a *system* or *eval-framework* contribution, not a model.
- **Defensible because:** the contribution is the orchestration + a new eval (Agent-as-a-Judge, temporal-aware retrieval) or a measured business/usability impact.
- **Examples:** FinResearchBench (logic-tree Agent-as-a-Judge), FinSearch (temporal-aware search agent + benchmark), PortfolioPilot (deployed no-code platform), MARL market-making collusion study.
- **Moat strength:** medium — strongest when paired with a benchmark (collapses into Shape A); weak as a pure demo.

*(A latent Shape G — pure theory with finance flavor: e-value online FDR, nested kernel quadrature, social-welfare RL portfolios. Real but only 14/250, and the bar is a math bar, not a finance bar.)*

---

## 4. What This Says For Our Gap Search

We keep dying three ways: **(i) mechanism turns out already known, (ii) no headroom over the obvious baseline, (iii) the win rides low-SNR return prediction.** The distribution above says all three are *symptoms of fishing in the wrong shape*. Concrete redirection:

### TARGET these (high headroom, low scoop risk, off the return treadmill)

1. **Shape B — decision-aware / constrained optimization.** This is our best fit. The novelty is the *proxy-vs-decision gap*, not a return number; baselines are honest (MSE estimator, shrinkage) and the win is attributable to the constraint, not luck. It does not ride return-SNR — GMVP optimizes *realized variance*, a high-SNR target. Findata-native (price + accounting constraints). **This dodges all three failure modes.**

2. **Shape E — structure-aware representation for a data pathology.** Missingness, PIT/restatement, lead-lag, evolving graphs. Crucially, **PIT-restatement is used by only 3/250 papers — a near-empty white space**, and our MEMORY explicitly flags findata as PIT-aware. A "look-ahead-bias is silently inflating reported Sharpe; here is a PIT-correct representation and the corrected gap" paper is Shape D∩E and almost unoccupied. High-SNR target (you're measuring a *bias*, not predicting returns).

3. **Shape D — LLM-behavior audit in a finance decision context.** First-to-measure beats first-to-improve. We don't need return headroom; we need a *clean measurement of a pathology* (look-ahead, chronology, positional/confirmation bias) plus mechanistic localization. Cheap, findata-native, no backtest-luck dependence.

4. **Shape C — but ONLY with a load-bearing finance property.** Pursue mechanism-transfer *only* when fat-tails or microstructure is the *cause* of the baseline's failure (e.g. tail-quantile imprecision, LOB non-differentiability/discreteness). The property must be ablatable: remove it → win collapses. This is exactly our existing "mechanism-line" thesis, sharpened.

### AVOID these (where we keep dying)

- **Shape A new benchmark** unless we have a genuinely hard-to-replicate annotation moat. Crowded; a relabel of public corpora gets desk-rejected.
- **`none-generic` mechanism transfers** ("first application of X to portfolios"). 7 of the 27 transfers are this, and they're the weak class — reviewers call them "just an application." If we can't name the finance property the mechanism exploits, kill the gap at intake.
- **Return-prediction architectures on low-SNR daily equity.** This is the 77/250 treadmill where headroom is noise and baselines are strong. Our repeated deaths (#stable-vs-lucky NASDAQ rounds) are textbook. If the win can only be shown as a Sharpe delta on noisy returns, it will not survive a holdout.
- **Generic new_architecture** that happens to use a finance dataset. That's an ML-conference bar competing with full ML labs; finance gives us no edge there.

### The one-line filter for any candidate gap

> **Does the win come from a *named finance property* or a *decision/structure objective* that is (a) high-SNR, (b) cheap to test, and (c) not scoopable by a generic ML lab? If the only story is a Sharpe delta on noisy returns, reject at intake.**

This pushes us toward B / E / D — measurement-of-bias, decision-aware optimization, and PIT/structure white space — and away from the return-SNR and `none-generic`-transfer graveyards where our last several lines died.
