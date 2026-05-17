"""
Entrenamiento final del modelo de producción.

Esquema:
    train  = partidos finalizados hasta hoy - (valid_window + test_window)
    valid  = bloque siguiente             → calibración + early stopping
    holdout= último bloque                 → reporte de métricas (no entra al fit)

Guarda artefactos en data/models/.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from .config import BACKTEST, PATHS, LABEL_MAP
from .dixon_coles import fit as fit_dc
from .elo import EloState, replay
from .features import FeatureBuilder, feature_columns
from .xgb_model import (fit_xgb, IsotonicMulticlassCalibrator,
                        save_artifacts)
from .metrics import (multi_log_loss, multi_brier, accuracy_top1,
                      market_baseline_log_loss, calibration_per_class)


def main() -> None:
    matches = pd.read_parquet(PATHS.matches)
    matches["kickoff_ts_utc"] = pd.to_datetime(matches["kickoff_ts_utc"], utc=True)
    finished = matches.dropna(subset=["home_goals", "away_goals"]).copy()
    finished = finished.sort_values("kickoff_ts_utc").reset_index(drop=True)

    now = pd.Timestamp.now(tz="UTC")
    test_end = now
    valid_end = now - pd.Timedelta(days=BACKTEST.test_window_days)
    train_end = valid_end - pd.Timedelta(days=BACKTEST.valid_window_days)

    train_raw = finished[finished["kickoff_ts_utc"] < train_end]
    if len(train_raw) < BACKTEST.min_train_matches:
        raise RuntimeError(f"Pocos partidos para entrenar: {len(train_raw)}")

    print(f"[train] {len(train_raw)} partidos hasta {train_end.date()}")
    dc_state = fit_dc(train_raw, asof_ts=train_end)
    dc_state.to_json()
    elo_state = EloState()
    replay(train_raw, elo_state)
    elo_state.to_json()

    fb = FeatureBuilder()
    full_feat = fb.build_training_table(finished, dc_state, elo_state)
    full_feat = full_feat.dropna(subset=["label"])

    train_feat = full_feat[full_feat["kickoff_ts_utc"] < train_end]
    valid_feat = full_feat[(full_feat["kickoff_ts_utc"] >= train_end) &
                            (full_feat["kickoff_ts_utc"] < valid_end)]
    holdout_feat = full_feat[(full_feat["kickoff_ts_utc"] >= valid_end) &
                              (full_feat["kickoff_ts_utc"] < test_end)]

    print(f"[train] n_train={len(train_feat)}  n_valid={len(valid_feat)}  n_holdout={len(holdout_feat)}")

    clf = fit_xgb(train_feat, valid_feat)

    X_valid = valid_feat.reindex(columns=feature_columns()).astype(float)
    valid_raw = clf.predict_proba(X_valid)
    y_valid = valid_feat["label"].map(LABEL_MAP).astype(int).values
    calibrator = IsotonicMulticlassCalibrator.fit(valid_raw, y_valid)

    holdout_metrics = {}
    if len(holdout_feat) > 0:
        X_ho = holdout_feat.reindex(columns=feature_columns()).astype(float)
        y_ho = holdout_feat["label"].map(LABEL_MAP).astype(int).values
        proba_ho = calibrator.transform(clf.predict_proba(X_ho))
        mkt_p = holdout_feat.reindex(columns=["market_p_home", "market_p_draw", "market_p_away"]).to_numpy(dtype=float)

        holdout_metrics = {
            "n": int(len(holdout_feat)),
            "log_loss": multi_log_loss(y_ho, proba_ho),
            "brier": multi_brier(y_ho, proba_ho),
            "accuracy": accuracy_top1(y_ho, proba_ho),
            "market_log_loss": market_baseline_log_loss(mkt_p, y_ho),
            "calibration": calibration_per_class(y_ho, proba_ho, n_bins=10),
        }
        print(f"[holdout] log_loss={holdout_metrics['log_loss']:.4f}  "
              f"brier={holdout_metrics['brier']:.4f}  "
              f"acc={holdout_metrics['accuracy']:.3f}  "
              f"mkt_ll={holdout_metrics['market_log_loss']}")

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_end": str(train_end),
        "valid_end": str(valid_end),
        "n_train": int(len(train_feat)),
        "n_valid": int(len(valid_feat)),
        "feature_columns": feature_columns(),
        "holdout_metrics": holdout_metrics,
    }
    save_artifacts(clf, calibrator, meta)
    print("[train] artefactos guardados")


if __name__ == "__main__":
    main()
