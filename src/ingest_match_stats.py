"""
Trae stats de partido (remates, posesion, pases, etc) desde API-Football
para partidos finalizados en Supabase que aun no tienen entry en stats_partido.

Estrategia (compatible con Free tier de API-Football):
- Free tier permite consultar fechas en rango +/- 1 dia desde "hoy" UTC.
- NO permite filtrar por league (requiere season y season tier-locked).
- SI permite GET /fixtures?date=X sin filtro de season -> trae todos los
  partidos del mundo ese dia (~200-700 segun la fecha).
- /fixtures/statistics?fixture=X funciona sin restricciones.

Algoritmo:
1. Lee de Supabase los partidos estado=finalizado sin stats.
2. Filtra a los que tienen fecha dentro del rango permitido (hoy +/- 1 dia).
3. Agrupa por fecha y por cada fecha hace UN GET /fixtures?date=X.
4. Matchea cada partido (slug del local) contra los fixtures de AF.
5. Por cada match: GET /fixtures/statistics?fixture=X y guarda a Supabase.

Costo aproximado: 1 call por fecha + 1 call por partido finalizado.
Para una jornada europea (~30 partidos en 1 dia): ~31 calls (~30% del budget free).

Uso:
    python -m src.ingest_match_stats
    python -m src.ingest_match_stats --limit 10
    python -m src.ingest_match_stats --dry-run
"""
from __future__ import annotations
import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from .team_normalize import canonical
from .supabase_writer import sb_get, sb_post


AF_BASE = "https://v3.football.api-sports.io"

# Pausa entre calls. Free tier de API-Football permite 10 req/min, asi que
# necesitamos al menos 6 seg entre calls. Margen de seguridad: 6.5 seg.
SLEEP_BETWEEN_CALLS = 6.5
# Si recibimos HTTP 429 (rate limited), esperar este tiempo y reintentar.
RATE_LIMIT_BACKOFF = 65.0
MAX_RETRIES_ON_429 = 2

# Free tier permite +/- 1 dia desde "hoy". Tolerancia conservadora.
FREE_TIER_DAYS_BACK = 2
FREE_TIER_DAYS_FWD = 2

# Mapeo "type" de API-Football statistics -> columna de stats_partido.
STAT_TYPE_TO_COL: dict[str, str] = {
    "Shots on Goal":   "remates_arco",
    "Total Shots":     "remates",
    "Fouls":           "faltas",
    "Corner Kicks":    "corners",
    "Offsides":        "offsides",
    "Ball Possession": "posesion",
    "Yellow Cards":    "amarillas",
    "Red Cards":       "rojas",
    "Total passes":    "pases",
    "Passes %":        "pases_pct",
}
PCT_COLS = {"posesion", "pases_pct"}

# Ligas que cubre el proyecto (para filtrar localmente sin pedir season al API).
# Los nombres aca deben coincidir con `league.name` de API-Football.
TARGET_LEAGUES = {
    "Premier League",         # PL
    "La Liga",                # PD
    "Primera Division",       # alias de La Liga en algunas respuestas
    "Serie A",                # SA
    "Bundesliga",             # BL1
    "Ligue 1",                # FL1
    "UEFA Champions League",  # CL
}


def _af_get(path: str, params: dict | None = None) -> dict:
    key = os.environ.get("API_FOOTBALL_KEY")
    if not key:
        raise RuntimeError("Falta API_FOOTBALL_KEY en el entorno")
    url = f"{AF_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req_headers = {"x-apisports-key": key, "Accept": "application/json"}
    last_err = None
    for attempt in range(MAX_RETRIES_ON_429 + 1):
        req = urllib.request.Request(url, headers=req_headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            # Algunos endpoints devuelven 200 con error de rate en el body; otros 429.
            if e.code == 429 and attempt < MAX_RETRIES_ON_429:
                print(f"  [rate-limit] HTTP 429, esperando {RATE_LIMIT_BACKOFF}s antes de reintentar (attempt {attempt+1})")
                time.sleep(RATE_LIMIT_BACKOFF)
                continue
            raise RuntimeError(f"HTTP {e.code} {path}: {body}") from e
        # Check error en body (rateLimit message dentro de errors)
        errs = data.get("errors")
        if isinstance(errs, dict) and errs:
            if "rateLimit" in errs and attempt < MAX_RETRIES_ON_429:
                print(f"  [rate-limit] body 'rateLimit', esperando {RATE_LIMIT_BACKOFF}s (attempt {attempt+1})")
                time.sleep(RATE_LIMIT_BACKOFF)
                continue
            raise RuntimeError(f"API errors: {errs}")
        return data
    raise RuntimeError(f"max retries excedidas para {path}")


def fetch_fixtures_by_date(date_str: str) -> list[dict]:
    """GET /fixtures?date=X. Filtramos localmente las ligas que nos interesan."""
    data = _af_get("/fixtures", {"date": date_str})
    fixtures = data.get("response", []) or []
    # Filtrar a top 6 ligas que cubre el proyecto.
    filtered = [
        f for f in fixtures
        if (f.get("league", {}).get("name") or "") in TARGET_LEAGUES
    ]
    return filtered


def fetch_statistics(fixture_id: int) -> list[dict]:
    data = _af_get("/fixtures/statistics", {"fixture": fixture_id})
    return data.get("response", []) or []


def parse_statistics(stats_response: list[dict], home_af_id: int) -> dict:
    out: dict = {}
    for team_stats in stats_response:
        team_id = team_stats.get("team", {}).get("id")
        prefix = "home_" if team_id == home_af_id else "away_"
        for s in team_stats.get("statistics", []):
            stat_type = s.get("type")
            value = s.get("value")
            col = STAT_TYPE_TO_COL.get(stat_type)
            if not col or value is None:
                continue
            if col in PCT_COLS:
                if isinstance(value, str):
                    try:
                        value = float(value.rstrip("%").strip())
                    except ValueError:
                        continue
            else:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            out[prefix + col] = value
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    today = datetime.now(timezone.utc).date()
    earliest = today - timedelta(days=FREE_TIER_DAYS_BACK)
    latest = today + timedelta(days=FREE_TIER_DAYS_FWD)
    print(f"[stats] hoy={today} | rango permitido AF: {earliest} -> {latest}")

    # 1. Partidos finalizados sin stats
    finalizados = sb_get(
        "partidos?select=id,fecha,liga_id,temporada,"
        "equipo_local:equipo_local_id(nombre),"
        "equipo_visitante:equipo_visitante_id(nombre),"
        "stats_partido(id)"
        "&estado=eq.finalizado&order=fecha.desc"
    )
    pendientes_all = [m for m in finalizados if not m.get("stats_partido")]
    print(f"[stats] finalizados en Supabase: {len(finalizados)} | sin stats: {len(pendientes_all)}")

    # 2. Filtrar a los que caen en el rango del free tier
    pendientes: list[dict] = []
    out_of_range = 0
    for m in pendientes_all:
        try:
            kd = datetime.fromisoformat((m["fecha"] or "").replace("Z", "+00:00")).date()
        except (ValueError, TypeError):
            continue
        if earliest <= kd <= latest:
            pendientes.append(m)
        else:
            out_of_range += 1
    print(f"[stats] dentro del rango AF: {len(pendientes)} | fuera de rango: {out_of_range}")

    if args.limit:
        pendientes = pendientes[: args.limit]
        print(f"[stats] aplicando --limit={args.limit} -> procesare {len(pendientes)}")

    if not pendientes:
        print("[stats] nada para procesar.")
        return

    # 3. Agrupar por fecha
    grupos: dict[str, list[dict]] = defaultdict(list)
    for m in pendientes:
        grupos[m["fecha"][:10]].append(m)
    print(f"[stats] fechas distintas: {len(grupos)}")

    api_calls = 0
    saved = 0
    not_found = 0
    errors = 0

    for fecha, partidos in sorted(grupos.items()):
        print(f"\n[fecha] {fecha}: {len(partidos)} partidos a procesar")
        try:
            af_fixtures = fetch_fixtures_by_date(fecha)
            api_calls += 1
        except Exception as e:
            print(f"  ! error fetch fixtures: {e}")
            errors += len(partidos)
            continue
        time.sleep(SLEEP_BETWEEN_CALLS)
        print(f"  AF: {len(af_fixtures)} fixtures (top 6 ligas) ese dia")

        # Indexar por slug del local
        by_slug: dict[str, dict] = {}
        for f in af_fixtures:
            home_name = f.get("teams", {}).get("home", {}).get("name") or ""
            by_slug[canonical(home_name)] = f

        for m in partidos:
            local_name = m["equipo_local"]["nombre"]
            visit_name = m["equipo_visitante"]["nombre"]
            slug_local = canonical(local_name)
            af_fix = by_slug.get(slug_local)
            if not af_fix:
                # Fallback: substring del home name
                hits = [f for f in af_fixtures
                        if local_name.lower() in (f.get("teams", {}).get("home", {}).get("name") or "").lower()]
                af_fix = hits[0] if hits else None
            if not af_fix:
                print(f"  ! no match: {local_name} vs {visit_name} (slug={slug_local})")
                not_found += 1
                continue

            fixture_id = af_fix["fixture"]["id"]
            home_af_id = af_fix["teams"]["home"]["id"]
            try:
                stats_resp = fetch_statistics(fixture_id)
                api_calls += 1
            except Exception as e:
                print(f"  ! error stats fixture={fixture_id}: {e}")
                errors += 1
                continue
            time.sleep(SLEEP_BETWEEN_CALLS)

            if not stats_resp:
                print(f"  ! stats vacio: {local_name} vs {visit_name} (fix {fixture_id})")
                not_found += 1
                continue

            parsed = parse_statistics(stats_resp, home_af_id)
            if not parsed:
                print(f"  ! parse vacio: {local_name} vs {visit_name}")
                not_found += 1
                continue
            parsed["partido_id"] = m["id"]
            parsed["api_football_fixture"] = fixture_id

            if args.dry_run:
                summary = ", ".join(f"{k}={v}" for k, v in sorted(parsed.items())
                                     if k not in ("partido_id", "api_football_fixture"))
                print(f"  [dry-run] {local_name} vs {visit_name}: {summary}")
                saved += 1
                continue

            try:
                sb_post(
                    "stats_partido",
                    [parsed],
                    prefer="resolution=merge-duplicates,return=minimal",
                )
                saved += 1
                print(f"  + OK: {local_name} vs {visit_name}  (fix={fixture_id})")
            except Exception as e:
                print(f"  ! error guardar {local_name} vs {visit_name}: {e}")
                errors += 1

    print()
    print(f"[stats] resumen: saved={saved} not_found={not_found} errors={errors} api_calls={api_calls}")


if __name__ == "__main__":
    main()
