"""Market-regime inference that never looks ahead.

A Gaussian hidden Markov model is fitted offline (``hmmlearn``). At inference
the usual ``predict`` and ``predict_proba`` calls run the forward-backward
algorithm: the state probability for a day in 2020 then depends on 2021. That
is fine for describing history and fatal for a backtest. This module runs the
**forward pass only**, so the probability for day ``t`` uses observations up
to ``t``, exactly what was knowable that evening.
"""

from __future__ import annotations

import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal

__all__ = ["filtered_probabilities", "gaussian_log_likelihoods"]


def gaussian_log_likelihoods(x: np.ndarray, means: np.ndarray, covars: np.ndarray) -> np.ndarray:
    """log p(x_t | state k) for every t and k. ``covars``: (K, d, d)."""
    x = np.atleast_2d(np.asarray(x, float))
    k = means.shape[0]
    out = np.empty((x.shape[0], k))
    for j in range(k):
        out[:, j] = multivariate_normal(mean=means[j], cov=covars[j], allow_singular=True).logpdf(x)
    return out


def filtered_probabilities(x: np.ndarray, startprob: np.ndarray, transmat: np.ndarray,
                           means: np.ndarray, covars: np.ndarray) -> np.ndarray:
    """P(state_t = k | x_1..x_t) for each t, shape (T, K). Forward pass in log space."""
    loglik = gaussian_log_likelihoods(x, means, covars)
    log_trans = np.log(np.clip(transmat, 1e-300, None))
    t_len, k = loglik.shape
    out = np.empty((t_len, k))
    log_alpha = np.log(np.clip(startprob, 1e-300, None)) + loglik[0]
    log_alpha -= logsumexp(log_alpha)
    out[0] = np.exp(log_alpha)
    for t in range(1, t_len):
        pred = logsumexp(log_alpha[:, None] + log_trans, axis=0)
        log_alpha = pred + loglik[t]
        log_alpha -= logsumexp(log_alpha)
        out[t] = np.exp(log_alpha)
    return out
