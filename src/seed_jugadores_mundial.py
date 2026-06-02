"""
Carga las plantillas de las 48 selecciones del Mundial 2026 (1247 jugadores)
desde el CSV verificado contra fuentes cruzadas (Reuters / TyC / Football365 /
AS), generado de `listas_jugadores_mundial_2026_VERIFICADO.xlsx`.

Idempotente: por cada selección, borra los jugadores existentes (DELETE por
equipo_id) y carga los del CSV. Re-correr no duplica.

Campos en `jugadores`:
- nombre, equipo_id, posicion (POR/DEF/MED/DEL), nacionalidad (= seleccion),
  rating=70 default (sin EA FC todavía — paso 1 del roadmap), notas (= club
  si vino en la fuente).

Uso:
    python -m src.seed_jugadores_mundial --dry-run
    python -m src.seed_jugadores_mundial
"""
from __future__ import annotations
import argparse
import csv
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

from .supabase_writer import sb_get, sb_post, _sb_url, _headers

CSV_PATH = Path(__file__).parent / "data" / "jugadores_mundial2026_1247.csv"

# xlsx (espanol) -> posicion en DB (mismo set que ingest_squads.POSITION_MAP)
POSITION_MAP = {
    "Arquero":       "POR",
    "Defensor":      "DEF",
    "Mediocampista": "MED",
    "Delantero":     "DEL",
}

# Selecciones xlsx -> equipos.nombre. 47 idénticas, solo 1 distinta.
NAME_OVERRIDES = {
    "RD Congo": "RD del Congo",
}


def delete_squad(eq_id: int) -> None:
    """Borra todos los jugadores de un equipo. Reusa el patrón de ingest_squads."""
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/jugadores?equipo_id=eq.{eq_id}",
        headers=_headers({"Prefer": "return=minimal"}),
        method="DELETE",
    )
    urllib.request.urlopen(req, timeout=30).read()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    eq = sb_get("equipos?select=id,nombre&liga_id=eq.7")
    name2id = {e["nombre"]: e["id"] for e in eq}

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[mundial] CSV: {len(rows)} jugadores")

    # Resolver seleccion -> id, agrupar payloads por equipo
    payloads_by_eq: dict[int, list[dict]] = defaultdict(list)
    missing_sel: set[str] = set()
    missing_pos: set[str] = set()
    name_by_id: dict[int, str] = {}
    for r in rows:
        sel = r["seleccion"]
        db_name = NAME_OVERRIDES.get(sel, sel)
        eq_id = name2id.get(db_name)
        if eq_id is None:
            missing_sel.add(sel)
            continue
        name_by_id[eq_id] = db_name
        pos = POSITION_MAP.get(r["posicion"])
        if pos is None:
            missing_pos.add(r["posicion"])
            continue
        club = (r.get("club") or "").strip() or None
        payloads_by_eq[eq_id].append({
            "nombre":       r["jugador"].strip(),
            "equipo_id":    eq_id,
            "posicion":     pos,
            "nacionalidad": db_name,
            "rating":       70,
            "notas":        club,
        })

    if missing_sel:
        print(f"  ! selecciones sin id en DB: {sorted(missing_sel)}")
        return
    if missing_pos:
        print(f"  ! posiciones sin mapeo: {sorted(missing_pos)}")
        return

    total = sum(len(v) for v in payloads_by_eq.values())
    print(f"\n[mundial] {len(payloads_by_eq)} selecciones, {total} jugadores listos")

    # Resumen por seleccion
    if args.dry_run:
        print("\n[mundial] preview (primeras 5 selecciones):")
        for eq_id in sorted(payloads_by_eq)[:5]:
            pls = payloads_by_eq[eq_id]
            by_pos = Counter(p["posicion"] for p in pls)
            print(f"  id={eq_id:>3} {name_by_id[eq_id]:<22} n={len(pls)} "
                  f"({by_pos['POR']} POR / {by_pos['DEF']} DEF / "
                  f"{by_pos['MED']} MED / {by_pos['DEL']} DEL)")
        print("\n(dry-run, no se escribió nada)")
        return

    # Carga real: borrar + insertar por equipo
    total_inserted = 0
    for eq_id in sorted(payloads_by_eq):
        pls = payloads_by_eq[eq_id]
        try:
            delete_squad(eq_id)
        except Exception as e:
            print(f"  ! delete squad {eq_id}: {e}")
            continue
        try:
            sb_post("jugadores", pls, prefer="return=minimal")
            total_inserted += len(pls)
            by_pos = Counter(p["posicion"] for p in pls)
            print(f"  + {name_by_id[eq_id]:<22} id={eq_id:>3} n={len(pls)} "
                  f"({by_pos['POR']}/{by_pos['DEF']}/{by_pos['MED']}/{by_pos['DEL']})")
        except Exception as e:
            print(f"  ! insert {name_by_id[eq_id]}: {e}")
    print(f"\n[mundial] upsert OK: {total_inserted} jugadores en {len(payloads_by_eq)} selecciones")


if __name__ == "__main__":
    main()
