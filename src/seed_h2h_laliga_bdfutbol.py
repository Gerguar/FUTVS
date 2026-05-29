"""
Carga la matriz de los 190 cruces all-time entre los 20 equipos de La Liga 2025/26
desde BDFutbol (4 verificados All competitions) + engsoccerdata 1928/29-2024/25 +
Football-Data 2025/26 (186 pendientes, solo Liga).

Regla: por cada cruce, comparar `partidos` con lo que ya está en h2h_historico y
quedarse con el que tenga MÁS partidos. Esto:
- Mejora los 126 cruces que en DB venían de couk (Liga desde 1995) — el xlsx cubre
  Liga desde 1928/29, así que gana en cobertura.
- Preserva los 18 cruces ya cargados como "manual" (all-time, todas las
  competiciones) — para ellos el xlsx tiene sólo Liga y pierde.

Goleadas 4+: el xlsx no las trae, así que se PRESERVAN las que ya calculó couk.

Fuente del row resultante:
- "bdfutbol" si la fila del xlsx está marcada como verified.
- "bdfutbol-liga" si es solo-Liga.

Uso:
    python -m src.seed_h2h_laliga_bdfutbol --dry-run
    python -m src.seed_h2h_laliga_bdfutbol
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from .supabase_writer import sb_get, sb_post

CSV_PATH = Path(__file__).parent / "data" / "laliga_bdfutbol_190.csv"

# XLSX (BDFutbol) name -> equipos.nombre. Validado: 0 missing.
NAME_MAP = {
    "Athletic Club":       "Athletic",
    "Atlético de Madrid":  "Atlético Madrid",
    "CA Osasuna":          "Osasuna",
    "Celta de Vigo":       "Celta",
    "Deportivo Alavés":    "Alavés",
    "Elche CF":            "Elche",
    "FC Barcelona":        "Barcelona",
    "Getafe CF":           "Getafe",
    "Girona FC":           "Girona",
    "Levante UD":          "Levante",
    "RCD Espanyol":        "Espanyol",
    "RCD Mallorca":        "Mallorca",
    "Rayo Vallecano":      "Rayo Vallecano",
    "Real Betis":          "Real Betis",
    "Real Madrid":         "Real Madrid",
    "Real Oviedo":         "Real Oviedo",
    "Real Sociedad":       "Real Sociedad",
    "Sevilla FC":          "Sevilla FC",
    "Valencia CF":         "Valencia",
    "Villarreal CF":       "Villarreal",
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    eq = sb_get("equipos?select=id,nombre")
    name2id = {e["nombre"]: e["id"] for e in eq}
    id2name = {e["id"]: e["nombre"] for e in eq}

    # Verificar mapeo
    miss = [v for v in NAME_MAP.values() if v not in name2id]
    if miss:
        print(f"  ! nombres NO en equipos: {miss}")
        return

    # H2H existente (paginado por el cap de 1000 de PostgREST).
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
    print(f"[bdfutbol] h2h_historico actual: {len(existing)} pares")

    # Leer CSV
    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[bdfutbol] CSV: {len(rows)} cruces")

    payloads: list[dict] = []
    skips_db_wins = 0
    skips_tie = 0
    for r in rows:
        e1 = NAME_MAP[r["equipo_x"]]
        e2 = NAME_MAP[r["equipo_y"]]
        v1, vy, emp, n = int(r["victorias_x"]), int(r["victorias_y"]), int(r["empates"]), int(r["partidos"])
        verified = r["verified"] == "1"
        ix, iy = name2id[e1], name2id[e2]
        # Canonical: a_id < b_id
        if ix < iy:
            a, b, va, vb = ix, iy, v1, vy
        else:
            a, b, va, vb = iy, ix, vy, v1

        ex = existing.get((a, b))
        if ex is None:
            ga, gb = 0, 0  # no debería pasar (los 190 ya existen), pero por las dudas
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
            "fuente": "bdfutbol" if verified else "bdfutbol-liga",
        })

    print(f"\n[bdfutbol] resumen:")
    print(f"  - updates (xlsx > db): {len(payloads)}")
    print(f"  - skip (db gana):      {skips_db_wins}")
    print(f"  - skip (empate):       {skips_tie}")

    if payloads:
        print(f"\n[bdfutbol] muestra de updates (primeros 15):")
        for pl in payloads[:15]:
            a, b = id2name[pl["equipo_a_id"]], id2name[pl["equipo_b_id"]]
            ex = existing.get((pl["equipo_a_id"], pl["equipo_b_id"]))
            ex_n = ex["partidos"] if ex else 0
            print(f"  {a:<18} {pl['victorias_a']}-{pl['empates']}-{pl['victorias_b']} {b:<18} "
                  f"n={pl['partidos']} (antes {ex_n}, +{pl['partidos']-ex_n}) [{pl['fuente']}]")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return

    if not payloads:
        print("\n[bdfutbol] nada que upsert")
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
    print(f"\n[bdfutbol] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
