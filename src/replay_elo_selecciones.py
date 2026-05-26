"""
Calcula el Elo basal de las selecciones procesando el historico de partidos
internacionales desde martj42/international_results (CSV publico, ~49.000
partidos desde 1872).

Filtra a:
- Fecha >= 2014-01-01 (post-Mundial 2014, datos modernos)
- Tournaments competitivos (excluye 'Friendly', mucho ruido)
- Partidos jugados (home_score y away_score no NA)
- Al menos un equipo en TEAM_SLUGS (selecciones que nos interesan)

Output:
- data/elo_state_selecciones.json con el Elo calibrado por slug

Despues del baseline, cada partido del Mundial 2026 (en partidos liga 7) que
se juegue actualiza este state via el smart-sync.

Uso:
    python -m src.replay_elo_selecciones
    python -m src.replay_elo_selecciones --dry-run --max-rows 100
"""
from __future__ import annotations
import argparse
import io
import urllib.request
from pathlib import Path

import pandas as pd

from .elo import EloState, replay


HIST_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
OUT_PATH = Path("data/elo_state_selecciones.json")
SINCE_DATE = "2014-01-01"

# Tournaments competitivos relevantes para Elo de selecciones.
RELEVANT_TOURNAMENTS = {
    "FIFA World Cup",
    "FIFA World Cup qualification",
    "UEFA Euro",
    "UEFA Euro qualification",
    "UEFA Nations League",
    "Copa América",
    "Copa America",
    "CONMEBOL Pre-Olympic Tournament",
    "African Cup of Nations",
    "African Cup of Nations qualification",
    "Africa Cup of Nations",
    "Africa Cup of Nations qualification",
    "AFC Asian Cup",
    "AFC Asian Cup qualification",
    "CONCACAF Gold Cup",
    "CONCACAF Nations League",
    "OFC Nations Cup",
    "FIFA Confederations Cup",
    "FIFA Arab Cup",
    "Copa America",
    "Finalissima",
}

# Mapeo nombre EN (como aparece en martj42) -> slug canonico.
# Cubre todas las selecciones de las top 80 Elo + repechajes Mundial.
NAME_TO_SLUG: dict[str, str] = {
    # Mundial 2026 (48)
    "Algeria":            "argelia",
    "Argentina":          "argentina",
    "Australia":          "australia",
    "Austria":            "austria",
    "Belgium":            "belgica",
    "Bosnia and Herzegovina": "bosnia",
    "Bosnia-Herzegovina": "bosnia",
    "Brazil":             "brasil",
    "Canada":             "canada",
    "Cape Verde":         "cabo_verde",
    "Cape Verde Islands": "cabo_verde",
    "Colombia":           "colombia",
    "DR Congo":           "rdc",
    "Congo DR":           "rdc",
    "Croatia":            "croacia",
    "Curaçao":            "curazao",
    "Czech Republic":     "republica_checa",
    "Czechia":            "republica_checa",
    "Ecuador":            "ecuador",
    "Egypt":              "egipto",
    "England":            "inglaterra",
    "France":             "francia",
    "Germany":            "alemania",
    "Ghana":              "ghana",
    "Haiti":              "haiti",
    "Iran":               "iran",
    "Iraq":               "irak",
    "Ivory Coast":        "costa_marfil",
    "Côte d'Ivoire":      "costa_marfil",
    "Japan":              "japon",
    "Jordan":             "jordania",
    "Mexico":             "mexico",
    "Morocco":            "marruecos",
    "Netherlands":        "paises_bajos",
    "New Zealand":        "nueva_zelanda",
    "Norway":             "noruega",
    "Panama":             "panama",
    "Paraguay":           "paraguay",
    "Portugal":           "portugal",
    "Qatar":              "qatar",
    "Saudi Arabia":       "arabia_saudita",
    "Scotland":           "escocia",
    "Senegal":            "senegal",
    "South Africa":       "sudafrica",
    "South Korea":        "corea_sur",
    "Spain":              "espana",
    "Sweden":             "suecia",
    "Switzerland":        "suiza",
    "Tunisia":            "tunez",
    "Turkey":             "turquia",
    "United States":      "estados_unidos",
    "USA":                "estados_unidos",
    "Uruguay":            "uruguay",
    "Uzbekistan":         "uzbekistan",
    # Otras top 50 + repechaje que pueden jugar amistosos contra los nuestros
    "Italy":              "italia",
    "Poland":             "polonia",
    "Denmark":            "dinamarca",
    "Wales":              "gales",
    "Hungary":            "hungria",
    "Greece":             "grecia",
    "Ukraine":            "ucrania",
    "Serbia":             "serbia",
    "Romania":            "rumania",
    "Slovakia":           "eslovaquia",
    "Slovenia":           "eslovenia",
    "Albania":            "albania",
    "Georgia":            "georgia",
    "Finland":            "finlandia",
    "Republic of Ireland": "irlanda",
    "Ireland":            "irlanda",
    "Israel":             "israel",
    "Bulgaria":           "bulgaria",
    "Iceland":            "islandia",
    "North Macedonia":    "macedonia_norte",
    "Macedonia":          "macedonia_norte",
    "FYR Macedonia":      "macedonia_norte",
    "Northern Ireland":   "irlanda_norte",
    "Russia":             "rusia",
    "Kosovo":             "kosovo",
    "Peru":               "peru",
    "Chile":              "chile",
    "Venezuela":          "venezuela",
    "Bolivia":            "bolivia",
    "Costa Rica":         "costa_rica",
    "Honduras":           "honduras",
    "Jamaica":            "jamaica",
    "El Salvador":        "el_salvador",
    "China PR":           "china",
    "China":              "china",
    "Oman":               "oman",
    "United Arab Emirates": "emiratos_arabes",
    "UAE":                "emiratos_arabes",
    "Nigeria":            "nigeria",
    "Cameroon":           "camerun",
    "Mali":               "mali",
}


def fetch_csv() -> pd.DataFrame:
    print(f"[elo-replay] descargando {HIST_URL}")
    with urllib.request.urlopen(HIST_URL, timeout=60) as r:
        data = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(data))
    print(f"[elo-replay] CSV total: {len(df):,} partidos ({df['date'].min()} a {df['date'].max()})")
    return df


def filter_relevant(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df[df["date"].notna()]
    df = df[df["date"] >= SINCE_DATE]
    # Solo torneos competitivos
    df = df[df["tournament"].isin(RELEVANT_TOURNAMENTS)]
    # Solo partidos jugados (scores no NA)
    df = df[df["home_score"].notna() & df["away_score"].notna()]
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
    df = df[df["home_score"].notna() & df["away_score"].notna()]
    return df.reset_index(drop=True)


def build_replay_df(df: pd.DataFrame) -> pd.DataFrame:
    """Construye el DataFrame en el formato que espera elo.replay()."""
    df = df.copy()
    df["home_slug"] = df["home_team"].map(NAME_TO_SLUG)
    df["away_slug"] = df["away_team"].map(NAME_TO_SLUG)

    # Reportar nombres sin mapeo
    unmapped_home = df[df["home_slug"].isna()]["home_team"].value_counts().head(20)
    if len(unmapped_home):
        print("[elo-replay] selecciones sin slug (top 20 por count):")
        for name, cnt in unmapped_home.items():
            print(f"  {cnt:>4d}  {name!r}")

    # Conservar solo partidos donde AMBOS slugs estan mapeados
    df = df[df["home_slug"].notna() & df["away_slug"].notna()]

    out = pd.DataFrame({
        "match_id": (df["date"].dt.strftime("%Y%m%d") + "_" + df["home_slug"] + "_" + df["away_slug"]),
        "kickoff_ts_utc": df["date"].dt.strftime("%Y-%m-%dT12:00:00Z"),
        "home_team_id": df["home_slug"],
        "away_team_id": df["away_slug"],
        "home_goals": df["home_score"].astype(int),
        "away_goals": df["away_score"].astype(int),
        "is_neutral": df["neutral"].astype(str).str.upper() == "TRUE",
    })
    return out.sort_values("kickoff_ts_utc").reset_index(drop=True)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--max-rows", type=int, default=None)
    args = p.parse_args()

    df = fetch_csv()
    df = filter_relevant(df)
    print(f"[elo-replay] tras filtros: {len(df):,} partidos competitivos {SINCE_DATE}+")

    replay_df = build_replay_df(df)
    print(f"[elo-replay] tras matching de slugs: {len(replay_df):,} partidos a procesar")

    if args.max_rows:
        replay_df = replay_df.head(args.max_rows)

    if args.dry_run:
        print()
        print("Primeros 10 partidos:")
        for _, r in replay_df.head(10).iterrows():
            print(f"  {r['kickoff_ts_utc'][:10]} {r['home_team_id']:<18} {r['home_goals']}-{r['away_goals']} {r['away_team_id']:<18} {'(N)' if r['is_neutral'] else ''}")
        return

    # Replay desde state vacio (ratings inicializan a ELO.initial_rating = 1500)
    state = EloState()
    state = replay(replay_df, state)

    # Top 20 ratings finales
    print()
    print("Top 20 selecciones por Elo despues del replay:")
    sorted_ratings = sorted(state.ratings.items(), key=lambda kv: -kv[1])
    for i, (slug, rating) in enumerate(sorted_ratings[:20], start=1):
        print(f"  {i:>2}. {slug:<22} {rating:>7.1f}")

    # Guardar a path custom (no piso el state de clubes)
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    state.to_json(OUT_PATH)
    print(f"\n[elo-replay] guardado en {OUT_PATH} ({len(state.ratings)} selecciones)")


if __name__ == "__main__":
    main()
