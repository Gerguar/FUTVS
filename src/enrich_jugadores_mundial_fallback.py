"""
Fallback para los ~355 jugadores del Mundial 2026 que quedaron en rating=70
default después del paso 1 (el CSV de EA FC 26 no los cubre — jugadores del
Brasileirao / MLS / Saudí / asiáticas / africanas).

Aplica en orden:

1. Overrides manuales: lee src/data/mundial_overrides_manual.csv con los
   ratings que sabemos por reputación pública (Son Heung-min 89, Salah 89,
   Mahrez 84, etc.). Cubre los TOP jugadores conocidos.

2. Estimación por Elo de su selección: para los que queden en 70, asigna
   un rating en función de la fuerza de su selección + orden en el squad
   (los primeros del CSV original suelen ser los principales).

Tabla de base por Elo (centrada en la heurística):
   Elo >= 2050  -> base 78
   Elo 1950-2050-> base 76
   Elo 1850-1950-> base 74
   Elo 1750-1850-> base 72
   Elo 1650-1750-> base 70
   Elo < 1650   -> base 68

Ajuste por posición y orden:
   Top 1 GK -> base+2,  GK 2 -> base, GK 3 -> base-3
   Top 3 DEF/MED/DEL -> base+2,  4-7 -> base, 8+ -> base-2

Sigue siendo una aproximación pero **no infla** las selecciones débiles
porque el techo se mueve con su Elo (Irán con Elo 1800 → top jugador en 76,
no 70 fijo).

Uso:
    python -m src.enrich_jugadores_mundial_fallback --dry-run
    python -m src.enrich_jugadores_mundial_fallback
"""
from __future__ import annotations
import argparse
import csv
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from .supabase_writer import sb_get, _sb_url, _headers


CSV_OVERRIDES = Path(__file__).parent / "data" / "mundial_overrides_manual.csv"

MUNDIAL_IDS = (
    111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    126, 127, 129, 130, 132, 133, 134, 135, 136, 141, 142, 145, 146, 148, 150,
    151, 153, 160, 161, 162, 168, 173, 178, 181, 187, 189, 192, 194, 196, 198,
    206, 211, 264,
)

ELO_BASE_TABLE = [
    (2050, 78),
    (1950, 76),
    (1850, 74),
    (1750, 72),
    (1650, 70),
    (0,    68),
]


def base_from_elo(elo: float) -> int:
    for threshold, base in ELO_BASE_TABLE:
        if elo >= threshold:
            return base
    return 68


def estimate_rating(pos: str, base: int, order_within_pos: int) -> int:
    """order_within_pos: 0=mejor del squad para esa pos, 1=segundo, etc."""
    if pos == "POR":
        if order_within_pos == 0:
            return min(99, base + 2)
        elif order_within_pos == 1:
            return base
        else:
            return max(50, base - 3)
    else:
        if order_within_pos <= 2:
            return min(99, base + 2)
        elif order_within_pos <= 6:
            return base
        else:
            return max(50, base - 2)


def patch(jid: int, payload: dict) -> None:
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/jugadores?id=eq.{jid}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers({"Content-Type": "application/json", "Prefer": "return=minimal"}),
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=15).read()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # 1. Cargar overrides manuales (rating + atributos si los pasamos)
    overrides: dict[tuple[int, str], dict] = {}
    if CSV_OVERRIDES.exists():
        with open(CSV_OVERRIDES, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                eq_id = int(row["equipo_id"])
                payload = {"rating": int(row["rating"])}
                # Atributos opcionales (vacíos = no patchear)
                for k in ("pace", "shooting", "passing", "dribbling", "defending",
                          "physic", "gk_diving", "gk_handling", "gk_kicking",
                          "gk_positioning", "gk_reflexes", "gk_speed"):
                    v = (row.get(k) or "").strip()
                    if v:
                        try:
                            payload[k] = int(v)
                        except ValueError:
                            pass  # texto en col equivocada, ignorar
                overrides[(eq_id, row["nombre"])] = payload
    print(f"[fallback] overrides manuales: {len(overrides)}")

    # 2. Elo por equipo_id (vía slug)
    elo_rows = sb_get("selecciones_elo?select=slug,nombre,elo")
    nombre2elo = {r["nombre"]: r["elo"] for r in elo_rows}
    eq = sb_get(f"equipos?select=id,nombre&id=in.({','.join(map(str, MUNDIAL_IDS))})")
    id2nombre = {e["id"]: e["nombre"] for e in eq}
    id2elo = {eid: nombre2elo.get(id2nombre[eid]) for eid in MUNDIAL_IDS if eid in id2nombre}
    elo_missing = [id2nombre[eid] for eid, e in id2elo.items() if e is None]
    if elo_missing:
        print(f"[fallback] selecciones sin Elo: {elo_missing}")

    # 3. Traer todos los jugadores con rating=70 (los que necesitan fallback)
    players: list[dict] = []
    offset = 0
    while True:
        chunk = sb_get(f"jugadores?select=id,nombre,equipo_id,posicion,rating"
                       f"&equipo_id=in.({','.join(map(str, MUNDIAL_IDS))})"
                       f"&order=equipo_id,id&limit=1000&offset={offset}")
        players.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    # Orden dentro de su squad: usar el orden de id (cargado igual que el CSV)
    by_team_pos: dict[tuple[int, str], list[dict]] = defaultdict(list)
    for pl in players:
        by_team_pos[(pl["equipo_id"], pl["posicion"])].append(pl)
    # ya está ordenado por id (porque ordenamos en el query)

    overrides_applied = 0
    estimated = 0
    unchanged = 0
    skipped_elo = 0
    by_team_summary: dict[int, dict[str, int]] = defaultdict(lambda: {"override":0, "est":0})

    for (eq_id, pos), squad_pos in by_team_pos.items():
        elo = id2elo.get(eq_id)
        for order, pl in enumerate(squad_pos):
            # Caso 1: override manual
            key = (pl["equipo_id"], pl["nombre"])
            if key in overrides:
                payload = overrides[key]
                if not args.dry_run:
                    try:
                        patch(pl["id"], payload)
                        overrides_applied += 1
                        by_team_summary[eq_id]["override"] += 1
                    except Exception as e:
                        print(f"  ! override {pl['nombre']}: {e}")
                else:
                    overrides_applied += 1
                continue

            # Caso 2: ya tiene rating real (no es 70 default)
            if pl["rating"] != 70:
                unchanged += 1
                continue

            # Caso 3: estimación por Elo
            if elo is None:
                skipped_elo += 1
                continue
            base = base_from_elo(elo)
            est_rating = estimate_rating(pos, base, order)
            if est_rating == 70:
                # No cambia, no patchear (evita ruido en logs)
                continue
            payload = {"rating": est_rating}
            if not args.dry_run:
                try:
                    patch(pl["id"], payload)
                    estimated += 1
                    by_team_summary[eq_id]["est"] += 1
                except Exception as e:
                    print(f"  ! est {pl['nombre']}: {e}")
            else:
                estimated += 1

    print(f"\n[fallback] resumen:")
    print(f"  overrides manuales aplicados: {overrides_applied}")
    print(f"  estimados por Elo + orden:    {estimated}")
    print(f"  ya con rating real:           {unchanged}")
    print(f"  sin Elo (saltado):            {skipped_elo}")

    if not args.dry_run:
        print(f"\nTop 8 selecciones por jugadores estimados:")
        ranked = sorted(by_team_summary.items(), key=lambda kv: -(kv[1]["est"]+kv[1]["override"]))
        for eid, s in ranked[:8]:
            print(f"  {id2nombre[eid]:<22} override={s['override']:>2}  estimated={s['est']:>2}")


if __name__ == "__main__":
    main()
