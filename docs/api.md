# API reference

Base URL `http://localhost:8010`, prefix `/api/v1`. Interactive docs at `/docs`.

All endpoints except `/health`, `/api/v1/auth/*`, `/api/v1/portfolio/assets`,
`/api/v1/models/status` and `/api/v1/copilot/capabilities` require
`Authorization: Bearer <token>`.

## analytics

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/portfolio/analytics` | Returns, risk-adjusted ratios and trailing performance by window. |
| `GET` | `/api/v1/portfolio/concentration` | Concentration by asset, sector and asset class, with plain-language notes. |
| `GET` | `/api/v1/portfolio/risk` | Volatility, drawdown, tail risk, beta and the correlation matrix. |

## auth

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/v1/auth/login` | Exchange email and password for an access token. |
| `GET` | `/api/v1/auth/me` |  |
| `PATCH` | `/api/v1/auth/me` | Update the investor profile that drives personalised analysis. |
| `POST` | `/api/v1/auth/register` | Create an account and return an access token. |

## copilot

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/copilot/capabilities` | What the Copilot can do and how it is currently running. |
| `POST` | `/api/v1/copilot/chat` | Ask a question about this portfolio. |

## goals

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/goals` |  |
| `POST` | `/api/v1/goals` |  |
| `GET` | `/api/v1/goals/{goal_id}` |  |
| `PATCH` | `/api/v1/goals/{goal_id}` |  |
| `DELETE` | `/api/v1/goals/{goal_id}` |  |
| `GET` | `/api/v1/goals/{goal_id}/forecast` | Project one goal forward under explicitly stated assumptions. |
| `GET` | `/api/v1/health-score` | The decomposable Portfolio Health Score, with every component shown. |

## insights

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/v1/anomalies` | Months whose portfolio behaviour the autoencoder could not reconstruct. |
| `GET` | `/api/v1/forecast` | Projected portfolio value, from the trained forecasting models. |
| `GET` | `/api/v1/investor-profile` | Which behavioural cluster this investor's portfolio resembles. |
| `GET` | `/api/v1/models/status` | Which model artifacts loaded, for diagnostics and the health page. |

## portfolio

| Method | Path | Purpose |
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

## system

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness and dependency check. |

---

## Conventions

**Assumptions travel with numbers.** Every analytics response carries the
risk-free rate, benchmark, observation count, window and method that
produced its figures. A Sharpe ratio without its risk-free rate cannot be
reproduced.

**Model endpoints degrade rather than fail.** When an artifact is missing
or a portfolio has too little history, the endpoint returns `200` with
`available: false` and a `reason`, so one panel goes quiet instead of the
page breaking.

**Errors.**

| Status | Meaning |
|---|---|
| `401` | Missing, malformed or expired token |
| `404` | Not found, *or* belongs to another user — the two are not distinguished |
| `409` | Email already registered |
| `413` | Upload over 2 MB |
| `422` | Validation failed, or not enough history to compute |
| `500` | Logged server-side with a trace; the client gets a generic message |

## Example

```bash
API=http://localhost:8010/api/v1

TOKEN=$(curl -s -X POST $API/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"email":"you@example.com","password":"a-strong-password",
       "age":32,"risk_tolerance":"moderate","monthly_savings":45000}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["access_token"])')

curl -s -X POST "$API/portfolio/import" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@docs/sample-holdings.csv"

curl -s "$API/portfolio/risk"  -H "Authorization: Bearer $TOKEN"
curl -s "$API/health-score"    -H "Authorization: Bearer $TOKEN"

curl -s -X POST "$API/copilot/chat" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"Why is my portfolio risky?"}'
```
