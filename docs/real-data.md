# Real data: where every figure comes from

WealthOS shows no demo, simulated or modelled market data. Every number on a
page comes from one of the sources below. When a source cannot answer, the page
says why (and, where you can fix it, how) instead of showing a stand-in number.

## Sources

| Data | Source | Needs |
|---|---|---|
| Stock and index prices, candles | **Upstox** (live) for a connected user; otherwise **Yahoo Finance** (about 15 minutes delayed) | Upstox: your own connection. Yahoo: internet access |
| Option chain: premiums, OI, OI change, volume, IV, Greeks | **Upstox** option chain | Upstox connection |
| Option and futures candles, multi-strike OI, OI crossovers | **Upstox** v3 candles (derivative candles carry OI) | Upstox connection |
| Futures prices | **Upstox** quotes for listed futures contracts | Upstox connection |
| Margin for writing options (paper) | **Upstox** margin API, stored on the position at the fill | Upstox connection |
| Expiries, strikes, lot sizes, instrument keys | **Upstox instrument master** (public file, refreshed daily) | Internet access only |
| Holdings sync into Analysis | **Upstox** long-term holdings | Upstox connection |
| Daily history for screeners and backtests | Yahoo daily OHLCV for the NIFTY 100 (`make data`, stage 12) | Internet access |
| Fundamentals (P/E, ROE, market cap, dividend yield, debt/equity) | Yahoo, cached daily | Internet access |
| News, results and dividend dates, dividends, splits | Yahoo | Internet access |
| Commodities | Yahoo: COMEX, NYMEX and ICE futures **in US dollars**. Not MCX | Internet access |
| AI answers and Memory | Gemini (or Claude); without a key, a template explainer over the same tools | `GEMINI_API_KEY` (or `ANTHROPIC_API_KEY`) |
| Analysis prices (portfolio value, risk, health) | Yahoo daily closes chained onto the stored series after every close (`price_refresh`) | Internet access |
| Autopilot, holdings review, amount planning | The swing models on live prices, applied to your risk profile, holdings and avoid lists | Trained models (`make swing`) |

Paper trading uses virtual money (₹10 lakh by default), and every fill is at a
real price from the table above. No order is ever sent to a broker or an
exchange.

The behaviour, anomaly and forecast models were trained and evaluated on a
synthetic investor cohort. That is research, documented on the Model Lab and
Data Quality pages. Applied to your own holdings, the models produce your
Insights. No synthetic investor is ever shown as a user.

## What you need to supply

1. **An Upstox account.** Then create a free **developer app** at
   <https://account.upstox.com/developer/apps> with this redirect URL:

   ```
   http://localhost:8010/api/v1/brokers/upstox/callback
   ```

   When deployed, register the production URL as well and set
   `UPSTOX_REDIRECT_URI` and `FRONTEND_URL` in `.env` to match.
2. **Enter the app's API key and secret** in Settings → Broker APIs, then
   press *Log in with Upstox*. They are encrypted at rest (`app/core/secrets.py`)
   and never shown again.
3. **Log in to Upstox once each trading day.** Upstox access tokens end at
   03:30 IST the next morning and cannot be refreshed (a SEBI-driven rule). An
   expired session is detected and the app asks you to log in again.
4. **An AI key** in `.env` for live, model-written answers (and for Memory to
   shape them): **`GEMINI_API_KEY`** from Google AI Studio
   (`GEMINI_MODEL`, default `gemini-3.6-flash`), or `ANTHROPIC_API_KEY` with
   `LLM_PROVIDER=anthropic`. Without one, the chat uses template answers over
   the same tools.
5. **Internet access from the API server** to Yahoo Finance and
   `assets.upstox.com`.

## Not available

These have no free source and are not shown:

* **IPO data and FII/DII flows.** NSE publishes them, but its site refuses
  automated clients and its terms forbid scraping. A licensed vendor (for
  example TrueData or Global Datafeeds) or NSE data licensing would be needed.
* **MCX commodity prices.** The Commodities page shows international futures
  in US dollars, labelled as such.
* **Real order placement.** Trading is paper only, by design. Live orders
  would need a broker order API, SEBI's retail-algo requirements (including a
  registered static IP for API orders) and careful testing.

## Usage terms

Upstox market data is for the account holder's own use. Each user connects
their own Upstox app, and the API caches broker data per user, so one user's
data is never served to another.

## For developers

* Per-user feed: `backend/app/services/market_data.py` (`feed_for`, `Feed`).
* Upstox client, OAuth and instrument master: `backend/app/integrations/upstox/`.
* Connection flow (credentials, signed single-use OAuth state, holdings sync):
  `backend/app/services/broker_service.py`.
* Missing data surfaces as HTTP 409 `upstox_required` (with an action) or 503
  `market_data_unavailable`. The frontend renders both with `DataUnavailable`.
* Tests replace Yahoo with `tests/fakes.FixtureMarket` and Upstox with
  `tests/fakes.FakeUpstox` (an `httpx.MockTransport`). These are test doubles
  only. `test_no_market_response_is_ever_simulated` asserts that no market
  response contains the word "simulated".
* `scripts/cleanup_test_accounts.py` removes test accounts (`@example.com`,
  `@wealthos-test.com`) and leftover sandbox links. It is a dry run unless you
  pass `--yes`.
