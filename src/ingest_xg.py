"""
Ingest de xG team-level por partido desde Understat (via soccerdata).

Para cada (liga, temporada) llama a `Understat.read_schedule()` o
`read_team_match_stats()` y obtiene xG por partido. Mergea los slugs
canonicos para emparejar con matches.parquet.

Output:
    data/team_xg.parquet con columnas:
        match_date   (date)
        home_slug
        away_slug
        home_xg
        away_xg
        home_goals
        away_goals
        league       (codigo interno: EPL/LL/SA/BL/L1)

DC luego usa este parquet para reemplazar `home_goals/away_goals` por
`home_xg/away_xg` cuando estan disponibles.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import pandas as pd

from .config import PATHS
from .team_normalize import canonical


TEAM_XG_PATH = PATHS.matches.parent / "team_xg.parquet"


def load_team_xg(path: Path = TEAM_XG_PATH) -> pd.DataFrame:
    """Lee team_xg.parquet. Devuelve DF vacio si no existe."""
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except Exception:
        return pd.DataFrame()

UNDERSTAT_LEAGUES = {
    "ENG-Premier League": "EPL",
    "ESP-La Liga":        "LL",
    "ITA-Serie A":        "SA",
    "GER-Bundesliga":     "BL",
    "FRA-Ligue 1":        "L1",
}


def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """Aplana MultiIndex de columnas y resetea el index si es multi-level."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [
            (c[1] if (isinstance(c, tuple) and c[1]) else c[0] if isinstance(c, tuple) else c)
            for c in df.columns
        ]
    if df.index.nlevels > 1:
        df = df.reset_index()
    return df


def _find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    for c in df.columns:
        if str(c).lower().strip() in candidates:
            return c
    return None


def fetch_league_schedule(league: str, seasons: list[str]) -> pd.DataFrame:
    """Devuelve schedule de una liga con xG por partido."""
    import soccerdata as sd
    u = sd.Understat(leagues=league, seasons=seasons)
    df = u.read_schedule()
    df = _flatten(df)
    print(f"  · raw shape: {df.shape}, columnas: {list(df.columns)[:20]}")
    return df


def normalize_schedule(df: pd.DataFrame, league_code: str) -> pd.DataFrame:
    """Convierte el schedule de Understat a nuestro formato."""
    if df.empty:
        return pd.DataFrame()

    # Buscar columnas relevantes con tolerancia a nombres distintos
    home_col = _find_col(df, ["home_team", "home", "hometeam", "h_team"])
    away_col = _find_col(df, ["away_team", "away", "awayteam", "a_team"])
    home_xg_col = _find_col(df, ["home_xg", "xg_home", "h_xg", "xghome"])
    away_xg_col = _find_col(df, ["away_xg", "xg_away", "a_xg", "xgaway"])
    home_g_col = _find_col(df, ["home_goals", "goals_home", "h_goals", "h_g"])
    away_g_col = _find_col(df, ["away_goals", "goals_away", "a_goals", "a_g"])
    date_col = _find_col(df, ["date", "datetime", "match_date", "kickoff", "kickoff_ts"])

    missing = [
        n for n, v in [
            ("home", home_col), ("away", away_col),
            ("home_xg", home_xg_col), ("away_xg", away_xg_col),
            ("date", date_col),
        ] if v is None
    ]
    if missing:
        print(f"  ! columnas faltantes: {missing}. Columnas disponibles: {list(df.columns)}")
        return pd.DataFrame()

    out = pd.DataFrame({
        "match_date": pd.to_datetime(df[date_col], errors="coerce").dt.date,
        "home_name": df[home_col].astype(str),
        "away_name": df[away_col].astype(str),
        "home_xg": pd.to_numeric(df[home_xg_col], errors="coerce"),
        "away_xg": pd.to_numeric(df[away_xg_col], errors="coerce"),
        "home_goals": pd.to_numeric(df[home_g_col], errors="coerce") if home_g_col else None,
        "away_goals": pd.to_numeric(df[away_g_col], errors="coerce") if away_g_col else None,
        "league": league_code,
    })
    out["home_slug"] = out["home_name"].map(canonical)
    out["away_slug"] = out["away_name"].map(canonical)

    # Filtrar partidos sin xG (no jugados o sin data)
    out = out.dropna(subset=["home_xg", "away_xg", "match_date"])
    out = out[(out["home_slug"] != "") & (out["away_slug"] != "")]

    return out[["match_date", "home_slug", "away_slug", "home_name", "away_name",
                "home_xg", "away_xg", "home_goals", "away_goals", "league"]]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seasons", default="2024,2023,2022,2021,2020",
                    help="Anios de inicio separados por coma (Understat: 2024=2024-25)")
    ap.add_argument("--leagues", default=None,
                    help="CSV de league names. Default: top 5")
    args = ap.parse_args()

    seasons = [s.strip() for s in args.seasons.split(",") if s.strip()]
    if args.leagues:
        league_names = [s.strip() for s in args.leagues.split(",")]
    else:
        league_names = list(UNDERSTAT_LEAGUES.keys())

    print(f"[xg] seasons={seasons} leagues={[UNDERSTAT_LEAGUES.get(l, l) for l in league_names]}")
    all_rows: list[pd.DataFrame] = []
    for league_name in league_names:
        league_code = UNDERSTAT_LEAGUES.get(league_name, league_name)
        print(f"\n[xg] === {league_code} ({league_name}) ===")
        try:
            raw = fetch_league_schedule(league_name, seasons)
            normalized = normalize_schedule(raw, league_code)
            if normalized.empty:
                print(f"  ! sin filas usables para {league_code}")
                continue
            print(f"  + {len(normalized)} partidos con xG")
            all_rows.append(normalized)
        except Exception as e:
            import traceback
            print(f"  ! error fetching {league_code}: {type(e).__name__}: {e}")
            traceback.print_exc()

    if not all_rows:
        print("\n[xg] no se obtuvo data. Salimos sin escribir parquet.")
        return

    final = pd.concat(all_rows, ignore_index=True)
    # Deduplicar por (date, home_slug, away_slug)
    final = final.drop_duplicates(subset=["match_date", "home_slug", "away_slug"], keep="last")
    TEAM_XG_PATH.parent.mkdir(parents=True, exist_ok=True)
    final.to_parquet(TEAM_XG_PATH, index=False)
    print(f"\n[xg] guardado: {TEAM_XG_PATH}  ({len(final)} partidos, "
          f"{final['league'].value_counts().to_dict()})")

    # Sanity: mostrar un sample
    print("\n[xg] sample primeros 5:")
    for _, r in final.head(5).iterrows():
        print(f"  {r['match_date']}  {r['home_slug']:>20} {r['home_xg']:>4.2f}-{r['away_xg']:>4.2f} {r['away_slug']:<20}  {r['league']}")


if __name__ == "__main__":
    main()
