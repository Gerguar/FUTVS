"""
Rating Elo dinámico online para fútbol.

Basado en Hvattum & Arntzen (2010). Variantes:
- ajuste por margen de victoria (goal difference)
- ventaja de localía aplicada en el rating del local al momento del cálculo
- estado serializable a JSON para persistencia entre runs
"""
from __future__ import annotations
import json
import math
from pathlib import Path
from dataclasses import dataclass, field
from typing import Iterable
import pandas as pd

from .config import ELO, PATHS


@dataclass
class EloState:
    ratings: dict[str, float] = field(default_factory=dict)
    last_seen: dict[str, str] = field(default_factory=dict)
    last_processed_match_id: str | None = None

    def get(self, team_id: str) -> float:
        return self.ratings.get(team_id, ELO.initial_rating)

    def set(self, team_id: str, rating: float, ts: str) -> None:
        self.ratings[team_id] = rating
        self.last_seen[team_id] = ts

    def to_json(self, path: Path = PATHS.elo_state) -> None:
        path.write_text(json.dumps({
            "ratings": self.ratings,
            "last_seen": self.last_seen,
            "last_processed_match_id": self.last_processed_match_id,
        }, indent=2))

    @classmethod
    def from_json(cls, path: Path = PATHS.elo_state) -> "EloState":
        if not path.exists():
            return cls()
        d = json.loads(path.read_text())
        return cls(
            ratings=d.get("ratings", {}),
            last_seen=d.get("last_seen", {}),
            last_processed_match_id=d.get("last_processed_match_id"),
        )


def _expected(rating_a: float, rating_b: float) -> float:
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _margin_multiplier(goal_diff: int, elo_diff: float) -> float:
    """
    Multiplicador FIFA-style basado en margen. Anula la inflación de Elo
    en goleadas contra rivales débiles.
    """
    g = abs(goal_diff)
    if g <= 1:
        return 1.0
    if g == 2:
        return 1.5
    return (11.0 + g) / 8.0 * (2.2 / ((elo_diff * 0.001) + 2.2))


def update_one(
    state: EloState,
    home: str,
    away: str,
    home_goals: int,
    away_goals: int,
    ts: str,
    is_neutral: bool = False,
) -> tuple[float, float]:
    """
    Aplica una actualización Elo a un partido. Devuelve (delta_home, delta_away).
    Llamar SOLO con partidos finalizados.
    """
    r_home = state.get(home)
    r_away = state.get(away)
    ha = 0.0 if is_neutral else ELO.home_advantage

    exp_home = _expected(r_home + ha, r_away)
    if home_goals > away_goals:
        score = 1.0
    elif home_goals < away_goals:
        score = 0.0
    else:
        score = 0.5

    elo_diff = (r_home + ha) - r_away
    k = ELO.k_base
    if ELO.margin_factor:
        k *= _margin_multiplier(home_goals - away_goals, elo_diff)

    delta = k * (score - exp_home)
    state.set(home, r_home + delta, ts)
    state.set(away, r_away - delta, ts)
    return delta, -delta


def pre_match_diff(state: EloState, home: str, away: str, is_neutral: bool = False) -> dict:
    """
    Snapshot pre-partido. Devuelve features listas para incorporar a X.
    NO modifica el estado.
    """
    r_home = state.get(home)
    r_away = state.get(away)
    ha = 0.0 if is_neutral else ELO.home_advantage
    return {
        "elo_home_pre": r_home,
        "elo_away_pre": r_away,
        "elo_diff_pre": r_home - r_away,
        "elo_p_home_implied": _expected(r_home + ha, r_away),
    }


def replay(matches: pd.DataFrame, state: EloState | None = None) -> EloState:
    """
    Re-procesa una secuencia de partidos finalizados en orden cronológico.
    Idempotente: salta partidos cuyo id ya fue procesado.
    Requiere columnas: match_id, kickoff_ts_utc, home_team_id, away_team_id,
                       home_goals, away_goals, is_neutral.
    """
    if state is None:
        state = EloState.from_json()

    df = matches.sort_values("kickoff_ts_utc").reset_index(drop=True)
    if state.last_processed_match_id is not None:
        seen = False
        for i, mid in enumerate(df["match_id"]):
            if mid == state.last_processed_match_id:
                df = df.iloc[i + 1:].reset_index(drop=True)
                seen = True
                break
        if not seen:
            pass

    for _, row in df.iterrows():
        update_one(
            state,
            home=row["home_team_id"],
            away=row["away_team_id"],
            home_goals=int(row["home_goals"]),
            away_goals=int(row["away_goals"]),
            ts=str(row["kickoff_ts_utc"]),
            is_neutral=bool(row.get("is_neutral", False)),
        )
        state.last_processed_match_id = row["match_id"]

    return state
