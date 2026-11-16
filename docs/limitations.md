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

**Forecast skill is modest, and that is the honest result.** The best model
achieves 0.249 skill over a mean-drift baseline at twelve months. At three
months essentially nothing beats the baseline. Portfolio value at t+h is
mostly value at t plus deposits; what remains is market return, which is
hard.

Do not read the 0.97 R² on rupee value as a forecasting result. It measures
scale. The zero-return baseline scores 0.96 on the same metric.

**Dormancy-break detection is weak** at 0.467 recall. A large one-off
contribution genuinely resembles lumpy saving.

**Clustering ARI of 0.947 reflects a cohort we generated.** Real investors
do not fall into six clean archetypes, and the same model on real data would
score far lower. The number demonstrates the method recovers structure that
is present, not that these are the structures of real investing.

**Live users are profiled from a reconstruction.** A real user's behavioural
history is inferred by valuing today's holdings back through price history,
not by replaying what they actually held. Turnover and trade frequency are
therefore near zero for an imported portfolio, which biases the cluster
assignment toward passive groups. The API reports a match confidence and
states the caveat.

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
