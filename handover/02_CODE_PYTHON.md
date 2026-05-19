# FutPronostico — Codigo Python (src/)
Todos los modulos del modelo y pipeline. El paquete se importa como `src.*` desde la raiz del proyecto.

---

## `src/config.py`

```python
"""
Configuración central del sistema.

Define ligas objetivo, ventanas temporales, paths, hiperparámetros del modelo,
y los horizontes de snapshot (t-7d, t-24h, t-60m).
"""
from __future__ import annotations
from pathlib import Path
from dataclasses import dataclass, field
import os

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
MODEL_DIR = DATA_DIR / "models"
WEB_DIR = ROOT / "web"

DATA_DIR.mkdir(exist_ok=True)
MODEL_DIR.mkdir(exist_ok=True)


@dataclass(frozen=True)
class Competition:
    code: str
    name: str
    fd_code: str | None = None
    is_international: bool = False


COMPETITIONS: list[Competition] = [
    # Solo competiciones disponibles en el FREE TIER de football-data.org.
    # UEL y UECL requieren plan pago — se omiten.
    Competition("UCL", "UEFA Champions League", "CL", True),

    Competition("EPL", "Premier League", "PL"),
    Competition("LL",  "La Liga",        "PD"),
    Competition("SA",  "Serie A",        "SA"),
    Competition("BL",  "Bundesliga",     "BL1"),
    Competition("L1",  "Ligue 1",        "FL1"),
]

INTERNATIONAL_CODES = [c.code for c in COMPETITIONS if c.is_international]
DOMESTIC_CODES = [c.code for c in COMPETITIONS if not c.is_international]


@dataclass(frozen=True)
class EloConfig:
    k_base: float = 20.0
    home_advantage: float = 65.0
    initial_rating: float = 1500.0
    margin_factor: bool = True


@dataclass(frozen=True)
class DixonColesConfig:
    xi: float = 0.0035
    max_goals: int = 8
    min_matches: int = 80


@dataclass(frozen=True)
class XGBConfig:
    objective: str = "multi:softprob"
    eval_metric: str = "mlogloss"
    max_depth: int = 4
    learning_rate: float = 0.03
    n_estimators: int = 2000
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    reg_lambda: float = 2.0
    early_stopping_rounds: int = 100
    num_class: int = 3


@dataclass(frozen=True)
class BacktestConfig:
    min_train_matches: int = 500
    valid_window_days: int = 60
    test_window_days: int = 30
    step_days: int = 30
    calibration_method: str = "isotonic"


@dataclass(frozen=True)
class Snapshots:
    """
    Cada feature debe corresponder a información disponible en uno de estos
    cortes temporales antes del kickoff. Mezclarlos = leakage.
    """
    far: str = "7d"
    mid: str = "24h"
    near: str = "60m"


@dataclass(frozen=True)
class Paths:
    matches: Path = DATA_DIR / "matches.parquet"
    elo_state: Path = DATA_DIR / "elo_state.json"
    dc_state: Path = DATA_DIR / "dc_state.json"
    xgb_model: Path = MODEL_DIR / "xgb_1x2.json"
    calibrator: Path = MODEL_DIR / "calibrator.joblib"
    feature_meta: Path = MODEL_DIR / "feature_meta.json"
    predictions: Path = DATA_DIR / "predictions.json"
    backtest_report: Path = DATA_DIR / "backtest_report.json"


@dataclass(frozen=True)
class APIKeys:
    football_data: str | None = field(default_factory=lambda: os.getenv("FOOTBALL_DATA_TOKEN"))
    the_odds_api: str | None = field(default_factory=lambda: os.getenv("THE_ODDS_API_KEY"))


ELO = EloConfig()
DC = DixonColesConfig()
XGB = XGBConfig()
BACKTEST = BacktestConfig()
SNAPSHOTS = Snapshots()
PATHS = Paths()
KEYS = APIKeys()

LABEL_MAP = {"H": 0, "D": 1, "A": 2}
LABEL_INV = {v: k for k, v in LABEL_MAP.items()}

```

---

## `src/team_normalize.py`

```python
"""
Normalización de nombres de equipos a un identificador estable ("slug").

Distintas fuentes (football-data.org, football-data.co.uk, etc.) llaman a los
mismos equipos de formas distintas. Por ejemplo:

    "Manchester City FC" (football-data.org)
    "Man City"           (football-data.co.uk)

Para que Dixon-Coles y Elo entrenen correctamente, las dos cadenas deben
mapear al mismo ID. Acá centralizamos esa lógica en `canonical(name)`.

Para los 12 equipos que están en Supabase la coincidencia DEBE ser exacta —
hardcodeamos todas las variantes conocidas. Para los demás equipos top de las 5
ligas grandes, también incluimos las variantes obvias. Cualquier nombre no
mapeado cae a un slug derivado del nombre (lower + underscores + sin sufijos
ruidosos tipo "FC"/"AFC"/"SC"/"CF").
"""
from __future__ import annotations
import re
import unicodedata


# ──────────────────────────────────────────────────────────────────────────
# Slug para cada equipo (lo que vamos a usar como home_team_id / away_team_id
# en todo el pipeline). Si dos fuentes mapean al mismo slug, el modelo los
# trata como el mismo equipo.
# ──────────────────────────────────────────────────────────────────────────

# Equipos en Supabase (críticos: tienen que mapear bien sí o sí).
SUPABASE_TEAMS_SLUGS = {
    "real_madrid", "barcelona", "atletico_madrid",
    "bayern_munich", "dortmund",
    "arsenal", "man_city", "liverpool", "chelsea",
    "inter_milan", "ac_milan", "paris_sg",
}

# Variantes de nombre -> slug. Case-insensitive en el lookup.
# La clave es el nombre tal como aparece en CADA fuente.
TEAM_NAME_TO_SLUG: dict[str, str] = {
    # Real Madrid
    "real madrid": "real_madrid",
    "real madrid cf": "real_madrid",

    # Barcelona
    "barcelona": "barcelona",
    "fc barcelona": "barcelona",
    "barça": "barcelona",
    "barca": "barcelona",

    # Atlético Madrid
    "atletico madrid": "atletico_madrid",
    "atlético madrid": "atletico_madrid",
    "atlético de madrid": "atletico_madrid",
    "atletico de madrid": "atletico_madrid",
    "club atlético de madrid": "atletico_madrid",
    "club atletico de madrid": "atletico_madrid",
    "ath madrid": "atletico_madrid",
    "atleti": "atletico_madrid",

    # Bayern
    "bayern": "bayern_munich",
    "bayern munich": "bayern_munich",
    "bayern múnich": "bayern_munich",
    "bayern munchen": "bayern_munich",
    "bayern münchen": "bayern_munich",
    "fc bayern münchen": "bayern_munich",
    "fc bayern munchen": "bayern_munich",

    # Dortmund
    "dortmund": "dortmund",
    "borussia dortmund": "dortmund",
    "bvb": "dortmund",

    # Arsenal
    "arsenal": "arsenal",
    "arsenal fc": "arsenal",

    # Man City
    "man city": "man_city",
    "man. city": "man_city",
    "manchester city": "man_city",
    "manchester city fc": "man_city",

    # Liverpool
    "liverpool": "liverpool",
    "liverpool fc": "liverpool",

    # Chelsea
    "chelsea": "chelsea",
    "chelsea fc": "chelsea",

    # Inter
    "inter": "inter_milan",
    "inter milán": "inter_milan",
    "inter milan": "inter_milan",
    "internazionale": "inter_milan",
    "fc internazionale milano": "inter_milan",

    # AC Milan
    "milan": "ac_milan",
    "ac milan": "ac_milan",
    "ac milán": "ac_milan",

    # PSG
    "psg": "paris_sg",
    "paris sg": "paris_sg",
    "paris saint-germain": "paris_sg",
    "paris saint-germain fc": "paris_sg",

    # ── Otros equipos comunes en top 5 ligas (importantes para entrenar bien)
    # Premier League
    "man united": "man_united",
    "manchester united": "man_united",
    "manchester united fc": "man_united",
    "newcastle": "newcastle",
    "newcastle united": "newcastle",
    "newcastle united fc": "newcastle",
    "tottenham": "tottenham",
    "tottenham hotspur": "tottenham",
    "tottenham hotspur fc": "tottenham",
    "nott'm forest": "nottingham_forest",
    "nottingham": "nottingham_forest",
    "nottingham forest": "nottingham_forest",
    "nottingham forest fc": "nottingham_forest",
    "west ham": "west_ham",
    "west ham united": "west_ham",
    "west ham united fc": "west_ham",
    "wolves": "wolves",
    "wolverhampton": "wolves",
    "wolverhampton wanderers": "wolves",
    "wolverhampton wanderers fc": "wolves",
    "brighton": "brighton",
    "brighton hove": "brighton",
    "brighton & hove albion": "brighton",
    "brighton & hove albion fc": "brighton",
    "brighton and hove albion fc": "brighton",
    "crystal palace": "crystal_palace",
    "crystal palace fc": "crystal_palace",
    "aston villa": "aston_villa",
    "aston villa fc": "aston_villa",
    "bournemouth": "bournemouth",
    "afc bournemouth": "bournemouth",
    "everton": "everton",
    "everton fc": "everton",
    "fulham": "fulham",
    "fulham fc": "fulham",
    "brentford": "brentford",
    "brentford fc": "brentford",
    "leicester": "leicester",
    "leicester city": "leicester",
    "leicester city fc": "leicester",
    "southampton": "southampton",
    "southampton fc": "southampton",
    "leeds": "leeds",
    "leeds united": "leeds",
    "leeds united fc": "leeds",
    "sheffield united": "sheffield_united",
    "sheffield united fc": "sheffield_united",
    "luton": "luton",
    "luton town": "luton",
    "luton town fc": "luton",
    "ipswich": "ipswich",
    "ipswich town": "ipswich",
    "ipswich town fc": "ipswich",
    "burnley": "burnley",
    "burnley fc": "burnley",

    # La Liga
    "ath bilbao": "athletic_bilbao",
    "athletic bilbao": "athletic_bilbao",
    "athletic": "athletic_bilbao",
    "athletic club": "athletic_bilbao",
    "sociedad": "real_sociedad",
    "real sociedad": "real_sociedad",
    "real sociedad de fútbol": "real_sociedad",
    "betis": "real_betis",
    "real betis": "real_betis",
    "real betis balompié": "real_betis",
    "vallecano": "rayo_vallecano",
    "rayo vallecano": "rayo_vallecano",
    "rayo vallecano de madrid": "rayo_vallecano",
    "cadiz": "cadiz",
    "cádiz cf": "cadiz",
    "mallorca": "mallorca",
    "rcd mallorca": "mallorca",
    "sevilla": "sevilla",
    "sevilla fc": "sevilla",
    "valencia": "valencia",
    "valencia cf": "valencia",
    "villarreal": "villarreal",
    "villarreal cf": "villarreal",
    "celta": "celta",
    "rc celta de vigo": "celta",
    "rc celta": "celta",
    "espanyol": "espanyol",
    "espanol": "espanyol",
    "rcd espanyol de barcelona": "espanyol",
    "rcd espanyol": "espanyol",
    "getafe": "getafe",
    "getafe cf": "getafe",
    "osasuna": "osasuna",
    "ca osasuna": "osasuna",
    "granada": "granada",
    "granada cf": "granada",
    "las palmas": "las_palmas",
    "ud las palmas": "las_palmas",
    "almeria": "almeria",
    "ud almería": "almeria",
    "alaves": "alaves",
    "deportivo alavés": "alaves",
    "girona": "girona",
    "girona fc": "girona",
    "leganes": "leganes",
    "cd leganés": "leganes",
    "valladolid": "valladolid",
    "real valladolid cf": "valladolid",

    # Serie A
    "juventus": "juventus",
    "juventus fc": "juventus",
    "napoli": "napoli",
    "ssc napoli": "napoli",
    "lazio": "lazio",
    "ss lazio": "lazio",
    "roma": "roma",
    "as roma": "roma",
    "atalanta": "atalanta",
    "atalanta bc": "atalanta",
    "bologna": "bologna",
    "bologna fc 1909": "bologna",
    "torino": "torino",
    "torino fc": "torino",
    "fiorentina": "fiorentina",
    "acf fiorentina": "fiorentina",
    "sassuolo": "sassuolo",
    "us sassuolo calcio": "sassuolo",
    "genoa": "genoa",
    "genoa cfc": "genoa",
    "lecce": "lecce",
    "us lecce": "lecce",
    "udinese": "udinese",
    "udinese calcio": "udinese",
    "cagliari": "cagliari",
    "cagliari calcio": "cagliari",
    "monza": "monza",
    "ac monza": "monza",
    "salernitana": "salernitana",
    "us salernitana 1919": "salernitana",
    "empoli": "empoli",
    "empoli fc": "empoli",
    "frosinone": "frosinone",
    "frosinone calcio": "frosinone",
    "como": "como",
    "como 1907": "como",
    "parma": "parma",
    "parma calcio 1913": "parma",
    "venezia": "venezia",
    "venezia fc": "venezia",
    "hellas verona": "verona",
    "verona": "verona",
    "hellas verona fc": "verona",

    # Bundesliga
    "leverkusen": "leverkusen",
    "bayer leverkusen": "leverkusen",
    "bayer 04 leverkusen": "leverkusen",
    "leipzig": "leipzig",
    "rb leipzig": "leipzig",
    "rasenballsport leipzig": "leipzig",
    "m'gladbach": "mgladbach",
    "mgladbach": "mgladbach",
    "borussia mönchengladbach": "mgladbach",
    "borussia monchengladbach": "mgladbach",
    "wolfsburg": "wolfsburg",
    "vfl wolfsburg": "wolfsburg",
    "stuttgart": "stuttgart",
    "vfb stuttgart": "stuttgart",
    "fc koln": "fc_koln",
    "fc köln": "fc_koln",
    "1. fc köln": "fc_koln",
    "1. fc koln": "fc_koln",
    "hoffenheim": "hoffenheim",
    "tsg hoffenheim": "hoffenheim",
    "tsg 1899 hoffenheim": "hoffenheim",
    "mainz": "mainz",
    "mainz 05": "mainz",
    "1. fsv mainz 05": "mainz",
    "union berlin": "union_berlin",
    "1. fc union berlin": "union_berlin",
    "heidenheim": "heidenheim",
    "1. fc heidenheim 1846": "heidenheim",
    "werder bremen": "werder_bremen",
    "sv werder bremen": "werder_bremen",
    "frankfurt": "eintracht_frankfurt",
    "ein frankfurt": "eintracht_frankfurt",
    "eintracht frankfurt": "eintracht_frankfurt",
    "eintracht frankfurt fußball ag": "eintracht_frankfurt",
    "augsburg": "augsburg",
    "fc augsburg": "augsburg",
    "freiburg": "freiburg",
    "sport-club freiburg": "freiburg",
    "sc freiburg": "freiburg",
    "bochum": "bochum",
    "vfl bochum 1848": "bochum",
    "darmstadt": "darmstadt",
    "sv darmstadt 98": "darmstadt",
    "st pauli": "st_pauli",
    "st. pauli": "st_pauli",
    "fc st. pauli 1910": "st_pauli",
    "holstein kiel": "holstein_kiel",
    "ksv holstein": "holstein_kiel",

    # Ligue 1
    "marseille": "marseille",
    "olympique marseille": "marseille",
    "olympique de marseille": "marseille",
    "lyon": "lyon",
    "olympique lyonnais": "lyon",
    "saint etienne": "saint_etienne",
    "saint-etienne": "saint_etienne",
    "st etienne": "saint_etienne",
    "st-etienne": "saint_etienne",
    "as saint-étienne": "saint_etienne",
    "as saint-etienne": "saint_etienne",
    "monaco": "monaco",
    "as monaco": "monaco",
    "as monaco fc": "monaco",
    "lille": "lille",
    "lille osc": "lille",
    "rennes": "rennes",
    "stade rennais": "rennes",
    "stade rennais fc 1901": "rennes",
    "nice": "nice",
    "ogc nice": "nice",
    "strasbourg": "strasbourg",
    "rc strasbourg alsace": "strasbourg",
    "rc strasbourg": "strasbourg",
    "reims": "reims",
    "stade de reims": "reims",
    "lens": "lens",
    "rc lens": "lens",
    "brest": "brest",
    "stade brestois 29": "brest",
    "le havre": "le_havre",
    "le havre ac": "le_havre",
    "auxerre": "auxerre",
    "aj auxerre": "auxerre",
    "angers": "angers",
    "angers sco": "angers",
    "toulouse": "toulouse",
    "toulouse fc": "toulouse",
    "nantes": "nantes",
    "fc nantes": "nantes",
    "montpellier": "montpellier",
    "montpellier hsc": "montpellier",
    "metz": "metz",
    "fc metz": "metz",
    "clermont": "clermont",
    "clermont foot 63": "clermont",
    "lorient": "lorient",
    "fc lorient": "lorient",
}


# Sufijos comunes que conviene tirar antes del slugify defensivo.
_NOISE_SUFFIXES = (
    " fc", " afc", " sc", " cf", " ac", " ssc", " bc", " ud", " rc",
    " cd", " ca", " us", " usl", " ksc", " ksv", " sv", " vfl", " vfb",
    " fk", " ssd", " club", " 1909", " 1910", " 1913", " 1907", " 1846",
    " 1898", " 1893", " 1900", " 1901", " 1919",
)


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s)
        if unicodedata.category(c) != "Mn"
    )


def _slugify(name: str) -> str:
    n = _strip_accents(name).lower().strip()
    for suf in _NOISE_SUFFIXES:
        if n.endswith(suf):
            n = n[: -len(suf)].strip()
    n = re.sub(r"[^a-z0-9]+", "_", n)
    n = re.sub(r"_+", "_", n).strip("_")
    return n or "unknown"


def canonical(name: str | None) -> str:
    """Devuelve el slug canónico para el equipo. Nunca devuelve None."""
    if not name:
        return "unknown"
    key = _strip_accents(name).strip().lower()
    if key in TEAM_NAME_TO_SLUG:
        return TEAM_NAME_TO_SLUG[key]
    # Fallback: slugify defensivo.
    return _slugify(name)


def is_known(name: str | None) -> bool:
    if not name:
        return False
    key = _strip_accents(name).strip().lower()
    return key in TEAM_NAME_TO_SLUG

```

---

## `src/data_ingest.py`

```python
"""
Ingesta de datos.

Fuentes:
- football-data.org v4: fixtures, results, lineups (free tier, 10 req/min).
- the-odds-api.com: odds 1X2 pre-match (free tier, 500 req/mes).

Output:
    data/matches.parquet — tabla canónica match-centric.

Esquema canónico (match_id es estable cross-source):
    match_id, kickoff_ts_utc, competition_code, season,
    home_team_id, away_team_id, home_team_name, away_team_name,
    is_neutral, status,
    home_goals, away_goals,
    odds_home, odds_draw, odds_away, odds_ts_utc,
    venue, referee_id
"""
from __future__ import annotations
import argparse
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from .config import COMPETITIONS, PATHS, KEYS
from .team_normalize import canonical, is_known
from .ingest_couk import backfill_couk


class RetryableHTTPError(Exception):
    """429 o 5xx — reintentar."""


class PermanentHTTPError(Exception):
    """403/404/401 — no reintentar, saltear."""

FD_BASE = "https://api.football-data.org/v4"
ODDS_BASE = "https://api.the-odds-api.com/v4"

ODDS_SPORTS = {
    "UCL": "soccer_uefa_champs_league",
    "UEL": "soccer_uefa_europa_league",
    "UECL": "soccer_uefa_europa_conference_league",
    "LIB": "soccer_conmebol_copa_libertadores",
    "EPL": "soccer_epl",
    "LL":  "soccer_spain_la_liga",
    "SA":  "soccer_italy_serie_a",
    "BL":  "soccer_germany_bundesliga",
    "L1":  "soccer_france_ligue_one",
    "BRA": "soccer_brazil_campeonato",
    "ARG": "soccer_argentina_primera_division",
}


@retry(stop=stop_after_attempt(3),
       wait=wait_exponential(min=5, max=60),
       retry=retry_if_exception_type(RetryableHTTPError))
def _fd_get(path: str, params: dict | None = None) -> dict:
    if not KEYS.football_data:
        raise RuntimeError("Falta FOOTBALL_DATA_TOKEN en el entorno")
    r = requests.get(f"{FD_BASE}{path}",
                     headers={"X-Auth-Token": KEYS.football_data},
                     params=params or {}, timeout=30)
    if r.status_code == 429:
        raise RetryableHTTPError("rate limited (429)")
    if r.status_code in (401, 403, 404):
        raise PermanentHTTPError(f"http {r.status_code} (plan no incluye este recurso)")
    if r.status_code >= 500:
        raise RetryableHTTPError(f"server {r.status_code}")
    if r.status_code != 200:
        raise PermanentHTTPError(f"http {r.status_code}: {r.text[:120]}")
    return r.json()


def _is_neutral_match(venue: str | None, home_name: str | None) -> bool:
    """Heurística: finales de copas suelen tener venue distinto al de cualquier club.
    En la práctica, marcar manualmente o cruzar contra una tabla de estadios."""
    if not venue or not home_name:
        return False
    neutrals = {"wembley", "estadio monumental", "lusail", "atatürk", "puskás aréna"}
    v = venue.lower()
    return any(k in v for k in neutrals)


def fetch_fd_matches(fd_code: str, date_from: str, date_to: str) -> list[dict]:
    """Trae partidos de football-data.org en un rango.

    home_team_id / away_team_id se normalizan a slug canónico (mismo ID
    que usa football-data.co.uk), para que ambas fuentes se unifiquen.
    """
    data = _fd_get(f"/competitions/{fd_code}/matches",
                   params={"dateFrom": date_from, "dateTo": date_to})
    out = []
    for m in data.get("matches", []):
        score = m.get("score", {}).get("fullTime") or {}
        home = m["homeTeam"]
        away = m["awayTeam"]
        home_name = home.get("shortName") or home.get("name")
        away_name = away.get("shortName") or away.get("name")
        out.append({
            "match_id": f"fd-{m['id']}",
            "kickoff_ts_utc": m["utcDate"],
            "competition_code": fd_code,
            "season": m.get("season", {}).get("startDate", "")[:4],
            "home_team_id": canonical(home_name),
            "away_team_id": canonical(away_name),
            "home_team_name": home_name,
            "away_team_name": away_name,
            "home_team_crest": home.get("crest"),
            "away_team_crest": away.get("crest"),
            "home_team_tla": home.get("tla"),
            "away_team_tla": away.get("tla"),
            "is_neutral": _is_neutral_match(m.get("venue"), home.get("name")),
            "status": m.get("status"),
            "home_goals": score.get("home"),
            "away_goals": score.get("away"),
            "venue": m.get("venue"),
            "referee_id": (m.get("referees") or [{}])[0].get("id"),
        })
    return out


def backfill(since: str = "2022-08-01", until: str | None = None) -> pd.DataFrame:
    """
    Backfill histórico. Itera por competición y chunks de 90 días.
    - Si una competición devuelve 403/404 una vez, la saltea entera (no está en el plan).
    - Sleep entre llamadas para respetar el rate limit del free tier (10 req/min).
    """
    until_dt = pd.to_datetime(until or datetime.now(timezone.utc).date())
    since_dt = pd.to_datetime(since)
    rows: list[dict] = []
    sleep_between_calls = 6.5  # 10 req/min con margen

    for comp in COMPETITIONS:
        if not comp.fd_code:
            continue
        cur = since_dt
        comp_total = 0
        comp_blocked = False
        while cur < until_dt:
            nxt = min(cur + timedelta(days=90), until_dt)
            print(f"[backfill] {comp.code} {cur.date()} -> {nxt.date()}", flush=True)
            try:
                chunk = fetch_fd_matches(comp.fd_code,
                                         cur.strftime("%Y-%m-%d"),
                                         nxt.strftime("%Y-%m-%d"))
                rows.extend(chunk)
                comp_total += len(chunk)
                print(f"  + {len(chunk)} partidos", flush=True)
            except PermanentHTTPError as e:
                print(f"  ! {comp.code} no disponible en este plan: {e}. Salteando el resto de {comp.code}.", flush=True)
                comp_blocked = True
                break
            except Exception as e:
                print(f"  ! error temporal: {e}", flush=True)
            cur = nxt
            time.sleep(sleep_between_calls)
        if not comp_blocked:
            print(f"[backfill] {comp.code} total: {comp_total} partidos", flush=True)
    return pd.DataFrame(rows)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def fetch_odds(comp_code: str) -> list[dict]:
    """Trae odds 1X2 pre-match. Promedio entre bookmakers (devigged)."""
    if not KEYS.the_odds_api:
        return []
    sport = ODDS_SPORTS.get(comp_code)
    if not sport:
        return []
    r = requests.get(f"{ODDS_BASE}/sports/{sport}/odds",
                     params={"apiKey": KEYS.the_odds_api,
                             "regions": "eu,uk",
                             "markets": "h2h",
                             "oddsFormat": "decimal"},
                     timeout=30)
    if r.status_code != 200:
        return []
    out = []
    for ev in r.json():
        home = ev.get("home_team")
        away = ev.get("away_team")
        odds_h, odds_d, odds_a, count = 0.0, 0.0, 0.0, 0
        for bk in ev.get("bookmakers", []):
            for mk in bk.get("markets", []):
                if mk.get("key") != "h2h":
                    continue
                m = {o["name"]: o["price"] for o in mk.get("outcomes", [])}
                if home in m and away in m and "Draw" in m:
                    odds_h += m[home]; odds_d += m["Draw"]; odds_a += m[away]
                    count += 1
        if count:
            out.append({
                "kickoff_ts_utc": ev["commence_time"],
                "home_team_name": home,
                "away_team_name": away,
                "odds_home": odds_h / count,
                "odds_draw": odds_d / count,
                "odds_away": odds_a / count,
                "odds_ts_utc": datetime.now(timezone.utc).isoformat(),
            })
    return out


def devig_odds(o_h: float, o_d: float, o_a: float) -> tuple[float, float, float]:
    """Convierte odds decimales a probabilidades implícitas normalizadas (devig proporcional)."""
    p_h, p_d, p_a = 1 / o_h, 1 / o_d, 1 / o_a
    s = p_h + p_d + p_a
    return p_h / s, p_d / s, p_a / s


def merge_odds(matches: pd.DataFrame, odds: pd.DataFrame) -> pd.DataFrame:
    """Hace match aproximado por nombre y fecha. Tolerancia ±6h."""
    if odds.empty:
        for c in ["odds_home", "odds_draw", "odds_away", "odds_ts_utc"]:
            if c not in matches.columns:
                matches[c] = None
        return matches
    m = matches.copy()
    m["kickoff_ts_utc"] = pd.to_datetime(m["kickoff_ts_utc"], utc=True)
    odds["kickoff_ts_utc"] = pd.to_datetime(odds["kickoff_ts_utc"], utc=True)
    out = m.merge(odds, on=["home_team_name", "away_team_name"], how="left",
                  suffixes=("", "_odds"))
    bad = (out["kickoff_ts_utc_odds"].notna() &
           ((out["kickoff_ts_utc"] - out["kickoff_ts_utc_odds"]).abs() > pd.Timedelta(hours=6)))
    for c in ["odds_home", "odds_draw", "odds_away", "odds_ts_utc"]:
        out.loc[bad, c] = None
    out = out.drop(columns=["kickoff_ts_utc_odds"], errors="ignore")
    return out


def upsert_matches(df_new: pd.DataFrame) -> pd.DataFrame:
    """Mergea con el parquet existente y deduplica por match_id (último gana)."""
    if PATHS.matches.exists():
        existing = pd.read_parquet(PATHS.matches)
        df = pd.concat([existing, df_new], ignore_index=True)
    else:
        df = df_new
    if df.empty or "match_id" not in df.columns:
        print("[ingest] no hay partidos para guardar (df vacio).", flush=True)
        return df
    df = df.drop_duplicates(subset=["match_id"], keep="last")
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    # Normalizar tipos para parquet: columnas que pueden venir como int/str/None
    # entre fuentes distintas se fuerzan a string para evitar ArrowTypeError.
    for col in ("referee_id", "home_team_id", "away_team_id", "venue", "season",
                "competition_code", "status"):
        if col in df.columns:
            df[col] = df[col].astype("object").where(df[col].notna(), None)
            df[col] = df[col].map(lambda v: None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v))
    df = df.sort_values("kickoff_ts_utc").reset_index(drop=True)
    df.to_parquet(PATHS.matches, index=False)
    return df


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--backfill", action="store_true",
                   help="Backfill: combina football-data.org (temporada actual + UCL) "
                        "con football-data.co.uk (5 temporadas historicas de top 5 ligas).")
    p.add_argument("--since", default="2025-07-01",
                   help="Solo aplica al ingest de football-data.org (free tier).")
    p.add_argument("--days-ahead", type=int, default=14,
                   help="Sólo refresca fixtures próximos (modo no-backfill)")
    p.add_argument("--couk-seasons", default="2020,2021,2022,2023,2024,2025",
                   help="Temporadas (anio inicio) a bajar de football-data.co.uk")
    p.add_argument("--skip-couk", action="store_true",
                   help="Salta el ingest historico de football-data.co.uk")
    p.add_argument("--skip-fd", action="store_true",
                   help="Salta el ingest de football-data.org")
    args = p.parse_args()

    frames = []

    # Fuente 1: football-data.org (temporada actual + UCL + fixtures proximos)
    if not args.skip_fd:
        if args.backfill:
            df_fd = backfill(since=args.since)
        else:
            today = datetime.now(timezone.utc).date()
            df_fd = backfill(since=(today - timedelta(days=14)).isoformat(),
                             until=(today + timedelta(days=args.days_ahead)).isoformat())
        print(f"[ingest] football-data.org: {len(df_fd)} partidos", flush=True)
        if not df_fd.empty:
            frames.append(df_fd)

    # Fuente 2: football-data.co.uk (historico profundo, solo en modo backfill)
    if args.backfill and not args.skip_couk:
        seasons = [int(s) for s in args.couk_seasons.split(",") if s.strip()]
        df_couk = backfill_couk(seasons=seasons)
        print(f"[ingest] football-data.co.uk: {len(df_couk)} partidos", flush=True)
        if not df_couk.empty:
            frames.append(df_couk)

    if not frames:
        print("[ingest] ningun partido fue fetcheado. Posibles causas:", flush=True)
        print("  - token de football-data.org invalido", flush=True)
        print("  - football-data.co.uk caido o blocked en el runner", flush=True)
        print("[ingest] terminando con exit 0 para no romper el workflow.", flush=True)
        return

    df = pd.concat(frames, ignore_index=True)

    # Odds en tiempo real desde The Odds API (opcional, solo si hay key)
    odds_rows = []
    for comp in COMPETITIONS:
        odds_rows.extend(fetch_odds(comp.code))
    odds_df = pd.DataFrame(odds_rows)
    df = merge_odds(df, odds_df)

    # Cuantos equipos no estan en el alias hardcodeado (telemetria util)
    if "home_team_name" in df.columns:
        all_names = pd.concat([df["home_team_name"], df["away_team_name"]]).dropna().unique()
        unknown = [n for n in all_names if not is_known(n)]
        if unknown:
            print(f"[ingest] {len(unknown)} equipos no estan en TEAM_NAME_TO_SLUG, "
                  f"se usa slugify automatico:", flush=True)
            for n in unknown[:30]:
                print(f"   - {n!r} -> {canonical(n)}", flush=True)
            if len(unknown) > 30:
                print(f"   ... y {len(unknown) - 30} mas", flush=True)

    df = upsert_matches(df)
    print(f"[ingest] total matches en parquet: {len(df)}", flush=True)


if __name__ == "__main__":
    main()

```

---

## `src/ingest_couk.py`

```python
"""
Ingesta de partidos históricos desde football-data.co.uk.

Fuente: CSVs públicos por liga × temporada. Sin API key, sin rate limit.

URL pattern:
    https://www.football-data.co.uk/mmz4281/{season_code}/{league_code}.csv

Donde:
    season_code = "2021" para 2020/21, "2122" para 2021/22, etc.
    league_code = E0 (Premier), SP1 (La Liga), I1 (Serie A),
                  D1 (Bundesliga), F1 (Ligue 1)

El CSV trae:
    - Resultado: Date, HomeTeam, AwayTeam, FTHG, FTAG, FTR
    - Odds de bookmakers (B365H, B365D, B365A, PSH, PSD, PSA, etc.)

Salida: lista[dict] con el mismo schema que `fetch_fd_matches`
        + odds promediadas entre bookmakers cuando están disponibles.
"""
from __future__ import annotations
import io
from datetime import datetime
import pandas as pd
import requests
from tenacity import retry, stop_after_attempt, wait_exponential

from .team_normalize import canonical


COUK_BASE = "https://www.football-data.co.uk/mmz4281"

# league_code -> nuestro competition_code interno
LEAGUE_MAP_COUK = {
    "E0":  "EPL",
    "SP1": "LL",
    "I1":  "SA",
    "D1":  "BL",
    "F1":  "L1",
}

# Bookmakers a promediar para sacar odds 1X2. Si una columna falta en una
# temporada vieja, se ignora — promediamos solo las que existan.
BOOKMAKER_COLS = [
    ("B365H", "B365D", "B365A"),  # Bet365
    ("BWH",   "BWD",   "BWA"),    # Bet&Win
    ("PSH",   "PSD",   "PSA"),    # Pinnacle
    ("WHH",   "WHD",   "WHA"),    # William Hill
    ("VCH",   "VCD",   "VCA"),    # VC Bet
]


def season_code(year_start: int) -> str:
    """2020 -> '2021', 2024 -> '2425'."""
    return f"{year_start % 100:02d}{(year_start + 1) % 100:02d}"


def url_for(season_year: int, league_code: str) -> str:
    return f"{COUK_BASE}/{season_code(season_year)}/{league_code}.csv"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=20))
def _download(url: str) -> bytes | None:
    r = requests.get(url, timeout=30)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def _parse_date(s: str) -> str | None:
    """football-data.co.uk usa DD/MM/YYYY o DD/MM/YY."""
    if not s:
        return None
    s = str(s).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            d = datetime.strptime(s, fmt)
            # asumimos kickoff a las 15:00 UTC si no hay hora (suficiente
            # para feature engineering de rest_days/congestion).
            return d.replace(hour=15).isoformat() + "+00:00"
        except ValueError:
            continue
    return None


def _avg_odds(row: pd.Series) -> tuple[float | None, float | None, float | None]:
    h, d, a, n = 0.0, 0.0, 0.0, 0
    for cH, cD, cA in BOOKMAKER_COLS:
        if cH in row and cD in row and cA in row:
            vh, vd, va = row.get(cH), row.get(cD), row.get(cA)
            if pd.notna(vh) and pd.notna(vd) and pd.notna(va) and vh > 1 and vd > 1 and va > 1:
                h += float(vh); d += float(vd); a += float(va); n += 1
    if n == 0:
        return None, None, None
    return h / n, d / n, a / n


def parse_csv(content: bytes, league_code: str, season_year: int) -> list[dict]:
    """Convierte un CSV de football-data.co.uk a nuestro schema canónico."""
    df = pd.read_csv(io.BytesIO(content), encoding="latin-1", on_bad_lines="skip")
    needed = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG"}
    if not needed.issubset(df.columns):
        return []
    comp_code = LEAGUE_MAP_COUK[league_code]
    season = f"{season_year}/{(season_year + 1) % 100:02d}"

    out: list[dict] = []
    for _, row in df.iterrows():
        home_name = str(row.get("HomeTeam") or "").strip()
        away_name = str(row.get("AwayTeam") or "").strip()
        if not home_name or not away_name:
            continue
        ts = _parse_date(row.get("Date"))
        if not ts:
            continue
        hg = row.get("FTHG"); ag = row.get("FTAG")
        if pd.isna(hg) or pd.isna(ag):
            continue
        odds_h, odds_d, odds_a = _avg_odds(row)

        home_slug = canonical(home_name)
        away_slug = canonical(away_name)

        # match_id estable basado en fuente + competición + fecha + equipos
        match_id = f"couk-{league_code}-{season_code(season_year)}-{home_slug}-{away_slug}-{ts[:10]}"

        out.append({
            "match_id": match_id,
            "kickoff_ts_utc": ts,
            "competition_code": comp_code,
            "season": season,
            "home_team_id": home_slug,
            "away_team_id": away_slug,
            "home_team_name": home_name,
            "away_team_name": away_name,
            "home_team_crest": None,
            "away_team_crest": None,
            "home_team_tla": None,
            "away_team_tla": None,
            "is_neutral": False,
            "status": "FINISHED",
            "home_goals": int(hg),
            "away_goals": int(ag),
            "venue": None,
            "referee_id": str(row["Referee"]).strip() if "Referee" in row and pd.notna(row.get("Referee")) else None,
            "odds_home": odds_h,
            "odds_draw": odds_d,
            "odds_away": odds_a,
            "odds_ts_utc": None,
        })
    return out


def backfill_couk(seasons: list[int] | None = None,
                  leagues: list[str] | None = None) -> pd.DataFrame:
    """
    Baja CSVs de football-data.co.uk para varias temporadas y ligas.

    seasons: lista de años de inicio. Default: [2020..2025].
    leagues: lista de league_code. Default: todos los de LEAGUE_MAP_COUK.
    """
    if seasons is None:
        seasons = list(range(2020, 2026))
    if leagues is None:
        leagues = list(LEAGUE_MAP_COUK.keys())

    rows: list[dict] = []
    for s in seasons:
        for lg in leagues:
            url = url_for(s, lg)
            print(f"[couk] {LEAGUE_MAP_COUK[lg]} {s}/{(s+1)%100:02d} -> {url}", flush=True)
            try:
                content = _download(url)
                if content is None:
                    print(f"  - 404 (temporada/liga no disponible)", flush=True)
                    continue
                chunk = parse_csv(content, lg, s)
                rows.extend(chunk)
                print(f"  + {len(chunk)} partidos", flush=True)
            except Exception as e:
                print(f"  ! error: {e}", flush=True)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    df = backfill_couk()
    print(f"[couk] total: {len(df)} partidos")

```

---

## `src/ingest_squads.py`

```python
"""
Ingest de plantillas (jugadores) + metadata de equipos desde football-data.org.

Para cada competition en COMPETITIONS, llama /competitions/{code}/teams que
devuelve TODO lo que necesitamos en una sola request:
- founded (anio de fundacion)
- venue (estadio)
- crest (escudo)
- squad: lista completa de jugadores con name, position, dateOfBirth,
  nationality, shirtNumber

Actualiza en Supabase:
- equipos.fundacion (si esta vacia)
- equipos.estadio   (si esta vacio)
- jugadores: BORRA todos los jugadores del equipo y los re-inserta con la
  plantilla actual. Esto es necesario porque las plantillas cambian con
  transferencias.

Importante: la tabla jugadores tiene FK desde estadisticas_jugador,
mercado_historico y minutos_por_anio. Si esas FK estan ON DELETE CASCADE,
los datos derivados se borran tambien (ok porque eran demo). Si no, el
DELETE puede fallar — manejamos el error gracefully.
"""
from __future__ import annotations
import argparse
import time
import urllib.request

from .config import COMPETITIONS
from .team_normalize import canonical
from .data_ingest import _fd_get
from .supabase_writer import sb_get, sb_post, sb_patch, _sb_url, _headers, LEAGUE_ALIAS
from .supabase_sync import SupabaseSync, TEAM_COLORS, TEAM_COUNTRY, LIGA_TO_PAIS


# football-data.org devuelve positions con muchos detalles. Las agrupamos
# en las 4 categorias que usa el HTML (POR/DEF/MED/DEL).
POSITION_MAP = {
    # Goalkeeper
    "Goalkeeper": "POR",
    # Defenders
    "Defence": "DEF", "Defender": "DEF",
    "Centre-Back": "DEF", "Center-Back": "DEF",
    "Left-Back": "DEF", "Right-Back": "DEF",
    "Left Wing-Back": "DEF", "Right Wing-Back": "DEF",
    # Midfielders
    "Midfielder": "MED", "Midfield": "MED",
    "Defensive Midfield": "MED",
    "Central Midfield": "MED",
    "Attacking Midfield": "MED",
    # Forwards
    "Forward": "DEL", "Offence": "DEL",
    "Centre-Forward": "DEL", "Center-Forward": "DEL",
    "Striker": "DEL",
    "Left Winger": "DEL", "Right Winger": "DEL",
    "Left Forward": "DEL", "Right Forward": "DEL",
}


def map_position(fd_position: str | None) -> str:
    if not fd_position:
        return "MED"
    return POSITION_MAP.get(fd_position, "MED")


def fetch_competition_teams(comp_fd_code: str) -> list[dict]:
    """Llama /competitions/{code}/teams. Free tier soportado."""
    data = _fd_get(f"/competitions/{comp_fd_code}/teams")
    return data.get("teams", [])


def delete_squad(eq_id: int) -> None:
    """Borra todos los jugadores de un equipo. Lanza si falla."""
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/jugadores?equipo_id=eq.{eq_id}",
        headers=_headers({"Prefer": "return=minimal"}),
        method="DELETE",
    )
    urllib.request.urlopen(req, timeout=30).read()


def upsert_squad(eq_id: int, squad_payload: list[dict]) -> None:
    if squad_payload:
        sb_post("jugadores", squad_payload, prefer="return=minimal")


def build_squad_payload(eq_id: int, squad: list[dict]) -> list[dict]:
    rows = []
    for p in squad:
        name = p.get("name")
        if not name:
            continue
        rows.append({
            "nombre": name,
            "equipo_id": eq_id,
            "posicion": map_position(p.get("position")),
            "nacionalidad": p.get("nationality"),
            "fecha_nac": p.get("dateOfBirth"),
            # Rating: football-data.org free tier no lo provee, default 70.
            # Cuando sumemos una fuente paga (API-Football, etc.) lo reemplazamos.
            "rating": 70,
        })
    return rows


def fetch_competition_full(comp_fd_code: str) -> dict:
    """Devuelve el response completo incluyendo el bloque 'competition' (con emblem)."""
    return _fd_get(f"/competitions/{comp_fd_code}/teams")


def update_liga_emblem(liga_id: int, emblem_url: str | None, dry_run: bool) -> bool:
    """Actualiza ligas.logo_url si esta vacio."""
    if not emblem_url:
        return False
    rows = sb_get(f"ligas?select=id,logo_url&id=eq.{liga_id}")
    if not rows or rows[0].get("logo_url"):
        return False
    if dry_run:
        print(f"  [dry-run] liga id={liga_id} logo_url -> {emblem_url}")
        return True
    try:
        sb_patch(f"ligas?id=eq.{liga_id}", {"logo_url": emblem_url})
        print(f"  + liga id={liga_id}: logo_url actualizado")
        return True
    except Exception as e:
        print(f"  ! patch logo liga {liga_id}: {e}")
        return False


def create_missing_equipo(sync: SupabaseSync, slug: str, fd_team: dict,
                          liga_id: int, dry_run: bool) -> int | None:
    """Crea un equipo que esta en football-data.org pero no en Supabase."""
    name = fd_team.get("shortName") or fd_team.get("name") or slug
    col_p, col_s = TEAM_COLORS.get(slug, ("#1f2937", "#ffffff"))
    payload = {
        "nombre": name,
        "abreviacion": (fd_team.get("tla") or slug.upper().replace("_", ""))[:5],
        "liga_id": liga_id,
        "color_prim": col_p,
        "color_sec": col_s,
        "pais": TEAM_COUNTRY.get(slug) or LIGA_TO_PAIS.get(liga_id, "Europa"),
        "escudo_url": fd_team.get("crest"),
        "fundacion": fd_team.get("founded"),
        "estadio": fd_team.get("venue"),
    }
    if dry_run:
        print(f"  [dry-run] crear equipo {slug}: {payload}")
        return None
    try:
        res = sb_post("equipos", [payload], prefer="return=representation")
        new_id = int(res[0]["id"])
        sync.slug_to_id[slug] = new_id
        sync.id_to_slug[new_id] = slug
        print(f"  + equipo CREADO: {slug:25} id={new_id}  ({name})  "
              f"fundacion={payload['fundacion']}  estadio={payload['estadio']!r}")
        return new_id
    except Exception as e:
        print(f"  ! crear equipo {slug}: {e}")
        return None


def sync_all(dry_run: bool = False, sleep_between_comps: float = 7.0,
             create_missing: bool = True) -> dict:
    """Recorre todas las competitions y sincroniza metadata + squads + logos."""
    sync = SupabaseSync()
    stats = {
        "competitions_seen": 0,
        "teams_seen": 0,
        "teams_matched": 0,
        "teams_created": 0,
        "metadata_updates": 0,
        "logos_ligas_updated": 0,
        "squads_replaced": 0,
        "players_inserted": 0,
        "delete_failures": 0,
        "errors": 0,
    }

    for comp in COMPETITIONS:
        if not comp.fd_code:
            continue
        stats["competitions_seen"] += 1
        print(f"\n[squads] === {comp.code} ({comp.fd_code}) ===")
        try:
            full = fetch_competition_full(comp.fd_code)
        except Exception as e:
            print(f"  ! error fetching teams para {comp.fd_code}: {e}")
            stats["errors"] += 1
            time.sleep(sleep_between_comps)
            continue

        # Update logo de la liga
        liga_id = LEAGUE_ALIAS.get(comp.code) or LEAGUE_ALIAS.get(comp.fd_code)
        if liga_id:
            emblem = (full.get("competition") or {}).get("emblem")
            if update_liga_emblem(liga_id, emblem, dry_run):
                stats["logos_ligas_updated"] += 1

        teams = full.get("teams", [])
        print(f"  + {len(teams)} equipos en {comp.code}")
        for team in teams:
            stats["teams_seen"] += 1
            team_name = team.get("shortName") or team.get("name") or ""
            slug = canonical(team_name)
            eq_id = sync.slug_to_id.get(slug)

            # Crear el equipo si no existe (cuando create_missing=True)
            if not eq_id:
                if create_missing and liga_id:
                    eq_id = create_missing_equipo(sync, slug, team, liga_id, dry_run)
                    if eq_id:
                        stats["teams_created"] += 1
                if not eq_id:
                    continue
            else:
                stats["teams_matched"] += 1

            # 1) Update metadata: fundacion + estadio
            patch = {}
            if team.get("founded"):
                patch["fundacion"] = team["founded"]
            if team.get("venue"):
                patch["estadio"] = team["venue"]
            if patch:
                if dry_run:
                    print(f"  [dry-run] metadata {slug:25} id={eq_id}: {patch}")
                else:
                    try:
                        sb_patch(f"equipos?id=eq.{eq_id}", patch)
                        stats["metadata_updates"] += 1
                    except Exception as e:
                        print(f"  ! patch metadata {slug}: {e}")
                        stats["errors"] += 1

            # 2) Squad replacement
            squad = team.get("squad", [])
            if not squad:
                continue
            payload = build_squad_payload(eq_id, squad)
            if not payload:
                continue

            if dry_run:
                print(f"  [dry-run] squad {slug:25} id={eq_id}: {len(payload)} jugadores")
                stats["squads_replaced"] += 1
                stats["players_inserted"] += len(payload)
                continue

            # Try delete (cascade-aware). Si falla, igual intentamos insertar.
            try:
                delete_squad(eq_id)
            except Exception as e:
                # FK sin CASCADE -> mantenemos los jugadores existentes
                stats["delete_failures"] += 1
                print(f"  - delete jugadores fallo para {slug} (probable FK sin CASCADE). "
                      f"Skipping insert para evitar duplicados.")
                continue

            try:
                upsert_squad(eq_id, payload)
                stats["squads_replaced"] += 1
                stats["players_inserted"] += len(payload)
                print(f"  + squad {slug:25} id={eq_id}: {len(payload)} jugadores")
            except Exception as e:
                print(f"  ! insert squad {slug}: {e}")
                stats["errors"] += 1

        # Sleep entre competitions (free tier: 10 req/min)
        time.sleep(sleep_between_comps)

    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-create-missing", action="store_true",
                    help="No crear equipos faltantes en Supabase (solo actualizar existentes)")
    args = ap.parse_args()

    print(f"[squads] iniciando (dry_run={args.dry_run}, create_missing={not args.no_create_missing})")
    stats = sync_all(args.dry_run, create_missing=not args.no_create_missing)

    print(f"\n[squads] === resumen ===")
    print(f"  competitions vistas:    {stats['competitions_seen']}")
    print(f"  equipos vistos:         {stats['teams_seen']}")
    print(f"  equipos matcheados:     {stats['teams_matched']}")
    print(f"  equipos CREADOS:        {stats['teams_created']}")
    print(f"  logos ligas updated:    {stats['logos_ligas_updated']}")
    print(f"  metadata actualizada:   {stats['metadata_updates']}")
    print(f"  squads reemplazados:    {stats['squads_replaced']}")
    print(f"  jugadores insertados:   {stats['players_inserted']}")
    print(f"  delete failures (FK):   {stats['delete_failures']}")
    print(f"  errores:                {stats['errors']}")


if __name__ == "__main__":
    main()

```

---

## `src/ingest_fbref_stats.py`

```python
"""
Ingest de estadísticas de jugadores desde Understat vía la librería soccerdata.

Understat provee stats detalladas por jugador (goles, asistencias, minutos,
xG, xA, shots, key_passes, etc.) para las top 5 ligas europeas.

Flujo:
1. Por cada liga top 5, llama a Understat.read_player_season_stats()
2. Para cada fila (un jugador de un equipo en la temporada):
   a. Matchea el equipo via slug canónico
   b. Matchea el jugador con los nombres existentes en Supabase (fuzzy match)
   c. UPSERT en estadisticas_jugador

Requiere SOLO: que la tabla `jugadores` ya tenga el plantel cargado (lo hace
ingest_squads.py). El matching es por nombre dentro del equipo.

Nota: Understat usa AÑO simple para temporada (2024 = 2024-25). Aceptamos
ambos formatos en el argumento --season.
"""
from __future__ import annotations
import argparse
import re
import unicodedata
from typing import Any
import pandas as pd

from .team_normalize import canonical
from .supabase_writer import sb_get, sb_post
from .supabase_sync import SupabaseSync


# Mapeo Understat league name -> nuestro competition code interno
UNDERSTAT_LEAGUES: dict[str, str] = {
    "ENG-Premier League": "EPL",
    "ESP-La Liga":        "LL",
    "ITA-Serie A":        "SA",
    "GER-Bundesliga":     "BL",
    "FRA-Ligue 1":        "L1",
}


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s or "")
                   if unicodedata.category(c) != "Mn")


def _normalize_name(name: str) -> str:
    """Normaliza un nombre de jugador para matching robusto."""
    n = _strip_accents(name).lower()
    n = re.sub(r"[^a-z0-9]+", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _safe_int(val: Any) -> int:
    try:
        if pd.isna(val):
            return 0
        return int(float(val))
    except (TypeError, ValueError):
        return 0


def _best_player_match(target_name: str, candidates: list[tuple[int, str]],
                       threshold: int = 60) -> int | None:
    """
    Devuelve el id del jugador con mejor match de nombre.
    candidates: lista de (id, nombre).
    threshold 0-100 de rapidfuzz (default 60, bajado desde 70 para mejor recall).
    """
    from rapidfuzz import fuzz, process
    if not candidates:
        return None
    target_norm = _normalize_name(target_name)
    options = [(eid, _normalize_name(n)) for eid, n in candidates]
    choices = {eid: norm for eid, norm in options}
    result = process.extractOne(target_norm, choices, scorer=fuzz.WRatio)
    if not result:
        return None
    _, score, eid = result
    if score < threshold:
        return None
    return eid


def _dedupe_payloads(plist: list[dict]) -> tuple[list[dict], int]:
    """
    Dedupa payloads del mismo batch por (jugador_id, temporada).
    Mantiene la fila con mayor `partidos` (más data = más confiable).
    Devuelve (dedupada, cantidad_descartada).
    """
    seen: dict[tuple, dict] = {}
    duplicates = 0
    for p in plist:
        key = (p["jugador_id"], p["temporada"])
        existing = seen.get(key)
        if existing is None:
            seen[key] = p
        else:
            duplicates += 1
            if p.get("partidos", 0) > existing.get("partidos", 0):
                seen[key] = p
    return list(seen.values()), duplicates


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """soccerdata devuelve columnas multi-level. Las aplanamos."""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        # Tomamos el segundo nivel si existe, sino el primero
        df.columns = [
            (c[1] if c[1] else c[0]).strip() if isinstance(c, tuple) else c
            for c in df.columns
        ]
    return df


def fetch_player_stats(league: str, seasons: list[str]) -> pd.DataFrame:
    """Llama a soccerdata.Understat para una liga y temporada(s)."""
    import soccerdata as sd
    understat = sd.Understat(leagues=league, seasons=seasons,
                             no_cache=False, no_store=False)
    df = understat.read_player_season_stats()
    print(f"  · raw shape: {df.shape}, index_levels: {df.index.nlevels}, "
          f"col_levels: {df.columns.nlevels if hasattr(df.columns, 'nlevels') else 1}")
    df = _flatten_columns(df)
    if df.index.nlevels >= 1:
        try:
            df = df.reset_index()
        except Exception:
            pass
    return df


def extract_stats(row: pd.Series) -> dict:
    """Extrae las stats que nos interesan en el formato de Supabase.
    Understat columns: games, time, goals, xG, assists, xA, shots,
    key_passes, yellow_cards, red_cards, npg, npxG, etc.
    """
    return {
        "partidos":    _safe_int(row.get("games") or row.get("apps") or row.get("matches")),
        "minutos":     _safe_int(row.get("time") or row.get("minutes")),
        "goles":       _safe_int(row.get("goals")),
        "asistencias": _safe_int(row.get("assists")),
        "amarillas":   _safe_int(row.get("yellow_cards") or row.get("yellows")),
        "rojas":       _safe_int(row.get("red_cards") or row.get("reds")),
    }


def sync_league(sync: SupabaseSync, league: str, our_code: str,
                seasons: list[str], temporada_label: str,
                dry_run: bool) -> dict:
    print(f"\n[stats] === {our_code} ({league}) ===")
    stats = {"rows_seen": 0, "team_matched": 0, "player_matched": 0,
             "upserted": 0, "no_team": 0, "no_player": 0, "errors": 0}

    try:
        df = fetch_player_stats(league, seasons)
    except Exception as e:
        import traceback
        print(f"  ! error fetching {league}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return stats

    print(f"  + {len(df)} filas obtenidas. Columnas (primeras 20): "
          f"{list(df.columns)[:20]}")

    if df.empty:
        print(f"  ! DataFrame vacio para {league_fbref}")
        return stats

    # Cache de jugadores por equipo para evitar requests redundantes
    players_cache: dict[int, list[tuple[int, str]]] = {}

    # Identificar columna 'team' y 'player' con matching flexible.
    # Understat usa 'team' y 'player' (en minusculas).
    def _find_col(candidates: list[str]) -> str | None:
        for c in df.columns:
            cs = str(c).lower().strip()
            if cs in candidates:
                return c
        return None
    team_col = _find_col(["team", "squad", "club", "team_title"])
    player_col = _find_col(["player", "name", "jugador", "player_name"])
    if not team_col or not player_col:
        print(f"  ! no encuentro columnas team/player. Columnas disponibles: "
              f"{list(df.columns)}")
        return stats
    print(f"  · usando team_col={team_col!r}  player_col={player_col!r}")

    payloads_per_team: dict[int, list[dict]] = {}

    for _, row in df.iterrows():
        stats["rows_seen"] += 1
        team_name = row.get(team_col)
        player_name = row.get(player_col)
        if not isinstance(team_name, str) or not isinstance(player_name, str):
            continue

        slug = canonical(team_name)
        eq_id = sync.slug_to_id.get(slug)
        if not eq_id:
            stats["no_team"] += 1
            continue
        stats["team_matched"] += 1

        # Cargar jugadores del equipo si no en cache
        if eq_id not in players_cache:
            rows = sb_get(f"jugadores?select=id,nombre&equipo_id=eq.{eq_id}")
            players_cache[eq_id] = [(int(r["id"]), r["nombre"]) for r in rows]

        jugador_id = _best_player_match(player_name, players_cache[eq_id])
        if not jugador_id:
            stats["no_player"] += 1
            continue
        stats["player_matched"] += 1

        s = extract_stats(row)
        payload = {
            "jugador_id": jugador_id,
            "equipo_id":  eq_id,
            "temporada":  temporada_label,
            **s,
        }
        payloads_per_team.setdefault(eq_id, []).append(payload)

    # Upsert por equipo (deduplicando antes para evitar errores 500)
    total_dups = 0
    for eq_id, plist in payloads_per_team.items():
        plist_clean, dups = _dedupe_payloads(plist)
        total_dups += dups
        if dry_run:
            extra = f" (descarte {dups} duplicados)" if dups else ""
            print(f"  [dry-run] {our_code} eq_id={eq_id}: {len(plist_clean)} estadisticas{extra}")
            stats["upserted"] += len(plist_clean)
            continue
        try:
            sb_post("estadisticas_jugador?on_conflict=jugador_id,temporada",
                    plist_clean,
                    prefer="resolution=merge-duplicates,return=minimal")
            stats["upserted"] += len(plist_clean)
            extra = f" (descarte {dups} dups)" if dups else ""
            print(f"  + {our_code} eq_id={eq_id}: {len(plist_clean)} stats upserted{extra}")
        except Exception as e:
            print(f"  ! upsert eq_id={eq_id}: {e}")
            stats["errors"] += 1

    if total_dups > 0:
        print(f"  · total duplicados descartados en {our_code}: {total_dups}")
    return stats


def sync_all(seasons: list[str], temporada_label: str,
             dry_run: bool = False) -> dict:
    sync = SupabaseSync()
    totals = {"rows_seen": 0, "team_matched": 0, "player_matched": 0,
              "upserted": 0, "no_team": 0, "no_player": 0, "errors": 0}
    for league, our_code in UNDERSTAT_LEAGUES.items():
        lstats = sync_league(sync, league, our_code, seasons,
                             temporada_label, dry_run)
        for k in totals:
            totals[k] += lstats.get(k, 0)
    return totals


def normalize_season_for_understat(season: str) -> str:
    """Understat usa el año del inicio: '2024-25' -> '2024'. Aceptamos ambos."""
    s = season.strip()
    if "-" in s and len(s) >= 5:
        return s.split("-")[0]
    if "/" in s:
        return s.split("/")[0]
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2024-25",
                    help="Temporada (ej: 2024-25 o 2024). Lo convertimos a formato Understat.")
    ap.add_argument("--temporada-label", default=None,
                    help="Como guardar en Supabase (default: 'YYYY/YY')")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    season_understat = normalize_season_for_understat(args.season)
    seasons = [season_understat]
    # Etiqueta default: 2024 -> 2024/25
    if args.temporada_label:
        label = args.temporada_label
    elif "-" in args.season:
        label = args.season.replace("-", "/")
    else:
        yr = int(season_understat)
        label = f"{yr}/{(yr+1) % 100:02d}"

    print(f"[stats] iniciando: season={season_understat} label={label} dry_run={args.dry_run}")
    stats = sync_all(seasons, label, args.dry_run)

    print(f"\n[stats] === resumen ===")
    print(f"  filas vistas:        {stats['rows_seen']}")
    print(f"  team matched:        {stats['team_matched']}")
    print(f"  player matched:      {stats['player_matched']}")
    print(f"  upserted:            {stats['upserted']}")
    print(f"  no_team:             {stats['no_team']}")
    print(f"  no_player:           {stats['no_player']}")
    print(f"  errores:             {stats['errors']}")


if __name__ == "__main__":
    main()

```

---

## `src/player_ratings.py`

```python
"""
Calcula y actualiza `jugadores.rating` en Supabase.

La fuente principal son las filas de `estadisticas_jugador` cargadas desde
Understat. Si un jugador no tiene stats, se usa un fallback conservador basado
en edad/posicion para evitar dejar todo clavado en 70.
"""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from .supabase_writer import sb_get, sb_patch


PAGE_SIZE = 1000
VALID_POSITIONS = {"POR", "DEF", "MED", "DEL"}
EAFC26_API = "https://api.msmc.cc/api/fc26/player/name/{name}"
EAFC26_CSV_URL = (
    "https://raw.githubusercontent.com/ismailoksuz/EAFC26-DataHub/"
    "main/data/players.csv"
)
EA_CACHE_PATH = Path("data/eafc26_ratings_cache.json")


@dataclass(frozen=True)
class RatingBreakdown:
    rating: int
    minutes: float
    production: float
    age: float
    discipline: float
    source: str


def strip_accents(value: str) -> str:
    import unicodedata

    value = "" if value is None else str(value)
    return "".join(
        c for c in unicodedata.normalize("NFD", value)
        if unicodedata.category(c) != "Mn"
    )


def norm_text(value: str | None) -> str:
    import re

    text = strip_accents(value or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\b(fc|cf|afc|sc|ac|club|de|the)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


TEAM_ALIASES = {
    "man city": "manchester city",
    "manchester city": "manchester city",
    "man united": "manchester united",
    "man utd": "manchester united",
    "inter milan": "inter",
    "inter milán": "internazionale",
    "internazionale": "inter",
    "lombardia": "inter",
    "lombardia fc": "inter",
    "atleti": "atletico madrid",
    "atletico de madrid": "atletico madrid",
    "bayern munich": "bayern munchen",
    "fc bayern munchen": "bayern munchen",
    "psg": "paris saint germain",
}


def canonical_team(value: str | None) -> str:
    text = norm_text(value)
    return TEAM_ALIASES.get(text, text)


def paged_get(path: str, page_size: int = PAGE_SIZE) -> list[dict]:
    """Lee todas las paginas de un endpoint PostgREST usando limit/offset."""
    rows: list[dict] = []
    sep = "&" if "?" in path else "?"
    offset = 0
    while True:
        page = sb_get(f"{path}{sep}limit={page_size}&offset={offset}")
        rows.extend(page)
        if len(page) < page_size:
            return rows
        offset += page_size


def load_ea_cache(path: Path = EA_CACHE_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_ea_cache(cache: dict, path: Path = EA_CACHE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def load_eafc26_csv(source: str = EAFC26_CSV_URL) -> list[dict]:
    import pandas as pd

    df = pd.read_csv(
        source,
        usecols=[
            "player_id", "short_name", "long_name", "overall", "potential",
            "club_name", "league_name", "age", "player_positions",
        ],
        low_memory=False,
    )
    return df.to_dict("records")


def build_eafc_index(rows: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for row in rows:
        for field in ("short_name", "long_name"):
            key = norm_text(str(row.get(field) or ""))
            if key:
                index.setdefault(key, []).append(row)
    return index


def eafc_rating_from_index(player: dict, index: dict[str, list[dict]]) -> tuple[int | None, str]:
    name = str(player.get("nombre") or "")
    keys = [norm_text(name)]
    parts = keys[0].split()
    if len(parts) >= 2:
        # SoFIFA a veces usa "F. Valverde" mientras football-data trae nombre largo.
        keys.append(norm_text(f"{parts[0][0]} {parts[-1]}"))

    candidates: list[dict] = []
    seen_ids: set[str] = set()
    for key in keys:
        for row in index.get(key, []):
            rid = str(row.get("player_id"))
            if rid not in seen_ids:
                candidates.append(row)
                seen_ids.add(rid)
    if not candidates:
        return None, "not_found"

    local_team = ((player.get("equipo") or {}) or {}).get("nombre")
    team_hits = [row for row in candidates if team_matches(local_team, row.get("club_name"))]
    if team_hits:
        candidates = team_hits
    elif len(candidates) > 1:
        return None, "team_mismatch"

    # Si quedan varios, elegimos el mayor OVR: en duplicados suele ser la carta/base mas relevante.
    best = max(candidates, key=lambda r: _safe_num(r.get("overall")))
    try:
        return int(best["overall"]), "eafc26_csv"
    except (TypeError, ValueError):
        return None, "bad_ovr"


def fetch_eafc26_player(name: str, timeout: int = 20) -> dict | None:
    quoted = urllib.parse.quote(name)
    req = urllib.request.Request(
        EAFC26_API.format(name=quoted),
        headers={"User-Agent": "FutPronostico/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if not isinstance(data, dict) or not data.get("OVR"):
        return None
    return data


def team_matches(local_team: str | None, ea_team: str | None) -> bool:
    if not ea_team:
        return True
    local = canonical_team(local_team)
    remote = canonical_team(ea_team)
    if not local or not remote:
        return True
    return local == remote or local in remote or remote in local


def eafc_rating_for_player(player: dict, cache: dict,
                           sleep_seconds: float = 0.0) -> tuple[int | None, str]:
    name = str(player.get("nombre") or "").strip()
    if not name:
        return None, "missing_name"
    key = norm_text(name)
    item = cache.get(key)
    if item is None:
        data = fetch_eafc26_player(name)
        item = {"found": bool(data), "data": data}
        cache[key] = item
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)

    if not item.get("found"):
        return None, "not_found"
    data = item.get("data") or {}
    local_team = ((player.get("equipo") or {}) or {}).get("nombre")
    if not team_matches(local_team, data.get("Team")):
        return None, "team_mismatch"
    try:
        return int(data["OVR"]), "eafc26"
    except (TypeError, ValueError):
        return None, "bad_ovr"


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError:
        return None


def age_years(fecha_nac: str | None, today: date | None = None) -> float | None:
    born = parse_date(fecha_nac)
    if not born:
        return None
    today = today or date.today()
    return (today - born).days / 365.25


def latest_season(stats_rows: list[dict]) -> str:
    seasons = {str(r.get("temporada") or "") for r in stats_rows if r.get("temporada")}
    if not seasons:
        raise RuntimeError("No hay temporadas en estadisticas_jugador")

    def start_year(label: str) -> int:
        head = label.replace("-", "/").split("/")[0]
        try:
            return int(head)
        except ValueError:
            return 0

    return max(seasons, key=start_year)


def _safe_num(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _age_component(position: str, age: float | None) -> float:
    if age is None:
        return 0.0
    peaks = {"POR": 29.0, "DEF": 27.0, "MED": 26.0, "DEL": 25.0}
    peak = peaks.get(position, 26.0)
    component = 4.0 - 0.35 * abs(age - peak)
    if age < 20:
        component -= 1.0
    if age > 34:
        component -= 0.4 * (age - 34)
    return max(-5.0, min(4.0, component))


def _fallback_rating(position: str, fecha_nac: str | None,
                     today: date | None = None) -> RatingBreakdown:
    age = age_years(fecha_nac, today)
    base = 68.0
    if age is not None:
        if age <= 20:
            base += 3.0
        elif age <= 23:
            base += 2.0
        elif age <= 29:
            base += 1.0
        elif age > 33:
            base -= 1.0
    rating = int(round(max(64.0, min(72.0, base))))
    return RatingBreakdown(rating, 0.0, 0.0, 0.0, 0.0, "fallback")


def rate_player(player: dict, stat: dict | None,
                today: date | None = None) -> RatingBreakdown:
    position = str(player.get("posicion") or "MED").upper()
    if position not in VALID_POSITIONS:
        position = "MED"
    if not stat:
        return _fallback_rating(position, player.get("fecha_nac"), today)

    minutes = _safe_num(stat.get("minutos"))
    matches = _safe_num(stat.get("partidos"))
    goals = _safe_num(stat.get("goles"))
    assists = _safe_num(stat.get("asistencias"))
    yellows = _safe_num(stat.get("amarillas"))
    reds = _safe_num(stat.get("rojas"))

    nineties = max(minutes / 90.0, 1.0)
    availability = min(minutes / 2700.0, 1.0)
    minutes_component = 18.0 * availability
    appearances_component = 4.0 * min(matches / 38.0, 1.0)

    weights = {
        "POR": (0.05, 0.10, 4.0),
        "DEF": (0.30, 0.30, 10.0),
        "MED": (0.45, 0.75, 16.0),
        "DEL": (0.75, 0.45, 18.0),
    }
    goal_w, assist_w, cap = weights[position]
    contribution_p90 = (goals * goal_w + assists * assist_w) / nineties
    sample_factor = min(1.0, math.sqrt(minutes / 900.0)) if minutes > 0 else 0.0
    production_component = min(cap, contribution_p90 * cap * 1.2) * sample_factor

    age_component = _age_component(position, age_years(player.get("fecha_nac"), today))
    discipline_penalty = min(5.0, yellows * 0.12 + reds * 1.4)

    rating = (
        55.0
        + minutes_component
        + appearances_component
        + production_component
        + age_component
        - discipline_penalty
    )
    rating_i = int(round(max(40.0, min(99.0, rating))))
    return RatingBreakdown(
        rating=rating_i,
        minutes=round(minutes_component + appearances_component, 2),
        production=round(production_component, 2),
        age=round(age_component, 2),
        discipline=round(discipline_penalty, 2),
        source="stats",
    )


def choose_stats(stats_rows: list[dict], season: str) -> dict[int, dict]:
    """Devuelve una fila de stats por jugador para la temporada elegida."""
    selected: dict[int, dict] = {}
    for row in stats_rows:
        if str(row.get("temporada") or "") != season:
            continue
        jid = int(row["jugador_id"])
        current = selected.get(jid)
        if current is None or _safe_num(row.get("minutos")) > _safe_num(current.get("minutos")):
            selected[jid] = row
    return selected


def build_updates(season: str | None = None,
                  today: date | None = None,
                  prefer_eafc: bool = False,
                  eafc_csv: str = EAFC26_CSV_URL,
                  eafc_api_fallback: bool = False,
                  refresh_eafc: bool = False,
                  eafc_sleep: float = 0.0,
                  scan_limit: int | None = None) -> tuple[list[dict], dict]:
    players = paged_get(
        "jugadores?select=id,nombre,posicion,fecha_nac,rating,equipo_id,"
        "equipo:equipos(nombre)&order=id"
    )
    if scan_limit:
        players = players[:scan_limit]
    stats_rows = paged_get(
        "estadisticas_jugador?select=jugador_id,temporada,equipo_id,partidos,minutos,"
        "goles,asistencias,amarillas,rojas"
    )
    season = season or latest_season(stats_rows)
    stats_by_player = choose_stats(stats_rows, season)
    ea_cache = load_ea_cache() if prefer_eafc else {}
    ea_index = build_eafc_index(load_eafc26_csv(eafc_csv)) if prefer_eafc else {}
    if refresh_eafc:
        ea_cache = {}

    updates: list[dict] = []
    summary = {
        "season": season,
        "rating_source": "eafc26+model" if prefer_eafc else "model",
        "players": len(players),
        "stats_rows": len(stats_rows),
        "eafc26": 0,
        "eafc26_not_found": 0,
        "eafc26_team_mismatch": 0,
        "eafc26_api_fallback": 0,
        "with_stats": 0,
        "fallback": 0,
        "changed": 0,
        "unchanged": 0,
        "min_rating": 100,
        "max_rating": 0,
    }

    for player in players:
        stat = stats_by_player.get(int(player["id"]))
        ea_rating = None
        ea_reason = ""
        if prefer_eafc:
            ea_rating, ea_reason = eafc_rating_from_index(player, ea_index)
            if ea_rating is None and eafc_api_fallback:
                ea_rating, ea_reason = eafc_rating_for_player(
                    player, ea_cache, sleep_seconds=eafc_sleep
                )
                if ea_rating is not None:
                    summary["eafc26_api_fallback"] += 1
        if ea_rating is not None:
            breakdown = RatingBreakdown(ea_rating, 0.0, 0.0, 0.0, 0.0, "eafc26")
            summary["eafc26"] += 1
        else:
            if prefer_eafc:
                if ea_reason == "team_mismatch":
                    summary["eafc26_team_mismatch"] += 1
                else:
                    summary["eafc26_not_found"] += 1
            breakdown = rate_player(player, stat, today=today)
        if breakdown.source == "stats":
            summary["with_stats"] += 1
        elif breakdown.source == "fallback":
            summary["fallback"] += 1

        old_rating = player.get("rating")
        new_rating = breakdown.rating
        summary["min_rating"] = min(summary["min_rating"], new_rating)
        summary["max_rating"] = max(summary["max_rating"], new_rating)
        if old_rating == new_rating:
            summary["unchanged"] += 1
            continue
        summary["changed"] += 1
        updates.append({
            "id": int(player["id"]),
            "nombre": player.get("nombre"),
            "equipo_id": player.get("equipo_id"),
            "old_rating": old_rating,
            "rating": new_rating,
            "source": breakdown.source,
            "breakdown": breakdown,
        })

    if prefer_eafc:
        save_ea_cache(ea_cache)
    if summary["players"] == 0:
        summary["min_rating"] = 0
    return updates, summary


def apply_updates(updates: list[dict], dry_run: bool,
                  limit: int | None = None) -> int:
    selected = updates[:limit]
    applied = 0
    if not dry_run:
        ids_by_rating: dict[int, list[int]] = {}
        for item in selected:
            ids_by_rating.setdefault(int(item["rating"]), []).append(int(item["id"]))
        for rating, ids in sorted(ids_by_rating.items()):
            for i in range(0, len(ids), 200):
                chunk = ids[i:i + 200]
                id_filter = ",".join(str(x) for x in chunk)
                sb_patch(f"jugadores?id=in.({id_filter})", {"rating": rating})
                applied += len(chunk)
        return applied

    for item in selected:
        if dry_run:
            print(
                f"  [dry-run] jugador_id={item['id']} {item['nombre']}: "
                f"{item['old_rating']} -> {item['rating']} ({item['source']})"
            )
        applied += 1
    return applied


def main() -> None:
    load_dotenv()
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default=None,
                    help="Temporada a usar (default: ultima disponible en estadisticas_jugador)")
    ap.add_argument("--prefer-eafc", action="store_true",
                    help="Usar EA FC 26 OVR gratis como fuente principal cuando matchee.")
    ap.add_argument("--eafc-csv", default=EAFC26_CSV_URL,
                    help="URL o path al CSV FC26 con columnas overall/club_name.")
    ap.add_argument("--eafc-api-fallback", action="store_true",
                    help="Si el CSV no matchea, consulta la API publica por nombre.")
    ap.add_argument("--refresh-eafc-cache", action="store_true",
                    help="Ignora data/eafc26_ratings_cache.json y vuelve a consultar EAFC.")
    ap.add_argument("--eafc-sleep", type=float, default=0.05,
                    help="Pausa entre requests nuevas a la API EAFC26.")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None,
                    help="Limita la cantidad de updates aplicados/imprimidos")
    ap.add_argument("--scan-limit", type=int, default=None,
                    help="Limita cuantos jugadores se escanean/calculan.")
    args = ap.parse_args()

    updates, summary = build_updates(
        args.season,
        prefer_eafc=args.prefer_eafc,
        eafc_csv=args.eafc_csv,
        eafc_api_fallback=args.eafc_api_fallback,
        refresh_eafc=args.refresh_eafc_cache,
        eafc_sleep=args.eafc_sleep,
        scan_limit=args.scan_limit,
    )
    print("[player-ratings] resumen:", summary)
    preview = sorted(updates, key=lambda x: x["rating"], reverse=True)[:10]
    if preview:
        print("[player-ratings] top cambios:")
        for item in preview:
            print(
                f"  {item['nombre']:<28} {item['old_rating']} -> {item['rating']} "
                f"({item['source']})"
            )
    applied = apply_updates(updates, dry_run=args.dry_run, limit=args.limit)
    action = "simulados" if args.dry_run else "aplicados"
    print(f"[player-ratings] updates {action}: {applied}")


if __name__ == "__main__":
    main()

```

---

## `src/elo.py`

```python
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

```

---

## `src/dixon_coles.py`

```python
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

```

---

## `src/features.py`

```python
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


def _team_history_view(matches: pd.DataFrame) -> pd.DataFrame:
    """Pivota la tabla match-centric a team-centric (dos filas por partido)."""
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
    return pd.concat([home[keep], away[keep]], ignore_index=True)


def _rolling_team_stats(team_view: pd.DataFrame,
                        windows: tuple[int, ...] = (3, 5, 10)) -> pd.DataFrame:
    """
    Para cada partido del equipo, calcula media de goles a favor/contra
    en los últimos N partidos *previos*. EWMA con halflife=5 también.
    """
    df = team_view.sort_values(["team_id", "kickoff_ts_utc"]).copy()
    df["gd"] = df["goals_for"] - df["goals_against"]
    g = df.groupby("team_id", sort=False)
    for w in windows:
        df[f"gf_roll{w}"] = g["goals_for"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        df[f"ga_roll{w}"] = g["goals_against"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
        df[f"gd_roll{w}"] = g["gd"].shift(1).rolling(w, min_periods=1).mean().reset_index(level=0, drop=True)
    df["gd_ewma5"] = g["gd"].shift(1).ewm(halflife=5, min_periods=1).mean().reset_index(level=0, drop=True)
    df["gd_ewma10"] = g["gd"].shift(1).ewm(halflife=10, min_periods=1).mean().reset_index(level=0, drop=True)
    df["momentum"] = df["gd_ewma5"] - df["gd_ewma10"]
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


def build_team_features(matches: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve una tabla con todas las features team-match-level calculadas
    estrictamente con info previa al partido (shift(1) + ventanas rolling).
    """
    matches = matches.copy()
    matches["kickoff_ts_utc"] = pd.to_datetime(matches["kickoff_ts_utc"], utc=True)
    tv = _team_history_view(matches)
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

        team_feats = build_team_features(m)
        team_feats_h = team_feats[team_feats["is_home"] == 1].add_prefix("home_")
        team_feats_a = team_feats[team_feats["is_home"] == 0].add_prefix("away_")
        team_feats_h = team_feats_h.rename(columns={"home_match_id": "match_id"})
        team_feats_a = team_feats_a.rename(columns={"away_match_id": "match_id"})

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
                                                               "rest_", "matches_last_",
                                                               "fatigue_", "momentum"))}

        elo_feats = pre_match_diff(elo_state, home, away, is_neutral=is_neutral)
        dc_feats = pre_match_features(dc_state, home, away, is_neutral=is_neutral)
        mkt_feats = _odds_to_features(pd.Series(odds_row or {}))

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
            **h, **a,
        }
        row["rest_diff"] = (h.get("home_rest_days") or 0) - (a.get("away_rest_days") or 0)
        row["congestion_diff"] = (h.get("home_matches_last_14d") or 0) - (a.get("away_matches_last_14d") or 0)
        row["fatigue_diff"] = (h.get("home_fatigue_idx") or 0) - (a.get("away_fatigue_idx") or 0)
        row["gd5_diff"] = (h.get("home_gd_roll5") or 0) - (a.get("away_gd_roll5") or 0)
        row["momentum_diff"] = (h.get("home_momentum") or 0) - (a.get("away_momentum") or 0)
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
    ]

```

---

## `src/xgb_model.py`

```python
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

```

---

## `src/train.py`

```python
"""
Entrenamiento final del modelo de producción.

Esquema:
    train  = partidos finalizados hasta hoy - (valid_window + test_window)
    valid  = bloque siguiente             → calibración + early stopping
    holdout= último bloque                 → reporte de métricas (no entra al fit)

Guarda artefactos en data/models/.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
import numpy as np
import pandas as pd

from .config import BACKTEST, PATHS, LABEL_MAP
from .dixon_coles import fit as fit_dc
from .elo import EloState, replay
from .features import FeatureBuilder, feature_columns
from .xgb_model import (fit_xgb, IsotonicMulticlassCalibrator,
                        save_artifacts)
from .metrics import (multi_log_loss, multi_brier, accuracy_top1,
                      market_baseline_log_loss, calibration_per_class)


def main() -> None:
    matches = pd.read_parquet(PATHS.matches)
    matches["kickoff_ts_utc"] = pd.to_datetime(matches["kickoff_ts_utc"], utc=True)
    finished = matches.dropna(subset=["home_goals", "away_goals"]).copy()
    finished = finished.sort_values("kickoff_ts_utc").reset_index(drop=True)

    now = pd.Timestamp.now(tz="UTC")
    test_end = now
    valid_end = now - pd.Timedelta(days=BACKTEST.test_window_days)
    train_end = valid_end - pd.Timedelta(days=BACKTEST.valid_window_days)

    train_raw = finished[finished["kickoff_ts_utc"] < train_end]
    if len(train_raw) < BACKTEST.min_train_matches:
        raise RuntimeError(f"Pocos partidos para entrenar: {len(train_raw)}")

    print(f"[train] {len(train_raw)} partidos hasta {train_end.date()}")
    dc_state = fit_dc(train_raw, asof_ts=train_end)
    dc_state.to_json()
    elo_state = EloState()
    replay(train_raw, elo_state)
    elo_state.to_json()

    fb = FeatureBuilder()
    full_feat = fb.build_training_table(finished, dc_state, elo_state)
    full_feat = full_feat.dropna(subset=["label"])

    train_feat = full_feat[full_feat["kickoff_ts_utc"] < train_end]
    valid_feat = full_feat[(full_feat["kickoff_ts_utc"] >= train_end) &
                            (full_feat["kickoff_ts_utc"] < valid_end)]
    holdout_feat = full_feat[(full_feat["kickoff_ts_utc"] >= valid_end) &
                              (full_feat["kickoff_ts_utc"] < test_end)]

    print(f"[train] n_train={len(train_feat)}  n_valid={len(valid_feat)}  n_holdout={len(holdout_feat)}")

    clf = fit_xgb(train_feat, valid_feat)

    X_valid = valid_feat.reindex(columns=feature_columns()).astype(float)
    valid_raw = clf.predict_proba(X_valid)
    y_valid = valid_feat["label"].map(LABEL_MAP).astype(int).values
    calibrator = IsotonicMulticlassCalibrator.fit(valid_raw, y_valid)

    holdout_metrics = {}
    if len(holdout_feat) > 0:
        X_ho = holdout_feat.reindex(columns=feature_columns()).astype(float)
        y_ho = holdout_feat["label"].map(LABEL_MAP).astype(int).values
        proba_ho = calibrator.transform(clf.predict_proba(X_ho))
        mkt_p = holdout_feat.reindex(columns=["market_p_home", "market_p_draw", "market_p_away"]).to_numpy(dtype=float)

        holdout_metrics = {
            "n": int(len(holdout_feat)),
            "log_loss": multi_log_loss(y_ho, proba_ho),
            "brier": multi_brier(y_ho, proba_ho),
            "accuracy": accuracy_top1(y_ho, proba_ho),
            "market_log_loss": market_baseline_log_loss(mkt_p, y_ho),
            "calibration": calibration_per_class(y_ho, proba_ho, n_bins=10),
        }
        print(f"[holdout] log_loss={holdout_metrics['log_loss']:.4f}  "
              f"brier={holdout_metrics['brier']:.4f}  "
              f"acc={holdout_metrics['accuracy']:.3f}  "
              f"mkt_ll={holdout_metrics['market_log_loss']}")

    meta = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "train_end": str(train_end),
        "valid_end": str(valid_end),
        "n_train": int(len(train_feat)),
        "n_valid": int(len(valid_feat)),
        "feature_columns": feature_columns(),
        "holdout_metrics": holdout_metrics,
    }
    save_artifacts(clf, calibrator, meta)
    print("[train] artefactos guardados")


if __name__ == "__main__":
    main()

```

---

## `src/train_dc.py`

```python
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

```

---

## `src/predict.py`

```python
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

```

---

## `src/evaluate.py`

```python
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

```

---

## `src/backtest.py`

```python
"""
Backtest rolling-origin (ventana expansiva) imitando operación real:

Para cada cutoff t:
    train  = todo lo anterior a t - (valid + test) days
    valid  = bloque [t - test_window - valid_window, t - test_window]  → calibración + early stopping
    test   = bloque [t - test_window, t]                                → evaluación
    cutoff t avanza step_days

En cada fold:
1) Re-ajustar Dixon-Coles con SOLO partidos hasta t_train_end.
2) Re-correr Elo desde cero hasta t_train_end.
3) Construir features sobre train+valid+test pero garantizando que Elo y DC
   visibles en la fila i son los previos a kickoff[i].
4) Entrenar XGBoost en train, calibrar isotonic en valid, evaluar en test.

Outputs:
- métricas por fold (log loss, Brier, accuracy, log loss del mercado como benchmark)
- agregados promedio y banda
- guardado en data/backtest_report.json
"""
from __future__ import annotations
import json
from dataclasses import dataclass, asdict
from pathlib import Path
import numpy as np
import pandas as pd

from .config import BACKTEST, PATHS, LABEL_MAP
from .dixon_coles import fit as fit_dc
from .elo import EloState, replay
from .features import FeatureBuilder, feature_columns
from .xgb_model import fit_xgb, IsotonicMulticlassCalibrator
from .metrics import (multi_log_loss, multi_brier, accuracy_top1,
                      market_baseline_log_loss)


@dataclass
class FoldResult:
    fold_idx: int
    train_end: str
    valid_end: str
    test_end: str
    n_train: int
    n_valid: int
    n_test: int
    log_loss: float
    brier: float
    accuracy: float
    market_log_loss: float | None


def _label_idx(df: pd.DataFrame) -> np.ndarray:
    return df["label"].map(LABEL_MAP).astype(int).values


def _market_proba(df: pd.DataFrame) -> np.ndarray:
    cols = ["market_p_home", "market_p_draw", "market_p_away"]
    return df.reindex(columns=cols).to_numpy(dtype=float)


def run_backtest(matches: pd.DataFrame) -> dict:
    df = matches.dropna(subset=["home_goals", "away_goals"]).copy()
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    df = df.sort_values("kickoff_ts_utc").reset_index(drop=True)

    if len(df) < BACKTEST.min_train_matches + 100:
        raise ValueError(f"Pocos partidos para backtest serio: {len(df)}")

    t0 = df["kickoff_ts_utc"].iloc[BACKTEST.min_train_matches]
    t_end = df["kickoff_ts_utc"].max()
    step = pd.Timedelta(days=BACKTEST.step_days)
    vw = pd.Timedelta(days=BACKTEST.valid_window_days)
    tw = pd.Timedelta(days=BACKTEST.test_window_days)

    results: list[FoldResult] = []
    cutoffs = pd.date_range(t0, t_end - tw, freq=step, tz="UTC")
    fb = FeatureBuilder()

    for i, cut in enumerate(cutoffs):
        train_end = cut - vw - tw
        valid_end = cut - tw
        test_end = cut

        train_mask = df["kickoff_ts_utc"] < train_end
        valid_mask = (df["kickoff_ts_utc"] >= train_end) & (df["kickoff_ts_utc"] < valid_end)
        test_mask = (df["kickoff_ts_utc"] >= valid_end) & (df["kickoff_ts_utc"] < test_end)

        if train_mask.sum() < BACKTEST.min_train_matches:
            continue
        if valid_mask.sum() < 30 or test_mask.sum() < 30:
            continue

        train_raw = df[train_mask].copy()
        all_known = df[train_mask | valid_mask | test_mask].copy()

        dc_state = fit_dc(train_raw, asof_ts=train_end)
        elo_state = EloState()
        replay(train_raw, elo_state)

        full_feat = fb.build_training_table(all_known, dc_state, elo_state)
        full_feat = full_feat.dropna(subset=["label"])

        train_feat = full_feat[full_feat["kickoff_ts_utc"] < train_end]
        valid_feat = full_feat[(full_feat["kickoff_ts_utc"] >= train_end) &
                                (full_feat["kickoff_ts_utc"] < valid_end)]
        test_feat = full_feat[(full_feat["kickoff_ts_utc"] >= valid_end) &
                               (full_feat["kickoff_ts_utc"] < test_end)]

        if len(test_feat) == 0 or len(valid_feat) == 0:
            continue

        clf = fit_xgb(train_feat, valid_feat)
        valid_raw_proba = clf.predict_proba(valid_feat.reindex(columns=feature_columns()).astype(float))
        calibrator = IsotonicMulticlassCalibrator.fit(valid_raw_proba, _label_idx(valid_feat))

        test_X = test_feat.reindex(columns=feature_columns()).astype(float)
        test_raw = clf.predict_proba(test_X)
        test_proba = calibrator.transform(test_raw)
        y_test = _label_idx(test_feat)

        mkt_p = _market_proba(test_feat)
        mkt_ll = market_baseline_log_loss(mkt_p, y_test)

        fr = FoldResult(
            fold_idx=i,
            train_end=str(train_end),
            valid_end=str(valid_end),
            test_end=str(test_end),
            n_train=int(train_mask.sum()),
            n_valid=int(valid_mask.sum()),
            n_test=int(test_mask.sum()),
            log_loss=multi_log_loss(y_test, test_proba),
            brier=multi_brier(y_test, test_proba),
            accuracy=accuracy_top1(y_test, test_proba),
            market_log_loss=mkt_ll,
        )
        results.append(fr)
        print(f"[fold {i}] ll={fr.log_loss:.4f}  brier={fr.brier:.4f}  "
              f"acc={fr.accuracy:.3f}  mkt_ll={fr.market_log_loss}")

    summary = {
        "n_folds": len(results),
        "log_loss_mean": float(np.mean([r.log_loss for r in results])) if results else None,
        "log_loss_std": float(np.std([r.log_loss for r in results])) if results else None,
        "brier_mean": float(np.mean([r.brier for r in results])) if results else None,
        "accuracy_mean": float(np.mean([r.accuracy for r in results])) if results else None,
        "market_log_loss_mean": float(np.nanmean([r.market_log_loss for r in results
                                                   if r.market_log_loss is not None])) if results else None,
        "folds": [asdict(r) for r in results],
    }
    PATHS.backtest_report.write_text(json.dumps(summary, indent=2))
    return summary


if __name__ == "__main__":
    import pandas as pd
    matches = pd.read_parquet(PATHS.matches)
    s = run_backtest(matches)
    print(json.dumps({k: v for k, v in s.items() if k != "folds"}, indent=2))

```

---

## `src/metrics.py`

```python
"""
Métricas para 1X2 probabilístico.

Principal: log loss (multiclass).
Complementarias: Brier score multiclass, accuracy, calibration curve.
"""
from __future__ import annotations
import numpy as np
from sklearn.metrics import log_loss, accuracy_score
from sklearn.calibration import calibration_curve


def multi_log_loss(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    return float(log_loss(y_true_idx, np.clip(proba, 1e-12, 1 - 1e-12), labels=[0, 1, 2]))


def multi_brier(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    y_oh = np.eye(3)[y_true_idx]
    return float(np.mean(np.sum((proba - y_oh) ** 2, axis=1)))


def accuracy_top1(y_true_idx: np.ndarray, proba: np.ndarray) -> float:
    return float(accuracy_score(y_true_idx, np.argmax(proba, axis=1)))


def calibration_per_class(y_true_idx: np.ndarray, proba: np.ndarray,
                          n_bins: int = 10) -> dict:
    out = {}
    for k, name in enumerate(["home", "draw", "away"]):
        y_bin = (y_true_idx == k).astype(int)
        true_p, pred_p = calibration_curve(y_bin, proba[:, k],
                                           n_bins=n_bins, strategy="quantile")
        out[name] = {"pred": pred_p.tolist(), "true": true_p.tolist()}
    return out


def market_baseline_log_loss(market_proba: np.ndarray, y_true_idx: np.ndarray,
                             mask: np.ndarray | None = None) -> float | None:
    if mask is None:
        mask = ~np.isnan(market_proba).any(axis=1)
    if mask.sum() == 0:
        return None
    return multi_log_loss(y_true_idx[mask], market_proba[mask])

```

---

## `src/supabase_writer.py`

```python
"""
Escribe pronósticos del modelo en Supabase.

Flujo:
1. Lee predictions.json generado por src.predict.
2. Por cada predicción:
   a. Mapea (home_team_name, away_team_name) → (equipo_local_id, equipo_visitante_id)
      usando TEAM_ALIAS (nombres football-data.org → ids Supabase).
   b. Mapea competition_code → liga_id usando LEAGUE_ALIAS.
   c. Busca el partido en `partidos` con (equipo_local_id, equipo_visitante_id, fecha ±6h).
   d. Si existe, deriva factor_* desde nuestras features y hace UPSERT en `pronosticos`
      por partido_id.
3. Imprime un resumen de cuántas predicciones se aplicaron / saltearon.

IMPORTANTE: requiere SUPABASE_SERVICE_KEY (rol service_role, bypasea RLS).
            Nunca commitear esa key. Solo via env var / GitHub Secrets.

NO crea partidos nuevos: si el partido no existe en Supabase, lo saltea.
Esa fue decisión explícita — los partidos los carga el usuario manualmente.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from .config import PATHS


# Supabase equipos.id → slug canónico (mismo identificador que usan DC/Elo).
# Si cambia el alias de un equipo en team_normalize.py, hay que mantenerlo
# consistente con este map.
SUPABASE_TO_SLUG: dict[int, str] = {
    1:  "real_madrid",
    2:  "barcelona",
    3:  "atletico_madrid",
    4:  "bayern_munich",
    5:  "dortmund",
    6:  "arsenal",
    7:  "man_city",
    8:  "liverpool",
    9:  "chelsea",
    10: "inter_milan",
    11: "ac_milan",
    12: "paris_sg",
}


# football-data.org team name → Supabase equipos.id
TEAM_ALIAS: dict[str, int] = {
    "Real Madrid CF":                 1,
    "Real Madrid":                    1,
    "FC Barcelona":                   2,
    "Barcelona":                      2,
    "Club Atlético de Madrid":        3,
    "Atlético Madrid":                3,
    "Atletico Madrid":                3,
    "Atlético de Madrid":             3,
    "FC Bayern München":              4,
    "Bayern München":                 4,
    "Bayern Munich":                  4,
    "Bayern Múnich":                  4,
    "Borussia Dortmund":              5,
    "Dortmund":                       5,
    "Arsenal FC":                     6,
    "Arsenal":                        6,
    "Manchester City FC":             7,
    "Manchester City":                7,
    "Man City":                       7,
    "Man. City":                      7,
    "Liverpool FC":                   8,
    "Liverpool":                      8,
    "Chelsea FC":                     9,
    "Chelsea":                        9,
    "FC Internazionale Milano":      10,
    "Inter":                          10,
    "Inter Milán":                    10,
    "Internazionale":                 10,
    "AC Milan":                       11,
    "Milan":                          11,
    "AC Milán":                       11,
    "Paris Saint-Germain FC":        12,
    "Paris Saint-Germain":           12,
    "PSG":                            12,
}

# Mapeo de competition codes -> Supabase ligas.id
# Aceptamos AMBOS: nuestros codigos internos (UCL/EPL/LL/...) y los de
# football-data.org que aparecen en matches.parquet (CL/PL/PD/...)
LEAGUE_ALIAS: dict[str, int] = {
    # Champions League
    "UCL": 1, "CL": 1,
    # La Liga
    "LL":  2, "PD": 2,
    # Premier League
    "EPL": 3, "PL": 3,
    # Serie A (mismo codigo en ambos)
    "SA":  4,
    # Bundesliga
    "BL":  5, "BL1": 5,
    # Ligue 1
    "L1":  6, "FL1": 6,
}

MATCH_FUZZ_HOURS = 6  # tolerancia para matchear partidos por fecha


# ───────── Supabase HTTP client (sin dependencias extra) ─────────

def _sb_url() -> str:
    u = os.getenv("SUPABASE_URL")
    if not u:
        raise RuntimeError("Falta SUPABASE_URL")
    return u.strip().rstrip("/")


def _sb_key() -> str:
    k = os.getenv("SUPABASE_SERVICE_KEY")
    if not k:
        raise RuntimeError("Falta SUPABASE_SERVICE_KEY (rol service_role)")
    # Strip de cualquier whitespace / newline accidental al copiar-pegar en GitHub.
    return k.strip()


def _headers(extra: dict | None = None) -> dict:
    k = _sb_key()
    h = {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def sb_get(path: str) -> list[dict]:
    req = urllib.request.Request(f"{_sb_url()}/rest/v1/{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def sb_post(path: str, body: list[dict] | dict, prefer: str = "return=representation") -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}",
        data=data,
        headers=_headers({"Prefer": prefer}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def sb_patch(path: str, body: dict, prefer: str = "return=minimal") -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}",
        data=data,
        headers=_headers({"Prefer": prefer}),
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


# ───────── Lookup de partidos ─────────

def _normalize(name: str | None) -> str:
    return (name or "").strip()


def find_partido_id(equipo_local_id: int, equipo_visitante_id: int,
                    kickoff_iso: str) -> int | None:
    """
    Busca un partido en Supabase con esos equipos y fecha cercana (±MATCH_FUZZ_HOURS).
    Devuelve el id si lo encuentra, None si no.
    """
    kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    lo = (kickoff - timedelta(hours=MATCH_FUZZ_HOURS)).isoformat()
    hi = (kickoff + timedelta(hours=MATCH_FUZZ_HOURS)).isoformat()
    q = urllib.parse.urlencode({
        "select": "id,fecha,estado",
        "equipo_local_id": f"eq.{equipo_local_id}",
        "equipo_visitante_id": f"eq.{equipo_visitante_id}",
        "fecha": f"gte.{lo}",
    })
    rows = sb_get(f"partidos?{q}&fecha=lte.{urllib.parse.quote(hi)}")
    return int(rows[0]["id"]) if rows else None


# ───────── Derivación de factores (0–100) ─────────

def _sigmoid_0_100(x: float, scale: float, center: float = 50.0) -> float:
    return float(round(center + 50.0 * math.tanh(x / scale), 1))


def derive_factors(match: dict) -> dict:
    """
    Convierte la predicción del modelo en los factor_* que espera el HTML.
    Cada factor representa "cuánto favorece al LOCAL" en escala 0-100.
    El HTML interpreta: >=65 = favorece local, <=40 = favorece visitante.

    Mapeo:
    - factor_localidad: 50 si neutral, ~75 si hay localía real.
    - factor_forma:     sigmoid del momentum_diff (xG reciente).
    - factor_tabla:     sigmoid del elo_diff_pre (ranking de fuerza).
    - factor_goles:     sigmoid del diff de λ esperadas (Dixon-Coles).
    - factor_h2h:       NULL (nuestro modelo no genera h2h directo).
    - factor_bajas:     NULL (sin datos de lesiones).
    """
    probs = match["probabilities"]
    ratings = match.get("ratings", {})
    xg = match.get("expected_goals", {})
    elo_diff = float(ratings.get("elo_diff", 0.0) or 0.0)
    lam_diff = float((xg.get("home", 0.0) or 0.0) - (xg.get("away", 0.0) or 0.0))

    is_neutral = bool(match.get("is_neutral", False))
    factor_localidad = 50.0 if is_neutral else 75.0

    factor_tabla = _sigmoid_0_100(elo_diff, scale=150.0)
    factor_goles = _sigmoid_0_100(lam_diff, scale=0.8)

    # Sin momentum directo en el JSON; usamos el spread de probabilidades como proxy
    prob_diff = float(probs["home"]) - float(probs["away"])
    factor_forma = _sigmoid_0_100(prob_diff, scale=0.30)

    return {
        "factor_localidad": factor_localidad,
        "factor_forma": factor_forma,
        "factor_tabla": factor_tabla,
        "factor_goles": factor_goles,
        "factor_h2h": None,
        "factor_bajas": None,
    }


def build_notas(match: dict) -> str:
    """Texto breve para la columna `notas`. El HTML lo muestra en la tarjeta."""
    home = match["home"]["name"]
    away = match["away"]["name"]
    xg_h = match.get("expected_goals", {}).get("home")
    xg_a = match.get("expected_goals", {}).get("away")
    elo_diff = match.get("ratings", {}).get("elo_diff")
    parts = [f"Modelo IA · DC+Elo+XGBoost"]
    if xg_h is not None and xg_a is not None:
        parts.append(f"xG esperado {home} {xg_h:.2f} - {xg_a:.2f} {away}")
    if elo_diff is not None:
        parts.append(f"d-Elo {elo_diff:+.0f}")
    return " - ".join(parts)


# ───────── Upsert principal ─────────

def upsert_pronostico(partido_id: int, match: dict, dry_run: bool = False) -> None:
    probs = match["probabilities"]
    payload = {
        "partido_id": partido_id,
        "prob_local":     round(float(probs["home"]) * 100, 1),
        "prob_empate":    round(float(probs["draw"]) * 100, 1),
        "prob_visitante": round(float(probs["away"]) * 100, 1),
        **derive_factors(match),
        "notas": build_notas(match),
    }
    if dry_run:
        print(f"  [dry-run] partido_id={partido_id} payload={payload}")
        return
    # PostgREST upsert: requiere índice único sobre partido_id en pronosticos.
    # Si no existe, lo creás con:
    #    create unique index if not exists pronosticos_partido_id_uq
    #      on pronosticos (partido_id);
    sb_post("pronosticos?on_conflict=partido_id",
            [payload],
            prefer="resolution=merge-duplicates,return=minimal")


def apply_predictions(predictions_path: Path = PATHS.predictions,
                      dry_run: bool = False) -> dict:
    """
    Modo from-json: lee predictions.json (output del pipeline XGBoost completo)
    y para cada predicción busca el partido correspondiente en Supabase usando
    el SLUG del equipo (no el nombre).

    Requiere que `supabase_sync` haya corrido primero para asegurar que los
    partidos existan en Supabase.
    """
    from .team_normalize import canonical

    doc = json.loads(predictions_path.read_text(encoding="utf-8"))

    # Cache slug -> equipos.id desde Supabase
    slug_to_id: dict[str, int] = {}
    for e in sb_get("equipos?select=id,nombre"):
        slug_to_id[canonical(e["nombre"])] = int(e["id"])
    for sid, slug in SUPABASE_TO_SLUG.items():
        slug_to_id.setdefault(slug, sid)
    print(f"[writer] cache de equipos: {len(slug_to_id)} entradas")

    stats = {"total": 0, "applied": 0, "skipped_team": 0,
             "skipped_no_partido": 0, "errors": 0}

    for match in doc.get("matches", []):
        stats["total"] += 1
        # Tras la refactorizacion a slugs, match.home.id ES el slug.
        slug_h = (match.get("home", {}) or {}).get("id")
        slug_a = (match.get("away", {}) or {}).get("id")
        name_h = (match.get("home", {}) or {}).get("name") or slug_h
        name_a = (match.get("away", {}) or {}).get("name") or slug_a
        if not slug_h or not slug_a:
            stats["skipped_team"] += 1
            continue

        eq_h = slug_to_id.get(slug_h)
        eq_a = slug_to_id.get(slug_a)
        if not eq_h or not eq_a:
            stats["skipped_team"] += 1
            missing = [s for s, eq in [(slug_h, eq_h), (slug_a, eq_a)] if not eq]
            print(f"  - sin equipo en Supabase: {missing}  ({name_h} vs {name_a})")
            continue

        try:
            pid = find_partido_id(eq_h, eq_a, match["kickoff_ts_utc"])
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! lookup error {name_h} vs {name_a}: {e}")
            continue

        if pid is None:
            stats["skipped_no_partido"] += 1
            continue

        try:
            upsert_pronostico(pid, match, dry_run=dry_run)
            stats["applied"] += 1
            print(f"  ok partido_id={pid:>5}  {name_h:<22} vs {name_a:<22}  "
                  f"H={match['probabilities']['home']:.2f} "
                  f"D={match['probabilities']['draw']:.2f} "
                  f"A={match['probabilities']['away']:.2f}")
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! upsert error partido_id={pid}: {e}")

    return stats


def apply_on_demand(dry_run: bool = False) -> dict:
    """
    Modo "on-demand": para cada partido `programado` en Supabase, calcula
    el pronóstico usando los ratings del modelo (Elo + Dixon-Coles) y hace
    upsert en `pronosticos`.

    No depende de que el matchup exista en predictions.json — usa las fuerzas
    de los equipos directamente. Ideal cuando los partidos de Supabase son
    fixtures elegidos a mano que pueden no coincidir con el calendario real.

    Nota: evaluamos aplicar un calibrador isotonico encima de DC y el resultado
    fue PEOR (ver eval del 2026-05-17). DC ya esta bien calibrado de fabrica
    porque modela conteos Poisson estructuralmente. Por eso usamos DC puro.
    """
    from .dixon_coles import DixonColesState
    from .elo import EloState

    dc = DixonColesState.from_json()
    elo = EloState.from_json()
    calibrator = None  # se mantiene None para no afectar las probabilidades

    partidos = sb_get("partidos?select=id,equipo_local_id,equipo_visitante_id,fecha,liga_id&estado=eq.programado&order=fecha")
    stats = {"total": len(partidos), "applied": 0, "skipped_no_alias": 0,
             "skipped_no_rating": 0, "errors": 0}

    for p in partidos:
        pid = int(p["id"])
        eq_h_sb = int(p["equipo_local_id"])
        eq_a_sb = int(p["equipo_visitante_id"])

        slug_h = SUPABASE_TO_SLUG.get(eq_h_sb)
        slug_a = SUPABASE_TO_SLUG.get(eq_a_sb)
        if not slug_h or not slug_a:
            print(f"  - partido_id={pid}: sin slug para uno de los equipos ({eq_h_sb},{eq_a_sb})")
            stats["skipped_no_alias"] += 1
            continue

        if slug_h not in dc.attack or slug_a not in dc.attack:
            print(f"  - partido_id={pid}: equipo sin rating en DC (h={slug_h} a={slug_a}). "
                  f"Probable que el equipo no haya jugado en las ligas bajadas.")
            stats["skipped_no_rating"] += 1
            continue

        try:
            probs = dc.probs_1x2(slug_h, slug_a, is_neutral=False)
            lam_h, lam_a = dc.lambdas(slug_h, slug_a, is_neutral=False)
            elo_h = elo.get(slug_h)
            elo_a = elo.get(slug_a)
            elo_diff = elo_h - elo_a

            # Construyo un "match" sintético con la forma que esperan
            # derive_factors() y build_notas().
            synthetic_match = {
                "probabilities": {
                    "home": probs["H"], "draw": probs["D"], "away": probs["A"],
                },
                "expected_goals": {"home": lam_h, "away": lam_a},
                "ratings": {"elo_home": elo_h, "elo_away": elo_a, "elo_diff": elo_diff},
                "is_neutral": False,
                "home": {"name": f"team-{eq_h_sb}"},
                "away": {"name": f"team-{eq_a_sb}"},
            }

            payload = {
                "partido_id": pid,
                "prob_local":     round(probs["H"] * 100, 1),
                "prob_empate":    round(probs["D"] * 100, 1),
                "prob_visitante": round(probs["A"] * 100, 1),
                **derive_factors(synthetic_match),
                "notas": (f"Modelo IA (on-demand DC+Elo) - "
                          f"xG {lam_h:.2f}-{lam_a:.2f} - d-Elo {elo_diff:+.0f}"),
            }
            if dry_run:
                print(f"  [dry-run] partido_id={pid} payload={payload}")
            else:
                sb_post("pronosticos?on_conflict=partido_id",
                        [payload],
                        prefer="resolution=merge-duplicates,return=minimal")
                print(f"  ok partido_id={pid}  "
                      f"H={probs['H']:.2f} D={probs['D']:.2f} A={probs['A']:.2f}  "
                      f"(elo {elo_h:.0f} vs {elo_a:.0f})")
            stats["applied"] += 1
        except Exception as e:
            print(f"  ! error partido_id={pid}: {e}")
            stats["errors"] += 1

    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["from-json", "on-demand"], default="on-demand",
                   help=("from-json: matchea predictions.json contra partidos reales. "
                         "on-demand: calcula prob para los partidos programados en Supabase."))
    p.add_argument("--predictions", default=str(PATHS.predictions),
                   help="Solo para --mode from-json")
    p.add_argument("--dry-run", action="store_true",
                   help="Imprime el payload sin escribir en Supabase")
    args = p.parse_args()

    print(f"[supabase-writer] mode={args.mode} dry_run={args.dry_run}")
    if args.mode == "from-json":
        stats = apply_predictions(Path(args.predictions), dry_run=args.dry_run)
    else:
        stats = apply_on_demand(dry_run=args.dry_run)
    print(f"[supabase-writer] resumen: {stats}")


if __name__ == "__main__":
    main()

```

---

## `src/supabase_sync.py`

```python
"""
Sincronización de Supabase con datos reales.

Operaciones (todas vía data en matches.parquet):

1. EQUIPOS — auto-crea/actualiza:
   - nombre, abreviacion, escudo_url
   - pais (derivado de la liga)
   - color_prim/sec (hardcoded para top teams conocidos)

2. PARTIDOS — auto-crea próximos + actualiza resultados:
   - Crea partidos con status=SCHEDULED/TIMED y kickoff en próximos N días.
   - Actualiza partidos viejos con goles reales + estado=finalizado cuando el
     match terminó (status=FINISHED en football-data.org).
   - Archiva los partidos viejos que quedaron 'programado' sin resultado.

3. FORMA_RECIENTE — calcula y persiste:
   - Para cada equipo, últimos 5 resultados (W/D/L) desde partidos finalizados.

El identificador estable es el SLUG canónico (ver team_normalize.py).
"""
from __future__ import annotations
import argparse
import urllib.parse
from datetime import timedelta
import pandas as pd

from .config import PATHS
from .team_normalize import canonical
from .supabase_writer import (sb_get, sb_post, sb_patch,
                              LEAGUE_ALIAS, SUPABASE_TO_SLUG)


# Colores oficiales (hex primario, hex secundario) por slug de equipo.
# Source: paletas oficiales de clubes. Para los que no estan aca se usa default.
TEAM_COLORS: dict[str, tuple[str, str]] = {
    "real_madrid":       ("#FEBE10", "#FFFFFF"),
    "barcelona":         ("#A50044", "#004D98"),
    "atletico_madrid":   ("#CB3524", "#FFFFFF"),
    "bayern_munich":     ("#DC052D", "#FFFFFF"),
    "dortmund":          ("#FDE100", "#000000"),
    "arsenal":           ("#EF0107", "#FFFFFF"),
    "man_city":          ("#6CABDD", "#FFFFFF"),
    "liverpool":         ("#C8102E", "#FFFFFF"),
    "chelsea":           ("#034694", "#FFFFFF"),
    "inter_milan":       ("#0068A8", "#000000"),
    "ac_milan":          ("#FB090B", "#000000"),
    "paris_sg":          ("#004170", "#DA291C"),
    "man_united":        ("#DA291C", "#FFE500"),
    "newcastle":         ("#241F20", "#FFFFFF"),
    "tottenham":         ("#FFFFFF", "#132257"),
    "nottingham_forest": ("#DD0000", "#FFFFFF"),
    "west_ham":          ("#7A263A", "#1BB1E7"),
    "wolves":            ("#FDB913", "#231F20"),
    "brighton":          ("#0057B8", "#FFCD00"),
    "crystal_palace":    ("#1B458F", "#C4122E"),
    "aston_villa":       ("#7A003C", "#94BDE9"),
    "bournemouth":       ("#DA291C", "#000000"),
    "everton":           ("#003399", "#FFFFFF"),
    "fulham":            ("#FFFFFF", "#000000"),
    "brentford":         ("#E30613", "#FBB800"),
    "burnley":           ("#6C1D45", "#99D6EA"),
    "leicester":         ("#003090", "#FDBE11"),
    "southampton":       ("#D71920", "#130C0E"),
    "leeds":             ("#FFCD00", "#1D428A"),
    "ipswich":           ("#3764A0", "#FFFFFF"),
    "sheffield_united":  ("#EE2737", "#000000"),
    "athletic_bilbao":   ("#EE2523", "#FFFFFF"),
    "real_sociedad":     ("#0067B1", "#FFFFFF"),
    "real_betis":        ("#00954C", "#FFFFFF"),
    "rayo_vallecano":    ("#DA251D", "#FFFFFF"),
    "sevilla":           ("#FFFFFF", "#D90019"),
    "valencia":          ("#FF8000", "#000000"),
    "villarreal":        ("#FCDC00", "#005CB9"),
    "celta":             ("#9BC3E8", "#E5174F"),
    "espanyol":          ("#0072CE", "#FFFFFF"),
    "getafe":            ("#003C8F", "#FFFFFF"),
    "osasuna":           ("#0A346F", "#D91A21"),
    "girona":            ("#CD2E3A", "#FFFFFF"),
    "leganes":           ("#005AAA", "#FFFFFF"),
    "valladolid":        ("#7C2C7C", "#FFFFFF"),
    "elche":             ("#FFFFFF", "#0D6E33"),
    "levante":           ("#173A8A", "#A20A2C"),
    "real_oviedo":       ("#003C8F", "#FFFFFF"),
    "sunderland":        ("#EB172B", "#FFFFFF"),
    "mallorca":          ("#A5263F", "#000000"),
    "alaves":            ("#0067B1", "#FFFFFF"),
    "las_palmas":        ("#FFE600", "#0066B3"),
    "juventus":          ("#000000", "#FFFFFF"),
    "napoli":            ("#003C82", "#FFFFFF"),
    "lazio":             ("#87CEEB", "#FFFFFF"),
    "roma":              ("#8E1F2F", "#F0BC42"),
    "atalanta":          ("#1E71B8", "#000000"),
    "bologna":           ("#9E1B32", "#172969"),
    "torino":            ("#8B1538", "#FFFFFF"),
    "fiorentina":        ("#592C82", "#FFFFFF"),
    "sassuolo":          ("#00935E", "#000000"),
    "genoa":             ("#C8102E", "#0E2B5C"),
    "lecce":             ("#FED504", "#D90019"),
    "udinese":           ("#1A1A1A", "#FFFFFF"),
    "cagliari":          ("#A5263F", "#0067B1"),
    "monza":             ("#E2001A", "#FFFFFF"),
    "empoli":            ("#005CA9", "#FFFFFF"),
    "verona":            ("#FFCD00", "#0067B1"),
    "como":              ("#003DA5", "#FFFFFF"),
    "parma":             ("#FFCD00", "#0067B1"),
    "venezia":           ("#F58220", "#000000"),
    "cremonese":         ("#A50034", "#A0A0A0"),
    "ac_pisa":           ("#001F4F", "#FFFFFF"),
    "pisa":              ("#001F4F", "#FFFFFF"),
    "leverkusen":        ("#E32221", "#000000"),
    "leipzig":           ("#DD0741", "#FFFFFF"),
    "mgladbach":         ("#FFFFFF", "#000000"),
    "wolfsburg":         ("#65B32E", "#FFFFFF"),
    "stuttgart":         ("#E32219", "#FFFFFF"),
    "fc_koln":           ("#ED1C24", "#FFFFFF"),
    "hoffenheim":        ("#1961AC", "#FFFFFF"),
    "mainz":             ("#C8102E", "#FFFFFF"),
    "union_berlin":      ("#EB1924", "#FFFFFF"),
    "heidenheim":        ("#E2001A", "#1B3675"),
    "werder_bremen":     ("#1D9053", "#FFFFFF"),
    "augsburg":          ("#BA3733", "#1D9053"),
    "freiburg":          ("#C8102E", "#FFFFFF"),
    "bochum":            ("#005CA9", "#FFFFFF"),
    "darmstadt":         ("#1A468B", "#FFFFFF"),
    "st_pauli":          ("#5A3C19", "#FFFFFF"),
    "holstein_kiel":     ("#0057B7", "#FFFFFF"),
    "eintracht_frankfurt": ("#E1000F", "#000000"),
    "marseille":         ("#2BABE3", "#FFFFFF"),
    "lyon":              ("#FFFFFF", "#D80012"),
    "saint_etienne":     ("#009639", "#FFFFFF"),
    "monaco":            ("#CE1126", "#FFFFFF"),
    "lille":             ("#E01E13", "#FFFFFF"),
    "rennes":            ("#000000", "#FFCD00"),
    "nice":              ("#ED1C24", "#000000"),
    "strasbourg":        ("#005CA9", "#FFFFFF"),
    "reims":             ("#C8102E", "#FFFFFF"),
    "lens":              ("#FFEC00", "#C8102E"),
    "brest":             ("#DA0024", "#FFFFFF"),
    "le_havre":          ("#01509C", "#000000"),
    "auxerre":           ("#0067B1", "#FFFFFF"),
    "angers":            ("#000000", "#FFFFFF"),
    "toulouse":          ("#5A3091", "#FFFFFF"),
    "nantes":            ("#FCDB07", "#005A2C"),
    "montpellier":       ("#1A4B8E", "#F36F21"),
    "metz":              ("#852A2F", "#FFFFFF"),
}


# Pais por slug (donde NO se puede derivar de la liga directamente — UCL es multi-pais).
# Si no esta aca, usamos liga.pais como fallback.
TEAM_COUNTRY: dict[str, str] = {
    # Espana
    "real_madrid": "España", "barcelona": "España", "atletico_madrid": "España",
    "athletic_bilbao": "España", "real_sociedad": "España", "real_betis": "España",
    "rayo_vallecano": "España", "sevilla": "España", "valencia": "España",
    "villarreal": "España", "celta": "España", "espanyol": "España",
    "getafe": "España", "osasuna": "España", "girona": "España",
    "leganes": "España", "valladolid": "España", "mallorca": "España",
    "alaves": "España", "las_palmas": "España",
    # Inglaterra
    "arsenal": "Inglaterra", "man_city": "Inglaterra", "liverpool": "Inglaterra",
    "chelsea": "Inglaterra", "man_united": "Inglaterra", "newcastle": "Inglaterra",
    "tottenham": "Inglaterra", "nottingham_forest": "Inglaterra", "west_ham": "Inglaterra",
    "wolves": "Inglaterra", "brighton": "Inglaterra", "crystal_palace": "Inglaterra",
    "aston_villa": "Inglaterra", "bournemouth": "Inglaterra", "everton": "Inglaterra",
    "fulham": "Inglaterra", "brentford": "Inglaterra", "burnley": "Inglaterra",
    "leicester": "Inglaterra", "southampton": "Inglaterra", "leeds": "Inglaterra",
    "ipswich": "Inglaterra", "sheffield_united": "Inglaterra",
    "sunderland": "Inglaterra",
    "elche": "España", "levante": "España", "real_oviedo": "España",
    # Italia
    "juventus": "Italia", "napoli": "Italia", "lazio": "Italia", "roma": "Italia",
    "inter_milan": "Italia", "ac_milan": "Italia", "atalanta": "Italia",
    "bologna": "Italia", "torino": "Italia", "fiorentina": "Italia",
    "sassuolo": "Italia", "genoa": "Italia", "lecce": "Italia", "udinese": "Italia",
    "cagliari": "Italia", "monza": "Italia", "empoli": "Italia", "verona": "Italia",
    "como": "Italia", "parma": "Italia", "venezia": "Italia",
    "cremonese": "Italia", "ac_pisa": "Italia", "pisa": "Italia",
    # Alemania
    "bayern_munich": "Alemania", "dortmund": "Alemania", "leverkusen": "Alemania",
    "leipzig": "Alemania", "mgladbach": "Alemania", "wolfsburg": "Alemania",
    "stuttgart": "Alemania", "fc_koln": "Alemania", "hoffenheim": "Alemania",
    "mainz": "Alemania", "union_berlin": "Alemania", "heidenheim": "Alemania",
    "werder_bremen": "Alemania", "augsburg": "Alemania", "freiburg": "Alemania",
    "bochum": "Alemania", "darmstadt": "Alemania", "st_pauli": "Alemania",
    "holstein_kiel": "Alemania", "eintracht_frankfurt": "Alemania",
    # Francia
    "paris_sg": "Francia", "marseille": "Francia", "lyon": "Francia",
    "saint_etienne": "Francia", "monaco": "Francia", "lille": "Francia",
    "rennes": "Francia", "nice": "Francia", "strasbourg": "Francia",
    "reims": "Francia", "lens": "Francia", "brest": "Francia",
    "le_havre": "Francia", "auxerre": "Francia", "angers": "Francia",
    "toulouse": "Francia", "nantes": "Francia", "montpellier": "Francia",
    "metz": "Francia",
}


# Mapeo de liga_id -> pais default (cuando el team no esta en TEAM_COUNTRY).
LIGA_TO_PAIS: dict[int, str] = {
    1: "Europa", 2: "España", 3: "Inglaterra",
    4: "Italia", 5: "Alemania", 6: "Francia",
}


class SupabaseSync:
    """Cache de equipos + helpers para sync."""

    def __init__(self):
        self.slug_to_id: dict[str, int] = {}
        self.id_to_slug: dict[int, str] = {}
        self.equipos_faltantes: dict[int, set[str]] = {}  # id -> set de campos null
        self._load_existing_equipos()

    def _load_existing_equipos(self) -> None:
        rows = sb_get("equipos?select=id,nombre,escudo_url,pais,color_prim,color_sec")
        for e in rows:
            slug = canonical(e["nombre"])
            eid = int(e["id"])
            self.slug_to_id[slug] = eid
            self.id_to_slug[eid] = slug
            faltantes = set()
            if not e.get("escudo_url"):       faltantes.add("escudo_url")
            if not e.get("pais"):             faltantes.add("pais")
            if not e.get("color_prim") or e.get("color_prim") in ("#1f2937", "#333"):
                faltantes.add("color_prim")
            if not e.get("color_sec") or e.get("color_sec") in ("#ffffff", "#fff"):
                faltantes.add("color_sec")
            if faltantes:
                self.equipos_faltantes[eid] = faltantes
        for sid, slug in SUPABASE_TO_SLUG.items():
            self.slug_to_id.setdefault(slug, sid)
            self.id_to_slug.setdefault(sid, slug)
        print(f"[sync] cache de equipos: {len(self.slug_to_id)} entradas "
              f"({len(self.equipos_faltantes)} con campos faltantes)")

    def _enrich_payload(self, slug: str, liga_id: int) -> dict:
        """Devuelve los campos derivables para un equipo: pais, color_prim, color_sec, abreviacion."""
        col_p, col_s = TEAM_COLORS.get(slug, ("#1f2937", "#ffffff"))
        return {
            "abreviacion": slug.upper().replace("_", "")[:5],
            "color_prim": col_p,
            "color_sec": col_s,
            "pais": TEAM_COUNTRY.get(slug) or LIGA_TO_PAIS.get(liga_id, "Europa"),
        }

    def ensure_equipo(self, slug: str, fd_name: str, liga_id: int,
                      escudo_url: str | None,
                      dry_run: bool) -> int | None:
        if slug in self.slug_to_id:
            eid = self.slug_to_id[slug]
            # Actualizar campos faltantes si los tenemos
            faltantes = self.equipos_faltantes.get(eid, set())
            if not faltantes:
                return eid
            patch = {}
            enriched = self._enrich_payload(slug, liga_id)
            if "escudo_url" in faltantes and escudo_url:
                patch["escudo_url"] = escudo_url
            if "pais" in faltantes:
                patch["pais"] = enriched["pais"]
            if "color_prim" in faltantes and slug in TEAM_COLORS:
                patch["color_prim"] = enriched["color_prim"]
            if "color_sec" in faltantes and slug in TEAM_COLORS:
                patch["color_sec"] = enriched["color_sec"]
            if not patch:
                return eid
            if dry_run:
                print(f"  [dry-run] update equipo id={eid} {slug}: {patch}")
            else:
                try:
                    sb_patch(f"equipos?id=eq.{eid}", patch)
                    for k in patch:
                        self.equipos_faltantes[eid].discard(k)
                    print(f"  + actualizado: {slug:25} id={eid}  campos={list(patch.keys())}")
                except Exception as e:
                    print(f"  ! error update {slug}: {e}")
            return eid

        # Creacion nueva
        enriched = self._enrich_payload(slug, liga_id)
        payload = {
            "nombre": fd_name,
            "liga_id": liga_id,
            "escudo_url": escudo_url,
            **enriched,
        }
        if dry_run:
            print(f"  [dry-run] crear equipo: {slug} -> {payload}")
            return None
        try:
            res = sb_post("equipos", [payload], prefer="return=representation")
            new_id = int(res[0]["id"])
            self.slug_to_id[slug] = new_id
            self.id_to_slug[new_id] = slug
            print(f"  + equipo creado: {slug:25} -> id={new_id}  "
                  f"escudo={'si' if escudo_url else 'no'}  pais={enriched['pais']}  "
                  f"colors={'si' if slug in TEAM_COLORS else 'default'}")
            return new_id
        except Exception as e:
            print(f"  ! error creando equipo {slug}: {e}")
            return None

    def find_partido_id(self, home_id: int, away_id: int,
                        fecha_iso: str) -> int | None:
        fecha_dt = pd.to_datetime(fecha_iso, utc=True)
        lo = (fecha_dt - timedelta(hours=6)).isoformat()
        hi = (fecha_dt + timedelta(hours=6)).isoformat()
        q = urllib.parse.urlencode({
            "select": "id",
            "equipo_local_id": f"eq.{home_id}",
            "equipo_visitante_id": f"eq.{away_id}",
            "fecha": f"gte.{lo}",
        })
        rows = sb_get(f"partidos?{q}&fecha=lte.{urllib.parse.quote(hi)}")
        return int(rows[0]["id"]) if rows else None

    def upsert_partido(self, home_id: int, away_id: int, fecha_iso: str,
                       liga_id: int, temporada: str,
                       dry_run: bool) -> tuple[int | None, bool]:
        """Devuelve (partido_id, created_bool)."""
        existing = self.find_partido_id(home_id, away_id, fecha_iso)
        if existing:
            return existing, False
        payload = {
            "equipo_local_id": home_id,
            "equipo_visitante_id": away_id,
            "fecha": fecha_iso,
            "liga_id": liga_id,
            "temporada": temporada or "2025/26",
            "estado": "programado",
        }
        if dry_run:
            print(f"  [dry-run] crear partido: {home_id} vs {away_id} @ {fecha_iso[:16]}")
            return None, True
        try:
            res = sb_post("partidos", [payload], prefer="return=representation")
            new_id = int(res[0]["id"])
            return new_id, True
        except Exception as e:
            print(f"  ! error creando partido: {e}")
            return None, False

    def archive_past_partidos(self, dry_run: bool) -> int:
        """Marca como finalizado los partidos `programado` con fecha pasada."""
        cutoff = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).isoformat()
        q = urllib.parse.urlencode({
            "select": "id,fecha",
            "estado": "eq.programado",
            "fecha": f"lt.{cutoff}",
        })
        rows = sb_get(f"partidos?{q}")
        if not rows:
            return 0
        ids = [r["id"] for r in rows]
        if dry_run:
            print(f"  [dry-run] archivar {len(ids)} partidos pasados: {ids}")
            return len(ids)
        ids_str = ",".join(str(i) for i in ids)
        sb_patch(f"partidos?id=in.({ids_str})", {"estado": "finalizado"})
        print(f"  + archivados {len(ids)} partidos pasados: {ids}")
        return len(ids)


def sync_finished_results(sync: "SupabaseSync", dry_run: bool = False) -> dict:
    """
    Actualiza partidos en Supabase que estaban 'programado' pero ahora
    estan finalizados en matches.parquet. Setea goles_local, goles_visitante
    y estado='finalizado'.
    """
    df = pd.read_parquet(PATHS.matches)
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    # Mapa: (slug_h, slug_a, fecha_iso[:10]) -> (home_goals, away_goals)
    finished = df[df["home_goals"].notna() & df["away_goals"].notna()].copy()
    results_map: dict[tuple, tuple] = {}
    for _, m in finished.iterrows():
        key = (m["home_team_id"], m["away_team_id"], m["kickoff_ts_utc"].strftime("%Y-%m-%d"))
        results_map[key] = (int(m["home_goals"]), int(m["away_goals"]))

    # Partidos en Supabase aun programado
    rows = sb_get("partidos?select=id,fecha,equipo_local_id,equipo_visitante_id&estado=eq.programado")
    stats = {"updated": 0, "still_pending": 0, "errors": 0}

    for p in rows:
        eq_h = int(p["equipo_local_id"])
        eq_a = int(p["equipo_visitante_id"])
        slug_h = sync.id_to_slug.get(eq_h)
        slug_a = sync.id_to_slug.get(eq_a)
        if not slug_h or not slug_a:
            stats["still_pending"] += 1
            continue
        fecha_iso = p["fecha"][:10]
        result = results_map.get((slug_h, slug_a, fecha_iso))
        if not result:
            stats["still_pending"] += 1
            continue
        gl, gv = result
        if dry_run:
            print(f"  [dry-run] partido id={p['id']}: {slug_h} {gl}-{gv} {slug_a} -> finalizado")
            stats["updated"] += 1
            continue
        try:
            sb_patch(f"partidos?id=eq.{p['id']}",
                     {"goles_local": gl, "goles_visitante": gv, "estado": "finalizado"})
            print(f"  + partido {p['id']}: {slug_h} {gl}-{gv} {slug_a}  -> finalizado")
            stats["updated"] += 1
        except Exception as e:
            print(f"  ! error update partido {p['id']}: {e}")
            stats["errors"] += 1
    return stats


# NOTA: `forma_reciente` es una VIEW en Supabase que computa W/D/L desde
# `partidos` directamente. No hay que escribirle nada — apenas
# sync_finished_results() actualice goles + estado='finalizado',
# la vista refresca automaticamente. Mantengamos esto asi (single source
# of truth en `partidos`).


def sync_upcoming(horizon_days: int = 14, dry_run: bool = False,
                  only_leagues: list[str] | None = None) -> dict:
    df = pd.read_parquet(PATHS.matches)
    df["kickoff_ts_utc"] = pd.to_datetime(df["kickoff_ts_utc"], utc=True)
    now = pd.Timestamp.now(tz="UTC")
    end = now + pd.Timedelta(days=horizon_days)

    valid_status = df["status"].isin(["SCHEDULED", "TIMED"])
    in_window = (df["kickoff_ts_utc"] >= now - pd.Timedelta(hours=2)) & \
                 (df["kickoff_ts_utc"] <= end)
    has_teams = df["home_team_id"].notna() & df["away_team_id"].notna()
    upcoming = df[valid_status & in_window & has_teams].copy()

    if only_leagues:
        upcoming = upcoming[upcoming["competition_code"].isin(only_leagues)]

    # Ordenar por fecha y eliminar duplicados de mismo partido entre fuentes
    upcoming = upcoming.sort_values("kickoff_ts_utc")
    upcoming = upcoming.drop_duplicates(
        subset=["home_team_id", "away_team_id"],
        keep="first"
    )

    print(f"[sync] {len(upcoming)} partidos proximos (status=SCHEDULED/TIMED) "
          f"en los proximos {horizon_days} dias")

    sync = SupabaseSync()
    stats = {"created_equipos": 0, "created_partidos": 0, "existing_partidos": 0,
             "skipped_no_liga": 0, "skipped_no_equipo": 0, "errors": 0}

    for _, m in upcoming.iterrows():
        liga_id = LEAGUE_ALIAS.get(m["competition_code"])
        if not liga_id:
            stats["skipped_no_liga"] += 1
            continue
        try:
            n_before = len(sync.slug_to_id)
            home_id = sync.ensure_equipo(
                slug=m["home_team_id"],
                fd_name=m.get("home_team_name") or m["home_team_id"],
                liga_id=liga_id,
                escudo_url=(m.get("home_team_crest") if isinstance(m.get("home_team_crest"), str) else None),
                dry_run=dry_run,
            )
            away_id = sync.ensure_equipo(
                slug=m["away_team_id"],
                fd_name=m.get("away_team_name") or m["away_team_id"],
                liga_id=liga_id,
                escudo_url=(m.get("away_team_crest") if isinstance(m.get("away_team_crest"), str) else None),
                dry_run=dry_run,
            )
            stats["created_equipos"] += len(sync.slug_to_id) - n_before
            if not home_id or not away_id:
                stats["skipped_no_equipo"] += 1
                continue
            pid, created = sync.upsert_partido(
                home_id=home_id, away_id=away_id,
                fecha_iso=m["kickoff_ts_utc"].isoformat(),
                liga_id=liga_id,
                temporada=m.get("season", ""),
                dry_run=dry_run,
            )
            if created:
                stats["created_partidos"] += 1
                print(f"  + partido: {m['home_team_name']} vs {m['away_team_name']} "
                      f"@ {m['kickoff_ts_utc'].strftime('%Y-%m-%d %H:%M')}  "
                      f"(liga={m['competition_code']})")
            else:
                stats["existing_partidos"] += 1
        except Exception as e:
            print(f"  ! error: {e}")
            stats["errors"] += 1

    stats["archived"] = sync.archive_past_partidos(dry_run)
    return stats


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=14,
                    help="Dias hacia adelante para sincronizar partidos proximos")
    ap.add_argument("--dry-run", action="store_true",
                    help="Imprime que haria sin tocar Supabase")
    ap.add_argument("--leagues", default=None,
                    help="CSV de competition_codes (default: todos)")
    ap.add_argument("--skip-results", action="store_true",
                    help="Saltar actualizacion de resultados de partidos finalizados")
    args = ap.parse_args()

    leagues = [s.strip() for s in args.leagues.split(",")] if args.leagues else None
    print(f"[sync] modo: horizon={args.horizon} dry_run={args.dry_run} leagues={leagues}")

    # 1) Sync de partidos proximos (crea equipos + partidos nuevos, actualiza colores/pais)
    upcoming_stats = sync_upcoming(args.horizon, args.dry_run, leagues)
    print(f"[sync] upcoming: {upcoming_stats}")

    # Recargamos cache despues del sync (puede haber equipos nuevos)
    print()
    sync = SupabaseSync()

    # 2) Sync de resultados reales (programado -> finalizado con goles).
    # Esto tambien actualiza forma_reciente indirectamente: es una VIEW que
    # computa desde `partidos`, asi que al cambiar el estado y los goles,
    # forma_reciente refleja automaticamente la W/D/L de cada equipo.
    if not args.skip_results:
        print("\n[sync] -- actualizando resultados de partidos finalizados --")
        results_stats = sync_finished_results(sync, args.dry_run)
        print(f"[sync] resultados: {results_stats}")


if __name__ == "__main__":
    main()

```
