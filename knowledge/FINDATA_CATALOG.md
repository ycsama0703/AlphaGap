# findata Capability Catalog — authoritative data reference

> **Purpose.** The single source of truth for *what data findata can actually provide*. Every time a gap's
> data needs are judged (DESIGN scoring `findata_native`, TEST routing, experiment authoring), compare the
> gap's `## 3. Data Requirements` against THIS file — do not judge from memory. (This file exists because a
> from-memory judgment wrongly assumed "findata = price only" and refuted a gap on a too-thin proxy.)
>
> Source of truth: `~/.xp/skills/<id>/lumid-findata/skills/client.py` (797 lines, ~67 `get_*` endpoints).
> Warehouse: `kv.run:5000`, **7,851 US-equity symbols**, Lumid PAT auth. Last audited: 2026-06-05.
> Access in TEST: `exp.data(sym, as_of, kind="ohlc"|"fundamentals")` or the `generic("get_<x>", sym, as_of)`
> passthrough to ANY endpoint below (still PIT-truncated for dated lists).

---

## 0. READ FIRST — coverage & hard limits (the stuff that bites)

- **Universe = US equities only (~7,851 symbols).** No non-US, no FX/rates instruments as symbols, no
  options/futures chains (COT is the only derivatives-positioning surface). ETF metadata yes, per-name only.
- **No research-grade PIT panel (no CRSP/Compustat).** Survivorship/restatement bias is NOT handled for you.
- **No Fama-French / factor-return files.** You must **construct** FF/characteristic factors yourself from
  the cross-section (see §6). "needs FF factors" is NOT a blocker — it's a build step.
- **Most endpoints are PER-SYMBOL.** A cross-sectional panel = loop over N symbols = N HTTP calls
  (cached). Budget for that; there is no bulk-panel endpoint except `get_quotes` (≤100 latest ticks).
- **PIT vs latest-snapshot — look-ahead risk.** Some endpoints are *historical lists* (safe to slice by
  `as_of`); others return a **current snapshot** (e.g. `get_fundamentals` "latest", `get_price_target`,
  `get_analyst_estimates`, `get_esg_ratings`) which embeds today's info — using them in a backtest as-of a
  past date is look-ahead. The harness PIT-truncates *dated list* rows only; snapshot endpoints it cannot
  fix. Column **PIT** below flags this: `hist` = dated history (safe), `snap` = current-only (look-ahead risk).
- **History depth varies — ⚠️ DEFAULT `limit` IS SMALL, IT IS *NOT* THE DATA DEPTH.** `ohlc` with `start=` →
  long daily history. Statement/ratio lists **default to a few periods** (`get_fundamentals_history` default
  `limit=8`) — **this is a paging default, not the available history.** NEVER infer "the data is shallow" from a
  default call; **always pass a large `limit` and measure.** Measured truth (2026-06): `get_fundamentals_history`
  returns **~160 quarterly statements per name back to 1985** (income/balance/cashflow), and `period="fy"` → ~40
  annual years — i.e. **deep 40-year fundamentals exist**. (A prior triage wrongly concluded "fundamentals only
  reach ~2021 / 3–8 rows" by reading the default `limit=8` — exactly the trap this bullet warns against.)
  `period=quarter|fy` (NOT `annual` — that 400s). Intraday = 1min/5min only.
- **`get_*` returns `None`/`[]` on failure or unknown symbol** (never raises) — always None-guard.

**Decision rule for a gap's `findata_native`:**
`true` only if every data object the experiment NEEDS maps to an endpoint below **at the required frequency,
history depth, and PIT-safety**. If it needs (a) text/agent trajectories with *labels*, (b) a corpus that must
be *generated* (factor expressions), (c) non-US / options / tick<1min, or (d) a snapshot endpoint used as
historical PIT — then it is **not** findata-native as-is; say so and name the missing piece.

---

## 1. Price & corporate actions  (the core, fully historical)

| endpoint | args | returns (key fields) | freq | PIT | good for |
|---|---|---|---|---|---|
| `get_ohlc` | symbol, interval=1d, start, end | `{symbol, interval, count, bars:[{ts,o,h,l,c,v}]}` | 1min/5min/1d | hist | returns, momentum, volatility, reversal, beta, liquidity(vol) |
| `get_quote` / `get_quotes` | symbol / [symbols≤100] | `{symbol,ts,price,bid,ask,change_pct,...}` | realtime (5s TTL) | snap | live ticks only |
| `get_dividends` | symbol, limit | `[{date,amount,adj_amount,yield_pct,frequency,...}]` | event | hist | dividend yield, total return |
| `get_splits` | symbol, limit | split history | event | hist | adjustment sanity |
| `get_market_cap_history` | symbol | `[{date, market_cap}]` | daily | hist | **size factor**, weighting |
| `get_shares_float` | symbol | float shares | snap | snap | float-adjusted size |
| streams | `stream_quotes/news/kol_tweets` | SSE generators | realtime | — | live loops only |

## 2. Fundamentals & statements  (historical → safe for PIT panels)

| endpoint | args | returns | freq | PIT | good for |
|---|---|---|---|---|---|
| `get_fundamentals_history` | symbol, statement=income\|balance\|cashflow, period=quarter\|fy\|all, **limit=8 (default — RAISE IT)** | historical statement lines — **~160 quarters back to 1985** w/ `limit≥200` (use `period=fy` for ~40 annual yrs; `annual` 400s) | quarterly/annual | hist | value, quality, accruals, growth inputs, **statement-evolution sequences** |
| `get_fundamentals` | symbol | latest combined snapshot | — | **snap** | current only — NOT for backtest as-of |
| `get_key_metrics` | symbol | `[{period, pe, pb, ps, ev_ebitda, debt_to_equity, roe, ...}]` | per period | hist* | **value (pe/pb/ps), quality (roe), leverage** |
| `get_ratios` | symbol | financial ratios per period | per period | hist* | margins, turnover, liquidity ratios |
| `get_financial_growth` | symbol | `[{period, revenue_growth, eps_growth, ...}]` | per period | hist* | **growth factor** |
| `get_financial_scores` | symbol | piotroski-style scores per period | per period | hist* | quality composite |
| `get_earnings_quality` | symbol | earnings-quality per period | per period | hist* | accruals/quality |
| `get_owner_earnings` | symbol | owner-earnings series | per period | hist* | valuation |
| `get_enterprise_value` | symbol | EV series | per period | hist* | EV-based value |
| `get_dcf` | symbol | DCF fair-value series | per period | hist* | mispricing proxy |
| `get_earnings_history` | symbol, limit | realized EPS vs estimate | per report | hist | earnings surprise (SUE), PEAD |

`hist*` = list carries per-period dates; verify the period date is ≤ as_of before use (PIT-slice it).

## 3. Analyst & expectations

| endpoint | returns | PIT | good for |
|---|---|---|---|
| `get_analyst_estimates` | forward EPS/revenue estimates | snap | expectation level (current) |
| `get_price_target` | `{target_consensus,high,low,analysts,updated_at}` | snap | target-implied return (current) |
| `get_grades` | `[{date,firm,grade,action}]` | hist | upgrade/downgrade events, revision momentum |
| `get_recommendation` | `[{period,strong_buy,buy,hold,sell,strong_sell}]` | hist | consensus rating drift |
| `get_earnings_calendar` | `[{symbol,report_date,eps_estimated,eps_actual,revenue_*}]` | hist/fwd | event windows, surprise |

## 4. Ownership & insider/fund flows

| endpoint | returns | PIT | good for |
|---|---|---|---|
| `get_holders` | top 13F institutional holders `{institution_name,shares,market_value}` | hist (13F lag) | institutional ownership/concentration |
| `get_fund_ownership` / `get_funds_disclosure` | fund-level holdings/disclosures | hist | crowding, fund flows |
| `get_insider_transactions` | Form-4 `[{date,insider_name,transaction_type,shares,price,value}]` | hist | insider-trading signal |
| `get_insider_sentiment` / `get_insider_statistics` | aggregated insider index / rolling stats | hist | insider sentiment factor |
| `get_gov_trades` | political/congressional trades | hist | alt signal |

## 5. Text & sentiment  (the corpus for NLP / LLM-agent gaps)

| endpoint | returns | good for |
|---|---|---|
| `get_filings` | `[{accession_no, form, filed_date, report_url, filing_url}]` | SEC filing **links** (10-K/10-Q) — the document set for agent/NLP gaps (body must be fetched from url) |
| `get_transcripts` / `get_transcript(year,quarter)` | list of calls / **full transcript body** | earnings-call NLP, retrieval/citation gaps (real text!) |
| `get_news` | `[{published_at,publisher,headline,summary,url,category}]` | news-flow, event study, headline NLP |
| `get_symbol_sentiment` / `get_social_sentiment` | news/social sentiment series | sentiment factor |
| `get_kols` / `get_kol_tweets` | curated KOL roster / tweets | social-signal gaps |

> **Note for agent/NLP gaps:** findata gives the *raw documents* (filings links, transcript bodies, news),
> but NOT: multi-step agent **trajectories**, tool-call logs, or **gold labels** (citation-correct,
> tool-correct, evidence-sufficient). Those must be built. So "agent" gaps are *document-available* but
> *harness-and-label-blocked* — `findata_native: false`, blocker = "agent harness + labels".

## 6. Macro / global  (not per-symbol)

| endpoint | returns | good for |
|---|---|---|
| `get_treasury_rates(limit)` | treasury yield curve history | **risk-free rate**, term/level signals |
| `get_economic_indicators()` | macro indicator series (GDP, CPI, unemployment, ...) | regime/state variables |
| `get_economic_calendar(limit)` | scheduled macro releases | event windows |
| `get_cot(symbol)` | Commitments-of-Traders positioning | the only futures-positioning surface |

> No VIX-as-symbol; proxy market vol from cross-sectional `ohlc` or an index ETF's `ohlc`.

## 7. Company / ETF / events / ESG  (mostly snapshot or low-freq)

`get_executives, get_employee_count, get_peers, get_supply_chain, get_governance_compensation,
get_patents, get_lobbying, get_usa_spending, get_visa_applications` (company descriptors, mostly snap/annual) ·
`get_etf_info, get_etf_holdings, get_etf_sector_weightings, get_etf_country_weightings, get_etf_exposure`
(ETF composition) · `get_esg_ratings(snap)/get_esg_historical(hist)/get_esg_disclosures` ·
`get_ipos, get_mergers_acquisitions, get_acquisitions, get_fda_calendar, get_symbol_changes,
get_exchange_holidays` (event calendars).

---

## 8. Deriving common research inputs (so judging is concrete, not vibes)

| research input a gap asks for | how to build it from findata | endpoints |
|---|---|---|
| momentum / reversal | trailing returns from daily bars | `get_ohlc` |
| volatility / idio-vol | rolling std of daily returns (idio = residual vs market) | `get_ohlc` |
| size | log market cap | `get_market_cap_history` |
| value | pb / pe / ps / ev_ebitda | `get_key_metrics`, `get_ratios` |
| quality | roe, margins, financial_scores, earnings_quality | `get_key_metrics`, `get_financial_scores` |
| growth | revenue/eps growth | `get_financial_growth` |
| risk-free rate | short treasury yield | `get_treasury_rates` |
| **market / FF / characteristic factors** | **construct**: cross-sectional sorts on the chars above → long-short factor returns; market = cap-weighted universe or broad ETF | loop `get_ohlc`+chars |
| earnings surprise (SUE/PEAD) | actual vs estimated EPS | `get_earnings_history`, `get_earnings_calendar` |
| document corpus (10-K, calls) | filing urls + transcript bodies | `get_filings`, `get_transcript` |

---

## 9. Judging checklist (run this for every gap before declaring findata-native / routing)

1. List each **data object** the gap's §3 needs (object, frequency, history span, PIT requirement).
2. For each, find the endpoint(s) above. If derived (e.g. FF factor), note the build recipe (§6/§8).
3. Flag any object that is: text-**with-labels** · a corpus to **generate** · **non-US/options/tick** ·
   a **snapshot** endpoint used as historical PIT · deeper history than available.
4. Verdict:
   - all objects covered (incl. constructible factors) → **findata_native: true**, name the endpoints.
   - some require a build (agent harness, label set, expression corpus) → **false**, name the *exact*
     missing piece (not "no data" — be specific: "needs gold citation labels", "needs factor-expr corpus").
5. Record the endpoint list in the experiment registration so the trace shows what was (or would be) fetched.

> Anti-pattern that motivated this file: judging "factor/asset-pricing gap → only price exists → can't test".
> Wrong. Price + fundamentals + macro are all here; FF factors are constructible. The genuinely blocked
> classes are **agent/NLP-with-labels** and **generate-a-corpus**, not "anything beyond price".
