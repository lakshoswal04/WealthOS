"""Model-backed insights: investor profile, anomalies and wealth forecast.

Every function degrades to a clear "unavailable" payload when its model
artifact is missing, rather than raising. A missing file should disable one
panel of the dashboard, not break the page.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import torch
from sqlalchemy.orm import Session

from app.ml_runtime import features as live_features
from app.ml_runtime.registry import registry
from app.models import User

MIN_MONTHS_FOR_PROFILE = 6
MIN_MONTHS_FOR_SEQUENCE = 24

UNAVAILABLE = {
    "available": False,
    "reason": "The trained model artifact is not present. Run the ml pipelines to build it.",
}


def _history(db: Session, user: User) -> pd.DataFrame:
    return live_features.monthly_history(db, user)


# --------------------------------------------------------------------------
# Investor profile (clustering)
# --------------------------------------------------------------------------

def investor_profile(db: Session, user: User) -> dict:
    artifact = registry.clustering()
    if artifact is None:
        return dict(UNAVAILABLE, model="investor_clustering")

    history = _history(db, user)
    if len(history) < MIN_MONTHS_FOR_PROFILE:
        return {
            "available": False,
            "reason": (
                f"At least {MIN_MONTHS_FOR_PROFILE} months of portfolio history "
                f"are needed to profile behaviour; this portfolio has {len(history)}."
            ),
        }

    profile = live_features.behavioural_profile(history, user)
    columns = artifact["feature_columns"]
    vector = pd.DataFrame([[profile.get(c, 0.0) for c in columns]], columns=columns)
    vector = vector.replace([np.inf, -np.inf], 0.0).fillna(0.0)

    scaled = artifact["scaler"].transform(vector)
    cluster = int(artifact["kmeans"].predict(scaled)[0])
    matched = next(p for p in artifact["cluster_profiles"] if p["cluster"] == cluster)

    # Distance to every centroid, so the UI can show how clear-cut the match is.
    distances = np.linalg.norm(artifact["kmeans"].cluster_centers_ - scaled, axis=1)
    order = np.argsort(distances)
    confidence = float(
        1.0 - distances[order[0]] / distances[order[1]]
    ) if len(order) > 1 and distances[order[1]] > 0 else 0.0

    # Where this investor sits against their cluster's centroid.
    centroid = matched["centroid"]
    differences = sorted(
        (
            {
                "feature": column,
                "investor": round(float(profile.get(column, 0.0)), 4),
                "cluster_average": round(float(centroid.get(column, 0.0)), 4),
            }
            for column in columns
        ),
        key=lambda d: -abs(d["investor"] - d["cluster_average"]),
    )[:5]

    return {
        "available": True,
        "cluster": cluster,
        "cluster_name": matched["name"],
        "cluster_size": matched["size"],
        "cluster_share": matched["share"],
        "match_confidence": round(max(0.0, min(confidence, 1.0)), 3),
        "distinguishing_traits": matched["distinguishing_traits"],
        "investor_features": {k: round(float(v), 4) for k, v in profile.items()},
        "largest_differences_from_cluster": differences,
        "stated_risk_tolerance": str(user.risk_tolerance) if user.risk_tolerance else None,
        "method": (
            "K-Means over behavioural features, fitted on a synthetic cohort of "
            "10,000 investors. Cluster names were derived from fitted centroids."
        ),
        "caveat": (
            "Behaviour is reconstructed by valuing current holdings back through "
            "price history, so it reflects the portfolio held today rather than "
            "a replay of past positions."
        ),
    }


# --------------------------------------------------------------------------
# Anomaly detection
# --------------------------------------------------------------------------

def detect_anomalies(db: Session, user: User, limit: int = 24) -> dict:
    artifact = registry.anomaly()
    if artifact is None:
        return dict(UNAVAILABLE, model="anomaly_autoencoder")

    history = _history(db, user)
    if len(history) < 3:
        return {
            "available": False,
            "reason": "At least three months of history are needed to detect unusual activity.",
        }

    columns = artifact["feature_columns"]
    frame = history.sort_values("date").copy()

    allocation_columns = [
        "equity_allocation", "etf_allocation", "gold_allocation",
        "debt_allocation", "cash_allocation",
    ]
    for column in allocation_columns + ["hhi", "top_holding_weight", "n_holdings"]:
        frame[f"delta_{column}"] = frame[column].diff()
    frame["allocation_shift"] = (
        frame[[f"delta_{c}" for c in allocation_columns]].abs().sum(axis=1) / 2.0
    )
    median_turnover = frame["turnover"].median()
    frame["turnover_ratio"] = (
        frame["turnover"] / median_turnover if median_turnover else 0.0
    )

    usable = frame.dropna(subset=["delta_equity_allocation"]).copy()
    if usable.empty:
        return {"available": False, "reason": "Not enough consecutive months to compare."}

    matrix = usable.reindex(columns=columns).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    scaled = artifact["scaler"].transform(matrix)

    with torch.no_grad():
        tensor = torch.tensor(scaled, dtype=torch.float32)
        rebuilt = artifact["model"](tensor)
        errors = ((rebuilt - tensor) ** 2).mean(dim=1).numpy()

    threshold = float(artifact["threshold"])
    usable["anomaly_score"] = errors
    usable["is_anomaly"] = errors >= threshold

    # Which features the model reconstructed worst explains *why* a month
    # looked unusual, rather than only that it did.
    per_feature_error = ((rebuilt - tensor) ** 2).numpy()

    detected = []
    for position, (_, row) in enumerate(usable.iterrows()):
        if not row["is_anomaly"]:
            continue
        worst = np.argsort(per_feature_error[position])[::-1][:3]
        detected.append({
            "date": str(pd.Timestamp(row["date"]).date()),
            "score": round(float(row["anomaly_score"]), 6),
            "threshold": round(threshold, 6),
            "severity": (
                "critical" if row["anomaly_score"] > threshold * 3
                else "warning" if row["anomaly_score"] > threshold * 1.5
                else "info"
            ),
            "contributing_features": [
                {"feature": columns[i], "value": round(float(matrix.iloc[position, i]), 4)}
                for i in worst
            ],
        })

    timeline = [
        {"date": str(pd.Timestamp(d).date()), "score": round(float(s), 6),
         "is_anomaly": bool(a)}
        for d, s, a in zip(usable["date"], usable["anomaly_score"], usable["is_anomaly"])
    ][-limit:]

    return {
        "available": True,
        "threshold": round(threshold, 6),
        "months_examined": int(len(usable)),
        "anomalies_found": len(detected),
        "anomalies": detected[-limit:],
        "timeline": timeline,
        "method": (
            "Autoencoder reconstruction error. The model was trained only on "
            "normal portfolio-months, so patterns it reconstructs poorly are "
            "unlike anything it learned."
        ),
        "caveat": (
            "Trained and validated against injected anomalies in a synthetic "
            "cohort, which are more clear-cut than real behaviour."
        ),
    }


# --------------------------------------------------------------------------
# Wealth forecast
# --------------------------------------------------------------------------

def wealth_forecast(db: Session, user: User, horizon: int = 12) -> dict:
    artifact = registry.forecast(horizon)
    if artifact is None:
        return dict(UNAVAILABLE, model=f"forecast_{horizon}m")

    history = _history(db, user)
    if len(history) < 12:
        return {
            "available": False,
            "reason": (
                "At least twelve months of portfolio history are needed to "
                f"forecast; this portfolio has {len(history)}."
            ),
        }

    market = live_features.market_context(db, pd.DatetimeIndex(history["date"]))
    frame = history.merge(market, on="date", how="left")

    latest = frame.iloc[-1]
    current_value = float(latest["total_value"])
    monthly_contribution = float(
        frame["net_contribution"].tail(3).mean()
        or (user.monthly_savings or 0.0)
    )
    baseline = current_value + horizon * monthly_contribution

    # Trailing returns the tabular model expects.
    returns = frame["period_return"].fillna(0.0)
    for window in (1, 3, 6, 12):
        frame[f"return_{window}m"] = (
            returns.rolling(window, min_periods=1).apply(lambda x: np.prod(1 + x) - 1, raw=True)
        )
    frame["contribution_3m"] = frame["net_contribution"].rolling(3, min_periods=1).mean()
    frame["contribution_12m"] = frame["net_contribution"].rolling(12, min_periods=1).mean()
    frame["age"] = user.age or 35
    frame["annual_income"] = float(user.annual_income or 1_200_000)
    frame["monthly_savings"] = float(user.monthly_savings or 0.0)
    frame["investment_horizon_years"] = user.investment_horizon_years or 15

    predictions: dict[str, dict] = {}

    tabular_columns = artifact["tabular_features"]
    tabular_row = (
        frame.reindex(columns=tabular_columns)
        .fillna(artifact["tabular_medians"])
        .replace([np.inf, -np.inf], 0.0)
        .fillna(0.0)
        .tail(1)
    )
    growth = float(artifact["xgboost"].predict(tabular_row.to_numpy())[0])
    predictions["xgboost"] = {
        "excess_log_growth": round(growth, 6),
        "projected_value": round(baseline * float(np.exp(growth)), 2),
    }

    sequence_columns = artifact["sequence_features"]
    sequence_length = artifact["sequence_length"]
    if len(frame) >= sequence_length and artifact["sequence_models"]:
        window = (
            frame.reindex(columns=sequence_columns)
            .replace([np.inf, -np.inf], np.nan)
            .fillna(0.0)
            .tail(sequence_length)
        )
        scaled = artifact["sequence_scaler"].transform(window).astype("float32")
        tensor = torch.tensor(scaled[None, :, :])
        for cell, model in artifact["sequence_models"].items():
            with torch.no_grad():
                value = float(model(tensor).item())
            predictions[cell] = {
                "excess_log_growth": round(value, 6),
                "projected_value": round(baseline * float(np.exp(value)), 2),
            }

    # The ensemble is the mean of the available models' log-growth estimates.
    estimates = [p["excess_log_growth"] for p in predictions.values()]
    mean_growth = float(np.mean(estimates))
    projected = baseline * float(np.exp(mean_growth))

    # How far apart the models are is itself information. On this portfolio
    # the LSTM and XGBoost can land on opposite signs, and averaging them
    # into one confident-looking number would hide that. The spread is
    # reported so the UI can show a range and say when the models disagree.
    spread = float(max(estimates) - min(estimates)) if len(estimates) > 1 else 0.0
    low_value = baseline * float(np.exp(min(estimates)))
    high_value = baseline * float(np.exp(max(estimates)))
    if spread < 0.05:
        agreement = "models broadly agree"
    elif spread < 0.15:
        agreement = "models differ moderately"
    else:
        agreement = "models disagree substantially; treat the single figure with caution"

    return {
        "available": True,
        "horizon_months": horizon,
        "current_value": round(current_value, 2),
        "monthly_contribution": round(monthly_contribution, 2),
        "baseline_value": round(baseline, 2),
        "projected_value": round(projected, 2),
        "projected_growth_over_baseline": round(float(np.exp(mean_growth) - 1), 4),
        "projection_range": {
            "low": round(low_value, 2),
            "high": round(high_value, 2),
            "log_growth_spread": round(spread, 4),
            "agreement": agreement,
        },
        "model_predictions": predictions,
        "models_used": list(predictions),
        "assumptions": {
            "baseline": (
                "Current value plus the recent average monthly contribution "
                "carried forward at a zero market return."
            ),
            "target": (
                "Models predict excess log growth over that baseline, so they "
                "estimate only the market-return component."
            ),
            "contribution_source": "average of the last three recorded months",
            "note": (
                "A projection under these assumptions, not a prediction. "
                "Actual returns vary and may be negative."
            ),
        },
        "model_performance": {
            "note": (
                "Measured on a held-out test period of the synthetic cohort. "
                "Skill is quoted against a mean-drift baseline, which is the "
                "honest reference; see ml/reports/forecast_12m.json."
            ),
        },
    }
