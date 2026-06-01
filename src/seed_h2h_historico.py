"""
Agrega el head-to-head histórico (victorias, empates, goleadas 4+) en la tabla
`h2h_historico`, que el comparador lee para las filas "Mano a mano: Victorias"
y "Goleadas históricas".

Fuentes:
- CLUBES (liga 2-6): football-data.co.uk vía src.ingest_couk (resultados de liga
  de las 5 grandes, ~desde 1995). Mapeo de nombres con team_normalize.canonical.
- SELECCIONES (liga 7): martj42/international_results (todos los internacionales
  desde 1872). Mapeo EN -> slug (NAME_TO_SLUG) -> nombre (selecciones_elo) -> id.

Orden canónico: cada par se guarda con equipo_a_id < equipo_b_id. victorias_a y
goleadas_a corresponden SIEMPRE al equipo con id menor.

Uso:
    python -m src.seed_h2h_historico --dry-run
    python -m src.seed_h2h_historico
    python -m src.seed_h2h_historico --since 2000     # clubes desde temporada 2000/01
    python -m src.seed_h2h_historico --only nations
"""
from __future__ import annotations
import argparse
import io
import urllib.request
from collections import defaultdict

# Usa el almacén de certificados del SO (Windows) para validar TLS de
# football-data.co.uk, que sirve una cadena incompleta para certifi.
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import pandas as pd

from .supabase_writer import sb_get, sb_post
from .team_normalize import canonical
from .ingest_couk import backfill_couk, LEAGUE_MAP_COUK
from .replay_elo_selecciones import NAME_TO_SLUG, HIST_URL


LIGAS_CLUBES = (2, 3, 4, 5, 6)
LIGA_SELECCIONES = 7
GOLEADA_DIF = 4

# Equipos cuyo nombre en football-data.co.uk no canonicaliza igual que en la DB.
# {slug_canonico_de_couk: nombre_exacto_en_equipos}
COUK_ALIASES = {
    "oviedo":        "Real Oviedo",
    "pisa":          "AC Pisa",
    "werder_bremen": "Bremen",
    "hamburg":       "HSV",
    "lyon":          "Olympique Lyon",
}


class H2HAgg:
    """Acumulador por par canónico (a_id < b_id)."""
    def __init__(self):
        self.data: dict[tuple[int, int], dict] = defaultdict(
            lambda: {"va": 0, "vb": 0, "e": 0, "ga": 0, "gb": 0, "n": 0}
        )

    def add(self, id_home: int, id_away: int, gh: int, ga: int):
        if id_home == id_away:
            return
        a, b = (id_home, id_away) if id_home < id_away else (id_away, id_home)
        rec = self.data[(a, b)]
        rec["n"] += 1
        dif = abs(gh - ga)
        if gh == ga:
            rec["e"] += 1
            return
        home_won = gh > ga
        winner = id_home if home_won else id_away
        if winner == a:
            rec["va"] += 1
            if dif >= GOLEADA_DIF:
                rec["ga"] += 1
        else:
            rec["vb"] += 1
            if dif >= GOLEADA_DIF:
                rec["gb"] += 1

    def payloads(self, fuente: str) -> list[dict]:
        out = []
        for (a, b), r in self.data.items():
            out.append({
                "equipo_a_id": a, "equipo_b_id": b,
                "victorias_a": r["va"], "victorias_b": r["vb"],
                "empates": r["e"], "goleadas_a": r["ga"], "goleadas_b": r["gb"],
                "partidos": r["n"], "fuente": fuente,
            })
        return out


# ── CLUBES ─────────────────────────────────────────────────────────────────
def aggregate_clubs(since: int) -> tuple[H2HAgg, set[str]]:
    eq = sb_get(f"equipos?select=id,nombre,liga_id&liga_id=in.({','.join(map(str, LIGAS_CLUBES))})")
    slug2id = {canonical(e["nombre"]): e["id"] for e in eq}
    name2id = {e["nombre"]: e["id"] for e in eq}
    for couk_slug, db_nombre in COUK_ALIASES.items():
        if db_nombre in name2id:
            slug2id[couk_slug] = name2id[db_nombre]
    print(f"[h2h] clubes liga {LIGAS_CLUBES}: {len(eq)} equipos")

    seasons = list(range(since, 2026))
    df = backfill_couk(seasons=seasons, leagues=list(LEAGUE_MAP_COUK.keys()))
    print(f"[h2h] couk: {len(df)} partidos descargados ({since}/01..2025/26)")

    agg = H2HAgg()
    unmatched: set[str] = set()
    matched = 0
    for _, row in df.iterrows():
        hid = slug2id.get(canonical(row["home_team_name"]))
        aid = slug2id.get(canonical(row["away_team_name"]))
        if hid is None:
            unmatched.add(row["home_team_name"])
        if aid is None:
            unmatched.add(row["away_team_name"])
        if hid is None or aid is None:
            continue
        agg.add(hid, aid, int(row["home_goals"]), int(row["away_goals"]))
        matched += 1
    print(f"[h2h] clubes: {matched} partidos mapeados | {len(agg.data)} pares | {len(unmatched)} nombres sin match")
    return agg, unmatched


# ── SELECCIONES ──────────────────────────────────────────────────────────────
def _fetch_martj42() -> pd.DataFrame:
    print(f"[h2h] descargando {HIST_URL}")
    with urllib.request.urlopen(HIST_URL, timeout=60) as r:
        data = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(data))
    df = df[df["home_score"].notna() & df["away_score"].notna()]
    print(f"[h2h] martj42: {len(df):,} internacionales jugados")
    return df


def aggregate_nations() -> tuple[H2HAgg, set[str]]:
    elo = sb_get("selecciones_elo?select=slug,nombre")
    slug2nombre = {r["slug"]: r["nombre"] for r in elo}
    eq = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_SELECCIONES}")
    nombre2id = {e["nombre"]: e["id"] for e in eq}

    def name_to_id(en_name: str):
        slug = NAME_TO_SLUG.get(en_name)
        if not slug:
            return None
        nombre = slug2nombre.get(slug)
        if not nombre:
            return None
        return nombre2id.get(nombre)

    df = _fetch_martj42()
    agg = H2HAgg()
    unmatched: set[str] = set()
    matched = 0
    for _, row in df.iterrows():
        hid = name_to_id(row["home_team"])
        aid = name_to_id(row["away_team"])
        if hid is None:
            if row["home_team"] in NAME_TO_SLUG:
                unmatched.add(row["home_team"])
        if aid is None:
            if row["away_team"] in NAME_TO_SLUG:
                unmatched.add(row["away_team"])
        if hid is None or aid is None:
            continue
        agg.add(hid, aid, int(row["home_score"]), int(row["away_score"]))
        matched += 1
    print(f"[h2h] selecciones: {matched} partidos mapeados | {len(agg.data)} pares")
    return agg, unmatched


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since", type=int, default=1995, help="Temporada inicial clubes (default 1995).")
    p.add_argument("--only", choices=["clubs", "nations"], default=None)
    args = p.parse_args()

    payloads: list[dict] = []

    if args.only != "nations":
        agg_c, unmatched_c = aggregate_clubs(args.since)
        payloads += agg_c.payloads("couk")
        if unmatched_c:
            print(f"  clubes sin match ({len(unmatched_c)}): {sorted(unmatched_c)[:30]}")

    if args.only != "clubs":
        agg_n, _ = aggregate_nations()
        payloads += agg_n.payloads("martj42")

    print(f"\n[h2h] total pares a upsert: {len(payloads)}")

    # Protección: NO pisar pares que ya tengan una fuente más completa
    # (manual / bdfutbol / 11v11 / transfermarkt / worldfootball). Esos vienen
    # de matrices all-time externas (todas las competiciones) y siempre tienen
    # más partidos que el cálculo couk (liga solo desde 1995).
    BETTER_SOURCES = {"manual", "bdfutbol", "bdfutbol-liga",
                      "11v11", "transfermarkt", "worldfootball"}
    existing_better: set[tuple[int, int]] = set()
    offset = 0
    while True:
        chunk = sb_get(f"h2h_historico?select=equipo_a_id,equipo_b_id,fuente"
                       f"&order=id&limit=1000&offset={offset}")
        for r in chunk:
            if r["fuente"] in BETTER_SOURCES:
                existing_better.add((r["equipo_a_id"], r["equipo_b_id"]))
        if len(chunk) < 1000:
            break
        offset += 1000
    before = len(payloads)
    payloads = [pl for pl in payloads
                if (pl["equipo_a_id"], pl["equipo_b_id"]) not in existing_better]
    skipped = before - len(payloads)
    print(f"[h2h] protegidos por fuente all-time: {skipped} pares (no se pisan)")
    print(f"[h2h] pares efectivos a upsert: {len(payloads)}")

    if args.dry_run:
        print("\nEjemplos (primeros 12):")
        id2name = {e["id"]: e["nombre"] for e in sb_get("equipos?select=id,nombre")}
        for pl in payloads[:12]:
            a = id2name.get(pl["equipo_a_id"], pl["equipo_a_id"])
            b = id2name.get(pl["equipo_b_id"], pl["equipo_b_id"])
            print(f"  {a:<18} {pl['victorias_a']}-{pl['empates']}-{pl['victorias_b']} {b:<18} "
                  f"(goleadas {pl['goleadas_a']}/{pl['goleadas_b']}, n={pl['partidos']}, {pl['fuente']})")
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
    print(f"[h2h] upsert OK: {up} pares")


if __name__ == "__main__":
    main()
