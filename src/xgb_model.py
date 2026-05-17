"""
Modelo XGBoost multiclase (H/D/A) + calibración isotónica multiclass.

La calibración no es opcional para boosting: el output crudo rankea bien pero
no produce probabilidades confiables. Aplicamos isotonic regression one-vs-rest
y renormalizamos.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.isotonic import IsotonicRegression
import joblib

from .config import XGB, PATHS, LABEL_MAP, LABEL_INV
from .features import feature_columns


def _prep_X(df: pd.DataFrame) -> pd.DataFrame:
    cols = feature_columns()
    X = df.reindex(columns=cols).astype(float)
    return X


def _prep_y(df: pd.DataFrame) -> np.ndarray:
    return df["label"].map(LABEL_MAP).astype(int).values


def fit_xgb(train_df: pd.DataFrame, valid_df: pd.DataFrame) -> XGBClassifier:
    X_tr = _prep_X(train_df)
    y_tr = _prep_y(train_df)
    X_va = _prep_X(valid_df)
    y_va = _prep_y(valid_df)

    clf = XGBClassifier(
        objective=XGB.objective,
        eval_metric=XGB.eval_metric,
        max_depth=XGB.max_depth,
        learning_rate=XGB.learning_rate,
        n_estimators=XGB.n_estimators,
        subsample=XGB.subsample,
        colsample_bytree=XGB.colsample_bytree,
        reg_lambda=XGB.reg_lambda,
        num_class=XGB.num_class,
        early_stopping_rounds=XGB.early_stopping_rounds,
        tree_method="hist",
        n_jobs=-1,
        verbosity=0,
    )
    clf.fit(X_tr, y_tr, eval_set=[(X_va, y_va)], verbose=False)
    return clf


@dataclass
class IsotonicMulticlassCalibrator:
    iso_h: IsotonicRegression
    iso_d: IsotonicRegression
    iso_a: IsotonicRegression

    @classmethod
    def fit(cls, proba: np.ndarray, y: np.ndarray) -> "IsotonicMulticlassCalibrator":
        def _iso(target_idx: int) -> IsotonicRegression:
            ir = IsotonicRegression(out_of_bounds="clip", y_min=1e-4, y_max=1 - 1e-4)
            ir.fit(proba[:, target_idx], (y == target_idx).astype(float))
            return ir
        return cls(_iso(0), _iso(1), _iso(2))

    def transform(self, proba: np.ndarray) -> np.ndarray:
        p_h = self.iso_h.transform(proba[:, 0])
        p_d = self.iso_d.transform(proba[:, 1])
        p_a = self.iso_a.transform(proba[:, 2])
        stacked = np.column_stack([p_h, p_d, p_a])
        stacked = np.clip(stacked, 1e-4, 1 - 1e-4)
        stacked /= stacked.sum(axis=1, keepdims=True)
        return stacked

    def save(self, path: Path) -> None:
        joblib.dump(self, path)

    @staticmethod
    def load(path: Path) -> "IsotonicMulticlassCalibrator":
        return joblib.load(path)


def predict_proba_calibrated(clf: XGBClassifier,
                             calibrator: IsotonicMulticlassCalibrator,
                             df: pd.DataFrame) -> np.ndarray:
    X = _prep_X(df)
    raw = clf.predict_proba(X)
    return calibrator.transform(raw)


def proba_to_records(proba: np.ndarray) -> list[dict]:
    out = []
    for row in proba:
        out.append({"p_home": float(row[0]), "p_draw": float(row[1]), "p_away": float(row[2])})
    return out


def save_artifacts(clf: XGBClassifier,
                   calibrator: IsotonicMulticlassCalibrator,
                   meta: dict) -> None:
    clf.save_model(PATHS.xgb_model)
    calibrator.save(PATHS.calibrator)
    PATHS.feature_meta.write_text(json.dumps(meta, indent=2))


def load_artifacts() -> tuple[XGBClassifier, IsotonicMulticlassCalibrator, dict]:
    clf = XGBClassifier()
    clf.load_model(PATHS.xgb_model)
    cal = IsotonicMulticlassCalibrator.load(PATHS.calibrator)
    meta = json.loads(PATHS.feature_meta.read_text())
    return clf, cal, meta
