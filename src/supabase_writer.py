"""
Escribe pronósticos del modelo en Supabase.

Flujo:
1. Lee predictions.json generado por src.predict.
2. Por cada predicción:
   a. Mapea (home_team_name, away_team_name) → (equipo_local_id, equipo_visitante_id)
      usando TEAM_ALIAS (nombres football-data.org → ids Supabase).
   b. Mapea competition_code → liga_id usando LEAGUE_ALIAS.
   c. Busca el partido en `partidos` con (equipo_local_id, equipo_visitante_id, fecha ±6h).
   d. Si existe, deriva factor_* desde nuestras features y hace UPSERT en `pronosticos`
      por partido_id.
3. Imprime un resumen de cuántas predicciones se aplicaron / saltearon.

IMPORTANTE: requiere SUPABASE_SERVICE_KEY (rol service_role, bypasea RLS).
            Nunca commitear esa key. Solo via env var / GitHub Secrets.

NO crea partidos nuevos: si el partido no existe en Supabase, lo saltea.
Esa fue decisión explícita — los partidos los carga el usuario manualmente.
"""
from __future__ import annotations
import argparse
import json
import math
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
import urllib.parse
import urllib.request

from .config import PATHS


# Supabase equipos.id → slug canónico (mismo identificador que usan DC/Elo).
# Si cambia el alias de un equipo en team_normalize.py, hay que mantenerlo
# consistente con este map.
SUPABASE_TO_SLUG: dict[int, str] = {
    1:  "real_madrid",
    2:  "barcelona",
    3:  "atletico_madrid",
    4:  "bayern_munich",
    5:  "dortmund",
    6:  "arsenal",
    7:  "man_city",
    8:  "liverpool",
    9:  "chelsea",
    10: "inter_milan",
    11: "ac_milan",
    12: "paris_sg",
}


# football-data.org team name → Supabase equipos.id
TEAM_ALIAS: dict[str, int] = {
    "Real Madrid CF":                 1,
    "Real Madrid":                    1,
    "FC Barcelona":                   2,
    "Barcelona":                      2,
    "Club Atlético de Madrid":        3,
    "Atlético Madrid":                3,
    "Atletico Madrid":                3,
    "Atlético de Madrid":             3,
    "FC Bayern München":              4,
    "Bayern München":                 4,
    "Bayern Munich":                  4,
    "Bayern Múnich":                  4,
    "Borussia Dortmund":              5,
    "Dortmund":                       5,
    "Arsenal FC":                     6,
    "Arsenal":                        6,
    "Manchester City FC":             7,
    "Manchester City":                7,
    "Man City":                       7,
    "Man. City":                      7,
    "Liverpool FC":                   8,
    "Liverpool":                      8,
    "Chelsea FC":                     9,
    "Chelsea":                        9,
    "FC Internazionale Milano":      10,
    "Inter":                          10,
    "Inter Milán":                    10,
    "Internazionale":                 10,
    "AC Milan":                       11,
    "Milan":                          11,
    "AC Milán":                       11,
    "Paris Saint-Germain FC":        12,
    "Paris Saint-Germain":           12,
    "PSG":                            12,
}

# Nuestro competition.code → Supabase ligas.id
LEAGUE_ALIAS: dict[str, int] = {
    "UCL": 1,   # Champions League
    "LL":  2,   # La Liga
    "EPL": 3,   # Premier League
    "SA":  4,   # Serie A
    "BL":  5,   # Bundesliga
    "L1":  6,   # Ligue 1
}

MATCH_FUZZ_HOURS = 6  # tolerancia para matchear partidos por fecha


# ───────── Supabase HTTP client (sin dependencias extra) ─────────

def _sb_url() -> str:
    u = os.getenv("SUPABASE_URL")
    if not u:
        raise RuntimeError("Falta SUPABASE_URL")
    return u.strip().rstrip("/")


def _sb_key() -> str:
    k = os.getenv("SUPABASE_SERVICE_KEY")
    if not k:
        raise RuntimeError("Falta SUPABASE_SERVICE_KEY (rol service_role)")
    # Strip de cualquier whitespace / newline accidental al copiar-pegar en GitHub.
    return k.strip()


def _headers(extra: dict | None = None) -> dict:
    k = _sb_key()
    h = {
        "apikey": k,
        "Authorization": f"Bearer {k}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if extra:
        h.update(extra)
    return h


def sb_get(path: str) -> list[dict]:
    req = urllib.request.Request(f"{_sb_url()}/rest/v1/{path}", headers=_headers())
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def sb_post(path: str, body: list[dict] | dict, prefer: str = "return=representation") -> Any:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/{path}",
        data=data,
        headers=_headers({"Prefer": prefer}),
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


# ───────── Lookup de partidos ─────────

def _normalize(name: str | None) -> str:
    return (name or "").strip()


def find_partido_id(equipo_local_id: int, equipo_visitante_id: int,
                    kickoff_iso: str) -> int | None:
    """
    Busca un partido en Supabase con esos equipos y fecha cercana (±MATCH_FUZZ_HOURS).
    Devuelve el id si lo encuentra, None si no.
    """
    kickoff = datetime.fromisoformat(kickoff_iso.replace("Z", "+00:00"))
    lo = (kickoff - timedelta(hours=MATCH_FUZZ_HOURS)).isoformat()
    hi = (kickoff + timedelta(hours=MATCH_FUZZ_HOURS)).isoformat()
    q = urllib.parse.urlencode({
        "select": "id,fecha,estado",
        "equipo_local_id": f"eq.{equipo_local_id}",
        "equipo_visitante_id": f"eq.{equipo_visitante_id}",
        "fecha": f"gte.{lo}",
    })
    rows = sb_get(f"partidos?{q}&fecha=lte.{urllib.parse.quote(hi)}")
    return int(rows[0]["id"]) if rows else None


# ───────── Derivación de factores (0–100) ─────────

def _sigmoid_0_100(x: float, scale: float, center: float = 50.0) -> float:
    return float(round(center + 50.0 * math.tanh(x / scale), 1))


def derive_factors(match: dict) -> dict:
    """
    Convierte la predicción del modelo en los factor_* que espera el HTML.
    Cada factor representa "cuánto favorece al LOCAL" en escala 0-100.
    El HTML interpreta: >=65 = favorece local, <=40 = favorece visitante.

    Mapeo:
    - factor_localidad: 50 si neutral, ~75 si hay localía real.
    - factor_forma:     sigmoid del momentum_diff (xG reciente).
    - factor_tabla:     sigmoid del elo_diff_pre (ranking de fuerza).
    - factor_goles:     sigmoid del diff de λ esperadas (Dixon-Coles).
    - factor_h2h:       NULL (nuestro modelo no genera h2h directo).
    - factor_bajas:     NULL (sin datos de lesiones).
    """
    probs = match["probabilities"]
    ratings = match.get("ratings", {})
    xg = match.get("expected_goals", {})
    elo_diff = float(ratings.get("elo_diff", 0.0) or 0.0)
    lam_diff = float((xg.get("home", 0.0) or 0.0) - (xg.get("away", 0.0) or 0.0))

    is_neutral = bool(match.get("is_neutral", False))
    factor_localidad = 50.0 if is_neutral else 75.0

    factor_tabla = _sigmoid_0_100(elo_diff, scale=150.0)
    factor_goles = _sigmoid_0_100(lam_diff, scale=0.8)

    # Sin momentum directo en el JSON; usamos el spread de probabilidades como proxy
    prob_diff = float(probs["home"]) - float(probs["away"])
    factor_forma = _sigmoid_0_100(prob_diff, scale=0.30)

    return {
        "factor_localidad": factor_localidad,
        "factor_forma": factor_forma,
        "factor_tabla": factor_tabla,
        "factor_goles": factor_goles,
        "factor_h2h": None,
        "factor_bajas": None,
    }


def build_notas(match: dict) -> str:
    """Texto breve para la columna `notas`. El HTML lo muestra en la tarjeta."""
    home = match["home"]["name"]
    away = match["away"]["name"]
    xg_h = match.get("expected_goals", {}).get("home")
    xg_a = match.get("expected_goals", {}).get("away")
    elo_diff = match.get("ratings", {}).get("elo_diff")
    parts = [f"Modelo IA · DC+Elo+XGBoost"]
    if xg_h is not None and xg_a is not None:
        parts.append(f"xG esperado {home} {xg_h:.2f} - {xg_a:.2f} {away}")
    if elo_diff is not None:
        parts.append(f"d-Elo {elo_diff:+.0f}")
    return " - ".join(parts)


# ───────── Upsert principal ─────────

def upsert_pronostico(partido_id: int, match: dict, dry_run: bool = False) -> None:
    probs = match["probabilities"]
    payload = {
        "partido_id": partido_id,
        "prob_local":     round(float(probs["home"]) * 100, 1),
        "prob_empate":    round(float(probs["draw"]) * 100, 1),
        "prob_visitante": round(float(probs["away"]) * 100, 1),
        **derive_factors(match),
        "notas": build_notas(match),
    }
    if dry_run:
        print(f"  [dry-run] partido_id={partido_id} payload={payload}")
        return
    # PostgREST upsert: requiere índice único sobre partido_id en pronosticos.
    # Si no existe, lo creás con:
    #    create unique index if not exists pronosticos_partido_id_uq
    #      on pronosticos (partido_id);
    sb_post("pronosticos?on_conflict=partido_id",
            [payload],
            prefer="resolution=merge-duplicates,return=minimal")


def apply_predictions(predictions_path: Path = PATHS.predictions,
                      dry_run: bool = False) -> dict:
    doc = json.loads(predictions_path.read_text(encoding="utf-8"))
    stats = {"total": 0, "applied": 0, "skipped_team": 0,
             "skipped_no_partido": 0, "errors": 0}

    for match in doc.get("matches", []):
        stats["total"] += 1
        home_name = _normalize(match.get("home", {}).get("name"))
        away_name = _normalize(match.get("away", {}).get("name"))
        eq_h = TEAM_ALIAS.get(home_name)
        eq_a = TEAM_ALIAS.get(away_name)
        if not eq_h or not eq_a:
            stats["skipped_team"] += 1
            print(f"  · sin alias: '{home_name}' vs '{away_name}'")
            continue

        try:
            pid = find_partido_id(eq_h, eq_a, match["kickoff_ts_utc"])
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! lookup error {home_name} vs {away_name}: {e}")
            continue

        if pid is None:
            stats["skipped_no_partido"] += 1
            print(f"  · no hay partido en Supabase para {home_name} vs {away_name} @ {match['kickoff_ts_utc']}")
            continue

        try:
            upsert_pronostico(pid, match, dry_run=dry_run)
            stats["applied"] += 1
            print(f"  ok partido_id={pid}  {home_name} vs {away_name}  "
                  f"H={match['probabilities']['home']:.2f} D={match['probabilities']['draw']:.2f} "
                  f"A={match['probabilities']['away']:.2f}")
        except Exception as e:
            stats["errors"] += 1
            print(f"  ! upsert error partido_id={pid}: {e}")

    return stats


def apply_on_demand(dry_run: bool = False) -> dict:
    """
    Modo "on-demand": para cada partido `programado` en Supabase, calcula
    el pronóstico usando los ratings del modelo (Elo + Dixon-Coles) y hace
    upsert en `pronosticos`.

    No depende de que el matchup exista en predictions.json — usa las fuerzas
    de los equipos directamente. Ideal cuando los partidos de Supabase son
    fixtures elegidos a mano que pueden no coincidir con el calendario real.

    Si existe un calibrador isotonico entrenado (data/models/dc_calibrator.joblib),
    se aplica a las probabilidades crudas de DC para corregir la subestimación
    de empates y la sobre-confianza en favoritos.
    """
    import numpy as np
    from .dixon_coles import DixonColesState
    from .elo import EloState
    from .train_dc import CALIBRATOR_PATH
    from .xgb_model import IsotonicMulticlassCalibrator

    dc = DixonColesState.from_json()
    elo = EloState.from_json()

    calibrator = None
    if CALIBRATOR_PATH.exists():
        try:
            calibrator = IsotonicMulticlassCalibrator.load(CALIBRATOR_PATH)
            print(f"[supabase-writer] calibrador isotonico cargado desde {CALIBRATOR_PATH.name}")
        except Exception as e:
            print(f"[supabase-writer] calibrador no se pudo cargar: {e}. Uso DC crudo.")
    else:
        print(f"[supabase-writer] sin calibrador entrenado. Uso DC crudo. "
              f"(Para activar: python -m src.train_dc)")

    partidos = sb_get("partidos?select=id,equipo_local_id,equipo_visitante_id,fecha,liga_id&estado=eq.programado&order=fecha")
    stats = {"total": len(partidos), "applied": 0, "skipped_no_alias": 0,
             "skipped_no_rating": 0, "errors": 0}

    for p in partidos:
        pid = int(p["id"])
        eq_h_sb = int(p["equipo_local_id"])
        eq_a_sb = int(p["equipo_visitante_id"])

        slug_h = SUPABASE_TO_SLUG.get(eq_h_sb)
        slug_a = SUPABASE_TO_SLUG.get(eq_a_sb)
        if not slug_h or not slug_a:
            print(f"  - partido_id={pid}: sin slug para uno de los equipos ({eq_h_sb},{eq_a_sb})")
            stats["skipped_no_alias"] += 1
            continue

        if slug_h not in dc.attack or slug_a not in dc.attack:
            print(f"  - partido_id={pid}: equipo sin rating en DC (h={slug_h} a={slug_a}). "
                  f"Probable que el equipo no haya jugado en las ligas bajadas.")
            stats["skipped_no_rating"] += 1
            continue

        try:
            probs = dc.probs_1x2(slug_h, slug_a, is_neutral=False)
            # Aplicar calibrador si esta disponible
            if calibrator is not None:
                raw = np.array([[probs["H"], probs["D"], probs["A"]]])
                cal_p = calibrator.transform(raw)[0]
                probs = {"H": float(cal_p[0]), "D": float(cal_p[1]), "A": float(cal_p[2])}
            lam_h, lam_a = dc.lambdas(slug_h, slug_a, is_neutral=False)
            elo_h = elo.get(slug_h)
            elo_a = elo.get(slug_a)
            elo_diff = elo_h - elo_a

            # Construyo un "match" sintético con la forma que esperan
            # derive_factors() y build_notas().
            synthetic_match = {
                "probabilities": {
                    "home": probs["H"], "draw": probs["D"], "away": probs["A"],
                },
                "expected_goals": {"home": lam_h, "away": lam_a},
                "ratings": {"elo_home": elo_h, "elo_away": elo_a, "elo_diff": elo_diff},
                "is_neutral": False,
                "home": {"name": f"team-{eq_h_sb}"},
                "away": {"name": f"team-{eq_a_sb}"},
            }

            payload = {
                "partido_id": pid,
                "prob_local":     round(probs["H"] * 100, 1),
                "prob_empate":    round(probs["D"] * 100, 1),
                "prob_visitante": round(probs["A"] * 100, 1),
                **derive_factors(synthetic_match),
                "notas": (f"Modelo IA (on-demand DC+Elo{'+calib' if calibrator else ''}) - "
                          f"xG {lam_h:.2f}-{lam_a:.2f} - d-Elo {elo_diff:+.0f}"),
            }
            if dry_run:
                print(f"  [dry-run] partido_id={pid} payload={payload}")
            else:
                sb_post("pronosticos?on_conflict=partido_id",
                        [payload],
                        prefer="resolution=merge-duplicates,return=minimal")
                print(f"  ok partido_id={pid}  "
                      f"H={probs['H']:.2f} D={probs['D']:.2f} A={probs['A']:.2f}  "
                      f"(elo {elo_h:.0f} vs {elo_a:.0f})")
            stats["applied"] += 1
        except Exception as e:
            print(f"  ! error partido_id={pid}: {e}")
            stats["errors"] += 1

    return stats


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["from-json", "on-demand"], default="on-demand",
                   help=("from-json: matchea predictions.json contra partidos reales. "
                         "on-demand: calcula prob para los partidos programados en Supabase."))
    p.add_argument("--predictions", default=str(PATHS.predictions),
                   help="Solo para --mode from-json")
    p.add_argument("--dry-run", action="store_true",
                   help="Imprime el payload sin escribir en Supabase")
    args = p.parse_args()

    print(f"[supabase-writer] mode={args.mode} dry_run={args.dry_run}")
    if args.mode == "from-json":
        stats = apply_predictions(Path(args.predictions), dry_run=args.dry_run)
    else:
        stats = apply_on_demand(dry_run=args.dry_run)
    print(f"[supabase-writer] resumen: {stats}")


if __name__ == "__main__":
    main()
