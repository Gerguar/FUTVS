"""
Evaluación rápida del modelo Dixon-Coles (el que usa el writer on-demand).

Toma los últimos N días de partidos finalizados como TEST (datos que el modelo
no vio durante el entrenamiento) y reporta métricas de la calidad del pronóstico.

Métricas:
- Log loss (multiclase H/D/A) — métrica principal del PDF
- Brier score
- Accuracy
- Curva de calibración (¿una predicción de 60% se cumple ~60% de las veces?)

Baselines de comparación:
- Uniforme (1/3, 1/3, 1/3) — peor caso
- Local con ventaja media (46/27/27 — frecuencias históricas top 5 ligas)
- Bookmakers (odds del mercado, devigged) — referencia "alta"
- DC entrenado con TODA la historia disponible

Uso:
    python -m src.evaluate                  # default: últimos 30 días como test
    python -m src.evaluate --test-days 60
"""
from __future__ import annotations
import argparse
import json
from datetime import timedelta
import pandas as pd
import numpy as np

from .config import PATHS, LABEL_MAP
from .dixon_coles import fit as fit_dc
from .metrics import (multi_log_loss, multi_brier, accuracy_top1,
                      calibration_per_class, market_baseline_log_loss)
from .data_ingest import devig_odds
from .train_dc import CALIBRATOR_PATH
from .xgb_model import IsotonicMulticlassCalibrator


def label_to_idx(home: int, away: int) -> int:
    if home > away:
        return 0  # H
    if home < away:
        return 2  # A
    return 1      # D


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-days", type=int, default=30,
                    help="N dias al final del dataset que usamos como test")
    ap.add_argument("--calib-days", type=int, default=90,
                    help="Ventana previa al test para entrenar el calibrador HONESTO")
    ap.add_argument("--out", default=str(PATHS.backtest_report))
    args = ap.parse_args()

    df = pd.read_parquet(PATHS.matches)
    df = df.dropna(subset=["home_goals", "away_goals"]).copy()
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    df = df.sort_values("kickoff_ts_utc").reset_index(drop=True)

    cutoff = df["kickoff_ts_utc"].max() - pd.Timedelta(days=args.test_days)
    train_df = df[df["kickoff_ts_utc"] < cutoff].copy()
    test_df = df[df["kickoff_ts_utc"] >= cutoff].copy()

    print(f"[evaluate] dataset total      : {len(df):>6}")
    print(f"[evaluate] cutoff             : {cutoff.date()}")
    print(f"[evaluate] train (entrenamos) : {len(train_df):>6}")
    print(f"[evaluate] test  (evaluamos)  : {len(test_df):>6}")
    print()

    if len(train_df) < 500 or len(test_df) < 30:
        print(f"[evaluate] insuficientes partidos para evaluar")
        return

    # Entrenar DC SOLO con datos previos al cutoff (no leakage)
    print("[evaluate] entrenando Dixon-Coles con el train...")
    dc = fit_dc(train_df, asof_ts=cutoff)

    # Predecir todos los partidos de test
    print("[evaluate] prediciendo el bloque de test...")
    rows = []
    y_true = []
    skipped = 0
    for _, m in test_df.iterrows():
        h, a = m["home_team_id"], m["away_team_id"]
        if h not in dc.attack or a not in dc.attack:
            skipped += 1
            continue
        p = dc.probs_1x2(h, a, is_neutral=bool(m.get("is_neutral", False)))
        rows.append([p["H"], p["D"], p["A"]])
        y_true.append(label_to_idx(int(m["home_goals"]), int(m["away_goals"])))

    if not rows:
        print("[evaluate] ningun partido testeable")
        return

    proba = np.array(rows)
    y = np.array(y_true)
    print(f"[evaluate] partidos predichos : {len(y):>6}  (skipped {skipped} sin rating)")
    print()

    # Métricas del modelo DC raw
    ll = multi_log_loss(y, proba)
    br = multi_brier(y, proba)
    acc = accuracy_top1(y, proba)
    cal = calibration_per_class(y, proba, n_bins=8)

    # Métricas del modelo DC + isotonic calibration HONESTO (sin data leakage):
    # entrenamos un calibrador independiente con datos PREVIOS al test,
    # usando un DC ajustado a una fecha aun mas vieja. Asi el calibrador
    # nunca ve los partidos del test set.
    proba_cal = None
    ll_dccal = None; br_dccal = None; acc_dccal = None
    ll_baseline = None
    cutoff_calib = cutoff - pd.Timedelta(days=args.calib_days)
    train_for_cal = df[df["kickoff_ts_utc"] < cutoff_calib]
    calib_block = df[(df["kickoff_ts_utc"] >= cutoff_calib) &
                      (df["kickoff_ts_utc"] < cutoff)]
    print(f"[evaluate] calib block: {len(calib_block)} partidos en {args.calib_days} dias")
    if len(train_for_cal) >= 500 and len(calib_block) >= 30:
        try:
            print("[evaluate] (honesto) entrenando DC sobre train < T-2*test_days...")
            dc_for_cal = fit_dc(train_for_cal, asof_ts=cutoff_calib)
            print("[evaluate] (honesto) prediciendo bloque de calibracion...")
            proba_calb, y_calb = [], []
            for _, m in calib_block.iterrows():
                h, a = m["home_team_id"], m["away_team_id"]
                if h not in dc_for_cal.attack or a not in dc_for_cal.attack:
                    continue
                p = dc_for_cal.probs_1x2(h, a, is_neutral=bool(m.get("is_neutral", False)))
                proba_calb.append([p["H"], p["D"], p["A"]])
                y_calb.append(label_to_idx(int(m["home_goals"]), int(m["away_goals"])))
            if len(y_calb) >= 30:
                fresh_cal = IsotonicMulticlassCalibrator.fit(np.array(proba_calb), np.array(y_calb))
                # ahora SI: re-predecimos el test con dc_for_cal y aplicamos el calibrador
                test_proba_for_cal = []
                test_y_for_cal = []
                for _, m in test_df.iterrows():
                    h, a = m["home_team_id"], m["away_team_id"]
                    if h not in dc_for_cal.attack or a not in dc_for_cal.attack:
                        continue
                    p = dc_for_cal.probs_1x2(h, a, is_neutral=bool(m.get("is_neutral", False)))
                    test_proba_for_cal.append([p["H"], p["D"], p["A"]])
                    test_y_for_cal.append(label_to_idx(int(m["home_goals"]), int(m["away_goals"])))
                test_proba_for_cal = np.array(test_proba_for_cal)
                test_y_for_cal = np.array(test_y_for_cal)
                # Apples-to-apples: usamos el mismo DC (mas viejo) para ambas mediciones
                ll_baseline = multi_log_loss(test_y_for_cal, test_proba_for_cal)
                proba_cal = fresh_cal.transform(test_proba_for_cal)
                ll_dccal = multi_log_loss(test_y_for_cal, proba_cal)
                br_dccal = multi_brier(test_y_for_cal, proba_cal)
                acc_dccal = accuracy_top1(test_y_for_cal, proba_cal)
        except Exception as e:
            print(f"[evaluate] calibrador honesto fallo: {e}")

    # Baseline 1: uniforme 1/3
    uniform = np.full_like(proba, 1.0 / 3.0)
    ll_unif = multi_log_loss(y, uniform)
    acc_unif = accuracy_top1(y, uniform)

    # Baseline 2: frecuencias históricas (prior de las 5 ligas top + UCL)
    freq = train_df.apply(
        lambda r: label_to_idx(int(r["home_goals"]), int(r["away_goals"])), axis=1
    ).value_counts(normalize=True).to_dict()
    p_h = freq.get(0, 0.46); p_d = freq.get(1, 0.27); p_a = freq.get(2, 0.27)
    s = p_h + p_d + p_a
    p_h, p_d, p_a = p_h / s, p_d / s, p_a / s
    freq_proba = np.tile([p_h, p_d, p_a], (len(y), 1))
    ll_freq = multi_log_loss(y, freq_proba)
    acc_freq = accuracy_top1(y, freq_proba)

    # Baseline 3: mercado (cuando hay odds)
    mkt_rows = []
    mkt_idx = []
    for i, (_, m) in enumerate(test_df.iterrows()):
        if i >= len(rows) + skipped:
            break
    # Re-recorremos test_df con el mismo filtro
    j = 0
    for _, m in test_df.iterrows():
        h, a = m["home_team_id"], m["away_team_id"]
        if h not in dc.attack or a not in dc.attack:
            continue
        oh, od, oa = m.get("odds_home"), m.get("odds_draw"), m.get("odds_away")
        if pd.notna(oh) and pd.notna(od) and pd.notna(oa):
            ph, pd_, pa = devig_odds(float(oh), float(od), float(oa))
            mkt_rows.append([ph, pd_, pa])
            mkt_idx.append(j)
        j += 1
    ll_mkt = None
    acc_mkt = None
    mkt_n = 0
    if mkt_rows:
        mkt_proba = np.array(mkt_rows)
        mkt_y = y[mkt_idx]
        ll_mkt = multi_log_loss(mkt_y, mkt_proba)
        acc_mkt = accuracy_top1(mkt_y, mkt_proba)
        mkt_n = len(mkt_rows)

    # Distribución real para contexto
    real = pd.Series(y).value_counts(normalize=True).sort_index()

    # ====== A/B/C test: XGBoost SIN ratings vs XGBoost CON ratings vs DC ======
    # Entrenamos 2 XGBoost desde cero (con los mismos splits) — uno usando todas
    # las features incluyendo EAFC ratings, otro excluyendo solo las de rating.
    # Asi aislamos el efecto exacto de las EAFC ratings.
    ll_xgb_no_rat = None; br_xgb_no_rat = None; acc_xgb_no_rat = None; n_xgb_test = 0
    ll_xgb_rat = None;    br_xgb_rat = None;    acc_xgb_rat = None
    n_train_xgb = 0; n_features_no_rat = 0; n_features_rat = 0
    try:
        from .features import FeatureBuilder, feature_columns
        from .elo import EloState
        from xgboost import XGBClassifier
        from .config import XGB

        print("\n[evaluate] A/B/C test: entrenando XGBoost con y sin EAFC ratings...")
        fb_eval = FeatureBuilder()
        elo_dummy = EloState()  # build_training_table arma Elo internamente
        feat_all = fb_eval.build_training_table(df, dc, elo_dummy)
        feat_all = feat_all.dropna(subset=["label"])

        # Filtro de XGBoost a ultimas 2 temporadas (igual que train.py)
        xgb_filter = pd.Timestamp("2024-07-01", tz="UTC")
        feat_xgb = feat_all[feat_all["kickoff_ts_utc"] >= xgb_filter]

        # Splits: train hasta cutoff-60d, valid 60d, test 30d
        valid_cutoff = cutoff - pd.Timedelta(days=60)
        xgb_train = feat_xgb[feat_xgb["kickoff_ts_utc"] < valid_cutoff]
        xgb_valid = feat_xgb[(feat_xgb["kickoff_ts_utc"] >= valid_cutoff) &
                              (feat_xgb["kickoff_ts_utc"] < cutoff)]
        xgb_test = feat_xgb[feat_xgb["kickoff_ts_utc"] >= cutoff]

        n_train_xgb = len(xgb_train)
        n_xgb_test = len(xgb_test)
        print(f"[evaluate] XGBoost splits: train={n_train_xgb} valid={len(xgb_valid)} test={n_xgb_test}")

        if n_train_xgb >= 500 and len(xgb_valid) >= 30 and n_xgb_test >= 30:
            all_features = feature_columns()
            RATING_FEATURES = {
                "home_xi_rating", "away_xi_rating", "xi_rating_diff",
                "home_attack_rating", "home_defense_rating",
                "away_attack_rating", "away_defense_rating",
                "home_attack_vs_away_defense", "away_attack_vs_home_defense",
            }
            features_rat = all_features
            features_no_rat = [f for f in all_features if f not in RATING_FEATURES]
            n_features_rat = len(features_rat)
            n_features_no_rat = len(features_no_rat)

            def _fit_xgb_subset(train_df, valid_df, feats):
                X_tr = train_df[feats].astype(float)
                y_tr = train_df["label"].map(LABEL_MAP).astype(int).values
                X_va = valid_df[feats].astype(float)
                y_va = valid_df["label"].map(LABEL_MAP).astype(int).values
                clf = XGBClassifier(
                    objective=XGB.objective, eval_metric=XGB.eval_metric,
                    max_depth=XGB.max_depth, learning_rate=XGB.learning_rate,
                    n_estimators=XGB.n_estimators, subsample=XGB.subsample,
                    colsample_bytree=XGB.colsample_bytree, reg_lambda=XGB.reg_lambda,
                    num_class=XGB.num_class, early_stopping_rounds=XGB.early_stopping_rounds,
                    tree_method="hist", n_jobs=-1, verbosity=0,
                )
                clf.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
                return clf

            y_te = xgb_test["label"].map(LABEL_MAP).astype(int).values

            # A) XGBoost SIN EAFC ratings
            print(f"[evaluate] A) XGBoost SIN ratings ({n_features_no_rat} features)...")
            clf_no = _fit_xgb_subset(xgb_train, xgb_valid, features_no_rat)
            proba_no = clf_no.predict_proba(xgb_test[features_no_rat].astype(float))
            ll_xgb_no_rat = multi_log_loss(y_te, proba_no)
            br_xgb_no_rat = multi_brier(y_te, proba_no)
            acc_xgb_no_rat = accuracy_top1(y_te, proba_no)

            # B) XGBoost CON EAFC ratings
            print(f"[evaluate] B) XGBoost CON ratings ({n_features_rat} features)...")
            clf_yes = _fit_xgb_subset(xgb_train, xgb_valid, features_rat)
            proba_yes = clf_yes.predict_proba(xgb_test[features_rat].astype(float))
            ll_xgb_rat = multi_log_loss(y_te, proba_yes)
            br_xgb_rat = multi_brier(y_te, proba_yes)
            acc_xgb_rat = accuracy_top1(y_te, proba_yes)

            print(f"[evaluate] A/B test completado sobre {n_xgb_test} partidos test")
        else:
            print(f"[evaluate] insuficiente data para A/B test")
    except Exception as e:
        import traceback
        print(f"[evaluate] A/B test fallo: {type(e).__name__}: {e}")
        traceback.print_exc()

    # ===== REPORTE =====
    print("=" * 70)
    print("RESULTADOS")
    print("=" * 70)
    print()
    print(f"  Test set: {len(y)} partidos de los últimos {args.test_days} días")
    print(f"  Resultados reales: H={real.get(0,0):.1%}  D={real.get(1,0):.1%}  A={real.get(2,0):.1%}")
    print()
    print(f"{'Modelo':<35} {'LogLoss':>10} {'Brier':>10} {'Accuracy':>10}")
    print(f"{'-'*65}")
    print(f"{'Uniforme (1/3 cada uno)':<35} {ll_unif:>10.4f} {'':>10} {acc_unif:>10.1%}")
    print(f"{'Prior historico (frecuencias)':<35} {ll_freq:>10.4f} {'':>10} {acc_freq:>10.1%}")
    if ll_mkt is not None:
        print(f"{f'Mercado bookmakers (n={mkt_n})':<35} {ll_mkt:>10.4f} {'':>10} {acc_mkt:>10.1%}")
    print(f"{'Dixon-Coles crudo (full training)':<35} {ll:>10.4f} {br:>10.4f} {acc:>10.1%}")
    if ll_baseline is not None:
        print(f"{'  -DC crudo (training reducido)':<35} {ll_baseline:>10.4f}      ...      ... (referencia)")
    if ll_dccal is not None:
        delta = ll_dccal - ll_baseline if ll_baseline else None
        marker = (f"  <- gana {-delta:.4f} sobre su DC base" if delta and delta < 0
                  else f"  <- empeora {delta:.4f} sobre su DC base" if delta else "")
        print(f"{'DC + isotonic (calib HONESTO)':<35} {ll_dccal:>10.4f} {br_dccal:>10.4f} {acc_dccal:>10.1%}{marker}")
    print()
    print("--- A/B/C test (XGBoost entrenado desde cero en este eval) ---")
    if ll_xgb_no_rat is not None:
        delta_no = ll_xgb_no_rat - ll
        tag_no = (f"  vs DC: {delta_no:+.4f}")
        print(f"{'A) XGBoost SIN EAFC ratings':<35} {ll_xgb_no_rat:>10.4f} {br_xgb_no_rat:>10.4f} {acc_xgb_no_rat:>10.1%}{tag_no}")
    if ll_xgb_rat is not None:
        delta_yes = ll_xgb_rat - ll
        tag_yes = (f"  vs DC: {delta_yes:+.4f}")
        print(f"{'B) XGBoost CON EAFC ratings':<35} {ll_xgb_rat:>10.4f} {br_xgb_rat:>10.4f} {acc_xgb_rat:>10.1%}{tag_yes}")
    if ll_xgb_no_rat is not None and ll_xgb_rat is not None:
        delta_ab = ll_xgb_rat - ll_xgb_no_rat
        if delta_ab < -0.001:
            verdict = f"CON-ratings GANA por {-delta_ab:.4f}"
        elif delta_ab > 0.001:
            verdict = f"SIN-ratings GANA por {delta_ab:.4f}"
        else:
            verdict = "empate practico (diferencia < 0.001)"
        print(f"     ==> Efecto de EAFC ratings: {verdict}")
        print(f"     ==> Splits: train={n_train_xgb} test={n_xgb_test}  "
              f"features: sin={n_features_no_rat} con={n_features_rat}")
    print()

    print("Calibración por clase:")
    print("  (si predice 60%, deberia cumplirse ~60% de las veces)")
    for clase, data in cal.items():
        print(f"  {clase}:")
        for pred, true in zip(data["pred"], data["true"]):
            bar = "#" * int(true * 30)
            print(f"    pred={pred:.0%}  real={true:.0%}  {bar}")
    print()

    print("Interpretación:")
    print(f"  - Log loss menor = mejor. Random absoluto = 1.0986.")
    print(f"  - Bookmakers en top 5 ligas suelen estar en 0.95-0.98.")
    if ll < ll_unif and ll < ll_freq:
        print(f"  - Nuestro modelo ({ll:.4f}) le gana al random ({ll_unif:.4f}) y al prior historico ({ll_freq:.4f}). OK.")
    else:
        print(f"  - Nuestro modelo ({ll:.4f}) NO le gana a los baselines. Revisar.")
    if ll_mkt is not None:
        delta = ll - ll_mkt
        if delta < 0:
            print(f"  - Le gana al mercado por {-delta:.4f}. (raro y bueno)")
        elif delta < 0.03:
            print(f"  - Esta a {delta:.4f} del mercado. Excelente para un modelo sin odds.")
        else:
            print(f"  - El mercado le gana por {delta:.4f}. Esperable, el mercado es muy fuerte.")
    print()
    print(f"Accuracy de baseline aleatorio: 33%. Nuestro modelo: {acc:.1%}.")

    # Guardar reporte JSON
    report = {
        "cutoff": str(cutoff),
        "n_train": len(train_df),
        "n_test": len(y),
        "real_distribution": {"H": float(real.get(0,0)), "D": float(real.get(1,0)), "A": float(real.get(2,0))},
        "metrics": {
            "log_loss": float(ll),
            "brier": float(br),
            "accuracy": float(acc),
        },
        "baselines": {
            "uniform": {"log_loss": float(ll_unif), "accuracy": float(acc_unif)},
            "frequency_prior": {"log_loss": float(ll_freq), "accuracy": float(acc_freq)},
            "market": {"log_loss": float(ll_mkt) if ll_mkt else None,
                       "accuracy": float(acc_mkt) if acc_mkt else None,
                       "n": mkt_n},
        },
        "calibration": cal,
    }
    with open(args.out, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nReporte guardado en {args.out}")


if __name__ == "__main__":
    main()
