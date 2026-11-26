"""SQLAlchemy models.

Importing every model here ensures they are all registered on ``Base.metadata``
before Alembic autogenerates a migration; a model that is never imported is
invisible to it and silently omitted.
"""

from app.db.base import Base
from app.models.alert import Alert
from app.models.asset import Asset, MarketPrice
from app.models.enums import (
    AlertSeverity, AlertType, AssetClass, AssetStatus, GoalStatus, GoalType,
    LinkedAccountStatus, ModelName, RiskTolerance, SyncStatus, TransactionType,
)
from app.models.goal import Goal
from app.models.holding import Holding
from app.models.model_output import ModelOutput
from app.models.linked_account import AccountSyncRun, LinkedAccount
from app.models.snapshot import PortfolioSnapshot
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "Base", "User", "Asset", "MarketPrice", "Holding", "Transaction", "Goal",
    "PortfolioSnapshot", "ModelOutput", "Alert",
    "LinkedAccount", "AccountSyncRun",
    "AssetClass", "AssetStatus", "RiskTolerance", "TransactionType",
    "GoalType", "GoalStatus", "AlertType", "AlertSeverity", "ModelName",
    "LinkedAccountStatus", "SyncStatus",
]
