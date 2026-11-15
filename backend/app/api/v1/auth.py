"""Registration, login and profile endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models import User
from app.schemas.auth import Token, UserLogin, UserOut, UserProfileUpdate, UserRegister

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserRegister, db: DbSession) -> Token:
    """Create an account and return an access token."""
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    user = User(
        email=payload.email.lower(),
        hashed_password=hash_password(payload.password),
        full_name=payload.full_name,
        age=payload.age,
        annual_income=payload.annual_income,
        monthly_savings=payload.monthly_savings,
        risk_tolerance=payload.risk_tolerance,
        investment_horizon_years=payload.investment_horizon_years,
        joined_on=date.today(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return Token(
        access_token=create_access_token(user.id),
        expires_in_minutes=settings.access_token_expire_minutes,
    )


@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: DbSession) -> Token:
    """Exchange email and password for an access token."""
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    # One message for both "no such account" and "wrong password", so the
    # endpoint cannot be used to discover which emails are registered.
    if user is None or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled"
        )

    return Token(
        access_token=create_access_token(user.id),
        expires_in_minutes=settings.access_token_expire_minutes,
    )


@router.get("/me", response_model=UserOut)
def read_profile(user: CurrentUser) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_profile(payload: UserProfileUpdate, user: CurrentUser, db: DbSession) -> User:
    """Update the investor profile that drives personalised analysis."""
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    db.commit()
    db.refresh(user)
    return user
