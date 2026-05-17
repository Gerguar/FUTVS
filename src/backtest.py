"""
Backtest rolling-origin (ventana expansiva) imitando operación real:

Para cada cutoff t:
    train  = todo lo anterior a t - (valid + test) days
    valid  = bloque [t - test_window - valid_window, t - test_window]  → calibración + early stopping
    test   = bloque [t - test_window, t]                                → evaluación
    cutoff t avanza step_days

En cada fold:
1) Re-ajustar Dixon-Coles con SOLO partidos hasta t_train_end.
2) Re-correr Elo desde cero hasta t_train_end.
3) Construir features sobre train+valid+test pero garantizando que Elo y DC
   visibles en la fila i son los previos a kickoff[i].
4) Entrenar XGBoost en train, calibrar isotonic en valid, evaluar en test.

Outputs:
- métricas por fold (log loss, Brier, accuracy, log loss del mercado como benchmark)
- agregados promedio y banda
- guardado en data/backtest_report.json
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd

from .config import BACKTEST, PATHS, LABEL_MAP
from .dixon_coles import fit as fit_dc
from .elo import EloState, replay
from .features import FeatureBuilder, feature_columns
from .xgb_model import fit_xgb, IsotonicMulticlassCalibrator
from .metrics import (multi_log_loss, multi_brier, accuracy_top1,
                      market_baseline_log_loss)


@dataclass
class FoldResult:
    fold_idx: int
    train_end: str
    valid_end: str
    test_end: str
    n_train: int
    n_valid: int
    n_test: int
    log_loss: float
    brier: float
    accuracy: float
    market_log_loss: float | None


def _label_idx(df: pd.DataFrame) -> np.ndarray:
    return df["label"].map(LABEL_MAP).astype(int).values


def _market_proba(df: pd.DataFrame) -> np.ndarray:
    cols = ["market_p_home", "market_p_draw", "market_p_away"]
    return df.reindex(columns=cols).to_numpy(dtype=float)


def run_backtest(matches: pd.DataFrame) -> dict:
    df = matches.dropna(subset=["home_goals", "away_goals"]).copy()
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    df = df.sort_values("kickoff_ts_utc").reset_index(drop=True)

    if len(df) < BACKTEST.min_train_matches + 100:
        raise ValueError(f"Pocos partidos para backtest serio: {len(df)}")

    t0 = df["kickoff_ts_utc"].iloc[BACKTEST.min_train_matches]
    t_end = df["kickoff_ts_utc"].max()
    step = pd.Timedelta(days=BACKTEST.step_days)
    vw = pd.Timedelta(days=BACKTEST.valid_window_days)
    tw = pd.Timedelta(days=BACKTEST.test_window_days)

    results: list[FoldResult] = []
    cutoffs = pd.date_range(t0, t_end - tw, freq=step, tz="UTC")
    fb = FeatureBuilder()

    for i, cut in enumerate(cutoffs):
        train_end = cut - vw - tw
        valid_end = cut - tw
        test_end = cut

        train_mask = df["kickoff_ts_utc"] < train_end
        valid_mask = (df["kickoff_ts_utc"] >= train_end) & (df["kickoff_ts_utc"] < valid_end)
        test_mask = (df["kickoff_ts_utc"] >= valid_end) & (df["kickoff_ts_utc"] < test_end)

        if train_mask.sum() < BACKTEST.min_train_matches:
            continue
        if valid_mask.sum() < 30 or test_mask.sum() < 30:
            continue

        train_raw = df[train_mask].copy()
        all_known = df[train_mask | valid_mask | test_mask].copy()

        dc_state = fit_dc(train_raw, asof_ts=train_end)
        elo_state = EloState()
        replay(train_raw, elo_state)

        full_feat = fb.build_training_table(all_known, dc_state, elo_state)
        full_feat = full_feat.dropna(subset=["label"])

        train_feat = full_feat[full_feat["kickoff_ts_utc"] < train_end]
        valid_feat = full_feat[(full_feat["kickoff_ts_utc"] >= train_end) &
                                (full_feat["kickoff_ts_utc"] < valid_end)]
        test_feat = full_feat[(full_feat["kickoff_ts_utc"] >= valid_end) &
                               (full_feat["kickoff_ts_utc"] < test_end)]

        if len(test_feat) == 0 or len(valid_feat) == 0:
            continue

        clf = fit_xgb(train_feat, valid_feat)
        valid_raw_proba = clf.predict_proba(valid_feat.reindex(columns=feature_columns()).astype(float))
        calibrator = IsotonicMulticlassCalibrator.fit(valid_raw_proba, _label_idx(valid_feat))

        test_X = test_feat.reindex(columns=feature_columns()).astype(float)
        test_raw = clf.predict_proba(test_X)
        test_proba = calibrator.transform(test_raw)
        y_test = _label_idx(test_feat)

        mkt_p = _market_proba(test_feat)
        mkt_ll = market_baseline_log_loss(mkt_p, y_test)

        fr = FoldResult(
            fold_idx=i,
            train_end=str(train_end),
            valid_end=str(valid_end),
            test_end=str(test_end),
            n_train=int(train_mask.sum()),
            n_valid=int(valid_mask.sum()),
            n_test=int(test_mask.sum()),
            log_loss=multi_log_loss(y_test, test_proba),
            brier=multi_brier(y_test, test_proba),
            accuracy=accuracy_top1(y_test, test_proba),
            market_log_loss=mkt_ll,
        )
        results.append(fr)
        print(f"[fold {i}] ll={fr.log_loss:.4f}  brier={fr.brier:.4f}  "
              f"acc={fr.accuracy:.3f}  mkt_ll={fr.market_log_loss}")

    summary = {
        "n_folds": len(results),
        "log_loss_mean": float(np.mean([r.log_loss for r in results])) if results else None,
        "log_loss_std": float(np.std([r.log_loss for r in results])) if results else None,
        "brier_mean": float(np.mean([r.brier for r in results])) if results else None,
        "accuracy_mean": float(np.mean([r.accuracy for r in results])) if results else None,
        "market_log_loss_mean": float(np.nanmean([r.market_log_loss for r in results
                                                   if r.market_log_loss is not None])) if results else None,
        "folds": [asdict(r) for r in results],
    }
    PATHS.backtest_report.write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    import pandas as pd
    matches = pd.read_parquet(PATHS.matches)
    s = run_backtest(matches)
    print(json.dumps({k: v for k, v in s.items() if k != "folds"}, indent=2))
