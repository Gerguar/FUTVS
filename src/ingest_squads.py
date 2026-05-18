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
