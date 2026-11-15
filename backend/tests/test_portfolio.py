"""Portfolio holdings, valuation, CSV import and cross-user isolation."""

from __future__ import annotations

import io

import pytest


def _csv(text: str) -> dict:
    return {"file": ("holdings.csv", io.BytesIO(text.encode()), "text/csv")}


# --------------------------------------------------------------------------
# Holdings
# --------------------------------------------------------------------------

def test_new_portfolio_is_empty_not_an_error(client, auth):
    response = client.get("/api/v1/portfolio", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["total_value"] == 0
    assert body["n_holdings"] == 0
    assert body["top_holdings"] == []


def test_holding_can_be_created_and_is_priced(client, auth):
    response = client.post("/api/v1/portfolio/holdings", headers=auth,
                           json={"symbol": "RELIANCE", "quantity": 10, "average_price": 1000})
    assert response.status_code == 201
    body = response.json()
    assert body["symbol"] == "RELIANCE"
    assert body["current_price"] > 0
    assert body["market_value"] == pytest.approx(body["current_price"] * 10)
    assert body["cost_basis"] == pytest.approx(10_000)


def test_symbol_is_case_insensitive(client, auth):
    response = client.post("/api/v1/portfolio/holdings", headers=auth,
                           json={"symbol": "reliance", "quantity": 5, "average_price": 1000})
    assert response.status_code == 201
    assert response.json()["symbol"] == "RELIANCE"


def test_unknown_symbol_is_rejected(client, auth):
    response = client.post("/api/v1/portfolio/holdings", headers=auth,
                           json={"symbol": "NOTREAL", "quantity": 1, "average_price": 1})
    assert response.status_code == 404


def test_delisted_asset_cannot_be_held(client, auth):
    response = client.post("/api/v1/portfolio/holdings", headers=auth,
                           json={"symbol": "OLDCO", "quantity": 1, "average_price": 100})
    assert response.status_code == 400
    assert "delisted" in response.json()["detail"]


def test_non_positive_quantity_is_rejected(client, auth):
    for quantity in (0, -5):
        response = client.post("/api/v1/portfolio/holdings", headers=auth,
                               json={"symbol": "TCS", "quantity": quantity,
                                     "average_price": 3000})
        assert response.status_code == 422


def test_buying_the_same_asset_twice_merges_at_weighted_average_cost(client, auth):
    # 10 at 1000 then 10 at 2000 is 20 units at an average of 1500. Appending a
    # second row instead would double-count the position in every weight.
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 10, "average_price": 1000})
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 10, "average_price": 2000})

    holdings = client.get("/api/v1/portfolio/holdings", headers=auth).json()
    assert len(holdings) == 1
    assert holdings[0]["quantity"] == pytest.approx(20)
    assert holdings[0]["average_price"] == pytest.approx(1500)


def test_portfolio_weights_sum_to_one(client, auth):
    for symbol, quantity, price in [("RELIANCE", 10, 1000), ("TCS", 5, 3000),
                                    ("GOLDBEES", 100, 50)]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity, "average_price": price})

    holdings = client.get("/api/v1/portfolio/holdings", headers=auth).json()
    assert sum(h["weight"] for h in holdings) == pytest.approx(1.0)


def test_summary_allocations_are_consistent_with_total_value(client, auth):
    for symbol, quantity, price in [("RELIANCE", 10, 1000), ("TCS", 5, 3000),
                                    ("GOLDBEES", 100, 50), ("DEBT", 200, 50)]:
        client.post("/api/v1/portfolio/holdings", headers=auth,
                    json={"symbol": symbol, "quantity": quantity, "average_price": price})

    body = client.get("/api/v1/portfolio", headers=auth).json()

    assert body["n_holdings"] == 4
    assert sum(a["weight"] for a in body["allocation_by_class"]) == pytest.approx(1.0)
    assert sum(a["value"] for a in body["allocation_by_class"]) == pytest.approx(
        body["total_value"]
    )
    assert sum(a["weight"] for a in body["allocation_by_sector"]) == pytest.approx(1.0)
    # IT holds only TCS here; Energy only RELIANCE.
    sectors = {a["label"] for a in body["allocation_by_sector"]}
    assert {"IT", "Energy", "Commodities", "Sovereign Debt"} <= sectors


def test_holding_can_be_updated_and_deleted(client, auth):
    created = client.post("/api/v1/portfolio/holdings", headers=auth,
                          json={"symbol": "TCS", "quantity": 5, "average_price": 3000}).json()

    updated = client.patch(f"/api/v1/portfolio/holdings/{created['id']}", headers=auth,
                           json={"quantity": 12})
    assert updated.status_code == 200
    assert updated.json()["quantity"] == pytest.approx(12)

    assert client.delete(f"/api/v1/portfolio/holdings/{created['id']}",
                         headers=auth).status_code == 204
    assert client.get("/api/v1/portfolio/holdings", headers=auth).json() == []


# --------------------------------------------------------------------------
# Cross-user isolation
# --------------------------------------------------------------------------

def test_users_cannot_see_each_others_holdings(client, auth, second_user):
    client.post("/api/v1/portfolio/holdings", headers=auth,
                json={"symbol": "RELIANCE", "quantity": 10, "average_price": 1000})

    assert client.get("/api/v1/portfolio/holdings", headers=second_user["headers"]).json() == []
    assert client.get("/api/v1/portfolio", headers=second_user["headers"]).json()["total_value"] == 0


def test_a_user_cannot_modify_another_users_holding_by_id(client, auth, second_user):
    created = client.post("/api/v1/portfolio/holdings", headers=auth,
                          json={"symbol": "RELIANCE", "quantity": 10,
                                "average_price": 1000}).json()
    other = second_user["headers"]

    # 404, not 403: the second user is not told the holding exists at all.
    assert client.patch(f"/api/v1/portfolio/holdings/{created['id']}", headers=other,
                        json={"quantity": 999}).status_code == 404
    assert client.delete(f"/api/v1/portfolio/holdings/{created['id']}",
                         headers=other).status_code == 404

    unchanged = client.get("/api/v1/portfolio/holdings", headers=auth).json()[0]
    assert unchanged["quantity"] == pytest.approx(10)


# --------------------------------------------------------------------------
# CSV import
# --------------------------------------------------------------------------

def test_valid_csv_imports_every_row(client, auth):
    response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
        "symbol,quantity,average_price\n"
        "RELIANCE,10,1000\n"
        "TCS,5,3000\n"
        "GOLDBEES,100,50\n"
    ))
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] is True
    assert body["rows_imported"] == 3
    assert body["holdings_created"] == 3
    assert len(client.get("/api/v1/portfolio/holdings", headers=auth).json()) == 3


def test_import_is_all_or_nothing(client, auth):
    # One bad row in ten rejects the file. A partially imported portfolio
    # produces analytics that look complete and are wrong.
    response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
        "symbol,quantity,average_price\n"
        "RELIANCE,10,1000\n"
        "NOTREAL,5,3000\n"
        "TCS,5,3000\n"
    ))
    body = response.json()

    assert body["accepted"] is False
    assert body["rows_imported"] == 0
    assert len(body["errors"]) == 1
    assert body["errors"][0]["row_number"] == 3
    # Nothing was written, including the rows that were individually valid.
    assert client.get("/api/v1/portfolio/holdings", headers=auth).json() == []


def test_missing_required_column_is_reported_clearly(client, auth):
    response = client.post("/api/v1/portfolio/import", headers=auth,
                           files=_csv("symbol,quantity\nRELIANCE,10\n"))
    body = response.json()
    assert body["accepted"] is False
    assert "average_price" in body["errors"][0]["message"]


@pytest.mark.parametrize("row,bad_field", [
    ("RELIANCE,-5,1000", "quantity"),
    ("RELIANCE,0,1000", "quantity"),
    ("RELIANCE,abc,1000", "quantity"),
    ("RELIANCE,10,0", "average_price"),
    ("RELIANCE,10,notanumber", "average_price"),
    ("NOTREAL,10,1000", "symbol"),
    (",10,1000", "symbol"),
])
def test_each_invalid_field_is_caught(client, auth, row, bad_field):
    response = client.post("/api/v1/portfolio/import", headers=auth,
                           files=_csv(f"symbol,quantity,average_price\n{row}\n"))
    body = response.json()
    assert body["accepted"] is False
    assert body["errors"][0]["field"] == bad_field


def test_invalid_and_future_dates_are_rejected(client, auth):
    for bad_date in ("31-02-2022", "not-a-date", "2099-01-01"):
        response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
            f"symbol,quantity,average_price,purchase_date\nRELIANCE,10,1000,{bad_date}\n"
        ))
        body = response.json()
        assert body["accepted"] is False, bad_date
        assert body["errors"][0]["field"] == "purchase_date"


def test_common_indian_date_formats_are_accepted(client, auth):
    for good_date in ("2022-03-15", "15-03-2022", "15/03/2022", "15-Mar-2022"):
        response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
            f"symbol,quantity,average_price,purchase_date\nRELIANCE,1,1000,{good_date}\n"
        ))
        assert response.json()["accepted"] is True, good_date


def test_duplicate_symbols_in_one_file_are_merged_with_a_warning(client, auth):
    response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
        "symbol,quantity,average_price\nRELIANCE,10,1000\nRELIANCE,10,2000\n"
    ))
    body = response.json()
    assert body["accepted"] is True
    assert any("also appears on row" in w for w in body["warnings"])

    holdings = client.get("/api/v1/portfolio/holdings", headers=auth).json()
    assert len(holdings) == 1
    assert holdings[0]["average_price"] == pytest.approx(1500)


def test_empty_and_headerless_files_are_rejected(client, auth):
    assert client.post("/api/v1/portfolio/import", headers=auth,
                       files=_csv("   ")).status_code == 400
    body = client.post("/api/v1/portfolio/import", headers=auth,
                       files=_csv("symbol,quantity,average_price\n")).json()
    assert body["accepted"] is False


def test_non_csv_upload_is_rejected(client, auth):
    response = client.post("/api/v1/portfolio/import", headers=auth, files={
        "file": ("holdings.xlsx", io.BytesIO(b"not a csv"), "application/vnd.ms-excel")
    })
    assert response.status_code == 400


def test_replace_existing_clears_the_previous_portfolio(client, auth):
    client.post("/api/v1/portfolio/import", headers=auth,
                files=_csv("symbol,quantity,average_price\nRELIANCE,10,1000\n"))
    client.post("/api/v1/portfolio/import?replace_existing=true", headers=auth,
                files=_csv("symbol,quantity,average_price\nTCS,5,3000\n"))

    holdings = client.get("/api/v1/portfolio/holdings", headers=auth).json()
    assert [h["symbol"] for h in holdings] == ["TCS"]


def test_cost_basis_far_from_the_historical_price_is_flagged(client, auth, seeded_db):
    # RELIANCE starts at 1000 in the fixture and drifts up slowly, so a cost
    # basis of 2000 on the first date is roughly 2x the adjusted price -- the
    # signature of an unadjusted corporate action.
    from app.models import Asset, MarketPrice

    asset = seeded_db.query(Asset).filter_by(symbol="RELIANCE").one()
    earliest = (
        seeded_db.query(MarketPrice)
        .filter_by(asset_id=asset.id)
        .order_by(MarketPrice.date)
        .first()
    )
    response = client.post("/api/v1/portfolio/import", headers=auth, files=_csv(
        "symbol,quantity,average_price,purchase_date\n"
        f"RELIANCE,10,{earliest.close * 2:.2f},{earliest.date}\n"
    ))
    body = response.json()
    assert body["accepted"] is True
    assert any("corporate action" in w for w in body["warnings"])


# --------------------------------------------------------------------------
# Transactions
# --------------------------------------------------------------------------

def test_a_trade_requires_a_symbol(client, auth):
    response = client.post("/api/v1/portfolio/transactions", headers=auth, json={
        "transaction_type": "buy", "date": "2024-01-15", "value": 10000,
    })
    assert response.status_code == 422


def test_a_contribution_must_not_carry_a_symbol(client, auth):
    # Contributions are external cash flows. Attaching an asset to one would
    # make it indistinguishable from a purchase in the return calculation.
    response = client.post("/api/v1/portfolio/transactions", headers=auth, json={
        "transaction_type": "contribution", "date": "2024-01-15",
        "symbol": "RELIANCE", "value": 10000,
    })
    assert response.status_code == 422


def test_contribution_is_recorded(client, auth):
    response = client.post("/api/v1/portfolio/transactions", headers=auth, json={
        "transaction_type": "contribution", "date": "2024-01-15", "value": 25000,
    })
    assert response.status_code == 201
    assert response.json()["symbol"] is None


def test_trade_value_is_derived_from_quantity_and_price(client, auth):
    response = client.post("/api/v1/portfolio/transactions", headers=auth, json={
        "transaction_type": "buy", "date": "2024-01-15",
        "symbol": "RELIANCE", "quantity": 10, "price": 1200,
    })
    assert response.status_code == 201
    assert response.json()["value"] == pytest.approx(12_000)


def test_transactions_are_scoped_to_their_owner(client, auth, second_user):
    client.post("/api/v1/portfolio/transactions", headers=auth, json={
        "transaction_type": "contribution", "date": "2024-01-15", "value": 25000,
    })
    assert client.get("/api/v1/portfolio/transactions",
                      headers=second_user["headers"]).json() == []
