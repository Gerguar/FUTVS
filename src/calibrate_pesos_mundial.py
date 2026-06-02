"""
Calibra los pesos del modelo de predicción del Mundial sobre un dataset
histórico de partidos de selecciones (martj42).

Para cada partido pasado calcula:
  - p_dc: probabilidades del DC entrenado para selecciones
  - p_elo: probabilidades estilo Elo basadas en el rating histórico
  - p_plantilla: probabilidades de plantilla actual

(NO incluye mercado porque martj42 no tiene cuotas históricas.)

Grid search sobre el simplex (w_dc + w_elo + w_plant = 1, step=0.05) y
encuentra los pesos que minimizan log-loss.

Output: data/wc2026_pesos_calibrados.json

Uso:
    python -m src.calibrate_pesos_mundial --since 2018
    python -m src.calibrate_pesos_mundial --since 2018 --save
"""
from __future__ import annotations
import argparse
import io
import json
import math
import urllib.request
from collections import defaultdict
from pathlib import Path

import pandas as pd
import numpy as np

from .predict_mundial import load_dc_selecciones, elo_probs, plantilla_probs
from .replay_elo_selecciones import NAME_TO_SLUG, HIST_URL
from .supabase_writer import sb_get
from .team_normalize import canonical


OUT_PATH = Path("data/wc2026_pesos_calibrados.json")


def label_from_score(h_g: int, a_g: int) -> int:
    """0=Home, 1=Draw, 2=Away."""
    if h_g > a_g: return 0
    if h_g < a_g: return 1 if False else 2
    return 1


def log_loss(probs: np.ndarray, labels: np.ndarray, eps: float = 1e-12) -> float:
    """Multiclass log loss. probs shape (N,3), labels shape (N,) en {0,1,2}."""
    probs = np.clip(probs, eps, 1 - eps)
    return float(-np.log(probs[np.arange(len(labels)), labels]).mean())


def build_dataset(since_year: int, include_friendlies: bool = True) -> tuple[np.ndarray, np.ndarray, dict]:
    """Devuelve (X, y, info) donde X tiene 9 cols: [p_h_dc, p_d_dc, p_a_dc, p_h_elo,...,p_a_plant]."""
    print(f"[calibrate] bajando martj42...")
    with urllib.request.urlopen(HIST_URL, timeout=60) as r:
        data = r.read().decode("utf-8")
    df = pd.read_csv(io.StringIO(data))
    df = df[df["home_score"].notna() & df["away_score"].notna()]
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"].dt.year >= since_year].copy()
    if not include_friendlies:
        df = df[~df["tournament"].str.contains("Friendly", case=False, na=False)]
    print(f"[calibrate] martj42 desde {since_year}: {len(df):,} partidos")

    # Mapeo EN -> equipo_id en DB (selecciones liga 7)
    elo_rows = sb_get("selecciones_elo?select=slug,nombre,elo")
    slug2nombre = {r["slug"]: r["nombre"] for r in elo_rows}
    nombre2elo = {r["nombre"]: r["elo"] for r in elo_rows}
    eq = sb_get("equipos?select=id,nombre&liga_id=eq.7")
    nombre2id = {e["nombre"]: e["id"] for e in eq}
    en2nombre = {}
    en2id = {}
    for en, slug in NAME_TO_SLUG.items():
        nombre = slug2nombre.get(slug)
        if not nombre: continue
        eid = nombre2id.get(nombre)
        if eid is None: continue
        en2nombre[en] = nombre
        en2id[en] = eid

    # Carga modelos
    dc = load_dc_selecciones()
    team_ratings = json.loads(Path("data/team_ratings.json").read_text(encoding="utf-8"))

    rows_x = []
    labels = []
    skipped = 0
    for _, row in df.iterrows():
        h_id = en2id.get(row["home_team"])
        a_id = en2id.get(row["away_team"])
        if h_id is None or a_id is None: skipped += 1; continue
        if h_id not in dc.attack or a_id not in dc.attack: skipped += 1; continue
        is_neutral = bool(row["neutral"])

        # DC
        dc_probs = dc.probs_1x2(h_id, a_id, is_neutral=is_neutral)
        p_h_dc, p_d_dc, p_a_dc = dc_probs["H"], dc_probs["D"], dc_probs["A"]

        # Elo (usamos el rating CURRENT — limitación pero aceptable porque queremos pesos no Elo)
        h_nombre = en2nombre[row["home_team"]]
        a_nombre = en2nombre[row["away_team"]]
        elo_h = nombre2elo.get(h_nombre)
        elo_a = nombre2elo.get(a_nombre)
        if elo_h is None or elo_a is None: skipped += 1; continue
        p_h_e, p_d_e, p_a_e = elo_probs(elo_h, elo_a)

        # Plantilla (rating actual del Mundial 26 — sirve como proxy de calidad)
        h_slug = canonical(h_nombre)
        a_slug = canonical(a_nombre)
        xi_h = (team_ratings.get(h_slug) or {}).get("top_xi_avg")
        xi_a = (team_ratings.get(a_slug) or {}).get("top_xi_avg")
        p_h_pl, p_d_pl, p_a_pl = plantilla_probs(xi_h, xi_a)

        rows_x.append([p_h_dc, p_d_dc, p_a_dc, p_h_e, p_d_e, p_a_e, p_h_pl, p_d_pl, p_a_pl])
        labels.append(label_from_score(int(row["home_score"]), int(row["away_score"])))

    print(f"[calibrate] usables: {len(rows_x):,} | skipped: {skipped:,}")
    info = {"n_train": len(rows_x), "since": since_year, "include_friendlies": include_friendlies}
    return np.array(rows_x), np.array(labels), info


def predict_with_weights(X: np.ndarray, w_dc: float, w_elo: float, w_plant: float) -> np.ndarray:
    """Combina linealmente; X shape (N,9)."""
    p = (w_dc * X[:, 0:3] + w_elo * X[:, 3:6] + w_plant * X[:, 6:9])
    # Renormalizar para sumar 1 (los componentes ya suman 1 cada uno, pero por seguridad)
    p = p / p.sum(axis=1, keepdims=True)
    return p


def grid_search(X: np.ndarray, y: np.ndarray, step: float = 0.05) -> dict:
    """Busca w_dc + w_elo + w_plant = 1 que minimice log-loss."""
    best = {"loss": float("inf"), "w_dc": None, "w_elo": None, "w_plant": None}
    # Baseline: pesos originales
    baseline_probs = predict_with_weights(X, 0.55, 0.30, 0.15)
    baseline_loss = log_loss(baseline_probs, y)
    print(f"[calibrate] baseline (0.55/0.30/0.15): log-loss = {baseline_loss:.4f}")
    print(f"[calibrate] grid search (step={step})...")
    n = int(round(1.0 / step))
    n_eval = 0
    for i in range(n + 1):
        for j in range(n - i + 1):
            w_dc = i * step
            w_elo = j * step
            w_plant = 1.0 - w_dc - w_elo
            if w_plant < -1e-9: continue
            w_plant = max(0.0, w_plant)
            probs = predict_with_weights(X, w_dc, w_elo, w_plant)
            l = log_loss(probs, y)
            n_eval += 1
            if l < best["loss"]:
                best = {"loss": l, "w_dc": w_dc, "w_elo": w_elo, "w_plant": w_plant}
    print(f"[calibrate] {n_eval} combinaciones evaluadas")
    best["baseline_loss"] = baseline_loss
    best["improvement_pct"] = (baseline_loss - best["loss"]) / baseline_loss * 100
    return best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", type=int, default=2018)
    ap.add_argument("--step", type=float, default=0.05)
    ap.add_argument("--no-friendlies", action="store_true",
                    help="Excluir amistosos (más representativo de competición)")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    X, y, info = build_dataset(args.since, include_friendlies=not args.no_friendlies)
    if len(X) < 100:
        print("[calibrate] muy pocos datos, abortando")
        return

    best = grid_search(X, y, step=args.step)
    print()
    print(f"[calibrate] pesos óptimos:")
    print(f"  w_dc       = {best['w_dc']:.2f}")
    print(f"  w_elo      = {best['w_elo']:.2f}")
    print(f"  w_plantilla= {best['w_plant']:.2f}")
    print(f"  log-loss   = {best['loss']:.4f}")
    print(f"  baseline   = {best['baseline_loss']:.4f}")
    print(f"  mejora     = {best['improvement_pct']:.2f}%")

    if args.save:
        out = {
            "w_dc":        round(best["w_dc"], 4),
            "w_elo":       round(best["w_elo"], 4),
            "w_plantilla": round(best["w_plant"], 4),
            "log_loss":    round(best["loss"], 5),
            "baseline_loss": round(best["baseline_loss"], 5),
            "improvement_pct": round(best["improvement_pct"], 3),
            "info": info,
        }
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\n[calibrate] guardado: {OUT_PATH}")


if __name__ == "__main__":
    main()
