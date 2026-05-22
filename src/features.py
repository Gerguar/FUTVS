"""
Feature engineering con snapshot temporal estricto.

Regla de oro: cada feature de una fila (partido i) sólo puede usar información
disponible ANTES de kickoff_ts_utc[i] - snapshot_offset.

Snapshots soportados: '7d', '24h', '60m'. El cutoff define qué se considera
"información pasada" para cada partido.

Genera:
- rolling/EWMA de goles a favor y en contra
- rolling de proxy de xG cuando hay event data; si no, se reemplaza por goles
- descanso, congestión, fatiga simple
- diferenciales (elo_diff, dc_lambda_diff, rest_diff, etc.)
- features de mercado a partir de odds devigged
- categóricas: competition_code, season
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Iterable
import pandas as pd
import numpy as np

from .config import LABEL_MAP, SNAPSHOTS
from .elo import EloState, pre_match_diff, update_one
from .dixon_coles import DixonColesState, pre_match_features
from .data_ingest import devig_odds
from .team_ratings import load_team_ratings


def _ratings_for(team_ratings: dict, slug: str, prefix: str) -> dict:
    """Devuelve features de EA FC rating para un equipo. NaN si no esta cargado."""
    r = team_ratings.get(slug) if team_ratings else None
    if not r:
        return {
            f"{prefix}_xi_rating": np.nan,
            f"{prefix}_attack_rating": np.nan,
            f"{prefix}_defense_rating": np.nan,
        }
    return {
        f"{prefix}_xi_rating": r.get("top_xi_avg"),
        f"{prefix}_attack_rating": r.get("attack_score"),
        f"{prefix}_defense_rating": r.get("defense_score"),
    }


SNAPSHOT_OFFSETS = {
    "7d":  pd.Timedelta(days=7),
    "24h": pd.Timedelta(hours=24),
    "60m": pd.Timedelta(minutes=60),
}


def label_from_score(home_goals: int | float, away_goals: int | float) -> str | None:
    if pd.isna(home_goals) or pd.isna(away_goals):
        return None
    if home_goals > away_goals:
        return "H"
    if home_goals < away_goals:
        return "A"
    return "D"


def _team_xg_view(team_xg: pd.DataFrame) -> pd.DataFrame:
    """Convierte team_xg.parquet (1 fila por partido) en team-centric (2 filas)."""
    if team_xg is None or team_xg.empty:
        return pd.DataFrame(columns=["match_date", "team_id", "xg_for", "xg_against"])
    home = team_xg[["match_date", "home_slug", "home_xg", "away_xg"]].copy()
    home.columns = ["match_date", "team_id", "xg_for", "xg_against"]
    away = team_xg[["match_date", "away_slug", "away_xg", "home_xg"]].copy()
    away.columns = ["match_date", "team_id", "xg_for", "xg_against"]
    out = pd.concat([home, away], ignore_index=True)
    out["match_date"] = pd.to_datetime(out["match_date"]).dt.date
    return out


def _team_history_view(matches: pd.DataFrame,
                       team_xg: pd.DataFrame | None = None) -> pd.DataFrame:
    """Pivota la tabla match-centric a team-centric (dos filas por partido).
    Si se pasa team_xg, mergea xG (xg_for, xg_against) por (date, team_id)."""
    home = matches.rename(columns={
        "home_team_id": "team_id", "away_team_id": "opp_id",
        "home_goals": "goals_for", "away_goals": "goals_against",
    }).assign(is_home=1)
    away = matches.rename(columns={
        "away_team_id": "team_id", "home_team_id": "opp_id",
        "away_goals": "goals_for", "home_goals": "goals_against",
    }).assign(is_home=0)
    keep = ["match_id", "kickoff_ts_utc", "competition_code",
            "team_id", "opp_id", "goals_for", "goals_against", "is_home"]
    df = pd.concat([home[keep], away[keep]], ignore_index=True)

    # Merge xG team-centric (si tenemos team_xg.parquet)
    if team_xg is not None and not team_xg.empty:
        tv_xg = _team_xg_view(team_xg)
        df["match_date"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True).dt.date
        df = df.merge(tv_xg, on=["match_date", "team_id"], how="left")
        df = df.drop(columns=["match_date"], errors="ignore")
        # Forzar float64 limpio
        for col in ("xg_for", "xg_against"):
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    else:
        df["xg_for"] = np.nan
        df["xg_against"] = np.nan
    return df


def _rolling_team_stats(team_view: pd.DataFrame,
                        windows: tuple[int, ...] = (3, 5, 10)) -> pd.DataFrame:
    """
    Para cada partido del equipo, calcula media de goles + xG a favor/contra
    en los últimos N partidos *previos*. EWMA con halflife=5 también.
    """
    df = team_view.sort_values(["team_id", "kickoff_ts_utc"]).copy()
    df["gd"] = df["goals_for"] - df["goals_against"]
    has_xg = "xg_for" in df.columns and "xg_against" in df.columns
    if has_xg:
        df["xgd"] = df["xg_for"] - df["xg_against"]
    g = df.groupby("team_id", sort=False)
    for w in windows:
        df[f"gf_roll{w}"] = g["goals_for"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        df[f"ga_roll{w}"] = g["goals_against"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        df[f"gd_roll{w}"] = g["gd"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        if has_xg:
            df[f"xg_roll{w}"] = g["xg_for"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
            df[f"xga_roll{w}"] = g["xg_against"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
            df[f"xgd_roll{w}"] = g["xgd"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
    df["gd_ewma5"] = g["gd"].shift(1).ewm(halflife=5, min_periods=1).mean().reset_index(level=0, drop=True)
    df["gd_ewma10"] = g["gd"].shift(1).ewm(halflife=10, min_periods=1).mean().reset_index(level=0, drop=True)
    df["momentum"] = df["gd_ewma5"] - df["gd_ewma10"]
    if has_xg:
        df["xgd_ewma5"] = g["xgd"].shift(1).ewm(halflife=5, min_periods=1).mean().reset_index(level=0, drop=True)
        df["xgd_ewma10"] = g["xgd"].shift(1).ewm(halflife=10, min_periods=1).mean().reset_index(level=0, drop=True)
        df["xg_momentum"] = df["xgd_ewma5"] - df["xgd_ewma10"]
    return df


def _rest_and_congestion(team_view: pd.DataFrame) -> pd.DataFrame:
    df = team_view.sort_values(["team_id", "kickoff_ts_utc"]).copy()
    g = df.groupby("team_id", sort=False)
    df["prev_kickoff"] = g["kickoff_ts_utc"].shift(1)
    df["rest_days"] = (df["kickoff_ts_utc"] - df["prev_kickoff"]).dt.total_seconds() / 86400.0
    df["rest_days"] = df["rest_days"].clip(lower=0, upper=60)

    df = df.sort_values(["team_id", "kickoff_ts_utc"])
    matches_7d = []
    matches_14d = []
    for _, sub in df.groupby("team_id", sort=False):
        ts = sub["kickoff_ts_utc"].values.astype("datetime64[ns]")
        m7, m14 = [], []
        for i in range(len(ts)):
            t = ts[i]
            window7 = t - np.timedelta64(7, "D")
            window14 = t - np.timedelta64(14, "D")
            m7.append(int(((ts[:i] >= window7) & (ts[:i] < t)).sum()))
            m14.append(int(((ts[:i] >= window14) & (ts[:i] < t)).sum()))
        matches_7d.extend(m7)
        matches_14d.extend(m14)
    df["matches_last_7d"] = matches_7d
    df["matches_last_14d"] = matches_14d
    df["fatigue_idx"] = (df["matches_last_14d"] * 2.0 +
                         np.where(df["rest_days"] < 3, 1.5, 0.0))
    return df


def build_team_features(matches: pd.DataFrame,
                        team_xg: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    Devuelve una tabla con todas las features team-match-level calculadas
    estrictamente con info previa al partido (shift(1) + ventanas rolling).
    Si se pasa team_xg, suma features de xG rolling.
    """
    matches = matches.copy()
    matches["kickoff_ts_utc"] = pd.to_datetime(matches["kickoff_ts_utc"], utc=True)
    tv = _team_history_view(matches, team_xg=team_xg)
    tv = _rolling_team_stats(tv)
    tv = _rest_and_congestion(tv)
    return tv


def _odds_to_features(row: pd.Series) -> dict:
    o_h, o_d, o_a = row.get("odds_home"), row.get("odds_draw"), row.get("odds_away")
    if pd.isna(o_h) or pd.isna(o_d) or pd.isna(o_a):
        return {"market_p_home": np.nan, "market_p_draw": np.nan,
                "market_p_away": np.nan, "market_overround": np.nan,
                "has_market": 0}
    p_h, p_d, p_a = devig_odds(o_h, o_d, o_a)
    overround = (1 / o_h + 1 / o_d + 1 / o_a) - 1
    return {"market_p_home": p_h, "market_p_draw": p_d, "market_p_away": p_a,
            "market_overround": overround, "has_market": 1}


@dataclass
class FeatureBuilder:
    """
    Materializa una tabla de features lista para entrenamiento o inferencia.

    Asegura snapshot temporal estricto. Para cada match i:
    - Elo y DC se calculan con un estado que SOLO contiene partidos cuyo
      kickoff < kickoff[i].
    - Las features rolling vienen de team_features ya shifted.
    - Las odds se aceptan si odds_ts_utc <= kickoff[i] - offset(snapshot).
    """
    snapshot: str = SNAPSHOTS.mid

    def build_training_table(self,
                             matches: pd.DataFrame,
                             dc_state: DixonColesState,
                             elo_replay_state: EloState) -> pd.DataFrame:
        """
        Para entrenamiento offline. Recorre cronológicamente y, para cada partido,
        toma el estado Elo previo y luego lo actualiza con el resultado real.
        DC se asume fitted sobre ventana <= asof; usamos un mismo state aquí por
        simplicidad operativa, pero en backtest serio se refittea por fold.
        """
        m = matches.copy()
        m["kickoff_ts_utc"] = pd.to_datetime(m["kickoff_ts_utc"], utc=True)
        m = m.sort_values("kickoff_ts_utc").reset_index(drop=True)

        # Cargar team_xg para sumar features de xG rolling
        from .ingest_xg import load_team_xg
        team_xg_df = load_team_xg()

        team_feats = build_team_features(m, team_xg=team_xg_df)
        team_feats_h = team_feats[team_feats["is_home"] == 1].add_prefix("home_")
        team_feats_a = team_feats[team_feats["is_home"] == 0].add_prefix("away_")
        team_feats_h = team_feats_h.rename(columns={"home_match_id": "match_id"})
        team_feats_a = team_feats_a.rename(columns={"away_match_id": "match_id"})

        team_ratings = load_team_ratings()
        elo_state = EloState()
        rows = []
        for _, row in m.iterrows():
            ts = row["kickoff_ts_utc"]
            home = row["home_team_id"]
            away = row["away_team_id"]
            neutral = bool(row.get("is_neutral", False))

            elo_feats = pre_match_diff(elo_state, home, away, is_neutral=neutral)
            dc_feats = pre_match_features(dc_state, home, away, is_neutral=neutral)
            mkt_feats = _odds_to_features(row)
            rating_h = _ratings_for(team_ratings, home, "home")
            rating_a = _ratings_for(team_ratings, away, "away")

            label = label_from_score(row.get("home_goals"), row.get("away_goals"))

            feat = {
                "match_id": row["match_id"],
                "kickoff_ts_utc": ts,
                "competition_code": row.get("competition_code"),
                "season": row.get("season"),
                "home_team_id": home,
                "away_team_id": away,
                "is_neutral": int(neutral),
                **elo_feats,
                **dc_feats,
                **mkt_feats,
                **rating_h,
                **rating_a,
                "label": label,
            }
            rows.append(feat)

            if (pd.notna(row.get("home_goals")) and pd.notna(row.get("away_goals"))):
                update_one(elo_state, home, away,
                           int(row["home_goals"]), int(row["away_goals"]),
                           ts=str(ts), is_neutral=neutral)

        base = pd.DataFrame(rows)
        out = (base
               .merge(team_feats_h, on="match_id", how="left")
               .merge(team_feats_a, on="match_id", how="left"))

        out["rest_diff"] = out.get("home_rest_days") - out.get("away_rest_days")
        out["congestion_diff"] = out.get("home_matches_last_14d") - out.get("away_matches_last_14d")
        out["fatigue_diff"] = out.get("home_fatigue_idx") - out.get("away_fatigue_idx")
        out["gd5_diff"] = out.get("home_gd_roll5") - out.get("away_gd_roll5")
        out["momentum_diff"] = out.get("home_momentum") - out.get("away_momentum")

        # Ratings EA FC: diferencial XI + match-up por posicion
        out["xi_rating_diff"] = out.get("home_xi_rating") - out.get("away_xi_rating")
        # Local ataca contra defensa visitante (y viceversa)
        out["home_attack_vs_away_defense"] = out.get("home_attack_rating") - out.get("away_defense_rating")
        out["away_attack_vs_home_defense"] = out.get("away_attack_rating") - out.get("home_defense_rating")

        # xG rolling diff (5 partidos): diferencia de calidad de juego reciente
        if "home_xgd_roll5" in out.columns and "away_xgd_roll5" in out.columns:
            out["xgd5_diff"] = out["home_xgd_roll5"] - out["away_xgd_roll5"]
            out["xg_momentum_diff"] = out.get("home_xg_momentum") - out.get("away_xg_momentum")
        return out

    def build_inference_row(self,
                            home: str, away: str,
                            kickoff_ts_utc: pd.Timestamp,
                            competition_code: str,
                            is_neutral: bool,
                            elo_state: EloState,
                            dc_state: DixonColesState,
                            team_features: pd.DataFrame,
                            odds_row: dict | None) -> dict:
        """Genera una fila de features para un partido futuro."""
        ts = pd.to_datetime(kickoff_ts_utc, utc=True)
        cutoff = ts - SNAPSHOT_OFFSETS[self.snapshot]

        def latest(team: str) -> dict:
            sub = team_features[(team_features["team_id"] == team) &
                                (team_features["kickoff_ts_utc"] <= cutoff)]
            if sub.empty:
                return {}
            r = sub.sort_values("kickoff_ts_utc").iloc[-1]
            return {k: r[k] for k in r.index if k.startswith(("gf_", "ga_", "gd_",
                                                               "xg_", "xga_", "xgd_",
                                                               "rest_", "matches_last_",
                                                               "fatigue_", "momentum"))}

        elo_feats = pre_match_diff(elo_state, home, away, is_neutral=is_neutral)
        dc_feats = pre_match_features(dc_state, home, away, is_neutral=is_neutral)
        mkt_feats = _odds_to_features(pd.Series(odds_row or {}))

        team_ratings = load_team_ratings()
        rating_h = _ratings_for(team_ratings, home, "home")
        rating_a = _ratings_for(team_ratings, away, "away")

        h = {f"home_{k}": v for k, v in latest(home).items()}
        a = {f"away_{k}": v for k, v in latest(away).items()}

        row = {
            "kickoff_ts_utc": ts,
            "competition_code": competition_code,
            "home_team_id": home,
            "away_team_id": away,
            "is_neutral": int(is_neutral),
            **elo_feats,
            **dc_feats,
            **mkt_feats,
            **rating_h,
            **rating_a,
            **h, **a,
        }
        row["rest_diff"] = (h.get("home_rest_days") or 0) - (a.get("away_rest_days") or 0)
        row["congestion_diff"] = (h.get("home_matches_last_14d") or 0) - (a.get("away_matches_last_14d") or 0)
        row["fatigue_diff"] = (h.get("home_fatigue_idx") or 0) - (a.get("away_fatigue_idx") or 0)
        row["gd5_diff"] = (h.get("home_gd_roll5") or 0) - (a.get("away_gd_roll5") or 0)
        row["momentum_diff"] = (h.get("home_momentum") or 0) - (a.get("away_momentum") or 0)

        h_xi = rating_h.get("home_xi_rating"); a_xi = rating_a.get("away_xi_rating")
        h_atk = rating_h.get("home_attack_rating"); a_atk = rating_a.get("away_attack_rating")
        h_def = rating_h.get("home_defense_rating"); a_def = rating_a.get("away_defense_rating")
        row["xi_rating_diff"] = (h_xi - a_xi) if (h_xi is not None and a_xi is not None) else np.nan
        row["home_attack_vs_away_defense"] = (h_atk - a_def) if (h_atk is not None and a_def is not None) else np.nan
        row["away_attack_vs_home_defense"] = (a_atk - h_def) if (a_atk is not None and h_def is not None) else np.nan
        return row


def feature_columns() -> list[str]:
    """Columnas que entran al modelo (orden estable)."""
    return [
        "is_neutral",
        "elo_home_pre", "elo_away_pre", "elo_diff_pre", "elo_p_home_implied",
        "dc_lambda_home", "dc_lambda_away", "dc_lambda_diff", "dc_lambda_sum",
        "dc_p_home", "dc_p_draw", "dc_p_away", "dc_p_over25", "dc_p_btts",
        "market_p_home", "market_p_draw", "market_p_away", "market_overround", "has_market",
        "home_gf_roll5", "home_ga_roll5", "home_gd_roll5", "home_gd_roll10",
        "away_gf_roll5", "away_ga_roll5", "away_gd_roll5", "away_gd_roll10",
        "home_rest_days", "away_rest_days",
        "home_matches_last_7d", "away_matches_last_7d",
        "home_fatigue_idx", "away_fatigue_idx",
        "home_momentum", "away_momentum",
        "rest_diff", "congestion_diff", "fatigue_diff", "gd5_diff", "momentum_diff",
        # Ratings EA FC 26 (top XI agregado, ataque/defensa por posicion)
        "home_xi_rating", "away_xi_rating", "xi_rating_diff",
        "home_attack_rating", "home_defense_rating",
        "away_attack_rating", "away_defense_rating",
        "home_attack_vs_away_defense", "away_attack_vs_home_defense",
        # xG rolling (Understat team-level) — calidad de juego reciente
        "home_xg_roll5", "home_xga_roll5", "home_xgd_roll5",
        "away_xg_roll5", "away_xga_roll5", "away_xgd_roll5",
        "home_xg_momentum", "away_xg_momentum",
        "xgd5_diff", "xg_momentum_diff",
    ]
