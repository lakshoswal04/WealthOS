"""The read-only tools the Wealth Copilot may call.

Every tool returns structured JSON computed by the service layer. The model
never calculates a financial figure: it selects which measurements to fetch
and then narrates them. That separation is what makes the Copilot's output
checkable, and it is what the groundedness validator enforces.

All tools are read-only. None can modify a portfolio, place a trade, or
change a goal. The two ``propose_*`` tools validate an order and price it,
then return a *proposal*: placing it takes a separate request from the user
pressing Confirm in the UI. The model has no path to an executed order.
"""

from __future__ import annotations

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.models import User
from app.services import (
    goal_service, health_service, ideas_service, insight_service, live_market_service,
    options_service, paper_trading_service, portfolio_service, risk_service,
    screener_service,
)
from app.services.risk_service import InsufficientHistory


def _signals_unavailable() -> type[Exception]:
    from app.services.signals_service import SignalsUnavailable

    return SignalsUnavailable


def _guarded(call: Callable[[], Any]) -> dict:
    """Run a service call, turning an expected failure into a stated reason.

    A tool that raises would leave the model with nothing to say and invite
    it to invent an answer. A tool that returns an explicit "unavailable"
    gives it something true to report instead.
    """
    try:
        return call()
    except InsufficientHistory as exc:
        return {"available": False, "reason": str(exc)}
    except (paper_trading_service.OrderRejected, screener_service.ScreenError,
            options_service.UnknownUnderlying, options_service.OptionsUnavailable,
            live_market_service.MarketDataUnavailable, ValueError, KeyError) as exc:
        return {"available": False, "reason": str(exc).strip("'\"")}
    except _signals_unavailable() as exc:
        return {"available": False, "reason": str(exc).strip("'\"")}
    except Exception as exc:  # a broken tool must not become a fabricated answer
        return {
            "available": False,
            "reason": f"This measurement could not be computed ({type(exc).__name__}).",
        }


# --------------------------------------------------------------------------
# Tool implementations
# --------------------------------------------------------------------------

def get_portfolio_summary(db: Session, user: User, **_: Any) -> dict:
    summary = portfolio_service.build_summary(db, user)
    return {
        "total_value": round(summary.total_value, 2),
        "total_cost": round(summary.total_cost, 2),
        "unrealized_gain": round(summary.unrealized_gain, 2),
        "unrealized_gain_pct": round(summary.unrealized_gain_pct * 100, 2),
        "n_holdings": summary.n_holdings,
        "n_sectors": summary.n_sectors,
        "as_of": str(summary.as_of) if summary.as_of else None,
        "allocation_by_class": [
            {"label": a.label, "value": round(a.value, 2), "weight_pct": round(a.weight * 100, 2)}
            for a in summary.allocation_by_class
        ],
        "top_holdings": [
            {
                "symbol": h.symbol,
                "market_value": round(h.market_value or 0, 2),
                "weight_pct": round((h.weight or 0) * 100, 2),
                "unrealized_gain_pct": round((h.unrealized_gain_pct or 0) * 100, 2),
            }
            for h in summary.top_holdings[:5]
        ],
    }


def get_risk_metrics(db: Session, user: User, **_: Any) -> dict:
    data = risk_service.risk(db, user)
    summary = data["summary"]
    return {
        "annualized_return_pct": round(summary["annualized_return"] * 100, 2),
        "annualized_volatility_pct": round(summary["annualized_volatility"] * 100, 2),
        "sharpe_ratio": round(summary["sharpe_ratio"], 3),
        "sortino_ratio": round(summary["sortino_ratio"], 3),
        "max_drawdown_pct": round(summary["max_drawdown"] * 100, 2),
        "current_drawdown_pct": round((data["drawdown"]["current_drawdown"] or 0) * 100, 2),
        "beta": round(summary["beta"], 3),
        "value_at_risk_95_pct": round(summary["var_95"] * 100, 2),
        "drawdown_peak_date": data["drawdown"]["peak_date"],
        "drawdown_trough_date": data["drawdown"]["trough_date"],
        "recovered": data["drawdown"]["recovered"],
        "average_pairwise_correlation": (
            round(data["correlation"]["average_pairwise"], 3)
            if data.get("correlation") else None
        ),
        "assumptions": data["assumptions"],
    }


def get_concentration(db: Session, user: User, **_: Any) -> dict:
    data = risk_service.concentration(db, user)
    return {
        "n_holdings": data["n_holdings"],
        "effective_holdings": round(data["effective_holdings"], 2),
        "hhi": round(data["hhi"], 4),
        "top_1_weight_pct": round(data["top_1_weight"] * 100, 2),
        "top_5_weight_pct": round(data["top_5_weight"] * 100, 2),
        "largest_holding": data["largest_holding"],
        "largest_sector": data.get("largest_sector"),
        "max_sector_weight_pct": round((data.get("max_sector_weight") or 0) * 100, 2),
        "sector_weights_pct": {
            k: round(v * 100, 2) for k, v in (data.get("sector_weights") or {}).items()
        },
        "average_pairwise_correlation": data.get("average_pairwise_correlation"),
        "observations": data["interpretation"],
    }


def get_health_score(db: Session, user: User, **_: Any) -> dict:
    data = health_service.health_score(db, user)
    return {
        "total": data["total"],
        "grade": data["grade"],
        "summary": data["summary"],
        "components": [
            {
                "name": c["name"], "score": c["score"],
                "weight": c["weight"], "reason": c["reason"],
            }
            for c in data["components"]
        ],
        "components_not_measured": data["missing_inputs"],
    }


def get_goal_status(db: Session, user: User, **_: Any) -> dict:
    alignment = goal_service.portfolio_goal_alignment(db, user)
    if not alignment["has_goals"]:
        return {"has_goals": False, "reason": "No goals have been set."}
    return {
        "has_goals": True,
        "n_goals": alignment["n_goals"],
        "n_on_track": alignment["n_on_track"],
        "goals": [
            {
                "name": g["name"],
                "target_amount": g["target_amount"],
                "projected_value": g["projected_value"],
                "funding_pct": round(g["funding_ratio"] * 100, 1),
                "shortfall": g["shortfall"],
                "on_track": g["on_track"],
                "months_remaining": g["months_remaining"],
                "monthly_contribution": g["monthly_contribution"],
                "required_monthly_contribution": g["required_monthly_contribution"],
                "target_date": g["target_date"],
            }
            for g in alignment["goals"]
        ],
    }


def get_forecast(db: Session, user: User, horizon_months: int = 12, **_: Any) -> dict:
    return insight_service.wealth_forecast(db, user, int(horizon_months))


def get_investor_profile(db: Session, user: User, **_: Any) -> dict:
    return insight_service.investor_profile(db, user)


def get_anomalies(db: Session, user: User, **_: Any) -> dict:
    return insight_service.detect_anomalies(db, user, limit=12)


# --------------------------------------------------------------------------
# Trading tools
# --------------------------------------------------------------------------

def _feed(db: Session, user: User):
    from app.services.market_data import feed_for
    return feed_for(db, user)


def get_quote(db: Session, user: User, symbol: str = "NIFTY", **_: Any) -> dict:
    if live_market_service.instrument_info(symbol) is None:
        return {"available": False, "reason": f"{symbol} is not in the tradable universe."}
    quote = live_market_service.get_quote(symbol, _feed(db, user))
    if quote is None:
        return {"available": False, "reason": f"No price is available for {symbol.upper()} right now."}
    return quote.to_dict()


def get_market_movers(db: Session, user: User, kind: str = "gainers", **_: Any) -> dict:
    feed = _feed(db, user)
    strip = live_market_service.index_strip(feed)
    stocks = live_market_service.movers(kind, 8, feed)
    if not strip and not stocks:
        return {"available": False, "reason": "No market prices are available right now."}
    return {
        "kind": kind,
        "market": live_market_service.market_status(),
        "indices": [{k: q[k] for k in ("symbol", "ltp", "change", "change_pct", "source")}
                    for q in strip],
        "stocks": [{k: m[k] for k in ("symbol", "name", "sector", "ltp", "change_pct")}
                   for m in stocks],
    }


def get_option_chain_summary(db: Session, user: User, underlying: str = "NIFTY",
                             expiry: str | None = None, **_: Any) -> dict:
    return options_service.summary(_feed(db, user), underlying, expiry)


def run_screener(db: Session, user: User, screen_id: str = "near-52w-high", **_: Any) -> dict:
    result = screener_service.run_screen(db, screen_id, limit=10)
    if not result.get("available"):
        return {"available": False, "reason": result.get("reason")}
    return {
        "screen": {k: result["screen"][k] for k in ("id", "name", "description")},
        "matches": result["count"],
        "universe_size": result["universe_size"],
        "results": result["results"],
    }


def get_ideas(db: Session, user: User, kind: str = "delivery", **_: Any) -> dict:
    return ideas_service.recommendations(db, kind, limit=5, feed=_feed(db, user))


def _risk(user: User) -> str | None:
    rt = getattr(user, "risk_tolerance", None)
    return getattr(rt, "value", rt)


def get_model_signals(db: Session, user: User, symbol: str | None = None, **_: Any) -> dict:
    from app.services import signals_service

    if symbol:
        return signals_service.signal_for(symbol, _risk(user))
    data = signals_service.signals(_risk(user), limit=8)
    for p in data["picks"]:
        p.pop("models", None)
        for d in p["drivers"]:
            d.pop("weight", None)
    return data


def get_market_regime(db: Session, user: User, **_: Any) -> dict:
    from app.services import signals_service

    return signals_service.regime() | {"history": None}


def propose_swing_plan(db: Session, user: User, amount: float = 100_000, **_: Any) -> dict:
    from app.services import advisor_service

    plan = advisor_service.swing_plan(db, user, float(amount))
    plan["requires_confirmation"] = True
    return plan


def review_my_portfolio(db: Session, user: User, **_: Any) -> dict:
    from app.services import autopilot_service

    data = autopilot_service.review_holdings(db, user)
    for h in data.get("holdings", []):
        for d in (h.get("model") or {}).get("drivers", []):
            d.pop("weight", None)
    return data


def plan_allocation(db: Session, user: User, amount: float = 50_000, sectors: list[str] | None = None,
                    horizon: str | None = "swing", **_: Any) -> dict:
    from app.services import autopilot_service

    try:
        return autopilot_service.allocate(db, user, float(amount), sectors or None, horizon or "swing")
    except autopilot_service.AutopilotError as exc:
        return {"available": False, "reason": str(exc)}


def get_autopilot_status(db: Session, user: User, **_: Any) -> dict:
    from app.services import autopilot_service

    data = autopilot_service.status(db, user)
    for r in data.get("runs", []):
        r.pop("target", None)
    return data


def get_paper_portfolio(db: Session, user: User, **_: Any) -> dict:
    data = paper_trading_service.portfolio(db, user)
    data.pop("weekly_activity", None)
    for h in data["holdings"]:
        h.pop("sparkline", None)
    return data


def run_backtest(db: Session, user: User, strategy_id: str = "ema-crossover",
                 symbol: str | None = None, **_: Any) -> dict:
    result = ideas_service.backtest(strategy_id, symbol)
    result.pop("equity_curve", None)
    return result


def propose_paper_order(db: Session, user: User, instrument: str = "equity",
                        symbol: str = "", side: str = "buy", quantity: int | None = None,
                        lots: int | None = None, option_type: str | None = None,
                        strike: float | None = None, expiry: str | None = None,
                        order_type: str = "market", limit_price: float | None = None,
                        **_: Any) -> dict:
    """Validate and price an order. Places nothing."""
    inst = paper_trading_service.resolve(instrument, symbol, option_type, strike, expiry)
    if inst.instrument == "option":
        quantity = (lots or 1) * inst.lot_size if lots or not quantity else quantity
        if quantity % inst.lot_size:
            raise paper_trading_service.OrderRejected(
                f"{inst.underlying} options trade in lots of {inst.lot_size}.")
    if not quantity or quantity <= 0:
        raise paper_trading_service.OrderRejected("A quantity is needed for the order.")
    quote = paper_trading_service.price(inst, _feed(db, user))
    acct = paper_trading_service.account(db, user)
    return {
        "requires_confirmation": True,
        "order": {
            "instrument": inst.instrument, "symbol": inst.underlying if inst.instrument == "option" else inst.symbol,
            "display_symbol": inst.symbol, "side": side, "quantity": int(quantity),
            "lots": int(quantity // inst.lot_size) if inst.instrument == "option" else None,
            "lot_size": inst.lot_size if inst.instrument == "option" else None,
            "option_type": inst.option_type, "strike": inst.strike,
            "expiry": str(inst.expiry) if inst.expiry else None,
            "order_type": order_type, "limit_price": limit_price,
            "product": "nrml" if inst.instrument == "option" else "delivery",
        },
        "ltp": quote["ltp"],
        "estimated_value": round(quote["ltp"] * quantity, 2),
        "cash_available": round(float(acct.cash), 2),
        "price_source": quote["source"],
        "note": "Paper trade. Nothing is placed until the user confirms.",
    }


def propose_autopilot(db: Session, user: User, amount: float = 50_000, **_: Any) -> dict:
    preview = paper_trading_service.autopilot_preview(db, user, float(amount))
    preview["requires_confirmation"] = True
    return preview


# --------------------------------------------------------------------------
# Tool schemas
# --------------------------------------------------------------------------
# strict=True with additionalProperties=False guarantees the arguments the
# model sends validate exactly, so a dispatch never receives a surprise key.

def _schema(name: str, description: str, properties: dict | None = None,
            required: list[str] | None = None) -> dict:
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
            "additionalProperties": False,
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "get_portfolio_summary",
        "Total portfolio value, cost, unrealised gain, allocation by asset class "
        "and the largest holdings. Use for 'what do I own' and 'how much is it worth'.",
    ),
    _schema(
        "get_risk_metrics",
        "Volatility, Sharpe and Sortino ratios, maximum and current drawdown, beta "
        "and Value at Risk, with the assumptions behind them. Use for 'how risky is "
        "my portfolio' and any question about returns relative to risk.",
    ),
    _schema(
        "get_concentration",
        "Concentration by holding, sector and asset class: HHI, effective number of "
        "holdings, largest positions and average pairwise correlation. Use for "
        "'am I diversified' and 'what am I over-exposed to'.",
    ),
    _schema(
        "get_health_score",
        "The Portfolio Health Score out of 100 with all six component scores, their "
        "weights and the reason for each. Use for 'how healthy is my portfolio' and "
        "'why is my score what it is'.",
    ),
    _schema(
        "get_goal_status",
        "Every financial goal with its target, projected value, funding percentage, "
        "shortfall and required monthly contribution. Use for 'am I on track'.",
    ),
    _schema(
        "get_forecast",
        "Projected portfolio value at a horizon, from the trained forecasting models, "
        "with the range across models. Use for 'what will my portfolio be worth'.",
        properties={
            "horizon_months": {
                "type": "integer",
                "enum": [1, 3, 6, 12],
                "description": "Months ahead to project. Defaults to 12.",
            }
        },
        required=["horizon_months"],
    ),
    _schema(
        "get_investor_profile",
        "The behavioural cluster this portfolio resembles and how it differs from "
        "that cluster's average. Use for 'what kind of investor am I'.",
    ),
    _schema(
        "get_anomalies",
        "Months whose portfolio behaviour the anomaly model could not reconstruct, "
        "with the features that drove each flag. Use for 'has anything unusual "
        "happened'.",
    ),
]

def _nullable(kind: str, description: str, **extra: Any) -> dict:
    return {"type": [kind, "null"], "description": description, **extra}


_UNDERLYING = {"type": "string", "enum": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"],
               "description": "Index the options are on."}

TRADING_TOOL_SCHEMAS = [
    _schema(
        "get_quote",
        "The delayed (about 15 minutes) price, day change, open, high and low of a "
        "NIFTY 100 stock or an index (NIFTY, SENSEX, BANKNIFTY, FINNIFTY, MIDCPNIFTY, "
        "INDIAVIX). Use for 'how is X doing' and 'what is X trading at'.",
        properties={"symbol": {"type": "string", "description": "NSE symbol or index key, e.g. RELIANCE, NIFTY."}},
        required=["symbol"],
    ),
    _schema(
        "get_market_movers",
        "Index levels and the day's top gainers, losers or movers among NIFTY 100 "
        "stocks. Use for 'what is moving today' and 'how is the market'.",
        properties={"kind": {"type": "string", "enum": ["gainers", "losers", "movers"]}},
        required=["kind"],
    ),
    _schema(
        "get_option_chain_summary",
        "For an index's option chain: put-call ratio, max pain, support (highest put "
        "OI), resistance (highest call OI), ATM premiums and IV, and the strikes with "
        "the biggest open-interest build-up. All of it is live data from the user's "
        "Upstox session; if that is not connected the tool says so -- relay that.",
        properties={"underlying": _UNDERLYING,
                    "expiry": _nullable("string", "ISO date of a listed expiry; null for the nearest.")},
        required=["underlying", "expiry"],
    ),
    _schema(
        "run_screener",
        "Run a ready-made stock screen over the NIFTY 100 and return the matches.",
        properties={"screen_id": {"type": "string", "enum": [sc.id for sc in screener_service.SCREENS]}},
        required=["screen_id"],
    ),
    _schema(
        "get_ideas",
        "Trade setups with entry, stop-loss and target: rule-based intraday momentum, "
        "delivery (swing) setups, index option strategies, or 'model' for the swing "
        "ensemble's top-ranked stocks. Educational setups, not advice; say so.",
        properties={"kind": {"type": "string", "enum": ["intraday", "delivery", "fno", "model"]}},
        required=["kind"],
    ),
    _schema(
        "get_paper_portfolio",
        "The user's paper-trading account: cash, holdings, open positions, P&L and "
        "today's change. Use for questions about their trades, positions or P&L.",
    ),
    _schema(
        "run_backtest",
        "Backtest a strategy from the library on two years of daily data: total and "
        "annualised return, max drawdown, Sharpe, trades and win rate, against buy and hold.",
        properties={
            "strategy_id": {"type": "string", "enum": [st.id for st in ideas_service.STRATEGIES]},
            "symbol": _nullable("string", "Stock or index to test on; null for the strategy's default."),
        },
        required=["strategy_id", "symbol"],
    ),
    _schema(
        "propose_paper_order",
        "Prepare a paper-trading order for the user to confirm. It validates and prices "
        "the order but places NOTHING; the user must press Confirm. Use only when the "
        "user asks to buy or sell something.",
        properties={
            "instrument": {"type": "string", "enum": ["equity", "option"]},
            "symbol": {"type": "string", "description": "Stock symbol, or the index for options."},
            "side": {"type": "string", "enum": ["buy", "sell"]},
            "quantity": _nullable("integer", "Shares (equity) or units (options)."),
            "lots": _nullable("integer", "Option lots; null for equity."),
            "option_type": _nullable("string", "CE or PE for options; null for equity.", enum=["CE", "PE", None]),
            "strike": _nullable("number", "Option strike; null for equity."),
            "expiry": _nullable("string", "Option expiry ISO date; null for the nearest."),
            "order_type": {"type": "string", "enum": ["market", "limit"]},
            "limit_price": _nullable("number", "Limit price; null for market orders."),
        },
        required=["instrument", "symbol", "side", "quantity", "lots", "option_type",
                  "strike", "expiry", "order_type", "limit_price"],
    ),
    _schema(
        "get_model_signals",
        "The trained swing-trading models' view (10-session horizon). With a symbol: that "
        "stock's rank among the 60 most-traded NIFTY 100 stocks, an 80% range for its next "
        "10 sessions' return, forecast volatility, stop and target for the user's risk "
        "profile, and the features that drove the score. With null: the top-ranked stocks "
        "today, plus the model's out-of-sample record. Always give the range rather than a "
        "point forecast, mention the out-of-sample record, and say it is a research signal, "
        "not advice.",
        properties={"symbol": _nullable("string", "NSE symbol, or null for today's top picks.")},
        required=["symbol"],
    ),
    _schema(
        "get_market_regime",
        "The regime model's reading of the market today (calm, normal or stress) with "
        "probabilities, from NIFTY's return and volatility and India VIX, using data up to "
        "today only. Use for 'is the market risky right now' and 'should I be cautious'.",
    ),
    _schema(
        "propose_swing_plan",
        "Prepare a swing basket from the models for an amount, sized for the user's risk "
        "profile and the current regime: names, quantities, stops, targets and reasons. "
        "Places NOTHING; the user must confirm. Use for 'build me a swing portfolio with X' "
        "or 'how should I invest X for the next two weeks'.",
        properties={"amount": {"type": "number", "description": "Rupees to plan for (at least 10,000)."}},
        required=["amount"],
    ),
    _schema(
        "review_my_portfolio",
        "Review the user's REAL holdings (imported CSV or Upstox sync) against the trained models: each "
        "holding's weight, sector, risk contribution and model rank with its 10-session range; sector "
        "concentration; and suggestions with reasons. Use for 'review my portfolio', 'what should I do with "
        "my holdings', 'which of my stocks look weak'. If it reports no holdings, tell the user to import them.",
    ),
    _schema(
        "plan_allocation",
        "Plan how to split an amount of money using live prices and the models: per-sector stock picks with "
        "whole-share quantities, ranges, stops and targets for the user's risk profile. horizon 'swing' (about "
        "two weeks) uses the swing models; 'long_term' adds a core of index, gold and bond ETFs. Use for 'how "
        "can I invest 50000 in different sectors', 'where should I put 1 lakh', 'invest 2 lakh for the long "
        "term'. Places nothing.",
        properties={
            "amount": {"type": "number", "description": "Rupees to plan for."},
            "sectors": _nullable("array", "Sectors the user named (e.g. banking, IT, pharma); null to let the "
                                          "models choose.", items={"type": "string"}),
            "horizon": {"type": "string", "enum": ["swing", "long_term"]},
        },
        required=["amount", "sectors", "horizon"],
    ),
    _schema(
        "get_autopilot_status",
        "The user's Autopilot: whether it is on, its budget, what its paper sleeve holds, its P&L, when it "
        "next rebalances, and its recent runs with the orders and reasons. Use for 'what is autopilot doing', "
        "'how is my autopilot performing'.",
    ),
    _schema(
        "propose_autopilot",
        "Prepare Autopilot's first paper basket for an amount: the swing models' picks sized for the "
        "user's risk profile and the regime. Places nothing; once the user confirms, Autopilot buys it and "
        "rebalances it on its own every few sessions. Use for 'invest X in autopilot'.",
        properties={"amount": {"type": "number", "description": "Rupees to deploy."}},
        required=["amount"],
    ),
]

PORTFOLIO_TOOL_NAMES = [t["name"] for t in TOOL_SCHEMAS]
TOOL_SCHEMAS = TOOL_SCHEMAS + TRADING_TOOL_SCHEMAS

TOOL_FUNCTIONS: dict[str, Callable] = {
    "get_portfolio_summary": get_portfolio_summary,
    "get_risk_metrics": get_risk_metrics,
    "get_concentration": get_concentration,
    "get_health_score": get_health_score,
    "get_goal_status": get_goal_status,
    "get_forecast": get_forecast,
    "get_investor_profile": get_investor_profile,
    "get_anomalies": get_anomalies,
    "get_quote": get_quote,
    "get_market_movers": get_market_movers,
    "get_option_chain_summary": get_option_chain_summary,
    "run_screener": run_screener,
    "get_ideas": get_ideas,
    "get_paper_portfolio": get_paper_portfolio,
    "run_backtest": run_backtest,
    "propose_paper_order": propose_paper_order,
    "propose_autopilot": propose_autopilot,
    "get_model_signals": get_model_signals,
    "review_my_portfolio": review_my_portfolio,
    "plan_allocation": plan_allocation,
    "get_autopilot_status": get_autopilot_status,
    "get_market_regime": get_market_regime,
    "propose_swing_plan": propose_swing_plan,
}


def run_tool(name: str, db: Session, user: User, arguments: dict) -> dict:
    """Dispatch one tool call."""
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"error": f"Unknown tool: {name}"}
    return _guarded(lambda: function(db, user, **(arguments or {})))
