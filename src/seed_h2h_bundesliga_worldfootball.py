"""
Carga la matriz de los 153 cruces all-time entre los 18 equipos de Bundesliga
2025/26 desde worldfootball.net (historial H2H, todas las competiciones cuando
la fuente lo agrega).

Regla: por cada cruce, comparar `partidos` con lo que ya está en h2h_historico y
quedarse con el que tenga MÁS partidos.

Goleadas 4+: worldfootball no las expone agregadas, así que se PRESERVAN las
existentes si las hay.

Nota histórica: Bayer Leverkusen (id=64) y Eintracht Frankfurt (id=65)
estaban en `equipos.liga_id=1` (Champions) en lugar de liga=5, así que el
seed couk los ignoraba. Sus cruces se cargaron acá por primera vez (33
NUEVOS) y luego se movieron a Bundesliga. Idem Marseille (67) y Monaco
(68) que pasaron a Ligue 1 (6).

Fuente del row resultante: "worldfootball".

Uso:
    python -m src.seed_h2h_bundesliga_worldfootball --dry-run
    python -m src.seed_h2h_bundesliga_worldfootball
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from .supabase_writer import sb_get, sb_post

CSV_PATH = Path(__file__).parent / "data" / "bundesliga_worldfootball_153.csv"

# worldfootball.net name -> equipos.nombre. Validado: 0 missing.
NAME_MAP = {
    "1. FC Heidenheim 1846": "Heidenheim",
    "1. FC Köln":            "1. FC Köln",
    "1. FC Union Berlin":    "Union Berlin",
    "1. FSV Mainz 05":       "Mainz",
    "1899 Hoffenheim":       "Hoffenheim",
    "Bayer Leverkusen":      "Leverkusen",
    "Bayern Munich":         "Bayern Múnich",
    "Bor. Mönchengladbach":  "M'gladbach",
    "Borussia Dortmund":     "Dortmund",
    "Eintracht Frankfurt":   "Frankfurt",
    "FC Augsburg":           "Augsburg",
    "FC St. Pauli":          "St. Pauli",
    "Hamburger SV":          "HSV",
    "RB Leipzig":            "RB Leipzig",
    "SC Freiburg":           "Freiburg",
    "VfB Stuttgart":         "Stuttgart",
    "VfL Wolfsburg":         "Wolfsburg",
    "Werder Bremen":         "Bremen",
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
    print(f"[worldfootball] h2h_historico actual: {len(existing)} pares")

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[worldfootball] CSV: {len(rows)} cruces")

    payloads: list[dict] = []
    new_pairs = 0
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
            new_pairs += 1
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
            "fuente": "worldfootball",
        })

    print(f"\n[worldfootball] resumen:")
    print(f"  - upserts totales:     {len(payloads)}")
    print(f"    de los cuales nuevos: {new_pairs} (Leverkusen/Frankfurt vs resto)")
    print(f"  - skip (db gana):      {skips_db_wins}")
    print(f"  - skip (empate):       {skips_tie}")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return
    if not payloads:
        print("\n[worldfootball] nada que upsert")
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
    print(f"\n[worldfootball] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
