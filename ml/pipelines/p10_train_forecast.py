"""Stage 10 — wealth trajectory forecasting: baselines, XGBoost, LSTM and GRU.

What is being predicted
-----------------------
Not next month's stock returns, which are close to unpredictable. The target
is an investor's portfolio value h months ahead, which is genuinely
forecastable because it is dominated by what they already hold and what they
are about to contribute.

That dominance is also the trap. Regressing on raw rupee value gives a
near-0.99 R-squared for almost any model, because the model is mostly
restating the current balance. So every model here predicts **excess log
growth** over a contribution baseline:

    baseline  = V_t + h * monthly_contribution        (zero market return)
    target    = log(V_{t+h}) - log(baseline)

The baseline absorbs the predictable part; the models compete only on the
market-return component.

Both numbers are reported. R-squared on reconstructed rupee value is kept
for comparability with how such results are usually quoted, clearly labelled
as scale-inflated. R-squared on excess growth, and the skill score against
the baseline, are the honest measures.

Models compared
---------------
    Baseline A  contributions only, zero return      (the bar to beat)
    Baseline B  trailing drift carried forward
    XGBoost     gradient-boosted trees on tabular features
    LSTM / GRU  24-month sequences of the same features

Run:  python -m ml.pipelines.p10_train_forecast [--horizon 12] [--quick]
"""

from __future__ import annotations

import argparse
import json

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import xgboost as xgb
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.preprocessing import StandardScaler

from .common import (
    MODEL_DIR,
    PROCESSED_DIR,
    PipelineError,
    Stage,
    get_logger,
    silence_accelerate_matmul_warnings,
    write_report,
)

log = get_logger("forecast")
silence_accelerate_matmul_warnings()

RANDOM_STATE = 42
SEQUENCE_LENGTH = 24
EPOCHS = 25
BATCH_SIZE = 512
LEARNING_RATE = 1e-3
PATIENCE = 4

TABULAR_FEATURES = [
    "log_value", "months_invested",
    "return_1m", "return_3m", "return_6m", "return_12m",
    "volatility", "current_drawdown", "max_drawdown", "cumulative_return",
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation",
    "hhi", "top_holding_weight", "n_holdings", "turnover",
    "contribution_3m", "contribution_12m",
    "market_return_1m", "market_return_3m", "market_return_12m",
    "market_volatility_12m", "market_drawdown",
    "age", "annual_income", "monthly_savings", "investment_horizon_years",
    "month_of_year",
]

# Features the sequence models see at each timestep.
SEQUENCE_FEATURES = [
    "log_value", "period_return", "volatility", "current_drawdown",
    "equity_allocation", "debt_allocation", "gold_allocation", "cash_allocation",
    "hhi", "turnover", "contribution_ratio",
    "market_return_1m", "market_volatility_12m", "market_drawdown",
]


class SequenceForecaster(nn.Module):
    """An LSTM or GRU over the trailing window, with a linear head.

    Deliberately small and heavily regularised. There are 450,000 training
    sequences but only ~121 distinct months behind them, so the effective
    sample is the number of market regimes, not the number of rows. A larger
    network memorises investor-specific paths instead of learning the market
    signal: the first attempt reached a training loss of 0.003 while
    validation loss climbed to 0.022.
    """

    def __init__(self, n_features: int, hidden: int = 32, cell: str = "lstm"):
        super().__init__()
        rnn = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn(n_features, hidden, num_layers=1, batch_first=True)
        self.head = nn.Sequential(
            nn.Dropout(0.3), nn.Linear(hidden, 16), nn.ReLU(),
            nn.Dropout(0.3), nn.Linear(16, 1),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        output, _ = self.rnn(x)
        return self.head(output[:, -1, :]).squeeze(-1)


def regression_metrics(actual: np.ndarray, predicted: np.ndarray, label: str) -> dict:
    """MAE, RMSE, MAPE and R-squared for one prediction set."""
    mask = np.isfinite(actual) & np.isfinite(predicted)
    actual, predicted = actual[mask], predicted[mask]
    if len(actual) == 0:
        return {"label": label, "n": 0}

    non_zero = np.abs(actual) > 1e-9
    mape = (
        float(np.mean(np.abs((actual[non_zero] - predicted[non_zero]) / actual[non_zero])) * 100)
        if non_zero.any() else None
    )
    return {
        "label": label,
        "n": int(len(actual)),
        "mae": round(float(mean_absolute_error(actual, predicted)), 6),
        "rmse": round(float(np.sqrt(mean_squared_error(actual, predicted))), 6),
        "mape_pct": round(mape, 3) if mape is not None else None,
        "r2": round(float(r2_score(actual, predicted)), 6),
    }


def skill_score(actual: np.ndarray, predicted: np.ndarray, reference: np.ndarray) -> float:
    """Fractional reduction in mean squared error against a reference forecast.

    1 is perfect, 0 means no better than the reference, negative means worse.
    This is the number that says whether a model added anything.
    """
    mask = np.isfinite(actual) & np.isfinite(predicted) & np.isfinite(reference)
    model_error = mean_squared_error(actual[mask], predicted[mask])
    reference_error = mean_squared_error(actual[mask], reference[mask])
    if reference_error <= 0:
        return float("nan")
    return float(1.0 - model_error / reference_error)


def build_sequences(
    frame: pd.DataFrame, target_column: str, scaler: StandardScaler
) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Trailing windows of fixed length, grouped by the split of their target.

    Windows are cut from the full timeline and then assigned to a split by
    the month being predicted, not by the months in the window.

    Cutting windows inside each split separately does not work: validation
    spans 18 months and test 17, so no 24-month window fits inside either and
    both come back empty. It is also unnecessary. A window is history
    relative to the month it predicts, so a validation target may legitimately
    look back into the training period -- that is memory, not leakage. What
    would be leakage is a *target* appearing in more than one split, and
    assigning by target month prevents exactly that.
    """
    frame = frame.sort_values(["investor_id", "date"]).reset_index(drop=True)
    scaled = scaler.transform(frame[SEQUENCE_FEATURES]).astype("float32")

    investor_ids = frame["investor_id"].to_numpy()
    target_values = frame[target_column].to_numpy()
    splits = frame["split"].to_numpy()
    positions = np.arange(len(frame))

    collected: dict[str, list] = {"train": [], "validation": [], "test": []}

    start = 0
    boundaries = list(np.flatnonzero(np.diff(investor_ids)) + 1) + [len(frame)]
    for end in boundaries:
        block = slice(start, end)
        block_scaled = scaled[block]
        block_target = target_values[block]
        block_split = splits[block]
        block_positions = positions[block]

        for i in range(SEQUENCE_LENGTH, len(block_scaled)):
            if not np.isfinite(block_target[i]):
                continue
            bucket = collected.get(str(block_split[i]))
            if bucket is None:
                continue
            bucket.append(
                (block_scaled[i - SEQUENCE_LENGTH : i], block_target[i], block_positions[i])
            )
        start = end

    out: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for name, rows in collected.items():
        if not rows:
            out[name] = (
                np.empty((0, SEQUENCE_LENGTH, len(SEQUENCE_FEATURES)), dtype="float32"),
                np.empty(0, dtype="float32"),
                np.empty(0, dtype=int),
            )
            continue
        sequences = np.stack([r[0] for r in rows]).astype("float32")
        targets = np.asarray([r[1] for r in rows], dtype="float32")
        index = np.asarray([r[2] for r in rows], dtype=int)
        out[name] = (sequences, targets, index)
    return out


def train_sequence_model(
    cell: str, x_train, y_train, x_validation, y_validation, epochs: int,
) -> tuple[SequenceForecaster, list[dict]]:
    """Fit an LSTM or GRU with early stopping on validation loss."""
    device = torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    model = SequenceForecaster(x_train.shape[2], cell=cell).to(device)
    optimiser = torch.optim.Adam(
        model.parameters(), lr=LEARNING_RATE, weight_decay=1e-4
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimiser, mode='min', factor=0.5, patience=2
    )
    criterion = nn.MSELoss()

    loader = torch.utils.data.DataLoader(
        torch.utils.data.TensorDataset(
            torch.tensor(np.asarray(x_train, dtype='float32')),
            torch.tensor(np.asarray(y_train, dtype='float32')),
        ),
        batch_size=BATCH_SIZE, shuffle=True,
    )
    # MPS has no float64 support, so everything crossing to the device is float32.
    xv = torch.tensor(np.asarray(x_validation, dtype='float32')).to(device)
    yv = torch.tensor(np.asarray(y_validation, dtype='float32')).to(device)

    best_loss, best_state, waited, history = float("inf"), None, 0, []
    for epoch in range(1, epochs + 1):
        model.train()
        total = 0.0
        for batch_x, batch_y in loader:
            batch_x, batch_y = batch_x.to(device), batch_y.to(device)
            optimiser.zero_grad()
            loss = criterion(model(batch_x), batch_y)
            loss.backward()
            # Recurrent nets on long windows are prone to exploding gradients.
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimiser.step()
            total += loss.item() * len(batch_x)

        model.eval()
        with torch.no_grad():
            validation_loss = criterion(model(xv), yv).item()
        scheduler.step(validation_loss)
        history.append({"epoch": epoch, "train_loss": round(total / len(x_train), 6),
                        "validation_loss": round(validation_loss, 6),
                        "lr": optimiser.param_groups[0]["lr"]})

        if validation_loss < best_loss - 1e-7:
            best_loss, best_state, waited = validation_loss, {
                k: v.cpu().clone() for k, v in model.state_dict().items()
            }, 0
        else:
            waited += 1
            if waited >= PATIENCE:
                log.info("    early stop at epoch %d", epoch)
                break
        if epoch % 5 == 0 or epoch == 1:
            log.info("    epoch %2d  train %.6f  validation %.6f",
                     epoch, history[-1]["train_loss"], validation_loss)

    if best_state is not None:
        model.load_state_dict(best_state)
    return model.cpu(), history


def predict_sequence(model: SequenceForecaster, x: np.ndarray) -> np.ndarray:
    model.eval()
    out = []
    with torch.no_grad():
        for start in range(0, len(x), 4096):
            chunk = np.asarray(x[start : start + 4096], dtype='float32')
            out.append(model(torch.tensor(chunk)).numpy())
    return np.concatenate(out) if out else np.empty(0)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train the wealth forecasting models")
    parser.add_argument("--horizon", type=int, default=12, choices=[1, 3, 6, 12])
    parser.add_argument("--quick", action="store_true", help="fewer epochs, for a smoke test")
    args = parser.parse_args()

    path = PROCESSED_DIR / "features_forecast.parquet"
    if not path.exists():
        raise PipelineError("run stage 07 first to build the feature tables")

    horizon = args.horizon
    epochs = 5 if args.quick else EPOCHS
    torch.manual_seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)

    target_column = f"excess_log_growth_{horizon}m"
    future_column = f"future_value_{horizon}m"
    baseline_column = f"baseline_{horizon}m"

    report: dict = {
        "horizon_months": horizon,
        "target": target_column,
        "random_state": RANDOM_STATE,
        "target_rationale": (
            "Models predict excess log growth over a zero-return contribution "
            "baseline. Predicting raw rupee value yields an R-squared near 0.99 "
            "that reflects portfolio scale rather than forecasting skill."
        ),
    }

    with Stage(log, "load features"):
        frame = pd.read_parquet(path)
        needed = [target_column, future_column, baseline_column]
        frame = frame.dropna(subset=needed)
        frame[TABULAR_FEATURES] = frame[TABULAR_FEATURES].replace([np.inf, -np.inf], np.nan)
        frame["contribution_ratio"] = (
            frame["net_contribution"] / frame["total_value"].replace(0, np.nan)
        ).fillna(0.0)

        train = frame[frame.split == "train"]
        validation = frame[frame.split == "validation"]
        test = frame[frame.split == "test"]
        for name, part in (("train", train), ("validation", validation), ("test", test)):
            log.info("  %-11s %8d rows  %s → %s", name, len(part),
                     part.date.min().date(), part.date.max().date())
        report["rows"] = {"train": len(train), "validation": len(validation), "test": len(test)}

    actual_growth = test[target_column].to_numpy()
    actual_value = test[future_column].to_numpy()
    baseline_value = test[baseline_column].to_numpy()

    results: dict[str, dict] = {}

    with Stage(log, "baseline A — contributions only, zero return"):
        # Excess growth of zero by construction: the baseline predicts the
        # baseline. This is the bar every model must clear.
        predicted_growth = np.zeros(len(test))
        results["baseline_contributions"] = {
            "growth": regression_metrics(actual_growth, predicted_growth, "excess log growth"),
            "value": regression_metrics(actual_value, baseline_value, "rupee value"),
            "skill_vs_zero_baseline": 0.0,
            "skill_vs_mean_baseline": None,  # filled in once baseline C exists
        }
        log.info("  value R² %.4f   growth R² %.4f",
                 results["baseline_contributions"]["value"]["r2"],
                 results["baseline_contributions"]["growth"]["r2"])

    with Stage(log, "baseline C — long-run average drift (the honest reference)"):
        # Baseline A assumes zero market return. Over this sample markets drifted
        # up, so excess log growth averages +0.125 (about +13% over 12 months)
        # and A is biased low by that amount. Any model clears it largely by
        # learning the drift, which makes a skill score against A flattering.
        #
        # Baseline C predicts the training-set mean excess growth: the best
        # constant forecast available without looking at the test period. Skill
        # against C is equivalent to R-squared on excess growth, and is the
        # figure the report should lead with.
        train_mean_growth = float(train[target_column].mean())
        mean_growth = np.full(len(test), train_mean_growth)
        mean_value = baseline_value * np.exp(train_mean_growth)
        results["baseline_mean_drift"] = {
            "growth": regression_metrics(actual_growth, mean_growth, "excess log growth"),
            "value": regression_metrics(actual_value, mean_value, "rupee value"),
            "skill_vs_zero_baseline": round(
                skill_score(actual_growth, mean_growth, np.zeros(len(test))), 4
            ),
            "skill_vs_mean_baseline": 0.0,
            "train_mean_excess_log_growth": round(train_mean_growth, 6),
        }
        log.info("  train mean excess log growth %+.4f (about %+.1f%% over %d months)",
                 train_mean_growth, 100 * (np.exp(train_mean_growth) - 1), horizon)
        log.info("  value R² %.4f   growth R² %.4f",
                 results["baseline_mean_drift"]["value"]["r2"],
                 results["baseline_mean_drift"]["growth"]["r2"])

    with Stage(log, "baseline B — trailing drift carried forward"):
        monthly_drift = test["return_12m"].fillna(0.0).to_numpy() / 12.0
        drift_growth = np.log1p(np.clip(monthly_drift, -0.9, 0.9)) * horizon
        drift_value = baseline_value * np.exp(drift_growth)
        results["baseline_drift"] = {
            "growth": regression_metrics(actual_growth, drift_growth, "excess log growth"),
            "value": regression_metrics(actual_value, drift_value, "rupee value"),
            "skill_vs_zero_baseline": round(
                skill_score(actual_growth, drift_growth, np.zeros(len(test))), 4
            ),
            "skill_vs_mean_baseline": round(
                skill_score(actual_growth, drift_growth, mean_growth), 4
            ),
        }
        log.info("  value R² %.4f   growth R² %.4f   skill vs mean %.4f",
                 results["baseline_drift"]["value"]["r2"],
                 results["baseline_drift"]["growth"]["r2"],
                 results["baseline_drift"]["skill_vs_mean_baseline"])

    with Stage(log, "XGBoost"):
        medians = train[TABULAR_FEATURES].median()
        def tabular(part): return part[TABULAR_FEATURES].fillna(medians).to_numpy()

        # A small grid, selected on validation RMSE. The first attempt used a
        # single configuration (depth 6, lr 0.05) and early-stopped at five
        # trees, because that much capacity per tree overfits this target
        # almost immediately. Concluding that a recurrent model beats XGBoost
        # while XGBoost is effectively untuned would not be a fair comparison.
        grid = [
            {"max_depth": 3, "learning_rate": 0.02, "min_child_weight": 50},
            {"max_depth": 4, "learning_rate": 0.02, "min_child_weight": 100},
            {"max_depth": 4, "learning_rate": 0.05, "min_child_weight": 50},
            {"max_depth": 6, "learning_rate": 0.05, "min_child_weight": 5},
        ]
        search = []
        xgb_model, best_rmse, best_params = None, float("inf"), None
        for params in grid:
            candidate = xgb.XGBRegressor(
                n_estimators=1500, subsample=0.8, colsample_bytree=0.8,
                reg_lambda=5.0, random_state=RANDOM_STATE, n_jobs=-1,
                early_stopping_rounds=50, eval_metric="rmse", **params,
            )
            candidate.fit(
                tabular(train), train[target_column],
                eval_set=[(tabular(validation), validation[target_column])],
                verbose=False,
            )
            rmse = float(candidate.best_score)
            search.append({**params, "validation_rmse": round(rmse, 6),
                           "best_iteration": int(candidate.best_iteration)})
            log.info("  depth %d lr %.2f min_child %3d → validation RMSE %.6f (%d trees)",
                     params["max_depth"], params["learning_rate"],
                     params["min_child_weight"], rmse, candidate.best_iteration)
            if rmse < best_rmse:
                xgb_model, best_rmse, best_params = candidate, rmse, params

        report["xgboost_search"] = search
        report["xgboost_best_params"] = best_params
        log.info("  chosen: %s", best_params)

        predicted_growth_xgb = xgb_model.predict(tabular(test))
        predicted_value_xgb = baseline_value * np.exp(predicted_growth_xgb)

        results["xgboost"] = {
            "growth": regression_metrics(actual_growth, predicted_growth_xgb, "excess log growth"),
            "value": regression_metrics(actual_value, predicted_value_xgb, "rupee value"),
            "skill_vs_zero_baseline": round(
                skill_score(actual_growth, predicted_growth_xgb, np.zeros(len(test))), 4
            ),
            "skill_vs_mean_baseline": round(
                skill_score(actual_growth, predicted_growth_xgb, mean_growth), 4
            ),
            "best_iteration": int(xgb_model.best_iteration),
        }
        log.info("  value R² %.4f   growth R² %.4f   skill vs mean %.4f   (%d trees)",
                 results["xgboost"]["value"]["r2"], results["xgboost"]["growth"]["r2"],
                 results["xgboost"]["skill_vs_mean_baseline"], xgb_model.best_iteration)

        importance = sorted(
            zip(TABULAR_FEATURES, xgb_model.feature_importances_), key=lambda kv: -kv[1]
        )[:12]
        report["xgboost_feature_importance"] = [
            {"feature": f, "importance": round(float(v), 5)} for f, v in importance
        ]
        log.info("  top features: %s", ", ".join(f for f, _ in importance[:5]))

    with Stage(log, "build sequences for the recurrent models"):
        prepared = frame.copy()
        prepared[SEQUENCE_FEATURES] = (
            prepared[SEQUENCE_FEATURES].replace([np.inf, -np.inf], np.nan).fillna(0.0)
        )
        sequence_scaler = StandardScaler().fit(
            prepared.loc[prepared.split == "train", SEQUENCE_FEATURES]
        )
        windows = build_sequences(prepared, target_column, sequence_scaler)
        x_train, y_train, _ = windows["train"]
        x_validation, y_validation, _ = windows["validation"]
        x_test, y_test, test_rows = windows["test"]

        log.info("  train %d, validation %d, test %d sequences of length %d",
                 len(x_train), len(x_validation), len(x_test), SEQUENCE_LENGTH)
        if len(x_validation) == 0 or len(x_test) == 0:
            raise PipelineError(
                "a split produced no sequences; check the split boundaries "
                "against the sequence length"
            )
        report["sequences"] = {
            "length": SEQUENCE_LENGTH, "features": len(SEQUENCE_FEATURES),
            "train": int(len(x_train)), "validation": int(len(x_validation)),
            "test": int(len(x_test)),
            "assignment": "by the split of the month being predicted",
        }

    sequence_models = {}
    for cell in ("lstm", "gru"):
        with Stage(log, cell.upper()):
            sequence_model, history = train_sequence_model(
                cell, x_train, y_train, x_validation, y_validation, epochs
            )
            sequence_models[cell] = sequence_model
            predicted = predict_sequence(sequence_model, x_test)

            # Sequence models cover a subset of test rows; compare on that subset.
            subset_actual_growth = y_test
            subset_baseline = prepared[baseline_column].to_numpy()[test_rows]
            subset_actual_value = prepared[future_column].to_numpy()[test_rows]
            predicted_value = subset_baseline * np.exp(predicted)

            results[cell] = {
                "growth": regression_metrics(subset_actual_growth, predicted, "excess log growth"),
                "value": regression_metrics(subset_actual_value, predicted_value, "rupee value"),
                "skill_vs_zero_baseline": round(
                    skill_score(subset_actual_growth, predicted, np.zeros(len(predicted))), 4
                ),
                "skill_vs_mean_baseline": round(
                    skill_score(
                        subset_actual_growth, predicted,
                        np.full(len(predicted), train_mean_growth),
                    ), 4
                ),
                "epochs_run": len(history),
                "evaluated_on_subset": True,
                "subset_rows": int(len(predicted)),
            }
            log.info("  value R² %.4f   growth R² %.4f   skill vs mean %.4f",
                     results[cell]["value"]["r2"], results[cell]["growth"]["r2"],
                     results[cell]["skill_vs_mean_baseline"])

    with Stage(log, "compare"):
        log.info("  %-24s %10s %11s %11s %11s", "model", "value R²",
                 "growth R²", "skill/zero", "skill/mean")
        for name, scores in results.items():
            zero = scores.get("skill_vs_zero_baseline")
            mean = scores.get("skill_vs_mean_baseline")
            log.info("  %-24s %10.4f %11.4f %11s %11s",
                     name, scores["value"]["r2"], scores["growth"]["r2"],
                     f"{zero:.4f}" if zero is not None else "-",
                     f"{mean:.4f}" if mean is not None else "-")

        ranked = sorted(
            ((n, s["skill_vs_mean_baseline"]) for n, s in results.items()
             if s.get("skill_vs_mean_baseline") is not None
             and n not in ("baseline_mean_drift", "baseline_contributions")),
            key=lambda kv: -kv[1],
        )
        report["best_model"] = {"name": ranked[0][0], "skill_vs_mean_baseline": ranked[0][1]}
        log.info("  best against the mean-drift baseline: %s (%.4f)",
                 ranked[0][0], ranked[0][1])

    report["results"] = results
    report["interpretation"] = (
        "R-squared on rupee value is high for every model including the "
        "zero-return baseline, because portfolio value at t+h is dominated by "
        "value at t plus contributions; it measures scale, not skill. "
        "Skill against the zero-return baseline is also flattering, because "
        "that baseline ignores market drift and so is biased low by roughly "
        "the average market return over the horizon. The honest figures are "
        "R-squared on excess log growth and the skill score against the "
        "mean-drift baseline, which are equivalent to each other and measure "
        "what a model adds over the best constant forecast."
    )

    with Stage(log, "save artifacts"):
        joblib.dump(
            {
                "xgboost": xgb_model, "tabular_features": TABULAR_FEATURES,
                "tabular_medians": medians, "sequence_scaler": sequence_scaler,
                "sequence_features": SEQUENCE_FEATURES, "sequence_length": SEQUENCE_LENGTH,
                "horizon": horizon, "version": "1.0.0",
            },
            MODEL_DIR / f"forecast_{horizon}m.joblib",
        )
        for cell, sequence_model in sequence_models.items():
            torch.save(
                {"state_dict": sequence_model.state_dict(),
                 "n_features": len(SEQUENCE_FEATURES), "cell": cell},
                MODEL_DIR / f"forecast_{cell}_{horizon}m.pt",
            )
        log.info("  → ml/models/forecast_%dm.joblib (+ lstm, gru)", horizon)

    write_report(f"forecast_{horizon}m", report)
    log.info("forecast report written")


if __name__ == "__main__":
    main()
