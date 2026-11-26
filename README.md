# WealthOS

**AI-powered personal wealth intelligence and portfolio management**
Polaris School of Technology — On-the-Job Training, Advanced Data Science track

A full-stack platform that ingests a retail investor's portfolio, computes
financial and risk analytics from fifteen years of real Indian market
history, profiles investor behaviour, detects anomalous activity, forecasts
wealth trajectories, produces a decomposable Portfolio Health Score, and
explains all of it through an AI Copilot that can only quote figures the
backend computed.

> **This is an academic research prototype, not a regulated financial
> advisory service.** It explains computed portfolio metrics. It does not
> give investment advice. Market prices are real; all investor-level data in
> demonstrations is synthetic and labelled as such.

---

## What it does

| Page | What it answers |
|---|---|
| **Overview** | What do I own, what is it worth, how healthy is it |
| **Portfolio** | Every position, priced and weighted, by sector and asset class |
| **Risk** | Volatility, Sharpe, Sortino, drawdown, VaR, beta, correlation |
| **Goals** | Am I on track, and what would it take |
| **Insights** | Behavioural cluster, anomalous months, wealth forecast |
| **Copilot** | Ask in plain language; every figure is verified against the backend |
| **Import** | CSV upload with full validation before anything is written |
| **Profile** | The investor details that drive risk bands and projections |
| **Model Lab** | How every model was selected and scored — silhouette by k, the cluster map, loss curves, skill by horizon, feature importances |
| **Data Quality** | Sources, the corporate-action finding, splice validation, cohort composition |

A public landing page sits at `/`; the dashboard lives behind sign-in.

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 15 (App Router), TypeScript, Tailwind CSS 4, Recharts |
| Backend | FastAPI, Pydantic v2, SQLAlchemy 2, Alembic |
| Database | PostgreSQL 17 |
| Classical ML | scikit-learn (K-Means), XGBoost |
| Deep learning | PyTorch (autoencoder, LSTM, GRU) |
| AI Copilot | Anthropic tool-calling, with a deterministic fallback |
| Tests | pytest (313), Playwright (12) |

A single shared library, `packages/wealthos_core`, holds every financial
formula and is imported by both the API and the training pipelines, so a
metric is computed identically at training and serving time.

---

## Quick start

### Prerequisites

- **Python 3.12** (PyTorch publishes no 3.14 wheels)
- **Node 20+** and pnpm
- **PostgreSQL 17**, running
- macOS only: `brew install libomp` (XGBoost links against OpenMP)

### Set up

```bash
# 1. Python environment
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .          # makes wealthos_core importable

# 2. Database
createdb wealthos
cp .env.example .env                # then set JWT_SECRET_KEY
cd backend && ../.venv/bin/alembic upgrade head && cd ..

# 3. Frontend
cd frontend && pnpm install && cd ..
```

### Build the data and models

Each stage is independently re-runnable and writes evidence to `ml/reports/`.

```bash
make data      # stages 01-04: ingest, fetch, splice, validate, seed
make cohort    # stages 05-07: Big Sharks priors, 10,000 investors, features
make models    # stages 08-11: clustering, anomaly, forecasting, copilot eval
```

Stage 01 expects the Kaggle NSE dataset at `$KAGGLE_NSE_DIR` (default
`~/Downloads/Datasets`, containing `SCRIP/` and `INDEX/`) and Big Sharks at
`$BIG_SHARKS_CSV`. Stage 02 makes one network fetch and caches it; every
later stage runs offline.

### Run

```bash
make dev       # API on :8010, web on :3000
```

Open http://localhost:3000, register, and import
`docs/sample-holdings.csv`.

### Test

```bash
make test      # 313 Python tests
make test-e2e  # 12 Playwright tests against the running stack
```

---

## Documentation

| Document | Contents |
|---|---|
| [`docs/architecture.md`](docs/architecture.md) | How the pieces fit, and why |
| [`docs/data.md`](docs/data.md) | Sources, what is real, what is synthetic, and the corporate-action problem |
| [`docs/models.md`](docs/models.md) | Model cards and measured results |
| [`docs/api.md`](docs/api.md) | Endpoint reference |
| [`docs/deployment.md`](docs/deployment.md) | Deployment runbook |
| [`docs/limitations.md`](docs/limitations.md) | What this does not do, and what to distrust |
| [`docs/screenshots/`](docs/screenshots/) | A capture of every page |

---

## Headline results

All measured on a held-out test period that no model saw during training.

| Model | Result |
|---|---|
| Investor clustering | ARI **0.947** against the true generating archetype; stability ARI 0.949 |
| Anomaly detection | PR-AUC **0.996**, F1 0.958, false-positive rate 0.0003 — against 0.275 PR-AUC for an Isolation Forest baseline |
| Wealth forecasting | Skill over a mean-drift baseline rising with horizon: 0.040 at 1m, 0.065 at 3m, 0.246 at 6m, **0.275** at 12m |
| Copilot grounding | **100%** of 458 figures across 30 questions traceable to a backend measurement |

Before and after, from
[`ml/reports/model_comparison.json`](ml/reports/model_comparison.json), which
is generated from a Phase 0 snapshot rather than written from memory:

| Metric | Before | After |
|---|---|---|
| Anomaly F1 | 0.839 | **0.958** |
| Anomaly PR-AUC | 0.935 | **0.996** |
| Dormancy-break recall | 0.467 | **0.969** |
| False-positive rate | 0.0008 | **0.0003** |
| Forecast skill, 3m | 0.005 | **0.065** |
| Forecast skill, 12m | 0.249 | **0.275** |

### Three caveats that belong next to those numbers

**The anomaly dataset changed.** The cohort generator wrote a dormancy break
as a large contribution and never created the silence the label describes, so
a row labelled `dormancy_break` was indistinguishable from an investor
receiving a bonus. Part of the improvement is therefore that the labels now
describe what is in the data, which is a correction rather than a gain in
modelling skill. The scoring fix measured in isolation — unchanged model,
unchanged data — accounts for 0.467 → 0.580 of the dormancy recall and
0.839 → 0.850 of F1. The rest is the data fix.

**Forecast skill carries a wide spread.** Measured across six expanding
walk-forward folds rather than one held-out block, the standard deviation of
skill is comparable to or larger than its mean at every horizon (1m 0.005 ±
0.018, 3m 0.052 ± 0.069, 6m 0.037 ± 0.095, 12m 0.155 ± 0.164). **At one month
the model does not beat a constant forecast and the pipeline recommends the
baseline**, even though the single test split reports +0.040 — which is the
clearest demonstration of why one window was never enough.

**The recurrent models' headline numbers are the weakest evidence here, not
the strongest.** The 0.246 at 6m and 0.275 at 12m come from the LSTM and GRU,
and walk-forward folds were run for the gradient-boosted families only —
fitting an LSTM six times per search trial was not affordable. So those two
figures rest on the same single 29-month window whose unreliability is the
finding that started this work. The deployment recommendation follows the
walk-forward evidence even where an RNN scores higher.

The **Model Lab** page inside the product shows how each of these was
produced: the k selection, the algorithm comparison, the archetype recovery
matrix, the autoencoder's loss curves against its baseline, and the skill
curve across all four horizons.

The forecasting numbers are deliberately quoted against a *mean-drift*
baseline rather than a zero-return one. See
[`docs/models.md`](docs/models.md) for why that distinction changes the
result by a factor of three.

---

## Repository layout

```
packages/wealthos_core/   shared financial analytics — one definition per formula
backend/                  FastAPI service, SQLAlchemy models, Alembic migrations
ml/
  pipelines/              numbered, re-runnable stages 01-11
  synthetic/              investor archetypes
  models/                 trained artifacts
  reports/                metrics and validation evidence from every stage
  tests/                  data-quality and model-artifact tests
frontend/                 Next.js application and Playwright tests
data/                     raw, external, processed, synthetic, reference
docs/                     architecture, data, models, API, deployment
```
