"""
Fetch de alineaciones desde API-Football (api-sports.io).
Free tier: 100 requests/dia.

Output por partido:
  {
    "home": {"formation": "4-3-3", "starters": [...], "coach": "..."},
    "away": {"formation": "4-2-3-1", "starters": [...], "coach": "..."}
  }

Nota: las alineaciones se publican 60-120min antes del kickoff.
Usarlas antes de esa ventana devuelve lista vacia.
"""
from __future__ import annotations
import time
import requests
from .config import KEYS

APIFOOTBALL_BASE = "https://v3.football.api-sports.io"

# Mapa de competition_code -> league_id en API-Football
LEAGUE_IDS: dict[str, int] = {
    "UCL": 2,
    "EPL": 39,
    "LL":  140,
    "SA":  135,
    "BL":  78,
    "L1":  61,
    "LIB": 13,
    "UEL": 3,
}


def _headers() -> dict:
    return {"x-apisports-key": KEYS.apifootball or ""}


def fetch_lineups_by_fixture(fixture_id: int) -> dict:
    """
    Dado un fixture_id de API-Football, devuelve alineaciones home/away.
    Retorna {} si no estan disponibles todavia o si falla la request.
    """
    if not KEYS.apifootball:
        return {}
    try:
        r = requests.get(
            f"{APIFOOTBALL_BASE}/lineups",
            headers=_headers(),
            params={"fixture": fixture_id},
            timeout=30,
        )
        if r.status_code != 200:
            return {}
        data = r.json().get("response", [])
        if len(data) < 2:
            return {}

        result = {}
        for team_data in data:
            side = "home" if team_data["team"]["id"] == data[0]["team"]["id"] else "away"
            result[side] = {
                "formation": team_data.get("formation"),
                "starters": [
                    p["player"]["name"]
                    for p in team_data.get("startXI", [])
                ],
                "coach": team_data.get("coach", {}).get("name"),
            }
        return result
    except Exception:
        return {}


def search_fixture_id(home_name: str, away_name: str,
                      date_str: str, league_id: int) -> int | None:
    """
    Busca el fixture_id en API-Football dado nombres de equipos y fecha (YYYY-MM-DD).
    Retorna None si no encuentra match.
    """
    if not KEYS.apifootball:
        return None
    try:
        r = requests.get(
            f"{APIFOOTBALL_BASE}/fixtures",
            headers=_headers(),
            params={"league": league_id, "date": date_str, "season": date_str[:4]},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        for fix in r.json().get("response", []):
            teams = fix.get("teams", {})
            h = teams.get("home", {}).get("name", "").lower()
            a = teams.get("away", {}).get("name", "").lower()
            if home_name.lower() in h or h in home_name.lower():
                if away_name.lower() in a or a in away_name.lower():
                    return fix["fixture"]["id"]
        return None
    except Exception:
        return None


def enrich_matches_with_lineups(matches_df, sleep_sec: float = 1.5) -> dict:
    """
    Dado el DataFrame de partidos proximos, busca alineaciones para cada uno.
    Retorna un dict { match_id -> lineups_dict }.
    Solo busca partidos con status TIMED o IN_PLAY.
    Respeta rate limit con sleep entre calls.
    """
    import pandas as pd
    from datetime import datetime, timezone

    results = {}
    now = datetime.now(timezone.utc)

    eligible = matches_df[
        matches_df["status"].isin(["TIMED", "IN_PLAY", "SCHEDULED"])
    ].copy()

    for _, row in eligible.iterrows():
        comp = row.get("competition_code", "")
        league_id = LEAGUE_IDS.get(comp)
        if not league_id:
            continue

        kickoff = pd.to_datetime(row["kickoff_ts_utc"], utc=True)
        # Solo buscar si el partido es en <= 2 horas o ya empezo
        diff_hours = (kickoff - now).total_seconds() / 3600
        if diff_hours > 2 or diff_hours < -3:
            continue

        date_str = kickoff.strftime("%Y-%m-%d")
        fixture_id = search_fixture_id(
            row["home_team_name"], row["away_team_name"],
            date_str, league_id
        )
        if fixture_id:
            lineups = fetch_lineups_by_fixture(fixture_id)
            if lineups:
                results[row["match_id"]] = lineups
                print(f"[lineups] {row['home_team_name']} vs {row['away_team_name']}: OK", flush=True)
            else:
                print(f"[lineups] {row['home_team_name']} vs {row['away_team_name']}: sin datos aun", flush=True)
        time.sleep(sleep_sec)

    return results
