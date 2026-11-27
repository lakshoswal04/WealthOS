# API reference

Generated from the live route table by `python -m scripts.generate_api_docs`. Do not edit by hand: the previous version was written from a route listing and had drifted, missing twelve endpoints and leaving several without a description.

Base URL `http://localhost:8010`, prefix `/api/v1`. Interactive docs at `/docs`.

**45 endpoints**, of which 11 are public. Every other endpoint requires `Authorization: Bearer <token>` and is scoped to the signed-in user; `backend/tests/test_route_isolation.py` enumerates this same route table and asserts both properties, so this list cannot drift from what is enforced.

## Public endpoints

Each is public for a stated reason, because "it was already public" is how an endpoint quietly stops being protected.

| Path | Why it needs no token |
|---|---|
| `/` | service metadata |
| `/api/v1/auth/login` | signing in cannot require being signed in |
| `/api/v1/auth/register` | creating an account cannot require one |
| `/api/v1/copilot/capabilities` | which mode the Copilot is running in and which tools it has; service metadata, no user data |
| `/api/v1/linked-accounts/providers` | static provider list and scopes |
| `/api/v1/market/assets` | the tradable universe, identical for everyone |
| `/api/v1/models/status` | which artifacts loaded; no user data |
| `/api/v1/portfolio/assets` | the tradable universe, identical for everyone |
| `/api/v1/research/reports` | published training evidence, no user data |
| `/api/v1/research/reports/{name}` | published training evidence |
| `/health` | liveness probe, used by Render |

## account linking

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/linked-accounts` | Linked accounts, with the last time each one actually synced. |
| `POST` | `/api/v1/linked-accounts` | Exchange the authorisation code and store the link. |
| `GET` | `/api/v1/linked-accounts/providers` | The simulated providers, and what live access would require. |
| `POST` | `/api/v1/linked-accounts/start` | Begin authorisation. Returns a URL; nothing is contacted. |
| `DELETE` | `/api/v1/linked-accounts/{account_id}` | Unlink an account and destroy its stored tokens. |
| `POST` | `/api/v1/linked-accounts/{account_id}/sync` | Pull holdings and transactions now. |
| `GET` | `/api/v1/linked-accounts/{account_id}/syncs` | Every sync attempt for this account, successes and failures alike. |

## alerts

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/alerts` | Alerts for the signed-in user, newest first. |
| `POST` | `/api/v1/alerts/generate` | Run every rule against the current portfolio and store what it finds. |
| `DELETE` | `/api/v1/alerts/{alert_id}` | Dismiss one alert permanently. |
| `POST` | `/api/v1/alerts/{alert_id}/read` | Mark one alert as read. |

## analytics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/portfolio/analytics` | Returns, risk-adjusted ratios and trailing performance by window. |
| `GET` | `/api/v1/portfolio/concentration` | Concentration by asset, sector and asset class, with plain-language notes. |
| `GET` | `/api/v1/portfolio/risk` | Volatility, drawdown, tail risk, beta and the correlation matrix. |

## auth

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Exchange email and password for an access token. |
| `GET` | `/api/v1/auth/me` |  |
| `PATCH` | `/api/v1/auth/me` | Update the investor profile that drives personalised analysis. |
| `POST` | `/api/v1/auth/register` | Create an account and return an access token. |

## copilot

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/copilot/capabilities` | What the Copilot can do and how it is currently running. |
| `POST` | `/api/v1/copilot/chat` | Ask a question about this portfolio. |

## goals

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/goals` |  |
| `POST` | `/api/v1/goals` |  |
| `GET` | `/api/v1/goals/{goal_id}` |  |
| `PATCH` | `/api/v1/goals/{goal_id}` |  |
| `DELETE` | `/api/v1/goals/{goal_id}` |  |
| `GET` | `/api/v1/goals/{goal_id}/forecast` | Project one goal forward under explicitly stated assumptions. |
| `POST` | `/api/v1/goals/{goal_id}/simulate` | Project a goal under assumptions the user chooses, with a range. |
| `GET` | `/api/v1/health-score` | The decomposable Portfolio Health Score, with every component shown. |

## insights

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/anomalies` | Months whose portfolio behaviour the autoencoder could not reconstruct. |
| `GET` | `/api/v1/forecast` | Projected portfolio value, from the trained forecasting models. |
| `GET` | `/api/v1/investor-profile` | Which behavioural cluster this investor's portfolio resembles. |
| `GET` | `/api/v1/models/status` | Which model artifacts loaded, for diagnostics and the health page. |

## portfolio

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/portfolio` | Total value, gain and allocation breakdowns for the Overview page. |
| `GET` | `/api/v1/portfolio/assets` | The investable universe, for symbol pickers and import validation. |
| `GET` | `/api/v1/portfolio/holdings` | Every holding, priced, with its unrealised gain and portfolio weight. |
| `POST` | `/api/v1/portfolio/holdings` | Add a position, merging into an existing one for the same asset. |
| `PATCH` | `/api/v1/portfolio/holdings/{holding_id}` |  |
| `DELETE` | `/api/v1/portfolio/holdings/{holding_id}` |  |
| `POST` | `/api/v1/portfolio/import` | Import holdings from a CSV. |
| `GET` | `/api/v1/portfolio/transactions` |  |
| `POST` | `/api/v1/portfolio/transactions` | Record a trade or an external cash flow. |

## research

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/research/reports` | Every training and data-quality report, grouped by page. |
| `POST` | `/api/v1/research/reports/refresh` | Drop the cache, so a re-run of the pipelines is picked up. |
| `GET` | `/api/v1/research/reports/{name}` | A single report by name. |

## system

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness and dependency check. |
