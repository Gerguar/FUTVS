"""
Carga partidos pasados de selecciones (2025-01-01 → hoy) a la tabla `partidos`
con liga_id=7, estado='finalizado', temporada='2025'.

Fuente: martj42/international_results CSV (~49k partidos desde 1872).

Esto permite que `loadTeamSeasonStats` del frontend calcule automáticamente
GOLES A FAVOR, GOLES EN CONTRA, V/E/D, partidos jugados para cada selección
del Mundial 2026, sin tocar el cuadro de estadísticas existente.

Dedupe por (liga_id=7, fecha[YYYY-MM-DD], equipo_local_id, equipo_visitante_id).
Idempotente: re-correr no duplica.

Uso:
    python -m src.ingest_partidos_selecciones_2025 --dry-run
    python -m src.ingest_partidos_selecciones_2025
"""
from __future__ import annotations
import argparse
import io
import json
import urllib.request
from datetime import datetime, timezone

import pandas as pd

from .replay_elo_selecciones import NAME_TO_SLUG, HIST_URL
from .supabase_writer import sb_get, sb_post


LIGA_SELECCIONES = 7      # 48 selecciones del Mundial 2026
LIGA_OTRAS = 8            # rivales historicos no-Mundial (Zambia, Mauritania, ...)
SINCE_DATE = "2025-01-01"
# Excluir partidos del Mundial 2026 y posteriores: esos los maneja
# ingest_wc2026.py con kickoff exacto desde football-data. Si dejamos que
# este script los procese, mete duplicados por desfasaje de timezone:
# martj42 da la fecha local (2026-06-11) y football-data da UTC
# (2026-06-12T02:00:00Z), entonces el dedup por YYYY-MM-DD no matchea y
# crea registros duplicados (bug detectado 13-jun-2026, ids 990/991).
UNTIL_DATE = "2026-06-11"


def build_name_to_id() -> dict[str, int]:
    """martj42 EN -> equipos.id (liga=7)."""
    elo = sb_get("selecciones_elo?select=slug,nombre")
    slug2nombre = {r["slug"]: r["nombre"] for r in elo}
    eq = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_SELECCIONES}")
    nombre2id = {e["nombre"]: e["id"] for e in eq}
    out: dict[str, int] = {}
    for en, slug in NAME_TO_SLUG.items():
        nombre = slug2nombre.get(slug)
        if not nombre:
            continue
        eid = nombre2id.get(nombre)
        if eid is None:
            continue
        out[en] = eid
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--since", default=SINCE_DATE,
                   help=f"Fecha desde (default {SINCE_DATE})")
    args = p.parse_args()

    print(f"[partidos-sel] bajando martj42...")
    with urllib.request.urlopen(HIST_URL, timeout=60) as r:
        data = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(data))
    df = df[df["home_score"].notna() & df["away_score"].notna()].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] >= pd.to_datetime(args.since)]
    today = pd.Timestamp.now(tz="UTC").tz_localize(None)
    df = df[df["date"] <= today]
    # Cortar antes del Mundial: esos los maneja ingest_wc2026.py. Si dejamos
    # que martj42 los procese, mete duplicados por timezone (ver UNTIL_DATE
    # arriba para detalles).
    df = df[df["date"] < pd.to_datetime(UNTIL_DATE)]
    print(f"[partidos-sel] martj42 {args.since} → {UNTIL_DATE} (excl): {len(df):,} partidos")

    en2id = build_name_to_id()

    # Para que se carguen los amistosos contra equipos NO del Mundial
    # (Zambia, Mauritania, Angola, Puerto Rico, etc), auto-creamos esos
    # equipos en LIGA_OTRAS y los reusamos en futuros runs.
    # Solo nos importan los partidos donde al menos UNO de los equipos
    # es del Mundial — los partidos de no-Mundial vs no-Mundial los
    # ignoramos (no aportan a forma_reciente de selecciones del Mundial).
    mundial_set = set(en2id.keys())
    home_in = df["home_team"].isin(mundial_set)
    away_in = df["away_team"].isin(mundial_set)
    df = df[home_in | away_in].copy()  # al menos uno del Mundial

    # Cache de equipos de LIGA_OTRAS ya cargados (no duplicar)
    existing_otras = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_OTRAS}")
    otras_nombre2id = {e["nombre"]: e["id"] for e in existing_otras}

    # Detectar nombres no mapeados (rivales no-Mundial)
    needed = set()
    for _, row in df.iterrows():
        if row["home_team"] not in en2id and row["home_team"] not in otras_nombre2id:
            needed.add(row["home_team"])
        if row["away_team"] not in en2id and row["away_team"] not in otras_nombre2id:
            needed.add(row["away_team"])

    # Crear los faltantes en LIGA_OTRAS
    if needed:
        print(f"[partidos-sel] creando {len(needed)} equipos nuevos en LIGA_OTRAS (no-Mundial)...")
        payloads_eq = [{"nombre": n, "liga_id": LIGA_OTRAS} for n in sorted(needed)]
        try:
            from .supabase_writer import sb_post as _sbp
            created = _sbp("equipos", payloads_eq, prefer="return=representation")
            for e in (created or []):
                otras_nombre2id[e["nombre"]] = e["id"]
            print(f"[partidos-sel] equipos creados OK: {len(created or [])}")
        except Exception as e:
            print(f"[partidos-sel] WARN: error creando equipos otras: {e}")

    # Mapear ambos lados ahora con en2id (Mundial) + otras_nombre2id (no-Mundial)
    def map_id(name):
        return en2id.get(name) or otras_nombre2id.get(name)

    df["home_team_id"] = df["home_team"].map(map_id)
    df["away_team_id"] = df["away_team"].map(map_id)
    df = df.dropna(subset=["home_team_id", "away_team_id"]).copy()
    df["home_team_id"] = df["home_team_id"].astype(int)
    df["away_team_id"] = df["away_team_id"].astype(int)
    df["home_goals"] = df["home_score"].astype(int)
    df["away_goals"] = df["away_score"].astype(int)
    print(f"[partidos-sel] mapeados a equipo_id: {len(df):,} partidos")

    # Dedupe contra existentes en DB (por (liga, fecha YYYY-MM-DD, local, visitante))
    existing = sb_get(
        f"partidos?select=fecha,equipo_local_id,equipo_visitante_id"
        f"&liga_id=eq.{LIGA_SELECCIONES}&estado=eq.finalizado&limit=5000"
    )
    existing_keys = {(r["fecha"][:10], r["equipo_local_id"], r["equipo_visitante_id"])
                     for r in existing}

    payloads = []
    for _, row in df.iterrows():
        fecha_iso = row["date"].strftime("%Y-%m-%dT%H:%M:%S")
        key = (fecha_iso[:10], int(row["home_team_id"]), int(row["away_team_id"]))
        if key in existing_keys:
            continue
        payloads.append({
            "liga_id":             LIGA_SELECCIONES,
            "equipo_local_id":     int(row["home_team_id"]),
            "equipo_visitante_id": int(row["away_team_id"]),
            "fecha":               fecha_iso,
            "temporada":           "2025",
            "goles_local":         int(row["home_goals"]),
            "goles_visitante":     int(row["away_goals"]),
            "estado":              "finalizado",
        })

    print(f"\n[partidos-sel] nuevos a insertar: {len(payloads)} | ya existentes: {len(existing_keys)}")
    if payloads:
        print(f"  primeros 5:")
        for pl in payloads[:5]:
            print(f"    {pl['fecha'][:10]} eq_local={pl['equipo_local_id']} vs eq_visit={pl['equipo_visitante_id']} "
                  f"{pl['goles_local']}-{pl['goles_visitante']}")

    if args.dry_run:
        print("\n(dry-run)")
        return
    if not payloads:
        print("[partidos-sel] nada nuevo que cargar")
        return

    print(f"\n[partidos-sel] insertando en batches de 100...")
    ok = 0
    BATCH = 100
    for i in range(0, len(payloads), BATCH):
        chunk = payloads[i:i + BATCH]
        try:
            sb_post("partidos", chunk, prefer="return=minimal")
            ok += len(chunk)
        except Exception as e:
            print(f"  ! batch {i}: {e}")
    print(f"[partidos-sel] OK: {ok}/{len(payloads)} insertados")


if __name__ == "__main__":
    main()
