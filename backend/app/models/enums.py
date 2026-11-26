"""Enumerations shared by the ORM models and the API schemas."""

from __future__ import annotations

from enum import StrEnum


class AssetClass(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    GOLD = "gold"
    DEBT = "debt"
    CASH = "cash"
    INDEX = "index"


class AssetStatus(StrEnum):
    ACTIVE = "active"
    DELISTED = "delisted"


class RiskTolerance(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class TransactionType(StrEnum):
    BUY = "buy"
    SELL = "sell"
    DIVIDEND = "dividend"
    CONTRIBUTION = "contribution"   # cash paid into the portfolio
    WITHDRAWAL = "withdrawal"       # cash taken out


class GoalType(StrEnum):
    RETIREMENT = "retirement"
    HOME = "home"
    EDUCATION = "education"
    TRAVEL = "travel"
    EMERGENCY_FUND = "emergency_fund"
    WEALTH_BUILDING = "wealth_building"
    OTHER = "other"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    ABANDONED = "abandoned"


class AlertSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertType(StrEnum):
    CONCENTRATION = "concentration"
    ANOMALY = "anomaly"
    DRAWDOWN = "drawdown"
    GOAL_OFF_TRACK = "goal_off_track"
    ALLOCATION_DRIFT = "allocation_drift"
    HEALTH_SCORE_DROP = "health_score_drop"


class ModelName(StrEnum):
    INVESTOR_CLUSTER = "investor_cluster"
    ANOMALY_AUTOENCODER = "anomaly_autoencoder"
    FORECAST_BASELINE = "forecast_baseline"
    FORECAST_XGBOOST = "forecast_xgboost"
    FORECAST_LSTM = "forecast_lstm"
    FORECAST_GRU = "forecast_gru"


class LinkedAccountStatus(StrEnum):
    """Lifecycle of a brokerage link.

    `EXPIRED` and `REVOKED` are distinct on purpose: an expired token can be
    refreshed silently, a revoked one requires the user to authorise again,
    and showing the same message for both would send people to re-authorise
    when they did not need to.
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class SyncStatus(StrEnum):
    """Outcome of one synchronisation attempt.

    `PARTIAL` exists because a broker returning half a portfolio is the
    dangerous case: silently treating it as success would delete or
    understate real holdings.
    """

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
