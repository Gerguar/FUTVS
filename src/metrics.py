"""
Métricas para 1X2 probabilístico.

Principal: log loss (multiclass).
Complementarias: Brier score multiclass, accuracy, calibration curve.
"""
from __future__ import annotations
import numpy as np
from sklearn.metrics import log_loss, accuracy_score
from sklearn.calibration import calibration_curve


def multi_log_loss(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    return float(log_loss(y_true_idx, np.clip(proba, 1e-12, 1 - 1e-12), labels=[0, 1, 2]))


def multi_brier(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    y_oh = np.eye(3)[y_true_idx]
    return float(np.mean(np.sum((proba - y_oh) ** 2, axis=1)))


def accuracy_top1(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    return float(accuracy_score(y_true_idx, np.argmax(proba, axis=1)))


def calibration_per_class(y_true_idx: np.ndarray, proba: np.ndarray,
                          n_bins: int = 10) -> dict:
    out = {}
    for k, name in enumerate(["home", "draw", "away"]):
        y_bin = (y_true_idx == k).astype(int)
        true_p, pred_p = calibration_curve(y_bin, proba[:, k],
                                           n_bins=n_bins, strategy="quantile")
        out[name] = {"pred": pred_p.tolist(), "true": true_p.tolist()}
    return out


def market_baseline_log_loss(market_proba: np.ndarray, y_true_idx: np.ndarray,
                             mask: np.ndarray | None = None) -> float | None:
    if mask is None:
        mask = ~np.isnan(market_proba).any(axis=1)
    if mask.sum() == 0:
        return None
    return multi_log_loss(y_true_idx[mask], market_proba[mask])
