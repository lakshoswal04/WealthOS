"""Test fixtures.

Tests run against a dedicated ``wealthos_test`` database so a test run can
never touch development data. Each test gets a clean schema and its own
client.
"""

from __future__ import annotations

import math
import os
from datetime import date, timedelta

import pandas as pd
import pytest

# Point the application at the test database before any app module is
# imported, since settings are read once at import time.
os.environ["DATABASE_URL"] = "postgresql+psycopg://localhost:5432/wealthos_test"
os.environ["JWT_SECRET_KEY"] = "test-only-secret-not-used-anywhere-else"

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.db.base import Base  # noqa: E402
from app.db.session import get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Asset, MarketPrice  # noqa: E402
from app.services.market_service import market_cache  # noqa: E402

TEST_DATABASE_URL = os.environ["DATABASE_URL"]
engine = create_engine(TEST_DATABASE_URL, poolclass=None)
TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


@pytest.fixture(scope="function")
def db():
    """A clean schema per test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    market_cache.invalidate()
    session = TestSession()
    try:
        yield session
    finally:
        session.close()
        market_cache.invalidate()


@pytest.fixture(scope="function")
def seeded_db(db):
    """A schema populated with a small, fully deterministic market.

    Prices are generated rather than sampled from the real panel so that
    expected values in assertions can be derived by hand.
    """
    assets = [
        Asset(symbol="RELIANCE", name="Reliance Industries", asset_class="equity", sector="Energy"),
        Asset(symbol="TCS", name="Tata Consultancy Services", asset_class="equity", sector="IT"),
        Asset(symbol="INFY", name="Infosys", asset_class="equity", sector="IT"),
        Asset(symbol="GOLDBEES", name="Gold BeES", asset_class="gold", sector="Commodities"),
        Asset(symbol="DEBT", name="Government Securities", asset_class="debt", sector="Sovereign Debt"),
        Asset(symbol="NIFTY50", name="NIFTY 50", asset_class="index", sector="Benchmark"),
        Asset(symbol="OLDCO", name="Delisted Company", asset_class="equity",
              sector="Energy", status="delisted"),
    ]
    db.add_all(assets)
    db.commit()

    # 500 business days ending today. Each asset grows at a fixed daily rate
    # with a deterministic sinusoidal wobble, so every statistic is exactly
    # reproducible across runs.
    #
    # Each asset gets its own period, phase and amplitude. Giving them all
    # the same wobble would make them perfectly correlated, which would erase
    # the diversification effect the risk tests exist to verify.
    dates = pd.bdate_range(end=date.today(), periods=500)
    profiles = {
        # symbol:      (start,   daily drift, wobble period, phase, amplitude)
        "RELIANCE": (1000.0,  0.00040, 23.0, 0.0, 0.020),
        "TCS":      (3000.0,  0.00030, 31.0, 1.1, 0.018),
        "INFY":     (1400.0,  0.00020, 17.0, 2.3, 0.022),
        "GOLDBEES": (  50.0,  0.00030, 41.0, 3.7, 0.015),
        "DEBT":     (  50.0,  0.00020, 59.0, 0.6, 0.003),
        "NIFTY50":  (18000.0, 0.00035, 27.0, 0.4, 0.016),
        "OLDCO":    ( 100.0,  0.00010, 13.0, 2.9, 0.025),
    }
    rows = []
    ids = {a.symbol: a.id for a in db.query(Asset).all()}
    for symbol, (start_price, drift, period, phase, amplitude) in profiles.items():
        for i, when in enumerate(dates):
            wobble = 1.0 + amplitude * math.sin(2 * math.pi * i / period + phase)
            rows.append({
                "asset_id": ids[symbol],
                "date": when.date(),
                "close": start_price * ((1 + drift) ** i) * wobble,
            })
    db.bulk_insert_mappings(MarketPrice, rows)
    db.commit()
    market_cache.invalidate()
    return db


@pytest.fixture(scope="function")
def client(seeded_db):
    """A TestClient wired to the test database."""
    def override_get_db():
        try:
            yield seeded_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def registered_user(client):
    """A registered account and its auth header."""
    response = client.post("/api/v1/auth/register", json={
        "email": "investor@example.com",
        "password": "a-strong-test-password",
        "full_name": "Test Investor",
        "age": 35,
        "annual_income": 1_500_000,
        "monthly_savings": 40_000,
        "risk_tolerance": "moderate",
        "investment_horizon_years": 20,
    })
    assert response.status_code == 201, response.text
    token = response.json()["access_token"]
    return {"headers": {"Authorization": f"Bearer {token}"}, "token": token}


@pytest.fixture
def second_user(client):
    """A second account, used to prove data cannot cross between users."""
    response = client.post("/api/v1/auth/register", json={
        "email": "other@example.com", "password": "another-strong-password",
    })
    assert response.status_code == 201, response.text
    return {"headers": {"Authorization": f"Bearer {response.json()['access_token']}"}}


@pytest.fixture
def auth(registered_user):
    return registered_user["headers"]
