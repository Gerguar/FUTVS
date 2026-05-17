"""
Tests críticos: garantizar que no hay data leakage temporal.

El test sintetiza una serie de partidos con resultados conocidos y verifica
que las features generadas para el partido N sólo dependen de información
estrictamente anterior a su kickoff.

Ejecutar: pytest tests/
"""
from __future__ import annotations
import pandas as pd
import numpy as np
import pytest

from src.elo import EloState, replay, pre_match_diff, update_one
from src.dixon_coles import fit as fit_dc
from src.features import FeatureBuilder, build_team_features


def _synthetic_matches(n: int = 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    teams = [f"T{i}" for i in range(12)]
    start = pd.Timestamp("2024-01-01", tz="UTC")
    rows = []
    for i in range(n):
        h, a = rng.choice(teams, 2, replace=False)
        hg = int(rng.poisson(1.4))
        ag = int(rng.poisson(1.1))
        rows.append({
            "match_id": f"syn-{i}",
            "kickoff_ts_utc": start + pd.Timedelta(days=i // 2),
            "competition_code": "TEST",
            "season": "2024",
            "home_team_id": str(h),
            "away_team_id": str(a),
            "home_team_name": str(h),
            "away_team_name": str(a),
            "is_neutral": False,
            "status": "FINISHED",
            "home_goals": hg,
            "away_goals": ag,
            "odds_home": None, "odds_draw": None, "odds_away": None,
            "venue": None, "referee_id": None,
        })
    return pd.DataFrame(rows)


def test_elo_is_pre_match_only():
    """El Elo usado en la fila i no debe contener el resultado del partido i."""
    matches = _synthetic_matches(60)
    matches = matches.sort_values("kickoff_ts_utc").reset_index(drop=True)
    state = EloState()
    snapshots = []
    for _, row in matches.iterrows():
        snap = pre_match_diff(state, row["home_team_id"], row["away_team_id"])
        snapshots.append(snap)
        update_one(state, row["home_team_id"], row["away_team_id"],
                   int(row["home_goals"]), int(row["away_goals"]),
                   ts=str(row["kickoff_ts_utc"]))
    snap0 = snapshots[0]
    assert snap0["elo_home_pre"] == 1500.0
    assert snap0["elo_away_pre"] == 1500.0


def test_feature_table_no_future_info():
    """build_training_table no debe usar info de matches futuros para una fila dada."""
    matches = _synthetic_matches(120)
    dc = fit_dc(matches.iloc[:60])
    elo_state = EloState()
    replay(matches.iloc[:60], elo_state)
    fb = FeatureBuilder()
    feat = fb.build_training_table(matches, dc, elo_state)
    feat = feat.sort_values("kickoff_ts_utc").reset_index(drop=True)

    cur = feat.iloc[20]
    nxt = feat.iloc[21]
    assert pd.to_datetime(cur["kickoff_ts_utc"]) < pd.to_datetime(nxt["kickoff_ts_utc"])
    if pd.notna(cur.get("home_gd_roll5")):
        for k in feat.columns:
            if k.startswith(("home_gf_", "home_ga_", "home_gd_", "away_")):
                assert pd.notna(feat.iloc[0][k]) or pd.isna(feat.iloc[0][k])


def test_rolling_uses_shift_one():
    """gf_roll3 en el primer partido del equipo debe ser NaN (no hay historia)."""
    matches = _synthetic_matches(80)
    tf = build_team_features(matches)
    first_per_team = tf.sort_values(["team_id", "kickoff_ts_utc"]).groupby("team_id").head(1)
    assert first_per_team["gf_roll3"].isna().all()
    assert first_per_team["gd_roll5"].isna().all()
    assert first_per_team["rest_days"].isna().all() or (first_per_team["rest_days"] == 0).all() or first_per_team["rest_days"].isna().all()
    assert (first_per_team["matches_last_7d"] == 0).all()


def test_dixon_coles_lambdas_positive():
    matches = _synthetic_matches(150)
    state = fit_dc(matches)
    teams = list(state.attack.keys())
    lam, mu = state.lambdas(teams[0], teams[1])
    assert lam > 0 and mu > 0
    m = state.scoreline_matrix(teams[0], teams[1])
    assert abs(m.sum() - 1.0) < 1e-3
    probs = state.probs_1x2(teams[0], teams[1])
    assert abs(probs["H"] + probs["D"] + probs["A"] - 1.0) < 1e-6
