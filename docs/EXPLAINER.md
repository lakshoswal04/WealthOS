# WealthOS — The Complete Explanation

*A full walkthrough of the project: what every folder, file and function does,
why it was built that way, what it costs in time and memory, and worked
examples you can run yourself.*

**Project** WealthOS — AI-Powered Personal Wealth Intelligence & Portfolio Management Platform
**Student** Laksh (240410700131) · Polaris School of Technology · Advanced Data Science (OJT)
**Mentor** Navneet Nautiyal
**Status** Academic research prototype. Not a regulated financial advisory service.

---

## How to read this document

The project is about 20,700 lines of code across four layers. This document
covers **every file and every function**, but it does not print all 20,700
lines back at you — that would be a copy, not an explanation. Instead:

- Every folder gets a map.
- Every file gets a paragraph saying what it is for.
- Every function gets a line saying what it takes, what it gives back, and
  what it costs (time and memory).
- The **load-bearing lines** — the ten or twenty places where a formula or a
  decision actually lives — are quoted exactly and explained line by line.
- Numbers come from the project's own report files in `ml/reports/`, not from
  memory, so everything here is checkable.

If you are preparing for a viva, read sections 1, 3, 7, 8, 11 and 14 first.
Section 14 is a list of likely questions with the answers.

---

## Table of contents

| § | Section | What it covers |
|---|---|---|
| 1 | [The project in plain words](#1-the-project-in-plain-words) | The problem, the idea, the five promises |
| 2 | [How to run it](#2-how-to-run-it) | Commands, ports, what to expect |
| 3 | [Architecture](#3-architecture) | The five layers and why they are separate |
| 4 | [Directory map](#4-directory-map) | Every folder and file |
| 5 | [The tools used, and why](#5-the-tools-used-and-why) | Every library, with the reason |
| 6 | [`wealthos_core` — the formula library](#6-wealthos_core--the-formula-library) | Every financial formula, line by line |
| 7 | [The database](#7-the-database) | Nine tables, constraints, indexes |
| 8 | [The backend API](#8-the-backend-api) | Config, auth, services, all 30 endpoints |
| 9 | [The data pipeline](#9-the-data-pipeline-stages-01-07) | Stages 01–07: raw data → model-ready tables |
| 10 | [The three models](#10-the-three-models-stages-0810) | Clustering, anomaly detection, forecasting |
| 11 | [The Wealth Copilot](#11-the-wealth-copilot) | Tool-calling, grounding, both paths |
| 12 | [The frontend](#12-the-frontend) | Pages, components, charts, design tokens |
| 13 | [Complexity reference](#13-complexity-reference) | Every operation, time and space, in one table |
| 14 | [Testing](#14-testing) | 313 Python tests + 12 browser tests |
| 15 | [Worked end-to-end examples](#15-worked-end-to-end-examples) | Four complete traces |
| 16 | [Honest limitations](#16-honest-limitations) | What this cannot do |
| 17 | [Viva questions and answers](#17-viva-questions-and-answers) | 30 likely questions |

---

## 1. The project in plain words

### The problem

An ordinary Indian retail investor holds money in four or five different
places: a demat account with shares, a few mutual funds, some gold, a fixed
deposit, cash in a savings account. Four things then go wrong:

1. **Nothing adds up.** There is no single screen showing total wealth.
2. **Only returns get tracked, never risk.** An app will happily tell you
   "+18% this year" and never mention that the same portfolio fell 40% in
   March 2020. Return without risk is half a sentence.
3. **Diversification is faked.** Holding twenty stocks sounds diversified.
   If eighteen of them are banks, it is one bet wearing twenty costumes.
4. **Goals live somewhere else.** "I need ₹50 lakh for a house in 2033" sits
   in a spreadsheet, completely disconnected from the portfolio that is
   supposed to get there.

### The idea

One platform that takes your holdings and answers five questions, each one
backed by a number you can audit:

| Question | How WealthOS answers it |
|---|---|
| What do I own, and what is it worth? | Positions valued against a real, corporate-action-adjusted price panel |
| How risky is it, really? | Volatility, drawdown, VaR, CVaR, beta, alpha, Sharpe, Sortino, Calmar, correlation |
| Is this portfolio actually *good*? | A 0–100 Portfolio Health Score, broken into six components you can see |
| Will I reach my goals? | Projections with a pessimistic/expected/optimistic band, plus a 2,000-path Monte Carlo fan |
| Can something explain this to me? | An AI Copilot that may only quote numbers the backend computed |

### The five promises the build had to keep

These are the constraints that shaped every design decision in the project.

**1. One definition per formula.**
Sharpe ratio is defined exactly once, in `packages/wealthos_core/metrics.py`.
The API imports it. The training pipelines import it. Nothing re-implements
it. This prevents *train/serve skew* — the classic bug where a model learns
from one definition of a feature and is then served a slightly different one.

**2. Every number carries its assumptions.**
A Sharpe ratio is meaningless without a risk-free rate. So every response
that contains a Sharpe ratio also contains `"risk_free_rate": 0.06`. Every
projection carries the return, the volatility and the horizon that produced
it. The UI prints them.

**3. The data must be right before the models are clever.**
The single most important piece of work in this project is not a neural
network. It is discovering that the Kaggle price data is not adjusted for
corporate actions, and fixing it. Section 9.3 explains why that one fix
changed INFY's maximum drawdown from −87.9% to −36.5% and flipped its Sharpe
ratio from **−0.30 to +0.43** — a profitable holding was being reported as a
loss-maker.

**4. Accuracy must measure skill, not scale.**
It is trivial to predict a portfolio's value 12 months from now with 99%
accuracy: guess "the same as today, plus the deposits". That scores R² = 0.996
and knows nothing. Section 10.3 explains the target redesign that makes the
reported accuracy mean something.

**5. The AI may not invent numbers.**
The Copilot has no calculator. It picks which backend measurement to fetch,
then narrates it. Before any answer reaches the user, every numeral in it is
extracted and matched against the tool outputs. Measured grounding: **458 of
458 numbers verified across 30 questions (100%)**.

### What is real and what is simulated — stated plainly

| Thing | Real or simulated | Source |
|---|---|---|
| Daily prices, 58 assets, 2012–2026 | **Real** | Kaggle NSE + Yahoo Finance `adj_close` |
| NIFTY 50 benchmark, 1990–2026 | **Real** | Kaggle index + Yahoo, spliced |
| Which stocks investors crowd into | **Real** (shape only) | Big Sharks portfolio dataset |
| 10,000 investors and their 1.25M monthly snapshots | **Simulated** | Generated from 6 archetypes, grown against the real prices |
| The 3,556 anomalous months | **Simulated and labelled** | Injected deliberately, so detection can be scored |
| Your own portfolio, once you import it | **Real** | Your CSV |

The cohort is simulated for one reason that is worth stating clearly: **real
retail portfolio data does not exist publicly, and would be a privacy
catastrophe if it did.** Simulating it also buys something real data cannot
give — because the generating archetype of every investor is known, the
clustering model can be scored against ground truth with Adjusted Rand Index,
not just with an internal index like silhouette. See section 10.1.

---

## 2. How to run it

### First time

```bash
brew install libomp postgresql@17     # libomp: XGBoost needs OpenMP on macOS
createdb wealthos
make setup                            # venv (Python 3.12), deps, pnpm install, migrations
```

`make setup` does five things, in order:

```make
python3.12 -m venv .venv                      # 1. isolated interpreter
$(PY) -m pip install -r requirements.txt      # 2. 25 pinned dependencies
$(PY) -m pip install -e .                     # 3. wealthos_core as an editable package
cd frontend && pnpm install                   # 4. 5 runtime + 10 dev JS packages
cd backend && ../$(PY) -m alembic upgrade head # 5. create the 9 tables
```

Step 3 is the one people skip and then wonder why imports fail. Installing
`wealthos_core` as an *editable* package is what lets both `backend/` and
`ml/` write `from wealthos_core import sharpe_ratio` and get the same file —
not a copy. Edit the formula once, both sides change.

Python must be **3.12**. PyTorch publishes no wheels for 3.14, so a newer
interpreter fails at install time, not at run time.

### Build the data and the models

```bash
make data      # stages 01–04: ingest, fetch, splice, validate, seed Postgres (~6 min)
make cohort    # stages 05–07: priors, 10,000 investors, feature tables (~11 min)
make models    # stages 08–11: train 3 models at 4 horizons, measure grounding (~25 min)
make all       # all of the above
```

Each stage is independently re-runnable and writes its findings to
`ml/reports/*.json`. Re-running stage 08 does not require re-running 01.

### Run it

```bash
make api    # FastAPI on http://localhost:8010  (docs at /docs)
make web    # Next.js on http://localhost:3000
make dev    # both, API backgrounded
```

Open **http://localhost:3000** — it opens on the public landing page. Sign up,
import `docs/sample-holdings.csv`, and every page has data.

### Check it

```bash
make test       # 313 Python tests
make test-e2e   # 12 Playwright tests in a real Chromium browser
make lint       # tsc --noEmit + eslint
curl localhost:8010/health
```

A healthy API replies:

```json
{"status":"ok","environment":"development","database":"connected",
 "market_data":{"assets":58,"latest_date":"2026-11-13"},"copilot":"fallback"}
```

`"copilot":"fallback"` means no `ANTHROPIC_API_KEY` is set, so the
deterministic template explainer is running. Add the key to `.env`, restart
the API, and it becomes `"copilot":"llm"` using `claude-opus-5-5`.

### Every Makefile target

| Target | What it does |
|---|---|
| `help` | Lists these targets (the default goal) |
| `setup` | venv, dependencies, editable core install, migrations |
| `data` | Stages 01–04 |
| `cohort` | Stages 05–07 |
| `models` | Stages 08–11 |
| `all` | `data cohort models` |
| `api` | uvicorn with `--reload` on port 8010 |
| `web` | `pnpm dev` on port 3000 |
| `dev` | Both, API in the background |
| `test` | `pytest -q` |
| `test-e2e` | `playwright test` against a running stack |
| `lint` | TypeScript type-check + ESLint |
| `db-reset` | Drop, recreate, migrate, re-seed prices |
| `clean` | Remove `__pycache__`, `.next`, test artifacts |

---

## 3. Architecture

### The five layers

```
┌────────────────────────────────────────────────────────────────────────┐
│  5. PRESENTATION      Next.js 15 · React 19 · Tailwind 4 · Recharts   │
│     12 routes. Landing page, 8 dashboard pages, 2 research pages,     │
│     login/register. Knows no formulas — it renders what the API says. │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ HTTPS + JSON, Bearer JWT
┌───────────────────────────────▼────────────────────────────────────────┐
│  4. API               FastAPI · Pydantic v2 · 7 routers, 30 endpoints │
│     Validates input, authenticates, scopes every query by user_id,    │
│     attaches assumptions to every number, degrades instead of dying.  │
└───────────────────────────────┬────────────────────────────────────────┘
                                │ Python function calls
┌───────────────────────────────▼────────────────────────────────────────┐
│  3. SERVICE           9 service modules + ml_runtime                  │
│     Turns database rows into the pandas objects the core expects,     │
│     loads trained model artifacts, builds live features, runs the     │
│     Copilot's tool loop.                                              │
└──────────────┬────────────────────────────────┬────────────────────────┘
               │                                │
┌──────────────▼──────────────┐   ┌─────────────▼────────────────────────┐
│  2a. wealthos_core          │   │  2b. ml/models/*.joblib, *.pt        │
│      PURE FUNCTIONS         │   │      Trained artifacts               │
│      No DB. No web. No      │   │      kmeans, autoencoder,            │
│      model files. 40        │   │      xgboost+lstm+gru × 4 horizons   │
│      formulas, 127 tests.   │   │                                      │
└──────────────┬──────────────┘   └─────────────▲────────────────────────┘
               │                                │
               │  IMPORTED BY BOTH SIDES        │  produced by
               │                                │
┌──────────────▼────────────────────────────────┴────────────────────────┐
│  1. DATA              PostgreSQL 17 (9 tables) + parquet + 19 JSON    │
│     reports. Built by 12 numbered, re-runnable pipeline stages.       │
└────────────────────────────────────────────────────────────────────────┘
```

### Why the layers are split this way

**Why `wealthos_core` is a separate package, not a folder in the backend.**
Because the ML pipelines need it too, and they do not import the web app. If
Sharpe lived in `backend/app/services/risk_service.py`, then training a model
on a Sharpe feature would require either importing FastAPI into a training
script (absurd) or writing Sharpe a second time (dangerous). Making it a
third thing that both import is the only arrangement where the formula cannot
drift. It is installed with `pip install -e .`, so there is one copy on disk.

**Why the core has no database access.** A function that takes a `Session`
cannot be unit-tested without a database. A function that takes a
`pd.Series` can be tested with three hand-calculated numbers. All 127 core
tests run in 0.27 seconds with no Postgres running. That speed is what makes
it practical to verify formulas by hand.

**Why the service layer exists at all.** The core wants pandas. The database
has rows. Something has to convert, and that something also has to decide
what to do when there is not enough history. Putting that in the API router
would make the router untestable; putting it in the core would make the core
impure. It goes in the middle.

**Why the frontend knows no formulas.** The scenario simulator was the
temptation here: a Monte Carlo in JavaScript would feel snappier than an API
round trip. It would also be a second implementation of the projection
formula, free to drift from the one in `goals.py`. So the simulator debounces
input by 260 ms and calls `POST /goals/{id}/simulate`. One definition.

### Request flow: a single trace

Here is what happens when a signed-in user loads the Risk page.

```
Browser                 Next.js            FastAPI             Service          Core
   │                       │                  │                   │               │
   │ GET /risk             │                  │                   │               │
   ├──────────────────────►│                  │                   │               │
   │                       │ render shell     │                   │               │
   │◄──────────────────────┤ (instant)        │                   │               │
   │                       │                  │                   │               │
   │ useApi(api.risk())    │                  │                   │               │
   │  GET /api/v1/analytics/risk              │                   │               │
   │  Authorization: Bearer eyJ...            │                   │               │
   ├─────────────────────────────────────────►│                   │               │
   │                       │                  │ get_current_user  │               │
   │                       │                  │  decode JWT       │               │
   │                       │                  │  SELECT users     │               │
   │                       │                  │  WHERE id=7       │               │
   │                       │                  ├──────────────────►│               │
   │                       │                  │                   │ holdings (1 q)│
   │                       │                  │                   │ weights       │
   │                       │                  │                   │ market_cache  │
   │                       │                  │                   │  .returns()   │
   │                       │                  │                   │  (RAM, no DB) │
   │                       │                  │                   ├──────────────►│
   │                       │                  │                   │               │ volatility
   │                       │                  │                   │               │ drawdown
   │                       │                  │                   │               │ VaR/CVaR
   │                       │                  │                   │               │ beta/alpha
   │                       │                  │                   │               │ corr matrix
   │                       │                  │                   │◄──────────────┤
   │                       │                  │◄──────────────────┤ + assumptions │
   │◄─────────────────────────────────────────┤ 200 JSON          │               │
   │                       │                  │ X-Response-Time-ms: 41.3          │
   │ Recharts renders      │                  │                   │               │
```

Two things to notice. First, **the price data never touches the database on
this path** — it was loaded into a process-wide pandas DataFrame at startup,
so the risk endpoint is pure in-memory arithmetic. Second, **every response
carries `X-Response-Time-ms`**, added by a middleware in `main.py`, which is
how the PRD's latency target becomes measurable rather than aspirational.

### Degradation: what happens when something is missing

A research prototype that falls over when one file is absent is not usable.
Three explicit fallbacks:

| If this is missing | What happens | Where |
|---|---|---|
| A trained model artifact | That one panel says "model unavailable — run the pipelines". Everything else works. | `ml_runtime/registry.py`, `insight_service.py` |
| `ANTHROPIC_API_KEY` | The Copilot runs a deterministic template explainer over the same eight tools. 100% grounded by construction. | `copilot_service.py` |
| A pipeline report JSON | That Model Lab section says which stage to run. The page renders. | `api/v1/research.py`, `lib/reports.ts` |

The market cache failing to load does **not** stop the API booting — it logs
an error and endpoints that need prices report the problem themselves. That
is a deliberate choice in `main.py`'s `lifespan`: a cold cache is a data
problem, not a reason the server cannot accept a login.

---

## 4. Directory map

```
Laksh_Ojt/
├── packages/wealthos_core/     ← LAYER 2a: the formula library (3,253 lines)
│   ├── __init__.py             re-exports 40 public functions
│   ├── constants.py            every assumption, in one place
│   ├── returns.py              8 return functions
│   ├── risk.py                 10 risk functions
│   ├── metrics.py              5 risk-adjusted ratios
│   ├── concentration.py        7 concentration measures
│   ├── portfolio.py            8 portfolio-level functions
│   ├── health.py               the 6-component Health Score
│   ├── goals.py                projections + Monte Carlo
│   └── tests/                  127 tests, hand-calculated
│
├── backend/                    ← LAYERS 3 & 4: API + services (6,637 lines)
│   ├── app/
│   │   ├── main.py             FastAPI app, lifespan, middleware, /health
│   │   ├── core/
│   │   │   ├── config.py       pydantic-settings, reads .env
│   │   │   └── security.py     bcrypt + JWT
│   │   ├── db/
│   │   │   ├── base.py         declarative Base + TimestampMixin
│   │   │   └── session.py      engine, pool, get_db dependency
│   │   ├── models/             9 SQLAlchemy models
│   │   ├── schemas/            Pydantic request/response shapes
│   │   ├── services/           9 service modules
│   │   ├── ml_runtime/
│   │   │   ├── registry.py     loads trained artifacts once per process
│   │   │   └── features.py     rebuilds live features for a real user
│   │   └── api/
│   │       ├── deps.py         get_current_user — the whole auth boundary
│   │       └── v1/             7 routers, 30 endpoints
│   ├── alembic/                one migration: the initial 9-table schema
│   └── tests/                  145 tests against a real test database
│
├── ml/                         ← the pipelines (4,682 lines)
│   ├── pipelines/
│   │   ├── common.py           paths, Stage timer, validation gate, loaders
│   │   ├── p01_ingest_market.py      Kaggle NSE → validated parquet
│   │   ├── p02_fetch_external.py     Yahoo adj_close → cache
│   │   ├── p03_build_prices.py       ★ the adjusted price panel
│   │   ├── p03b_validate_adjustment.py ★ proves why 03 was necessary
│   │   ├── p04_seed_database.py      panel → PostgreSQL
│   │   ├── p05_big_sharks_priors.py  real holding popularity
│   │   ├── p06_generate_cohort.py    10,000 investors, simulated forward
│   │   ├── p07_features.py           ★ three feature tables, time splits
│   │   ├── p08_train_clustering.py   K-Means + GMM + Agglomerative
│   │   ├── p09_train_anomaly.py      autoencoder + Isolation Forest
│   │   ├── p10_train_forecast.py     XGBoost + LSTM + GRU + 3 baselines
│   │   └── p11_eval_copilot.py       groundedness over 30 questions
│   ├── synthetic/archetypes.py       6 latent investor archetypes
│   ├── models/                       trained artifacts (.joblib, .pt)
│   ├── reports/                      19 JSON evidence files
│   └── tests/                        41 tests on data and artifacts
│
├── frontend/                   ← LAYER 5: the web app (6,098 lines)
│   ├── src/app/
│   │   ├── page.tsx                  the public landing page
│   │   ├── layout.tsx                fonts, AuthProvider
│   │   ├── globals.css               design tokens
│   │   ├── (marketing)/layout.tsx    public shell
│   │   ├── (auth)/login, register    sign-in pages
│   │   └── (dashboard)/              8 protected pages
│   ├── src/components/
│   │   ├── ui/index.tsx              21 primitives
│   │   ├── ui/shell.tsx              sidebar, top bar, user chip
│   │   ├── ui/marketing.tsx          public header + footer
│   │   ├── ui/simulator.tsx          the scenario simulator
│   │   └── charts/index.tsx          19 chart components
│   ├── src/lib/
│   │   ├── api.ts                    typed client, 30 methods
│   │   ├── auth.tsx                  AuthProvider + useApi hook
│   │   ├── format.ts                 rupees, percents, dates
│   │   ├── viz.ts                    the validated chart palette
│   │   └── reports.ts                safe access into pipeline JSON
│   └── e2e/                          12 Playwright tests + screenshots
│
├── data/
│   ├── raw/                    nse_equity.parquet (5.23M rows), nse_index.parquet
│   ├── external/yahoo/         58 per-symbol parquet files
│   ├── processed/              price_panel, returns, 3 feature tables
│   ├── synthetic/              investors.parquet, snapshots.parquet
│   └── reference/universe.csv  the 51-name MVP universe + mappings
│
├── docs/                       data.md, models.md, architecture.md,
│                               limitations.md, api.md, deployment.md,
│                               this file, 11 screenshots, sample CSV
├── docker/                     Dockerfiles + compose (unverified)
├── .github/workflows/ci.yml    lint + test on push
├── Makefile                    14 targets
├── requirements.txt            25 pinned Python dependencies
└── render.yaml                 deploy config
```

★ marks the four files that carry the project's most consequential decisions.

---

## 5. The tools used, and why

### Python side

| Tool | Version | What it does here | Why this one |
|---|---|---|---|
| **Python** | 3.12 | The language | 3.13+ has no PyTorch wheels. Pinned for that reason. |
| **NumPy** | 2.2.6 | Arrays, percentiles, RNG | The Monte Carlo runs on a single `(2000, months)` array rather than a Python loop — about 100× faster |
| **pandas** | 2.3.3 | Every table and time series | Date-indexed `Series` is the natural shape for prices; `groupby` carries the cohort work |
| **PyArrow** | 21.0.0 | Parquet read/write | Columnar and typed. The 1.25M-row snapshot table loads in under a second; CSV would take 20× the space and lose dtypes |
| **SciPy** | 1.18.1 | Statistics | 1.15.x ships a macOS binary that fails to `dlopen` on Darwin 27 — pinned forward with a comment |
| **scikit-learn** | 1.7.2 | K-Means, GMM, Agglomerative, Isolation Forest, `StandardScaler`, every metric | The standard. Also supplies the honest comparators |
| **XGBoost** | 3.0.5 | Gradient-boosted trees for forecasting | Best-in-class on tabular data. Needs `brew install libomp` on macOS |
| **PyTorch** | 2.8.0 | The autoencoder, the LSTM, the GRU | Needed for a custom bottleneck architecture and a custom training loop with early stopping |
| **joblib** | 1.5.2 | Saving sklearn/XGBoost artifacts | Handles NumPy arrays better than pickle |
| **FastAPI** | 0.118.0 | The HTTP API | Async, and generates OpenAPI docs from the type hints — `/docs` is free |
| **Pydantic** | 2.11.9 | Request/response validation | Rejects bad input at the boundary, so no service function has to defend itself |
| **pydantic-settings** | 2.11.0 | `.env` loading | Typed configuration; secrets never hard-coded |
| **SQLAlchemy** | 2.0.43 | ORM | 2.0's `Mapped[...]` typing means the models are checkable |
| **Alembic** | 1.16.5 | Migrations | Schema changes are versioned files, not remembered commands |
| **psycopg** | 3.2.10 | PostgreSQL driver | Version 3, binary build |
| **bcrypt** | 4.3.0 | Password hashing | Deliberately slow (~250 ms), which is the point |
| **PyJWT** | 2.10.1 | Token signing | HS256 |
| **anthropic** | 0.69.0 | The Copilot's LLM path | Official SDK, `claude-opus-5-5` |
| **httpx** | 0.28.1 | Yahoo Finance fetch | Modern HTTP client |
| **rapidfuzz** | 3.14.1 | Fuzzy company-name matching | Maps "Infosys Ltd" → `INFY`; 22 of 845 matches came from here |
| **pytest** | 8.4.2 | 313 tests | — |
| **matplotlib/seaborn** | 3.10.6 / 0.13.2 | Pipeline figures | Offline charts; the web app uses Recharts |

### JavaScript side

| Tool | Version | What it does here | Why this one |
|---|---|---|---|
| **Next.js** | 15.5.4 | React framework, App Router | File-based routing, route groups for the three shells (marketing/auth/dashboard), server components for instant shell render |
| **React** | 19.1.0 | UI | — |
| **TypeScript** | 5.x | Types | Every API response has an interface. `tsc --noEmit` is part of `make lint` |
| **Tailwind CSS** | 4.x | Styling | Utility classes on top of CSS custom properties, so one token change restyles the app |
| **Recharts** | 2.15.3 | All 19 charts | Composable React charts; renders SVG so text stays selectable and accessible |
| **clsx** | 2.1.1 | Conditional classes | Tiny |
| **Playwright** | 1.61.1 | 12 browser tests + screenshots | Runs real Chromium. Caught three bugs a green unit suite missed |
| **pnpm** | — | Package manager | Content-addressed store, strict by default |

### Infrastructure

| Tool | What it does here |
|---|---|
| **PostgreSQL 17** | 9 tables. JSONB columns for model payloads, B-tree indexes on every query path |
| **uvicorn** | ASGI server |
| **GitHub Actions** | `ci.yml` runs lint + tests on push |
| **Docker** | Dockerfiles and compose for backend/frontend — written but marked **unverified**, because they were never actually built and run |
| **Render / Vercel** | `render.yaml` and `vercel.json` deploy configs |
| **Git** | 15 commits, one per completed phase |

### The two datasets

| Dataset | Rows | What it actually gave the project |
|---|---|---|
| **NSE India 1990–2020** (`stoicstatic/india-stock-data-nse-1990-2020`) | 5,230,852 equity rows across 2,096 symbols; 206,696 index rows across 54 indices | Long NIFTY 50 history (back to 1990-07-03) and a deep equity universe. Its closing prices are **unadjusted**, which stage 03 had to fix |
| **Big Sharks Portfolio** (`pranaybshah/big-sharks-portfolio`) | 1,169 company names, 50 investors | The PRD treated this as a schema reference. It was used for more: which Indian stocks investors crowd into, and how concentrated real portfolios are (median HHI 0.2266). 72.3% of names mapped to NSE symbols |
| **Yahoo Finance** (fetched once, cached) | 58 symbols, 2000–2026 | `adj_close` — split-, bonus- and dividend-adjusted. This became the price source |

---

## 6. `wealthos_core` — the formula library

This is the most important package in the project, because everything else
depends on it being right. It is **3,253 lines**, of which about 1,400 are
tests, and it has one hard rule: **no imports from a database, a web
framework, or a model file.** It takes pandas objects in and gives numbers
out. Nothing else.

Two conventions run through the whole package:

**1. Never raise on thin data — return `NaN`.**

```python
def annualized_volatility(returns, periods_per_year=252) -> float:
    r = _clean(returns)
    if len(r) < 2:
        return float("nan")          # not an exception
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))
```

Why: a caller is usually looping over 58 assets, and three of them listed last
month. If thin data raised, every call site would need a `try/except`. With
`NaN`, the caller aggregates and the gap is visible in the output.

**2. Never mutate the input.** Every function starts by coercing to a fresh
`pd.Series(..., dtype="float64")`. A function that silently modified the
caller's price series would produce bugs that only appear on the second call.

### 6.1 `constants.py` — every assumption, in one file

```python
TRADING_DAYS_PER_YEAR: int = 252        # Indian equity trading days
MONTHS_PER_YEAR: int = 12
DEFAULT_RISK_FREE_RATE: float = 0.06    # proxy for the Indian 10-year G-sec
CASH_ANNUAL_RETURN: float = 0.055       # deterministic accrual for 'cash'
BENCHMARK_SYMBOL: str = "NIFTY 50"
ASSET_CLASSES = ("equity", "etf", "gold", "debt", "cash")
ASSET_CLASS_LIQUIDITY = {"cash": 1.00, "debt": 0.75, "etf": 0.85,
                         "gold": 0.80, "equity": 0.70}
```

Why this file exists at all: `0.06` appears in Sharpe, Sortino, Treynor,
alpha, the Health Score's risk band, and the goal engine. If it were typed in
six places, changing it would mean finding six places and getting all six
right. Here it is one line, and the project report can cite it.

`CASH_ANNUAL_RETURN` deserves a note. Liquid ETFs like LIQUIDBEES hold their
NAV at a constant and pay their return out as dividends, so their *price*
series is flat. Reading a flat price series as a flat return would say cash
earns 0%, which is false. Modelling it at an explicitly documented 5.5% is
less precise but more honest, and the assumption is printed in the UI.

**Complexity:** O(1). It is a module of literals.

### 6.2 `returns.py` — eight functions

| Function | Formula | Time | Space |
|---|---|---|---|
| `simple_returns(prices)` | `P_t / P_{t−1} − 1` | O(n) | O(n) |
| `log_returns(prices)` | `ln(P_t / P_{t−1})` | O(n) | O(n) |
| `wealth_index(returns)` | `∏(1 + r)` running | O(n) | O(n) |
| `cumulative_return_series(r)` | `wealth_index − 1` | O(n) | O(n) |
| `total_return(r)` | `∏(1 + r) − 1` | O(n) | O(1) |
| `annualized_return(r)` | `(∏(1+r))^(1/years) − 1` | O(n) | O(1) |
| `annualized_volatility(r)` | `std(r, ddof=1) · √252` | O(n) | O(1) |
| `cagr(start, end, years)` | `(end/start)^(1/years) − 1` | O(1) | O(1) |

**Worked example** (run it yourself — these are real outputs):

```python
prices = pd.Series([100.0, 110.0, 99.0, 108.9])

simple_returns(prices)   →  [NaN, 0.10, −0.10, 0.10]
log_returns(prices)      →  [NaN, 0.09531, −0.105361, 0.09531]
total_return(...)        →  0.089           # +8.9%, not 0.10 − 0.10 + 0.10 = 0.10
wealth_index(...)        →  [1.10, 0.99, 1.089]
```

Three things this example teaches:

1. **The first return is always `NaN`.** You cannot compute a change without a
   previous value. Code that forgets this silently shifts every series by one day.
2. **+10%, −10%, +10% is not +10%.** It is **+8.9%**. Multiplying 1.10 × 0.90
   × 1.10 = 1.089. This is why `total_return` compounds instead of summing, and
   why `annualized_return` is geometric rather than an arithmetic mean.
3. **Log returns add where simple returns multiply.** 0.09531 − 0.105361 +
   0.09531 = 0.085259, and `e^0.085259 − 1 = 0.089` — the same answer. That
   additivity is exactly why the forecasting target in section 10.3 is a *log*
   growth figure: horizons can be added.

Two defensive details worth pointing out:

```python
return prices.pct_change().replace([np.inf, -np.inf], np.nan)
```
A zero price in the source data would make `pct_change` return `inf`, which
then poisons the mean, the std, and every ratio downstream. It becomes `NaN`
instead, which propagates visibly rather than silently.

```python
safe = prices.where(prices > 0)       # in log_returns
return np.log(safe / safe.shift(1))
```
`log` of a non-positive number is undefined. Masking first turns that into
`NaN` rather than a RuntimeWarning plus garbage.

```python
growth = float((1.0 + r).prod())
if growth <= 0:
    return float("nan")    # a total wipeout has no finite annual growth rate
```
If an asset goes to zero, the compounded growth is 0 and `0^(1/years)` is 0,
giving an "annualised return" of −100% for every horizon. That is arithmetically
true and practically meaningless, so it reports `NaN`.

### 6.3 `risk.py` — ten functions

#### Drawdown

```python
def drawdown_series(returns):
    wealth = wealth_index(returns)   # ∏(1+r) running
    peak   = wealth.cummax()         # highest value seen SO FAR
    return wealth / peak - 1.0       # ≤ 0 always
```

`cummax` is the whole trick. It is the running maximum, so at every date it
knows the highest the portfolio has ever been *up to that point* — never
looking forward. Three lines, O(n) time, O(n) space, no loop.

```
prices:   100 → 110 → 99 → 108.9
wealth:         1.10   0.99   1.089
peak:           1.10   1.10   1.10
drawdown:       0.00  −0.10  −0.01       →  max_drawdown = −0.10
```

`drawdown_detail` adds the dates:

| Field | Value in the example | How it is found |
|---|---|---|
| `max_drawdown` | −0.10 | `dd.min()` |
| `trough_date` | the 99 day | `dd.idxmin()` |
| `peak_date` | the 110 day | `wealth.loc[:trough].idxmax()` |
| `recovery_date` | `None` | first date after the trough where wealth ≥ peak value — never happens here, 1.089 < 1.10 |
| `recovered` | `False` | — |
| `drawdown_days` | 2 | calendar days from peak to recovery (or to the end) |

That `recovered: False` is the kind of detail that matters in a wealth product.
A portfolio down 1% from its peak sounds fine; "has not recovered its 2021
high" is the actual situation.

**Complexity:** `drawdown_series` O(n)/O(n); `max_drawdown` O(n)/O(n);
`drawdown_detail` O(n) — the three slices and two `idxmax` calls are each
linear, so the total stays linear.

#### Downside deviation — the Sortino denominator

```python
mar_per_period = (1.0 + minimum_acceptable_return) ** (1.0 / periods_per_year) - 1.0
shortfall = np.minimum(r - mar_per_period, 0.0)
return float(np.sqrt((shortfall ** 2).mean()) * np.sqrt(periods_per_year))
```

Line 1 de-annualises the target. A 6% annual MAR is **not** 6% per day; it is
`1.06^(1/252) − 1 ≈ 0.0000231` per day. Dividing by 252 instead would be close
but wrong, and would make Sortino inconsistent with Sharpe, which annualises
geometrically.

Line 2 clips every return at zero from above: good days become 0, bad days keep
their shortfall. This is what makes Sortino ignore upside volatility.

Line 3 is where most tutorials get it wrong. `.mean()` averages over **all**
observations, not only the losing ones. If you average over losing days only,
a portfolio that falls rarely but hard gets a *larger* denominator than one
that falls constantly and gently — the ratio stops being comparable between
assets. The docstring says so explicitly, because it is a deliberate choice
and a reviewer will ask.

**Hand check** (verified in code): for `r = [0.02, −0.01, 0.03, −0.02, 0.01]`
with MAR = 0 and `periods_per_year = 1`:
shortfalls are `[0, −0.01, 0, −0.02, 0]`, squares `[0, 0.0001, 0, 0.0004, 0]`,
mean `0.0001`, √ = **0.01**. The function returns exactly `0.01`.

#### Tail risk: VaR and CVaR

```python
if method == "historical":
    return float(np.quantile(r, 1.0 - confidence))
```

VaR at 95% is the 5th percentile of the return distribution. `−0.0203` means
"on the worst 5% of days, the loss was at least 2.03%".

```python
threshold = value_at_risk(r, confidence, method="historical")
tail = r[r <= threshold]
return float(tail.mean())
```

CVaR (expected shortfall) is the *average* of that worst 5%: `−0.0251`. It is
the more useful number, because VaR tells you where the cliff edge is and CVaR
tells you how far down it goes. `−0.0251` vs `−0.0203` says the bad days are
roughly 24% worse than the threshold.

Historical is the default because it makes no distributional assumption.
Gaussian VaR is offered for comparison and the docstring states plainly that
it *understates* fat tails in equity returns — October 2008 and March 2020 do
not live in a normal distribution.

**Complexity:** `np.quantile` uses introselect partitioning, so O(n) average
rather than the O(n log n) a full sort would cost. CVaR is O(n) for the
boolean mask plus O(n) for the mean. Space O(n) for the tail copy.

#### Benchmark sensitivity: beta and alpha

```python
def _align(a, b):
    frame = pd.concat([...], axis=1, join="inner")   # dates present in BOTH
    frame = frame.replace([np.inf, -np.inf], np.nan).dropna()
    return frame.iloc[:, 0], frame.iloc[:, 1]
```

`_align` is small and load-bearing. Beta compares two series day by day. If
the portfolio has a value on a date the benchmark does not (or vice versa),
pairing them by position instead of by date shifts one series against the
other and produces a beta that is pure noise. `join="inner"` guarantees the
pairing is by date.

```python
def beta(asset_returns, benchmark_returns):
    a, b = _align(asset_returns, benchmark_returns)
    benchmark_variance = float(b.var(ddof=1))
    if benchmark_variance <= 0:
        return float("nan")
    return float(a.cov(b) / benchmark_variance)
```

β = Cov(asset, benchmark) / Var(benchmark). β = 1.13 in the worked example
means that when the NIFTY moves 1%, this portfolio has historically moved
about 1.13%.

```python
expected = risk_free_rate + asset_beta * (bench_annual - risk_free_rate)
return float(asset_annual - expected)
```

Jensen's alpha: what the portfolio earned *beyond* what its beta alone would
predict. In the worked example the benchmark returned 14.05% annualised, so a
β = 1.133 portfolio "should" have returned 6% + 1.133 × (14.05% − 6%) =
15.11%. It actually returned 19.79%, so α = **+4.68%**.

**Complexity:** both O(n) after the align, which is O(n log n) in the worst
case because `concat` with `join="inner"` may sort the union of indexes.

#### Correlation

```python
def correlation_matrix(returns_frame):
    frame = pd.DataFrame(returns_frame).replace([np.inf, -np.inf], np.nan)
    return frame.corr(min_periods=2)
```

One sentence in the docstring is the whole point: *"Correlation is computed on
returns, never on price levels."* Two completely unrelated stocks that both
drift upward over fifteen years will show a price correlation near 0.95. Their
*returns* might be correlated 0.1. Correlating levels would make every
portfolio look undiversified and the diversification score useless.

**Complexity:** this is the most expensive function in the core.
For m assets over n days: **O(m²n) time, O(m²) space.** For a 12-holding
portfolio over 4,069 days that is 12² × 4,069 ≈ 586,000 multiply-adds —
sub-millisecond in BLAS. For 58 assets it would be 13.7 million, still fast,
but the m² growth is why the Risk page correlates only the user's holdings and
not the whole universe.

`average_pairwise_correlation` takes the mean of the off-diagonal entries:

```python
mask = ~np.eye(corr.shape[0], dtype=bool)   # everything except the diagonal
values = corr.to_numpy()[mask]
```

The diagonal must be excluded because every asset correlates 1.0 with itself.
Including it would drag a genuinely diversified portfolio's average upward and
make it look worse, by an amount that depends on the holding count — so the
bias would differ between portfolios. O(m²) after the matrix exists.

### 6.4 `metrics.py` — the four ratios

All four divide an excess return by a *different* notion of risk, so they
disagree by design:

| Ratio | Numerator | Denominator | Answers |
|---|---|---|---|
| **Sharpe** | annual return − r_f | annualised total volatility | Return per unit of *all* variability |
| **Sortino** | annual return − MAR | downside deviation | Return per unit of *harmful* variability |
| **Calmar** | annual return | &#124;max drawdown&#124; | Return per unit of *worst realised loss* |
| **Treynor** | annual return − r_f | beta | Return per unit of *market* risk |

In the worked example: Sharpe 0.70, Sortino 1.01, Calmar 0.87, Treynor 0.12.
Sortino > Sharpe tells you the volatility is more upside than downside, which
is a real and useful distinction that Sharpe alone hides.

#### The `_ZERO_TOLERANCE` bug and its fix

This was a real bug found during the build. A constant return series — a cash
holding, say — has a standard deviation that floating-point arithmetic
computes as roughly `1e-18` rather than exactly `0`. Dividing by that:

```
sharpe_ratio = (0.055 − 0.06) / 1e-18  =  −1.9e16
```

A Sharpe ratio of negative nineteen quadrillion. The fix:

```python
_ZERO_TOLERANCE = 1e-12

def _is_effectively_zero(value: float) -> bool:
    return bool(np.isnan(value)) or abs(value) < _ZERO_TOLERANCE
```

and then, in all four ratios:

```python
if np.isnan(annual_return) or _is_effectively_zero(annual_vol):
    return float("nan")
```

The right answer when the denominator is zero is **undefined**, not infinity
and certainly not 1.9e16. The same guard protects Sortino (a portfolio that
never fell below the MAR), Calmar (a portfolio that never drew down) and
Treynor (a market-neutral portfolio with β ≈ 0).

#### `performance_summary` — the single entry point

```python
def performance_summary(returns, benchmark_returns=None,
                        risk_free_rate=DEFAULT_RISK_FREE_RATE,
                        periods_per_year=TRADING_DAYS_PER_YEAR) -> dict:
```

This is the function that both the API **and** the ML feature builders call.
That is the enforcement mechanism for promise #1: a portfolio's Sharpe is
computed by the same code path when training a model and when serving the Risk
page. It returns 16 keys, including `"risk_free_rate": 0.06` and
`"periods_per_year": 252` — the assumptions travel with the numbers.

**Complexity:** O(n) overall. It calls about ten O(n) functions over the same
series, so the constant is roughly 10, but the growth is linear. Adding a
benchmark adds the O(n log n) align.

### 6.5 `concentration.py` — seven measures

```python
def herfindahl_index(weights) -> float:
    w = normalize_weights(weights)
    return float((w ** 2).sum())
```

HHI = Σ wᵢ². Squaring is what makes it a concentration measure: a 50% position
contributes 0.25, while five 10% positions contribute 0.05 between them.

| Portfolio | HHI | Normalised HHI | Effective holdings |
|---|---|---|---|
| 4 equal positions | 0.2500 | **0.0000** | 4.00 |
| 80% / 10% / 5% / 5% | 0.6550 | **0.5400** | **1.53** |
| 1 position | 1.0000 | **1.0000** | 1.00 |

Read the middle row. It holds **four** stocks. It behaves like **1.53**. That
number — `1 / HHI` — is the single most communicative output in this module,
because "effective holdings: 1.5" lands with a user in a way "HHI = 0.655"
never will.

Raw HHI has a flaw: its floor is `1/n`, which moves with the holding count, so
0.25 means "perfectly diversified" for 4 holdings and "very concentrated" for
40. Normalised HHI fixes that:

```python
hhi = float((w ** 2).sum())
floor = 1.0 / n
return float((hhi - floor) / (1.0 - floor))
```

Now 0 always means perfectly equal-weighted and 1 always means a single
holding, whatever n is — so two portfolios of different sizes can be compared.
This is the version the Health Score uses.

`normalize_weights` handles three real-world input messes in five lines:

```python
series = pd.Series(weights, dtype="float64")
series = series.replace([np.inf, -np.inf], np.nan).dropna()
series = series[series > 0]              # drop shorts: the MVP does not model them
total = float(series.sum())
if series.empty or total <= 0:
    return pd.Series(dtype="float64")
return series / total
```

It accepts percentages (`40`) and fractions (`0.40`) identically, because it
divides by the sum either way. It drops negatives rather than letting a short
position silently distort the denominator.

**Complexity:** `herfindahl_index` O(n) time, O(n) space (the normalised copy).
`concentration_by_group` is O(n) for the map plus O(g log g) for the sort,
g = number of groups. `concentration_report` is O(n log n), dominated by
sorting the weights for display.

### 6.6 `portfolio.py` — the time-weighted return

This module exists for one function.

```python
def time_weighted_returns(values, cashflows=None):
    previous = v.shift(1)
    returns = (v - flows) / previous - 1.0
    returns[previous <= 0] = np.nan
    return returns.iloc[1:]
```

The formula is `r_t = (V_t − CF_t) / V_{t−1} − 1`, where CF_t is the net money
*added* during period t.

**Why this matters — a worked example with real output:**

```
month:        0        1        2        3
value:   100,000  110,000  125,000  130,000
deposit:       0        0   10,000        0

naive pct_change:   +10.0%   +13.64%   +4.0%      ← WRONG
time-weighted:      +10.0%    +4.55%   +4.0%      ← right
```

In month 2 the investor deposited ₹10,000. The naive calculation reads that
deposit as **+13.64% investment performance**. The portfolio actually earned
₹5,000 on ₹110,000 — **+4.55%**.

The damage is not just a wrong return. That inflated series then feeds
volatility (now too high), Sharpe (now wrong in both numerator and
denominator), max drawdown, beta, and the forecast target. One unsubtracted
deposit corrupts the entire analytics stack. Every return series this platform
reports for a contributing investor is time-weighted, including inside the
cohort simulator in stage 06.

The guard `returns[previous <= 0] = np.nan` handles a portfolio that was empty
last month: dividing by zero would give `inf`.

`money_weighted_return` is the complement — an XIRR by bisection:

```python
low, high = -0.9999, 10.0
for _ in range(200):          # bisection: robust where Newton diverges
    mid = (low + high) / 2.0
    f_mid = net_present_value(mid)
    if abs(f_mid) < 1e-9:
        return float(mid)
    ...
```

Bisection rather than Newton–Raphson, deliberately. Newton converges faster
but can diverge or oscillate on irregular cash-flow series; bisection cannot,
as long as the root is bracketed, which the sign check guarantees. 200
iterations halve the interval each time, so the precision is
`10.9 / 2^200` — overkill, and still instant.

The two returns answer different questions, which is why both exist:
time-weighted asks *how did the investments perform* (used for risk metrics);
money-weighted asks *what did I earn on my money* (rewards contribution
timing).

**Complexity:** `time_weighted_returns` O(n)/O(n).
`money_weighted_return` O(k · f) where k = 200 iterations and f = flows, so
O(200f) → effectively O(f). `portfolio_returns_from_weights` is O(mn) for an
m-asset, n-day frame.

### 6.7 `health.py` — the Portfolio Health Score

This is the project's signature feature, and the design decision behind it is
worth stating directly: **the score is an analytics engine, not a model.**

A learned score would have been easier to build — regress on something and
report the output. It would also be impossible to defend to the person whose
portfolio it judges. "Your score is 61 because the gradient boosting said so"
is not an explanation. So every component is a documented function of
measurable inputs, and the API returns the full derivation with each score.

#### The six components and their weights

```python
COMPONENT_WEIGHTS = {
    "diversification": 20.0,
    "risk":            20.0,
    "concentration":   15.0,
    "liquidity":       10.0,
    "goal_alignment":  20.0,
    "behaviour":       15.0,
}
```

The weights come from a stated rationale, not from tuning:

- **Diversification (20)** and **risk (20)** are highest because they drive the
  outcomes a retail investor is least equipped to see unaided.
- **Goal alignment (20)** matches them because a portfolio that is excellent in
  isolation can still be failing its purpose.
- **Concentration (15)** overlapped diversification in v1, so it was weighted
  below it. That overlap was a defect, not a reason for a weight: v1's
  diversification averaged an `evenness` sub-score computed from
  `hhi_normalized`, the same statistic concentration summarises, so weight
  dispersion drove two components the UI presents as independent. Probed with
  two portfolios of identical breadth differing only in weight dispersion, v1's
  diversification moves 13.67 points; v2's moves 0.00. v2 splits them cleanly —
  diversification measures breadth and independence, concentration measures
  weight dispersion — and keeps the weight at 15 because fixing the measure is
  a better answer than re-weighting around a broken one.
- **Behaviour (15)** is real but partly a matter of preference.
- **Liquidity (10)** is lowest because every asset in this universe is
  exchange-traded. In v1 that left it with 9.0 points of range across the
  scenario bank and a standard deviation of 2.7 — about three points of the
  hundred, which made it decorative. v1's refusal to re-scale a narrow real
  range was correct; the error was the measure. v2 adds the cash-and-debt
  buffer share against a 10% target, which portfolios genuinely differ on,
  taking the range to 54.5. The weight stays at 10 because it now buys ten
  real points rather than three.

#### Two scoring primitives

```python
def _ramp(value, worst, best) -> float:
    if np.isnan(value):
        return float("nan")
    if worst == best:
        return 100.0
    fraction = (value - worst) / (best - worst)
    return float(np.clip(fraction, 0.0, 1.0) * 100.0)
```

A linear map onto 0–100. It works in either direction, because `worst` may be
the *larger* number when lower is better: `_ramp(hhi_normalized, 0.6, 0.0)`
gives 100 at HHI 0 and 0 at HHI 0.6.

```python
def _band_score(value, low, high, under_penalty=0.6, over_penalty=1.0):
    if low <= value <= high:
        return 100.0
    width = max(high - low, 1e-9)
    if value < low:
        return max(0.0, 100.0 - 100.0 * ((low - value) / width) * under_penalty)
    return max(0.0, 100.0 - 100.0 * ((value - high) / width) * over_penalty)
```

Full marks inside a band, decaying outside it. Note the asymmetry:
`over_penalty = 1.0` but `under_penalty = 0.6`. Taking **more** risk than you
intended can cause a loss you never agreed to; taking **less** mostly costs
return. The two mistakes are not equally bad, so they are not scored equally.

The bands come from the user's own stated risk tolerance:

```python
RISK_TOLERANCE_VOLATILITY_BANDS = {
    "conservative": (0.04, 0.10),
    "moderate":     (0.08, 0.17),
    "aggressive":   (0.14, 0.28),
}
DRAWDOWN_TOLERANCE = {"conservative": 0.12, "moderate": 0.25, "aggressive": 0.40}
```

So the risk component does not ask "is this portfolio risky?" — it asks "is
this portfolio as risky as *this investor said they wanted*?" A 25% volatility
portfolio scores 100 for an aggressive investor and poorly for a conservative
one. Same portfolio, different answer, because the question is about fit.

#### Worked example — a complete score

Inputs: 12 holdings, 6 sectors, 4 asset classes, normalised HHI 0.18, average
pairwise correlation 0.42, volatility 14.9%, max drawdown −21.3%, moderate
tolerance, top-1 19%, top-5 63%, largest sector 31%, 62% equity / 18% ETF /
8% gold / 8% debt / 4% cash, goals set with progress 0.93 and funding 1.04,
turnover 34%, contributions in 83% of months, drift 11%.

| Component | Score | Weight | Contributes |
|---|---|---|---|
| Diversification | 73.6 | 20 | 14.72 |
| Risk | 78.7 | 20 | 15.74 |
| Concentration | 79.4 | 15 | 11.91 |
| Liquidity | 75.1 | 10 | 7.51 |
| Goal alignment | 78.8 | 20 | 15.77 |
| Behaviour | 87.3 | 15 | 13.09 |
| **Total** | | **100** | **78.7 → "Good"** |

The contributions sum to the total: 14.72 + 15.74 + 11.91 + 7.51 + 15.77 +
13.09 = 78.74. **The score is fully decomposable** — a user can see exactly
where each point came from, which is the PRD's explainability requirement
satisfied by construction rather than by a post-hoc attribution method.

Generated summary: *"Good (79/100). Strongest: behaviour (87). Weakest:
diversification (74)."*

#### Three bugs this component had, and the fixes

**1. An empty portfolio graded "Poor".** Scoring zero holdings as
diversification = 0 produced a total near 0 and a grade of "Poor". But an
empty account is not a badly built portfolio; it is an absence of data. Fixed
by returning `NaN`:

```python
if not data.n_holdings:
    return ComponentScore(..., score=float("nan"),
        reason="The portfolio holds nothing, so diversification cannot be assessed.")
```

**2. Liquidity scored 57.7 for a perfectly sound portfolio.** The first
version ramped between the best and worst *achievable* asset-class blends. But
every asset in this universe is exchange-traded and sellable within a day, so
the worst achievable blend (all equity, 0.70) is still perfectly liquid in
practice. Stretching that narrow real range across the whole 0–100 scale
manufactured large score differences out of a distinction that barely exists.
The fix reports the weighted rating directly:

```python
score = float(weighted_liquidity * 100.0)
```

All-equity now scores 70, all-cash 100, and the reason string says plainly
that this component varies little between portfolios in this universe. Less
dramatic, more honest.

**3. Missing components silently penalised the user.** A user with no goals
would lose all 20 goal-alignment points. Fixed by renormalising:

```python
scored  = [c for c in components if not np.isnan(c.score)]
missing = [c.name for c in components if np.isnan(c.score)]
available_weight = sum(c.weight for c in scored)
total = sum(c.score * c.weight for c in scored) / available_weight
```

With no goals, the remaining five components carry weight 80, and the total is
divided by 80 instead of 100. The summary then says *"Scored on 5 of 6
components; goal alignment could not be measured."* The user is told what was
skipped rather than quietly marked down for it.

#### `sensitivity_analysis` — proving explainability

```python
baseline = compute_health_score(data).total
# for each numeric input: shift up and down, re-score, record the swing
```

Required by the PRD as evidence the score is explainable. Each input is nudged
±10% and the total re-scored. Real output for the example portfolio:

| Input | Baseline | If increased | If decreased | Swing | Direction |
|---|---|---|---|---|---|
| `goal_funding_ratio` | 1.04 | 79.59 | 77.25 | **2.34** | higher is better |
| `goal_progress_ratio` | 0.93 | 79.90 | 77.57 | **2.33** | higher is better |
| `top_5_weight` | 0.63 | 78.10 | 79.36 | 1.26 | lower is better |
| `max_drawdown` | −0.213 | 79.16 | 78.31 | 0.85 | higher is better |
| `contribution_consistency` | 0.83 | 79.15 | 78.32 | 0.83 | higher is better |
| `max_sector_weight` | 0.31 | 78.39 | 79.08 | 0.69 | lower is better |

This portfolio's score is driven mostly by its goals, then by concentration.
That is actionable in a way a single number is not.

One refinement was needed here. Inputs already at full marks showed as "lower
is better" with a swing of 0, which was misleading — the input had no effect
*at this level*, not an inverted relationship. A `saturated: True` flag and the
label `"no effect at this level"` were added.

**Complexity:** `compute_health_score` is **O(1) given its inputs** — six
components, each a fixed number of arithmetic operations. The expensive work
(correlation, volatility, drawdown) happens before the score, in the services.
`sensitivity_analysis` re-scores for each of ~14 inputs × 2 directions = 28
calls of O(1) work, so also effectively O(1).

### 6.8 `goals.py` — projections and Monte Carlo

#### Deterministic projection

```python
def future_value(present_value, monthly_contribution, annual_return, months):
    monthly_rate = (1.0 + annual_return) ** (1.0 / MONTHS_PER_YEAR) - 1.0
    if abs(monthly_rate) < 1e-12:
        return float(present_value + monthly_contribution * months)
    growth = (1.0 + monthly_rate) ** months
    return float(present_value * growth
                 + monthly_contribution * (growth - 1.0) / monthly_rate)
```

FV = PV(1+r)ⁿ + PMT · ((1+r)ⁿ − 1)/r — the standard annuity formula.

The first line matters more than it looks. The monthly rate is derived
**geometrically**: `(1.11)^(1/12) − 1 = 0.008735`, not `0.11/12 = 0.009167`.
The second is the common shortcut and it overstates: compounded over 76 months
it inflates the projection by about 3.5%. Since the whole point is that
projections should not flatter, it uses the geometric form.

The zero-rate branch avoids a division by zero; with no growth the answer is
simply contributions × months.

**Complexity:** O(1) — closed form. `projection_path` is O(m) for m months
because the chart needs every intermediate value. `required_monthly_contribution`
is the same formula rearranged for PMT, also O(1).

#### The scenario band, and the bug that forced a rethink

```python
years = max(months / MONTHS_PER_YEAR, 1.0 / MONTHS_PER_YEAR)
return_standard_error = return_volatility / np.sqrt(years)
```

This two-line calculation replaced a real bug. The first version used the full
annual volatility (σ = 14%) as the scenario offset, so the optimistic case
assumed 25% returns *every year for seven years* and the pessimistic case
assumed −3% every year. The resulting band ran from **90% funded to 642%
funded** — not an uncertainty range so much as an arithmetic artifact.

The error was conceptual. Single-year volatility does not persist as a
permanent shift in the long-run average. Good and bad years partially offset,
so the **mean** return over a long horizon is far more tightly determined than
any single year's return. The right spread is the standard error of that
average, σ/√years.

With σ = 14% over 6.3 years, the offset becomes 14%/√6.3 = **5.6%**, and the
band is believable:

| Scenario | Annual return | Projected value | Funded |
|---|---|---|---|
| Pessimistic | 5.44% | ₹34,40,978 | 69% |
| Expected | 11.00% | ₹43,26,923 | 87% |
| Optimistic | 16.56% | ₹54,32,851 | 109% |

A band is shown rather than a point estimate for a specific reason stated in
the module docstring: *presenting one figure invites it to be read as a
promise.*

#### `progress_ratio` — the metric that distinguishes two very different users

```python
if started_on is not None:
    elapsed = months_between(started_on, as_of)
    total_months = elapsed + months
    expected_by_now = target_amount * (elapsed / total_months)
progress_ratio = current_amount / expected_by_now
```

This compares what has actually been saved with what a straight-line plan
would have accumulated *by now*. A plain percent-of-target figure cannot tell
apart two people both at 17% of their goal: one started last month and is
contributing hard, the other started in 2019 and has stalled. `progress_ratio`
separates them — 1.0 means exactly on trajectory.

#### `monte_carlo_paths` — the honest answer

The deterministic projection answers "what if returns are exactly average
every single month", which never happens. This answers the better question.

```python
rng = np.random.default_rng(seed)                              # seeded: reproducible
monthly_rate  = (1.0 + annual_return) ** (1.0 / 12) - 1.0
monthly_sigma = annual_volatility / np.sqrt(12)                # √time scaling

draws = rng.normal(monthly_rate, monthly_sigma, size=(n_paths, months))
np.clip(draws, -0.95, None, out=draws)                         # no sub-total-loss month

values = np.empty((n_paths, months + 1), dtype="float64")
values[:, 0] = float(current_amount)
for month in range(months):
    values[:, month + 1] = values[:, month] * (1.0 + draws[:, month]) + monthly_contribution
```

Line by line:

- `default_rng(seed)` with `seed = 42` by default, so a demo is reproducible —
  the same inputs give the same fan every time.
- `annual_volatility / √12` is the square-root-of-time rule: volatility scales
  with the square root of the horizon, not linearly. 14% annual → 4.04% monthly.
- `size=(n_paths, months)` generates all 2,000 × 76 = 152,000 draws in **one**
  NumPy call. A Python double loop would be roughly 100× slower.
- `np.clip(..., -0.95, None, out=draws)` floors a month at −95%. Without it, a
  normal draw can exceed −100% and the portfolio value goes negative, which is
  not a thing that happens. `out=draws` clips in place — no second 152,000-element array.
- **The loop is over months (76), not paths (2,000).** Each iteration does
  vectorised work on all 2,000 paths at once. Looping the other way would be
  2,000 iterations of 76 scalar operations: same arithmetic, ~26× the Python
  interpreter overhead.
- Contributions are added **after** growth, matching `project_goal`'s
  end-of-month convention. If the two disagreed, the fan's median would not
  line up with the deterministic line and nobody would know which was wrong.

**Real output** (₹8.5L now, ₹25k/month, 11% expected, 14% volatility, 76 months,
₹50L target):

| | Value |
|---|---|
| Deterministic projection | ₹43,26,923 |
| Monte Carlo p10 | ₹29,96,484 |
| Monte Carlo p25 | ₹34,76,262 |
| **Monte Carlo p50 (median)** | **₹41,21,167** |
| Monte Carlo p75 | ₹49,00,600 |
| Monte Carlo p90 | ₹58,23,784 |
| **Probability of reaching ₹50L** | **23.3%** |

Two things to notice.

**The median (₹41.2L) is below the deterministic projection (₹43.3L).** That
gap is **volatility drag**, and it is not a bug. Because returns compound
multiplicatively, a −20% year followed by a +20% year leaves you at 0.8 × 1.2
= 0.96, not 1.00. Volatility costs you money even when the average return is
unchanged. The deterministic line ignores this; the simulation cannot.

**The deterministic view says "87% funded"; the simulation says "23% chance of
getting there".** Both are true and they answer different questions. The first
is the single most likely trajectory; the second is how often that trajectory
or better actually occurs. Showing only the first would be the misleading
choice.

A validation check: with `annual_volatility = 0.0`, all five percentiles
collapse to exactly ₹43,26,923 — the deterministic value. Zero uncertainty,
zero fan. That is a unit test in `tests/test_goals.py`.

And the honesty note, returned with every simulation and printed by the UI:

> *"A range of outcomes under these assumptions, not a prediction. Real returns
> have fatter tails and more negative skew than a normal distribution, so the
> extreme bands are if anything optimistic."*

**Complexity:**
- Time: **O(P · M)** where P = paths, M = months. 2,000 × 76 = 152,000 for the
  draws, the same for the accumulation, then 5 percentile passes of O(P) each
  per month via partitioning → O(M · P). Total ≈ 10⁶ operations, which runs in
  about 25 ms.
- Space: **O(P · M)** = the `values` array, 2,000 × 77 × 8 bytes ≈ **1.2 MB**,
  plus the same again for `draws`. For a 50-year goal (600 months) that becomes
  2,000 × 601 × 8 ≈ 9.6 MB — still fine, which is why `SIMULATION_BOUNDS` caps
  months at 600.

---

## 7. The database

PostgreSQL 17, nine tables, one Alembic migration
(`51242919357c_initial_schema.py`). SQLAlchemy 2.0 declarative models with
`Mapped[...]` typing, so the schema is type-checked.

### The nine tables

```
users ──┬── holdings ───── assets ──── market_prices
        ├── transactions ──┘
        ├── goals
        ├── portfolio_snapshots
        ├── model_outputs
        └── alerts
```

#### `users`
Identity plus the investor profile that personalises the analysis: `age`,
`annual_income`, `monthly_savings`, `risk_tolerance`, `investment_horizon_years`.
`risk_tolerance` is what selects the volatility band in the Health Score, so
this is not decoration — it changes the score.

#### `assets` — the shared universe
58 rows: 51 from the MVP universe plus composites. Columns: `symbol` (unique,
indexed), `name`, `asset_class`, `sector`, `status`, `price_source`, `note`.

`price_source` and `note` exist for auditability. `DEBT` is a *composite*
asset built by splicing two series, and its `note` says so. Months later,
nobody has to reverse-engineer where a number came from.

#### `market_prices` — 232,287 rows

```python
__table_args__ = (
    UniqueConstraint("asset_id", "date", name="asset_date"),
    Index("ix_market_prices_asset_date", "asset_id", "date"),
    Index("ix_market_prices_date", "date"),
    CheckConstraint("close > 0", name="close_positive"),
)
```

- The **unique constraint** makes stage 04 idempotent: re-running it updates
  rather than duplicating. Without it, running the seed twice would double
  every price series and silently halve every return.
- The **composite index** `(asset_id, date)` is the shape of every query —
  "prices for asset X between dates A and B" — so Postgres does one B-tree
  descent and then a sequential range scan: **O(log N + k)** for k rows.
- The **check constraint** `close > 0` is enforced by the *database*, not by
  Python. A zero price would make `simple_returns` produce `inf`. Defending at
  the storage layer means no code path can get it wrong.

#### `holdings`

```python
UniqueConstraint("user_id", "asset_id", name="user_asset"),
CheckConstraint("quantity > 0", name="quantity_positive"),
CheckConstraint("average_price > 0", name="average_price_positive"),
```

The unique constraint is the one that caught a real bug. A CSV with INFY on
two rows (two purchase lots, which is completely normal) violated it. The
right fix was not to drop the constraint — it was to **merge the lots at
their weighted average cost** before writing. Without the constraint, that
duplicate would have silently double-counted INFY in every weight, every HHI,
and every correlation.

#### `transactions`
Append-only log. `asset_id` is **nullable** on purpose, because a deposit or
withdrawal is a cash flow with no asset attached — and those flows are exactly
what `time_weighted_returns` needs to subtract.

#### `portfolio_snapshots`
A monthly point-in-time record: value, invested amount, net contribution, the
five allocation percentages, and the computed metrics. Unique on
`(user_id, date)`.

This table is the bridge between the real user and the trained models. The
models learned from monthly snapshots of simulated investors, so a real user's
holdings have to be turned into the same shape — which is what
`ml_runtime/features.py` does.

#### `model_outputs`
Stores predictions with `model_name`, `model_version`, `as_of_date`, and a
**JSONB** `payload`. JSONB because a cluster assignment, an anomaly score and
a four-horizon forecast have genuinely different shapes, and inventing a
column per model would mean a migration every time a model changes.

#### `alerts`
Generated findings with `severity`, `metric_value`, `threshold` and an
`is_read` flag. Indexed on `(user_id, created_at)` for the newest-first query.

### The patterns used across all nine tables

**Every constraint is named.**

```python
CheckConstraint("quantity > 0", name="quantity_positive")
```

Unnamed constraints get auto-generated names that differ between Postgres
versions, which makes a later Alembic migration that drops one fail
unpredictably. Naming them is two seconds now and saves an afternoon later.

**`ON DELETE CASCADE` on every user-owned foreign key.** Deleting a user
removes their holdings, transactions, goals, snapshots, outputs and alerts in
one statement, at the database level. No orphan rows, no cleanup code to
forget.

**A `TimestampMixin`** gives `created_at` / `updated_at` with server-side
defaults, so the timestamps come from the database clock rather than from
whichever machine happened to run the code.

### Connection pooling

```python
engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,   # recycle connections the server has dropped
    pool_size=10,
    max_overflow=20,
)
```

`pool_pre_ping=True` issues a cheap `SELECT 1` before handing out a pooled
connection. Managed Postgres providers close idle connections; without the
ping, the first request after an idle period fails with a stale-connection
error. One flag, one class of production bug avoided.

```python
SessionLocal = sessionmaker(bind=engine, autocommit=False,
                            autoflush=False, expire_on_commit=False)
```

- `autoflush=False` — SQLAlchemy will not sneak an INSERT in before a SELECT.
  This is what made the duplicate-CSV bug *visible* rather than intermittent.
  The fix adds an explicit `db.flush()` where one is actually needed.
- `expire_on_commit=False` — objects stay usable after commit. Without it,
  returning a committed ORM object from an endpoint triggers a fresh SELECT
  per attribute access during serialisation.

**Complexity of the common queries:**

| Query | Index used | Complexity |
|---|---|---|
| User by id (auth, every request) | primary key | O(log N) |
| Holdings for a user, with assets joined | `ix_holdings_user_asset` + `joinedload` | O(log N + h), **one** query |
| Price history, asset × date range | `ix_market_prices_asset_date` | O(log N + k) |
| Newest alerts for a user | `ix_alerts_user_created` | O(log N + k) |

The `joinedload` detail matters. Without it, fetching 12 holdings and then
reading `holding.asset.sector` on each one fires 1 + 12 = 13 queries — the
classic N+1 problem. With it, one query:

```python
select(Holding).where(Holding.user_id == user.id).options(joinedload(Holding.asset))
```

---

## 8. The backend API

FastAPI, **30 endpoints** across 7 routers, 6,637 lines including 145 tests.

### 8.1 `main.py` — the application

#### The lifespan: warming the cache

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    with SessionLocal() as db:
        market_cache.load(db)
        panel = market_cache.panel(db)
```

At startup the entire price panel is read from Postgres and pivoted into one
wide pandas DataFrame: **4,069 dates × 58 assets**. Why:

- In RAM that is 4,069 × 58 × 8 bytes ≈ **1.9 MB**. Trivial.
- Every analytics request becomes a slice of an in-process frame instead of a
  database round trip. That is what keeps the risk endpoints under the PRD's
  sub-second budget.
- Market prices are **reference data** — identical for every user, changed
  only by the pipeline — so a process-wide shared cache cannot leak anything
  between accounts. A cache of *user* data would be a security problem; this
  is not.

```python
except Exception as exc:
    log.error("market cache failed to load: %s", exc)
```

A cold cache must not stop the API from booting. Logging in and viewing a
profile does not need prices, so a data problem should not prevent a login.
Endpoints that *do* need prices report the problem themselves.

#### The timing middleware

```python
@app.middleware("http")
async def add_timing_header(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Response-Time-ms"] = f"{(time.perf_counter()-started)*1000:.1f}"
    return response
```

Six lines that turn "responses should be fast" into a measurable number on
every single response. You can watch it in the browser's network tab.

#### The exception handler

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500,
        content={"detail": "An internal error occurred. The incident has been logged."})
```

A security measure. A raw stack trace tells an attacker your file paths, your
library versions and your table names. The detail goes to the server log; the
client gets a generic message.

#### `/health`
Reports status, environment, database connectivity, asset count, latest price
date and whether the Copilot is in `llm` or `fallback` mode. Degrades to
`"status": "degraded"` rather than throwing, so a monitor gets a usable answer
even when Postgres is down.

### 8.2 `core/config.py` — typed settings

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")
    database_url: str = Field(default="postgresql+psycopg://localhost:5432/wealthos",
                              alias="DATABASE_URL")
    jwt_secret_key: str = Field(default="insecure-development-key", alias="JWT_SECRET_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    copilot_model: str = Field(default="claude-opus-5-5", alias="COPILOT_MODEL")

    @property
    def copilot_enabled(self) -> bool:
        return bool(self.anthropic_api_key.strip())
```

```python
@lru_cache
def get_settings() -> Settings:
    return Settings()
```

`@lru_cache` means the `.env` file is parsed **once per process**, not on every
import. `copilot_enabled` is the single switch that decides which of the two
Copilot paths runs — one property, checked in one place.

The default JWT secret is deliberately named `"insecure-development-key"`. If
it ever appears in a production deployment, the name is the alarm.

### 8.3 `core/security.py` — passwords and tokens

```python
MAX_PASSWORD_BYTES = 72

def hash_password(password: str) -> str:
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"password exceeds {MAX_PASSWORD_BYTES} bytes, which bcrypt would truncate")
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")
```

**This is a real vulnerability, closed.** bcrypt silently truncates input at 72
bytes. A user with a 100-character passphrase would find that only the first 72
characters matter — so a *shorter prefix* of their password would
authenticate. Most implementations accept this silently. This one rejects the
input and says why.

```python
def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False     # a malformed stored hash is a failed login, not a crash
```

`bcrypt.checkpw` compares in constant time, so an attacker cannot learn how
many leading characters were right by measuring how long the comparison took.

```python
payload = {"sub": str(subject), "exp": expire,
           "iat": datetime.now(timezone.utc), "type": "access"}
```

```python
if payload.get("type") != "access":
    return None
```

The `type` claim is forward-looking defence. If a refresh token or a
password-reset token is added later, it will carry a different type, and this
check means it cannot be replayed against a protected endpoint. Adding the
claim now costs one line; retrofitting it after a token-confusion bug costs a
lot more.

**Complexity:** bcrypt is **intentionally expensive** — about 2^12 key
derivations, roughly 250 ms. That is the security property, not a performance
problem: it makes offline brute-forcing a stolen hash table infeasible. JWT
encode/decode is O(1) (an HMAC over a short string).

### 8.4 `api/deps.py` — the entire authorisation boundary

```python
def get_current_user(db: DbSession, credentials) -> User:
    if credentials is None or not credentials.credentials:
        raise CREDENTIALS_ERROR
    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise CREDENTIALS_ERROR
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise CREDENTIALS_ERROR from None
    user = db.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise CREDENTIALS_ERROR
    if not user.is_active:
        raise HTTPException(403, "Account is disabled")
    return user
```

This function and the `user.id` filter in every query are **the only
mechanism** preventing one account from reading another's portfolio. It is
worth knowing that explicitly.

Three details:

- Every failure path raises the **same** `CREDENTIALS_ERROR`. A missing token,
  a forged token, an expired token and a deleted user are indistinguishable to
  the caller. Different messages would let an attacker enumerate valid user ids.
- `raise ... from None` suppresses the chained exception, so a malformed `sub`
  claim does not leak a Python traceback into the response.
- The database is checked, not just the token. A user deleted or disabled five
  minutes ago is rejected even though their signed JWT is still technically valid.

```python
CurrentUser = Annotated[User, Depends(get_current_user)]
```

Then every protected endpoint is simply:

```python
def get_portfolio(db: DbSession, user: CurrentUser) -> dict:
```

FastAPI resolves the dependency before the function body runs. An endpoint
cannot *accidentally* be public — omitting `user: CurrentUser` is visible in
one line of the signature. This is what makes the test
`test_research_requires_no_auth_but_leaks_no_user_data` meaningful: the
research endpoint is the *only* one without it, and that is deliberate.

### 8.5 The service layer — nine modules

#### `market_service.py` — the price cache

```python
class MarketDataCache:
    """Process-wide cache of the adjusted price panel."""
```

| Method | What it does | Complexity |
|---|---|---|
| `load(db)` | Reads 232,287 rows, pivots to 4,069 × 58 | O(R) time, O(D·A) ≈ 1.9 MB space |
| `panel(db)` | Returns the wide frame | O(1) |
| `latest_prices(db)` | Last **non-null** price per column | O(D·A) |
| `price_history(db, symbols, start, end)` | Date+column slice | O(d·m) |
| `returns(db, symbols, start, end)` | `pct_change` over the slice | O(d·m) |
| `sector_map` / `asset_class_map` | Dicts from asset metadata | O(A) |

`latest_prices` deserves its comment:

```python
# Uses the last non-null observation per column rather than the final row,
# so an asset that did not trade on the last date is still priced.
```

Taking `panel.iloc[-1]` would return `NaN` for any asset that did not trade on
the final date — a suspended stock, a thinly traded ETF — and that `NaN` would
propagate into the portfolio total, making the user's entire net worth read as
`NaN`. Using the last valid observation per column avoids that.

#### `portfolio_service.py` — valuation and CSV import

**The cost-basis warning.** This solved a genuinely confusing problem:

```python
COST_BASIS_PLAUSIBLE_BAND = (0.67, 1.5)
CORPORATE_ACTION_FACTORS = (2.0, 3.0, 4.0, 5.0, 10.0, 0.5, 0.2, 0.1)
```

The platform's prices are **adjusted** for splits and bonuses. But an investor
naturally types the rupee price they actually paid. If HDFCBANK did a 1:2
bonus, the adjusted historical price is half what they paid, and their
"average price" looks 2.03× too high — so the app would report a 50% loss on a
profitable position.

The fix does not silently rescale the user's input. It detects the ratio, tests
it against known corporate-action factors, and tells them:

> *"Your cost basis is 2.03× the adjusted price on that date, which is close to
> a 1:2 corporate action factor. Prices here are adjusted for splits and
> bonuses; your entry price may not be."*

Naming the cause is better than either ignoring it or quietly "fixing" the
user's data.

**CSV import — validate everything before writing anything.**

```python
REQUIRED_CSV_COLUMNS = {"symbol", "quantity", "average_price"}
OPTIONAL_CSV_COLUMNS = {"asset_type", "purchase_date"}
MAX_IMPORT_ROWS = 5000
```

```python
"""Validation runs over the whole file before anything is written. A file with
any invalid row is rejected in full, because a partially imported portfolio
produces analytics that are confidently wrong."""
```

That last clause is the reasoning. A half-imported portfolio does not look
broken — it looks like a portfolio. Every weight, every HHI, every correlation
would be computed on incomplete holdings and reported with full confidence.
All-or-nothing is the only safe behaviour, and the response returns a per-row
error list so the user can fix the file.

`_parse_date` accepts the formats an Indian retail investor actually pastes:
`DD/MM/YYYY`, `DD-MM-YYYY`, `YYYY-MM-DD`, and a few more.

**Complexity:** `get_holdings` O(log N + h) in one query; `value_holdings`
O(h); `build_summary` O(h log h) for the top-holdings sort; `import_holdings_csv`
O(r) parse + O(r) validate + O(r) upsert, r ≤ 5,000.

#### `risk_service.py` — turning holdings into return series

```python
MIN_OBSERVATIONS_FOR_RISK = 60
LOOKBACK_WINDOWS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252, "3y": 756, "5y": 1260}
```

60 observations ≈ three months. Below that, a volatility estimate is noise, so
the service raises `InsufficientHistory` and the endpoint returns a stated
reason rather than a confident-looking wrong number.

The key function and its honesty:

```python
def portfolio_return_series(db, user, start=None, end=None):
    """Returns are computed on today's weights held fixed across history. This
    answers "how risky is the portfolio I hold now", which is what the Risk
    page asks. It is deliberately not a transaction-accurate replay of what
    the investor actually earned, and the metadata says so."""
```

And the metadata really does say so:

```python
metadata = {
    "method": "current weights held constant over history",
    "symbols_used": [...], "symbols_excluded": [...],
    "observations": int(len(portfolio_returns)),
    "risk_free_rate": DEFAULT_RISK_FREE_RATE,
    "benchmark": BENCHMARK_SYMBOL,
    "rebalancing": "daily (the weighted series assumes continuous rebalancing)",
}
```

Three limitations stated in the response itself: the weights are current not
historical, the series assumes daily rebalancing, and any symbol with
insufficient history is listed as excluded. Each of those would be a valid
criticism; printing them pre-empts it.

The graceful-degradation ladder:

```python
usable = asset_returns.dropna(how="any")      # dates where EVERY holding has a price
if len(usable) < MIN_OBSERVATIONS_FOR_RISK:
    coverage = asset_returns.notna().mean()
    keep = coverage[coverage > 0.9].index.tolist()   # assets with >90% coverage
    usable = asset_returns[keep].dropna(how="any")
    weights = weights[keep]
```

One newly listed holding would otherwise collapse the common window to a few
weeks and make the whole portfolio unanalysable. So assets with more than 90%
coverage are kept, the recent listing is dropped, and `symbols_excluded` names
it.

**Complexity:** dominated by the correlation matrix, **O(m²n)**. For 12
holdings × 4,069 days ≈ 586k operations. The window loop in `analytics` runs
`performance_summary` six times over nested windows: O(6n) = O(n).

#### `health_service.py` — gathering the inputs

```python
BEHAVIOUR_WINDOW_DAYS = 365
```

```python
"""All three need transaction history. Where there is none they are left as
NaN so the health score drops the component rather than scoring the user
badly for data the platform does not have."""
```

Three behaviour metrics — turnover, contribution consistency, allocation drift
— all require a transaction log. A user who just signed up has none. `NaN` and
renormalise, as established in section 6.7.

#### `goal_service.py` — bounded estimation

```python
FALLBACK_EXPECTED_RETURN = 0.10
FALLBACK_VOLATILITY = 0.12
RETURN_ESTIMATE_BOUNDS = (0.02, 0.18)
```

```python
"""Derived from the user's own holdings where there is enough history,
otherwise from a stated fallback. The estimate is bounded, because
extrapolating a short window produces absurd long-run assumptions."""
```

This bound is important. A portfolio that happened to return 47% over the last
eight months would, unbounded, project at 47% a year for fifteen years and
produce a gloriously fictional number. Clamping to 2–18% keeps the projection
in the range of plausible long-run equity outcomes. The clamp is stated in the
response's assumptions, so the user can see it was applied.

```python
SIMULATION_BOUNDS = {
    "annual_return":        (-0.10, 0.30),
    "annual_volatility":    (0.0, 0.60),
    "monthly_contribution": (0.0, 10_000_000.0),
    "months":               (1, 600),
}
SIMULATION_PATHS = 2000
```

Input validation for the scenario simulator. A user who drags the return
slider to 500% should get a clamped value and a stated assumption, not a
nonsense fan or a 10-million-element array.

```python
def _current_amount(db, user, goal):
    """The MVP attributes the whole portfolio to each goal rather than
    earmarking assets, so a user with several goals sees each measured against
    the same pool. This is stated in the response."""
```

A genuine simplification, stated rather than hidden. Per-goal asset earmarking
is listed in `docs/limitations.md` as future work.

#### `insight_service.py` — model-backed panels

```python
MIN_MONTHS_FOR_PROFILE = 6
MIN_MONTHS_FOR_SEQUENCE = 24
UNAVAILABLE = {"available": False,
               "reason": "The trained model artifact is not present. Run the ml pipelines to build it."}
```

`MIN_MONTHS_FOR_SEQUENCE = 24` is not arbitrary: the LSTM and GRU were trained
on 24-month windows, so they cannot be fed 18 months. The service checks and
reports rather than padding with zeros, which would produce a confident
prediction from invented history.

Every function here returns `{"available": false, "reason": "..."}` instead of
raising. **A missing file should disable one panel of the dashboard, not break
the page.**

#### `ml_runtime/registry.py` — artifact loading

```python
class ModelRegistry:
    """Lazily loads and caches the trained model artifacts.
    If one is missing the platform keeps working and the affected endpoint
    reports that the model is unavailable, rather than the whole API failing
    to boot."""
```

Artifacts load **once per process** and stay in memory. The autoencoder is
2,878 parameters (~11 KB); the LSTM 6,561 (~26 KB); the K-Means model 7
centroids × 15 features. All of them together are under a megabyte. XGBoost
with up to 1,500 trees is the largest, at a few MB.

`status()` reports which loaded and which did not, and feeds both `/health`
and the Insights page.

#### `ml_runtime/features.py` — the hardest honest problem

```python
"""The models were trained on monthly snapshots of simulated investors. A real
user has holdings and a transaction log, so this module reconstructs the
equivalent monthly history: it values the current positions back through the
real price panel and overlays any recorded cash flows. The reconstruction is
explicitly approximate, and every caller states so."""
```

This is the train/serve bridge and the place where honesty matters most. The
models learned from 1.25 million simulated investor-months. A real user has
twelve holdings and maybe three transactions. The reconstruction values
*today's* positions back through history — so it assumes the user always held
what they hold now.

That assumption is wrong for anyone who has traded. The module says so, and
every endpoint that uses it repeats the caveat. The alternative — presenting
reconstructed history as if it were observed — would be the dishonest option.

| Function | What it builds | Complexity |
|---|---|---|
| `monthly_history(db, user)` | Monthly snapshot frame from holdings + prices + flows | O(h · d) |
| `market_context(month_ends)` | Market-regime features aligned to those months | O(d) |
| `behavioural_profile(history)` | The 15 clustering features | O(m) |

### 8.6 All 30 endpoints

#### `auth.py` — 4 endpoints

| Method | Path | What it does |
|---|---|---|
| POST | `/api/v1/auth/register` | Create account, return a JWT |
| POST | `/api/v1/auth/login` | Exchange email + password for a JWT |
| GET | `/api/v1/auth/me` | The current profile |
| PATCH | `/api/v1/auth/me` | Update the investor profile |

#### `portfolio.py` — 9 endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/portfolio` | Value, gain, allocation breakdowns (Overview) |
| GET | `/portfolio/holdings` | Every holding, priced, with weight and gain |
| POST | `/portfolio/holdings` | Add a position (merges on conflict) |
| PATCH | `/portfolio/holdings/{id}` | Update quantity or cost |
| DELETE | `/portfolio/holdings/{id}` | Remove a position |
| POST | `/portfolio/import` | CSV upload, max 2 MB, all-or-nothing |
| GET | `/portfolio/transactions` | The transaction log |
| POST | `/portfolio/transactions` | Record a trade or a cash flow |
| GET | `/portfolio/assets` | The investable universe, for pickers |

```python
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
```

A size cap before parsing. Without it, a 2 GB upload would be read into memory
before any validation ran.

#### `analytics.py` — 3 endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/analytics` | Returns and ratios across six windows |
| GET | `/analytics/risk` | Volatility, drawdown detail, VaR, CVaR, beta, alpha, correlation matrix |
| GET | `/analytics/concentration` | HHI, effective holdings, sector and class concentration, plain-language notes |

#### `goals.py` — 8 endpoints

| Method | Path | What it does |
|---|---|---|
| GET | `/goals` | List goals |
| POST | `/goals` | Create one |
| GET | `/goals/{id}` | One goal |
| PATCH | `/goals/{id}` | Update |
| DELETE | `/goals/{id}` | Delete |
| GET | `/goals/{id}/forecast` | Projection with the three-scenario band |
| **POST** | **`/goals/{id}/simulate`** | **Monte Carlo fan + success probability** |
| GET | `/goals/health-score` | The decomposable Health Score |

```python
def _owned_goal(db, user, goal_id) -> Goal:
    """Fetch a goal, scoped to its owner."""
```

Every one of the six per-goal endpoints goes through this. Requesting another
user's goal returns **404, not 403** — deliberately. A 403 confirms the goal
exists; a 404 reveals nothing. There is a test for exactly this.

#### `insights.py` — 4 endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/insights/profile` | Which behavioural cluster this portfolio resembles |
| GET | `/insights/anomalies` | Months the autoencoder could not reconstruct |
| GET | `/insights/forecast` | Projected value from the trained models |
| GET | `/insights/models` | Which artifacts loaded |

#### `copilot.py` — 2 endpoints

| Method | Path | What it does |
|---|---|---|
| POST | `/copilot/chat` | Ask a question; returns answer + tool calls + grounding report |
| GET | `/copilot/capabilities` | What it can do and which path is active |

#### `research.py` — 3 endpoints (the only public ones)

```python
MODEL_REPORTS = ("clustering", "anomaly_detection", "copilot_groundedness",
                 "forecast_1m", "forecast_3m", "forecast_6m", "forecast_12m",
                 "features", "cluster_map")
DATA_REPORTS  = ("ingest_quality", "price_build", "adjustment_impact",
                 "external_fetch", "big_sharks_priors", "cohort", "database_seed")
```

| Method | Path | Returns |
|---|---|---|
| GET | `/research/reports` | All 16 reports, grouped |
| GET | `/research/reports/{name}` | One report |
| POST | `/research/reports/refresh` | Drop the cache after a pipeline re-run |

This is the only unauthenticated router, for a stated reason:

```python
"""They carry no user data: every figure describes the training cohort or the
market data, so the endpoint needs no auth and touches no user tables."""
```

It also reads **no database at all** — only JSON files from `ml/reports/`,
cached in memory on first read. That is what lets the landing page quote live
model metrics to an anonymous visitor without opening any hole. There is a
test asserting it returns 200 without a token *and* that nothing in the
payload resembles user data.

```python
def _load(name: str) -> dict:
    """A missing report disables one panel rather than failing the page, which
    matches how the model endpoints already degrade."""
```

Same convention as `insight_service`: `{"available": false, "reason": "..."}`.

---

## 9. The data pipeline (stages 01–07)

Twelve numbered scripts under `ml/pipelines/`. Three properties hold for all
of them:

1. **Independently re-runnable.** Stage 08 does not require re-running stage 01.
2. **Every stage writes evidence.** 19 JSON files in `ml/reports/`. The project
   can show *what it found*, not just what it built.
3. **Validation gates fail loudly.** A `PipelineError` aborts the stage rather
   than writing data that looks plausible and is silently wrong.

### 9.0 `common.py` — the shared plumbing

```python
class Stage:
    """Context manager that logs a pipeline stage and how long it took."""
```

```python
with Stage(log, "build the adjusted price panel"):
    ...
```

Timed, labelled log lines for free. When `make all` takes 42 minutes, the log
says which stage took which part of it.

```python
class PipelineError(Exception):
    """Raised when a validation gate fails. Pipelines fail loudly rather than
    writing suspect data: a silent data defect propagates into every
    downstream metric and model."""
```

```python
def find_column(frame, candidates):
    """Locate the column best matching any of `candidates`.
    Kaggle dataset revisions rename columns between versions, so column
    identification is done by matching rather than by hard-coding."""
```

A small piece of real-world defensiveness. The Kaggle dataset has shipped
revisions where `Close` became `Close Price` became `close_price`. Matching on
a simplified key (`"Open Price"` → `"openprice"`) means a dataset refresh does
not break the ingest.

```python
def silence_accelerate_matmul_warnings():
    """Suppress a known false positive from numpy on Apple's Accelerate BLAS."""
```

NumPy 2.x on macOS Accelerate emits "divide by zero / overflow / invalid value
encountered in matmul" on matrix products containing no such values. This was
**verified as spurious** before being silenced — tested on a clean random
matrix product that produced the warning with no problematic values anywhere.
The filter matches the exact message text only, so a genuine overflow
elsewhere still surfaces.

### 9.1 Stage 01 — ingest the Kaggle NSE dataset

**In:** 1,756 CSV files from the Kaggle NSE archive.
**Out:** `data/raw/nse_equity.parquet`, `data/raw/nse_index.parquet`,
`ml/reports/ingest_quality.json`.

| Finding | Equity | Index |
|---|---|---|
| Rows | **5,230,852** | 206,696 |
| Symbols | **2,096** | 54 |
| Files read / skipped | 1,720 / 36 | — |
| Invalid OHLC rows | 8,372 (**0.16%**) | 3,349 (**1.62%**) |
| Symbols affected | 379 | 11 |
| Non-positive prices | 0 | 0 |
| Duplicate symbol+date | 0 | 0 |
| Universe coverage | 50 of 51 (missing `MM`) | — |

"Invalid OHLC" means a row where the high/low/open/close relationship is
impossible — for instance a low above the open.

**The decision that defines this stage:**

```python
"""Outliers are flagged, never dropped. An extreme move in Indian equity
history is usually a real event -- a crash, a split, a corporate action -- and
deleting it would quietly bias every volatility and drawdown figure computed
downstream."""
```

```python
def _quality_checks(frame):
    """Findings are reported, not acted on: the decision to exclude a row
    belongs to a human reading the report, not to the loader."""
```

This is the correct instinct and it is worth being able to defend. If you
delete the 20 worst days from fifteen years of Indian equity history, you have
not cleaned the data — you have deleted March 2020, and every volatility
figure, every drawdown and every VaR computed afterwards is wrong in the
flattering direction. Flag, report, and let a human decide.

**One bug found here:** the universe file listed Mahindra & Mahindra as `MM`,
but the dataset stores it as `M&M`. The coverage check caught it (`missing:
["MM"]`) and the universe `file_symbol` was corrected.

**Complexity:** O(F · R) for F files of R rows — about 5.4 million rows read
once. Memory is the constraint, not time: the frames are built per file and
concatenated, so peak memory is roughly one copy of the final 5.2M-row frame
(~400 MB) rather than F copies.

### 9.2 Stage 02 — fetch what Kaggle does not have

**Out:** 58 parquet files in `data/external/yahoo/` + a manifest.

Two gaps motivated this stage:

1. The Kaggle set has **no gold and no ETF series**, yet the product universe
   is "NIFTY 50 plus ETF / gold / debt / cash". GOLDBEES and NIFTYBEES supply
   real rupee-denominated history for those classes.
2. The Kaggle set **stops on 2021-07-01** — a limitation the PRD itself flags.
   Fetching the same symbols forward extends the universe to the present
   (2026-11-13).

```python
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
REQUEST_DELAY_SECONDS = 0.6
REQUEST_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; wealthos-research/0.1)"}
```

A 0.6-second delay between requests — a free public endpoint used politely. A
generic research User-Agent, with no personal information in it.

```python
"""The fetch runs once; every later stage reads the cache, so the pipeline is
reproducible offline."""
```

This matters for reproducibility. Re-running `make all` does not re-hit Yahoo,
so the results do not change because the network did. 58 cached parquet files
are the data.

**Complexity:** O(S) requests for S = 58 symbols, wall-clock bound by the
0.6 s delay (~35 seconds). Space O(S · D) ≈ 58 × 6,500 rows.

### 9.3 Stage 03 — ★ the corporate-action-adjusted price panel

**This is the most consequential stage in the project.** If you present one
piece of data engineering, present this one.

#### The discovery

The Kaggle NSE closing prices are **raw, unadjusted closes**. So:

- RELIANCE shows **−50.3%** on 2017-09-07
- TCS shows **−50.5%** on 2018-05-31

Neither is a crash. Both are **1:1 bonus issues** — the company gave every
shareholder one extra share, so the price per share halved while the holder's
wealth was unchanged. Across the 51-name universe over full history there are
**78 such phantom moves**.

#### Why this is not a cosmetic problem

Computing volatility, drawdown, Sharpe or beta from that series produces
numbers that are confidently and badly wrong. Stage 03b quantifies it exactly
(section 9.4). The headline: **INFY's maximum drawdown reads −87.9%
unadjusted and −36.5% adjusted, and its Sharpe ratio flips from −0.302 to
+0.427.** A profitable holding was being reported as a loss-maker.

#### The fix

Yahoo's `adj_close` is adjusted for splits, bonuses **and** dividends and
spans 2000–2026, covering the whole simulation window. It becomes the price
source for every tradeable asset.

The Kaggle data keeps the three jobs it is uniquely good at:
- the 1990–2021 **index** history (Yahoo's ^NSEI starts in 2007),
- the 2,096-symbol **breadth** used for sector assignment and EDA,
- **independent cross-validation** of the Yahoo series.

An intermediate idea was tested and rejected: the Kaggle files have a
`Prev Close` column, which in principle could be compared against the previous
row's close to detect adjustments. It was checked and found useless — the
column simply repeats the prior close, carrying no adjustment information.
Worth mentioning because "we tried the cheaper fix first" is a better story
than "we went straight to a second data source".

#### Splices and their gates

Two series had to be joined, and they are held to **different standards**:

```python
SAME_INSTRUMENT_MIN_CORR  = 0.95
SAME_INSTRUMENT_MAX_DRIFT = 0.02
PROXY_MIN_CORR            = 0.80
PROXY_MAX_VOL_RATIO       = 2.0
```

| Kind | Case | Gate | Measured |
|---|---|---|---|
| `same_instrument` | Kaggle "NIFTY 50" + Yahoo ^NSEI — literally the same index | correlation ≥ 0.95, level-ratio drift < 2% | **correlation 1.0000** over **3,374** overlapping days, drift 0.0000, handover 2007-09-17. Result: 8,795 rows, 1990-07-03 → 2026-11-13 |
| `proxy_handoff` | NIFTY GS Composite → GILT5YBEES for the debt class — *related but distinct instruments* | correlation ≥ 0.80, volatility within 2× | **correlation 0.8581** over 57 overlapping days. Passes, and is recorded in the data dictionary as an **instrument change**, not a continuation |

A third candidate, LTGILTBEES, was **rejected** by the gate and is recorded as
rejected. That is the gate doing its job.

```python
def _splice(historical, recent, kind, label):
    """Join a historical series onto a recent one on the recent one's scale.
    The two series are rescaled rather than concatenated, because they sit on
    different bases: an unadjusted index level and an adjusted ETF price are
    not the same number even when they track the same exposure."""
```

```python
ratio = joined["recent"] / joined["hist"]
scale = float(ratio.median())
drift = float(abs(ratio.iloc[-1] / ratio.iloc[0] - 1.0))
```

The median ratio is the scale factor (median, not mean — one bad day cannot
move it). The drift check compares the ratio at the start and end of the
overlap: if the two series are the same instrument, their ratio should be
*constant*. A drifting ratio means they are diverging, and the gate fails.

#### `repair_reverting_spikes` — a second feed defect

Yahoo itself has a defect: it occasionally applies a split adjustment to a
couple of days and then reverts it. NIFTYBEES, BANKBEES and GOLDBEES each
show this on **2019-12-19/20** — the price drops to a tenth (a hundredth for
GOLDBEES), holds for two sessions, then returns to its previous level.

```python
ratio = prices[index] / previous
if (1 / jump_factor) < ratio < jump_factor:
    index += 1
    continue
# Does the price come back to where it was, within `lookahead` days?
recovery = None
for ahead in range(index + 1, min(index + 1 + lookahead, len(prices))):
    if abs(prices[ahead] / previous - 1.0) <= tolerance:
        recovery = ahead
        break
if recovery is None:
    index += 1   # one-way move: leave it for the gate to judge
    continue
flagged[index:recovery] = True
```

The critical line is `if recovery is None: continue`.

**Only round trips are repaired.** A jump that does *not* come back is left
alone, so the validation gate still fails on a genuine unadjusted corporate
action rather than having it quietly smoothed away. The reasoning is in the
docstring: *"A real split never reverts, so a round trip of that magnitude is
a feed defect."*

This is the difference between a data repair and data laundering. A filter
that smoothed every large move would also erase real crashes — and would have
hidden the very bug this stage exists to fix.

Repairs are recorded per symbol in `price_build.json` with the exact dates,
the excursion ratio, and the level before and after.

#### The cash series

```python
def build_cash_series():
    """A deterministic cash accrual, compounded daily on trading days.
    Liquid ETFs such as LIQUIDBEES hold their NAV at a constant and pay their
    return out as dividends, so their price series shows zero return."""
```

A flat price series would say cash earns nothing. An explicit 5.5% annual
accrual, compounded daily, is less precise but not false — and the assumption
is documented and printed.

#### The output

| | |
|---|---|
| Panel | **4,069 trading days × 58 assets**, 2012-01-01 → 2026-11-13 |
| Files | `prices.parquet` (long), `returns.parquet` (wide), `price_panel.parquet` (wide) |
| Evidence | `price_build.json` — every splice, every gate result, every repair, per-asset annualised return and volatility |

Sanity-check a few: NIFTY50 10.86% annual return / 15.21% volatility; DEBT
7.09% / 3.88%; EICHERMOT 28.5% / high volatility. Debt less volatile than
equity, index less volatile than single stocks — the panel behaves like real
markets, and there are tests asserting exactly that.

**Complexity:** O(S · D) to read 58 series; splice is O(D log D) for the
inner join; `repair_reverting_spikes` is O(D · L) where L = 5 lookahead, so
effectively O(D). Space O(D · S) ≈ 4,069 × 58 × 8 bytes ≈ 1.9 MB.

### 9.4 Stage 03b — ★ proving why stage 03 was necessary

This stage computes nothing the platform uses. It exists to produce
**evidence**, and it is the single most persuasive artifact in the project.

```python
COMPARISON_START = "2012-01-01"
COMPARISON_END   = "2021-07-01"
PHANTOM_MOVE_THRESHOLD = 0.35
```

It recomputes the headline risk metrics **both ways** over the window where
both sources exist, and records the difference.

#### The results

| Measure | Value |
|---|---|
| Symbols compared | 51 |
| Symbols with phantom moves | **24** |
| Total phantom moves in this window | **28** |
| Volatility **overstated** by | median **4.81 pp**, max 15.18 pp |
| Max drawdown **overstated** by | median **7.88 pp**, max **63.8 pp** |
| Sharpe **understated** by | median **0.211**, max 0.941 |
| **Sharpe sign flips** | **15** |

> **A note on 78 versus 28.** Both numbers are correct and they measure
> different windows. **78** is the count across the full available history
> (from 1996). **28** is the count inside the 2012-01-01 → 2021-07-01
> comparison window where both sources overlap, affecting 24 symbols. The
> Data Quality page states its window; `docs/data.md` states its own. Getting
> this wrong is an easy way to look careless in a viva, so it is worth saying
> which window you mean.

#### The five worst cases

| Symbol | Phantom moves | Volatility | Max drawdown | Sharpe |
|---|---|---|---|---|
| **ASIANPAINT** | 1 | 39.6% → **24.4%** | −92.5% → **−28.7%** | −0.11 → **+0.83** |
| **INFY** | 3 | 40.1% → **26.3%** | −87.9% → **−36.5%** | −0.30 → **+0.43** |
| **EICHERMOT** | 1 | 44.6% → **31.0%** | −93.8% → **−60.7%** | +0.01 → **+0.81** |
| **TRENT** | 1 | 44.8% → **31.3%** | −92.6% → **−49.3%** | −0.13 → **+0.58** |
| **SBIN** | 1 | 46.2% → **33.1%** | −94.9% → **−59.5%** | −0.42 → **+0.12** |

Read the ASIANPAINT row. Unadjusted, Asian Paints appears to have lost 92.5%
of its value and to have a *negative* risk-adjusted return. Adjusted, it had a
−28.7% drawdown and a Sharpe of 0.83 — one of the best holdings in the
universe. **Fifteen symbols had their Sharpe ratio's sign flipped.** Any
portfolio optimiser, any ranking, any "best holding" recommendation built on
the unadjusted data would have been not slightly off but inverted.

**Complexity:** O(S · D) for S = 51 symbols × D days, computing a fixed set of
O(D) metrics twice per symbol.

### 9.5 Stage 04 — seed PostgreSQL

```python
CHUNK_SIZE = 20000
```

```python
"""Market data is reference data: it belongs to no user and is shared by every
account. This stage is idempotent, so re-running it after a pipeline change
refreshes prices without duplicating rows."""
```

**Result:** 58 assets, **232,287 price rows**, span 2012-01-01 → 2026-11-13.

Chunked inserts of 20,000 rows: one 232k-row `INSERT` would build an enormous
statement and risk a timeout; one row at a time would be 232,287 round trips.
20,000 is the middle.

Idempotency comes from the `UniqueConstraint("asset_id", "date")` plus an
upsert. Re-running updates in place.

**One bug found here:** debt instruments seeded with **zero** prices. The
`CheckConstraint("close > 0")` caught it at the database level — exactly what
it is for. The cause was that the debt series was a *composite* with no single
source symbol. The fix adds an explicit `DEBT` asset and marks its component
series as `component` so they are not double-counted in the universe.

**Complexity:** O(R / C) round trips for R = 232,287 rows in chunks of
C = 20,000 — about 12 statements. Each insert is O(log N) per row for the
index maintenance, so O(R log R) total.

### 9.6 Stage 05 — holding priors from Big Sharks

The PRD treated the Big Sharks dataset as a **schema reference only**. It can
do more.

```python
"""After mapping its company names onto NSE symbols it yields two empirical
distributions worth borrowing for the synthetic cohort:
  * which Indian stocks investors actually concentrate in, and
  * how concentrated real portfolios are (the distribution of HHI).
Sampling synthetic holdings from observed popularity rather than uniformly
makes the cohort look like real Indian portfolios instead of a random draw
from the NIFTY 50."""
```

#### Name matching

```python
NOISE_WORDS = {"ltd", "limited", "the", "india", "indian", "co", "corp",
               "corporation", "company", "pvt", "private", "inc", "plc", "and", "of"}
FUZZY_ACCEPT_SCORE = 88
```

```python
def build_symbol_map(...):
    """Exact normalised matching first, then fuzzy matching for the remainder
    with a score floor. Anything below the floor is left unmapped rather than
    guessed."""
```

Two passes:
1. **Normalise and match exactly.** "Infosys Ltd" → `infosys` → `INFY`.
2. **Fuzzy-match the remainder** with rapidfuzz, accepting only ≥ 88.

| Result | Count |
|---|---|
| Total names | 1,169 |
| Exact matches | **823** |
| Fuzzy matches | **22** |
| Unmatched | 324 |
| **Match rate** | **72.28%** |

The 324 unmatched are mostly small-caps outside the universe (`7Seas_Entertainment_Ltd`,
`Aarti_Pharmalabs_Ltd`), and a sample of them is written into the report so
the gap is inspectable rather than asserted.

The threshold of 88 is the honest part. Lower it to 70 and the match rate
rises — along with wrong matches, which would silently corrupt the popularity
distribution. Leaving 324 names unmapped and *saying so* is better than a
higher number built on bad joins.

#### What it yielded

| Measure | p10 | Median | p90 |
|---|---|---|---|
| Portfolio HHI | 0.0483 | **0.2266** | 0.8748 |
| Holdings count | 2 | **13** | 80 |

And the caveat, carried through into every downstream report:

> *"Derived from large and institutional investors, not retail ones. Used as a
> loose shape for the synthetic concentration distribution, never as a retail
> benchmark."*

**Complexity:** exact matching is O(N) with a hash map. Fuzzy matching is
**O(U · V · L²)** for U unmatched names against V universe names with
Levenshtein-style comparison on length-L strings — the expensive step, which
is why it runs only on the 346 names the exact pass missed, not all 1,169.

### 9.7 Stage 06 — the synthetic investor cohort

**Out:** `investors.parquet` (10,000 rows), `snapshots.parquet` (**1,253,505**
rows), `transactions.parquet`, `cohort.json`.

```python
RANDOM_SEED = 42
MIN_MONTHS_OF_HISTORY = 24
```

```python
"""Everything here is simulated and is labelled as such throughout. Only the
prices are real."""
```

#### The six archetypes

From `ml/synthetic/archetypes.py`. Each is a set of distributions over
profile, allocation and behaviour:

| Archetype | Generated | Share |
|---|---|---|
| `balanced_investor` | 2,606 | 26.1% |
| `aggressive_growth` | 2,003 | 20.0% |
| `conservative_saver` | 1,835 | 18.4% |
| `goal_focused_sip` | 1,656 | 16.6% |
| `active_trader` | 1,211 | 12.1% |
| `dormant_holder` | 689 | 6.9% |

Why archetypes rather than pure randomness:

```python
"""Generating from known archetypes buys something a purely random cohort
cannot: the clustering model can be scored against the true generating label
with Adjusted Rand Index, not just silhouette. Silhouette says whether
clusters are tight; ARI says whether they are the *right* clusters."""
```

This is the key methodological move in the whole ML section. See 10.1.

#### Two deliberate design choices

**1. Stated risk tolerance does not always match behaviour.**

```python
risk_mismatch_probability    # per archetype
```

**1,520 of 10,000** investors are given a stated tolerance inconsistent with
how they actually invest — a "conservative" investor running 85% equity. This
is true of real people, and it gives the Health Score's risk component
something real to detect. A cohort where everyone behaved exactly as labelled
would make the mismatch detection untestable.

**2. Archetypes overlap on purpose.** The boundaries are soft, so a perfect
clustering score is neither expected nor desirable. An ARI of 1.0 would mean
the cohort was too easy.

#### The simulation

```python
def simulate(...):
    """State is an (investors x assets) quantity matrix. Each month: value the
    holdings at real prices, add contributions, allocate..."""
```

The entire cohort is one NumPy matrix of shape **(10,000 × 58)**, stepped
forward month by month against the **real** adjusted price panel. One
vectorised step per month, not 10,000 Python objects.

Target weights come from the Big Sharks popularity priors:

```python
def _build_target_weights(...):
    """Equity names are drawn without replacement using Big Sharks popularity,
    so the cohort concentrates in the stocks Indian investors actually hold."""
```

#### Time-weighted returns, again

```python
def build_snapshots(...):
    """Returns are time-weighted: the month's contribution is removed before
    dividing by the opening value. Without that step every SIP contribution
    reads as investment performance."""
```

The same formula from section 6.6, applied inside the simulator. This is
promise #1 in action: if the simulator had used a naive `pct_change`, the
models would have been **trained on inflated returns** and then served
correctly-computed ones. The models would appear to work and be subtly wrong
in production. Using the same core function makes that impossible.

#### Injected anomalies

```python
ANOMALY_TYPES = ("allocation_shock", "concentration_spike", "turnover_spike",
                 "panic_sell", "dormancy_break")
ANOMALY_INVESTOR_SHARE = 0.12
ANOMALY_MIN_HISTORY = 12
```

```python
def inject_anomalies(...):
    """Applied to the recorded snapshots rather than threaded through the
    simulation, so each anomaly's location and type are known exactly."""
```

**3,556 anomalous months across 1,200 investors** (12% of the cohort):

| Type | Count | What it is |
|---|---|---|
| `turnover_spike` | 742 | Sudden burst of trading |
| `dormancy_break` | 734 | A dormant account suddenly active |
| `panic_sell` | 717 | Mass liquidation into cash |
| `concentration_spike` | 690 | Piling into one holding |
| `allocation_shock` | 673 | Drastic asset-class reshuffle |

And the caveat that travels with every reported detection score:

> *"Injected, not observed. They are deliberately unambiguous, so detection
> scores against them are an upper bound on real-world performance."*

This sentence is why the 0.9355 PR-AUC in section 10.2 is credible. A paper
reporting 0.94 without that caveat invites the question; stating it first is
better.

#### Sanity checks on the output

| Measure | p10 | Median | p90 |
|---|---|---|---|
| Final portfolio value | ₹11,74,658 | **₹45,13,941** | ₹1,32,20,045 |
| Growth multiple | 1.628× | **2.258×** | 3.397× |
| Holdings per investor | 7 (min) | **12** | 22 (max) |

A median 2.26× over roughly 12 years is about **7% a year** — plausible for a
mixed portfolio over 2012–2026, and consistent with the real NIFTY return of
10.86% once debt, gold and cash are blended in. If the median had come out at
0.4× or 40×, the simulator would be broken.

**Complexity:**
- Time: **O(M · I · A)** — M = 178 months × I = 10,000 investors × A = 58
  assets ≈ 103 million cell operations, vectorised in NumPy. Runs in a few
  minutes.
- Space: the quantity matrix is I × A = 10,000 × 58 × 8 bytes = **4.6 MB**.
  The output snapshot table is 1,253,505 rows × 23 columns ≈ **230 MB** in
  memory, written to parquet where it compresses to a fraction of that. This
  is the largest single object in the project.

### 9.8 Stage 07 — ★ feature engineering and the split that matters

**Out:** three parquet tables, one per model, plus `features.json`.

| Table | Rows | Grain |
|---|---|---|
| `features_clustering.parquet` | **9,743** | one row per investor |
| `features_anomaly.parquet` | **1,243,505** | one row per investor-month, with deltas |
| `features_forecast.parquet` | **1,143,505** | one row per investor-month, with forward targets |

#### The chronological split

```python
TRAIN_END       = pd.Timestamp("2022-12-31")
VALIDATION_END  = pd.Timestamp("2024-06-30")
```

```python
def _assign_split(frame):
    """Label every row train / validation / test by date alone. All investors
    share the same boundaries. Splitting per investor, or at random, would let
    a model learn from a market regime it is later tested on."""
```

This is the most important line in the file. Consider the alternative: a
random 70/15/15 split over 1.25 million investor-months. March 2020 rows
would land in both train and test. The model would have *seen* the COVID crash
during training and would then be scored on predicting it. The reported
accuracy would be excellent and completely fake.

Splitting by **date alone**, with every investor sharing the same boundaries,
means the test set is a market period the model has genuinely never seen.

| Split | Anomaly rows | Anomalies | Forecast rows (12m) |
|---|---|---|---|
| Train (→ 2022-12-31) | 774,093 | 1,966 | 675,724 |
| Validation (→ 2024-06-30) | 179,412 | 590 | 177,884 |
| Test (2024-07-01 →) | 290,000 | 1,000 | 169,897 |

There is a test — `test_feature_splits_do_not_overlap_in_time` — asserting
this holds.

#### The clustering features: trained on the past only

```python
def build_clustering_features(...):
    """Built only from months up to the training cut, so an investor's cluster
    is not informed by behaviour that occurs after the period the model was
    fitted on."""
```

Even the unsupervised model respects the time boundary.

#### The anomaly features: levels *and* changes

```python
def build_anomaly_features(...):
    """Change matters as much as level here. A 70% equity weight is ordinary;
    moving from 70% to 20% in one month is not."""
```

So for every state feature there is a `delta_` companion — 24 features in
total, half of them first differences. This is the feature engineering that
makes the autoencoder work: a snapshot alone cannot distinguish a stable
conservative investor from one who panic-sold last Tuesday. They have the same
20% equity weight. Only the delta separates them.

#### ★ The forecasting target — the decision that makes accuracy mean something

```python
target = "excess_log_growth_{h}m = log(V_{t+h}) - log(V_t + h*contribution)"
```

```python
"""Raw rupee value is dominated by current value plus deposits, so regressing
on it yields a near-0.99 R-squared that measures scale rather than skill. The
baseline absorbs that predictable part and leaves the model only the
market-return component."""
```

Here is the trap, with real numbers from the report. Predicting raw rupee
value 12 months ahead:

| Model | R² on rupee value |
|---|---|
| "Same as today, plus deposits" (a **baseline that knows nothing**) | **0.9625** |
| XGBoost | 0.9697 |

A model that does *no* modelling scores 96.25%. Reporting 0.9697 as "97%
forecasting accuracy" would be technically true and completely misleading —
the model is restating the current balance, which it was given as an input.

The fix subtracts the predictable part. The target becomes:

```
excess_log_growth = log(V_{t+h}) − log(V_t + h · contribution)
                    └── what happened ──┘   └── what you'd have with 0% return ──┘
```

This is the **market-return component only**. The current balance and the
planned deposits are gone, because they appear identically in both terms.

Why **log**: log growth is additive across periods, so a 3-month and a
9-month figure can be combined into a 12-month one. And it is symmetric —
+50% and −33% are equal and opposite in log space, which they are not in
simple returns.

**Complexity:** `groupby("investor_id")` with shifts and rolling windows over
1.25M rows is **O(R log R)** for the sort plus O(R · W) for W-length rolling
windows. Space is the binding constraint: three feature tables of 1.1–1.25M
rows each, held one at a time and written to parquet.

---

## 10. The three models (stages 08–10)

### 10.1 Clustering — investor behaviour segmentation

**Script:** `p08_train_clustering.py` · **Data:** 9,743 investors × 15 features
· **Artifact:** `ml/models/clustering.joblib` · **Report:**
`ml/reports/clustering.json`

#### The 15 features

```python
FEATURE_COLUMNS = [
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation",        # what they hold
    "allocation_volatility",                     # how much that shifts
    "turnover", "trades_per_month",              # how much they trade
    "portfolio_volatility", "max_drawdown",      # what risk they run
    "hhi", "top_holding_weight", "n_holdings",   # how concentrated
    "contribution_consistency", "contribution_rate",  # how they save
]
```

All behavioural. Deliberately **no** age, income or stated risk tolerance —
the model segments on what people *do*, not on what they say or who they are.
That is what lets the Health Score later detect a mismatch between the two.

Features are standardised (`StandardScaler`) first. This is mandatory for
K-Means: the algorithm minimises Euclidean distance, and `annual_income` in
rupees would otherwise dominate `equity_allocation` in the 0–1 range by six
orders of magnitude.

#### Choosing K

```python
K_RANGE = range(2, 11)
model = KMeans(n_clusters=k, n_init=10, random_state=RANDOM_STATE)
```

| k | Inertia | **Silhouette** | Davies–Bouldin | Calinski–Harabasz |
|---|---|---|---|---|
| 2 | 108,599 | 0.309 | 1.027 | 3,368 |
| 3 | 87,024 | 0.273 | 1.511 | 3,309 |
| 4 | 68,331 | 0.336 | 1.265 | 3,697 |
| 5 | 58,053 | 0.334 | 1.198 | 3,694 |
| 6 | 50,075 | 0.363 | 1.082 | 3,736 |
| **7** | **47,033** | **0.3707** ← best | **1.0796** | 3,419 |
| 8 | 44,639 | 0.367 | 1.220 | 3,162 |
| 9 | 43,167 | 0.312 | 1.378 | 2,903 |
| 10 | 40,604 | 0.298 | 1.315 | 2,811 |

Three indices, not one:
- **Silhouette** (higher better) — how well each point fits its own cluster
  versus the next nearest. Peaks at k = 7.
- **Davies–Bouldin** (lower better) — ratio of within-cluster scatter to
  between-cluster separation. Also best at k = 7 (1.0796).
- **Calinski–Harabasz** (higher better) — variance ratio. Peaks at k = 6, so
  it mildly disagrees. Reporting all three including the one that disagrees is
  the honest presentation.

Inertia falls monotonically with k and so cannot choose k on its own — that is
exactly what the elbow method tries to eyeball, and silhouette replaces the
eyeballing with a number.

**The complexity note that is in the code itself:**

```python
# Silhouette on the full set is O(n^2); sample for that metric only.
sample = rng.choice(len(scaled), size=min(5000, len(scaled)), replace=False)
```

Silhouette requires every pairwise distance: **O(n²·d)**. For 9,743 investors
× 15 features that is 9,743² × 15 ≈ **1.4 billion** operations — per candidate
k, and there are nine. Sampling 5,000 points cuts it to 5,000² × 15 ≈ 375
million, a **3.8× reduction**, and a 5,000-point sample estimates a mean
silhouette to well within the precision that matters here. Note the sampling
applies to *that metric only*: K-Means itself is fitted on all 9,743.

#### Comparing against other algorithms

```python
gmm = GaussianMixture(n_components=best_k, random_state=RANDOM_STATE, n_init=3)
agglomerative = AgglomerativeClustering(n_clusters=best_k)   # on a 4,000 subsample
```

| Algorithm | Silhouette | Davies–Bouldin | Note |
|---|---|---|---|
| **K-Means** | **0.3707** | **1.0796** | chosen |
| Gaussian Mixture | 0.3356 | 1.8253 | soft assignment, elliptical clusters |
| Agglomerative | 0.3558 | 1.1339 | fitted on a 4,000-investor subsample |

```python
# Agglomerative is O(n^2) in memory; fit on a subsample.
```

Agglomerative clustering holds a full pairwise distance matrix:
**O(n²) space**. For 9,743 points that is 9,743² × 8 bytes ≈ **760 MB**, and
the naive linkage algorithm is **O(n³)** in time. On a 4,000 subsample the
matrix is 4,000² × 8 ≈ 128 MB — tractable. The subsample is disclosed in the
report's `note` field rather than hidden.

K-Means wins on both indices. That makes the choice of K-Means **an argued
one** rather than an assumption, which is the difference between "we used
K-Means" and "we used K-Means because it beat the two obvious alternatives on
this data, and here are the numbers".

#### Stability — the check most projects skip

```python
BOOTSTRAP_ROUNDS = 20
BOOTSTRAP_FRACTION = 0.8
```

```python
def bootstrap_stability(...):
    """Refit on overlapping subsamples and compare labels on the shared rows.
    A high silhouette on an unstable solution means the model found a
    partition of this particular sample, not a structure in the population."""
```

Twenty rounds. Each round draws two overlapping 80% subsamples, fits K-Means
on each, and compares the labels on the rows both contain:

| | |
|---|---|
| Mean ARI across 20 resamples | **0.9573** |
| Standard deviation | 0.0328 |
| Worst round | **0.9090** |

Even in the worst of twenty resamples, 91% agreement. The clusters are a
property of the population, not an artifact of this particular sample. That
last docstring sentence is the point: a tight-looking clustering that
rearranges itself when you remove 20% of the data has found nothing.

#### ★ Archetype recovery — scoring against ground truth

This is only possible because the cohort is synthetic, and it is the strongest
evaluation in the project.

| Metric | Value |
|---|---|
| **Adjusted Rand Index** | **0.9465** |
| Normalized Mutual Information | **0.9312** |
| True archetypes | 6 |
| Clusters found | 7 |

Why ARI rather than plain accuracy: cluster labels are arbitrary (cluster "3"
has no inherent meaning), so you cannot compare label-to-label. ARI compares
*which points were grouped together*, and it **corrects for chance agreement**
— 0 means random, 1 means perfect. An unadjusted Rand Index would score ~0.7
for a random partition, which is why the adjusted form is the standard.

The crosstab makes it concrete — true archetype (columns) against discovered
cluster (rows):

| Cluster | active_trader | aggressive_growth | balanced | conservative | dormant | goal_sip |
|---|---|---|---|---|---|---|
| 0 | 11 | 34 | **73** | 48 | 12 | 43 |
| 1 | 0 | 8 | 0 | 0 | **656** | 0 |
| 2 | 1 | **1,874** | 11 | 0 | 0 | 0 |
| 3 | 0 | 0 | 1 | **1,740** | 0 | 0 |
| 4 | 0 | 32 | **2,448** | 6 | 0 | 11 |
| 5 | 0 | 0 | 11 | 0 | 0 | **1,558** |
| 6 | **1,165** | 0 | 0 | 0 | 0 | 0 |

Read cluster 6: **1,165 active traders and nothing else.** Cluster 3: 1,740
conservative savers and a single stray. Cluster 2: 1,874 aggressive-growth
investors. The diagonal is almost clean.

Cluster 0 is the interesting one — 221 investors scattered across all six
archetypes. That is the **boundary cluster**: investors whose behaviour sits
between archetypes. It exists because the archetypes were designed to overlap.
Its presence is why 7 clusters recover 6 archetypes, and why ARI is 0.9465
rather than 1.0.

And the note in the report:

> *"Measurable only because the cohort is synthetic. ARI corrects for chance
> agreement: 0 is random, 1 is a perfect match. Archetypes overlap by design,
> so a perfect score is neither expected nor desirable."*

#### Naming the clusters

```python
def describe_clusters(...):
    """Characterise each cluster from its centroid, then name it.
    Names are derived here, after fitting, from how each cluster actually
    differs from the cohort average."""
```

| Cluster | Name | Size | Share |
|---|---|---|---|
| 0 | Balanced investor | 221 | 2.3% |
| 1 | Passive holder | 664 | 6.8% |
| 2 | Growth-oriented investor | 1,886 | 19.4% |
| 3 | Capital preserver | 1,741 | 17.9% |
| 4 | Broadly diversified investor | 2,497 | 25.6% |
| 5 | Systematic index accumulator | 1,569 | 16.1% |
| 6 | High-turnover trader | 1,165 | 12.0% |

The names come from the centroids *after* fitting, not from the archetype
labels — which keeps the naming honest, because in production on real users
there are no archetype labels to peek at.

**A bug found here:** the first naming heuristic produced three clusters all
called "Balanced investor", which is useless in a UI. The rules were rewritten
with ordered specificity: check the most distinctive signal first (turnover,
then dormancy, then equity tilt, then diversification), and only fall back to
"balanced" if nothing stands out.

#### The tracked cluster map

```python
CLUSTER_MAP_POINTS = 2400
# A downsampled copy as a tracked report. The parquet lives in gitignored
# data/processed/, so a stratified sample keeps every cluster represented.
sampled = (assignments.groupby("cluster")
           .apply(lambda g: g.sample(min(len(g), per_cluster), random_state=RANDOM_STATE)))
```

The full `cluster_assignments.parquet` is gitignored, so the Model Lab's
scatter plot would have had nothing to draw after deployment. A **stratified**
2,400-point sample is written to `ml/reports/cluster_map.json`, which *is*
tracked. Stratified rather than uniform so that cluster 0 (221 investors,
2.3%) still appears — a uniform sample would show roughly 55 of them and the
boundary cluster would visually vanish.

#### Complexity summary

| Operation | Time | Space |
|---|---|---|
| K-Means (Lloyd's), one fit | O(n · k · d · i) | O(n·d + k·d) |
| K-Means with `n_init=10` | ×10 | same |
| The whole k = 2..10 sweep | Σ O(n·k·d·i·10) | same |
| Silhouette (full) | **O(n²·d)** ← sampled to 5,000 | O(n²) |
| Davies–Bouldin | O(n·k·d) | O(k·d) |
| Gaussian Mixture | O(n·k·d·i) diagonal | O(n·k) |
| Agglomerative | **O(n³)** time, **O(n²)** space ← subsampled to 4,000 | O(n²) |
| Bootstrap stability | 20 × 2 × O(0.8n·k·d·i) | O(n) |
| ARI | O(n + k²) | O(k²) |

For this data: n = 9,743, d = 15, k = 7, i ≈ 20 iterations. One K-Means fit is
about 9,743 × 7 × 15 × 20 ≈ 20 million operations — well under a second. The
*metrics*, not the fitting, are the expensive part, which is a useful thing to
know and the opposite of most people's intuition.

### 10.2 Anomaly detection — a PyTorch autoencoder

**Script:** `p09_train_anomaly.py` · **Data:** 1,243,505 investor-months × 24
features · **Artifacts:** `anomaly.pt` + scaler · **Report:**
`anomaly_detection.json`

#### The idea

```python
"""An autoencoder is trained to reconstruct *normal* portfolio-months.
Anything it reconstructs badly is unusual relative to what it has seen.
Training uses only rows labelled normal, so the model never learns to
reproduce the behaviour it is meant to flag."""
```

That last clause is essential. If anomalous rows were in the training set, the
autoencoder would learn to reconstruct them too, and the reconstruction error
would no longer separate them. Training on normal rows only is what makes the
error a usable anomaly score.

#### The architecture, and why it is small

```python
LATENT_DIM = 6

class Autoencoder(nn.Module):
    """Kept deliberately narrow. A high-capacity network reconstructs
    anomalies as faithfully as normal rows, which defeats the entire
    approach: the bottleneck is what forces the model to learn only typical
    structure."""

    def __init__(self, n_features, latent_dim=LATENT_DIM):
        self.encoder = nn.Sequential(
            nn.Linear(n_features, 32), nn.ReLU(),
            nn.Linear(32, 16), nn.ReLU(),
            nn.Linear(16, latent_dim))
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 16), nn.ReLU(),
            nn.Linear(16, 32), nn.ReLU(),
            nn.Linear(32, n_features))
```

```
24 features → 32 → 16 → [6] → 16 → 32 → 24 features
                      bottleneck
```

**Total: 2,878 parameters** (1,430 encoder + 1,448 decoder) — about 11 KB.

The bottleneck is the entire mechanism. Forcing 24 features through 6 numbers
means the network can only keep the patterns that recur. A wide network with
no bottleneck would learn the identity function, reconstruct everything
perfectly, and detect nothing. **Capacity is the enemy here**, which is the
reverse of the usual deep-learning instinct and a good thing to be able to
explain.

#### Training

```python
EPOCHS = 30; BATCH_SIZE = 1024; LEARNING_RATE = 0.001; PATIENCE = 5
```

| Epoch | Train loss | Holdout loss |
|---|---|---|
| 1 | 0.4725 | 0.2347 |
| 5 | 0.1260 | 0.1197 |
| 10 | 0.1077 | 0.1056 |
| 20 | 0.0934 | 0.0916 |
| **29** | 0.0883 | **0.08647** ← best |
| 30 | 0.0872 | 0.0874 |

Train and holdout loss fall **together** throughout. No overfitting — which is
exactly what the 2,878-parameter bottleneck was for. If holdout loss had
turned upward, early stopping (`PATIENCE = 5`) would have halted training.

#### The threshold

```python
def best_threshold(scores, labels):
    """Threshold maximising F1 on the validation set."""
    candidates = np.quantile(scores, np.linspace(0.90, 0.9995, 150))
    for threshold in candidates:
        f1 = f1_score(labels, (scores >= threshold).astype(int), zero_division=0)
```

150 candidate thresholds between the 90th and 99.95th percentile of the
reconstruction error, scored by F1.

| | |
|---|---|
| Chosen threshold | **5.84296525** |
| Validation F1 at that threshold | 0.9041 |
| Selected on | **validation** |

```python
"note": "Chosen on validation and applied unchanged to test. Tuning it on
         test would inflate every reported figure."
```

This is the discipline that makes the test numbers believable. Choosing the
threshold on test would optimise against the very set used to report
performance — the most common way an honest-looking ML result becomes
meaningless.

#### Results on the held-out test set (289,989 rows, 1,000 anomalies)

| Metric | **Autoencoder** | Isolation Forest (baseline) |
|---|---|---|
| Precision | **0.7962** | 0.1783 |
| Recall | **0.8870** | 0.6380 |
| F1 | **0.8392** | 0.2787 |
| False positive rate | **0.00079** | 0.01018 |
| ROC-AUC | 0.9995 | 0.9734 |
| **PR-AUC** | **0.9355** | **0.3255** |
| Rows flagged | 1,114 | 3,579 |

```python
"""An Isolation Forest is fitted on the same features as a baseline. A deep
model that cannot beat a standard shallow detector has not earned its place in
the system, and reporting only the autoencoder's score would hide that."""
```

**PR-AUC improvement: +0.61.** The autoencoder earned its place.

#### Why PR-AUC and not ROC-AUC

Look at the two ROC-AUC figures: 0.9995 and 0.9734. Both look excellent. Both
are nearly useless as a comparison here, because **the positive class is
0.34%** of the data (1,000 of 289,989).

ROC-AUC uses the false positive rate, whose denominator is the 288,989
negatives. A detector can flag 3,579 rows — more than three times too many —
and still have an FPR of only 1%, which barely dents ROC-AUC. Precision-recall
uses the *positive* class as the denominator, so it feels the cost of those
false alarms immediately: the Isolation Forest's precision is **0.178**, which
means four out of five of its alerts are wrong.

In a product this is the difference between a useful alert and a notification
people turn off. **At severe class imbalance, report PR-AUC.**

#### Recall by anomaly type — including the failure

| Anomaly type | Occurrences | Detected | Recall | Mean error |
|---|---|---|---|---|
| `turnover_spike` | 213 | 213 | **1.0000** | 425.8 |
| `concentration_spike` | 193 | 193 | **1.0000** | 183.4 |
| `panic_sell` | 199 | 197 | **0.9899** | 118.8 |
| `allocation_shock` | 200 | 193 | **0.9650** | 52.7 |
| **`dormancy_break`** | **195** | **91** | **0.4667** | **5.84** |

> **Superseded.** Dormancy recall is now **0.969** and every other type holds
> or improves. The table above is the Phase 0 baseline, kept because the
> reasoning that followed it was partly wrong and the correction is more
> instructive than the number. The current figures are in
> `ml/reports/anomaly_detection.json` and the before-and-after in
> `ml/reports/model_comparison.json`.

Four types are caught almost perfectly. `dormancy_break` was caught **less
than half** the time, and this was reported rather than buried.

The "mean error" column shows the mechanism. A turnover spike produces a
reconstruction error of 425.8 — wildly outside anything the model saw in
training. A dormancy break produced **5.84** against a threshold of
**5.84296525**: the class mean straddled the cut by 0.0003, so recall was
effectively a coin flip.

**What the original explanation got right.** "The difference is the preceding
months of inactivity, and a single-month feature vector cannot see them" was
exactly the right diagnosis, and it pointed at the fix.

**What it got wrong, in two ways.**

First, it concluded the signal was "genuinely weak". It was not. In the same
test split, `contribution_ratio` for a dormancy break spanned 0.30 to 0.79
while the maximum across 289,000 normal rows was 0.2006 — the classes did not
overlap at all. What diluted it was the score: a flat mean over 24 features of
unequal reconstruction difficulty, in which a deviation confined to two
well-reconstructed features is averaged away against the ordinary noise of a
harder one. Per-feature z-scoring against the error distribution on normal
training rows took recall to 0.5795 and F1 from 0.8392 to 0.8500 with no new
features, no new data and the same weights.

Instructively, a per-feature *maximum* — the obvious fix for dilution — made
it **worse** (recall 0.3897), because an unnormalised max simply returns
whichever feature is hardest to reconstruct, which is largely the same feature
on every row. The improvement lives in the normalisation, not the reducer.

Second, and more seriously: **the preceding months of inactivity did not
exist.** `inject_anomalies` wrote the large contribution and left the months
before it exactly as the simulation produced them — still contributing, still
trading. So a row labelled `dormancy_break` was a large contribution and
nothing more, and this document was explaining a low recall with a pattern the
generator never produced. A model cannot learn what the data does not contain.

The fix was therefore in two places, and they are measured separately so
neither takes credit for the other. The generator now zeroes three to six
months of contributions, trades and turnover before the injection, and three
lag features make that silence visible: `months_since_contribution`,
`delta_contribution_ratio` and `recent_funding_rate` — the last deliberately
excluding the current month, because a dormancy break *is* a funded month and
including it would leak the label.

**No sequence model was needed.** The original conclusion — that this required
a model with longer memory — was reasonable and turned out to be unnecessary:
three lag features gave the point-in-time model the history it was missing.
Worth remembering the next time an architecture looks like the answer.

#### Complexity

| Operation | Time | Space |
|---|---|---|
| Forward + backward pass | O(B · P) for batch B, P = 2,878 params | O(B · 24) activations |
| One epoch | O(N · P), N = 774,093 normal rows | O(B · 24) |
| 30 epochs | O(30 · N · P) ≈ 6.7 × 10¹⁰ FLOPs | — |
| Scoring (inference) | O(N · P), batched at 8,192 | O(8,192 · 24) |
| Threshold search | O(150 · N_val) | O(N_val) |
| Isolation Forest build | O(t · ψ · log ψ), t=200 trees, ψ=256 subsample | O(t · ψ) |
| Isolation Forest score | O(t · log ψ) **per row** | O(1) |

Inference is batched at 8,192 rows deliberately: scoring 290,000 rows in one
tensor would allocate a 290,000 × 24 float tensor plus every intermediate
activation. Batching keeps peak memory at a few megabytes regardless of how
many rows are scored.

Note how cheap the Isolation Forest is: O(200 · log 256) ≈ 1,600 operations
per row, no gradients, no epochs. That is precisely why it is the right
baseline — if the expensive model cannot beat the cheap one, use the cheap one.

### 10.3 Forecasting — XGBoost vs LSTM vs GRU vs three baselines

**Script:** `p10_train_forecast.py` · **Data:** 1,143,505 investor-months ·
**Horizons:** 1, 3, 6, 12 months · **Reports:** four JSON files

#### What is being predicted — and what is not

```python
"""Not next month's stock returns, which are close to unpredictable. The
target is an investor's portfolio value h months ahead, which is genuinely
forecastable because it is dominated by what they already hold and what they
are about to contribute.

That dominance is also the trap."""
```

This framing is worth stating clearly in a viva, because the obvious question
is "aren't you claiming to predict the market?" No. Predicting individual
stock returns is close to impossible. Predicting a *portfolio's* trajectory is
tractable because most of it is already determined. The modelling problem is
isolating the part that is *not* already determined.

#### The three baselines, and why there are three

| Baseline | What it predicts | Why it exists |
|---|---|---|
| `baseline_contributions` | "Same value, plus the planned deposits" — **zero return** | The naive floor |
| **`baseline_mean_drift`** | **The training-set mean excess log growth** | **The honest reference** |
| `baseline_drift` | Extrapolates the investor's own recent trend | A plausible wrong idea, included to show it is wrong |

Most projects use only the first. Using it alone is flattering, and here is why
in numbers — at the 12-month horizon:

| Reference | XGBoost's apparent skill |
|---|---|
| vs zero-return baseline | **0.4801** |
| vs mean-drift baseline | **0.1533** |

The zero-return baseline ignores market drift, so it is **biased low by
roughly the average market return over the horizon** (`train_mean_excess_log_growth`
= 0.1189 at 12m). Beating it is partly just knowing that markets go up on
average — which the model should not get credit for discovering.

The mean-drift baseline predicts a *constant*: the average excess growth seen
in training. Beating that means the model used the features to say something
specific about *this* investor at *this* time. That is skill.

**A real result from the build:** adding the mean-drift baseline dropped
XGBoost's reported 12-month skill from **0.48 to 0.153**. Nothing about the
model changed. The reference did. The lower number is the true one.

`baseline_drift` — extrapolating the investor's own recent trend — scores
**−2.4811** at 12 months. Dramatically *worse* than a constant. It is kept in
the report because it is the intuitive thing a person would try, and showing
that momentum extrapolation actively destroys value is a finding.

#### The skill score

```python
def skill_score(actual, predicted, reference) -> float:
    """Fractional reduction in mean squared error against a reference forecast.
    1 is perfect, 0 means no better than the reference, negative means worse.
    This is the number that says whether a model added anything."""
    return float(1.0 - model_error / reference_error)
```

#### The models

**XGBoost** — 31 tabular features, grid-searched on validation:

```python
grid = [
    {"max_depth": 3, "learning_rate": 0.02, "min_child_weight": 50},
    {"max_depth": 4, "learning_rate": 0.02, "min_child_weight": 100},
    {"max_depth": 4, "learning_rate": 0.05, "min_child_weight": 50},
    {"max_depth": 6, "learning_rate": 0.05, "min_child_weight": 5},
]
candidate = xgb.XGBRegressor(n_estimators=1500, subsample=0.8, colsample_bytree=0.8,
                             reg_lambda=5.0, early_stopping_rounds=50, ...)
```

The grid exists because of a fairness objection: the LSTM and GRU were tuned
(hidden size, dropout, weight decay) and XGBoost was not, so comparing them
was unfair to XGBoost. A four-point grid over the parameters that actually
matter on noisy financial data — depth, learning rate, and the minimum child
weight that controls how much evidence a split needs — fixed that. At 1 month
the search confirmed the original guess; at 12 months it chose a different
configuration (depth 6, lr 0.05).

`early_stopping_rounds=50` with `n_estimators=1500` means the tree count is
chosen by validation, not fixed. At the 1-month horizon `best_iteration` came
back as **0** — the model found no usable signal at all and stopped
immediately, which is itself an honest result about how hard 1-month
prediction is.

**LSTM and GRU** — 24-month sequences of 14 features:

```python
SEQUENCE_LENGTH = 24

class SequenceForecaster(nn.Module):
    """Deliberately small and heavily regularised. There are 450,000 training
    sequences but only ~121 distinct months behind them, so the effective
    sample is the number of market regimes, not the number of rows. A larger
    network memorises investor-specific paths instead of learning the market
    signal: the first attempt reached a training loss of 0.003 while
    validation loss climbed to 0.022."""

    def __init__(self, n_features, hidden=32, cell="lstm"):
        rnn = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn(n_features, hidden, num_layers=1, batch_first=True)
        self.head = nn.Sequential(
            nn.Dropout(0.3), nn.Linear(hidden, 16), nn.ReLU(),
            nn.Dropout(0.3), nn.Linear(16, 1),
        )

    def forward(self, x):
        output, _ = self.rnn(x)
        return self.head(output[:, -1, :]).squeeze(-1)
```

`output[:, -1, :]` takes only the **last** timestep's hidden state. The RNN
reads all 24 months, but only its final summary of them is used to predict.

**That docstring is the most important paragraph in the forecasting stage.**
There are 449,819 training sequences, which sounds like plenty. But every one
of those sequences is drawn from the same ~121 distinct calendar months. The
**effective sample size is the number of market regimes, not the number of
rows.** 450,000 highly correlated samples do not give you 450,000 independent
observations.

The first attempt ignored this and overfit hard — training loss 0.003,
validation loss 0.022, a 7× gap. Four changes fixed it:

| Change | Why |
|---|---|
| Hidden size → 32 | 6,561 parameters (LSTM) / 5,057 (GRU) instead of tens of thousands |
| Dropout 0.3 × 2 | Randomly zero 30% of activations each pass |
| Weight decay | L2 penalty on the weights |
| Gradient clipping | Stops exploding gradients, a standard RNN failure mode |

#### ★ The sequence-split bug and its fix

```python
def build_sequences(frame, target_column, scaler):
    """Windows are cut from the full timeline and then assigned to a split by
    the month being predicted, not by the months in the window."""
```

The first version cut sequences **within** each split. The validation split is
18 months long and a window is 24 months, so it produced **zero sequences**.
The LSTM had no validation set at all.

The fix: cut windows across the **full** timeline, then assign each one to a
split by the split of the **target month**. A window ending in validation may
contain training months — which is correct, because at prediction time you
genuinely do have the preceding 24 months of your own history. What must not
leak is the **target**, and that is assigned by date.

| Split | Sequences (12m horizon) |
|---|---|
| Train | 449,819 |
| Validation | 167,778 |
| Test | 166,404 |

#### Results across all four horizons

Skill against the mean-drift baseline (the honest number). **Bold = winner.**

| Horizon | Zero-return baseline | Mean-drift baseline | Drift baseline | XGBoost | LSTM | GRU |
|---|---|---|---|---|---|---|
| **1 month** | 0.0 | 0.0 | −0.2189 | 0.0013 | −0.0082 | **0.0383** |
| **3 months** | — | 0.0 | −0.7163 | **0.0052** | −0.4761 | −0.8188 |
| **6 months** | — | 0.0 | −1.3642 | 0.0160 | 0.2364 | **0.2402** |
| **12 months** | — | 0.0 | −2.4811 | 0.1533 | **0.2486** | 0.0907 |

And R² on excess log growth (equivalent to the skill score, shown because it
is the more familiar statistic):

| Horizon | Best model | R² on excess log growth | R² on rupee value |
|---|---|---|---|
| 1m | GRU | 0.0234 | 0.9960 |
| 3m | XGBoost | −0.0882 | — |
| 6m | GRU | 0.1452 | — |
| **12m** | **LSTM** | **0.1490** | 0.9732 |

#### Reading these results honestly

**Short horizons are nearly unforecastable.** At 1 month the best skill is
0.038 — a 3.8% reduction in squared error over predicting a constant. At 3
months the best is 0.005, and both sequence models are *worse* than the
constant. This is the correct and expected result: one month of portfolio
growth is almost entirely one month of market noise, and market noise is not
predictable. A project reporting 1-month skill of 0.6 should be disbelieved.

**Longer horizons are genuinely forecastable.** At 12 months, skill of 0.2486
means the LSTM cut squared error by a quarter against the best constant
forecast. That is a real, modest, defensible result. Over 12 months the
mean-reverting and regime components dominate the noise, and the model can see
them.

**Different models win at different horizons**, and that pattern makes sense:

- At 1 month, the GRU's simpler gating (3 gates vs the LSTM's 4) overfits less
  when there is barely any signal to find.
- At 3 months, only the tree model finds anything at all.
- At 6 and 12 months, the sequence models pull ahead, because the signal lives
  in the *trajectory* — momentum, volatility regime, drawdown recovery — and a
  24-month window sees that while a single-row feature vector cannot.

**Look at the last column.** R² on rupee value is 0.996 at 1 month and 0.973
at 12 months. That is the number a less careful project would have reported as
"99.6% accurate". The honest number for the same model at the same horizon is
**0.0234**. Same model. Same predictions. Two targets, and only one of them
measures skill.

#### Feature importances — a useful sanity check

At 12 months, XGBoost's top features:

| Rank | Feature | Importance |
|---|---|---|
| 1 | `market_volatility_12m` | 0.190 |
| 2 | `return_3m` | 0.117 |
| 3 | `market_return_12m` | 0.085 |
| 4 | `volatility` | 0.075 |
| 5 | `market_drawdown` | 0.064 |
| 6 | `current_drawdown` | 0.042 |

Market-regime features dominate, as they should: over 12 months, what happens
to a portfolio is mostly what happens to the market. At the **1-month**
horizon the ordering is even more market-dominated (`market_return_12m` 0.207,
`market_return_3m` 0.190, `market_return_1m` 0.142) — which is consistent with
there being almost no investor-specific signal at that horizon.

If `log_value` or `annual_income` had topped this list, it would be evidence of
leakage — the model finding a way to restate the current balance. It does not.
There is also a test, `test_no_target_column_is_exposed_as_a_feature`,
asserting no target column appears in any feature list.

#### A bug worth telling

```python
joblib.dump({"xgboost": model, ...})     # BUG: `model` was the GRU
```

The variable `model` was reused in the training loop, so by the time the
artifact was saved it held the GRU, not the XGBoost regressor — and the
dictionary key said `"xgboost"`. The reported metrics were **unaffected**
(they were computed from the correct predictions earlier), but the saved
artifact was wrong, so serving would have used the wrong model.

Fixed by renaming to `xgb_model` and `sequence_model`. The lesson: variable
shadowing in a long function is a real hazard, and `joblib.dump` will happily
save whatever you hand it under whatever name you choose.

#### Complexity

| Operation | Time | Space |
|---|---|---|
| XGBoost, one tree | O(d · n · log n) exact / O(d · (n + bins·f)) histogram | O(n·f) |
| XGBoost, full fit | O(T · d · n · log n), T ≤ 1,500 | O(T · 2^d) for the model |
| XGBoost grid search | ×4 configurations | same |
| LSTM forward, one sequence | O(L · 4 · H · (F + H)) = 24 · 4 · 32 · 46 ≈ 141k FLOPs | O(L · H) hidden states |
| GRU forward | O(L · 3 · H · (F + H)) — **25% cheaper** (3 gates not 4) | same |
| One training epoch | O(N_seq · L · H · (F+H)) ≈ 6.4 × 10¹⁰ FLOPs | O(B · L · F) |
| 25 epochs | ×25 | — |
| **Sequence array** | — | **O(N_seq · L · F)** |

**The space bottleneck of the entire project** is that last row.

```
449,819 sequences × 24 timesteps × 14 features × 4 bytes (float32) ≈ 605 MB
```

Two deliberate mitigations:

```python
scaled = scaler.transform(frame[SEQUENCE_FEATURES]).astype("float32")
```
**float32, not float64** — halves it from 1.2 GB to 605 MB. The comment in the
file gives a second reason: *"MPS has no float64 support, so everything
crossing to the device is float32."* Apple's Metal backend simply cannot take
float64.

```python
chunk = np.asarray(x[start : start + 4096], dtype="float32")
```
**Chunked inference at 4,096 sequences.** Predicting all 166,404 test
sequences in one tensor would allocate the input plus every intermediate
activation at once. Chunking caps peak memory regardless of test-set size.

### 10.4 Stage 11 — measuring Copilot groundedness

```python
QUESTIONS = ["What is my portfolio worth?", "What do I own?", ...]   # 30 total
```

```python
"""The PRD asks for a "groundedness / factual consistency" metric for the
Copilot. This is it, made concrete: a fixed set of 30 questions is put to the
Copilot against a real portfolio, every number in each answer is extracted and
matched against the tool outputs that produced it, and the rate is reported."""
```

| Measure | Value |
|---|---|
| Questions | 30 |
| Mode measured | `deterministic_fallback` |
| **Numbers checked** | **458** |
| **Numbers verified** | **458** |
| **Groundedness rate** | **100%** |
| Fully grounded answers | 30 of 30 |
| Median latency | **24.4 ms** |

Tool usage across the 30 questions:

| Tool | Calls |
|---|---|
| `get_portfolio_summary` | 30 |
| `get_health_score` | 8 |
| `get_risk_metrics` | 5 |
| `get_forecast` | 4 |
| `get_concentration` | 4 |
| `get_goal_status` | 3 |
| `get_investor_profile` | 2 |
| `get_anomalies` | 2 |

```python
"""With no API key it measures the deterministic explainer, which should score
100% by construction -- anything less is a bug in the templates or the
validator."""
```

That framing is important and should be stated rather than glossed. 100% from
the template path is **not** an impressive AI result — the templates can only
emit numbers they were handed, so 100% is the floor, and anything below it
means the validator or the templates are broken. The measurement's real value
is as a **regression test on the validator itself**, which is what the next
section is about.

---

## 11. The Wealth Copilot

The claim being made is strong: **the Copilot explains computed values and
never invents a number.** Three files turn that claim into something enforced
rather than hoped for.

### 11.1 `copilot_tools.py` — eight read-only tools

```python
"""Every tool returns structured JSON computed by the service layer. The model
never calculates a financial figure: it selects which measurements to fetch
and then narrates them. That separation is what makes the Copilot's output
checkable, and it is what the groundedness validator enforces.

All tools are read-only. None can modify a portfolio, place a trade or
change a goal."""
```

| Tool | Returns |
|---|---|
| `get_portfolio_summary` | Value, cost, unrealised gain, allocation, largest holdings |
| `get_risk_metrics` | Volatility, drawdown, VaR, CVaR, Sharpe, Sortino, beta, alpha |
| `get_concentration` | HHI, effective holdings, top-k weights, sector concentration |
| `get_health_score` | The total, the grade, and all six components with reasons |
| `get_goal_status` | Each goal's projection, funding ratio and shortfall |
| `get_forecast` | The trained models' projected value |
| `get_investor_profile` | Behavioural cluster assignment |
| `get_anomalies` | Flagged months and their reconstruction errors |

Read-only is an architectural property, not a prompt instruction. There is no
tool that writes, so no prompt — adversarial or otherwise — can make the
Copilot place a trade.

```python
def _guarded(label, fn):
    """Run a service call, turning an expected failure into a stated reason.
    A tool that raises would leave the model with nothing to say and invite it
    to invent an answer. A tool that returns an explicit "unavailable" gives
    it something true to report."""
```

This is subtle and important. If `get_risk_metrics` raised because the user
has three days of history, the model would be left with a question and no
data — which is exactly the situation in which a language model fabricates. A
tool returning `{"available": false, "reason": "only 12 observations; at least
60 are needed"}` gives it something true to say.

### 11.2 `copilot_service.py` — two paths

#### The system prompt

```
How you must work:
- Call tools to obtain every figure. You have no other source of information
  about this portfolio.
- Never calculate, estimate, infer or recall a financial number yourself. If a
  figure you want is not in a tool result, say it is not available rather than
  producing one.
- Quote figures as the tools report them, rounding at most to one or two
  decimal places.
- If a tool reports available=false, tell the user that measurement could not
  be computed and why.
- Report the assumptions that come with a figure when they matter, especially
  the risk-free rate behind a Sharpe ratio and the fact that forecasts are
  projections rather than predictions.

What you must not do:
- Do not recommend buying, selling or holding any security. You are an
  analytics tool, not a regulated financial adviser.
- Do not describe a forecast as what will happen.
- Do not invent history, news, prices or events.
```

The prompt is necessary but **not sufficient** — a prompt is a request, not a
guarantee. That is what section 11.3 is for.

#### The LLM path

```python
for _ in range(MAX_TOOL_ROUNDS):          # MAX_TOOL_ROUNDS = 6
    response = client.beta.messages.create(
        model=settings.copilot_model,     # claude-opus-5-5
        max_tokens=MAX_TOKENS,            # 8192
        system=SYSTEM_PROMPT,
        tools=copilot_tools.TOOL_SCHEMAS,
        tool_choice={"type": "auto"},
        output_config={"effort": "low"},
        messages=messages,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
```

Each parameter, with its reason:

| Parameter | Reason |
|---|---|
| `tool_choice={"type": "auto"}` | Forced tool choice is rejected by current models with a 400. The system prompt does the steering instead — and the comment in the code says so, so nobody "fixes" it back |
| `output_config={"effort": "low"}` | *"Narrating structured values needs little deliberation."* The reasoning work was done by the backend; the model is writing sentences about numbers it was handed |
| `betas=[...]` + `fallbacks="default"` | A safety decline should fall back to another model rather than dead-end the user's question |
| `MAX_TOOL_ROUNDS = 6` | A bounded loop. Without it, a model that kept calling tools would run forever |

Stop-reason handling:

```python
if response.stop_reason == "refusal":
    raise CopilotUnavailable("The language model declined to answer this question.")
if response.stop_reason == "pause_turn":
    messages.append({"role": "assistant", "content": response.content})
    continue                                   # resume, do not restart
if response.stop_reason != "tool_use":
    ...return the final answer
```

```python
# Tool inputs are parsed JSON from the SDK; never string-matched.
arguments = dict(block.input or {})
output = copilot_tools.run_tool(block.name, db, user, arguments)
```

The comment matters: tool arguments come from the SDK's parsed JSON, never
from regexing the model's text. String-matching model output to decide what to
execute is how prompt injection becomes code execution.

#### The fallback path

```python
INTENTS = {
    "health": (["health", "score", "rating", "how good", "how healthy"], ["get_health_score"]),
    "risk":   (["risk", "risky", "volatil", "drawdown", "sharpe", "sortin"], ["get_risk_metrics"]),
    ...
}
```

With no API key, keyword matching selects tools and `_narrate()` turns each
tool's output into sentences from templates. It is not as fluent, and it is
**100% grounded by construction** — the templates can only interpolate values
they were given.

This exists for the PRD's reliability requirement: the platform must stay
fully usable with no external dependency. Measured median latency: **24.4 ms**,
versus a few seconds for the LLM path.

### 11.3 `copilot_grounding.py` — ★ the enforcement

```python
NUMBER_PATTERN = re.compile(r"-?\d[\d,]*\.?\d*")
IGNORE_SMALL_INTEGERS_UPTO = 12
IGNORE_EXACT = {0.0, 1.0, 100.0}
YEAR_RANGE = (1990, 2100)
RELATIVE_TOLERANCE = 0.02
ABSOLUTE_TOLERANCE = 0.51
ABSOLUTE_TOLERANCE_APPLIES_ABOVE = 100.0
```

The algorithm:

1. **Extract** every numeral from the answer.
2. **Collect** every number the tools returned, recursively at any depth.
3. **Match** each claim against that set, within tolerance.
4. **Report** the rate, the unverified figures, and a boolean verdict.

```python
def collect_tool_numbers(payload, values):
    """Percentages are recorded in both forms. A tool reporting
    `volatility_pct: 11.08` may legitimately be narrated as "11.08%" or as
    "0.1108", and both should verify."""
```

```python
def _matches(claim, known):
    for value in known:
        scale = max(abs(claim), abs(value))
        if scale >= ABSOLUTE_TOLERANCE_APPLIES_ABOVE and abs(claim - value) <= ABSOLUTE_TOLERANCE:
            return True
        if scale > 0 and abs(claim - value) / scale <= RELATIVE_TOLERANCE:
            return True
    return False
```

Two tolerances, because rounding is legitimate: a tool returning
`1234567.89` may be narrated as "₹12.3 lakh". The 2% relative tolerance
accepts that. The 0.51 absolute tolerance accepts rounding to the nearest
whole rupee, but **only above 100** — see fix 3 below.

#### Four iterations to get this right

The validator needed four passes. Each failure mode is instructive.

**Fix 1 — `IGNORE_BELOW` was skipping real claims.**
The first version ignored any number below 13, on the theory that small
integers are usually counts ("your 12 holdings") rather than financial claims.
But **a Sharpe ratio of 0.73 is below 13.** So were Sortino, beta, alpha,
Calmar and every ratio in the system — the validator was skipping exactly the
numbers most worth checking. Narrowed to skip only small whole integers and
years:

```python
IGNORE_SMALL_INTEGERS_UPTO = 12     # whole integers only
YEAR_RANGE = (1990, 2100)
```

**Fix 2 — pairwise derived sums were far too permissive.**
An earlier version also accepted any pairwise sum or difference of tool
outputs, reasoning that a reader might compute a total. With a few dozen tool
values that generates **hundreds** of accepted numbers, and the check passed
almost anything. The comment in the file records what it let through:

```python
# Deliberately no derived values. [...] it waved through a fabricated 47.3%
# return. If the model needs a total, it should take it from a tool that
# computes one.
```

Removed entirely. The rule is now: if the model wants a total, it calls a tool
that computes totals.

**Fix 3 — a flat absolute tolerance swallowed small differences.**
A flat 0.51 absolute tolerance means a *claimed* Sharpe of 0.73 matches a
*real* Sharpe of 1.20. Catastrophic for ratios, where 0.5 is the difference
between a mediocre portfolio and a good one. Fixed by applying the absolute
tolerance **only above 100** — where it is about rupee rounding — and relying
on the 2% relative tolerance below that.

**Fix 4 — a false positive on drawdowns.**
The tool returns `max_drawdown: -27.14`. A correct narration is *"the
portfolio fell 27.14% from its peak"* — positive 27.14, because "fell" already
carries the sign. The validator flagged it as unverified. Fixed by also
collecting the `abs()` of every tool value.

That sequence — too permissive, then too strict, then wrong on signs — is what
building a real verification layer looks like. The 100% rate in section 10.4 is
meaningful **because** the validator was adversarially tested against known
fabrications and now catches them.

#### What the API does with the verdict

The `/copilot/chat` response carries:

```json
{
  "answer": "...",
  "tool_calls": [{"tool": "get_risk_metrics", "arguments": {}}],
  "grounding": {
    "numbers_checked": 14, "numbers_verified": 14,
    "groundedness_rate": 1.0, "unverified_numbers": [],
    "is_grounded": true, "tool_values_available": 87
  },
  "mode": "fallback",
  "disclaimer": "WealthOS is an academic research prototype..."
}
```

The grounding report is **returned to the client and displayed in the UI**.
The user can see that 14 of 14 numbers were verified. Verification that
happens invisibly is a claim; verification the user can see is evidence.

**Complexity:**

| Operation | Time | Space |
|---|---|---|
| `extract_numbers` (regex over the answer) | O(A) for answer length A | O(c) claims |
| `collect_tool_numbers` (recursive walk) | O(T) nodes in the tool JSON | O(v) distinct values |
| `_matches` (one claim vs the set) | O(v) | O(1) |
| `check_groundedness` | **O(c · v)** | O(c + v) |

For a typical answer: c ≈ 15 claims against v ≈ 90 tool values = 1,350
comparisons. Microseconds. The *removed* pairwise-derivation step would have
made v ≈ 90² / 2 = 4,050 and the check O(c · v²) — slower *and* useless.

---

## 12. The frontend

Next.js 15 App Router, React 19, Tailwind 4, Recharts 2.15.3. **6,098 lines**
across 28 files.

### 12.1 Route structure — three shells

```
src/app/
├── layout.tsx              root: fonts, AuthProvider
├── page.tsx                /              ← public landing page
├── globals.css             design tokens
├── (marketing)/layout.tsx  public shell: header + footer
├── (auth)/
│   ├── layout.tsx          centred card shell
│   ├── login/page.tsx      /login
│   └── register/page.tsx   /register
└── (dashboard)/
    ├── layout.tsx          Shell: sidebar + top bar, redirects if unauthenticated
    ├── overview/page.tsx       /overview
    ├── portfolio/page.tsx      /portfolio
    ├── risk/page.tsx           /risk
    ├── goals/page.tsx          /goals      + the scenario simulator
    ├── insights/page.tsx       /insights
    ├── copilot/page.tsx        /copilot
    ├── research/page.tsx       /research      ← Model Lab
    ├── data-quality/page.tsx   /data-quality
    ├── import/page.tsx         /import
    └── profile/page.tsx        /profile
```

Parentheses make a **route group**: `(dashboard)` does not appear in the URL,
but every page inside it shares one layout. That is how three completely
different chromes — marketing, auth card, app shell — coexist without any page
knowing which it is in.

`page.tsx` at the root used to redirect to `/login` or `/overview`. It is now a
full marketing page, and a signed-in visitor sees "Go to dashboard" rather
than being bounced.

### 12.2 `globals.css` — the design tokens

```css
:root {
  --surface-0: #070a0e;   /* page ground, deeper than the cards it holds */
  --surface-1: #0e1116;   /* chart + input ground — validated, do not change */
  --surface-2: #11151b;   /* card */
  --surface-3: #1a212a;   /* raised / hover */
  --surface-4: #232c37;   /* control, active */
```

With the comment that governs the whole file:

```css
/* --surface-1 (#0e1116) is the CHART GROUND and is load-bearing. The eight
   series colours in lib/viz.ts were validated against exactly this value for
   the lightness band, chroma floor, colour-vision-deficiency separation,
   normal-vision separation and 3:1 contrast. Changing it silently
   invalidates that work: re-run the palette validator before touching it. */
```

This was a real constraint during the visual redesign. The request was to make
everything feel more premium, which naturally means lifting the surfaces. But
`--surface-1` is the colour the eight chart series were *validated against*.
Lifting it would have silently invalidated the colour-vision-deficiency
separation checks. So everything **around** it was elevated and it stayed at
exactly `#0e1116`.

```css
  --accent: #d4a24c;        /* warm metal, not amber */
  --accent-bright: #e8bd6d;
  --accent-wash: color-mix(in oklab, var(--accent) 12%, transparent);

  --good: #0ca30c; --warning: #c98500; --serious: #d95926; --critical: #e66767;
```

Status colours are **reserved**. They never get reused as a chart series
colour, because then "green" would mean both "good" and "series 6".

```css
  --lift-1: 0 1px 0 0 rgb(255 255 255 / 0.03) inset, 0 1px 2px rgb(0 0 0 / 0.4);
  --lift-2: 0 1px 0 0 rgb(255 255 255 / 0.04) inset,
            0 2px 8px rgb(0 0 0 / 0.45), 0 12px 32px -12px rgb(0 0 0 / 0.6);
```

```css
/* Dark interfaces need shadow plus a top highlight; shadow alone reads as a
   smudge because there is no light surface to cast onto. */
```

Each elevation is an **inset white top-edge highlight plus** an outer shadow.
On a light background a shadow alone implies depth. On a dark background there
is nothing for the shadow to fall onto, so it reads as dirt. The 3–5% white
inset line simulates a light source catching the card's top edge, and that is
what makes the card look like a physical layer.

### 12.3 `lib/viz.ts` — the validated palette

```ts
export const SERIES = [
  "#3987e5", "#d95926", "#199e70", "#c98500",
  "#d55181", "#0ca30c", "#9085e9", "#e66767",
] as const;
```

```ts
/** The series colours are the validated categorical palette, checked against
 *  this app's dark surface for colour-vision-deficiency separation and
 *  contrast. They are assigned in fixed order and never cycled: a ninth
 *  series folds into "Other" rather than inventing a hue, because a repeated
 *  colour makes two different things look like one. */
```

Five gates were checked programmatically against `#0e1116`, not judged by eye:
lightness band, chroma floor, colour-vision-deficiency separation between
adjacent pairs, normal-vision separation, and 3:1 contrast against the surface.

```ts
/** Scatter, bubble and heatmap put every pair on screen at once; only the
 *  first three slots clear the all-pairs separation floors. */
export const SERIES_ALL_PAIRS = SERIES.slice(0, 3);
```

A subtlety worth understanding. In a line chart, series 1 sits next to series
2 and series 2 next to series 3 — only **adjacent** pairs need to be
distinguishable. In a scatter plot every point is next to every other point,
so **all** pairs must separate. Only the first three slots clear that stricter
floor, so scatter charts use three series maximum.

```ts
export const ASSET_CLASS_COLOR: Record<string, string> = {
  equity: SERIES[0], etf: SERIES[2], gold: SERIES[3],
  debt: SERIES[6], cash: SERIES[5], index: SERIES[4],
};
```

Equity is the same blue on the Overview donut, the Portfolio bar and the
Insights timeline. Colour follows the **entity**, never its rank — so
filtering a chart does not repaint the survivors, which would make the reader
think the data changed.

```ts
export function divergingColor(value: number): string {
  if (t >= 0) return `color-mix(in oklab, #2b333d ${(1-a)*100}%, #3987e5 ${a*100}%)`;
  return `color-mix(in oklab, #2b333d ${(1-a)*100}%, #d95926 ${a*100}%)`;
}
```

For the correlation heatmap: two hues with a **neutral grey midpoint**, mixed
in OKLab (perceptually uniform, so equal numeric steps look like equal visual
steps). Never a rainbow — a rainbow scale has no meaningful ordering and
invents false boundaries where hues change fast.

### 12.4 `lib/api.ts` — the typed client

```ts
export class ApiError extends Error {
  constructor(message: string, public status: number, public detail?: unknown) { ... }
}
```

```ts
export const api = {
  login, register, me, updateProfile,
  portfolio, holdings, createHolding, updateHolding, deleteHolding, importCsv,
  transactions, createTransaction, assets,
  analytics, risk, concentration,
  goals, createGoal, updateGoal, deleteGoal, forecastGoal, simulateGoal, healthScore,
  profile, anomalies, forecast, models,
  chat, capabilities,
  research,
};
```

Every endpoint has a method and an interface — `PortfolioSummary`, `RiskReport`,
`HealthScore`, `Simulation`, `ResearchReports`, and 20 more. `tsc --noEmit`
then catches a field rename at compile time rather than as `undefined` in
production.

The token lives in `localStorage` and is attached as a `Bearer` header by the
shared `request()` helper, so no page handles auth itself.

### 12.5 `lib/auth.tsx` — session and data loading

```tsx
const refresh = useCallback(async () => {
  if (!getToken()) { setUser(null); setLoading(false); return; }
  try { setUser(await api.me()); }
  catch {
    clearToken();        // an invalid stored token must not leave the app in limbo
    setUser(null);
  } finally { setLoading(false); }
}, []);
```

The `catch` matters. An expired token in `localStorage` would otherwise leave
the app permanently loading: it has a token, so it thinks it is signed in, but
every request 401s. Clearing it on failure sends the user cleanly to `/login`.

```tsx
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = []) {
  useEffect(() => {
    let cancelled = false;
    loader()
      .then((result) => { if (!cancelled) setData(result); })
      .catch((err: Error) => { if (!cancelled) setError(err.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, deps);
  return { data, error, loading };
}
```

The `cancelled` flag is the React race-condition fix. If the user navigates
away while a request is in flight, the response arrives for an unmounted
component. Without the flag, `setData` on an unmounted component warns and can
overwrite newer data. The cleanup function sets `cancelled = true`, so the
late response is discarded.

One hook gives every page `{data, error, loading}`, which is why all twelve
pages render loading skeletons and error states consistently.

### 12.6 `components/ui/index.tsx` — 21 primitives

| Primitive | Purpose |
|---|---|
| `Card` | glass surface + lit top edge, with `tone` variants |
| `CardHeader` | title, subtitle, optional eyebrow label and action |
| `Section` | page section with a title and a lede |
| `Stat` | a figure with a label, in `sm`/`md`/`lg` |
| `Meter` | a horizontal bar, used for the Health components |
| `Badge` | status pill, tone-coloured |
| `Button` / `LinkButton` | matched button and link styling |
| `Field` / `inputClass` | labelled form field |
| `Slider` | the simulator's range inputs |
| `Spinner` / `Skeleton` | loading states |
| `Empty` | no-data state, with a call to action |
| `ErrorNote` | a failed request |
| `Unavailable` | **a model or report that is missing, with the reason** |
| `Hairline` | a 1px rule |
| `Assumptions` | **the assumptions panel every projection carries** |
| `Note` | a callout |
| `MetricRow` | label / value / note row |

Two of these exist purely to serve the project's principles. `Unavailable`
makes the degradation convention a *component*, so every panel degrades the
same way. `Assumptions` makes "every number carries its assumptions" a
reusable thing rather than a habit someone might forget.

Changing `Card` restyles all twelve pages, which is how the visual elevation
happened without rewriting a single page.

### 12.7 `components/ui/shell.tsx` — the app chrome

```tsx
/** Navigation is grouped so the dashboard reads as a wealth service with a
 *  research wing, rather than a flat list of eight equal pages. */
const NAV_GROUPS = [
  { label: "Wealth",       items: [Overview, Portfolio, Risk, Goals] },
  { label: "Intelligence", items: [Insights, Copilot] },
  { label: "Research",     items: [Model Lab, Data Quality] },
  { label: "Account",      items: [Import, Profile] },
];
```

The grouping is information architecture, not decoration. A flat list of ten
links says "these are all the same kind of thing". Four named groups say what
the product *is*: wealth management, with intelligence on top and research
behind it.

```tsx
useEffect(() => {
  if (!loading && !user && typeof window !== "undefined") {
    window.location.href = "/login";
  }
}, [loading, user]);
if (loading || !user) return <LoadingShell />;
```

```tsx
// A protected page must not flash its chrome before the session resolves.
```

Without the `if (loading || !user) return` guard, an unauthenticated visitor
would see the sidebar and the top bar for a few hundred milliseconds before
the redirect — which looks broken and briefly implies they are signed in.

The top bar shows live portfolio value and day gain on every page, which is
the single detail that most makes the app feel like a wealth service rather
than a reporting tool.

### 12.8 `components/charts/index.tsx` — 19 charts

| Chart | Where | Form |
|---|---|---|
| `AllocationDonut` | Overview, Portfolio | donut with a centre total |
| `CumulativeReturnChart` | Overview | two lines, portfolio vs NIFTY |
| `DrawdownChart` | Risk | area below zero |
| `SectorBar` | Portfolio | horizontal bars |
| `RiskReturnScatter` | Risk | scatter, ≤ 3 series |
| `CorrelationHeatmap` | Risk | diverging cells |
| `GoalProjectionChart` | Goals | line with a target rule |
| `ProjectionFan` | Goals simulator | percentile bands |
| `HealthBreakdown` | Overview | six component meters |
| `AnomalyTimeline` | Insights | error over time with a threshold line |
| `ClusterComparison` | Insights | centroid vs this user |
| `SilhouetteByK` | Model Lab | line, chosen k marked |
| `ClusterMapScatter` | Model Lab | 2,400-point PCA map |
| `LossCurve` | Model Lab | train vs holdout |
| `SkillByHorizon` | Model Lab | grouped bars, 4 horizons |
| `MetricComparisonBars` | Model Lab | autoencoder vs Isolation Forest |
| `CountMatrix` | Model Lab | archetype × cluster crosstab |
| `MagnitudeBars` | Model Lab, Data Quality | feature importances, impacts |

Rules applied to all nineteen:

- **One y-axis, never two.** Two measures of different scale get two charts.
  A dual-axis chart lets the author choose where the lines cross, which means
  the reader can be shown any relationship the author prefers.
- **A legend whenever there are ≥ 2 series**, so identity is never
  colour-alone — which matters for colour-blind readers and for printing.
- **Selective direct labels**, never a number on every point.
- **Recessive grid and axes** (`--grid: #1a212a`, `--axis: #3c4654`) so the
  data is the only thing with contrast.
- **Hover tooltips** on every chart, because an SVG chart in a browser *is*
  interactive and a static one wastes that.

### 12.9 `components/ui/simulator.tsx` — the scenario simulator

```tsx
// 4 sliders: monthly contribution, expected return, volatility, horizon
// debounced 260ms → POST /api/v1/goals/{id}/simulate
```

```tsx
<div data-testid="success-probability">{pct(sim.success_probability)}</div>
```

Three decisions:

1. **No projection maths in the browser.** It calls the API, which uses
   `wealthos_core/goals.py`. A JavaScript Monte Carlo would be a second
   implementation free to drift. One definition.
2. **Debounced at 260 ms.** Dragging a slider fires dozens of change events;
   without debouncing each would be an API call. 260 ms is below the threshold
   where a UI feels laggy and above the rate at which a drag generates events.
3. **A `data-testid` on the probability.** The first Playwright test matched
   `/^\d+%$/`, which also matched a goal card showing "2%". An explicit test id
   makes the assertion unambiguous.

The panel frames the fan explicitly as *a range of outcomes under stated
assumptions*. A single confident line would be the wrong thing to draw.

### 12.10 `lib/reports.ts` — safe access into pipeline JSON

```ts
function walk(source: Source, path: string): unknown {
  let node: unknown = source;
  for (const key of path.split(".")) {
    if (node === null || typeof node !== "object") return undefined;
    node = (node as Record<string, unknown>)[key];
  }
  return node;
}
export function num(source: Source, path: string, fallback = 0): number {
  const value = walk(source, path);
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}
```

```ts
/** The reports are JSON written by Python and deliberately typed loosely on
 *  the client: mirroring every nested field in TypeScript would be a standing
 *  maintenance cost that buys no real safety, since the shape is owned by the
 *  pipelines rather than by this app.
 *
 *  What does matter is that a page never crashes because a stage has not been
 *  run. */
```

A reasoned exception to the strict typing used everywhere else. The reports are
deeply nested and owned by Python; mirroring them in TypeScript would be a
maintenance burden that provides no guarantee, because Python can change the
shape without TypeScript noticing. The actual requirement is *never crash on a
missing report*, and dotted-path accessors with typed fallbacks deliver that.

```ts
/** For a value that is genuinely absent rather than zero — a missing score
 *  and a score of zero must not render the same way. */
export function maybeNum(source: Source, path: string): number | null
```

A real distinction. `num(..., 0)` would render a missing silhouette score as
"0.00", which reads as "the clustering failed". `maybeNum` returns `null` and
the page renders "—".

### 12.11 The landing page

```tsx
const clusteringAri = num(models?.clustering,
                          "archetype_recovery.adjusted_rand_index",
                          FALLBACK.clusteringAri);
```

Every metric on the marketing page is read **live** from
`/api/v1/research/reports`. The sections are: hero with a real product
screenshot, a trust strip, the four problems from the PRD, four capability
blocks, the measured results, how it works, and a prominent prototype
disclaimer.

Reading them live rather than hard-coding them means **the marketing page
cannot drift from what the models actually scored.** Retrain a model and the
landing page updates. Hard-coded numbers in a marketing page are how a project
ends up claiming an accuracy it no longer has. `FALLBACK` values exist only so
the page renders before the fetch resolves or if the API is down.

---

## 13. Complexity reference

All in one place. **n** = observations, **m** = assets/holdings, **h** =
holdings, **R** = rows, **I** = investors, **A** = assets, **M** = months,
**P** = Monte Carlo paths, **d** = features, **k** = clusters, **L** =
sequence length, **H** = hidden units, **T** = trees.

### 13.1 Core library

| Function | Time | Space | Note |
|---|---|---|---|
| `simple_returns`, `log_returns` | O(n) | O(n) | single vectorised pass |
| `wealth_index`, `cumulative_return_series` | O(n) | O(n) | `cumprod` |
| `total_return`, `annualized_return` | O(n) | O(1) | |
| `annualized_volatility` | O(n) | O(1) | |
| `cagr`, `future_value`, `required_monthly_contribution` | **O(1)** | O(1) | closed form |
| `drawdown_series`, `max_drawdown` | O(n) | O(n) | `cummax` |
| `drawdown_detail` | O(n) | O(n) | 3 slices + 2 `idxmax` |
| `downside_deviation` | O(n) | O(n) | |
| `value_at_risk` (historical) | O(n) avg | O(n) | partition-based selection |
| `conditional_value_at_risk` | O(n) | O(n) | mask + mean |
| `beta`, `alpha` | O(n log n) | O(n) | the align may sort |
| **`correlation_matrix`** | **O(m²n)** | **O(m²)** | most expensive core function |
| `average_pairwise_correlation` | O(m²n) | O(m²) | |
| `sharpe`/`sortino`/`calmar`/`treynor` | O(n) | O(1) | each |
| `performance_summary` | O(n) | O(n) | ~10 linear passes |
| `normalize_weights`, `herfindahl_index` | O(m) | O(m) | |
| `concentration_report` | O(m log m) | O(m) | sort for display |
| `time_weighted_returns` | O(n) | O(n) | |
| `money_weighted_return` | O(200 · f) | O(f) | 200 bisection steps |
| `portfolio_returns_from_weights` | O(mn) | O(n) | |
| `compute_health_score` | **O(1)** | O(1) | given its inputs |
| `sensitivity_analysis` | O(1) | O(1) | 28 × O(1) re-scores |
| `projection_path` | O(M) | O(M) | |
| **`monte_carlo_paths`** | **O(P · M)** | **O(P · M)** | 2,000 × 76 ≈ 1.2 MB |

### 13.2 Backend

| Operation | Time | Space | Note |
|---|---|---|---|
| Startup cache load | O(R) | **O(D · A) ≈ 1.9 MB** | 232,287 rows → 4,069 × 58 |
| `market_cache.panel` | O(1) | O(1) | already in RAM |
| `latest_prices` | O(D · A) | O(A) | last valid per column |
| `returns(symbols, range)` | O(d · m) | O(d · m) | frame slice |
| `get_current_user` | O(log N) | O(1) | PK index |
| `get_holdings` | O(log N + h) | O(h) | **one** query, `joinedload` |
| `value_holdings` | O(h) | O(h) | |
| `build_summary` | O(h log h) | O(h) | top-holdings sort |
| `/analytics` | O(6n) | O(n) | six nested windows |
| **`/analytics/risk`** | **O(m²n)** | O(m²) | correlation dominates |
| `/analytics/concentration` | O(m log m) | O(m) | |
| `/goals/{id}/forecast` | O(M) | O(M) | |
| **`/goals/{id}/simulate`** | **O(P · M)** | O(P · M) | ~25 ms for 2,000 × 76 |
| `/goals/health-score` | O(m²n) | O(m²) | needs the correlation input |
| `import_holdings_csv` | O(r) | O(r) | r ≤ 5,000, validate-then-write |
| `/copilot/chat` (fallback) | O(c · v) | O(c + v) | median 24.4 ms |
| `/copilot/chat` (LLM) | network-bound | — | ≤ 6 tool rounds |
| `/research/reports` | O(1) after first | O(report size) | in-memory cache |
| `hash_password` | **O(2¹²) ≈ 250 ms** | O(1) | **intentionally slow** |
| JWT encode / decode | O(1) | O(1) | HMAC |

### 13.3 Database queries

| Query | Index | Complexity |
|---|---|---|
| User by id | primary key | O(log N) |
| Holdings for a user + assets | `ix_holdings_user_asset` | O(log N + h) |
| Price history, asset × range | `ix_market_prices_asset_date` | O(log N + k) |
| All prices (startup) | `ix_market_prices_date` | O(N) sequential |
| Newest alerts | `ix_alerts_user_created` | O(log N + k) |
| Insert price chunk | B-tree maintenance | O(C log N) per chunk |

### 13.4 Pipelines

| Stage | Time | Space | Bottleneck |
|---|---|---|---|
| 01 ingest | O(F · R) ≈ 5.4M rows | ~400 MB peak | file I/O |
| 02 fetch | O(S) requests, 0.6 s delay | O(S · D) | network politeness |
| 03 build prices | O(S · D) + O(D log D) splice | O(D · S) ≈ 1.9 MB | — |
| 03b validate | O(S · D) | O(D) | — |
| 04 seed | O(R log R) | O(C) per chunk | index maintenance |
| 05 priors | O(N) exact + **O(U · V · L²)** fuzzy | O(N) | fuzzy matching |
| **06 cohort** | **O(M · I · A)** ≈ 103M ops | **O(R · cols) ≈ 230 MB** | the snapshot table |
| 07 features | O(R log R) + O(R · W) | three 1.1–1.25M-row tables | groupby + rolling |

### 13.5 Model training

| Model | Time | Space | Note |
|---|---|---|---|
| K-Means, one fit | O(n·k·d·i) ≈ 20M ops | O(n·d + k·d) | sub-second |
| K-Means `n_init=10`, k=2..10 | ×10 × 9 candidates | same | |
| **Silhouette (full)** | **O(n²·d)** ≈ 1.4B | O(n²) | **sampled to 5,000** |
| Davies–Bouldin | O(n·k·d) | O(k·d) | full set |
| Gaussian Mixture | O(n·k·d·i) | O(n·k) | diagonal covariance |
| **Agglomerative** | **O(n³)** | **O(n²) ≈ 760 MB** | **subsampled to 4,000** |
| Bootstrap stability | 20 × 2 × O(0.8n·k·d·i) | O(n) | |
| ARI / NMI | O(n + k²) | O(k²) | |
| Autoencoder, 1 epoch | O(N · P), P = 2,878 | O(B · d) | B = 1,024 |
| Autoencoder, 30 epochs | ≈ 6.7 × 10¹⁰ FLOPs | — | |
| AE inference | O(N · P) batched at 8,192 | O(8192 · d) | |
| Isolation Forest build | O(t·ψ·log ψ), t=200, ψ=256 | O(t·ψ) | very cheap |
| Isolation Forest score | O(t · log ψ) **per row** | O(1) | ≈1,600 ops/row |
| XGBoost, one tree | O(d·n·log n) | O(n·f) | |
| XGBoost full + grid | O(4 · T · d · n · log n), T ≤ 1,500 | O(T · 2^d) | early stopping |
| LSTM forward, 1 sequence | O(L·4·H·(F+H)) ≈ 141k | O(L·H) | 6,561 params |
| GRU forward | O(L·3·H·(F+H)) | O(L·H) | **25% cheaper**, 5,057 params |
| Sequence epoch | O(N_seq·L·H·(F+H)) ≈ 6.4 × 10¹⁰ | O(B·L·F) | |
| **Sequence array** | — | **O(N_seq·L·F) ≈ 605 MB** | **the project's space bottleneck** |

### 13.6 The three places complexity actually changed the design

Worth being able to name these, because they are the moments where a
complexity analysis produced a decision rather than a footnote.

**1. Silhouette, O(n²·d) → sampled to 5,000.** Nine candidate values of k ×
1.4 billion operations each is 12.6 billion. Sampling cuts it 3.8× per
candidate with no meaningful loss of precision in a *mean* statistic. The
comment is in the code.

**2. Agglomerative clustering, O(n²) space → subsampled to 4,000.** A full
9,743-point distance matrix is 760 MB and the linkage is O(n³). The subsample
is disclosed in the report's `note` field, so a reader knows that comparator
was fitted on less data.

**3. The sequence array, 605 MB → float32 and chunked inference.** float64
would be 1.2 GB. float32 halves it, is required by Apple's MPS backend anyway,
and loses no precision that matters for a 32-unit RNN. Inference is chunked at
4,096 so peak memory does not scale with the test-set size.

And one where it changed the *architecture*: the market price panel is
**O(D · A) = 1.9 MB in RAM**, which is small enough to cache process-wide. That
single observation is why every analytics endpoint is in-memory arithmetic
instead of a database round trip, and it is the main reason the latency target
is met.

---

## 14. Testing

**313 Python tests + 12 Playwright browser tests.** All passing.

### 14.1 Core library — 127 tests (0.27 s, no database)

| File | Tests | What it proves |
|---|---|---|
| `test_returns.py` | 14 | Hand-calculated returns; +10%/−10%/+10% = +8.9% |
| `test_risk.py` | 20 | Drawdown dates, VaR vs CVaR ordering, beta of a series against itself = 1 |
| `test_metrics.py` | 12 | All four ratios; a constant series gives `NaN`, not 1.9e16 |
| `test_concentration.py` | 16 | HHI floors and ceilings, effective holdings, percentage/fraction equivalence |
| `test_portfolio.py` | 17 | Time-weighted vs naive returns; XIRR against a known answer |
| `test_health.py` | 16 | Contributions sum to the total; missing components renormalise; empty portfolio is not "Poor" |
| `test_goals.py` | 30 | Percentile ordering p10 ≤ … ≤ p90; zero volatility collapses the fan onto the deterministic line; fixed seed is reproducible; probability ∈ [0,1] |

(125 test functions; two are parametrised, so pytest collects 127.)

These are **hand-calculated**, not snapshot tests. A snapshot test tells you a
number changed; a hand-calculated test tells you which number is right.

### 14.2 Backend — 145 tests against a real test database

| File | Tests | Highlights |
|---|---|---|
| `test_auth.py` | 13 | A 73-byte password is rejected; a malformed hash is a failed login; a non-access token is refused |
| `test_portfolio.py` | 28 | Duplicate CSV symbols merge at weighted average cost; an invalid row rejects the whole file; 2 MB cap |
| `test_analytics.py` | 15 | Thin history returns a stated reason, not a number; assumptions present on every response |
| `test_goals_health.py` | 19 | Another user's goal returns **404 not 403**; simulator overrides are clamped to `SIMULATION_BOUNDS` |
| `test_insights.py` | 13 | A missing artifact degrades one panel; 18 months of history is refused by the sequence model |
| `test_copilot.py` | 21 | A fabricated number is caught; a drawdown narrated as positive is not a false positive; no tool can write |
| `test_research.py` | 17 | Returns 200 **without** a token, and leaks no user data; a missing report degrades |

### 14.3 ML — 41 tests on data and artifacts

```python
"""A model whose metrics silently regress below its baseline should fail the
build, not appear in a report."""
```

`test_data_quality.py` (17) asserts properties the pipeline **promises**: the
panel is sorted and unique by date; every price is positive; every asset class
is represented; **no phantom crash survives into the panel**; the RELIANCE
bonus date is adjusted; cash grows monotonically; debt is less volatile than
equity; both splices passed their gates; the adjustment impact was quantified.

`test_models.py` (23) asserts each artifact loads, accepts the exact feature
contract it was fitted on, returns the right shape, and **clears the bar the
project claims** — clustering ARI, anomaly PR-AUC above the Isolation Forest,
forecast skill above the mean-drift baseline. Plus
`test_feature_splits_do_not_overlap_in_time` and
`test_no_target_column_is_exposed_as_a_feature`.

### 14.4 Playwright — 12 tests in real Chromium

1. The full journey: sign up → import → overview → risk → goals → insights → copilot
2. A malformed CSV is rejected in full and says why
3. An empty portfolio explains itself instead of showing broken charts
4. Protected pages redirect an anonymous visitor to sign in
5. The landing page is public and routes to sign-up
6. `/research/reports` needs no account
7. The Model Lab renders real training evidence
8. The Data Quality page shows the corporate-action finding
9. The scenario simulator responds to input
10–12. Screenshot capture across all 12 routes

### 14.5 ★ Three bugs a green test suite could not see

This is the most useful lesson in the testing section.

| Bug | Why tests missed it |
|---|---|
| The allocation donut's legend crushed to **"5", "2", "2", "3"** | The labels were *present* in the DOM, so every assertion passed. They were visually truncated. Fixed by widening the legend basis |
| A goal showed **0% funded** in the list and **166%** in its own forecast panel beside it | Both numbers rendered. They used different denominators. No test compared two components against each other |
| The simulator truncated its own axis label to **"LOWER QUARTI"** | The text node existed. It was clipped by a narrow parent. Fixed by moving the panel full-width |

All three were **obvious in a screenshot and invisible to 325 passing tests.**
The project's `e2e/screenshots.spec.ts` exists for exactly this: capture all
12 pages, then *look at them*. Assertions verify logic; eyes verify layout.

### 14.6 CI

`.github/workflows/ci.yml` runs on push: install, `pytest -q`,
`tsc --noEmit`, `pnpm lint`.

---

## 15. Worked end-to-end examples

### Example 1 — Importing a portfolio

**Input** `docs/sample-holdings.csv`:

```csv
symbol,quantity,average_price
RELIANCE,50,2400
INFY,80,1450
HDFCBANK,60,1520
TCS,25,3300
NIFTYBEES,200,210
GOLDBEES,300,52
```

**What happens:**

1. `POST /api/v1/portfolio/import`, size checked against `MAX_UPLOAD_BYTES` (2 MB).
2. Header validated against `REQUIRED_CSV_COLUMNS = {symbol, quantity, average_price}`.
3. **Every row validated before anything is written** — symbol exists in the
   58-asset universe, quantity > 0, price > 0, date parses.
4. Duplicate symbols pre-merged at weighted average cost.
5. `_cost_basis_warning()` compares each cost basis against the adjusted price
   on that date. HDFCBANK at 1,520 against an adjusted price of ~750 triggers:
   *"2.03× the adjusted price, close to a 1:2 corporate action factor."*
6. `db.flush()`, then commit. Response: 6 imported, 0 errors, 1 warning.

**If row 3 had quantity `-60`:** nothing is written at all, and the response
returns `{"row": 3, "field": "quantity", "error": "must be greater than 0"}`.
A half-imported portfolio produces analytics that are confidently wrong.

### Example 2 — The Risk page

`GET /api/v1/analytics/risk`

1. `get_current_user` → JWT decoded, user 7 loaded (O(log N)).
2. `portfolio_weights` → 6 weights from holdings × latest prices.
3. `market_cache.returns(symbols)` → 4,069 × 6 frame, **from RAM**.
4. `dropna(how="any")` → 4,069 usable dates, all above the 60 minimum.
5. `portfolio_returns_from_weights` → one weighted return series, O(mn).
6. Core functions: volatility, `drawdown_detail`, VaR, CVaR, beta, alpha,
   Sharpe, Sortino, Calmar, `correlation_matrix` (O(m²n) = 6² × 4,069).
7. Response includes the metadata block: *"current weights held constant over
   history"*, `risk_free_rate: 0.06`, `rebalancing: daily`, `symbols_excluded: []`.

`X-Response-Time-ms: 41.3`. The UI prints every assumption beneath the chart.

### Example 3 — Asking the Copilot

**Question:** *"How risky is my portfolio?"*

**LLM path:** the model calls `get_risk_metrics`, receives JSON, and writes
two paragraphs. Before the response is returned, `check_groundedness` extracts
every numeral and matches it against that JSON. Suppose it wrote *"a Sharpe
ratio of 0.73"* when the tool said `0.68`:

```
relative difference = |0.73 − 0.68| / 0.73 = 0.068  →  6.8% > 2% tolerance
absolute tolerance does not apply (0.73 < 100)
→ 0.73 lands in unverified_numbers, is_grounded = false
```

The grounding report goes to the client and the UI shows that one number could
not be verified.

**Fallback path** (no API key): `_select_tools` keyword-matches "risky" →
`["get_risk_metrics"]`, `_narrate` fills a template. Grounded by construction.
**24 ms.**

### Example 4 — The scenario simulator

**Setup:** goal ₹50,00,000 by April 2033. Saved ₹8,50,000. Contributing
₹25,000/month. Portfolio's estimated return 11%, volatility 14%.

**Deterministic** (`GET /goals/{id}/forecast`):

| | |
|---|---|
| Months remaining | 76 |
| Projected value | **₹43,26,923** |
| Funded | 86.5% |
| Required monthly | ₹31,277 (a gap of ₹6,277) |
| Pessimistic / Expected / Optimistic | ₹34,40,978 / ₹43,26,923 / ₹54,32,851 |

**Monte Carlo** (`POST /goals/{id}/simulate`, 2,000 paths, seed 42):

| Percentile | Final value |
|---|---|
| p10 | ₹29,96,484 |
| p25 | ₹34,76,262 |
| **p50** | **₹41,21,167** |
| p75 | ₹49,00,600 |
| p90 | ₹58,23,784 |
| **Probability of reaching ₹50L** | **23.3%** |

Two readings the UI makes explicit:

- The median (₹41.2L) is **below** the deterministic projection (₹43.3L). That
  is volatility drag — compounding is multiplicative, so 0.8 × 1.2 = 0.96, not 1.
- "86.5% funded" and "23.3% chance of success" are both true. The first is the
  single most likely path; the second is how often that path or better occurs.

Drag the contribution slider to ₹32,000 and the probability climbs past 50%.
Set volatility to 0 and all five bands collapse onto ₹43,26,923 exactly.

---

## 16. Honest limitations

Stated here and in `docs/limitations.md`, because a prototype that claims
nothing it cannot support is worth more than one that oversells.

| Limitation | Detail |
|---|---|
| **The cohort is simulated** | 10,000 investors and 1.25M monthly snapshots are generated, not observed. Only the prices are real |
| **Anomalies are injected** | Deliberately unambiguous, so PR-AUC 0.9355 is an **upper bound** on real-world performance |
| **Dormancy breaks are poorly detected** | Recall 0.4667. Reported, not hidden. Needs a sequence model, not a lower threshold |
| **Short-horizon forecasts have almost no skill** | 0.038 at 1 month, 0.005 at 3 months. This is the correct result, not a failure |
| **Risk uses current weights over full history** | Not a transaction-accurate replay. Stated in every response's metadata |
| **Goals are not asset-earmarked** | The whole portfolio counts toward every goal. Stated in the response |
| **Live features are reconstructed** | A real user's monthly history assumes they always held what they hold now. Wrong for anyone who has traded; the caveat is printed |
| **Monte Carlo assumes normal returns** | Real returns have fatter tails and negative skew, so extreme bands are if anything **optimistic** |
| **Big Sharks is institutional, not retail** | Used as a loose shape for concentration, never as a retail benchmark |
| **Universe is 58 assets** | NIFTY 50 plus ETF/gold/debt/cash. Not mutual funds, bonds, property or crypto |
| **One missing symbol** | 50 of 51; `MM` resolved as `M&M` |
| **Docker configs are unverified** | Written, never built and run. Marked as such |
| **Not financial advice** | An academic research prototype. It explains computed metrics and recommends nothing |

---

## 17. Viva questions and answers

### On the data

**Q: What was the single hardest data problem?**
The Kaggle NSE closing prices are not adjusted for corporate actions. RELIANCE
shows −50.3% on 2017-09-07 and TCS −50.5% on 2018-05-31; both are 1:1 bonus
issues, not crashes. 78 such phantom moves across the universe. Uncorrected,
INFY's max drawdown reads −87.9% instead of −36.5% and its Sharpe flips from
−0.30 to **+0.43**. Fifteen symbols had their Sharpe's sign inverted. Stage
03b exists purely to quantify this as permanent evidence.

**Q: Why not just delete the outliers?**
Because an extreme move in Indian equity history is usually a real event. Delete
the 20 worst days from fifteen years and you have deleted March 2020 — every
volatility, drawdown and VaR figure afterwards is wrong in the flattering
direction. Stage 01 flags and reports; it never drops.

**Q: You repaired some prices. Isn't that the same thing?**
No — and the distinction is in the code. `repair_reverting_spikes` only repairs
**round trips**: a price that drops to a tenth, holds two sessions, and returns
to its previous level. A real split never reverts. A one-way jump is left alone
specifically so the validation gate still fails on a genuine unadjusted
corporate action rather than having it smoothed away.

**Q: Why two different splice standards?**
Because the two joins are different claims. Kaggle "NIFTY 50" and Yahoo ^NSEI
are literally the same index, so they must agree: correlation ≥ 0.95 and
level-ratio drift < 2%. Measured correlation was **1.0000** over 3,374 days.
The debt handoff swaps one instrument for a related but distinct one, so it is
held to ≥ 0.80 correlation and recorded in the data dictionary as an
**instrument change**. It measured 0.8581. A third candidate, LTGILTBEES, was
rejected by the gate.

**Q: 78 phantom moves or 28?**
Both, in different windows. 78 across the full available history; 28 within the
2012-01-01 → 2021-07-01 window where both sources overlap, affecting 24 of 51
symbols. Each page states its own window.

### On the models

**Q: Why is clustering evaluated with ARI and not just silhouette?**
Silhouette says whether the clusters are **tight**. ARI says whether they are
the **right** clusters. A model can score well on the first while recovering
nothing real. Because the cohort was generated from six known archetypes, ARI
against the true label is measurable: **0.9465**. ARI also corrects for chance
agreement, which an unadjusted Rand Index does not.

**Q: Why k = 7 when there are 6 archetypes?**
Silhouette peaks at 7 (0.3707) and Davies–Bouldin is best there too. The
seventh cluster is a **boundary cluster** — 221 investors scattered across all
six archetypes. It exists because the archetypes were designed to overlap, and
its presence is why ARI is 0.9465 rather than 1.0. An ARI of 1.0 would mean
the cohort was too easy.

**Q: Why is the autoencoder so small?**
2,878 parameters, with a 6-unit bottleneck. **Capacity is the enemy here.** A
high-capacity network reconstructs anomalies as faithfully as normal rows,
which defeats the approach entirely. The bottleneck is what forces the model
to learn only typical structure.

**Q: Why PR-AUC and not ROC-AUC?**
Positives are 0.34% of the data. ROC-AUC uses the false-positive rate, whose
denominator is 288,989 negatives, so flagging 3,579 rows — more than three
times too many — barely dents it: the Isolation Forest still scores 0.9734.
PR-AUC uses the positive class as the denominator and feels those false alarms
immediately: 0.3255 versus the autoencoder's **0.9355**. The Isolation Forest's
precision is 0.178 — four of five alerts are wrong.

**Q: Why include an Isolation Forest at all?**
A deep model that cannot beat a standard shallow detector has not earned its
place in the system, and reporting only the autoencoder's score would hide
that. It won by +0.61 PR-AUC, so it stayed.

**Q: Your forecast R² is only 0.149. Isn't that bad?**
That is R² on **excess log growth** — the honest target. On raw rupee value the
same model scores 0.973, and a baseline that predicts "same value plus
deposits" scores **0.9625** while knowing nothing. Portfolio value at t+h is
dominated by value at t plus contributions, so R² on value measures scale, not
skill. 0.149 on the honest target means a 24.9% reduction in squared error
against the best constant forecast. Modest, real, and defensible.

**Q: Why three baselines?**
The zero-return baseline is flattering because it ignores market drift — it is
biased low by roughly the average market return. Against it, XGBoost looks
like 0.48 skill at 12 months. Against the **mean-drift** baseline (predict the
training-set mean), the same model scores **0.153**. Nothing changed but the
reference, and the lower number is the true one. The third baseline
extrapolates the investor's own trend and scores −2.48 — dramatically worse
than a constant — which is a finding worth reporting because it is the
intuitive thing a person would try.

**Q: Why does 1-month skill look so poor?**
Because one month of portfolio growth is almost entirely one month of market
noise, and market noise is not predictable. 0.038 is the correct result. A
project reporting 1-month skill of 0.6 should be disbelieved.

**Q: Why do different models win at different horizons?**
At 1 month the GRU's simpler gating (3 gates vs the LSTM's 4) overfits less
when there is barely any signal. At 3 months only the tree model finds
anything. At 6 and 12 months the sequence models pull ahead, because the signal
lives in the **trajectory** — momentum, volatility regime, drawdown recovery —
and a 24-month window sees that while a single-row feature vector cannot.

**Q: How do you know there's no leakage?**
Four mechanisms. Splits are **chronological by date alone**, shared by all
investors, so the test set is a market period never seen. Sequence windows are
assigned by the split of the **target month**. There is a test,
`test_feature_splits_do_not_overlap_in_time`. And `market_volatility_12m`
rather than `log_value` tops the feature importances — if the model had found a
way to restate the current balance, `log_value` would dominate.

**Q: Why not a random train/test split?**
Because March 2020 rows would land in both. The model would have *seen* the
COVID crash during training and would then be scored on predicting it. The
accuracy would be excellent and completely fake.

### On the architecture

**Q: Why a separate core package?**
Because both the API and the ML pipelines need the same formulas. If Sharpe
lived in the backend, training a model on a Sharpe feature would mean either
importing FastAPI into a training script or writing Sharpe twice. A third
package both import is the only arrangement where the formula cannot drift —
and it is installed with `pip install -e .`, so there is one copy on disk.

**Q: What is train/serve skew and how is it prevented?**
A model learning from one definition of a feature and being served a slightly
different one. Prevented structurally: `performance_summary` is the single
function both sides call. The cohort simulator even uses the same
`time_weighted_returns` — had it used a naive `pct_change`, the models would
have trained on inflated returns and been served correct ones, appearing to
work while being subtly wrong.

**Q: Why cache prices in memory?**
4,069 dates × 58 assets × 8 bytes ≈ **1.9 MB**. That single complexity
observation is why every analytics endpoint is in-memory arithmetic rather
than a database round trip, and it is the main reason the latency target is
met. It is safe because market prices are reference data — identical for every
user, so a shared cache cannot leak between accounts.

**Q: What stops one user reading another's portfolio?**
`get_current_user` plus the `user.id` filter in every query. That is the whole
mechanism, and it is worth knowing explicitly. Every failure path raises the
*same* error so a token cannot be used to enumerate user ids, and another
user's goal returns **404 not 403**, because a 403 would confirm it exists.

**Q: Why is `/research/reports` public?**
Because it carries no user data — every figure describes the training cohort or
the market data. It also touches **no database at all**, only cached JSON
files. That is what lets the landing page quote live model metrics to an
anonymous visitor. There is a test asserting it returns 200 without a token
and leaks nothing resembling user data.

### On the Health Score

**Q: Why not learn the score?**
It would have been easier and impossible to defend. "Your score is 61 because
the gradient boosting said so" is not an explanation. Every component is a
documented function of measurable inputs, the contributions sum exactly to the
total (14.72 + 15.74 + 11.91 + 7.51 + 15.77 + 13.09 = 78.74), and
`sensitivity_analysis` shows which inputs actually move it.

**Q: Where do the weights come from?**
A stated rationale, not tuning. Diversification and risk are highest because
they drive the outcomes a retail investor is least equipped to see unaided.
Goal alignment matches them because a portfolio excellent in isolation can
still be failing its purpose. Liquidity is lowest because every asset in this
universe is exchange-traded, so the component has little room to discriminate.

**Q: What if a component cannot be measured?**
It is excluded and the remaining weights renormalise. A user with no goals is
scored out of 80, not penalised 20 points, and the summary says *"Scored on 5
of 6 components; goal alignment could not be measured."*

### On the Copilot

**Q: How do you know it does not invent numbers?**
Because it is checked, not trusted. Every numeral in every answer is extracted
and matched against the tool outputs that produced it. Measured over 30
questions: **458 of 458 verified**. The grounding report is returned to the
client and shown in the UI.

**Q: 100% sounds too good.**
It is measured on the deterministic fallback path, where 100% is the **floor**,
not an achievement — the templates can only emit numbers they were handed, so
anything below 100% means the validator or the templates are broken. The real
value of the measurement is as a regression test on the validator, which took
**four iterations** to get right: it once passed a fabricated 47.3% return
because it accepted pairwise sums of tool outputs, and it once skipped every
Sharpe ratio because it ignored numbers below 13.

**Q: Could it be prompt-injected into placing a trade?**
No, and not because of the prompt. **There is no tool that writes.** All eight
are read-only, so the capability does not exist to be exploited. Tool arguments
also come from the SDK's parsed JSON, never from regexing model text.

**Q: Why does it work without an API key?**
The PRD's reliability requirement. With no key, keyword matching selects the
same eight tools and templates narrate them — less fluent, 100% grounded,
24 ms median latency. The platform never depends on an external service to be
usable.

### On complexity

**Q: What is the most expensive operation at serve time?**
The correlation matrix, **O(m²n)**. For a 12-holding portfolio over 4,069 days
that is 586,000 multiply-adds — sub-millisecond in BLAS. The m² growth is why
the Risk page correlates only the user's holdings, not all 58 assets.

**Q: Where did complexity actually change a decision?**
Three places. Silhouette is **O(n²·d)** — 1.4 billion operations per candidate
k, nine candidates — so it is computed on a 5,000-point sample, with the reason
in a code comment. Agglomerative clustering is **O(n²) space** — a full
distance matrix would be 760 MB — so it is fitted on a 4,000 subsample,
disclosed in the report. And the sequence array is **O(N·L·F) ≈ 605 MB** in
float32, which is why it is float32 and why inference is chunked at 4,096.

**Q: What is the project's space bottleneck?**
The LSTM/GRU training array: 449,819 sequences × 24 timesteps × 14 features ×
4 bytes ≈ **605 MB**. float64 would be 1.2 GB. float32 is also required by
Apple's MPS backend, which has no float64 support.

**Q: Why is bcrypt slow? Isn't that a problem?**
It is the security property. ~2¹² key derivations, roughly 250 ms, which makes
offline brute-forcing a stolen hash table infeasible. A fast password hash is
a vulnerability.

### On the build itself

**Q: What was the most surprising bug?**
`joblib.dump({"xgboost": model})` saved the **GRU**. The variable `model` had
been reused in the training loop. The reported metrics were unaffected — they
were computed from the correct predictions earlier — but the artifact was
wrong, so serving would have used the wrong model. Renamed to `xgb_model` and
`sequence_model`.

**Q: What did testing miss?**
Three layout bugs that a fully passing suite could not see: a donut legend
crushed to "5", "2", "2", "3"; a goal showing **0% funded** in a list and
**166%** in its own panel beside it; and a simulator label truncated to "LOWER
QUARTI". Every text node existed, so every assertion passed. All three were
obvious in a screenshot. Assertions verify logic; eyes verify layout.

**Q: If you had one more week?**
Fix dormancy detection with a sequence model — the only reported metric that is
genuinely weak at 0.4667 recall. Then per-goal asset earmarking, so each goal
measures against its own assets rather than the whole portfolio.

---

## Appendix — key numbers at a glance

| | |
|---|---|
| Lines of code | ~20,700 (core 3,253 · backend 6,637 · ml 4,682 · frontend 6,098) |
| Tests | **313 Python + 12 Playwright** |
| Commits | 15, one per completed phase |
| Kaggle rows ingested | 5,230,852 equity + 206,696 index |
| Price panel | 4,069 trading days × 58 assets, 2012-01-01 → 2026-11-13 |
| Prices in Postgres | 232,287 |
| Phantom moves found | 78 (full history) / 28 (2012–2021 window, 24 symbols) |
| Sharpe sign flips from adjustment | **15** |
| NIFTY splice correlation | **1.0000** over 3,374 days |
| Synthetic cohort | 10,000 investors · 1,253,505 investor-months |
| Injected anomalies | 3,556 months across 1,200 investors |
| Clustering | k = 7 · silhouette 0.3707 · **ARI 0.9465** · stability 0.9573 |
| Anomaly detection | **PR-AUC 0.9355** vs 0.3255 · F1 0.8392 · FPR 0.00079 |
| Forecast skill (12m, LSTM) | **0.2486** vs the mean-drift baseline |
| Copilot grounding | **458 / 458 numbers (100%)** over 30 questions |
| Health Score components | 6, weights 20/20/15/10/20/15, fully decomposable |
| Monte Carlo | 2,000 paths, seed 42, 5 percentile bands |

---

*WealthOS — academic research prototype. It explains computed portfolio
metrics and does not provide investment advice. Every forecast is a projection
under stated assumptions, not a prediction of returns.*
