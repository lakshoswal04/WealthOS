"""Contracts for the trained swing models and their reports.

Like ``test_models.py`` these load the real artifacts and skip when one has
not been trained. They check the feature contract, that the artifacts score
a real feature row, and that each report's deployment verdict agrees with the
numbers it reports. They deliberately do not assert that a model beats the
market: that is an empirical result for the reports to state, not a
property to test for.
"""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from ml.pipelines.common import MODEL_DIR, PROCESSED_DIR, REPORT_DIR
from wealthos_core import swing_features as sf


def _report(name: str) -> dict:
    path = REPORT_DIR / f"{name}.json"
    if not path.exists():
        pytest.skip(f"{name}.json not generated")
    return json.loads(path.read_text())


def _joblib(name: str):
    import joblib

    path = MODEL_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not trained")
    return joblib.load(path)


@pytest.fixture(scope="module")
def latest_rows() -> pd.DataFrame:
    path = PROCESSED_DIR / "features_swing.parquet"
    if not path.exists():
        pytest.skip("features_swing.parquet not built")
    f = pd.read_parquet(path)
    last = f.index.get_level_values("date").max()
    return f.xs(last, level="date")


def test_ranker_artifact_matches_the_feature_contract(latest_rows):
    bundle = _joblib("swing_ranker.joblib")
    assert bundle["features"] == sf.FEATURES
    assert bundle["feature_version"] == sf.FEATURE_VERSION
    assert bundle["deployed"] == "ensemble"
    scores = bundle["model"].predict(latest_rows[sf.FEATURES])
    assert np.isfinite(scores).all() and scores.std() > 0
    assert np.isfinite(bundle["regressor"].predict(latest_rows[sf.FEATURES])).all()


def test_quantile_artifact_gives_ordered_ranges(latest_rows):
    bundle = _joblib("swing_quantiles.joblib")
    preds = np.column_stack([bundle["models"][q].predict(latest_rows[bundle["features"]]) for q in bundle["quantiles"]])
    preds = np.sort(preds, axis=1)
    lo, hi = preds[:, 0] - bundle["conformal_adjustment"], preds[:, -1] + bundle["conformal_adjustment"]
    assert (hi > lo).all()
    assert bundle["nominal_coverage"] == 0.8


def test_ranker_gate_agrees_with_its_numbers():
    r = _report("swing_ranker")
    dep = r["deployed_model"]
    m = r["models"][dep]
    ew = r["benchmarks"]["equal_weight"]["backtest"]
    checks = r["deployment"]["checks"]
    assert checks["ic_positive"] == (m["signal"]["mean_ic"] > 0)
    assert checks["ic_beats_momentum"] == (m["signal"]["mean_ic"] > r["models"]["momentum_12_1"]["signal"]["mean_ic"])
    assert checks["cagr_beats_equal_weight_after_costs"] == (m["backtest"]["cagr"] > ew["cagr"])
    assert r["deployment"]["recommended"] == all(checks.values())
    # Every year from the first test year was scored out of sample.
    years = sorted(int(y) for y in m["signal"]["ic_by_year"])
    assert years[0] == 2013 and years == list(range(years[0], years[-1] + 1))


def test_ranker_was_tuned_before_the_test_years():
    r = _report("swing_ranker")
    assert "2011" in r["design"]["tuning"] and "2012" in r["design"]["tuning"]
    for fold in r["folds"]:
        assert pd.Timestamp(fold["train_end"]) < pd.Timestamp(fold["test_start"])
    assert r["n_trials_charged"] >= len(r["tuning_trials"])


def test_intervals_are_calibrated_out_of_sample():
    r = _report("swing_ranker")
    assert abs(r["intervals"]["oos_coverage_calibrated"] - 0.8) < 0.05


def test_volatility_models_beat_the_naive_forecast():
    r = _report("swing_volatility")
    naive = r["overall_common_rows"]["naive_rv22"]["qlike"]
    assert r["overall_common_rows"][r["serving_model"]]["qlike"] < naive


def test_regime_artifact_orders_states_by_volatility():
    bundle = _joblib("swing_regime.joblib")
    means = np.asarray(bundle["means"])
    assert bundle["state_names"] == ["calm", "normal", "stress"]
    assert list(np.argsort(means[:, 1])) == [0, 1, 2]
    trans = np.asarray(bundle["transmat"])
    assert np.allclose(trans.sum(axis=1), 1.0)


@pytest.mark.parametrize("name", ["lstm", "gru", "tcn", "transformer"])
def test_deep_checkpoints_load_and_score(name, latest_rows):
    import torch

    from ml.pipelines.deep_models import build, cpu_inference_mode

    cpu_inference_mode()
    path = MODEL_DIR / f"swing_{name}.pt"
    if not path.exists():
        pytest.skip(f"swing_{name}.pt not trained")
    ckpt = torch.load(path, map_location="cpu", weights_only=False)
    model = build(ckpt["name"], ckpt["n_features"], ckpt["seq_len"])
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    x = torch.rand(4, ckpt["seq_len"], ckpt["n_features"])
    with torch.no_grad():
        out = model(x)
    assert out.shape == (4,) and torch.isfinite(out).all()


def test_model_card_verdict_carries_the_disclaimer():
    card = _report("swing_model_card")
    assert "not investment advice" in card["verdict"]
    assert "survivorship" in card["verdict"].lower()
