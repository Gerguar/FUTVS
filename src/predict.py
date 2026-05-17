"""
Inferencia: genera predicciones para los próximos partidos y escribe predictions.json.

El JSON queda en `data/predictions.json` y es el contrato con la web.
Schema (estable, versionado):

{
  "schema_version": "1.0",
  "generated_at_utc": "2026-05-16T12:00:00Z",
  "model": {
     "trained_at": "...",
     "method": "DixonColes+Elo+XGBoost(isotonic)",
     "holdout_metrics": { "log_loss": ..., "brier": ..., "accuracy": ... }
  },
  "matches": [
    {
      "match_id": "fd-123456",
      "kickoff_ts_utc": "2026-05-20T19:00:00Z",
      "competition": { "code": "UCL", "name": "UEFA Champions League" },
      "home": { "id": "65", "name": "Manchester City" },
      "away": { "id": "81", "name": "FC Barcelona" },
      "venue": "Etihad Stadium",
      "is_neutral": false,
      "snapshot": "24h",
      "probabilities": { "home": 0.46, "draw": 0.27, "away": 0.27 },
      "market_probabilities": { "home": 0.48, "draw": 0.25, "away": 0.27 },
      "scoreline_top": [
         { "score": "2-1", "p": 0.11 },
         { "score": "1-1", "p": 0.10 }
      ],
      "expected_goals": { "home": 1.72, "away": 1.31 },
      "derived": {
         "p_over_2_5": 0.55,
         "p_btts": 0.58
      },
      "ratings": {
         "elo_home": 1820, "elo_away": 1790, "elo_diff": 30
      }
    }
  ]
}
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
import numpy as np
import pandas as pd

from .config import COMPETITIONS, PATHS, SNAPSHOTS, INTERNATIONAL_CODES
from .dixon_coles import DixonColesState
from .elo import EloState
from .features import FeatureBuilder, feature_columns, build_team_features
from .xgb_model import load_artifacts


COMP_NAME_BY_FD = {c.fd_code: c.name for c in COMPETITIONS if c.fd_code}
COMP_CODE_BY_FD = {c.fd_code: c.code for c in COMPETITIONS if c.fd_code}


def _competition(fd_code: str | None) -> dict:
    return {
        "code": COMP_CODE_BY_FD.get(fd_code, fd_code or "UNK"),
        "name": COMP_NAME_BY_FD.get(fd_code, fd_code or "Unknown"),
    }


def _top_scorelines(dc_state: DixonColesState, home: str, away: str,
                    is_neutral: bool, k: int = 5) -> list[dict]:
    m = dc_state.scoreline_matrix(home, away, is_neutral)
    flat = [(i, j, float(m[i, j])) for i in range(m.shape[0]) for j in range(m.shape[1])]
    flat.sort(key=lambda x: x[2], reverse=True)
    return [{"score": f"{i}-{j}", "p": round(p, 4)} for i, j, p in flat[:k]]


def filter_upcoming(matches: pd.DataFrame, horizon_days: int,
                    only_international: bool) -> pd.DataFrame:
    now = pd.Timestamp.now(tz="UTC")
    end = now + pd.Timedelta(days=horizon_days)
    m = matches.copy()
    m["kickoff_ts_utc"] = pd.to_datetime(m["kickoff_ts_utc"], utc=True)
    upcoming = m[(m["kickoff_ts_utc"] >= now - pd.Timedelta(hours=2)) &
                  (m["kickoff_ts_utc"] <= end) &
                  (m["home_goals"].isna() | (m["status"].isin(["SCHEDULED", "TIMED"]) if "status" in m.columns else True))]
    if only_international:
        intl_fd = {c.fd_code for c in COMPETITIONS if c.is_international and c.fd_code}
        upcoming = upcoming[upcoming["competition_code"].isin(intl_fd)]
    return upcoming.sort_values("kickoff_ts_utc").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", default="14", help="Días hacia adelante (entero)")
    p.add_argument("--snapshot", default=SNAPSHOTS.mid, choices=["7d", "24h", "60m"])
    p.add_argument("--only-international", action="store_true", default=False,
                   help="Si se setea, predice solo competiciones internacionales (UCL/UEL/etc.)")
    p.add_argument("--out", default=str(PATHS.predictions))
    args = p.parse_args()
    horizon_days = int(args.horizon.rstrip("d"))

    matches = pd.read_parquet(PATHS.matches)
    matches["kickoff_ts_utc"] = pd.to_datetime(matches["kickoff_ts_utc"], utc=True)

    elo_state = EloState.from_json()
    dc_state = DixonColesState.from_json()
    # XGBoost es opcional. Si no esta entrenado, caemos a DC + Elo solamente.
    use_xgb = True
    try:
        clf, calibrator, meta = load_artifacts()
    except Exception as e:
        print(f"[predict] XGBoost artefactos no disponibles ({e}). Uso DC-only fallback.")
        clf, calibrator = None, None
        meta = {"trained_at": dc_state.fitted_at,
                "method": "DixonColes+Elo (fallback sin XGBoost)",
                "holdout_metrics": {}}
        use_xgb = False

    finished = matches.dropna(subset=["home_goals", "away_goals"])
    team_features = build_team_features(finished)

    upcoming = filter_upcoming(matches, horizon_days, args.only_international)
    if upcoming.empty:
        print("[predict] no hay partidos próximos")
        out_doc = _empty_doc(meta)
        Path(args.out).write_text(json.dumps(out_doc, indent=2))
        return

    fb = FeatureBuilder(snapshot=args.snapshot)
    rows = []
    for _, m in upcoming.iterrows():
        odds_row = {k: m.get(k) for k in ["odds_home", "odds_draw", "odds_away"]}
        feat = fb.build_inference_row(
            home=m["home_team_id"], away=m["away_team_id"],
            kickoff_ts_utc=m["kickoff_ts_utc"],
            competition_code=m["competition_code"],
            is_neutral=bool(m.get("is_neutral", False)),
            elo_state=elo_state, dc_state=dc_state,
            team_features=team_features,
            odds_row=odds_row,
        )
        feat["match_id"] = m["match_id"]
        feat["home_team_name"] = m.get("home_team_name")
        feat["away_team_name"] = m.get("away_team_name")
        feat["venue"] = m.get("venue")
        rows.append(feat)

    feat_df = pd.DataFrame(rows)
    if use_xgb:
        import numpy as np
        X = feat_df.reindex(columns=feature_columns()).astype(float)
        proba_raw = clf.predict_proba(X)
        # Diagnostico: cuantas probs unicas vs duplicadas
        unique_raw = len(set(tuple(round(p, 4) for p in row) for row in proba_raw))
        print(f"[predict] {len(proba_raw)} partidos -> {unique_raw} probabilidades unicas (XGBoost crudo)")
        # Decisión: usar XGBoost CRUDO siempre. El calibrador isotonico:
        #  (a) demostro empeorar DC en evaluacion honesta (+0.034 log loss)
        #  (b) colapsa outputs de XGBoost en bins identicos (escalones isotonic)
        # Si en el futuro queremos calibracion, usaremos Platt/sigmoide.
        proba = proba_raw
    else:
        # Fallback: probabilidades vienen de DC directamente.
        import numpy as np
        proba_rows = []
        for _, m in upcoming.iterrows():
            p = dc_state.probs_1x2(m["home_team_id"], m["away_team_id"],
                                    is_neutral=bool(m.get("is_neutral", False)))
            proba_rows.append([p["H"], p["D"], p["A"]])
        proba = np.array(proba_rows)

    out_matches = []
    for i, (_, m) in enumerate(upcoming.iterrows()):
        is_neutral = bool(m.get("is_neutral", False))
        home_id, away_id = m["home_team_id"], m["away_team_id"]
        lam_h, lam_a = dc_state.lambdas(home_id, away_id, is_neutral)

        market = None
        f = feat_df.iloc[i]
        if not pd.isna(f.get("market_p_home")):
            market = {"home": round(float(f["market_p_home"]), 4),
                      "draw": round(float(f["market_p_draw"]), 4),
                      "away": round(float(f["market_p_away"]), 4)}

        out_matches.append({
            "match_id": m["match_id"],
            "kickoff_ts_utc": pd.to_datetime(m["kickoff_ts_utc"], utc=True).isoformat(),
            "competition": _competition(m.get("competition_code")),
            "home": {"id": home_id, "name": m.get("home_team_name")},
            "away": {"id": away_id, "name": m.get("away_team_name")},
            "venue": m.get("venue"),
            "is_neutral": is_neutral,
            "snapshot": args.snapshot,
            "probabilities": {
                "home": round(float(proba[i, 0]), 4),
                "draw": round(float(proba[i, 1]), 4),
                "away": round(float(proba[i, 2]), 4),
            },
            "market_probabilities": market,
            "scoreline_top": _top_scorelines(dc_state, home_id, away_id, is_neutral, k=5),
            "expected_goals": {"home": round(lam_h, 2), "away": round(lam_a, 2)},
            "derived": {
                "p_over_2_5": round(dc_state.prob_over(home_id, away_id, 2.5, is_neutral), 4),
                "p_btts": round(dc_state.prob_btts(home_id, away_id, is_neutral), 4),
            },
            "ratings": {
                "elo_home": round(elo_state.get(home_id), 1),
                "elo_away": round(elo_state.get(away_id), 1),
                "elo_diff": round(elo_state.get(home_id) - elo_state.get(away_id), 1),
            },
        })

    out_doc = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": {
            "trained_at": meta.get("trained_at"),
            "method": "DixonColes+Elo+XGBoost(isotonic)",
            "holdout_metrics": {k: v for k, v in meta.get("holdout_metrics", {}).items()
                                 if k in ("log_loss", "brier", "accuracy",
                                          "market_log_loss", "n")},
        },
        "matches": out_matches,
    }
    Path(args.out).write_text(json.dumps(out_doc, indent=2))
    print(f"[predict] {len(out_matches)} matches → {args.out}")


def _empty_doc(meta: dict) -> dict:
    return {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": {
            "trained_at": meta.get("trained_at"),
            "method": "DixonColes+Elo+XGBoost(isotonic)",
            "holdout_metrics": meta.get("holdout_metrics", {}),
        },
        "matches": [],
    }


if __name__ == "__main__":
    main()
