"""Goals and the Portfolio Health Score."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.models import Goal
from app.schemas.goal import GoalCreate, GoalOut, GoalUpdate
from app.services import goal_service, health_service

router = APIRouter(tags=["goals"])


def _owned_goal(db, user, goal_id: int) -> Goal:
    """Fetch a goal, scoped to its owner."""
    goal = db.scalar(select(Goal).where(Goal.id == goal_id, Goal.user_id == user.id))
    if goal is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Goal not found")
    return goal


@router.get("/goals", response_model=list[GoalOut])
def list_goals(user: CurrentUser, db: DbSession) -> list[Goal]:
    return goal_service.list_goals(db, user)


@router.post("/goals", response_model=GoalOut, status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalCreate, user: CurrentUser, db: DbSession) -> Goal:
    goal = Goal(user_id=user.id, **payload.model_dump())
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return goal


@router.get("/goals/{goal_id}", response_model=GoalOut)
def get_goal(goal_id: int, user: CurrentUser, db: DbSession) -> Goal:
    return _owned_goal(db, user, goal_id)


@router.patch("/goals/{goal_id}", response_model=GoalOut)
def update_goal(goal_id: int, payload: GoalUpdate, user: CurrentUser, db: DbSession) -> Goal:
    goal = _owned_goal(db, user, goal_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(goal, field, value)
    db.commit()
    db.refresh(goal)
    return goal


@router.delete("/goals/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(goal_id: int, user: CurrentUser, db: DbSession) -> None:
    db.delete(_owned_goal(db, user, goal_id))
    db.commit()


@router.get("/goals/{goal_id}/forecast")
def forecast_goal(goal_id: int, user: CurrentUser, db: DbSession) -> dict:
    """Project one goal forward under explicitly stated assumptions.

    Returns a pessimistic/expected/optimistic band rather than a single
    figure, so the projection cannot be read as a promised outcome.
    """
    return goal_service.forecast_goal(db, user, _owned_goal(db, user, goal_id))


class SimulationRequest(BaseModel):
    """Optional overrides for the scenario simulator.

    Anything left unset falls back to the user's actual position, so the
    simulator opens on reality rather than on invented defaults.
    """

    monthly_contribution: float | None = Field(default=None, ge=0, le=10_000_000)
    annual_return: float | None = Field(default=None, ge=-0.10, le=0.30)
    annual_volatility: float | None = Field(default=None, ge=0.0, le=0.60)
    months: int | None = Field(default=None, ge=1, le=600)


@router.post("/goals/{goal_id}/simulate")
def simulate_goal(
    goal_id: int, payload: SimulationRequest, user: CurrentUser, db: DbSession
) -> dict:
    """Project a goal under assumptions the user chooses, with a range.

    Returns the deterministic path, a Monte Carlo fan of percentile bands,
    and the probability of reaching the target. The fan matters more than the
    line: a single projection implies a precision that does not exist.
    """
    return goal_service.simulate_goal(
        db, user, _owned_goal(db, user, goal_id), **payload.model_dump()
    )


@router.get("/health-score")
def get_health_score(
    user: CurrentUser,
    db: DbSession,
    sensitivity: bool = Query(
        default=False,
        description="Include a sensitivity analysis showing how much each input moves the score",
    ),
) -> dict:
    """The decomposable Portfolio Health Score, with every component shown."""
    return health_service.health_score(db, user, include_sensitivity=sensitivity)
