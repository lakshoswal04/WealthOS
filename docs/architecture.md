# Architecture

## The shape of it

```
 Kaggle NSE          Yahoo Finance        Big Sharks
 1996–2021           2000–2026            50 investors
 2,096 symbols       adjusted prices      holding priors
      │                    │                   │
      └──────────┬─────────┴───────────────────┘
                 ▼
     ml/pipelines/  01 ingest → 02 fetch → 03 splice + validate
                    05 priors → 06 simulate → 07 features
                    08 cluster → 09 anomaly → 10 forecast → 11 eval
                 │                              │
                 ▼                              ▼
         PostgreSQL                      ml/models/*.joblib|pt
         58 assets, 232k prices          clustering, autoencoder,
         users, holdings, goals          xgboost, lstm, gru
                 │                              │
                 └──────────────┬───────────────┘
                                ▼
                    FastAPI service layer
         portfolio · risk · health · goals · insights · copilot
                                │
                 ┌──────────────┴──────────────┐
                 ▼                             ▼
        Next.js dashboard              AI Wealth Copilot
        8 pages, Recharts              8 read-only tools
                                       grounding validator
```

The Copilot sits beside the dashboard, not beneath it. It consumes the same
service-layer outputs the pages render, and never reaches the database or
computes a figure of its own.

---

## One definition per formula

`packages/wealthos_core` is a pure library — no database, no web framework,
no model artifacts — imported by **both** the FastAPI services and the
offline training pipelines.

This is the single most load-bearing structural decision in the project. It
means a Sharpe ratio is computed one way at training time and the identical
way at serving time. The common failure it prevents is train/serve skew:
analytics drifting from the numbers a model was fitted on, with nothing in
either codebase looking wrong.

It is also why the formulas are directly unit-testable. 97 tests assert
against values derived by hand or in closed form, with no database or HTTP
layer in the way.

---

## Layers

### `packages/wealthos_core`

Returns, risk (drawdown, downside deviation, VaR/CVaR, beta, alpha),
risk-adjusted ratios, concentration (HHI, effective holdings), portfolio
construction, the health score, goal projection.

Two deliberate departures from the common tutorial versions:

- **Sortino's denominator** averages squared shortfall over *all*
  observations, not only losing ones. The latter inflates the denominator
  for portfolios that rarely lose and makes Sortino incomparable across
  assets.
- **Portfolio returns are time-weighted.** `(V_t − CF_t) / V_{t−1} − 1`.
  Taking a plain percentage change of a portfolio value series treats every
  deposit as investment performance.

### `ml/pipelines`

Eleven numbered stages, each independently re-runnable, each writing
evidence to `ml/reports/`. A stage that detects a data defect raises
`PipelineError` and aborts rather than writing plausible-looking bad data.

### `backend`

FastAPI with Pydantic v2 and SQLAlchemy 2. Services hold the logic;
routers only validate, dispatch and shape responses.

Market prices are cached in memory as a wide DataFrame at startup — about
232,000 rows, small enough to hold. Every analytics request becomes a slice
of an in-process frame rather than a database round trip, which is what
keeps the risk endpoints at ~3ms against the PRD's sub-second target. The
cache is safe to share because market data is reference data: identical for
every user, written only by the pipeline.

### `frontend`

Next.js App Router, client-side rendered against the API with a typed
client. Dark theme, tokenised in CSS custom properties. Chart colours are
the validated categorical palette, checked against this app's exact surface
for colour-vision-deficiency separation and contrast.

---

## Data model

Eleven tables. Three of the original nine were **defined, migrated and never
written to**, which is worth recording because finding them changed what
several later phases needed to build:

| Table | Was | Now |
|---|---|---|
| `alerts` | Dead. Schema already carried `title`, `message`, `metric_value`, `threshold`, a `details` JSONB and an `alert_type` enum listing exactly the six categories the decision-support requirement asks for. | The decision-support engine writes it. Phase 6 implemented a write path rather than designing something new. |
| `model_outputs` | Dead. | Stores each health score, which is what makes `health_score_drop` measurable: comparing today's score to the last one requires having kept the last one. |
| `portfolio_snapshots` | Dead. | **Still dead, deliberately.** Allocation drift was supposed to come from here. It comes from the transaction record instead, with the reconstructed price path as a labelled fallback — both better sources than snapshots nobody writes. Left in place rather than dropped, with this note, so the next person does not rediscover it as an opportunity. |

Two tables were added for account linking: `linked_accounts` and
`account_sync_runs`. Both are described in
[`docs/account-linking.md`](account-linking.md). The access and refresh token
columns are named `*_encrypted` on purpose — a column called `access_token`
invites someone to log it.

`transactions` gained `external_id` with a unique constraint on
`(user_id, external_id)`. That is what makes a repeated broker sync
idempotent, and it has to be the provider's own identifier rather than
`(date, symbol, value)`: two genuine trades in the same stock on the same day
at the same price are two trades, and content matching silently merges them.
The constraint means a bug in the dedupe query becomes an error rather than a
duplicated portfolio.

Two further decisions worth noting:

**Market data has no foreign key to users.** It is reference data shared by
every account. Mixing it with user records is how portfolio systems end up
leaking data between accounts.

**`transactions` carries a check constraint** requiring an asset for
buy/sell/dividend and forbidding one for contribution/withdrawal. External
cash flows are what make the time-weighted return computable; without them
a deposit is indistinguishable from a gain.

`holdings` is unique on `(user_id, asset_id)`, so buying more of an existing
position updates quantity and weighted average cost rather than creating a
second row that would double-count the weight.

---

## Request path

A typical analytics request:

```
GET /api/v1/portfolio/risk
  → auth dependency resolves the user from the JWT
  → risk_service builds the return series from the user's holdings
      · weights from the priced positions
      · price history from the in-memory cache
      · portfolio returns via wealthos_core
  → performance_summary() computes every metric
  → response carries the numbers AND the assumptions that produced them
```

That last line is a convention, not a detail. A Sharpe ratio without its
risk-free rate cannot be reproduced or checked, so every analytics response
carries the rate, the benchmark, the observation count, the window and the
method.

---

## The Copilot

Eight read-only tools over the service layer. The model selects which
measurements to fetch and narrates them; it never computes.

```
question → model picks tools → services compute → structured JSON
         → model narrates → grounding validator → response
```

The validator extracts every numeral from the answer and matches it against
that turn's tool outputs. Unmatched figures are flagged rather than shipped.
This turns "the Copilot is grounded" from an intention into a measurement.

Two execution paths: the Anthropic API when a key is configured, and a
deterministic template explainer over the same tools when none is. The
platform stays fully usable without an external dependency, and any API
failure falls through to the template path rather than returning an error.

---

## Failure behaviour

| Failure | Behaviour |
|---|---|
| Model artifact missing | That endpoint returns `available: false` with a reason; the API still boots and other pages work |
| LLM unreachable or refuses | Falls through to the deterministic explainer |
| Not enough price history | 422 with a specific reason, not an empty chart |
| Malformed CSV | Whole file rejected with per-row reasons; nothing written |
| Unhandled exception | Logged with a trace; the client gets a generic message, since stack traces disclose schema and paths |

---

## Security

- bcrypt password hashing; passwords over the 72-byte limit are rejected
  rather than silently truncated, which would let a prefix authenticate.
- JWTs carry a type claim, so a future refresh token cannot be replayed
  against protected endpoints.
- Login returns one message for both a wrong password and an unknown email,
  so the endpoint cannot enumerate accounts.
- Every portfolio query is scoped by `user_id`; a holding belonging to
  another user returns 404, not 403, so its existence is not confirmed.
- SQLAlchemy throughout — no string-built SQL.
- Secrets come from the environment; `.env` is gitignored.
