"""Sequence models for the swing deep-learning comparison (stage 18).

Each model reads the last ``seq_len`` sessions of a stock's ranked features
(the same features the LightGBM ranker sees on one day) and outputs a score
whose job is to rank stocks within a date. Kept small on purpose: about 60
stocks a day over 15 years is a modest dataset, and large networks only
memorise its noise.

Defined here, not inside the stage, so the API's model registry can import
the classes to load checkpoints.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import torch
from torch import nn

__all__ = ["RNNRanker", "TCNRanker", "PatchTransformerRanker", "build", "DEEP_MODELS",
           "tensorise", "normalise", "score_dates"]

DEEP_MODELS = ("lstm", "gru", "tcn", "transformer")


class RNNRanker(nn.Module):
    def __init__(self, n_features: int, hidden: int = 64, cell: str = "lstm", dropout: float = 0.2):
        super().__init__()
        rnn = nn.LSTM if cell == "lstm" else nn.GRU
        self.rnn = rnn(n_features, hidden, num_layers=1, batch_first=True)
        self.head = nn.Sequential(nn.Dropout(dropout), nn.Linear(hidden, 32), nn.ReLU(),
                                  nn.Dropout(dropout), nn.Linear(32, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(out[:, -1, :]).squeeze(-1)


class _CausalBlock(nn.Module):
    def __init__(self, c_in: int, c_out: int, kernel: int, dilation: int, dropout: float):
        super().__init__()
        self.pad = (kernel - 1) * dilation
        self.conv1 = nn.Conv1d(c_in, c_out, kernel, dilation=dilation)
        self.conv2 = nn.Conv1d(c_out, c_out, kernel, dilation=dilation)
        self.drop = nn.Dropout(dropout)
        self.skip = nn.Conv1d(c_in, c_out, 1) if c_in != c_out else nn.Identity()

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = nn.functional.pad(x, (self.pad, 0))
        y = self.drop(torch.relu(self.conv1(y)))
        y = nn.functional.pad(y, (self.pad, 0))
        y = self.drop(torch.relu(self.conv2(y)))
        return torch.relu(y + self.skip(x))


class TCNRanker(nn.Module):
    """Temporal convolutional network: dilated causal convolutions (1, 2, 4, 8)."""

    def __init__(self, n_features: int, channels: int = 32, levels: int = 4, kernel: int = 3,
                 dropout: float = 0.2):
        super().__init__()
        blocks, c_in = [], n_features
        for i in range(levels):
            blocks.append(_CausalBlock(c_in, channels, kernel, 2 ** i, dropout))
            c_in = channels
        self.net = nn.Sequential(*blocks)
        self.head = nn.Sequential(nn.Linear(channels, 32), nn.ReLU(), nn.Dropout(dropout), nn.Linear(32, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        y = self.net(x.transpose(1, 2))          # (B, C, L)
        return self.head(y[:, :, -1]).squeeze(-1)


class PatchTransformerRanker(nn.Module):
    """PatchTST-style encoder: the window is cut into patches that become tokens."""

    def __init__(self, n_features: int, seq_len: int = 60, patch: int = 10, d_model: int = 64,
                 heads: int = 4, layers: int = 2, dropout: float = 0.2):
        super().__init__()
        if seq_len % patch:
            raise ValueError("seq_len must be a multiple of patch")
        self.patch = patch
        self.n_patches = seq_len // patch
        self.embed = nn.Linear(patch * n_features, d_model)
        self.pos = nn.Parameter(torch.zeros(1, self.n_patches, d_model))
        layer = nn.TransformerEncoderLayer(d_model, heads, dim_feedforward=d_model * 2, dropout=dropout,
                                           batch_first=True, norm_first=True)
        self.encoder = nn.TransformerEncoder(layer, layers, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.LayerNorm(d_model), nn.Linear(d_model, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        b, length, f = x.shape
        tokens = x.reshape(b, self.n_patches, self.patch * f)
        z = self.encoder(self.embed(tokens) + self.pos)
        return self.head(z[:, -1, :]).squeeze(-1)


def build(name: str, n_features: int, seq_len: int = 60) -> nn.Module:
    if name in ("lstm", "gru"):
        return RNNRanker(n_features, cell=name)
    if name == "tcn":
        return TCNRanker(n_features)
    if name == "transformer":
        return PatchTransformerRanker(n_features, seq_len=seq_len)
    raise ValueError(f"unknown deep model {name!r}")


# --------------------------------------------------------------------------
# Inputs: shared by training (stage 18) and serving (signals service)
# --------------------------------------------------------------------------

def tensorise(features: pd.DataFrame, names: list[str]) -> tuple[np.ndarray, pd.DatetimeIndex, list[str], np.ndarray, np.ndarray]:
    """(date, symbol) feature rows to a (dates, symbols, features + 1) array.

    The extra last channel is 1 where the stock was eligible that day. Also
    returns each row's (t, s) position.
    """
    feats = features[names]
    dates = pd.DatetimeIndex(sorted(feats.index.get_level_values("date").unique()))
    symbols = sorted(feats.index.get_level_values("symbol").unique())
    t = dates.get_indexer(feats.index.get_level_values("date"))
    s = pd.Index(symbols).get_indexer(feats.index.get_level_values("symbol"))
    x = np.full((len(dates), len(symbols), len(names) + 1), np.nan, dtype=np.float32)
    x[t, s, :-1] = feats.to_numpy(np.float32)
    x[t, s, -1] = 1.0
    return x, dates, symbols, t, s


def normalise(raw: np.ndarray, n_stock: int, market_mean: np.ndarray, market_std: np.ndarray) -> np.ndarray:
    """Neutral ranks where a stock was not eligible; market features standardised."""
    x = raw.copy()
    stock = x[:, :, :n_stock]
    stock[np.isnan(stock)] = 0.5
    market = x[:, :, n_stock:-1]
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            day_vals = np.nanmean(market, axis=1)
    day_vals = pd.DataFrame(day_vals).ffill().fillna(0.0).to_numpy()
    market[:] = ((day_vals - np.asarray(market_mean)) / np.asarray(market_std))[:, None, :]
    flag = x[:, :, -1]
    flag[np.isnan(flag)] = 0.0
    return np.nan_to_num(x, nan=0.0)


def windows(x: torch.Tensor, t_idx: torch.Tensor, s_idx: torch.Tensor, seq_len: int) -> torch.Tensor:
    offs = torch.arange(-seq_len + 1, 1, device=x.device)
    tt = (t_idx[:, None] + offs).clamp(min=0)
    return x[tt, s_idx[:, None]]


def cpu_inference_mode() -> None:
    """Single-threaded CPU inference.

    On macOS, LightGBM and PyTorch each bring an OpenMP runtime; once LightGBM
    has run in a process, a multi-threaded torch CPU forward pass can
    deadlock. Inference here is a few thousand small windows, so one thread
    costs nothing and removes the hang.
    """
    torch.set_num_threads(1)


def score_dates(model: nn.Module, features: pd.DataFrame, names: list[str], n_stock: int,
                market_mean, market_std, seq_len: int, at: pd.DatetimeIndex | None = None) -> pd.Series:
    """Scores for every eligible (date, symbol) on ``at`` (default: all dates), on the CPU."""
    cpu_inference_mode()
    raw, dates, symbols, t, s = tensorise(features, names)
    x = torch.as_tensor(normalise(raw, n_stock, market_mean, market_std))
    keep = np.ones(len(t), dtype=bool) if at is None else np.isin(dates[t], at)
    ti, si = t[keep], s[keep]
    model.eval()
    out = []
    with torch.no_grad():
        for i in range(0, len(ti), 4096):
            out.append(model(windows(x, torch.as_tensor(ti[i:i + 4096]), torch.as_tensor(si[i:i + 4096]),
                                     seq_len)).float().numpy())
    values = np.concatenate(out) if out else np.empty(0)
    index = pd.MultiIndex.from_arrays([dates[ti], [symbols[j] for j in si]], names=["date", "symbol"])
    return pd.Series(values, index=index)
