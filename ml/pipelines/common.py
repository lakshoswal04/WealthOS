"""Shared plumbing for the WealthOS data and model pipelines.

Every pipeline script is independently re-runnable and writes its output to a
known location under ``data/`` or ``ml/``, so a stage can be re-run without
replaying the ones before it.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
EXTERNAL_DIR = DATA_DIR / "external"
PROCESSED_DIR = DATA_DIR / "processed"
SYNTHETIC_DIR = DATA_DIR / "synthetic"
REFERENCE_DIR = DATA_DIR / "reference"

ML_DIR = PROJECT_ROOT / "ml"
MODEL_DIR = ML_DIR / "models"
REPORT_DIR = ML_DIR / "reports"
FIGURE_DIR = REPORT_DIR / "figures"

# Source data lives outside the repository because it is large and
# redistributable only under the original dataset licences.
KAGGLE_NSE_DIR = Path(
    os.environ.get("KAGGLE_NSE_DIR", Path.home() / "Downloads" / "Datasets")
)
BIG_SHARKS_CSV = Path(
    os.environ.get("BIG_SHARKS_CSV", Path.home() / "Downloads" / "Big_Sharks.csv")
)

for _directory in (
    RAW_DIR, EXTERNAL_DIR, PROCESSED_DIR, SYNTHETIC_DIR, REFERENCE_DIR,
    MODEL_DIR, REPORT_DIR, FIGURE_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)


# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------

def get_logger(name: str) -> logging.Logger:
    """A logger that prints a readable, timestamped line per pipeline step."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter("%(asctime)s  %(levelname)-7s %(name)s │ %(message)s", "%H:%M:%S")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger


class Stage:
    """Context manager that logs a pipeline stage and how long it took."""

    def __init__(self, logger: logging.Logger, label: str):
        self.logger = logger
        self.label = label

    def __enter__(self):
        self.started = time.time()
        self.logger.info("▶ %s", self.label)
        return self

    def __exit__(self, exc_type, exc, tb):
        elapsed = time.time() - self.started
        if exc_type is None:
            self.logger.info("✓ %s (%.1fs)", self.label, elapsed)
        else:
            self.logger.error("✗ %s failed after %.1fs", self.label, elapsed)
        return False


class PipelineError(RuntimeError):
    """Raised when a validation gate fails.

    Pipelines fail loudly rather than writing suspect data: a silent data
    defect propagates into every downstream metric and model.
    """


# --------------------------------------------------------------------------
# Column handling
# --------------------------------------------------------------------------

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names with underscores replacing spaces and symbols."""
    out = df.copy()
    names = out.columns.astype(str)
    names = names.str.strip().str.lower()
    names = names.str.replace(r"[^a-z0-9]+", "_", regex=True).str.strip("_")
    out.columns = names
    return out


def _simplify(text: str) -> str:
    """Reduce a label to letters and digits: 'Open Price' -> 'openprice'."""
    return re.sub(r"[^a-z0-9]", "", str(text).lower())


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Locate the column best matching any of ``candidates``.

    Kaggle dataset revisions rename columns between versions, so column
    identification is done by matching rather than by hard-coded names.
    """
    columns = list(df.columns)
    wanted = [_simplify(c) for c in candidates]

    exact = {_simplify(col): col for col in columns}
    for name in wanted:
        if name in exact:
            return exact[name]

    for col in columns:
        simple = _simplify(col)
        for name in wanted:
            if name and (name in simple or simple in name):
                return col
    return None


def read_tabular(path: Path) -> pd.DataFrame:
    """Read a csv/excel/parquet file, trying several text encodings."""
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix == ".csv":
        for encoding in ("utf-8", "utf-8-sig", "latin1"):
            try:
                return pd.read_csv(path, encoding=encoding)
            except UnicodeDecodeError:
                continue
        return pd.read_csv(path, encoding="latin1", engine="python")

    if suffix in (".xlsx", ".xls"):
        return pd.read_excel(path)
    if suffix == ".parquet":
        return pd.read_parquet(path)
    raise ValueError(f"unsupported file type: {path.suffix}")


def clean_numeric(series: pd.Series) -> pd.Series:
    """Parse a text column such as '1,234.5' or '12%' into floats."""
    text = series.astype(str)
    text = text.str.replace(",", "", regex=False).str.replace("%", "", regex=False).str.strip()
    return pd.to_numeric(text, errors="coerce")


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------

def load_universe() -> pd.DataFrame:
    """The MVP asset universe: symbol, asset class, sector and source mappings."""
    return pd.read_csv(REFERENCE_DIR / "universe.csv", keep_default_na=False, na_values=[""])


# --------------------------------------------------------------------------
# Artifacts
# --------------------------------------------------------------------------

def write_report(name: str, payload: dict) -> Path:
    """Persist a stage's metrics or validation results as JSON."""
    path = REPORT_DIR / f"{name}.json"
    payload = {"generated_at": datetime.now(timezone.utc).isoformat(), **payload}
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


def describe_frame(df: pd.DataFrame, label: str = "frame") -> str:
    """One-line shape and date-range summary for logging."""
    parts = [f"{label}: {len(df):,} rows x {df.shape[1]} cols"]
    if "date" in df.columns and len(df):
        parts.append(f"{df['date'].min():%Y-%m-%d} → {df['date'].max():%Y-%m-%d}")
    if "symbol" in df.columns:
        parts.append(f"{df['symbol'].nunique():,} symbols")
    return "  │  ".join(parts)

# --------------------------------------------------------------------------
# Numerical warnings
# --------------------------------------------------------------------------

def silence_accelerate_matmul_warnings() -> None:
    """Suppress a known false positive from numpy on Apple's Accelerate BLAS.

    numpy 2.x on macOS Accelerate raises "divide by zero / overflow / invalid
    value encountered in matmul" on matrix products whose inputs and outputs
    are entirely finite. Accelerate leaves FPU exception flags set and numpy
    reports them, but the arithmetic is correct: a clean 9743x15 @ 15x2
    product of random normals triggers all three warnings and still returns
    finite values.

    Left alone, these appear throughout scikit-learn's KMeans and PCA output
    and look exactly like a data-quality failure, which costs real time to
    chase. Only this precise message on this precise operation is filtered,
    so genuine overflows elsewhere still surface.
    """
    for message in (
        "divide by zero encountered in matmul",
        "overflow encountered in matmul",
        "invalid value encountered in matmul",
    ):
        warnings.filterwarnings("ignore", message=message, category=RuntimeWarning)
