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

    # ═══ Ampliación: cruces entre grandes de cada liga ═══════════════════════════
    # ── La Liga ──────────────────────────────────────────────────────────────────
    ("Barcelona",       "Atlético Madrid", 116, 57,  79),  # (252)
    ("Real Madrid",     "Sevilla FC",      109, 32,  57),  # (198)
    ("Real Madrid",     "Valencia",        112, 43,  59),  # (214)
    ("Real Madrid",     "Athletic",        126, 45,  79),  # (250)
    ("Real Madrid",     "Real Sociedad",   102, 38,  43),  # (183)
    ("Real Madrid",     "Real Betis",       77, 32,  32),  # (141)
    ("Real Madrid",     "Villarreal",       31, 17,   6),  # (54)
    ("Barcelona",       "Sevilla FC",      118, 39,  46),  # (203)
    ("Barcelona",       "Valencia",        115, 57,  59),  # (231)
    ("Barcelona",       "Athletic",        126, 40,  80),  # (246)
    ("Barcelona",       "Real Sociedad",   117, 42,  38),  # (197)
    ("Barcelona",       "Real Betis",       87, 26,  30),  # (143)
    ("Barcelona",       "Villarreal",       36, 10,  12),  # (58)
    # ── Premier League (Big Six entre sí) ────────────────────────────────────────
    ("Arsenal",         "Chelsea",          87, 62,  66),  # (215)
    ("Arsenal",         "Liverpool",        83, 67,  96),  # (246) fuentes en conflicto
    ("Arsenal",         "Man United",       90, 60, 101),  # (251)
    ("Arsenal",         "Man. City",        87, 46,  56),  # (189)
    ("Chelsea",         "Liverpool",        59, 49,  75),  # (183)
    ("Chelsea",         "Man United",       57, 57,  85),  # (199)
    ("Chelsea",         "Man. City",        71, 42,  70),  # (183)
    ("Chelsea",         "Tottenham",        83, 42,  56),  # (181)
    ("Liverpool",       "Man. City",       108, 58,  60),  # (226)
    ("Liverpool",       "Tottenham",        84, 42,  44),  # (170)
    ("Man United",      "Tottenham",        97, 52,  58),  # (207)
    ("Man. City",       "Tottenham",        69, 37,  69),  # (175)
    # ── Serie A (grandes entre sí) ────────────────────────────────────────────────
    ("Juventus",        "Inter Milán",     114, 63,  78),  # (255) Derby d'Italia
    ("Juventus",        "Napoli",           85, 55,  46),  # (186)
    ("Juventus",        "Roma",             96, 59,  49),  # (204)
    ("Juventus",        "Lazio",            86, 38,  35),  # (159)
    ("Inter Milán",     "Napoli",           81, 45,  52),  # (178)
    ("Inter Milán",     "Roma",             99, 57,  63),  # (219)
    ("Inter Milán",     "Lazio",            78, 62,  45),  # (185)
    ("AC Milán",        "Napoli",           68, 54,  53),  # (175)
    ("AC Milán",        "Roma",             88, 63,  53),  # (204)
    ("AC Milán",        "Lazio",            86, 65,  41),  # (192)
    ("Napoli",          "Roma",             53, 60,  63),  # (176)
    ("Napoli",          "Lazio",            64, 53,  53),  # (170)
    # ── Bundesliga (Bayern/Dortmund vs clásicos) ──────────────────────────────────
    ("Bayern Múnich",   "M'gladbach",       63, 32,  29),  # (124)
    ("Bayern Múnich",   "Bremen",           76, 26,  29),  # (131)
    ("Bayern Múnich",   "HSV",              74, 24,  23),  # (121)
    ("Bayern Múnich",   "Stuttgart",        98, 29,  37),  # (164)
    ("Bayern Múnich",   "1. FC Köln",       61, 24,  24),  # (109)
    ("Dortmund",        "M'gladbach",       61, 36,  37),  # (134)
    ("Dortmund",        "Bremen",           55, 21,  46),  # (122)
    # ── Premier ↔ Ligue 1 (cruces PSG/Lyon) ──────────────────────────────────────
    ("PSG",             "Lille",            29, 13,   7),  # (49)
    ("PSG",             "RC Lens",          16,  8,   4),  # (28)
    ("PSG",             "Nice",             22,  7,  14),  # (43)
    ("Olympique Lyon",  "Lille",            15, 17,  16),  # (48)
    ("Olympique Lyon",  "RC Lens",          13,  6,   8),  # (27)
]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    eq = sb_get("equipos?select=id,nombre")
    name2id = {e["nombre"]: e["id"] for e in eq}

    # H2H existente (couk) para preservar las goleadas 4+ ya calculadas.
    # Se pagina porque PostgREST corta en 1000 filas y la tabla tiene ~3000.
    existing = {}
    offset = 0
    while True:
        chunk = sb_get("h2h_historico?select=equipo_a_id,equipo_b_id,goleadas_a,goleadas_b"
                       f"&order=id&limit=1000&offset={offset}")
        for r in chunk:
            existing[(r["equipo_a_id"], r["equipo_b_id"])] = (r["goleadas_a"], r["goleadas_b"])
        if len(chunk) < 1000:
            break
        offset += 1000

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
