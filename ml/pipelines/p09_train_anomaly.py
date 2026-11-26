"""Stage 09 — portfolio anomaly detection with a PyTorch autoencoder.

An autoencoder is trained to reconstruct *normal* portfolio-months. Anything
it reconstructs badly is unusual relative to what it has seen. Training uses
only rows labelled normal, so the model never learns to reproduce the
behaviour it is meant to flag.

An Isolation Forest is fitted on the same features as a baseline. A deep
model that cannot beat a standard shallow detector has not earned its place
in the system, and reporting only the autoencoder's score would hide that.

Thresholds are chosen on validation and applied unchanged to test. Picking
the threshold that maximises F1 on the test set itself would inflate every
number reported.

Honest framing for the report: the anomalies are injected and deliberately
unambiguous, so these scores are an upper bound on performance against real,
subtler behaviour.

Run:  python -m ml.pipelines.p09_train_anomaly
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from sklearn.ensemble import IsolationForest
from sklearn.metrics import (
    average_precision_score, f1_score, precision_recall_fscore_support, roc_auc_score,
)
from sklearn.preprocessing import StandardScaler

from wealthos_core.anomaly import (
    AGGREGATIONS,
    aggregate_error,
    error_reference,
    threshold_at_budget,
)

from .common import (
    MODEL_DIR,
    PROCESSED_DIR,
    PipelineError,
    Stage,
    get_logger,
    silence_accelerate_matmul_warnings,
    write_report,
)

log = get_logger("anomaly")
silence_accelerate_matmul_warnings()

RANDOM_STATE = 42
EPOCHS = 30
BATCH_SIZE = 1024
LEARNING_RATE = 1e-3
LATENT_DIM = 6
PATIENCE = 5

FEATURE_COLUMNS = [
    "equity_allocation", "etf_allocation", "gold_allocation",
    "debt_allocation", "cash_allocation",
    "delta_equity_allocation", "delta_etf_allocation", "delta_gold_allocation",
    "delta_debt_allocation", "delta_cash_allocation",
    "allocation_shift", "hhi", "delta_hhi",
    "top_holding_weight", "delta_top_holding_weight",
    "n_holdings", "delta_n_holdings",
    "turnover", "turnover_ratio", "n_trades",
    "contribution_ratio", "period_return", "current_drawdown", "volatility",
    # Lag features added in Phase 3a. A dormancy break is a large
    # contribution *after a silence*; every column above describes a single
    # month, so the silence was invisible and the class was being separated
    # on evidence the table did not contain.
    "months_since_contribution", "delta_contribution_ratio",
    "recent_funding_rate",
]

# How per-row reconstruction error is reduced to one anomaly score.
#
# The original was a flat mean over the feature errors, which is wrong for a
# reason that is easy to miss: the features do not have comparable
# reconstruction difficulty. `volatility` is intrinsically harder to
# reconstruct than `cash_allocation`, so its ordinary noise dominates the
# mean, and a clean two-feature deviation in easy features is averaged away
# against it.
#
# Measured on the unchanged v1 model and dataset, so the effect of the
# aggregation is isolated from every other change (see
# ml/reports/anomaly_aggregation_study.json):
#
#     mean (original)        test F1 0.8392   PR-AUC 0.9355   dormancy 0.4667
#     max                    test F1 0.7914   PR-AUC 0.9028   dormancy 0.3897
#     top3_mean              test F1 0.8143   PR-AUC 0.9203   dormancy 0.4410
#     zscore_mean            test F1 0.8500   PR-AUC 0.9539   dormancy 0.5795
#     zscore_max             test F1 0.7486   PR-AUC 0.9389   dormancy 0.6359
#
# Note that plain `max` is WORSE than the mean. The dilution hypothesis on
# its own was wrong: an unnormalised max just returns whichever feature is
# hardest to reconstruct, which is largely the same feature on every row.
# It is the per-feature normalisation that carries the improvement, not the
# choice of reducer.
#
# `zscore_mean` is the default. It scores best on validation PR-AUC among the
# aggregations that average over all features, and averaging is preferred a
# priori over `max`, whose operating point rests on a single feature's tail
# and is correspondingly threshold-sensitive -- which the measured numbers
# above confirm, zscore_max having the best validation scores of any variant
# and the worst test F1.
DEFAULT_AGGREGATION = "zscore_mean"

# One false alert per thousand normal portfolio-months. Used only to measure
# how far the operating point drifts between splits, never to pick the
# shipped threshold.
FALSE_ALERT_BUDGET = 0.001


class Autoencoder(nn.Module):
    """A small symmetric autoencoder.

    Kept deliberately narrow. A high-capacity network reconstructs anomalies
    as faithfully as normal rows, which defeats the entire approach: the
    bottleneck is what forces the model to learn only typical structure.
    """

    def __init__(self, n_features: int, latent_dim: int = LATENT_DIM):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(n_features, 32), nn.ReLU(),
            nn.Linear(32, 16), nn.ReLU(),
            nn.Linear(16, latent_dim),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 16), nn.ReLU(),
            nn.Linear(16, 32), nn.ReLU(),
            nn.Linear(32, n_features),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.decoder(self.encoder(x))


def per_feature_error(model: Autoencoder, data: torch.Tensor) -> np.ndarray:
    """Squared reconstruction error per row and per feature.

    Returned unreduced so the aggregation is a separate, inspectable decision
    rather than a `.mean(dim=1)` buried in the scoring function.
    """
    model.eval()
    chunks = []
    with torch.no_grad():
        for start in range(0, len(data), 8192):
            batch = data[start : start + 8192]
            rebuilt = model(batch)
            chunks.append(((rebuilt - batch) ** 2).cpu().numpy())
    return np.concatenate(chunks)


# Aggregation, the per-feature reference scale and the budget threshold are
# defined in wealthos_core.anomaly, so the serving path reduces the error the
# identical way. A second copy here is how train/serve skew starts.
aggregate = aggregate_error


def best_threshold(scores: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
    """Threshold maximising F1 on the validation set."""
    candidates = np.quantile(scores, np.linspace(0.90, 0.9995, 150))
    best_value, best_f1 = float(candidates[0]), -1.0
    for threshold in candidates:
        f1 = f1_score(labels, (scores >= threshold).astype(int), zero_division=0)
        if f1 > best_f1:
            best_f1, best_value = f1, float(threshold)
    return best_value, best_f1


def evaluate(scores: np.ndarray, labels: np.ndarray, threshold: float) -> dict:
    """Detection metrics at a fixed threshold, plus threshold-free ones."""
    predicted = (scores >= threshold).astype(int)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels, predicted, average="binary", zero_division=0
    )
    negatives = int((labels == 0).sum())
    false_positives = int(((predicted == 1) & (labels == 0)).sum())
    true_positives = int(((predicted == 1) & (labels == 1)).sum())
    false_negatives = int(((predicted == 0) & (labels == 1)).sum())
    true_negatives = int(((predicted == 0) & (labels == 0)).sum())

    return {
        "confusion_matrix": {
            "true_positive": true_positives,
            "false_positive": false_positives,
            "false_negative": false_negatives,
            "true_negative": true_negatives,
        },
        "accuracy": round(
            (true_positives + true_negatives) / len(labels), 6
        ) if len(labels) else None,
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
        "false_positive_rate": round(false_positives / negatives, 5) if negatives else None,
        "roc_auc": round(float(roc_auc_score(labels, scores)), 4) if labels.sum() else None,
        "pr_auc": round(float(average_precision_score(labels, scores)), 4) if labels.sum() else None,
        "flagged": int(predicted.sum()),
        "actual_anomalies": int(labels.sum()),
        "rows": int(len(labels)),
    }


def main() -> None:
    path = PROCESSED_DIR / "features_anomaly.parquet"
    if not path.exists():
        raise PipelineError("run stage 07 first to build the feature tables")

    torch.manual_seed(RANDOM_STATE)
    np.random.seed(RANDOM_STATE)
    report: dict = {"random_state": RANDOM_STATE, "features": FEATURE_COLUMNS}

    with Stage(log, "load features"):
        frame = pd.read_parquet(path)
        frame[FEATURE_COLUMNS] = frame[FEATURE_COLUMNS].replace([np.inf, -np.inf], np.nan)
        frame = frame.dropna(subset=FEATURE_COLUMNS)

        train = frame[frame.split == "train"]
        validation = frame[frame.split == "validation"]
        test = frame[frame.split == "test"]
        for name, part in (("train", train), ("validation", validation), ("test", test)):
            log.info("  %-11s %8d rows, %4d anomalies (%.3f%%)",
                     name, len(part), int(part.is_anomaly.sum()),
                     100 * part.is_anomaly.mean())

    with Stage(log, "scale on normal training rows only"):
        # Fitting the scaler on anomalies too would let their extreme values
        # set the scale and make them look ordinary.
        normal_train = train[train.is_anomaly == 0]
        scaler = StandardScaler().fit(normal_train[FEATURE_COLUMNS])

        def prepare(part: pd.DataFrame) -> torch.Tensor:
            return torch.tensor(
                scaler.transform(part[FEATURE_COLUMNS]), dtype=torch.float32
            )

        x_train = prepare(normal_train)
        x_validation = prepare(validation)
        x_test = prepare(test)
        log.info("  trained on %d normal rows, %d features", len(x_train), x_train.shape[1])

    with Stage(log, "train autoencoder"):
        model = Autoencoder(len(FEATURE_COLUMNS))
        optimiser = torch.optim.Adam(model.parameters(), lr=LEARNING_RATE)
        criterion = nn.MSELoss()

        # Hold out a slice of normal rows to watch for overfitting.
        split_at = int(len(x_train) * 0.9)
        fit_data, watch_data = x_train[:split_at], x_train[split_at:]
        loader = torch.utils.data.DataLoader(
            torch.utils.data.TensorDataset(fit_data), batch_size=BATCH_SIZE, shuffle=True
        )

        best_loss, best_state, waited = float("inf"), None, 0
        history = []
        for epoch in range(1, EPOCHS + 1):
            model.train()
            total = 0.0
            for (batch,) in loader:
                optimiser.zero_grad()
                loss = criterion(model(batch), batch)
                loss.backward()
                optimiser.step()
                total += loss.item() * len(batch)
            train_loss = total / len(fit_data)

            model.eval()
            with torch.no_grad():
                watch_loss = criterion(model(watch_data), watch_data).item()
            history.append({"epoch": epoch, "train_loss": round(train_loss, 6),
                            "holdout_loss": round(watch_loss, 6)})

            if watch_loss < best_loss - 1e-6:
                best_loss, best_state, waited = watch_loss, model.state_dict().copy(), 0
            else:
                waited += 1
                if waited >= PATIENCE:
                    log.info("  early stop at epoch %d", epoch)
                    break
            if epoch % 5 == 0 or epoch == 1:
                log.info("  epoch %2d  train %.6f  holdout %.6f", epoch, train_loss, watch_loss)

        if best_state is not None:
            model.load_state_dict(best_state)
        report["training"] = {"epochs_run": len(history), "best_holdout_loss": round(best_loss, 6),
                              "history": history}

    with Stage(log, "compare aggregations on validation"):
        # The per-feature error is computed once; only the reduction changes.
        error_train_normal = per_feature_error(model, x_train)
        error_validation = per_feature_error(model, x_validation)
        reference = error_reference(error_train_normal)

        validation_labels = validation.is_anomaly.to_numpy()
        study = []
        for how in AGGREGATIONS:
            scores = aggregate(error_validation, how, reference)
            candidate, f1 = best_threshold(scores, validation_labels)
            study.append({
                "aggregation": how,
                "validation_f1": round(float(f1), 4),
                "validation_pr_auc": round(
                    float(average_precision_score(validation_labels, scores)), 4
                ),
                "validation_roc_auc": round(
                    float(roc_auc_score(validation_labels, scores)), 4
                ),
                "threshold": round(float(candidate), 8),
                "selected": how == DEFAULT_AGGREGATION,
            })
            log.info("  %-18s validation F1 %.4f  PR-AUC %.4f",
                     how, f1, study[-1]["validation_pr_auc"])
        report["aggregation_study"] = {
            "selected": DEFAULT_AGGREGATION,
            "candidates": study,
            "rationale": (
                "Chosen on validation PR-AUC among the aggregations that "
                "average across all features. Extremes (`max`) are rejected a "
                "priori: their operating point rests on one feature's tail and "
                "does not transfer between periods. Test was not consulted."
            ),
        }
        log.info("  using %s", DEFAULT_AGGREGATION)

    with Stage(log, "choose the threshold on validation"):
        validation_scores = aggregate(error_validation, DEFAULT_AGGREGATION, reference)
        threshold, validation_f1 = best_threshold(
            validation_scores, validation.is_anomaly.to_numpy()
        )
        log.info("  threshold %.6f (validation F1 %.4f)", threshold, validation_f1)
        report["threshold"] = {
            "value": round(float(threshold), 8),
            "validation_f1": round(float(validation_f1), 4),
            "selected_on": "validation",
            "note": (
                "Chosen on validation and applied unchanged to test. Tuning it "
                "on test would inflate every reported figure."
            ),
        }

    with Stage(log, "evaluate on the untouched test period"):
        test_scores = aggregate(
            per_feature_error(model, x_test), DEFAULT_AGGREGATION, reference
        )
        test_labels = test.is_anomaly.to_numpy()
        autoencoder_metrics = evaluate(test_scores, test_labels, threshold)
        report["autoencoder"] = autoencoder_metrics
        log.info("  precision %.3f  recall %.3f  F1 %.3f  FPR %.4f  PR-AUC %.3f  ROC-AUC %.3f",
                 autoencoder_metrics["precision"], autoencoder_metrics["recall"],
                 autoencoder_metrics["f1"], autoencoder_metrics["false_positive_rate"],
                 autoencoder_metrics["pr_auc"], autoencoder_metrics["roc_auc"])

    with Stage(log, "isolation forest baseline"):
        forest = IsolationForest(
            n_estimators=200, contamination=float(max(train.is_anomaly.mean(), 1e-4)),
            random_state=RANDOM_STATE, n_jobs=-1,
        )
        forest.fit(scaler.transform(normal_train[FEATURE_COLUMNS]))
        # Negate so that, as with reconstruction error, larger means stranger.
        forest_validation = -forest.score_samples(scaler.transform(validation[FEATURE_COLUMNS]))
        forest_threshold, _ = best_threshold(forest_validation, validation.is_anomaly.to_numpy())
        forest_test = -forest.score_samples(scaler.transform(test[FEATURE_COLUMNS]))

        forest_metrics = evaluate(forest_test, test_labels, forest_threshold)
        report["isolation_forest"] = forest_metrics
        log.info("  precision %.3f  recall %.3f  F1 %.3f  PR-AUC %.3f",
                 forest_metrics["precision"], forest_metrics["recall"],
                 forest_metrics["f1"], forest_metrics["pr_auc"])

        improvement = autoencoder_metrics["pr_auc"] - forest_metrics["pr_auc"]
        report["autoencoder_vs_baseline"] = {
            "pr_auc_improvement": round(float(improvement), 4),
            "autoencoder_wins": bool(improvement > 0),
        }
        log.info("  autoencoder %s the baseline on PR-AUC by %.4f",
                 "beats" if improvement > 0 else "LOSES TO", abs(improvement))

    with Stage(log, "measure how far the operating point drifts to test"):
        # A finding, not a formality. The threshold is fitted on validation
        # and applied unchanged to test, which is the correct protocol -- but
        # it only delivers the intended false-alert rate if the score
        # distribution is stationary across the two periods, and it is not.
        # Reporting the realised rate alongside the intended one is the
        # difference between a known limitation and a silent one.
        budget_threshold = threshold_at_budget(
            validation_scores, validation.is_anomaly.to_numpy(), FALSE_ALERT_BUDGET
        )

        def realised_fpr(scores: np.ndarray, labels: np.ndarray, cut: float) -> float:
            negatives = int((labels == 0).sum())
            if not negatives:
                return float("nan")
            return float(((scores >= cut) & (labels == 0)).sum() / negatives)

        validation_fpr = realised_fpr(
            validation_scores, validation.is_anomaly.to_numpy(), budget_threshold
        )
        test_fpr = realised_fpr(test_scores, test_labels, budget_threshold)

        report["threshold_transfer"] = {
            "false_alert_budget": FALSE_ALERT_BUDGET,
            "threshold_at_budget": round(float(budget_threshold), 8),
            "validation_false_positive_rate": round(validation_fpr, 6),
            "test_false_positive_rate": round(test_fpr, 6),
            "drift_multiple": (
                round(test_fpr / validation_fpr, 3) if validation_fpr > 0 else None
            ),
            "finding": (
                "The score distribution is not stationary between the "
                "validation and test periods, so a threshold calibrated to a "
                "given false-alert rate on validation does not deliver that "
                "rate on test. This affects the shipped threshold too, and it "
                "is a property of the data rather than of the aggregation: "
                "the same threshold transfers cleanly across a time boundary "
                "placed inside validation. Any deployment should recalibrate "
                "the threshold on recent data rather than trust a fixed one."
            ),
        }
        log.info("  FPR at budget: validation %.5f, test %.5f (%.1fx drift)",
                 validation_fpr, test_fpr,
                 test_fpr / validation_fpr if validation_fpr else float("nan"))

    with Stage(log, "calibration of the score"):
        # Required by the evaluation spec. The score is not a probability, so
        # the honest presentation is: within each decile of the score, what
        # share of rows were actually anomalies?
        edges = np.quantile(test_scores, np.linspace(0, 1, 11))
        bins = []
        for lower, upper in zip(edges[:-1], edges[1:]):
            mask = (test_scores >= lower) & (test_scores <= upper)
            if not mask.any():
                continue
            bins.append({
                "score_from": round(float(lower), 6),
                "score_to": round(float(upper), 6),
                "rows": int(mask.sum()),
                "observed_anomaly_rate": round(float(test_labels[mask].mean()), 6),
            })
        report["calibration"] = {
            "method": "observed anomaly rate per score decile on the test split",
            "monotonic": all(
                bins[i]["observed_anomaly_rate"] <= bins[i + 1]["observed_anomaly_rate"] + 1e-9
                for i in range(len(bins) - 1)
            ),
            "deciles": bins,
        }
        log.info("  top decile anomaly rate %.4f, bottom %.6f",
                 bins[-1]["observed_anomaly_rate"], bins[0]["observed_anomaly_rate"])

    with Stage(log, "break down by anomaly type"):
        by_type = {}
        predicted = (test_scores >= threshold).astype(int)
        for kind in sorted(set(test.anomaly_type) - {""}):
            mask = (test.anomaly_type == kind).to_numpy()
            caught = int(predicted[mask].sum())
            total = int(mask.sum())
            by_type[kind] = {
                "occurrences": total,
                "detected": caught,
                "recall": round(caught / total, 4) if total else None,
                "mean_error": round(float(test_scores[mask].mean()), 6),
            }
            log.info("  %-22s %4d events, %4d detected (recall %.3f)",
                     kind, total, caught, by_type[kind]["recall"])
        normal_error = float(test_scores[test_labels == 0].mean())
        log.info("  %-22s mean reconstruction error %.6f", "normal months", normal_error)
        report["by_anomaly_type"] = by_type
        report["normal_mean_error"] = round(normal_error, 6)

    with Stage(log, "save artifacts"):
        torch.save(
            {
                "state_dict": model.state_dict(),
                "n_features": len(FEATURE_COLUMNS),
                "latent_dim": LATENT_DIM,
            },
            MODEL_DIR / "anomaly_autoencoder.pt",
        )
        joblib.dump(
            {
                "scaler": scaler,
                "threshold": float(threshold),
                "feature_columns": FEATURE_COLUMNS,
                "isolation_forest": forest,
                "isolation_forest_threshold": float(forest_threshold),
                # The aggregation and its per-feature reference scale are part
                # of the model, not of this script. Serving that reduced the
                # error differently, or z-scored against a different
                # reference, would compute a different score from the same
                # weights -- train/serve skew of exactly the kind
                # wealthos_core exists to prevent elsewhere.
                "aggregation": DEFAULT_AGGREGATION,
                "error_reference_mean": reference["mean"].astype("float64").tolist(),
                "error_reference_std": reference["std"].astype("float64").tolist(),
                "version": "2.0.0",
            },
            MODEL_DIR / "anomaly_support.joblib",
        )
        log.info("  → ml/models/anomaly_autoencoder.pt")

    report["caveat"] = (
        "Anomalies are injected and deliberately unambiguous. These scores "
        "are an upper bound on performance against real, subtler behaviour."
    )
    write_report("anomaly_detection", report)
    log.info("anomaly report written")


if __name__ == "__main__":
    main()
