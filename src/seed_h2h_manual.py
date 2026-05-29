"""
Carga manual del head-to-head HISTÓRICO COMPLETO (toda la historia, todas las
competiciones) para los clásicos/derbis más relevantes de clubes europeos.

Motivo: `seed_h2h_historico` (fuente couk) solo cubre partidos de LIGA desde 1995.
Para las grandes rivalidades eso subcuenta el H2H real (ej. El Clásico tiene ~264
partidos en todas las competiciones, no 60 de liga). worldfootball.net tiene el
dato exacto pero bloquea el acceso programático (403), así que estos números se
cargan a mano desde fuentes oficiales (LaLiga.com, Bundesliga.com, Wikipedia de
cada rivalidad, etc.).

Las victorias/empates/partidos pasan a ser el total histórico real. Las goleadas
4+ no están disponibles en esas fuentes agregadas, así que se PRESERVAN las que
ya calculó couk (liga desde 1995) leyendo la fila existente.

Cada tupla: (nombre_X, nombre_Y, victorias_X, empates, victorias_Y)
El total de partidos es la suma de los tres. Los nombres deben coincidir EXACTO
con `equipos.nombre`.

Uso:
    python -m src.seed_h2h_manual --dry-run
    python -m src.seed_h2h_manual
"""
from __future__ import annotations
import argparse

from .supabase_writer import sb_get, sb_post

# (X, Y, victorias_X, empates, victorias_Y) — total = suma. Fuentes oficiales.
H2H_MANUAL: list[tuple[str, str, int, int, int]] = [
    # ── La Liga ──────────────────────────────────────────────────────────────
    ("Real Madrid",     "Barcelona",       106, 52, 106),  # El Clásico (264)
    ("Real Madrid",     "Atlético Madrid", 156, 73,  76),  # Derbi madrileño (305)
    ("Sevilla FC",      "Real Betis",       66, 36,  42),  # Gran Derbi (144)
    ("Athletic",        "Real Sociedad",    79, 50,  62),  # Derbi vasco (191)
    ("Barcelona",       "Espanyol",        130, 46,  44),  # Derbi barceloní (220)
    # ── Premier League ─────────────────────────────────────────────────────────
    ("Man United",      "Liverpool",        93, 70,  82),  # (245)
    ("Arsenal",         "Tottenham",        91, 54,  68),  # North London derby (213)
    ("Man United",      "Man. City",        81, 55,  62),  # Manchester derby (198)
    ("Liverpool",       "Everton",         101, 78,  68),  # Merseyside derby (247)
    # ── Serie A ─────────────────────────────────────────────────────────────────
    ("Inter Milán",     "AC Milán",         91, 71,  82),  # Derby della Madonnina (244)
    ("Roma",            "Lazio",            71, 65,  51),  # Derby della Capitale (187)
    ("Juventus",        "Torino",           96, 59,  58),  # Derby della Mole (213)
    ("Juventus",        "AC Milán",         80, 73,  57),  # (210)
    # ── Bundesliga ──────────────────────────────────────────────────────────────
    ("Bayern Múnich",   "Dortmund",         68, 37,  33),  # Der Klassiker (138)
    # ── Ligue 1 ──────────────────────────────────────────────────────────────────
    ("PSG",             "Olympique Lyon",   24,  8,  15),  # (47)
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    eq = sb_get("equipos?select=id,nombre")
    name2id = {e["nombre"]: e["id"] for e in eq}

    # H2H existente (couk) para preservar las goleadas 4+ ya calculadas.
    existing = {}
    for r in sb_get("h2h_historico?select=equipo_a_id,equipo_b_id,goleadas_a,goleadas_b"):
        existing[(r["equipo_a_id"], r["equipo_b_id"])] = (r["goleadas_a"], r["goleadas_b"])

    payloads = []
    for nx, ny, wx, e, wy in H2H_MANUAL:
        ix, iy = name2id.get(nx), name2id.get(ny)
        if ix is None or iy is None:
            print(f"  ! sin id: {nx!r}({ix}) / {ny!r}({iy}) — salteado")
            continue
        # Orden canónico a_id < b_id; victorias_a = equipo de menor id.
        if ix < iy:
            a, b, va, vb = ix, iy, wx, wy
        else:
            a, b, va, vb = iy, ix, wy, wx
        ga, gb = existing.get((a, b), (0, 0))  # preservar goleadas de couk
        payloads.append({
            "equipo_a_id": a, "equipo_b_id": b,
            "victorias_a": va, "victorias_b": vb, "empates": e,
            "goleadas_a": ga, "goleadas_b": gb,
            "partidos": va + vb + e, "fuente": "manual",
        })

    id2name = {e["id"]: e["nombre"] for e in eq}
    print(f"[h2h-manual] {len(payloads)} pares a upsert:")
    for pl in payloads:
        a, b = id2name[pl["equipo_a_id"]], id2name[pl["equipo_b_id"]]
        print(f"  {a:<16} {pl['victorias_a']}-{pl['empates']}-{pl['victorias_b']} {b:<16} "
              f"(n={pl['partidos']}, goleadas {pl['goleadas_a']}/{pl['goleadas_b']} de couk)")

    if args.dry_run:
        print("\n(dry-run, no se escribió nada)")
        return

    sb_post("h2h_historico?on_conflict=equipo_a_id,equipo_b_id", payloads,
            prefer="resolution=merge-duplicates,return=minimal")
    print(f"\n[h2h-manual] upsert OK: {len(payloads)} pares")


if __name__ == "__main__":
    main()
