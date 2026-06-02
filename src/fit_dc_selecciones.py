"""
Entrena Dixon-Coles específico para selecciones nacionales con el dataset
martj42/international_results (~49k partidos internacionales desde 1872).

Output: data/dc_state_selecciones.json (paralelo a data/dc_state.json para
clubes). Usa equipos.id como identificador, igual que el sistema actual.

Las 48 selecciones del Mundial 2026 quedan con sus atributos atk/def
ajustados al histórico. El home_advantage se aprende del dataset.

Uso:
    python -m src.fit_dc_selecciones --xi 0.0035
    python -m src.fit_dc_selecciones --xi 0.0015 --since 2015
"""
from __future__ import annotations
import argparse
import io
import json
import urllib.request
from pathlib import Path

import pandas as pd

from .dixon_coles import fit
from .replay_elo_selecciones import NAME_TO_SLUG, HIST_URL
from .supabase_writer import sb_get


OUT_PATH = Path("data/dc_state_selecciones.json")

# Mundial 2026 ids para reporte de verificación al final
MUNDIAL_IDS = (
    111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    126, 127, 129, 130, 132, 133, 134, 135, 136, 141, 142, 145, 146, 148, 150,
    151, 153, 160, 161, 162, 168, 173, 178, 181, 187, 189, 192, 194, 196, 198,
    206, 211, 264,
)


def build_name_to_id() -> dict[str, int]:
    """martj42 EN -> equipos.id (liga=7). Encadena NAME_TO_SLUG + selecciones_elo + equipos."""
    elo = sb_get("selecciones_elo?select=slug,nombre")
    slug2nombre = {r["slug"]: r["nombre"] for r in elo}
    eq = sb_get("equipos?select=id,nombre&liga_id=eq.7")
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
    p.add_argument("--xi", type=float, default=0.0035,
                   help="Time decay (default 0.0035, mismo que clubes).")
    p.add_argument("--since", type=int, default=1990,
                   help="Filtrar partidos desde este año (default 1990).")
    args = p.parse_args()

    # 1. Bajar martj42
    print(f"[dc-selecciones] bajando {HIST_URL}")
    with urllib.request.urlopen(HIST_URL, timeout=60) as r:
        data = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(data))
    df = df[df["home_score"].notna() & df["away_score"].notna()].copy()
    print(f"[dc-selecciones] martj42: {len(df):,} partidos con resultado")

    # 2. Filtro temporal
    df["kickoff_ts_utc"] = pd.to_datetime(df["date"], utc=True)
    df = df[df["kickoff_ts_utc"].dt.year >= args.since]
    print(f"[dc-selecciones] desde {args.since}: {len(df):,} partidos")

    # 3. Mapeo EN -> equipo_id
    en2id = build_name_to_id()
    print(f"[dc-selecciones] selecciones mapeadas a equipo_id: {len(en2id)}")
    df["home_team_id"] = df["home_team"].map(en2id)
    df["away_team_id"] = df["away_team"].map(en2id)
    df = df.dropna(subset=["home_team_id", "away_team_id"]).copy()
    df["home_team_id"] = df["home_team_id"].astype(int)
    df["away_team_id"] = df["away_team_id"].astype(int)
    df["home_goals"] = df["home_score"].astype(int)
    df["away_goals"] = df["away_score"].astype(int)
    df["is_neutral"] = df["neutral"].astype(bool)
    print(f"[dc-selecciones] tras mapeo: {len(df):,} partidos | "
          f"selecciones únicas: {len(set(df['home_team_id']).union(df['away_team_id']))}")
    print(f"[dc-selecciones] neutral: {df['is_neutral'].sum():,} ({100*df['is_neutral'].mean():.1f}%)")

    # 4. Ajustar DC
    cols = ["kickoff_ts_utc", "home_team_id", "away_team_id",
            "home_goals", "away_goals", "is_neutral"]
    state = fit(df[cols], xi=args.xi)
    print(f"\n[dc-selecciones] home_adv (selecciones): {state.home_adv:.4f}  rho: {state.rho:.4f}")

    # 5. Guardar
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    # DixonColesState.to_json escribe en PATHS.dc_state por default; lo escribimos manual
    from dataclasses import asdict
    OUT_PATH.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    print(f"[dc-selecciones] guardado en {OUT_PATH}")

    # 6. Verificación: probabilidades en partidos icónicos del Mundial
    print(f"\nProbabilidades de muestra (campo neutral, xi={args.xi}):")
    eq = sb_get(f"equipos?select=id,nombre&id=in.({','.join(map(str, MUNDIAL_IDS))})")
    id2nombre = {e["id"]: e["nombre"] for e in eq}
    pairs = [
        (112, 115),  # Argentina vs Brasil
        (111, 113),  # España vs Francia
        (114, 116),  # Inglaterra vs Portugal
        (112, 130),  # Argentina vs México
        (115, 117),  # Brasil vs Colombia
    ]
    for h_id, a_id in pairs:
        if h_id not in state.attack or a_id not in state.attack:
            print(f"  ! ids {h_id}/{a_id} no entrenados (sin partidos suficientes)")
            continue
        probs = state.probs_1x2(h_id, a_id, is_neutral=True)
        lam, mu = state.lambdas(h_id, a_id, is_neutral=True)
        print(f"  {id2nombre[h_id]:<14} vs {id2nombre[a_id]:<14}  "
              f"H={probs['H']:.2%}  D={probs['D']:.2%}  A={probs['A']:.2%}  "
              f"(λ={lam:.2f}, μ={mu:.2f})")


if __name__ == "__main__":
    main()
