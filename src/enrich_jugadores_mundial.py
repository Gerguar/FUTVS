"""
Enriquece `jugadores.rating` + los 12 stats EAFC (pace, shooting, ..., gk_*)
para los 1247 jugadores de las 48 selecciones del Mundial 2026.

Estrategia de matching contra el CSV de EA FC 26 (~18k jugadores) en orden de
preferencia:

  1. Match exacto: short_name o long_name normalizado == nombre del jugador.
  2. Match por apellido (último token) si short_name == apellido.
  3. Substring match: el nombre del jugador está contenido en long_name.

Para los candidatos resultantes, si hay más de uno, se filtra por club
(usando `jugadores.notas` que guardamos en seed_jugadores_mundial.py vs
`club_name` del CSV). Si tampoco desempata, se elige el mayor OVR.

Si no hay match, se deja el rating actual (70 default) y se usa un fallback
por edad/posición — pero como las selecciones no traen fecha_nac todavía,
en la práctica queda el 70 default y se marca como "not_found".

Uso:
    python -m src.enrich_jugadores_mundial --dry-run
    python -m src.enrich_jugadores_mundial
"""
from __future__ import annotations
import argparse
import json
import os
import urllib.request
from collections import Counter, defaultdict

from .player_ratings import (
    load_eafc26_csv, build_eafc_index, eafc_attributes_from_row,
    norm_text, canonical_team, _safe_num,
)
from .supabase_writer import sb_get, _sb_url, _headers


MUNDIAL_TEAM_IDS = (
    # Grupo A-L del Mundial 2026 (48 selecciones)
    111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    126, 127, 129, 130, 132, 133, 134, 135, 136, 141, 142, 145, 146, 148, 150,
    151, 153, 160, 161, 162, 168, 173, 178, 181, 187, 189, 192, 194, 196, 198,
    206, 211, 264,
)


def build_extra_indexes(rows: list[dict]):
    """Índices auxiliares para matching más flexible:
    - by_last: apellido (último token de long_name) -> filas
    - long_names: lista de (long_name_normalizado, row) para substring match
    """
    by_last: dict[str, list[dict]] = defaultdict(list)
    long_names: list[tuple[str, dict]] = []
    for r in rows:
        ln = norm_text(str(r.get("long_name") or ""))
        sn = norm_text(str(r.get("short_name") or ""))
        if ln:
            parts = ln.split()
            if parts:
                by_last[parts[-1]].append(r)
            long_names.append((ln, r))
        if sn and " " not in sn:
            by_last[sn].append(r)
    return by_last, long_names


def find_candidates(player_name: str, idx: dict[str, list[dict]],
                    by_last: dict[str, list[dict]],
                    long_names: list[tuple[str, dict]]) -> tuple[list[dict], list[dict]]:
    """Devuelve (confiables, solo_apellido).

    - confiables: matches exactos de nombre, iniciales+apellido o substring de long_name.
      Estos se pueden aceptar sin requerir match de club.
    - solo_apellido: matches por apellido solo (ambiguos). Solo se aceptan si
      hay confirmación por club, sino se descartan para evitar mismatches groseros
      (ej. "Jose Manuel Lopez" vs Pedri "Pedro González López").
    """
    key = norm_text(player_name)
    parts = key.split()
    confident: list[dict] = []
    seen_conf: set = set()

    def add(rows: list[dict], target: list[dict], seen: set):
        for r in rows:
            rid = r.get("player_id")
            if rid not in seen:
                seen.add(rid)
                target.append(r)

    # 1. Match exacto en short_name o long_name normalizado
    add(idx.get(key, []), confident, seen_conf)

    # 2. Iniciales + apellido (ej. "F. Valverde" en CSV)
    if len(parts) >= 2:
        add(idx.get(norm_text(f"{parts[0][0]} {parts[-1]}"), []), confident, seen_conf)

    # 3. Substring match: el nombre completo del jugador dentro de long_name
    #    Ej. "Martin Zubimendi" en "Martin Zubimendi Ibanez"
    if not confident and len(parts) >= 2:
        for ln, r in long_names:
            if key in ln:
                rid = r.get("player_id")
                if rid not in seen_conf:
                    seen_conf.add(rid)
                    confident.append(r)

    # 4. Solo apellido (ambiguo) — solo si hay >= 2 tokens en el nombre buscado
    surname_only: list[dict] = []
    seen_sn: set = set(seen_conf)
    if len(parts) >= 2:
        add(by_last.get(parts[-1], []), surname_only, seen_sn)

    return confident, surname_only


def filter_by_club(candidates: list[dict], player_club: str | None) -> list[dict]:
    """Devuelve los candidatos cuyo club_name matchea con player_club.
    Si no hay club registrado, devuelve la lista intacta (sin filtrar)."""
    if not player_club or not candidates:
        return candidates
    target = canonical_team(player_club)
    hits = []
    for r in candidates:
        ea_club = canonical_team(r.get("club_name"))
        if not ea_club:
            continue
        if target == ea_club or target in ea_club or ea_club in target:
            hits.append(r)
    return hits


def pick_best(candidates: list[dict]) -> dict | None:
    if not candidates:
        return None
    return max(candidates, key=lambda r: _safe_num(r.get("overall")))


def patch_jugador(jid: int, payload: dict) -> None:
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/jugadores?id=eq.{jid}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers({"Content-Type": "application/json", "Prefer": "return=minimal"}),
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=20).read()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None,
                   help="Procesar solo los primeros N (debug).")
    args = p.parse_args()

    print("[mundial-ratings] descargando EA FC 26 CSV...")
    ea_rows = load_eafc26_csv()
    print(f"[mundial-ratings] CSV: {len(ea_rows)} jugadores")
    idx = build_eafc_index(ea_rows)
    by_last, long_names = build_extra_indexes(ea_rows)
    print(f"[mundial-ratings] indices: {len(idx)} nombres exactos, "
          f"{len(by_last)} apellidos, {len(long_names)} long_names")

    # Traer los 1247 jugadores del Mundial paginado
    players: list[dict] = []
    offset = 0
    cols = ("id,nombre,equipo_id,posicion,notas,rating,"
            "pace,shooting,passing,dribbling,defending,physic,"
            "gk_diving,gk_handling,gk_kicking,gk_positioning,gk_reflexes,gk_speed")
    while True:
        chunk = sb_get(f"jugadores?select={cols}"
                       f"&equipo_id=in.({','.join(map(str, MUNDIAL_TEAM_IDS))})"
                       f"&order=id&limit=1000&offset={offset}")
        players.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    if args.limit:
        players = players[:args.limit]
    print(f"[mundial-ratings] {len(players)} jugadores del Mundial a procesar\n")

    stats = Counter()
    samples_ok = []
    samples_no = []
    updates: list[tuple[int, dict]] = []

    for pl in players:
        confident, surname_only = find_candidates(pl["nombre"], idx, by_last, long_names)
        club = pl.get("notas")
        chosen: list[dict] = []

        if confident:
            # Match confiable. Si hay club, filtrar; si nadie matchea por club,
            # igual aceptar (porque el nombre exacto ya es señal fuerte).
            if club:
                hits = filter_by_club(confident, club)
                chosen = hits if hits else confident
                if hits and len(hits) < len(confident):
                    stats["filtered_by_club"] += 1
            else:
                chosen = confident
        elif surname_only and club:
            # Match solo por apellido: SOLO aceptar si el club confirma.
            # Sin club, descartamos para evitar mismatches groseros.
            hits = filter_by_club(surname_only, club)
            if hits:
                chosen = hits
                stats["matched_by_surname_plus_club"] += 1

        if not chosen:
            stats["not_found"] += 1
            if len(samples_no) < 8:
                samples_no.append(f"{pl['nombre']} ({pl.get('notas') or 'sin club'})")
            continue

        best = pick_best(chosen)
        if not best:
            stats["not_found"] += 1
            continue

        new_rating = int(best["overall"]) if best.get("overall") is not None else None
        if new_rating is None:
            stats["bad_ovr"] += 1
            continue

        attrs = eafc_attributes_from_row(best)
        payload = {"rating": new_rating, **attrs}

        # Solo actualizar si cambia algo
        changed = (pl.get("rating") != new_rating) or any(
            pl.get(k) != v for k, v in attrs.items() if v is not None
        )
        if not changed:
            stats["unchanged"] += 1
            continue

        stats["matched"] += 1
        if len(samples_ok) < 8:
            samples_ok.append((pl["nombre"], pl.get("notas"), best.get("club_name"),
                              best.get("short_name"), new_rating))
        updates.append((pl["id"], payload))

    print(f"[mundial-ratings] resumen:")
    print(f"  matched      : {stats['matched']}")
    print(f"  unchanged    : {stats['unchanged']}")
    print(f"  filt by club : {stats['filtered_by_club']}")
    print(f"  not_found    : {stats['not_found']}")
    print(f"  bad_ovr      : {stats['bad_ovr']}")
    print()
    if samples_ok:
        print("ejemplos OK (primeros 8):")
        for n, c_db, c_ea, sn, r in samples_ok:
            print(f"  {n:<28} club_db={c_db or '-':<20} ea={sn:<22} club_ea={c_ea or '-':<20} ovr={r}")
    if samples_no:
        print(f"\nejemplos NOT_FOUND: {samples_no}")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return

    print(f"\n[mundial-ratings] aplicando {len(updates)} PATCH...")
    ok = 0
    for jid, payload in updates:
        try:
            patch_jugador(jid, payload)
            ok += 1
        except Exception as e:
            print(f"  ! patch {jid}: {e}")
    print(f"[mundial-ratings] OK: {ok}/{len(updates)} actualizados")


if __name__ == "__main__":
    main()
