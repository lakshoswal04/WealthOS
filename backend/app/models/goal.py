"""Financial goals and their progress."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin
from app.models.enums import GoalStatus, GoalType

if TYPE_CHECKING:
    from app.models.user import User


class Goal(Base, TimestampMixin):
    """A target amount by a target date, with a planned monthly contribution."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    goal_type: Mapped[GoalType] = mapped_column(String(32), nullable=False)
    target_amount: Mapped[float] = mapped_column(Float, nullable=False)
    current_amount: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    monthly_contribution: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    status: Mapped[GoalStatus] = mapped_column(
        String(20), default=GoalStatus.ACTIVE, nullable=False
    )
    priority: Mapped[int] = mapped_column(default=3, nullable=False)

    user: Mapped["User"] = relationship(back_populates="goals")

    __table_args__ = (
        Index("ix_goals_user_status", "user_id", "status"),
        CheckConstraint("target_amount > 0", name="target_positive"),
        CheckConstraint("current_amount >= 0", name="current_non_negative"),
        CheckConstraint("monthly_contribution >= 0", name="contribution_non_negative"),
        CheckConstraint("priority BETWEEN 1 AND 5", name="priority_range"),
    )

    @property
    def progress_fraction(self) -> float:
        if self.target_amount <= 0:
            return 0.0
        return min(float(self.current_amount) / float(self.target_amount), 1.0)

    def __repr__(self) -> str:
        return f"<Goal {self.name} {self.current_amount}/{self.target_amount}>"
