"""
Modelo Dixon-Coles (1997).

Extiende Poisson clásico con:
- corrección tau(x, y) para resultados bajos (0-0, 1-0, 0-1, 1-1)
- ponderación temporal exponencial exp(-xi * dt_dias)

Estima por equipo:
    attack[t], defence[t]
y un parámetro global home_adv y rho (corrección DC).

Intensidades esperadas:
    lambda_home = exp(attack[home] - defence[away] + home_adv)
    lambda_away = exp(attack[away] - defence[home])

Probabilidades de scoreline -> 1X2, over/under, BTTS.
"""
from __future__ import annotations
import json
import math
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.optimize import minimize

from .config import DC, PATHS


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


def _log_pmf_poisson(k: int, lam: float) -> float:
    if lam <= 0:
        return -1e9
    return k * math.log(lam) - lam - math.lgamma(k + 1)


@dataclass
class DixonColesState:
    teams: list[str]
    attack: dict[str, float]
    defence: dict[str, float]
    home_adv: float
    rho: float
    fitted_at: str | None = None
    n_matches: int = 0

    def to_json(self, path: Path = PATHS.dc_state) -> None:
        path.write_text(json.dumps(asdict(self), indent=2))

    @classmethod
    def from_json(cls, path: Path = PATHS.dc_state) -> "DixonColesState":
        d = json.loads(path.read_text())
        return cls(**d)

    def lambdas(self, home: str, away: str, is_neutral: bool = False) -> tuple[float, float]:
        atk_h = self.attack.get(home, 0.0)
        def_h = self.defence.get(home, 0.0)
        atk_a = self.attack.get(away, 0.0)
        def_a = self.defence.get(away, 0.0)
        ha = 0.0 if is_neutral else self.home_adv
        lam = math.exp(atk_h - def_a + ha)
        mu = math.exp(atk_a - def_h)
        return lam, mu

    def scoreline_matrix(self, home: str, away: str, is_neutral: bool = False,
                         max_goals: int | None = None) -> np.ndarray:
        max_g = max_goals or DC.max_goals
        lam, mu = self.lambdas(home, away, is_neutral)
        m = np.zeros((max_g + 1, max_g + 1))
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                p = math.exp(_log_pmf_poisson(i, lam) + _log_pmf_poisson(j, mu))
                m[i, j] = p * _tau(i, j, lam, mu, self.rho)
        s = m.sum()
        if s > 0:
            m = m / s
        return m

    def probs_1x2(self, home: str, away: str, is_neutral: bool = False) -> dict[str, float]:
        m = self.scoreline_matrix(home, away, is_neutral)
        p_h = float(np.tril(m, -1).sum())
        p_d = float(np.trace(m))
        p_a = float(np.triu(m, 1).sum())
        s = p_h + p_d + p_a
        return {"H": p_h / s, "D": p_d / s, "A": p_a / s}

    def prob_over(self, home: str, away: str, line: float = 2.5,
                  is_neutral: bool = False) -> float:
        m = self.scoreline_matrix(home, away, is_neutral)
        max_g = m.shape[0] - 1
        p_over = 0.0
        for i in range(max_g + 1):
            for j in range(max_g + 1):
                if i + j > line:
                    p_over += m[i, j]
        return float(p_over)

    def prob_btts(self, home: str, away: str, is_neutral: bool = False) -> float:
        m = self.scoreline_matrix(home, away, is_neutral)
        return float(m[1:, 1:].sum())


def _pack(params: np.ndarray, teams: list[str]) -> dict:
    n = len(teams)
    atk = dict(zip(teams, params[:n]))
    dfn = dict(zip(teams, params[n:2 * n]))
    return {"attack": atk, "defence": dfn, "home_adv": params[-2], "rho": params[-1]}


def _unpack(d: dict, teams: list[str]) -> np.ndarray:
    n = len(teams)
    a = np.array([d["attack"][t] for t in teams])
    b = np.array([d["defence"][t] for t in teams])
    return np.concatenate([a, b, [d["home_adv"], d["rho"]]])


def fit(matches: pd.DataFrame, asof_ts: pd.Timestamp | None = None,
        xi: float | None = None) -> DixonColesState:
    """
    Ajusta Dixon-Coles por MLE con ponderación temporal.
    matches debe contener: kickoff_ts_utc, home_team_id, away_team_id,
                           home_goals, away_goals, is_neutral.
    asof_ts: ponderación temporal calculada relativa a este instante.
             Si es None, usa el partido más reciente como referencia.
    """
    df = matches.dropna(subset=["home_goals", "away_goals"]).copy()
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    df = df.sort_values("kickoff_ts_utc")

    if asof_ts is None:
        asof_ts = df["kickoff_ts_utc"].max()
    else:
        asof_ts = pd.to_datetime(asof_ts, utc=True)

    xi_val = xi if xi is not None else DC.xi
    dt_days = (asof_ts - df["kickoff_ts_utc"]).dt.total_seconds().values / 86400.0
    w = np.exp(-xi_val * np.maximum(dt_days, 0.0))

    teams = sorted(set(df["home_team_id"]).union(df["away_team_id"]))
    n = len(teams)
    idx = {t: i for i, t in enumerate(teams)}

    home_idx = df["home_team_id"].map(idx).values
    away_idx = df["away_team_id"].map(idx).values
    hg = df["home_goals"].astype(int).values
    ag = df["away_goals"].astype(int).values
    neutral = df.get("is_neutral", pd.Series([False] * len(df))).fillna(False).astype(bool).values

    x0 = np.concatenate([
        np.zeros(n),
        np.zeros(n),
        [0.25, -0.10],
    ])

    def neg_loglik(params: np.ndarray) -> float:
        atk = params[:n]
        dfn = params[n:2 * n]
        ha = params[-2]
        rho = params[-1]
        lam = np.exp(atk[home_idx] - dfn[away_idx] + np.where(neutral, 0.0, ha))
        mu = np.exp(atk[away_idx] - dfn[home_idx])
        ll_poiss = (hg * np.log(lam) - lam - np.array([math.lgamma(k + 1) for k in hg])
                    + ag * np.log(mu) - mu - np.array([math.lgamma(k + 1) for k in ag]))
        tau_vec = np.ones(len(df))
        for k in range(len(df)):
            x, y = hg[k], ag[k]
            if x <= 1 and y <= 1:
                tau_vec[k] = _tau(x, y, lam[k], mu[k], rho)
        tau_safe = np.where(tau_vec > 1e-9, tau_vec, 1e-9)
        ll = ll_poiss + np.log(tau_safe)
        return -np.sum(w * ll)

    constraints = (
        {"type": "eq", "fun": lambda p: np.sum(p[:n])},
        {"type": "eq", "fun": lambda p: np.sum(p[n:2 * n])},
    )
    bounds = [(-3, 3)] * (2 * n) + [(-0.5, 1.5), (-0.3, 0.3)]

    res = minimize(neg_loglik, x0, method="SLSQP", bounds=bounds,
                   constraints=constraints, options={"maxiter": 200, "ftol": 1e-6})

    params = res.x
    state = DixonColesState(
        teams=teams,
        attack=dict(zip(teams, params[:n].tolist())),
        defence=dict(zip(teams, params[n:2 * n].tolist())),
        home_adv=float(params[-2]),
        rho=float(params[-1]),
        fitted_at=str(asof_ts),
        n_matches=len(df),
    )
    return state


def pre_match_features(state: DixonColesState, home: str, away: str,
                       is_neutral: bool = False) -> dict:
    """Features prepartido derivadas de DC para alimentar el modelo tabular."""
    lam, mu = state.lambdas(home, away, is_neutral)
    p = state.probs_1x2(home, away, is_neutral)
    return {
        "dc_lambda_home": lam,
        "dc_lambda_away": mu,
        "dc_lambda_diff": lam - mu,
        "dc_lambda_sum": lam + mu,
        "dc_p_home": p["H"],
        "dc_p_draw": p["D"],
        "dc_p_away": p["A"],
        "dc_p_over25": state.prob_over(home, away, 2.5, is_neutral),
        "dc_p_btts": state.prob_btts(home, away, is_neutral),
    }
