"""
Sincroniza conservadoramente los planteles del Mundial 2026.

Reglas:
- Football-Data solo se usa para reemplazos claros en equipos actualizados en 2026.
- Una baja confirmada en lesiones_overrides_manual.json se marca como inactiva.
- Nunca se borran jugadores: preservamos IDs, ratings e historiales asociados.
- Un reemplazo se aplica solo cuando hay exactamente una alta y una baja.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .ingest_wc2026 import FD_BASE, FD_TO_ES, LIGA_SELECCIONES
from .supabase_writer import sb_get, sb_patch, sb_post


OVERRIDES_PATH = Path("data/lesiones_overrides_manual.json")
INACTIVE_PREFIX = "[FUERA_MUNDIAL]"
TRUSTED_UPDATED_YEAR = 2026
POSITION_MAP = {
    "Goalkeeper": "POR",
    "Defence": "DEF",
    "Defender": "DEF",
    "Midfielder": "MED",
    "Midfield": "MED",
    "Forward": "DEL",
    "Offence": "DEL",
}


def normalize_name(value: str | None) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_inactive(player: dict) -> bool:
    return str(player.get("notas") or "").startswith(INACTIVE_PREFIX)


def inactive_notes(reason: str, previous: str | None) -> str:
    clean_previous = previous or ""
    if clean_previous.startswith(INACTIVE_PREFIX):
        parts = clean_previous.split(" | ", 1)
        clean_previous = parts[1] if len(parts) == 2 else ""
    suffix = f" | {clean_previous}" if clean_previous else ""
    return f"{INACTIVE_PREFIX} {reason}{suffix}"


def active_notes(notes: str | None) -> str | None:
    value = notes or ""
    if not value.startswith(INACTIVE_PREFIX):
        return notes
    parts = value.split(" | ", 1)
    return parts[1] if len(parts) == 2 else None


def load_confirmed_absences() -> dict[int, dict[str, dict]]:
    data = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    result: dict[int, dict[str, dict]] = defaultdict(dict)
    for item in data:
        if float(item.get("delta_pp") or 0) <= 0:
            continue
        result[int(item["equipo_id"])][normalize_name(item["jugador"])] = item
    return result


def players_match(remote: dict, local: dict) -> bool:
    remote_name = normalize_name(remote.get("name"))
    local_name = normalize_name(local.get("nombre"))
    if remote_name == local_name:
        return True

    remote_dob = remote.get("dateOfBirth")
    local_dob = local.get("fecha_nac")
    if remote_dob and local_dob and remote_dob == local_dob:
        return True

    remote_tokens = remote_name.split()
    local_tokens = local_name.split()
    if not remote_tokens or not local_tokens:
        return False
    if remote_tokens[-1] != local_tokens[-1]:
        return False
    shorter, longer = sorted((set(remote_tokens), set(local_tokens)), key=len)
    return shorter.issubset(longer)


def diff_squad(remote: list[dict], local: list[dict]) -> tuple[list[dict], list[dict]]:
    """Devuelve (altas remotas, bajas locales) luego de matchear identidades."""
    unmatched_local = list(local)
    additions: list[dict] = []
    for remote_player in remote:
        match_index = next(
            (
                index for index, local_player in enumerate(unmatched_local)
                if players_match(remote_player, local_player)
            ),
            None,
        )
        if match_index is None:
            additions.append(remote_player)
        else:
            unmatched_local.pop(match_index)
    return additions, unmatched_local


def map_position(value: str | None) -> str:
    return POSITION_MAP.get(value or "", "MED")


def fetch_world_cup_teams() -> list[dict]:
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        raise RuntimeError("Falta FOOTBALL_DATA_TOKEN")
    request = urllib.request.Request(
        f"{FD_BASE}/competitions/WC/teams?season=2026",
        headers={"X-Auth-Token": token},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read())
    teams = payload.get("teams", [])
    if len(teams) != 48:
        raise RuntimeError(f"Football-Data devolvio {len(teams)} selecciones, se esperaban 48")
    return teams


def paged_sb_get(path: str, page_size: int = 1000) -> list[dict]:
    rows: list[dict] = []
    separator = "&" if "?" in path else "?"
    offset = 0
    while True:
        chunk = sb_get(
            f"{path}{separator}limit={page_size}&offset={offset}"
        )
        rows.extend(chunk)
        if len(chunk) < page_size:
            return rows
        offset += page_size


def _updated_year(team: dict) -> int | None:
    value = team.get("lastUpdated")
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    ).year


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    equipos = paged_sb_get(
        f"equipos?select=id,nombre&liga_id=eq.{LIGA_SELECCIONES}"
    )
    name_to_id = {row["nombre"]: int(row["id"]) for row in equipos}
    normalized_name_to_id = {
        normalize_name(row["nombre"]): int(row["id"]) for row in equipos
    }
    if len(name_to_id) < 48:
        raise RuntimeError(f"Supabase tiene {len(name_to_id)} selecciones del Mundial")

    team_ids = ",".join(str(value) for value in sorted(name_to_id.values()))
    jugadores = paged_sb_get(
        "jugadores?select=id,nombre,equipo_id,posicion,nacionalidad,fecha_nac,"
        f"rating,notas&equipo_id=in.({team_ids})"
    )
    by_team: dict[int, list[dict]] = defaultdict(list)
    nationality_to_id: dict[str, int] = {}
    for player in jugadores:
        team_id = int(player["equipo_id"])
        by_team[team_id].append(player)
        nationality = normalize_name(player.get("nacionalidad"))
        if nationality:
            nationality_to_id[nationality] = team_id

    confirmed = load_confirmed_absences()
    teams = fetch_world_cup_teams()
    stats = defaultdict(int)

    # Aplicar bajas confirmadas aunque Football-Data siga atrasado.
    for team_id, absences in confirmed.items():
        for player in by_team.get(team_id, []):
            item = absences.get(normalize_name(player["nombre"]))
            if not item or is_inactive(player):
                continue
            payload = {"notas": inactive_notes(item["razon"], player.get("notas"))}
            print(f"[baja] equipo={team_id} jugador={player['nombre']}: {item['razon']}")
            if not args.dry_run:
                sb_patch(f"jugadores?id=eq.{player['id']}", payload)
            player["notas"] = payload["notas"]
            stats["bajas_confirmadas"] += 1

    for team in teams:
        db_name = FD_TO_ES.get(team.get("name"))
        team_id = name_to_id.get(db_name or "") or normalized_name_to_id.get(
            normalize_name(db_name)
        ) or nationality_to_id.get(normalize_name(db_name))
        if not team_id:
            raise RuntimeError(f"Sin equipo_id para Football-Data team={team.get('name')!r}")

        if _updated_year(team) != TRUSTED_UPDATED_YEAR:
            stats["equipos_no_confiables"] += 1
            continue

        absences = confirmed.get(team_id, {})
        remote = [
            player for player in (team.get("squad") or [])
            if normalize_name(player.get("name")) not in absences
        ]
        local_active = [
            player for player in by_team.get(team_id, [])
            if not is_inactive(player)
        ]
        additions, removals = diff_squad(remote, local_active)

        if not additions and not removals:
            stats["equipos_sin_cambios"] += 1
            continue

        if len(additions) != 1 or len(removals) != 1:
            print(
                f"[revisar] {db_name}: altas={[p.get('name') for p in additions]} "
                f"bajas={[p.get('nombre') for p in removals]}"
            )
            stats["equipos_ambiguos"] += 1
            continue

        incoming = additions[0]
        outgoing = removals[0]
        reason = (
            f"Reemplazado por {incoming['name']} segun plantel oficial "
            f"Football-Data ({team.get('lastUpdated')})"
        )
        print(f"[reemplazo] {db_name}: sale {outgoing['nombre']} -> entra {incoming['name']}")

        incoming_payload = {
            "nombre": incoming["name"],
            "equipo_id": team_id,
            "posicion": map_position(incoming.get("position")),
            "nacionalidad": db_name,
            "fecha_nac": incoming.get("dateOfBirth"),
            "rating": 70,
        }
        if not args.dry_run:
            sb_patch(
                f"jugadores?id=eq.{outgoing['id']}",
                {"notas": inactive_notes(reason, outgoing.get("notas"))},
            )
            sb_post("jugadores", [incoming_payload], prefer="return=minimal")
        stats["reemplazos"] += 1

    print("\n[squads-mundial] resumen")
    for key in (
        "bajas_confirmadas",
        "reemplazos",
        "equipos_sin_cambios",
        "equipos_no_confiables",
        "equipos_ambiguos",
    ):
        print(f"  {key}: {stats[key]}")


if __name__ == "__main__":
    main()
