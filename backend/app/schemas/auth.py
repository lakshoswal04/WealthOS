"""Authentication and user-profile payloads."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import MAX_PASSWORD_BYTES, MIN_PASSWORD_LENGTH
from app.models.enums import RiskTolerance


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH)
    full_name: str | None = Field(default=None, max_length=255)

    # --- optional investor profile, settable at registration ---
    age: int | None = Field(default=None, ge=18, le=100)
    annual_income: float | None = Field(default=None, ge=0)
    monthly_savings: float | None = Field(default=None, ge=0)
    risk_tolerance: RiskTolerance | None = None
    investment_horizon_years: int | None = Field(default=None, gt=0, le=60)

    @field_validator("password")
    @classmethod
    def password_fits_bcrypt(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_PASSWORD_BYTES:
            raise ValueError(
                f"password must be at most {MAX_PASSWORD_BYTES} bytes; bcrypt would "
                "silently truncate anything longer"
            )
        return value


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, max_length=255)
    age: int | None = Field(default=None, ge=18, le=100)
    annual_income: float | None = Field(default=None, ge=0)
    monthly_savings: float | None = Field(default=None, ge=0)
    risk_tolerance: RiskTolerance | None = None
    investment_horizon_years: int | None = Field(default=None, gt=0, le=60)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    full_name: str | None
    age: int | None
    annual_income: float | None
    monthly_savings: float | None
    risk_tolerance: RiskTolerance | None
    investment_horizon_years: int | None
    is_synthetic: bool
    joined_on: date | None
    created_at: datetime
