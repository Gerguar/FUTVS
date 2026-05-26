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


def _safe_float(val: Any) -> float:
    try:
        if pd.isna(val):
            return 0.0
        return round(float(val), 3)
    except (TypeError, ValueError):
        return 0.0


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
        "xg":          _safe_float(row.get("xG") or row.get("xg") or row.get("expected_goals")),
        "xa":          _safe_float(row.get("xA") or row.get("xa") or row.get("expected_assists")),
        "shots":       _safe_int(row.get("shots")),
        "npxg":        _safe_float(row.get("npxG") or row.get("npxg")),
        "key_passes":  _safe_int(row.get("key_passes")),
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
