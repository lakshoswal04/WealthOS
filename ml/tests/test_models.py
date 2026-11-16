"""Model artifact tests.

These check that each trained artifact loads, accepts the feature contract
it was fitted on, returns the right shape, and that its recorded evaluation
clears the bar the project claims. A model whose metrics silently regress
below its baseline should fail the build, not appear in a report.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml.pipelines.common import MODEL_DIR, PROCESSED_DIR, REPORT_DIR


def _report(name: str) -> dict:
    path = REPORT_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"{name} report not present; run the training pipelines")
    return json.loads(path.read_text())


# --------------------------------------------------------------------------
# Clustering
# --------------------------------------------------------------------------

class TestClustering:
    @pytest.fixture(scope="class")
    def artifact(self):
        path = MODEL_DIR / "investor_clustering.joblib"
        if not path.exists():
            pytest.skip("clustering artifact not present")
        import joblib
        return joblib.load(path)

    def test_artifact_carries_everything_inference_needs(self, artifact):
        assert {"scaler", "kmeans", "feature_columns", "cluster_profiles", "k"} <= set(artifact)
        assert len(artifact["cluster_profiles"]) == artifact["k"]

    def test_scaler_and_model_agree_on_the_feature_count(self, artifact):
        n_features = len(artifact["feature_columns"])
        assert artifact["scaler"].n_features_in_ == n_features
        assert artifact["kmeans"].cluster_centers_.shape == (artifact["k"], n_features)

    def test_prediction_returns_one_valid_cluster(self, artifact):
        columns = artifact["feature_columns"]
        row = pd.DataFrame([[0.0] * len(columns)], columns=columns)
        predicted = artifact["kmeans"].predict(artifact["scaler"].transform(row))

        assert predicted.shape == (1,)
        assert 0 <= int(predicted[0]) < artifact["k"]

    def test_every_cluster_has_a_distinct_descriptive_name(self, artifact):
        names = [p["name"] for p in artifact["cluster_profiles"]]
        assert len(set(names)) == len(names), f"duplicate cluster names: {names}"
        assert all(name and not name[0].isdigit() for name in names)

    def test_clusters_recover_the_true_archetypes(self):
        # The measure that distinguishes "tight clusters" from "the right
        # clusters". Only measurable because the cohort is synthetic.
        recovery = _report("clustering")["archetype_recovery"]
        assert recovery["adjusted_rand_index"] > 0.5, (
            "clustering no longer recovers the generating archetypes"
        )

    def test_clustering_is_stable_under_resampling(self):
        stability = _report("clustering")["stability"]
        assert stability["mean_ari"] > 0.7, (
            "the partition is not reproducible across resamples"
        )


# --------------------------------------------------------------------------
# Anomaly detection
# --------------------------------------------------------------------------

class TestAnomalyDetector:
    @pytest.fixture(scope="class")
    def artifact(self):
        import joblib
        import torch

        support_path = MODEL_DIR / "anomaly_support.joblib"
        model_path = MODEL_DIR / "anomaly_autoencoder.pt"
        if not (support_path.exists() and model_path.exists()):
            pytest.skip("anomaly artifacts not present")

        from ml.pipelines.p09_train_anomaly import Autoencoder

        support = joblib.load(support_path)
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=False)
        model = Autoencoder(checkpoint["n_features"], checkpoint["latent_dim"])
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()
        return {"model": model, **support, "n_features": checkpoint["n_features"]}

    def test_feature_contract_matches_the_network(self, artifact):
        assert artifact["n_features"] == len(artifact["feature_columns"])
        assert artifact["scaler"].n_features_in_ == artifact["n_features"]

    def test_reconstruction_returns_one_error_per_row(self, artifact):
        import torch

        batch = torch.zeros(5, artifact["n_features"])
        with torch.no_grad():
            rebuilt = artifact["model"](batch)
            errors = ((rebuilt - batch) ** 2).mean(dim=1)

        assert rebuilt.shape == batch.shape
        assert errors.shape == (5,)
        assert torch.isfinite(errors).all()

    def test_threshold_is_a_positive_number(self, artifact):
        assert artifact["threshold"] > 0

    def test_detector_beats_the_shallow_baseline(self):
        # A deep model that cannot beat an Isolation Forest has not earned
        # its place in the system.
        report = _report("anomaly_detection")
        assert report["autoencoder"]["pr_auc"] > report["isolation_forest"]["pr_auc"]

    def test_detection_quality_holds(self):
        metrics = _report("anomaly_detection")["autoencoder"]
        assert metrics["pr_auc"] > 0.7
        assert metrics["recall"] > 0.6
        # A detector that flags everything is useless however high its recall.
        assert metrics["false_positive_rate"] < 0.05

    def test_the_known_weak_case_is_still_reported(self):
        # Dormancy breaks are genuinely hard to separate from lumpy saving.
        # The point is that the report says so rather than hiding it.
        by_type = _report("anomaly_detection")["by_anomaly_type"]
        assert set(by_type) >= {
            "allocation_shock", "concentration_spike", "turnover_spike",
            "panic_sell", "dormancy_break",
        }
        assert all(0.0 <= entry["recall"] <= 1.0 for entry in by_type.values())


# --------------------------------------------------------------------------
# Forecasting
# --------------------------------------------------------------------------

class TestForecasting:
    @pytest.fixture(scope="class")
    def artifact(self):
        path = MODEL_DIR / "forecast_12m.joblib"
        if not path.exists():
            pytest.skip("forecast artifact not present")
        import joblib
        return joblib.load(path)

    def test_the_xgboost_slot_holds_an_xgboost_model(self, artifact):
        # A variable-shadowing bug once stored the GRU under this key, so the
        # type is asserted rather than assumed.
        import xgboost as xgb
        assert isinstance(artifact["xgboost"], xgb.XGBRegressor)

    def test_artifact_carries_both_feature_contracts(self, artifact):
        assert artifact["tabular_features"]
        assert artifact["sequence_features"]
        assert artifact["sequence_length"] > 0
        assert artifact["horizon"] == 12

    def test_tabular_prediction_returns_one_finite_value(self, artifact):
        columns = artifact["tabular_features"]
        row = pd.DataFrame([artifact["tabular_medians"]])[columns]
        predicted = artifact["xgboost"].predict(row.to_numpy())

        assert predicted.shape == (1,)
        assert np.isfinite(predicted[0])

    @pytest.mark.parametrize("cell", ["lstm", "gru"])
    def test_sequence_models_accept_a_window_and_return_a_scalar(self, cell):
        import torch

        path = MODEL_DIR / f"forecast_{cell}_12m.pt"
        if not path.exists():
            pytest.skip(f"{cell} artifact not present")

        from ml.pipelines.p10_train_forecast import SequenceForecaster

        checkpoint = torch.load(path, map_location="cpu", weights_only=False)
        model = SequenceForecaster(checkpoint["n_features"], cell=checkpoint["cell"])
        model.load_state_dict(checkpoint["state_dict"])
        model.eval()

        window = torch.zeros(1, 24, checkpoint["n_features"])
        with torch.no_grad():
            predicted = model(window)

        assert predicted.shape == (1,)
        assert torch.isfinite(predicted).all()

    def test_every_horizon_was_trained_and_evaluated(self):
        for horizon in (1, 3, 6, 12):
            report = _report(f"forecast_{horizon}m")
            assert report["horizon_months"] == horizon
            assert "baseline_mean_drift" in report["results"]

    def test_the_honest_baseline_is_present_and_used(self):
        # Skill against a zero-return baseline flatters every model, because
        # markets drifted up. The mean-drift reference is what the report
        # leads with, so it must exist.
        report = _report("forecast_12m")
        assert "baseline_mean_drift" in report["results"]
        assert "skill_vs_mean_baseline" in report["results"]["xgboost"]
        assert "skill_vs_mean_baseline" in report["best_model"]

    def test_the_best_model_actually_beats_the_baseline(self):
        best = _report("forecast_12m")["best_model"]
        assert best["skill_vs_mean_baseline"] > 0, (
            "no model adds anything over the best constant forecast"
        )

    def test_scale_inflated_and_honest_metrics_are_both_reported(self):
        # Reporting only the rupee-value R-squared would overstate the result
        # by an order of magnitude.
        results = _report("forecast_12m")["results"]["xgboost"]
        assert results["value"]["r2"] > 0.9       # scale-dominated, as expected
        assert results["growth"]["r2"] < 0.9      # the real measure, far lower
        assert {"mae", "rmse", "mape_pct", "r2"} <= set(results["growth"])


# --------------------------------------------------------------------------
# Copilot grounding
# --------------------------------------------------------------------------

def test_copilot_groundedness_was_measured_and_is_high():
    summary = _report("copilot_groundedness")["summary"]
    assert summary["numbers_checked"] > 50
    assert summary["overall_groundedness_rate"] >= 0.95, (
        "the Copilot stated figures the backend never produced"
    )


# --------------------------------------------------------------------------
# Feature tables
# --------------------------------------------------------------------------

def test_feature_splits_do_not_overlap_in_time():
    path = PROCESSED_DIR / "features_forecast.parquet"
    if not path.exists():
        pytest.skip("feature tables not built")

    frame = pd.read_parquet(path, columns=["date", "split"])
    ranges = frame.groupby("split")["date"].agg(["min", "max"])

    assert ranges.loc["train", "max"] < ranges.loc["validation", "min"]
    assert ranges.loc["validation", "max"] < ranges.loc["test", "min"]


def test_no_target_column_is_exposed_as_a_feature():
    path = PROCESSED_DIR / "features_forecast.parquet"
    if not path.exists():
        pytest.skip("feature tables not built")

    columns = pd.read_parquet(path).columns
    features = [
        c for c in columns
        if not c.startswith(("future_", "excess_log_growth_", "baseline_"))
    ]
    assert not [c for c in features if "future" in c.lower()]
