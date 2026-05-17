"""
Entrenamiento del pipeline Dixon-Coles + calibrador isotónico.

Pasos:
1. Carga matches.parquet
2. Split temporal: train=hasta T-30d, calib=últimos 30d
3. Fit DC sobre train
4. Predice sobre calib → fit IsotonicMulticlassCalibrator
5. RE-fit DC sobre TODO el dataset (production)
6. Guarda dc_state.json + dc_calibrator.joblib

El calibrador corrige la tendencia conocida de DC a subestimar empates
y a ser sobre-confiado en los favoritos. Es el ajuste estándar del PDF.
"""
from __future__ import annotations
import argparse
import numpy as np
import pandas as pd
import joblib

from .config import PATHS, MODEL_DIR, LABEL_MAP
from .dixon_coles import fit as fit_dc, DixonColesState
from .xgb_model import IsotonicMulticlassCalibrator
from .metrics import multi_log_loss, multi_brier, accuracy_top1


CALIBRATOR_PATH = MODEL_DIR / "dc_calibrator.joblib"


def _label_idx(home: int, away: int) -> int:
    if home > away:
        return 0
    if home < away:
        return 2
    return 1


def _predict_dc(dc: DixonColesState, matches: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Devuelve (proba [n,3], y_idx [n])."""
    rows = []
    ys = []
    for _, m in matches.iterrows():
        h, a = m["home_team_id"], m["away_team_id"]
        if h not in dc.attack or a not in dc.attack:
            continue
        p = dc.probs_1x2(h, a, is_neutral=bool(m.get("is_neutral", False)))
        rows.append([p["H"], p["D"], p["A"]])
        ys.append(_label_idx(int(m["home_goals"]), int(m["away_goals"])))
    return np.array(rows), np.array(ys)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--calib-days", type=int, default=30,
                    help="Cuantos dias al final del dataset se usan SOLO para calibracion")
    args = ap.parse_args()

    df = pd.read_parquet(PATHS.matches)
    df = df.dropna(subset=["home_goals", "away_goals"]).copy()
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    df = df.sort_values("kickoff_ts_utc").reset_index(drop=True)

    cutoff = df["kickoff_ts_utc"].max() - pd.Timedelta(days=args.calib_days)
    train_df = df[df["kickoff_ts_utc"] < cutoff]
    calib_df = df[df["kickoff_ts_utc"] >= cutoff]

    print(f"[train_dc] total          : {len(df)}")
    print(f"[train_dc] train (DC fit) : {len(train_df)}  (hasta {cutoff.date()})")
    print(f"[train_dc] calib          : {len(calib_df)}")

    if len(train_df) < 500 or len(calib_df) < 50:
        print(f"[train_dc] insuficiente data, abortando")
        return

    # PASO 1: fit DC sobre train
    print("[train_dc] fitting DC en train...")
    dc_train = fit_dc(train_df, asof_ts=cutoff)

    # PASO 2: predict en calib
    print("[train_dc] prediciendo calib con DC-train...")
    proba_calib, y_calib = _predict_dc(dc_train, calib_df)
    print(f"[train_dc] calib predicho : {len(y_calib)} partidos")

    if len(y_calib) < 30:
        print("[train_dc] pocos partidos predichos, abortando calibrador")
        return

    ll_raw = multi_log_loss(y_calib, proba_calib)
    print(f"[train_dc] log_loss DC raw en calib  : {ll_raw:.4f}")

    # PASO 3: fit isotonic calibrator
    print("[train_dc] fit IsotonicMulticlassCalibrator...")
    cal = IsotonicMulticlassCalibrator.fit(proba_calib, y_calib)
    proba_cal = cal.transform(proba_calib)
    ll_cal = multi_log_loss(y_calib, proba_cal)
    br_cal = multi_brier(y_calib, proba_cal)
    acc_cal = accuracy_top1(y_calib, proba_cal)
    print(f"[train_dc] log_loss DC calibrado     : {ll_cal:.4f}  (mejora {ll_raw - ll_cal:+.4f})")
    print(f"[train_dc] brier DC calibrado        : {br_cal:.4f}")
    print(f"[train_dc] accuracy DC calibrado     : {acc_cal:.1%}")

    # PASO 4: re-fit DC sobre TODO el dataset (production)
    print("[train_dc] re-fit DC sobre todo el dataset (production)...")
    dc_full = fit_dc(df, asof_ts=df["kickoff_ts_utc"].max())

    # PASO 5: guardar artefactos
    dc_full.to_json(PATHS.dc_state)
    cal.save(CALIBRATOR_PATH)
    print(f"[train_dc] DC state -> {PATHS.dc_state}")
    print(f"[train_dc] calibrator -> {CALIBRATOR_PATH}")
    print("[train_dc] listo")


if __name__ == "__main__":
    main()
