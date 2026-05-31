"""
Carga la matriz de los 190 cruces all-time entre los 20 equipos de Premier League
2025/26 desde 11v11.com (historial global por rival, todas las competiciones que
11v11 indexa). Mismo patrón que `seed_h2h_laliga_bdfutbol.py`:

Regla: por cada cruce, comparar `partidos` con lo que ya está en h2h_historico y
quedarse con el que tenga MÁS partidos.

Goleadas 4+: 11v11 no las expone, así que se PRESERVAN las que ya calculó couk.

Fuente del row resultante: "11v11".

Uso:
    python -m src.seed_h2h_premier_11v11 --dry-run
    python -m src.seed_h2h_premier_11v11
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from .supabase_writer import sb_get, sb_post

CSV_PATH = Path(__file__).parent / "data" / "premier_11v11_190.csv"

# XLSX (11v11) name -> equipos.nombre. Validado: 0 missing.
NAME_MAP = {
    "AFC Bournemouth":          "Bournemouth",
    "Arsenal":                  "Arsenal",
    "Aston Villa":              "Aston Villa",
    "Brentford":                "Brentford",
    "Brighton and Hove Albion": "Brighton Hove",
    "Burnley":                  "Burnley",
    "Chelsea":                  "Chelsea",
    "Crystal Palace":           "Crystal Palace",
    "Everton":                  "Everton",
    "Fulham":                   "Fulham",
    "Leeds United":             "Leeds United",
    "Liverpool":                "Liverpool",
    "Manchester City":          "Man. City",
    "Manchester United":        "Man United",
    "Newcastle United":         "Newcastle",
    "Nottingham Forest":        "Nottingham",
    "Sunderland":               "Sunderland",
    "Tottenham Hotspur":        "Tottenham",
    "West Ham United":          "West Ham",
    "Wolverhampton Wanderers":  "Wolverhampton",
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
    print(f"[11v11] h2h_historico actual: {len(existing)} pares")

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[11v11] CSV: {len(rows)} cruces")

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
            "fuente": "11v11",
        })

    print(f"\n[11v11] resumen:")
    print(f"  - updates (xlsx > db): {len(payloads)}")
    print(f"  - skip (db gana):      {skips_db_wins}")
    print(f"  - skip (empate):       {skips_tie}")

    if payloads:
        print(f"\n[11v11] muestra (primeros 15):")
        for pl in payloads[:15]:
            a, b = id2name[pl["equipo_a_id"]], id2name[pl["equipo_b_id"]]
            ex = existing.get((pl["equipo_a_id"], pl["equipo_b_id"]))
            ex_n = ex["partidos"] if ex else 0
            print(f"  {a:<16} {pl['victorias_a']}-{pl['empates']}-{pl['victorias_b']} {b:<16} "
                  f"n={pl['partidos']} (antes {ex_n}, +{pl['partidos']-ex_n})")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return
    if not payloads:
        print("\n[11v11] nada que upsert")
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
    print(f"\n[11v11] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
