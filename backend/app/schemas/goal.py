"""Goal payloads."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import GoalStatus, GoalType


class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    goal_type: GoalType
    target_amount: float = Field(gt=0)
    target_date: date
    current_amount: float = Field(default=0.0, ge=0)
    monthly_contribution: float = Field(default=0.0, ge=0)
    priority: int = Field(default=3, ge=1, le=5)

    @field_validator("target_date")
    @classmethod
    def target_must_be_in_the_future(cls, value: date) -> date:
        if value <= date.today():
            raise ValueError("target_date must be in the future")
        return value


class GoalUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    goal_type: GoalType | None = None
    target_amount: float | None = Field(default=None, gt=0)
    target_date: date | None = None
    current_amount: float | None = Field(default=None, ge=0)
    monthly_contribution: float | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=1, le=5)
    status: GoalStatus | None = None


class GoalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    goal_type: GoalType
    target_amount: float
    current_amount: float
    target_date: date
    monthly_contribution: float
    status: GoalStatus
    priority: int
    progress_fraction: float
