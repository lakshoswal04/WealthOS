# Swing-trading models

Models that rank NIFTY 100 stocks for the next two trading weeks, forecast
their volatility, read the market's regime, and turn all three into a
risk-profiled paper basket. Every number below comes from a report in
`ml/reports/` (`swing_*.json`). The Swing Lab page (`/analysis/swing-lab`)
renders the same reports.

> Research signals for paper trading. Not investment advice. Past
> out-of-sample results do not promise future returns.

## The questions, and the models that answer them

| Question | Model | Stage |
|---|---|---|
| Which stocks will beat the others over the next 10 sessions? | Ensemble of LightGBM LambdaRank, LightGBM regression and ridge (mean of daily ranks) | `p15_train_ranker` |
| What range of returns is likely? | LightGBM quantile models (10/50/90%), conformally calibrated | `p15_train_ranker` |
| How much will each stock move? | HAR-RV (served), GARCH(1,1) and LightGBM, against trailing volatility | `p16_train_volatility` |
| Is the market calm, normal or stressed? | 3-state Gaussian hidden Markov model, filtered probabilities | `p17_train_regime` |
| Does deep learning do better? | LSTM, GRU, temporal CNN, PatchTST-style transformer, on identical folds | `p18_train_deep` |
| What should a given investor hold? | Inverse-volatility sizing, volatility target and regime exposure per risk profile | `p19_swing_portfolio` |

Run all of it with `make swing` (about 30 minutes on a laptop; no GPU needed,
though the networks use Apple's MPS if present). `make swing-quick` is a smoke
run.

## Data

* **Prices.** Yahoo daily OHLCV for today's NIFTY 100, adjusted for splits and
  dividends, 1995 to now (median 24 years per stock), plus NIFTY 50, NIFTY
  Bank and India VIX (from 2007 and 2008). Stage 13, `history_daily.parquet`.
  The live app keeps its own two-year file, refreshed after each close.
* **Features** (33, `wealthos_core/swing_features.py`, shared by training and
  serving):
  * Returns over 1 week to 12 months, 12-1 month momentum, distance from the
    52-week high and low, gaps to the 20/50/200-day averages.
  * RSI, MACD, ATR, realised and downside volatility, volatility of
    volatility.
  * Beta and stock-specific volatility against NIFTY.
  * Volume surge, turnover trend, illiquidity, biggest daily jump, skew,
    1-month return against the stock's sector.

  Each is ranked across stocks every day. Six market features (NIFTY trend
  and volatility, VIX level and change, breadth, cross-stock dispersion) tell
  the model which regime it is ranking in.
* **Target.** The return from the **next session's open** to the close ten
  sessions later, minus that day's universe average.
* **Fundamentals are not features.** Yahoo only has today's P/E and ROE, so
  using them in 2015 would leak the future.

### Survivorship bias, measured

A list of today's index members is a list of winners. Equal-weight books
from 2013, after costs:

| Eligible stocks each day | Equal-weight CAGR | 12-1 momentum top-10 CAGR | Momentum's edge |
|---|---|---|---|
| All of today's NIFTY 100 | 23.0% | 32.5% | +9.5 pts |
| Top 70 by traded value at the time | 19.2% | 23.8% | +4.6 pts |
| **Top 60 by traded value at the time (used)** | **17.6%** | **20.9%** | **+3.3 pts** |
| Top 50 by traded value at the time | 17.0% | 17.1% | +0.0 pts |
| *NIFTY 50 price index, same years* | *11.5%* | | |

Restricting each date to stocks that were large and liquid *at the time*
removes most of momentum's apparent edge. That edge came from buying stocks
that later grew into the index. The rest of the bias cannot be removed
without NSE's historical constituent lists, which cannot be fetched
automatically. So the models are judged by their **margin over the
equal-weight book of the same universe**, which carries the same remaining
bias, not by absolute return.

## Validation

* **Walk-forward, purged, embargoed.** For each test year from 2013 to 2026, a
  model is trained only on earlier data.
  * Purge: training rows whose 10-day label would reach into the test year
    are dropped.
  * Embargo: a further 5 sessions are dropped after that.
* **Tuning before testing.** Optuna (30 trials) chose the LightGBM settings on
  2011–2012 only, and they were frozen before 2013.
* **Every configuration counts.** 42 were looked at:
  * the 30 tuning trials;
  * 4 candidate models;
  * 8 score-smoothing variants, tried and rejected.

  The **deflated Sharpe ratio** (Bailey and López de Prado) raises the bar to
  what the best of 42 skill-less strategies would show.
* **Costs.**
  * STT 0.1% each side.
  * Stamp duty 0.015% on buys.
  * Exchange and SEBI fees with GST.
  * Slippage 0.05% a side.

  About 0.32% a round trip.
* **The book.**
  * Top 10 names, equal weight, rebuilt every 5 sessions at the next open.
  * Names already held are kept while they stay in the top 20.
* **Tests that look for leaks.** `packages/wealthos_core/tests/test_swing.py`
  perturbs prices after a date and checks that nothing computed for that date
  moves. This covers the features, the liquidity filter and the regime
  filter.

## Results (out of sample, 2013 to November 2026, after costs)

### Stock ranker

| Model | Rank IC | t | Hit rate | CAGR | Sharpe | Max drawdown | Deflated Sharpe |
|---|---|---|---|---|---|---|---|
| **Swing ensemble (deployed)** | **0.033** | **3.7** | **51.1%** | **25.4%** | **1.27** | **−33%** | **0.99** |
| LightGBM LambdaRank | 0.027 | 2.9 | 50.9% | 26.5% | 1.16 | −45% | 0.97 |
| LightGBM regression | 0.033 | 3.6 | 51.2% | 20.3% | 1.04 | −42% | 0.95 |
| Ridge regression | 0.025 | 2.7 | 50.7% | 19.5% | 1.08 | −34% | 0.96 |
| 12-1 momentum (baseline) | 0.014 | 1.1 | 50.7% | 20.9% | 0.92 | −38% | 0.89 |
| 1-week reversal (baseline) | 0.013 | 1.2 | 50.3% | 11.4% | 0.48 | −49% | 0.46 |
| Random (baseline) | −0.001 | −0.1 | 50.0% | 3.3% | 0.17 | −59% | 0.11 |
| *Equal-weight universe* | | | | *17.6%* | *0.98* | *−38%* | |
| *NIFTY 50 (price index)* | | | | *11.5%* | *0.71* | *−38%* | |

* **Rank IC** is the daily correlation between a model's ranking and what
  happened. Its t-statistic is corrected for the overlap between
  consecutive 10-day labels.
* **Hit rate** is the share of stocks placed on the right side of the day's
  median. Around 51% is what a real market edge looks like. The top-decile
  picks rose over their 10 sessions 54% of the time.
* **The deployment gate passed:**
  * IC above zero and above momentum;
  * CAGR above equal-weight after costs;
  * drawdown no worse than 1.2 times equal-weight's.
* **The edge is not steady.** IC was highest in 2013–2014 (0.10, 0.07), near
  zero in 2017, 2020 and 2022, and negative so far in 2026 (−0.024).
* **Robustness.** With slippage tripled to 0.15% a side, the ensemble still
  returns 21.8% a year. On stocks with ten years of history (the least
  survivorship-affected), IC is 0.023.

### Ranges

Raw quantile models covered between 65% and 81% of outcomes depending on the
year, too narrow in most years. After conformal calibration on the year
before each test year, out-of-sample coverage is **80.3%** against the 80%
target. Individual years range from 75% to 87%.

### Volatility

| Model | QLIKE (lower is better) | R² of log vol | Mean abs. error |
|---|---|---|---|
| Trailing 1-month volatility | 0.473 | 0.07 | 10.6 pts |
| **HAR-RV (served)** | **0.370** | 0.17 | 9.7 pts |
| GARCH(1,1) (best QLIKE) | 0.363 | 0.06 | 10.6 pts |
| LightGBM | 0.378 | 0.27 | 9.0 pts |

* **All three beat the naive forecast** by about 22%.
* **Why HAR is served:** GARCH needs per-stock state and refits, so serving
  uses HAR, which is nearly as good.

### Regime

| Filtered state | Share of days | NIFTY vol, next 10 sessions | NIFTY return, next 10 sessions |
|---|---|---|---|
| Calm | 74% | 12% | +0.2% |
| Normal | 20% | 17% | +0.9% |
| Stress | 6% | 25% | +2.1% |

* **What it does well:** it identifies turbulent markets.
* **What it doesn't do:** stress was followed by rebounds on average, so it
  is a **risk dial, not a timing signal**.
* **The overlay** cuts the top-10 book's worst drawdown from −33% to −25% but
  its return from 25.4% to 18.7%.
* **How profiles use it:** conservative profiles use it fully; aggressive
  ones barely do.

### Deep learning against gradient boosting

| Model | Rank IC | t | CAGR | Sharpe | Max drawdown |
|---|---|---|---|---|---|
| **LightGBM swing ensemble (deployed)** | 0.033 | 3.7 | **25.4%** | **1.27** | **−33%** |
| Temporal CNN | 0.037 | 3.6 | 22.4% | 1.14 | −39% |
| LSTM | 0.025 | 2.3 | 20.2% | 1.03 | −35% |
| GRU | 0.020 | 2.0 | 16.0% | 0.77 | −40% |
| Transformer (PatchTST-style) | 0.018 | 1.8 | 15.6% | 0.84 | −34% |
| Ensemble + temporal CNN | **0.040** | **4.1** | 24.7% | 1.25 | −37% |

* **Inputs and schedule.** The networks read 60 sessions of the same
  features. They were retrained every two test years, so they are never newer
  than the LightGBM model they are compared with.
* **The result.** The temporal CNN ranks slightly better than LightGBM, and
  blending the two gives the best IC. Neither made a better portfolio after
  costs, so the LightGBM ensemble stays deployed.
* **Chronos** (a pre-trained foundation model) is an optional baseline and
  was not run.

### Risk profiles

These use the same sizing code as the live swing plan.

| Profile | Names | Per-stock cap | Vol target | CAGR | Volatility | Sharpe | Max drawdown | Avg invested |
|---|---|---|---|---|---|---|---|---|
| Conservative | 10 | 12% | 12% | 7.0% | 7% | 0.97 | −16% | 43% |
| Moderate | 8 | 18% | 18% | 12.3% | 14% | 0.91 | −31% | 75% |
| Aggressive | 6 | 25% | 25% | 16.3% | 18% | 0.92 | −44% | 92% |

* **Cash earns nothing** in these backtests; a real account would earn a
  liquid-fund rate. The low-exposure profiles are therefore understated.
* **Concentration** gives the aggressive profile a deeper drawdown than the
  plain top-10 book.

## In the app

* **Market → Model picks** (`/market/model-picks`)
  * A ranked table: score, 80% range, volatility, the stop and target for the
    user's profile, and the three features that drove each score (SHAP).
  * The regime banner and the model's out-of-sample record.
  * A **swing plan** builder that places paper orders only after the user
    confirms.
* **Ideas → Model** and the chart's AI panel show the same signals.
* **AI chat tools:** `get_model_signals`, `get_market_regime` and
  `propose_swing_plan`. The assistant is told to give ranges and to quote the
  out-of-sample record.
* **Forward test** (Swing Lab)
  * From the first day the models ran on a server, every model's scores are
    recorded once and never recomputed (`forward_scores`).
  * They are replayed against prices that arrive later. This is the only
    test the models cannot have been tuned on.
  * It began on 25 November 2026 and needs months before it means much.
* **Freshness**
  * Signals use only completed sessions. A bar is used only if the price
    file was written after that day's 16:00 IST close.
  * The daily file refreshes itself after each close.

## Limits

* **Survivorship.** The bias is mitigated, not removed (see above).
* **Dividends.** Stock prices include dividends but NIFTY does not, so NIFTY
  is a secondary benchmark.
* **Edge size.** The edge is modest, uneven across years, and smaller
  recently.
* **Not in the backtests:** taxes, depository charges per sale, the impact of
  larger orders, and short selling (the books are long-only).
* **Paper only.** No order reaches a broker.
* **Regulation.** Giving personalised advice to real users would need SEBI
  Investment Adviser registration.
