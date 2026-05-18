"""
Ingest de estadísticas de jugadores desde fbref.com vía la librería soccerdata.

fbref provee stats detalladas de la temporada actual por jugador (goles,
asistencias, minutos, xG, etc.) para las top 5 ligas europeas.

Flujo:
1. Por cada liga top 5, llama a fbref.read_player_season_stats()
2. Para cada fila (un jugador de un equipo en la temporada):
   a. Matchea el equipo via slug canónico
   b. Matchea el jugador con los nombres existentes en Supabase (fuzzy match)
   c. UPSERT en estadisticas_jugador

Requiere SOLO: que la tabla `jugadores` ya tenga el plantel cargado (lo hace
ingest_squads.py). El matching es por nombre dentro del equipo.

IMPORTANTE: respetar rate limit de fbref. soccerdata lo hace por defecto
(pausa entre requests).
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


# Mapeo fbref league name -> nuestro competition code interno
FBREF_LEAGUES: dict[str, str] = {
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
                       threshold: int = 70) -> int | None:
    """
    Devuelve el id del jugador con mejor match de nombre.
    candidates: lista de (id, nombre).
    threshold 0-100 de rapidfuzz (default 70).
    """
    from rapidfuzz import fuzz, process
    if not candidates:
        return None
    target_norm = _normalize_name(target_name)
    options = [(eid, _normalize_name(n)) for eid, n in candidates]
    # process.extractOne con un dict {eid: norm_name}
    choices = {eid: norm for eid, norm in options}
    result = process.extractOne(target_norm, choices, scorer=fuzz.WRatio)
    if not result:
        return None
    # result = (norm_match, score, eid)
    _, score, eid = result
    if score < threshold:
        return None
    return eid


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


def fetch_player_stats(league_fbref: str, seasons: list[str]) -> pd.DataFrame:
    """Llama a soccerdata.FBref para una liga y temporada(s)."""
    import soccerdata as sd
    fbref = sd.FBref(leagues=league_fbref, seasons=seasons)
    df = fbref.read_player_season_stats(stat_type="standard")
    df = _flatten_columns(df)
    # Reset index para que team y player esten como columnas
    if df.index.nlevels > 1:
        df = df.reset_index()
    return df


def extract_stats(row: pd.Series) -> dict:
    """Extrae las stats que nos interesan en el formato de Supabase."""
    return {
        "partidos":    _safe_int(row.get("MP") or row.get("matches_played") or row.get("Playing Time MP")),
        "minutos":     _safe_int(row.get("Min") or row.get("Playing Time Min") or row.get("minutes")),
        "goles":       _safe_int(row.get("Gls") or row.get("Performance Gls") or row.get("goals")),
        "asistencias": _safe_int(row.get("Ast") or row.get("Performance Ast") or row.get("assists")),
        "amarillas":   _safe_int(row.get("CrdY") or row.get("Performance CrdY") or row.get("yellow_cards")),
        "rojas":       _safe_int(row.get("CrdR") or row.get("Performance CrdR") or row.get("red_cards")),
    }


def sync_league(sync: SupabaseSync, league_fbref: str, our_code: str,
                seasons: list[str], temporada_label: str,
                dry_run: bool) -> dict:
    print(f"\n[fbref-stats] === {our_code} ({league_fbref}) ===")
    stats = {"rows_seen": 0, "team_matched": 0, "player_matched": 0,
             "upserted": 0, "no_team": 0, "no_player": 0, "errors": 0}

    try:
        df = fetch_player_stats(league_fbref, seasons)
    except Exception as e:
        print(f"  ! error fetching {league_fbref}: {e}")
        return stats

    print(f"  + {len(df)} filas obtenidas")

    # Cache de jugadores por equipo para evitar requests redundantes
    players_cache: dict[int, list[tuple[int, str]]] = {}

    # Identificar columna 'team' y 'player' (soccerdata las nombra distinto segun version)
    team_col = next((c for c in df.columns if c.lower() in ("team", "squad")), None)
    player_col = next((c for c in df.columns if c.lower() in ("player",)), None)
    if not team_col or not player_col:
        print(f"  ! no encuentro columnas team/player. Columnas: {list(df.columns)[:15]}")
        return stats

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

    # Upsert por equipo
    for eq_id, plist in payloads_per_team.items():
        if dry_run:
            print(f"  [dry-run] {our_code} eq_id={eq_id}: {len(plist)} estadisticas")
            stats["upserted"] += len(plist)
            continue
        try:
            sb_post("estadisticas_jugador?on_conflict=jugador_id,temporada",
                    plist,
                    prefer="resolution=merge-duplicates,return=minimal")
            stats["upserted"] += len(plist)
            print(f"  + {our_code} eq_id={eq_id}: {len(plist)} stats upserted")
        except Exception as e:
            print(f"  ! upsert eq_id={eq_id}: {e}")
            stats["errors"] += 1

    return stats


def sync_all(seasons: list[str], temporada_label: str,
             dry_run: bool = False) -> dict:
    sync = SupabaseSync()
    totals = {"rows_seen": 0, "team_matched": 0, "player_matched": 0,
              "upserted": 0, "no_team": 0, "no_player": 0, "errors": 0}
    for fbref_league, our_code in FBREF_LEAGUES.items():
        lstats = sync_league(sync, fbref_league, our_code, seasons,
                             temporada_label, dry_run)
        for k in totals:
            totals[k] += lstats.get(k, 0)
    return totals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", default="2024-25",
                    help="Temporada en formato fbref (ej: 2024-25)")
    ap.add_argument("--temporada-label", default=None,
                    help="Como guardar en Supabase (default: igual al season pero con / en vez de -)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    seasons = [args.season]
    label = args.temporada_label or args.season.replace("-", "/")

    print(f"[fbref-stats] iniciando: season={args.season} label={label} dry_run={args.dry_run}")
    stats = sync_all(seasons, label, args.dry_run)

    print(f"\n[fbref-stats] === resumen ===")
    print(f"  filas vistas:        {stats['rows_seen']}")
    print(f"  team matched:        {stats['team_matched']}")
    print(f"  player matched:      {stats['player_matched']}")
    print(f"  upserted:            {stats['upserted']}")
    print(f"  no_team:             {stats['no_team']}")
    print(f"  no_player:           {stats['no_player']}")
    print(f"  errores:             {stats['errors']}")


if __name__ == "__main__":
    main()
