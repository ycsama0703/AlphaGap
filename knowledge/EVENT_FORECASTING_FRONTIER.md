# Event Forecasting × Prediction Markets — research frontier (2024–2026)

> Frontier/novelty scan for an AI×finance research agenda. Produced by the deep-research workflow
> (5 angles → 24 primary sources fetched → 116 claims → 25 adversarially verified, 23 confirmed / 2
> killed → 11 synthesized findings). All findings rest on primary arXiv papers (several peer-reviewed:
> NeurIPS 2024, ICLR 2025, EMNLP 2025), unanimous 3-0 verification unless noted. Scanned 2026-06-06.
> Purpose: decide whether "LLM/agent event forecasting × finance" has a defensible, publishable gap.

## TL;DR (the decision)
- **LLM event forecasting is a hot, well-defined area but NOT solved**: the best LLMs still lose to
  human expert/superforecasters on every major benchmark. So there's real room — it's not saturated.
- **The dominant methodological theme is data-LEAKAGE**, and 2025–26 work proves the standard controls
  (date-filtered search, "pretend you don't know", CoT inspection) are **unreliable**. The field's
  response: **go forward-only / live**. Any credible new paper here MUST be forward-only — reviewers
  now reject retrospective/"simulated-ignorance" backtests.
- **The finance white space is REAL but actively closing**: no major general benchmark covers discrete
  financial events (earnings/FDA/M&A/macro), BUT finance-specific benchmarks emerged in **2025**
  (FinCall-Surprise, SAE-FiRE, Prophet Arena) — a new agenda must position against *these*, not just
  ForecastBench/Halawi.

---

## 1. State of the art — "LLMs as forecasters"
- **Canonical system — Halawi et al. 2024 (NeurIPS), arXiv 2402.18563**: retrieval-augmented LM that
  auto-searches news → generates probabilistic forecasts → aggregates. **Approached but did NOT beat**
  the competitive-forecaster crowd overall (Brier **0.179 vs crowd 0.149**, gap 0.03); beat the crowd
  only in a *selective high-confidence* subset (0.240 vs 0.247, 22% of forecasts). [The headline
  "surpasses human crowd" framing was REFUTED in verification — it's selective-subset only.]
- **Still below human experts (as of mid-2025)** across every benchmark:
  - **ForecastBench (arXiv 2409.19839)**: experts beat the top LLM, p<0.001. Superforecaster Brier
    ~0.092–0.096 vs best LLM (Claude 3.5 Sonnet) 0.114–0.122.
  - **Lu 2025 (arXiv 2507.04562)**, 464 Metaculus Qs: frontier LLMs **beat the crowd but lost to experts**
    (best LLM o3 Brier 0.135 vs expert median ~0.0225).
  - LLMs only *match the inexperienced public* even with news retrieval + prompt engineering + crowd access.
- **Caveat — gap is narrowing fast**: AIA Forecaster (arXiv 2511.07678, Nov 2025) claims **near-parity**
  (Brier 0.0753 vs human 0.0740) on one live benchmark. So "LLMs not at expert level" is true as of
  mid-2025 but may not hold by late 2026.

## 2. Benchmarks & datasets
- **Halawi multi-platform dataset**: 5,516 binary Qs (3,762/840/914) from 48,754 Qs + 7.17M forecasts,
  5 platforms (Metaculus/GJOpen/INFER/Polymarket/Manifold), 2015–24. **General-domain, NOT finance.**
- **ForecastBench (2409.19839)**: 1,000 auto-generated, regularly-updated, **forward-only** Qs from 9
  sources (markets + datasets incl. FRED, Yahoo Finance). Structurally leakage-free (only future events).
- **THE GAP (high-confidence)**: **no major forecasting benchmark covers discrete FINANCIAL events.**
  ForecastBench touches finance only via generic time-series templates (FRED CPI, S&P500 %-change-by-date);
  Halawi buckets all finance into one broad "Economics & Business" slice. **Neither has earnings
  surprises, FDA decisions, M&A completion, or macro surprises as discrete forecastable events.**
- **BUT — finance-specific benchmarks emerged in 2025 (must position against these):**
  - **FinCall-Surprise (arXiv 2510.03965)** — earnings-call / surprise oriented.
  - **SAE-FiRE (arXiv 2505.14420)** — financial reasoning/event.
  - **Prophet Arena (arXiv 2510.17638)** — prediction-market-style forecasting arena.
  *(These were not directly verified in this scan — their exact coverage/SOTA is an open question to check.)*

## 3. Prediction markets as a research object
- Polymarket's 2024–25 rise made prediction-market data a real research object.
- **PolyBench (arXiv 2604.14199, Apr 2026)**: multimodal benchmark of **38,666 binary Polymarket markets**
  across 4,997 events (CLOB state + news + resolution criteria), argues markets are **structurally
  contamination-immune** (forecast future events). [This "immune" claim split 2-1 in verification — the
  dissent notes live setups still face *secondary* leakage: pre-cutoff info, post-resolution docs in retrieval.]
- Active LLM-trading-agent / efficiency / aggregation work on Polymarket (multiple 2026 arXiv + SSRN).
- **Our constraint**: findata has **NO prediction-market odds** — so we can study *LLM event forecasting*
  (predict the event from text), NOT *prediction-market trading/microstructure* (no odds data).

## 4. Calibration & reliability — the leakage problem (most important)
- **LLMs are overconfident**: hold rigid high confidence (0.8–0.9) regardless of difficulty; forecasting
  ability varies sharply by domain + prompt framing; failure modes = rumor/recency overweighting,
  definition drift (2604.14199, 2511.18394). [overconfidence figures from a narrow 6-day/7-model snapshot.]
- **Leakage controls are PROVABLY unreliable (the killer finding):**
  - **Date-filtered search fails (arXiv 2602.00758)**: across ~393 Metaculus Qs, post-cutoff info leaked
    for **71% (Google before:) / 81% (DuckDuckGo)**, directly revealing the answer for 41% / 55%.
    Inflates accuracy massively (Brier 0.24 → ~0.10).
  - **"Simulated ignorance" (prompt to forget) fails (arXiv 2601.13717)**: across 477 Qs / 9 models, a
    **52% residual performance gap** vs true ignorance; **CoT inspection cannot detect the leakage**
    (reasoning looks cutoff-compliant, forecast still uses leaked knowledge). Authors **recommend AGAINST
    retrospective/simulated-ignorance evaluation entirely.**
- **Halawi's canonical controls** (test Qs after the cutoff, discard cutoff-spanning Qs, retrieval window
  between open and a chosen date) — later (2026) work shows these are **insufficient in practice**.
- **⇒ Hard rule for us**: a credible finance-forecasting paper must use **forward-only / live evaluation
  on future events with realized outcomes** — NOT backtests on pre-cutoff events. Reviewers know to reject the latter.

## 5. Open white space (finance-specific) + how to position
The defensible, positive-result-attainable space, given we have **event calendars + realized outcomes +
filings/transcripts/news text, but NO prediction-market odds**:

1. **A forward-only FINANCIAL-event forecasting benchmark by discrete event type** (earnings-surprise sign,
   FDA approval, M&A completion, macro-surprise direction) with realized outcomes as labels.
   - *Novel vs prior*: ForecastBench/Halawi have no discrete financial events; we slice by event type.
   - *Why finance is harder/better*: events have clean dates + objective realized outcomes + a natural
     non-market baseline (analyst consensus for earnings, base rates for FDA/M&A).
   - *Risk*: must position against the 2025 finance benchmarks (FinCall-Surprise/SAE-FiRE/Prophet Arena)
     — check their coverage first; and **leakage** (outcomes are heavily/immediately reported).

2. **Calibration of LLM forecasts BROKEN DOWN by financial event category** (is the model differently
   mis-calibrated on FDA binary catalysts vs earnings-surprise sign vs macro magnitude?).
   - *Novel*: Karkar & Chopra (2511.18394) show domain-dependence in *general* events; **no cited work
     breaks calibration down by discrete financial event category.**
   - *Risk*: leakage; need forward-only.

3. **Does the search-leakage finding extend to FINANCIAL text** (filings/transcripts/news), and is it
   *worse* in finance because outcomes are reported instantly/heavily?
   - *Novel*: the leakage audits (2602.00758) were Metaculus general-domain only — a finance-specific
     leakage audit is unclaimed and timely.

4. **A credible NON-market human/statistical baseline** for finance-event forecasting (analyst consensus,
   base rates) — PolyBench/ForecastBench lean on market/platform odds as the comparison; a finance agenda
   without odds **needs** this baseline, and establishing it is itself a contribution (open question #1).

## Open questions (verify before committing)
- Can forward-only finance-event eval be made cheap for a small team **without** prediction-market odds?
  (need a credible non-market baseline — analyst consensus / base rates).
- Does search-date-filter leakage (71–81%) extend to / worsen on financial text?
- Are LLMs differentially mis-calibrated across FDA vs earnings vs macro event types?
- **What do the 2025 finance benchmarks (FinCall-Surprise 2510.03965, SAE-FiRE 2505.14420, Prophet Arena
  2510.17638) already cover/achieve?** — the true remaining gap depends on this; check next.

## Bottom line for AlphaGap
- **Direction is viable and on-target** (AI-protagonist, text/reasoning edge, not return-prediction,
  auto-gradable via realized outcomes, currently hot).
- **Two hard constraints**: (1) **forward-only evaluation is mandatory** (retrospective is now rejectable);
  (2) **position against the 2025 finance-specific benchmarks**, not just the general ones.
- **Cheapest defensible first move**: not a full benchmark, but the **finance-event calibration breakdown**
  (#2) or the **finance-text leakage audit** (#3) — both are small, forward-only-compatible, novel vs the
  cited prior, and don't need prediction-market odds.
