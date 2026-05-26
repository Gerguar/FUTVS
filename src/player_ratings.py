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
            # 6 stats de jugador de campo
            "pace", "shooting", "passing", "dribbling", "defending", "physic",
            # 6 stats de arquero
            "goalkeeping_diving", "goalkeeping_handling", "goalkeeping_kicking",
            "goalkeeping_positioning", "goalkeeping_reflexes", "goalkeeping_speed",
        ],
        low_memory=False,
    )
    return df.to_dict("records")


# Columnas EAFC -> columnas de la tabla `jugadores` en Supabase.
_EAFC_ATTR_MAP = {
    "pace":                    "pace",
    "shooting":                "shooting",
    "passing":                 "passing",
    "dribbling":               "dribbling",
    "defending":               "defending",
    "physic":                  "physic",
    "goalkeeping_diving":      "gk_diving",
    "goalkeeping_handling":    "gk_handling",
    "goalkeeping_kicking":     "gk_kicking",
    "goalkeeping_positioning": "gk_positioning",
    "goalkeeping_reflexes":    "gk_reflexes",
    "goalkeeping_speed":       "gk_speed",
}


def _safe_smallint(value) -> int | None:
    """Convierte un valor de pandas (puede ser NaN/None/str) a int o None."""
    if value is None:
        return None
    try:
        # pd.isna no esta importado aca; chequeo manual por NaN
        if isinstance(value, float) and value != value:  # NaN
            return None
        v = int(round(float(value)))
        if 0 <= v <= 99:
            return v
    except (TypeError, ValueError):
        pass
    return None


def eafc_attributes_from_row(row: dict) -> dict:
    """Devuelve {col_supabase: valor_int_or_None} listo para PATCH."""
    out: dict = {}
    for src_col, dst_col in _EAFC_ATTR_MAP.items():
        out[dst_col] = _safe_smallint(row.get(src_col))
    return out


def build_eafc_index(rows: list[dict]) -> dict[str, list[dict]]:
    index: dict[str, list[dict]] = {}
    for row in rows:
        for field in ("short_name", "long_name"):
            key = norm_text(str(row.get(field) or ""))
            if key:
                index.setdefault(key, []).append(row)
    return index


def eafc_rating_from_index(player: dict, index: dict[str, list[dict]]) -> tuple[int | None, str, dict | None]:
    """Devuelve (rating, reason, attrs).

    `attrs` es dict con las 12 columnas EAFC traducidas a columnas de Supabase
    (pace/shooting/.../gk_speed) o None si no hubo match.
    """
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
        return None, "not_found", None

    local_team = ((player.get("equipo") or {}) or {}).get("nombre")
    team_hits = [row for row in candidates if team_matches(local_team, row.get("club_name"))]
    if team_hits:
        candidates = team_hits
    elif len(candidates) > 1:
        return None, "team_mismatch", None

    # Si quedan varios, elegimos el mayor OVR: en duplicados suele ser la carta/base mas relevante.
    best = max(candidates, key=lambda r: _safe_num(r.get("overall")))
    attrs = eafc_attributes_from_row(best)
    try:
        return int(best["overall"]), "eafc26_csv", attrs
    except (TypeError, ValueError):
        return None, "bad_ovr", None


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
        "pace,shooting,passing,dribbling,defending,physic,"
        "gk_diving,gk_handling,gk_kicking,gk_positioning,gk_reflexes,gk_speed,"
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

    summary["attrs_filled"] = 0
    for player in players:
        stat = stats_by_player.get(int(player["id"]))
        ea_rating = None
        ea_reason = ""
        ea_attrs: dict | None = None
        if prefer_eafc:
            ea_rating, ea_reason, ea_attrs = eafc_rating_from_index(player, ea_index)
            if ea_rating is None and eafc_api_fallback:
                # API fallback no devuelve los 12 stats detallados, solo rating.
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

        # Check si los 12 stats EAFC ya estan iguales en Supabase -> no resync.
        attrs_changed = False
        if ea_attrs:
            for col, new_val in ea_attrs.items():
                if player.get(col) != new_val:
                    attrs_changed = True
                    break

        summary["min_rating"] = min(summary["min_rating"], new_rating)
        summary["max_rating"] = max(summary["max_rating"], new_rating)
        if ea_attrs and any(v is not None for v in ea_attrs.values()):
            summary["attrs_filled"] += 1
        if old_rating == new_rating and not attrs_changed:
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
            "attrs": ea_attrs,  # None si no hubo match EAFC
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
        # Separamos en dos grupos:
        #  1) Updates con `attrs` (EAFC matcheado) -> PATCH individual incluyendo los 12 stats.
        #  2) Updates sin `attrs` (fallback/stats) -> batch por rating (eficiente).
        with_attrs = [u for u in selected if u.get("attrs")]
        without_attrs = [u for u in selected if not u.get("attrs")]

        # Grupo 1: PATCH individual por jugador (rating + 12 attrs).
        for item in with_attrs:
            payload = {"rating": int(item["rating"])}
            payload.update({k: v for k, v in item["attrs"].items() if v is not None})
            try:
                sb_patch(f"jugadores?id=eq.{int(item['id'])}", payload)
                applied += 1
            except Exception as e:
                print(f"  ! error PATCH jugador {item['id']}: {e}")

        # Grupo 2: batch tradicional por rating.
        ids_by_rating: dict[int, list[int]] = {}
        for item in without_attrs:
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
            extra = ""
            if item.get("attrs"):
                pace = item["attrs"].get("pace")
                shoot = item["attrs"].get("shooting")
                extra = f" [+attrs: pace={pace} sho={shoot} ...]"
            print(
                f"  [dry-run] jugador_id={item['id']} {item['nombre']}: "
                f"{item['old_rating']} -> {item['rating']} ({item['source']}){extra}"
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
