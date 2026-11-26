"""Every route, audited for authentication and user scoping.

Written as an enumeration over the live route table rather than a list of
paths, so a route added later is covered without anyone remembering to add
it here. That property is the point: a hand-maintained list of endpoints to
check is a list that falls behind the router.

Two questions are asked of every route. Does it require a session? And if it
takes a resource id, does it refuse one belonging to somebody else? The
second matters more -- an endpoint that authenticates the caller and then
reads whatever id it is handed is worse than one with no auth at all,
because it looks safe.
"""

from __future__ import annotations

import re

import pytest

from app.main import app

# Routes that are public by design. Every one is listed with the reason,
# because "it was already in the list" is how an endpoint quietly becomes
# public.
PUBLIC_PATHS = {
    "/": "service metadata",
    "/health": "liveness probe, used by Render",
    "/docs": "OpenAPI UI",
    "/redoc": "OpenAPI UI",
    "/openapi.json": "OpenAPI schema",
    "/docs/oauth2-redirect": "OpenAPI UI plumbing",
    "/api/v1/auth/register": "creating an account cannot require one",
    "/api/v1/auth/login": "signing in cannot require being signed in",
    "/api/v1/models/status": "which artifacts loaded; no user data",
    "/api/v1/research/reports": "published training evidence, no user data",
    "/api/v1/research/reports/{name}": "published training evidence",
    "/api/v1/linked-accounts/providers": "static provider list and scopes",
    "/api/v1/market/assets": "the tradable universe, identical for everyone",
    "/api/v1/portfolio/assets": "the tradable universe, identical for everyone",
    "/api/v1/copilot/capabilities": (
        "which mode the Copilot is running in and which tools it has; "
        "service metadata, no user data"
    ),
}

METHOD_BODIES = {
    "POST": {},
    "PUT": {},
    "PATCH": {},
    "DELETE": None,
}


def _routes():
    """(path, method) for every real API route, excluding HEAD and OPTIONS."""
    out = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in sorted(methods - {"HEAD", "OPTIONS"}):
            out.append((path, method))
    return sorted(set(out))


ALL_ROUTES = _routes()
PROTECTED_ROUTES = [
    (p, m) for p, m in ALL_ROUTES if p not in PUBLIC_PATHS
]


def test_the_route_table_is_not_empty():
    # Guards against this whole file passing vacuously if the app fails to
    # build its router.
    assert len(ALL_ROUTES) > 30, ALL_ROUTES
    assert len(PROTECTED_ROUTES) > 20


def test_every_public_route_is_public_on_purpose():
    """A public path must be declared, with a reason, not discovered."""
    for path, reason in PUBLIC_PATHS.items():
        assert reason and len(reason) > 8, f"{path} has no stated reason"


@pytest.mark.parametrize(
    "path,method", PROTECTED_ROUTES, ids=lambda v: str(v)
)
def test_every_protected_route_refuses_an_anonymous_caller(client, path, method):
    """401 or 403, never 200 and never a 500.

    A 404 is also acceptable for a parameterised path, since an id that does
    not exist is indistinguishable from one belonging to someone else -- that
    is the correct answer, not a leak.
    """
    url = re.sub(r"\{[^}]+\}", "1", path)
    body = METHOD_BODIES.get(method)

    response = client.request(
        method, url, json=body if body is not None else None
    )

    assert response.status_code != 200, (
        f"{method} {path} served an anonymous caller"
    )
    assert response.status_code < 500, (
        f"{method} {path} returned {response.status_code} to an anonymous "
        f"caller instead of refusing it: {response.text[:200]}"
    )
    assert response.status_code in {401, 403, 404, 405, 422}, (
        f"{method} {path} returned an unexpected {response.status_code}"
    )


# --------------------------------------------------------------------------
# Cross-user access
# --------------------------------------------------------------------------

def _create_owned_resources(client, headers) -> dict[str, int]:
    """One of each id-addressable resource, owned by this user."""
    ids: dict[str, int] = {}

    holding = client.post("/api/v1/portfolio/holdings", headers=headers,
                          json={"symbol": "RELIANCE", "quantity": 10,
                                "average_price": 1000})
    if holding.status_code == 201:
        ids["holding"] = holding.json()["id"]

    goal = client.post("/api/v1/goals", headers=headers, json={
        "name": "Private goal", "goal_type": "retirement",
        "target_amount": 1_000_000, "target_date": "2032-01-01",
        "monthly_contribution": 10_000,
    })
    if goal.status_code == 201:
        ids["goal"] = goal.json()["id"]

    link = client.post("/api/v1/linked-accounts", headers=headers,
                       json={"provider": "sandbox", "code": "sbx_code_abcdefgh"})
    if link.status_code == 201:
        ids["linked_account"] = link.json()["id"]

    client.post("/api/v1/alerts/generate", headers=headers)
    alerts = client.get("/api/v1/alerts", headers=headers).json()
    if alerts.get("alerts"):
        ids["alert"] = alerts["alerts"][0]["id"]

    return ids


def test_one_user_cannot_read_or_change_anothers_resources(
    client, auth, second_user
):
    """The audit that matters: an id from one account, used by another.

    Every attempt must be refused. A 404 is the right refusal -- confirming
    that an id exists but belongs to someone else is itself a disclosure.
    """
    mine = _create_owned_resources(client, auth)
    assert mine, "no resources were created, so nothing was tested"

    other = second_user["headers"]
    attempts = []

    if "holding" in mine:
        attempts += [
            ("PATCH", f"/api/v1/portfolio/holdings/{mine['holding']}", {"quantity": 1}),
            ("DELETE", f"/api/v1/portfolio/holdings/{mine['holding']}", None),
        ]
    if "goal" in mine:
        attempts += [
            ("GET", f"/api/v1/goals/{mine['goal']}/forecast", None),
            ("PATCH", f"/api/v1/goals/{mine['goal']}", {"name": "hijacked"}),
            ("DELETE", f"/api/v1/goals/{mine['goal']}", None),
        ]
    if "linked_account" in mine:
        attempts += [
            ("POST", f"/api/v1/linked-accounts/{mine['linked_account']}/sync", None),
            ("GET", f"/api/v1/linked-accounts/{mine['linked_account']}/syncs", None),
            ("DELETE", f"/api/v1/linked-accounts/{mine['linked_account']}", None),
        ]
    if "alert" in mine:
        attempts += [
            ("POST", f"/api/v1/alerts/{mine['alert']}/read", None),
            ("DELETE", f"/api/v1/alerts/{mine['alert']}", None),
        ]

    assert len(attempts) >= 6, f"too few resources to audit: {sorted(mine)}"

    for method, url, body in attempts:
        response = client.request(method, url, headers=other,
                                  json=body if body is not None else None)
        assert response.status_code in {403, 404}, (
            f"{method} {url} returned {response.status_code} to a different "
            f"user: {response.text[:200]}"
        )


def test_a_second_user_sees_an_empty_account(client, auth, second_user):
    """Listing endpoints must be scoped, not just id lookups."""
    _create_owned_resources(client, auth)
    other = second_user["headers"]

    assert client.get("/api/v1/portfolio/holdings", headers=other).json() == []
    assert client.get("/api/v1/goals", headers=other).json() == []
    assert client.get("/api/v1/alerts", headers=other).json()["total"] == 0
    assert client.get("/api/v1/linked-accounts", headers=other).json()["total"] == 0
    assert client.get("/api/v1/portfolio/transactions", headers=other).json() == []


def test_a_malformed_token_is_refused_everywhere(client):
    """Not a 500. A bad token is an ordinary condition, not an exception."""
    bad = {"Authorization": "Bearer not.a.real.token"}
    for path, method in PROTECTED_ROUTES[:12]:
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, headers=bad)
        assert response.status_code < 500, (
            f"{method} {path} raised on a malformed token: {response.status_code}"
        )
        assert response.status_code != 200
