# Models and results

Written for: an examiner assessing whether the reported numbers mean what
they appear to mean.

Every figure here comes from `ml/reports/`, measured on a chronologically
held-out test period that no model saw during training.

---

## 1. Investor behaviour clustering

**K-Means over 15 behavioural features, k = 7 selected by silhouette.**

Features are behavioural only — allocations, turnover, trade frequency,
volatility, drawdown, concentration, contribution consistency. Age and
income are deliberately excluded: the goal is to group investors by how they
*behave*, and including demographics would let the model cluster on who they
are instead.

### Results

| Measure | Value | What it says |
|---|---|---|
| Silhouette | 0.371 | clusters are reasonably tight |
| Davies–Bouldin | 1.05 | — |
| Bootstrap stability (ARI) | **0.957** | the partition reproduces under resampling |
| **ARI vs true archetype** | **0.947** | the clusters are the *right* ones |
| NMI vs true archetype | 0.931 | — |

The fourth row is the one that matters, and it is only measurable because
the cohort is synthetic and the generating label is known. A model can score
well on silhouette while recovering nothing real; ARI corrects for chance
agreement and says whether the structure found is the structure present.

### Against other algorithms

| Algorithm | Silhouette |
|---|---|
| **K-Means** | **0.371** |
| Agglomerative | 0.356 |
| Gaussian Mixture | 0.336 |

K-Means was not assumed; it won.

### The clusters

Named from fitted centroids *after* training, never decided in advance.

| Cluster | Name | Share | Dominant archetype |
|---|---|---|---|
| 4 | Broadly diversified investor | 25.6% | balanced investor |
| 2 | Growth-oriented investor | 19.4% | aggressive growth |
| 3 | Capital preserver | 17.9% | conservative saver |
| 5 | Systematic index accumulator | 16.1% | goal-focused SIP |
| 6 | High-turnover trader | 12.0% | active trader |
| 1 | Passive holder | 6.8% | dormant holder |
| 0 | Balanced investor | 2.3% | mixed |

Six of seven map cleanly onto one generating archetype.

---

## 2. Portfolio anomaly detection

**PyTorch autoencoder, 24 features → 6-dimensional bottleneck.**

Trained only on months labelled normal, so the model never learns to
reproduce the behaviour it is meant to flag. The bottleneck is deliberately
narrow: a high-capacity network reconstructs anomalies as faithfully as
normal rows, which defeats the whole approach.

The threshold is chosen on validation and applied unchanged to test. Tuning
it on test would inflate every number below.

### Results on the untouched test period

| Measure | Autoencoder | Isolation Forest baseline |
|---|---|---|
| Precision | **0.796** | 0.178 |
| Recall | **0.887** | 0.638 |
| F1 | **0.839** | 0.279 |
| **PR-AUC** | **0.935** | 0.326 |
| ROC-AUC | 0.9995 | — |
| False-positive rate | **0.0008** | — |

PR-AUC is the headline rather than ROC-AUC: at 0.3% positives, ROC-AUC is
flattering by construction.

The baseline exists so the deep model has to earn its place. It does, by a
margin of 0.61 PR-AUC.

### By anomaly type

| Type | Recall (baseline) | Recall (now) |
|---|---|---|
| Concentration spike | 1.000 | 1.000 |
| Turnover spike | 1.000 | 1.000 |
| Panic sell | 0.990 | 1.000 |
| Allocation shock | 0.965 | 0.968 |
| **Dormancy break** | **0.467** | **0.969** |

The weak case used to be explained here as a signal that genuinely resembles
lumpy saving. That explanation was wrong, and the way it was wrong is worth
recording.

Measurement contradicted it: `contribution_ratio` for a dormancy break
spanned 0.30 to 0.79 against a maximum of 0.2006 across 289,000 normal test
rows. The classes did not overlap. Two defects produced the 0.467.

**The score diluted the signal.** Reconstruction error was reduced by a flat
mean over 24 features, which assumes they are equally hard to reconstruct.
They are not, so a feature with large ordinary noise dominated and a clean
deviation in two well-reconstructed features was averaged away. Per-feature
z-scoring against the error distribution on normal training rows fixes it.
Measured on the unchanged model and unchanged data, that change alone took
F1 from 0.8392 to 0.8500 and dormancy recall from 0.4667 to 0.5795. Note
that a plain per-feature maximum was *worse* than the mean (F1 0.7914,
dormancy 0.3897): an unnormalised max returns whichever feature is hardest
to reconstruct, which is largely the same feature every row. The improvement
is in the normalisation, not the reducer. Full table in
`ml/reports/anomaly_aggregation_study.json`.

**The generator never created the anomaly.** `inject_anomalies` wrote the
large contribution and left the preceding months exactly as simulated — still
contributing, still trading — so a row labelled `dormancy_break` was a large
contribution and nothing more. It now zeroes three to six months of
contributions, trades and turnover first, and three lag features make that
silence visible: `months_since_contribution`, `delta_contribution_ratio` and
`recent_funding_rate`. The last deliberately excludes the current month,
because a dormancy break *is* a funded month and including it would leak the
label.

The jump from 0.5795 to 0.969 is therefore mostly the data fix. That is a
correction to mislabelled data, not a gain in modelling skill, and the two
should not be added together.

### What limits this number

The anomalies are injected and deliberately unambiguous. **These scores are
an upper bound on performance against real, subtler behaviour.**

---

## 3. Wealth trajectory forecasting

This is where the methodology matters more than the model.

### What is predicted, and why not the obvious thing

Not next month's stock returns — those are close to unpredictable, and a
model built on them would report an R² near zero.

The target is an investor's portfolio value *h* months ahead. That is
genuinely forecastable, because it is dominated by what they already hold
and what they are about to contribute.

**That dominance is also the trap.** Regressing on raw rupee value gives an
R² near 0.97 for almost any model, including a baseline that assumes markets
return nothing. The model is mostly restating the current balance.

So every model predicts **excess log growth** over a contribution baseline:

```
baseline = V_t + h × monthly_contribution       (zero market return)
target   = log(V_{t+h}) − log(baseline)
```

The baseline absorbs the predictable part; the models compete only on the
market-return component.

### The baseline problem, and a correction made mid-build

The first results looked good: XGBoost scored a skill of 0.48 against the
zero-return baseline. That number was misleading.

Over this sample markets drifted upward, so excess log growth averages
**+0.125** — about +13% over twelve months. A zero-return baseline is
therefore biased low by roughly the market's own drift, and any model clears
it largely by learning that drift.

A third baseline was added: **mean drift**, which predicts the training-set
mean excess growth. It is the best constant forecast available without
looking at the test period, it is mathematically equivalent to R² on excess
growth, and it is the figure the project leads with.

The same XGBoost model scores **0.153** against it. The honest number is a
third of the flattering one.

### Results at the 12-month horizon

| Model | R² on rupee value | R² on excess growth | Skill vs zero | **Skill vs mean** |
|---|---|---|---|---|
| Baseline — contributions only | 0.962 | −0.841 | 0.000 | — |
| Baseline — mean drift | 0.962 | −0.131 | 0.386 | 0.000 |
| Baseline — trailing drift | 0.701 | −2.935 | −1.138 | −2.481 |
| XGBoost | 0.970 | 0.043 | 0.480 | 0.153 |
| **LSTM** | **0.973** | **0.149** | 0.539 | **0.249** |
| GRU | 0.968 | −0.030 | 0.442 | 0.091 |

Note how little the second column distinguishes anything: every model,
including the zero-return baseline, lands near 0.97. That column measures
scale, not skill, and is reported only because it is how such results are
usually quoted.

### Across horizons

Skill is now measured across expanding walk-forward folds rather than on one
held-out block, and the per-horizon figures live in
`ml/reports/forecast_*.json` under `tabular_search.<model>.walk_forward` with
`ml/reports/model_comparison.json` holding the before-and-after. The shape of
the result is unchanged: **skill rises with horizon**, because short-horizon
portfolio growth is dominated by unpredictable market noise while longer
horizons carry a larger predictable component through contribution
compounding and regime persistence.

**At one month the model does not beat a constant forecast, and the pipeline
recommends the baseline.** That is the result rather than a failure to tune.

### Why the old numbers measured the wrong thing

`best_iteration = 0` for every XGBoost configuration at 1, 3 and 6 months was
read as an undertrained model, and the recurrent models finding their best
validation loss at epoch 1 of 25 looked like the same problem. It was the
opposite: early stopping was working correctly and declining to fit a
relationship the validation block could not confirm.

The forecast features are dominated by market-level variables that are
identical for every investor in a given month, and 47-63% of the target's
variance is between-month rather than between-investor. So the effective
sample for a market-driven forecast is the number of distinct months, not the
number of rows:

| Split | Months | Investors | Rows |
|---|---|---|---|
| Train | 121 | 9,743 | 675,724 |
| Validation | **18** | 9,963 | 177,884 |
| Test | 29 | 10,000 | 289,897 |

Eighteen months is one small draw of market regimes. Early stopping against
it is early stopping against noise.

A ridge regression makes the same point from the other side. Over the 121
training months the month-mean target correlates with market volatility at
r = 0.24 to 0.52, statistically significant at every horizon (t = 2.6 to
6.6) — and it still generalises to the validation block with *negative* skill
at all four horizons. Real signal, unmeasurable on one block.

### What replaced it

- **Walk-forward folds.** Six expanding windows, each training on everything
  before a boundary and scoring the next six months. Ten judgements over ten
  regimes where there was one, and the spread across folds is the error bar on
  any skill claim.
- **Optuna, over the right objective.** XGBoost and LightGBM searched against
  mean walk-forward skill penalised by its own standard deviation, because a
  configuration that wins hugely in one regime and loses in the next is not a
  better forecaster than one that is mildly positive throughout.
- **A principled search sample.** The search runs on 2,000 investors across
  all months, and the winner is refitted on everything. Subsampling investors
  leaves the effective sample — months — completely intact while removing 80%
  of the compute. Not a corner cut; a consequence of the diagnosis.
- **Real epoch budgets.** 120 epochs with patience 15, against 25 and 4.
- **Prediction intervals** from the pooled walk-forward residual spread, with
  the coverage actually realised on test printed next to the nominal level,
  because return residuals are fat-tailed and the nominal figure understates
  the tails.
- **A deployment gate.** Where a model does not beat the constant baseline on
  balance across folds, the artifact records `baseline_mean_drift` as the
  recommendation and the API carries that through to the response, so a
  number the evidence does not support is never presented as a forecast.

### Fairness of the comparison

Two corrections were needed before the comparison meant anything.

The recurrent models first overfitted badly — training loss 0.003 against
validation 0.022 and rising. With 450,000 sequences resting on only ~121
distinct months, the effective sample size is the number of market regimes,
not the number of rows. They were shrunk (32 hidden units), given dropout
0.3, weight decay and gradient clipping.

XGBoost was then given a small validation grid search, since concluding that
an LSTM beats an untuned competitor would not be a comparison. The grid
confirmed the original configuration was already best of four.

### Leakage controls

- Chronological splits with a single shared cut date: train to 2022-12,
  validation to 2024-06, test thereafter.
- The pipeline aborts if split date ranges overlap.
- The pipeline aborts if any target column appears among the features.
- Sequence windows are assigned to a split by the *month being predicted*.
  A window may look back past a boundary — that is memory, not leakage; what
  would be leakage is a target appearing in two splits, which assigning by
  target month prevents.

---

## 4. Portfolio Health Score

An analytics engine, not a model. Every component is a documented function
of measurable inputs, so a score can always be explained, audited and
reproduced. An opaque learned score would be easier to build and impossible
to defend to the person whose portfolio it judges.

| Component | Weight | Inputs |
|---|---|---|
| Diversification | 20 | holding/sector/class counts, normalised HHI, average pairwise correlation |
| Risk | 20 | volatility against the band implied by stated tolerance, max drawdown |
| Concentration | 15 | top-1, top-5, max sector weight |
| Liquidity | 10 | weighted asset-class liquidity rating |
| Goal alignment | 20 | progress against required run-rate, projected funding ratio |
| Behaviour | 15 | turnover, contribution consistency, allocation drift |

Design decisions worth defending:

- **Unmeasurable components are dropped and the remaining weights
  renormalised.** A user with no goals is not penalised for something that
  could not be measured. A test pins this down: having no goals must score
  better than having goals that are badly behind.
- **Risk is scored against a band implied by the user's own stated
  tolerance**, so 20% volatility is appropriate for an aggressive investor
  and excessive for a conservative one. Overshooting is penalised harder
  than undershooting, because excess risk can cause a loss the investor
  never agreed to while caution mostly costs return.
- **Diversification includes average pairwise correlation**, which is the
  part holding counts cannot see: twenty holdings that all move together are
  not twenty bets.

Sensitivity analysis perturbs each input ±10% and records the swing in the
total, available on the API and shown on the Insights page. Inputs already
at full marks are reported as saturated rather than given a spurious
direction.

---

## 5. Copilot grounding

The platform's central claim is that the Copilot explains computed values
rather than inventing them. That claim is enforced, not merely intended.

Every number in a generated answer is extracted and matched against the tool
outputs that produced it. Unmatched figures are reported rather than
presented as fact.

### Measured over a fixed 30-question set

| Measure | Result |
|---|---|
| Numbers checked | 458 |
| Numbers verified | **458** |
| Overall groundedness | **100%** |
| Fully grounded answers | 30 of 30 |
| Median latency | 24 ms |
| Tools exercised | all 8 |

Measured on the deterministic path, which should score 100% by construction
— anything less would be a bug in the templates or the validator. With an
`ANTHROPIC_API_KEY` configured the same harness measures the language model,
which is the number worth reporting in a live deployment.

### The validator took three corrections

Each had it passing a fabricated answer:

1. It skipped every number below 13 as "probably prose", excluding
   essentially all ratios and percentages. A fabricated Sharpe ratio passed.
2. It accepted any pairwise sum or difference of tool values. With a few
   dozen values that admits hundreds of numbers; a fabricated 47.3% return
   passed. Derived values were removed entirely.
3. A flat 0.51 absolute tolerance let a fabricated beta of 2.85 match a real
   2.5. Absolute tolerance now applies only above 100, where rounding to a
   whole unit is normal.

A fourth change fixed a false positive: a drawdown stored as −27.14 and
written as "fell 27.14%" read as unverified, so magnitudes of negative tool
values now count.

---

## Seeing all of this in the product

The **Model Lab** page (`/research`) renders every figure in this document
from the same `ml/reports/` files, including the charts that are hard to
convey in prose: the silhouette curve, the 2,273-point cluster map, the
archetype×cluster recovery matrix, the autoencoder's training curves against
the Isolation Forest, the skill curve across horizons, and the feature
importances. **Data Quality** (`/data-quality`) does the same for the
pipeline findings.

## Reproducing all of this

```bash
make all
```

Every stage writes its evidence to `ml/reports/`. Seeds are fixed at 42.
`ml/tests/test_models.py` asserts that each result above still holds, so a
silent regression fails the build rather than appearing in a report.
