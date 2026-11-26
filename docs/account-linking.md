# Account linking

Written for: whoever decides whether to take this from a sandbox to a live
brokerage connection, and whoever has to explain to an examiner why it is a
sandbox today.

## What is built, and what is simulated

The integration layer is real and complete:

| Built | Where |
|---|---|
| OAuth-style authorisation flow (code exchange, no passwords) | `app/services/linking_service.py` |
| Encrypted token storage at rest | `app/core/secrets.py` |
| Token refresh ahead of expiry | `linking_service._usable_token` |
| Holdings and transaction retrieval | `linking_service.sync_account` |
| Manual and scheduled sync triggers | `POST /linked-accounts/{id}/sync?trigger=` |
| Duplicate suppression on re-sync | `Transaction.external_id` + a unique constraint |
| Per-attempt sync history, failures included | `account_sync_runs` |
| Expiry, revocation, rate limits, outages, partial responses, missing scopes | `broker_sandbox` + `sync_account` |

The provider is simulated. `app/services/broker_sandbox.py` generates
holdings and transactions deterministically from the account reference and
contacts nothing. Its authorisation URLs point at `sandbox.invalid`, a
reserved name that cannot resolve.

**Nothing presents a simulated link as a live one.** `is_simulated` is a
column on `linked_accounts`, a field on every API response, and part of a
`simulation_notice` string that travels with the data rather than living only
in the UI. A test asserts the word appears in every linking response.

## Two rules that are not negotiable

**Passwords are never requested or stored.** There is no password column,
no password field in any request model, and `SandboxBroker.exchange_code`
takes a single parameter — an authorisation code. A test reads the live
OpenAPI schema, resolves every schema reachable from a linking request body,
and fails if any field is named `password`, `pin`, `mpin`, `totp`, `secret`,
`credentials` or `otp`. A platform that collects brokerage passwords can
drain an account; careful handling does not make asking for one acceptable.

**Official authentication is never bypassed.** The flow is the provider's
own: the user authorises at the provider, the provider returns a code, the
platform exchanges it for a token. There is no screen-scraping, no session
replay, and no stored login.

## What live access actually requires

None of this is a code change. It is paperwork, money and approval.

### Zerodha (Kite Connect)

- A Kite Connect developer app, created at `developers.kite.trade`, giving an
  `api_key` and `api_secret`.
- **₹500 per month per app**, plus ₹2,000/month if historical data is needed.
- A registered redirect URL. Zerodha will not redirect anywhere else, so the
  deployed callback URL must be registered before it will work.
- A live Zerodha trading account to authorise against.
- Access tokens expire **daily**, around 06:00 IST, and cannot be refreshed
  without the user logging in again. A daily re-authorisation prompt is a
  product constraint, not a bug — any claim of continuous background sync
  against Kite is wrong.
- Rate limits are per-endpoint; holdings is 1 request/second at the time of
  writing.

### Upstox (Upstox API v2)

- An app registered in the Upstox developer console, giving an API key and
  secret, and a registered redirect URI.
- Free tier available at the time of writing, which makes Upstox the cheapest
  path to a real connection.
- Access tokens expire daily at 03:30 IST. Same consequence as Zerodha.
- Scopes are granted per app; holdings and order history are separate
  permissions, and a token without the right scope returns an empty list
  rather than an error — which is exactly the failure the sandbox raises
  `ScopeNotGranted` for, because treating "empty" as "holds nothing" deletes
  a real portfolio.

### Groww

- No public developer programme at the time of writing. Groww's API is
  available to institutional partners under a commercial agreement, not by
  self-service registration.
- So Groww cannot be supported without a business relationship, regardless of
  engineering effort. It is listed as a sandbox provider only.

### Account aggregators (the alternative)

India's Account Aggregator framework (Sahamati / RBI) is the sanctioned route
to multi-broker data without per-broker integration. It requires becoming a
registered Financial Information User, which means an RBI-recognised entity,
a security audit and a technical certification. Out of reach for an academic
project, and worth naming because it is the route a real product would take.

## Known limitations

- **Daily token expiry is the binding constraint.** Both brokers that have
  self-service APIs expire tokens once a day with no silent refresh. The
  refresh path implemented here works against the sandbox and would work for
  the within-day case, but a production system must prompt the user daily.
- **Sync is a full pull, not incremental.** `transactions(since=...)` accepts
  a watermark and the sandbox honours it, but `sync_account` currently passes
  `None`. Correct and cheap at this scale, wasteful at a real one.
- **No webhook or push support.** Sync is pull-only, on manual trigger or a
  caller-supplied schedule. Neither broker offers holdings push.
- **Partial responses are detected but not reconciled.** A partial sync
  updates what it saw and removes nothing, which is the safe behaviour. It
  does not attempt to work out *why* the response was short.
- **CSV import remains first-class** and is deliberately not deprecated. It
  depends on no third party, and for a portfolio someone is willing to type
  out it is strictly more reliable than any API.

## Security notes

- Tokens are encrypted with Fernet (AES-128-CBC with HMAC) before storage.
  The key is derived from `JWT_SECRET_KEY` via PBKDF2-HMAC-SHA256, 200,000
  iterations, with a domain-separation label so the encryption key can never
  equal the signing key.
- The trade-off in sharing one secret is deliberate and worth stating:
  rotating `JWT_SECRET_KEY` invalidates stored tokens as well as sessions.
  A dedicated key would be better practice. One secret was chosen because two
  secrets that must both be set correctly is two chances to deploy with a
  default, and a token encrypted under `insecure-development-key` is not
  encrypted. If this ever becomes a real integration, split them.
- A token that cannot be decrypted raises rather than returning `None`, so a
  key rotation surfaces as "re-authorise this account" instead of being
  mistaken for an unlinked account and silently skipped.
- Disconnecting destroys both tokens and keeps the sync history, so the
  record remains auditable without retaining a usable credential.
- Tokens never appear in an API response. A test asserts that the strings
  `access_token`, `refresh_token`, `sbx_at_` and `sbx_rt_` are absent from the
  accounts listing.
