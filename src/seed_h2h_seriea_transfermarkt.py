"""
Carga la matriz de cruces all-time entre los 20 equipos de Serie A 2025/26 desde
Transfermarkt (Record against, Competition=All). 157 verificados + 33 pendientes
(equipos recién ascendidos como Como, Cremonese, Pisa que aún no tienen H2H
verificado en la fuente). Los pendientes se saltean (no se cargan filas en cero).

Regla: por cada cruce, comparar `partidos` con lo que ya está en h2h_historico y
quedarse con el que tenga MÁS partidos.

Goleadas 4+: Transfermarkt no las expone agregadas, así que se PRESERVAN las que
ya calculó couk.

Fuente del row resultante: "transfermarkt".

Uso:
    python -m src.seed_h2h_seriea_transfermarkt --dry-run
    python -m src.seed_h2h_seriea_transfermarkt
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from .supabase_writer import sb_get, sb_post

CSV_PATH = Path(__file__).parent / "data" / "seriea_transfermarkt_190.csv"

# Transfermarkt name -> equipos.nombre. Validado: 0 missing.
NAME_MAP = {
    "Atalanta":      "Atalanta",
    "Bologna":       "Bologna",
    "Cagliari":      "Cagliari",
    "Como":          "Como 1907",
    "Cremonese":     "Cremonese",
    "Fiorentina":    "Fiorentina",
    "Genoa":         "Genoa",
    "Hellas Verona": "Verona",
    "Inter":         "Inter Milán",
    "Juventus":      "Juventus",
    "Lazio":         "Lazio",
    "Lecce":         "Lecce",
    "Milan":         "AC Milán",
    "Napoli":        "Napoli",
    "Parma":         "Parma",
    "Pisa":          "AC Pisa",
    "Roma":          "Roma",
    "Sassuolo":      "Sassuolo",
    "Torino":        "Torino",
    "Udinese":       "Udinese",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    eq = sb_get("equipos?select=id,nombre")
    name2id = {e["nombre"]: e["id"] for e in eq}
    id2name = {e["id"]: e["nombre"] for e in eq}

    miss = [v for v in NAME_MAP.values() if v not in name2id]
    if miss:
        print(f"  ! nombres NO en equipos: {miss}")
        return

    # h2h_historico paginado (cap 1000 de PostgREST).
    existing: dict[tuple[int, int], dict] = {}
    offset = 0
    while True:
        chunk = sb_get("h2h_historico?select=equipo_a_id,equipo_b_id,partidos,goleadas_a,goleadas_b,fuente"
                       f"&order=id&limit=1000&offset={offset}")
        for r in chunk:
            existing[(r["equipo_a_id"], r["equipo_b_id"])] = r
        if len(chunk) < 1000:
            break
        offset += 1000
    print(f"[transfermarkt] h2h_historico actual: {len(existing)} pares")

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[transfermarkt] CSV: {len(rows)} cruces verificados")

    payloads: list[dict] = []
    skips_db_wins = 0
    skips_tie = 0
    for r in rows:
        e1 = NAME_MAP[r["equipo_x"]]
        e2 = NAME_MAP[r["equipo_y"]]
        v1 = int(r["victorias_x"])
        v2 = int(r["victorias_y"])
        emp = int(r["empates"])
        n = int(r["partidos"])
        ix, iy = name2id[e1], name2id[e2]
        if ix < iy:
            a, b, va, vb = ix, iy, v1, v2
        else:
            a, b, va, vb = iy, ix, v2, v1

        ex = existing.get((a, b))
        if ex is None:
            ga, gb = 0, 0
        else:
            if ex["partidos"] > n:
                skips_db_wins += 1
                continue
            if ex["partidos"] == n:
                skips_tie += 1
                continue
            ga, gb = ex["goleadas_a"], ex["goleadas_b"]

        payloads.append({
            "equipo_a_id": a, "equipo_b_id": b,
            "victorias_a": va, "victorias_b": vb, "empates": emp,
            "goleadas_a": ga, "goleadas_b": gb,
            "partidos": va + vb + emp,
            "fuente": "transfermarkt",
        })

    print(f"\n[transfermarkt] resumen:")
    print(f"  - updates (xlsx > db): {len(payloads)}")
    print(f"  - skip (db gana):      {skips_db_wins}")
    print(f"  - skip (empate):       {skips_tie}")

    if payloads:
        print(f"\n[transfermarkt] muestra (primeros 12):")
        for pl in payloads[:12]:
            a, b = id2name[pl["equipo_a_id"]], id2name[pl["equipo_b_id"]]
            ex = existing.get((pl["equipo_a_id"], pl["equipo_b_id"]))
            ex_n = ex["partidos"] if ex else 0
            print(f"  {a:<14} {pl['victorias_a']}-{pl['empates']}-{pl['victorias_b']} {b:<14} "
                  f"n={pl['partidos']} (antes {ex_n}, +{pl['partidos']-ex_n})")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return
    if not payloads:
        print("\n[transfermarkt] nada que upsert")
        return

    BATCH = 100
    up = 0
    for i in range(0, len(payloads), BATCH):
        chunk = payloads[i:i + BATCH]
        try:
            sb_post("h2h_historico?on_conflict=equipo_a_id,equipo_b_id", chunk,
                    prefer="resolution=merge-duplicates,return=minimal")
            up += len(chunk)
        except Exception as e:
            print(f"  ! error upsert chunk {i}: {e}")
    print(f"\n[transfermarkt] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
