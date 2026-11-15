"""System-generated portfolio notifications."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AlertSeverity, AlertType

if TYPE_CHECKING:
    from app.models.user import User


class Alert(Base):
    """A flagged condition in a user's portfolio.

    Alerts describe what was measured and why it was flagged. They never
    recommend a trade: the platform is an analytics tool, not a regulated
    advisory service.
    """

    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    alert_type: Mapped[AlertType] = mapped_column(String(32), nullable=False, index=True)
    severity: Mapped[AlertSeverity] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(String(1024), nullable=False)

    # The measurement behind the alert, so the UI can show the evidence.
    metric_value: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[float | None] = mapped_column(Float)
    details: Mapped[dict | None] = mapped_column(JSONB)

    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    user: Mapped["User"] = relationship(back_populates="alerts")

    __table_args__ = (Index("ix_alerts_user_created", "user_id", "created_at"),)

    def __repr__(self) -> str:
        return f"<Alert {self.alert_type} user={self.user_id} {self.severity}>"
