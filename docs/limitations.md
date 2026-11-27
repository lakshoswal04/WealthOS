# Limitations

Written for: anyone deciding how much weight to put on a number this system
reports. Stated plainly, because a result whose limits are hidden is worth
less than a smaller result whose limits are known.

## The data

**All investor-level data is synthetic.** Profiles, holdings, transactions
and goals are generated. Model results are proof-of-concept on simulated
behaviour, not production-validated performance on real investors. Prices
are real.

**Anomaly scores are an upper bound.** Precision and recall are measured
against *injected* anomalies that are deliberately unambiguous. Real
anomalous behaviour is subtler, and performance against it would be worse.

**Cash returns are modelled, not observed**, at a documented 5.5% annual
accrual. Liquid ETFs pin their NAV and pay return as dividends, so no usable
cash price series exists in the sources.

**Equity history is spliced across two sources** on different
corporate-action bases. The method and its validation gates are documented
in `data.md`, but it remains a join rather than a single continuous series.

**The debt series changes instrument in 2021**, from the NIFTY GS Composite
to GILT5YBEES. Correlation over the 57-day overlap is 0.858, not 1.0. This
is a proxy handoff and is labelled as one.

**Big Sharks is institutional, not retail.** Its holding preferences inform
which stocks the synthetic cohort holds; its position sizes do not inform
anything, and should not be read as a retail benchmark.

## The models

**Forecast skill is modest, and that is the honest result.** Portfolio value
at t+h is mostly value at t plus deposits; what remains is market return,
which is hard. Skill rises with horizon, and at one month the model does not
beat a constant forecast — the pipeline recommends the baseline there rather
than present a figure the evidence does not support.

**The evaluation itself is the binding limitation, not the model.** The
forecast features are dominated by market-level variables identical across
investors in a given month, and 47-63% of the target variance is
between-month, so the effective sample is the number of distinct months — 121
train, **18 validation**, 29 test — rather than 675,724 rows. Eighteen months
is one draw of market regimes, and the original `best_iteration = 0` across
every XGBoost configuration was early stopping working correctly against it
rather than an untrained model. Walk-forward folds give several regimes
instead of one; the spread across folds is reported as the error bar, and it
is wide. Any skill figure from 29 test months should be read with that in
mind.

Do not read the 0.97 R² on rupee value as a forecasting result. It measures
scale. The zero-return baseline scores 0.96 on the same metric.

**Dormancy-break detection was weak at 0.467 recall, and the explanation
given here was wrong.** This section used to say a large one-off contribution
genuinely resembles lumpy saving. Measurement said otherwise: in the original
test split, `contribution_ratio` for a dormancy break spanned 0.30 to 0.79
while the maximum across 289,000 normal rows was 0.2006, so the two classes
did not overlap at all. Two separate defects produced the number. The anomaly
score was a flat mean over 24 features of unequal reconstruction difficulty,
which buried a deviation appearing in two of them; and the generator wrote
the large contribution without ever creating the quiet period the label
describes, so the data did not contain the pattern the label named. Recall is
now 0.969. Of that, the scoring fix alone accounts for 0.4667 to 0.5795,
measured on the unchanged model and unchanged data; the rest is the data
correction, which is a correction and not a modelling gain.

**A threshold calibrated on validation does not hold on test.** At a 0.1%
false-alert budget the realised rate on the original test split was 0.475%,
five times the target, and the same threshold transferred cleanly across a
time boundary placed inside validation — so it is drift between the two
periods, not a property of the aggregation. The pipeline measures and reports
this every run (1.5x on the current data). Any deployment should recalibrate
on recent data rather than trust a fixed cut.

**Clustering ARI of 0.947 reflects a cohort we generated.** Real investors
do not fall into six clean archetypes, and the same model on real data would
score far lower. The number demonstrates the method recovers structure that
is present, not that these are the structures of real investing.

**Live users are profiled from a reconstruction where no transaction record
exists.** A user's behavioural history is inferred by valuing today's
holdings back through price history, which holds quantities fixed, so
turnover and trade frequency are biased toward zero and the cluster
assignment toward the passive archetypes.

This is now a fallback rather than the only path. Where the `transactions`
table holds at least six months and four directional trades, those features
are measured from what the user actually did, and the API labels every
behavioural feature `observed`, `reconstructed` or `unavailable` with a
confidence score — the share of the price history the transaction record
covers. Contribution consistency and funding rate are not gated on the trade
count, so a disciplined passive saver keeps their real funding record.

Until Phase 4, nothing wrote to that table except the explicit
`POST /transactions` endpoint. Not holdings creation, and not CSV import —
the documented onboarding route — so in practice it was always empty and the
reconstruction was always used. A CSV row carrying a purchase date now
records a BUY. Rows without a date record nothing, because inventing one
would put a fabricated event in a user's own history.

## The Copilot

**Grounding is measured on the deterministic path** in this build, where it
scores 100% by construction. With a live model the number would be lower and
is the one worth reporting.

**The validator checks numbers, not claims.** A statement with correct
figures and wrong reasoning would pass. It prevents fabricated numbers, not
flawed narrative.

**It does not give advice, by design.** The system prompt forbids
recommending any buy, sell or hold.

## The product

**Goals are not funded by earmarked assets.** The MVP measures every goal
against the whole portfolio, so two goals both read as funded by the same
money. Responses state this.

**Cost basis must be entered in adjusted terms.** Prices here are adjusted
for splits and bonuses; an investor entering the rupee price they actually
paid before such an event will see a misreported gain. The importer detects
the common cases and warns, but cannot correct them automatically, because
the same symptom can mean a mistyped price or a wrong date.

**Risk is measured on current weights held constant over history.** This
answers "how risky is the portfolio I hold now", not "what did I actually
earn". It is not a transaction-accurate replay.

**Market data stops at the last pipeline run.** There is no live price feed.

## Engineering

**Docker configuration is unverified.** Docker was not installed on the
development machine, so the container builds ship untested.

**Load has not been tested.** Concurrency is tested only for correctness —
that two users cannot see each other's data — not for throughput.

**One process holds the price cache in memory.** Several API replicas would
each hold their own copy, which is fine at this size but is not a shared
cache.

## Account linking

**No broker is connected.** The integration layer is complete and tested —
authorisation, encrypted tokens, refresh, sync, duplicate suppression, and
the handling of expiry, revocation, rate limits, outages, partial responses
and missing scopes — against a simulated provider that contacts nothing. What
is missing is an account and an approval, not a design;
[`docs/account-linking.md`](account-linking.md) states exactly what live
access to Zerodha, Upstox or Groww requires.

**Daily token expiry is the binding product constraint, not an
implementation gap.** Both brokers with self-service APIs expire access
tokens once a day with no silent refresh — Zerodha around 06:00 IST, Upstox
at 03:30. Any claim of continuous background sync against them would be
false. A production system has to prompt the user daily.

**Groww cannot be supported without a commercial agreement.** It has no
public developer programme, so no amount of engineering reaches it. It is
listed as a sandbox provider only.

**Sync is a full pull, not incremental.** The sandbox honours a `since`
watermark and the service does not pass one. Correct and cheap at this scale,
wasteful at a real one.

**One secret protects both sessions and tokens.** The Fernet key is derived
from `JWT_SECRET_KEY`, so rotating it invalidates stored broker tokens as
well as logins. A dedicated key would be better practice; one secret was
chosen because two secrets that must both be set correctly is two chances to
deploy with a default, and a token encrypted under
`insecure-development-key` is not encrypted.

## Decision support

**Alerts describe measurements, never trades.** "Your largest holding is 38%
of the portfolio" is a measurement; "reduce it" is investment advice, and this
platform is not licensed to give it. The distinction is enforced rather than
documented: every generated message is scanned for advisory phrasing and
refused if it matches, and a test plants a rule saying "you should sell some
of this position" to prove the gate rejects.

**Every alert message is checked against the measurements that produced it**,
using the same groundedness machinery as the Copilot. A rule that states a
figure the services did not compute is refused, and the refusal is reported
rather than hidden, because a rule that keeps failing verification is a bug
worth seeing.

**Alerts are generated on request, not on a schedule.** There is no
background job and no notification delivery. `POST /alerts/generate` is
called by the client; an alert of the same type raised in the last 24 hours
is not recreated.

**`health_score_drop` needs two measurements to exist.** On a first run there
is nothing to have dropped from, and the rule correctly stays silent rather
than inventing a comparison.
