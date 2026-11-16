# Data

Written for: an examiner or reviewer who needs to know exactly what is real
in this project and what is simulated.

## The short version

| Layer | Real or simulated | Source |
|---|---|---|
| Daily asset prices | **Real** | Kaggle NSE (1996–2021) and Yahoo Finance (2000–2026) |
| Benchmark (NIFTY 50) | **Real** | Kaggle index series spliced with `^NSEI` |
| Debt series | **Real** | NIFTY GS Composite handing off to GILT5YBEES |
| Cash returns | **Modelled** | A documented 5.5% annual accrual |
| Holding popularity priors | **Real, derived** | Big Sharks investor holdings |
| Investor profiles, holdings, transactions, goals | **Simulated** | Generated from six latent archetypes |

Every investor-level record in a demonstration is synthetic. Every price
behind it is real, with one documented exception (cash).

---

## Sources

### 1. Kaggle — NSE India Stock Data (1990–2021)

1,756 per-stock CSV files and 54 index files. Ingest produces **5.23M rows
across 2,096 symbols**, spanning 1996-01-01 to 2021-07-01.

Used for: the deep index history (NIFTY 50 from 1990, 18 sector indices, the
NIFTY GS government-securities family, INDIA VIX), the breadth needed for
sector work, and as an independent cross-check on the adjusted series.

**Not used for portfolio return calculations.** See the next section.

### 2. Yahoo Finance (`query1.finance.yahoo.com`, no key)

One cached fetch per symbol into `data/external/yahoo/`. Supplies
`adj_close`, adjusted for splits, bonuses and dividends, for 57 symbols from
2000 to the present.

Used for: every tradeable asset's price series, and for the two things the
Kaggle set does not contain at all — gold and ETFs.

### 3. Kaggle — Big Sharks (Investors) Portfolio

2,912 holdings rows across 50 investors and 1,169 stocks.

The PRD treats this as a schema reference. It does more here. After mapping
company names onto NSE symbols — **72% matched**, covering 48 of the 51 MVP
equity names — it yields an empirical distribution of which Indian stocks
investors actually concentrate in. Synthetic holdings are drawn from that
distribution rather than uniformly, so the cohort looks like real Indian
portfolios instead of a random draw from the NIFTY 50.

**Caveat carried into every use:** these are large and institutional
investors, not retail ones. Their *holding preferences* are a defensible
prior for which large-cap names are widely held. Their *position sizes* are
not, and are used only as a loose shape for the concentration distribution.

### 4. FinRL (AI4Finance)

Methodological reference only for the train/validation/test split pattern.
No code or data is taken from it.

---

## The corporate-action problem

**This is the most consequential data finding in the project.**

The Kaggle NSE closing prices are **not adjusted for corporate actions**.
A 1:1 bonus issue halves the raw price overnight, so the series records a
50% crash that never happened:

| Symbol | Date | Event | Raw recorded return |
|---|---|---|---|
| RELIANCE | 2017-09-07 | 1:1 bonus | **−50.3%** |
| TCS | 2018-05-31 | 1:1 bonus | **−50.5%** |

There are **78 such phantom moves** in the 51-name MVP universe alone.

The source's `Prev Close` column was checked as a possible fix and carries
no adjustment information — on RELIANCE's ex-date it simply repeats the
previous row's close.

### What it would have cost

Stage 03b recomputes the headline risk metrics both ways over 2012–2021 and
records the difference. Across **24 of 51** symbols:

| Metric | Median error | Worst case |
|---|---|---|
| Annualised volatility | overstated by 4.8 pp | **15.2 pp** |
| Maximum drawdown | overstated by 7.9 pp | **63.8 pp** |
| Sharpe ratio | understated by 0.22 | 0.73 |

**15 symbols flip the sign of their Sharpe ratio.** INFY reads a −87.9%
maximum drawdown instead of −36.5%, and a Sharpe of −0.30 instead of +0.43
— a profitable holding judged a loss-maker.

Every one of those numbers would have looked entirely plausible on a
dashboard.

### The resolution

Yahoo's `adj_close` handles the same RELIANCE bonus correctly (−0.56% on the
ex-date) and spans 2000–2026, covering the whole simulation window. It is
therefore the price source for every tradeable asset.

---

## Splicing, and its two standards

Two joins happen in stage 03, held to deliberately different bars.

**`same_instrument`** — the two sources carry the identical series.
Gate: return correlation ≥ 0.95, level-ratio drift < 2%.

> NIFTY 50: Kaggle index (1990–2021) joined to `^NSEI` (2007–2026).
> Correlation **1.0000** over 3,374 overlapping days, scale factor exactly
> 1.0, zero drift. An exact join.

**`proxy_handoff`** — one instrument takes over from a related but distinct
one. Gate: correlation ≥ 0.80, volatility within 2×. Recorded as an
instrument change, never as a continuation.

> Debt: NIFTY GS Composite (2012–2021) handing off to GILT5YBEES (2021–2026).
> Correlation **0.858**, volatility 3.1% against 4.3%.

LTGILTBEES was evaluated first and **rejected**: 12.7% volatility, three
times the index it would replace, and correlation of only 0.30. The gate
caught it.

---

## Validation gates

The pipeline aborts rather than writing data that looks plausible and is
wrong:

- No spliced daily move may exceed 50%.
- A `same_instrument` splice must clear 0.95 correlation and 2% drift.
- A `proxy_handoff` must clear 0.80 correlation and a 2× volatility band.
- Feature-table splits must not overlap in time.
- No target column may appear among the features.

### A defect these gates caught

NIFTYBEES, BANKBEES and GOLDBEES each sit at a tenth of their price (a
hundredth for GOLDBEES) for exactly two sessions in December 2019, then snap
back. A real split does not revert; this is a feed defect. Only reverting
round trips are repaired, so a genuine one-way jump still fails the build.

---

## Asset universe

58 priced assets, in `data/reference/universe.csv`.

| Class | Count | Notes |
|---|---|---|
| equity | 51 | NIFTY 50 constituents plus TVSMOTOR and TRENT |
| etf | 3 | NIFTYBEES, JUNIORBEES, BANKBEES |
| gold | 1 | GOLDBEES — the only gold series available anywhere in the sources |
| debt | 1 | Spliced GS Composite → GILT5YBEES |
| cash | 1 | Modelled at 5.5% |
| index | 1 | NIFTY 50 benchmark |

**Two symbols are marked delisted rather than spliced across a
discontinuity.** HDFC merged into HDFCBANK in July 2023; TATAMOTORS demerged
into TMPV in October 2025 and the successor is not price-continuous with it.
Their Kaggle history remains available for historical analysis, but neither
can be held today.

**Why cash is modelled.** LIQUIDBEES and similar liquid ETFs pin their NAV
at a constant and pay their return out as dividends, so their *price* series
shows a flat line. Reading that as "cash returns nothing" would be wrong, so
cash is modelled at an explicit documented rate instead.

Resulting figures over 2012–2026, all realistic: NIFTY 50 10.9% return at
15.2% volatility, gold 9.4% / 14.7%, gilt 7.1% / 3.9%.

---

## The synthetic investor cohort

10,000 investors, 1.25M investor-months, simulated against the real price
panel. Generated in about five seconds, because the simulation is vectorised
across investors as an (investors × assets) matrix rather than looped.

Six latent archetypes: conservative saver, balanced investor, aggressive
growth, active trader, goal-focused SIP, dormant holder.

Three choices exist specifically to keep the later evaluation honest:

1. **Known archetypes.** Clustering can be scored with Adjusted Rand Index
   against the true generating label, not just silhouette. Silhouette says
   clusters are *tight*; ARI says they are the *right* clusters.
2. **Overlapping archetypes.** Cleanly separated blobs would flatter the
   clustering model into a score that says nothing.
3. **Deliberate risk mismatches.** 18% of investors are given a stated risk
   tolerance that contradicts how they invest, because detecting that
   divergence is a product goal and a cohort where the two always agree
   makes the problem trivial.

Returns are **time-weighted** throughout: a month's contribution is removed
before dividing by the opening value. Without that step a steady contributor
in a flat market would look like a strong performer, and the entire
behavioural feature set would rest on a false signal.

### Injected anomalies

3,556 anomalous months across 1,200 investors (0.28%), balanced across five
types: allocation shock, concentration spike, turnover spike, panic sell,
dormancy break.

They are applied to recorded snapshots rather than threaded through the
simulation, so each one's location and type are known exactly — which is
what makes real precision and recall measurable.

**They are also deliberately unambiguous.** Detection scores against them
are an upper bound on performance against real, subtler behaviour.

### Does the cohort behave like a market?

| Check | Result |
|---|---|
| Archetypes separate on behaviour | conservative savers 15% equity / 14% turnover; aggressive growth 72% / 58% |
| Cohort return and volatility | 13.8% at 12.4%, skew −0.70 |
| Worst months | cluster in March 2020 |

That last row is the strongest validation available: the real NIFTY fell 23%
that month and individual large caps up to 46%, so a 76%-equity portfolio
losing 40% is correct behaviour, not a defect.

---

## Privacy and reproducibility

- No real user financial data is used anywhere.
- Passwords are bcrypt-hashed; the API never returns a hash.
- Raw data stays outside the repository; `data/` is gitignored except
  `reference/`.
- Every pipeline stage writes evidence to `ml/reports/`, so any figure in
  this document can be traced to the run that produced it.
- Random seeds are fixed at 42 throughout.
