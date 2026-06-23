# findata Data-Requirements Verification — procedure & traps

> **Purpose.** Before claiming a gap is `findata_native` (or that "findata data is insufficient"), VERIFY
> the data against reality with this procedure. This file exists because a triage made **five consecutive
> data-fetching errors** judging one gap's data needs from ad-hoc default calls (see §3). Authoritative
> capability map = `knowledge/FINDATA_CATALOG.md` — **consult it FIRST, every time.**
>
> Core rule: **a data claim is not valid until you have cleared the cache, passed a large `limit`, and
> measured (count, true date range, field validity).** Never infer depth from a default call.

---

## 1. The procedure (run for EVERY data object a gap needs)

For each data object the experiment needs (e.g. "10 years of earnings-call text", "daily prices",
"insider events"):

1. **Catalog first.** Find the endpoint in `FINDATA_CATALOG.md`. Note its declared `freq`, `PIT`
   (`hist` = dated history, safe to slice by as_of; `snap` = current-only = look-ahead risk), and any
   depth note. The catalog is the source of truth; this procedure confirms it for your specific need.
2. **Clear the cache** for your test symbol: `rm -rf ~/.xp/cache/findata/<SYM>`. (The client caches by
   `symbol+kind`; the cache key does NOT include params like `since`/`limit`, so a cached result will
   MASK whether your params work — see Trap C.)
3. **Call with a LARGE `limit`** (e.g. 200–1000), not the default. Default `limit` is a paging default,
   NOT the data depth (Trap B).
4. **MEASURE three things and write them down:**
   - **count** of rows returned,
   - **true date range** (`min`/`max` of the dated field) — span in years,
   - **field validity** — are the dated/key fields actually populated and non-duplicated? (Trap A)
5. **Classify PIT:** is it a dated history (`hist`, safe) or a current snapshot (`snap`, look-ahead in a
   backtest)? Snapshot endpoints used as-of a past date = look-ahead bug.
6. **List-cap vs body-fetch (Trap D):** a *list* endpoint may cap (e.g. 12), but a per-item *body* fetch
   may go far deeper. The list cap is NOT the corpus depth.
7. **Decide `findata_native`:** `true` only if EVERY needed object maps to an endpoint at the required
   **frequency, history depth, AND PIT-safety**. If any needs (a) agent trajectories / tool-logs / gold
   labels, (b) a corpus that must be generated, (c) non-US / options / tick<1min, (d) a snapshot used as
   historical PIT, or (e) **dense document history beyond the recent window** — say `false` and name the
   missing piece.

---

## 2. Measured depth table (verified 2026-06-21, cache-cleared, large limit)

**Deep (long history — real statistical power):**
| object | endpoint + how | measured depth |
|---|---|---|
| daily prices | `get_ohlc(sym,'1d',start='2004-01-01','')` | ~20 yr (5007 bars back to ~2006) |
| fundamentals (income/balance/cashflow) | `get_fundamentals_history(sym, statement=, period='quarter', limit≥200)` | **163 quarters back to 1985**; `period='fy'` → ~40 annual yrs (`annual` 400s — don't use) |
| earnings-call **full text** | `get_transcript(sym, year, quarter)` looping years | **~50–64 full bodies back to ~2009/2010 (~15+ yr), median ~7.7–9.4k words** (list `get_transcripts(limit=100)` returns ~50 — NOT a hard 12; bodies go deeper still) |
| earnings dates (clean) | `get_earnings_history(sym,limit=40)` → use **`fiscal_date`** | ~40 quarters to 2017 (⚠ use fiscal_date, NOT report_date) |
| dividends / market_cap / splits | `get_dividends`/`get_market_cap_history`/`get_splits` | multi-year historical |

**Shallow / recent-only (the real constraints):**
| object | endpoint | measured limit |
|---|---|---|
| **news** | `get_news` | **NOT a reliable history archive.** `since=` times out (15s). Default returns only a recent window whose span depends on the name's news VOLUME: high-volume names cover only **~few days** (AAPL/MSFT/NVDA), low-volume names extend to **months** (e.g. ORLY → 2026-05; `since=2026-01-01` → 2026-01-15). Uncontrollable — do NOT treat as historical news. |
| filings (substantive) | `get_filings(limit=1000)` | **hard 200-cap** (limit=1000 still returns 200). Span is **SYMBOL-DEPENDENT and often tiny** — AAPL ~2.3 yr (9× 10-K/Q), MSFT ~1 yr (4), NVDA ~11 mo (4), **JPM ~2 DAYS (0 — drowned by 424B2 prospectuses)**. Do NOT generalize a span. Full filing TEXT via `report_url` **403s** without EDGAR-compliant headers — not readily in findata. |
| transcripts **list** | `get_transcripts(limit=100)` | returns **~50** (NOT a hard 12); per-quarter bodies fetch deeper still (see Deep table) |
| key_metrics / analyst snapshots | `get_key_metrics`, `get_price_target`, `get_analyst_estimates`, `get_recommendation` | shallow (~20 periods) or `snap` (current-only, look-ahead) |
| analyst events / insider events | `get_grades`, `get_insider_transactions` | dated `hist` but ~1–1.5 yr / capped few-hundred |

**One-line takeaway:** findata is **deep on NUMERIC** (40-yr fundamentals, 20-yr prices) and **deep on
earnings-call FULL TEXT (~15+ yr, ~50–64 quarterly calls/name)**, but **shallow & unreliable on dense
documents** (news = uncontrollable recent window, substantive filings = hard 200-cap with symbol-dependent
span as small as ~2 days). "Long dense multi-document timeline" → NOT findata-native; needs EDGAR full-text
/ a news archive.

> Cross-verified by an independent re-check (2026-06-21): cache-key bug, numeric depth, report_date garbage,
> transcript depth (~50–64 bodies to 2009/2010), filings hard-200-cap + symbol-dependent span, and news
> unreliability all confirmed. The transcript depth here SUPERSEDES the earlier "list cap 12 / ~40 to 2014".

---

## 3. The traps that caused the 5 errors (check yourself against each)

- **Trap A — invalid field.** `earnings_history.report_date` is **duplicated garbage** (40 rows → 5
  unique dates clustered recent). Use `fiscal_date` or transcript `call_date`. *Always inspect uniqueness
  of the dated field before using it.*
- **Trap B — default limit ≠ depth.** `fundamentals_history` default `limit=8` looks like "only ~8
  periods / data ends 2021". Reality with `limit≥200`: 163 quarters to 1985. *Always pass a large limit.*
- **Trap C — cache masks params.** `get_news(since='2019-...')` returned the cached recent result because
  the cache key ignores `since`. *Clear `~/.xp/cache/findata/<SYM>` or call `client._get(path, **params)`
  directly to test any param.*
- **Trap D — list cap ≠ corpus depth.** `get_transcripts(limit=100)` returns ~50 (the default-12 is a
  paging default, not a cap); `get_transcript(y,q)` fetches full bodies back to ~2009. *Distinguish list
  endpoints from per-item body fetches, and pass a large limit to the list too (Trap B applies here).*
- **Trap E — judging from memory / ad-hoc calls instead of the catalog.** All of the above were avoidable
  by reading `FINDATA_CATALOG.md` first (it explicitly documents Trap B). *Catalog first, then verify.*
- **Trap F — strawman baseline hides the truth.** Separately from data: when testing whether a fancy
  method beats time/standard baselines, make sure the task isn't rigged so a trivial baseline (e.g.
  "filter by event type") wins by construction. A simple-beats-fancy result is a real finding only if the
  task is fair (see `knowledge/FAILURE_PREMORTEM.md` #15).

---

## 4. Quick verification snippet (copy-paste, cache-cleared)

```python
import sys, subprocess; sys.path.insert(0,'phase0')
subprocess.run("rm -rf ~/.xp/cache/findata/AAPL", shell=True)   # clear cache for the test symbol
import pandas as pd
from findata_adapter import load_client
c = load_client()
def measure(rows, datekey):
    rows = rows or []
    ds = sorted(pd.to_datetime(r[datekey]) for r in rows if isinstance(r, dict) and r.get(datekey))
    uniq = len(set(ds))
    print(f"  count={len(rows)} unique_dates={uniq} range={ds[0].date() if ds else None}..{ds[-1].date() if ds else None}")
# example: verify fundamentals depth (pass LARGE limit!)
measure(c.get_fundamentals_history('AAPL', statement='income', period='quarter', limit=300), 'period_end_date')
# example: bypass cache to test a param
# rows = c._get('/news/AAPL', since='2024-01-01', limit=200)   # may time out → news is recent-only
```

Run this (with a large limit, cache cleared) for each data object **before** writing `findata_native` or
"data insufficient" in any brief.
