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
| Investor clustering | ARI **0.947** against the true generating archetype; stability ARI 0.957 |
| Anomaly detection | PR-AUC **0.935**, F1 0.839, false-positive rate 0.0008 — against 0.326 PR-AUC for an Isolation Forest baseline |
| Wealth forecasting | Skill over a mean-drift baseline rising with horizon: 0.04 at 1m, 0.24 at 6m, **0.249** at 12m |
| Copilot grounding | **100%** of 458 figures across 30 questions traceable to a backend measurement |

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
