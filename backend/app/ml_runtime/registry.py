"""Model artifact loading.

Artifacts are loaded once per process and held in memory. If one is missing
the platform keeps working and the affected endpoint reports that the model
is unavailable, rather than the whole API failing to boot. The PRD requires
exactly this: a missing model file degrades a feature, it does not take the
system down.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from app.core.config import settings

log = logging.getLogger("wealthos.models")


class ModelRegistry:
    """Lazily loads and caches the trained model artifacts."""

    def __init__(self, model_dir: Path | None = None):
        self._dir = model_dir or settings.model_dir
        self._lock = threading.Lock()
        self._cache: dict[str, Any] = {}
        self._failures: dict[str, str] = {}

    # ---- loading ----

    def _load(self, key: str, loader) -> Any | None:
        if key in self._cache:
            return self._cache[key]
        if key in self._failures:
            return None

        with self._lock:
            if key in self._cache:
                return self._cache[key]
            try:
                artifact = loader()
            except Exception as exc:
                self._failures[key] = f"{type(exc).__name__}: {exc}"
                log.warning("model %s unavailable: %s", key, self._failures[key])
                return None
            self._cache[key] = artifact
            log.info("loaded model artifact: %s", key)
            return artifact

    # ---- artifacts ----

    def clustering(self) -> dict | None:
        def loader():
            import joblib
            return joblib.load(self._dir / "investor_clustering.joblib")
        return self._load("clustering", loader)

    def anomaly(self) -> dict | None:
        def loader():
            import joblib
            import torch

            from ml.pipelines.p09_train_anomaly import Autoencoder

            support = joblib.load(self._dir / "anomaly_support.joblib")
            checkpoint = torch.load(
                self._dir / "anomaly_autoencoder.pt", map_location="cpu", weights_only=False
            )
            model = Autoencoder(checkpoint["n_features"], checkpoint["latent_dim"])
            model.load_state_dict(checkpoint["state_dict"])
            model.eval()
            return {"model": model, **support}
        return self._load("anomaly", loader)

    def forecast(self, horizon: int = 12) -> dict | None:
        key = f"forecast_{horizon}m"

        def loader():
            import joblib
            import torch

            from ml.pipelines.p10_train_forecast import SequenceForecaster

            support = joblib.load(self._dir / f"forecast_{horizon}m.joblib")
            sequence_models = {}
            for cell in ("lstm", "gru"):
                path = self._dir / f"forecast_{cell}_{horizon}m.pt"
                if not path.exists():
                    continue
                checkpoint = torch.load(path, map_location="cpu", weights_only=False)
                model = SequenceForecaster(checkpoint["n_features"], cell=cell)
                model.load_state_dict(checkpoint["state_dict"])
                model.eval()
                sequence_models[cell] = model
            return {**support, "sequence_models": sequence_models}

        return self._load(key, loader)

    # ---- swing-trading models (ml/pipelines stages 15-18) ----

    def _joblib(self, key: str, filename: str) -> dict | None:
        def loader():
            import joblib
            return joblib.load(self._dir / filename)
        return self._load(key, loader)

    def swing_ranker(self) -> dict | None:
        return self._joblib("swing_ranker", "swing_ranker.joblib")

    def swing_quantiles(self) -> dict | None:
        return self._joblib("swing_quantiles", "swing_quantiles.joblib")

    def swing_vol(self) -> dict | None:
        return self._joblib("swing_vol", "swing_vol.joblib")

    def swing_regime(self) -> dict | None:
        return self._joblib("swing_regime", "swing_regime.joblib")

    def swing_deep(self, name: str) -> dict | None:
        """One sequence network (lstm, gru, tcn, transformer) with its input contract."""
        def loader():
            import torch

            from ml.pipelines.deep_models import build, cpu_inference_mode

            cpu_inference_mode()
            checkpoint = torch.load(self._dir / f"swing_{name}.pt", map_location="cpu", weights_only=False)
            model = build(checkpoint["name"], checkpoint["n_features"], checkpoint["seq_len"])
            model.load_state_dict(checkpoint["state_dict"])
            model.eval()
            return {**{k: v for k, v in checkpoint.items() if k != "state_dict"}, "model": model}
        return self._load(f"swing_{name}", loader)

    # ---- status ----

    def status(self) -> dict:
        """What is loaded and what is not, for the health endpoint."""
        available = {}
        for name, probe in (
            ("investor_clustering", self.clustering),
            ("anomaly_autoencoder", self.anomaly),
            ("forecast_12m", lambda: self.forecast(12)),
            ("swing_ranker", self.swing_ranker),
            ("swing_vol", self.swing_vol),
            ("swing_regime", self.swing_regime),
        ):
            available[name] = probe() is not None
        return {
            "available": available,
            "all_loaded": all(available.values()),
            "failures": dict(self._failures),
            "model_dir": str(self._dir),
        }

    def invalidate(self) -> None:
        with self._lock:
            self._cache.clear()
            self._failures.clear()


registry = ModelRegistry()
