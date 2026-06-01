"""
Carga los 42 cruces verificados (de 153 posibles) entre los 18 equipos de
Ligue 1 2025/26 desde worldfootball.net / Wikipedia / LiveFutbol. Los 111
cruces pendientes (sin conteo capturado en la fuente) NO se cargan.

Regla: por cada cruce, comparar `partidos` con lo que ya está en h2h_historico
y quedarse con el que tenga MÁS partidos.

Goleadas 4+: la fuente no las expone agregadas, así que se PRESERVAN las
existentes si las hay.

Nota: Marseille (id=67) y Monaco (id=68) fueron recién pasados a liga_id=6
(antes estaban en Champions / liga_id=1). El seed couk no los había procesado
contra Ligue 1, así que sus cruces aparecen como NUEVOS acá.

Fuente del row resultante: "worldfootball-ligue1".

Uso:
    python -m src.seed_h2h_ligue1_worldfootball --dry-run
    python -m src.seed_h2h_ligue1_worldfootball
"""
from __future__ import annotations
import argparse
import csv
from pathlib import Path

from .supabase_writer import sb_get, sb_post

CSV_PATH = Path(__file__).parent / "data" / "ligue1_worldfootball_42.csv"

# Source name -> equipos.nombre. Validado: 0 missing.
NAME_MAP = {
    "AJ Auxerre":             "Auxerre",
    "AS Monaco":              "Monaco",
    "Angers SCO":             "Angers SCO",
    "FC Lorient":             "Lorient",
    "FC Metz":                "FC Metz",
    "FC Nantes":              "Nantes",
    "Havre AC":               "Le Havre",
    "Lille OSC":              "Lille",
    "OGC Nice":               "Nice",
    "Olympique Lyonnais":     "Olympique Lyon",
    "Olympique de Marseille": "Marseille",
    "Paris FC":               "Paris FC",
    "Paris Saint-Germain":    "PSG",
    "RC Lens":                "RC Lens",
    "Racing Strasbourg":      "Strasbourg",
    "Stade Brestois 29":      "Brest",
    "Stade Rennais":          "Stade Rennais",
    "Toulouse FC":            "Toulouse",
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
    print(f"[ligue1] h2h_historico actual: {len(existing)} pares")

    with open(CSV_PATH, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"[ligue1] CSV: {len(rows)} cruces verificados")

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
            "fuente": "worldfootball-ligue1",
        })

    print(f"\n[ligue1] resumen:")
    print(f"  - upserts totales:     {len(payloads)}")
    print(f"    de los cuales nuevos: {new_pairs} (Marseille/Monaco vs resto + alguno mas)")
    print(f"  - skip (db gana):      {skips_db_wins}")
    print(f"  - skip (empate):       {skips_tie}")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return
    if not payloads:
        print("\n[ligue1] nada que upsert")
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
    print(f"\n[ligue1] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
