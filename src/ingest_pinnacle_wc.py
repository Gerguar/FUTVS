"""
Trae cuotas H/D/A de Pinnacle para los partidos del Mundial 2026 y las matchea
con `partidos.id` de Supabase. Guarda probabilidades devigged en
data/wc2026_market_odds.json para consumo de predict_mundial.py.

Pinnacle Arcadia API (sin auth con guest key pública estable):
  /0.1/leagues/2686/matchups                     -> lista de matchups WC
  /0.1/matchups/{parent_id}/markets/related/straight -> markets del partido

El moneyline 1X2 principal tiene `key='s;0;m', type='moneyline', period=0` y
`prices` con `designation in {home,away,draw}` en formato americano.

Cuotas via devig proporcional (reusa src.data_ingest.devig_odds).

Uso:
    python -m src.ingest_pinnacle_wc                 # imprime tabla, no guarda
    python -m src.ingest_pinnacle_wc --save          # guarda JSON
"""
from __future__ import annotations
import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

from .data_ingest import devig_odds
from .supabase_writer import sb_get
from .enrich_jugadores_mundial_msmc import DB_TO_API_NATION


PINNACLE_GUEST_KEY = "CmX2KcMrXuFmNg6YFbmTxE0y9CIrOi0R"
WC_LEAGUE_ID = 2686
OUT_PATH = Path("data/wc2026_market_odds.json")

# Inverso: nombre EN de Pinnacle -> nombre DB castellano. Algunos nombres difieren
# entre la API de msmc y Pinnacle (e.g. Turkiye vs Turkey).
API_TO_DB_NATION = {api: db for db, api in DB_TO_API_NATION.items()}
PINNACLE_OVERRIDES = {
    "Turkiye": "Turquía",
    "Korea Republic": "Corea del Sur",
    "South Korea": "Corea del Sur",
    "Brazil": "Brasil",
    "Czechia": "República Checa",
    "Czech Republic": "República Checa",
    "USA": "Estados Unidos",
    "United States": "Estados Unidos",
    "Côte d'Ivoire": "Costa de Marfil",
    "Ivory Coast": "Costa de Marfil",
    "DR Congo": "RD del Congo",
    "South Africa": "Sudáfrica",
    "Cape Verde": "Cabo Verde",
    "Curaçao": "Curazao",
    "Bosnia and Herzegovina": "Bosnia y Herzegovina",
    "Saudi Arabia": "Arabia Saudita",
    "New Zealand": "Nueva Zelanda",
}


def pinnacle_to_db(pinnacle_name: str) -> str | None:
    """Convierte nombre Pinnacle -> nombre selección en DB castellano."""
    if pinnacle_name in PINNACLE_OVERRIDES:
        return PINNACLE_OVERRIDES[pinnacle_name]
    return API_TO_DB_NATION.get(pinnacle_name) or pinnacle_name


def american_to_decimal(price: int) -> float:
    return (price / 100.0 + 1.0) if price > 0 else (100.0 / abs(price) + 1.0)


def _get(url: str, timeout: int = 15) -> dict | list:
    req = urllib.request.Request(url, headers={
        "X-API-Key": PINNACLE_GUEST_KEY,
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def fetch_wc_h2h_parents() -> list[dict]:
    """Devuelve la lista de partidos H2H únicos del Mundial.
    Cada entry: {parent_id, home, away, start_iso}."""
    all_m = _get(f"https://guest.api.arcadia.pinnacle.com/0.1/leagues/{WC_LEAGUE_ID}/matchups")
    seen = set()
    out = []
    for m in all_m:
        parent = m.get("parent")
        if not parent:
            continue
        parts = parent.get("participants", [])
        if len(parts) != 2:
            continue
        align = sorted(p.get("alignment", "") for p in parts)
        if align != ["away", "home"]:
            continue
        pid = parent["id"]
        if pid in seen:
            continue
        seen.add(pid)
        home = next(p["name"] for p in parts if p["alignment"] == "home")
        away = next(p["name"] for p in parts if p["alignment"] == "away")
        out.append({
            "parent_id": pid,
            "home_pinnacle": home,
            "away_pinnacle": away,
            "start_iso": parent.get("startTime"),
        })
    return out


def fetch_h2h_odds(parent_id: int) -> dict | None:
    """Devuelve {p_h, p_d, p_a, decimal_h, decimal_d, decimal_a, overround} o None."""
    try:
        markets = _get(f"https://guest.api.arcadia.pinnacle.com/0.1/matchups/{parent_id}/markets/related/straight")
    except urllib.error.HTTPError as e:
        print(f"  ! markets {parent_id}: HTTP {e.code}")
        return None
    for m in markets:
        if (m.get("type") == "moneyline" and m.get("period") == 0
                and m.get("key") == "s;0;m" and len(m.get("prices", [])) == 3):
            d = {p["designation"]: american_to_decimal(int(p["price"]))
                 for p in m["prices"] if "designation" in p}
            if not {"home", "draw", "away"}.issubset(d):
                continue
            p_h, p_d, p_a = devig_odds(d["home"], d["draw"], d["away"])
            overround = (1/d["home"] + 1/d["draw"] + 1/d["away"]) - 1
            return {
                "decimal_h": round(d["home"], 3),
                "decimal_d": round(d["draw"], 3),
                "decimal_a": round(d["away"], 3),
                "p_market_home": round(p_h, 4),
                "p_market_draw": round(p_d, 4),
                "p_market_away": round(p_a, 4),
                "overround": round(overround, 4),
            }
    return None


def match_to_db(parent: dict, partidos_db: list[dict]) -> int | None:
    """Devuelve partido_id de la DB que matchea o None.
    Match: nombres de equipos coinciden + fecha dentro de ±6h."""
    home_db = pinnacle_to_db(parent["home_pinnacle"])
    away_db = pinnacle_to_db(parent["away_pinnacle"])
    if not home_db or not away_db:
        return None
    pin_dt = datetime.fromisoformat(parent["start_iso"].replace("Z", "+00:00"))
    if pin_dt.tzinfo is None:
        pin_dt = pin_dt.replace(tzinfo=timezone.utc)
    for p in partidos_db:
        h, a = p["home_nombre"], p["away_nombre"]
        names_match = (h == home_db and a == away_db) or (h == away_db and a == home_db)
        if not names_match:
            continue
        # `partidos.fecha` viene sin tz desde Supabase (timestamp without tz, ya en UTC)
        s = p["fecha"]
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        db_dt = datetime.fromisoformat(s)
        if db_dt.tzinfo is None:
            db_dt = db_dt.replace(tzinfo=timezone.utc)
        if abs((db_dt - pin_dt).total_seconds()) <= 6 * 3600:
            return p["id"], (h == home_db and a == away_db)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--save", action="store_true", help="Guardar JSON")
    ap.add_argument("--sleep", type=float, default=0.4, help="Delay entre requests")
    args = ap.parse_args()

    print(f"[pinnacle-wc] bajando matchups del WC (league={WC_LEAGUE_ID})...")
    parents = fetch_wc_h2h_parents()
    print(f"[pinnacle-wc] H2H únicos disponibles: {len(parents)}")

    # Partidos en DB del Mundial (selecciones, programados)
    rows = sb_get(
        "partidos?select=id,fecha,"
        "equipo_local:equipo_local_id(nombre),"
        "equipo_visitante:equipo_visitante_id(nombre)"
        "&estado=eq.programado&liga_id=eq.7&order=fecha"
    )
    partidos_db = [{
        "id": r["id"],
        "fecha": r["fecha"],
        "home_nombre": r["equipo_local"]["nombre"],
        "away_nombre": r["equipo_visitante"]["nombre"],
    } for r in rows]
    print(f"[pinnacle-wc] partidos en DB: {len(partidos_db)}")

    out = {}
    not_matched = []
    no_odds = []
    inverted = 0
    for parent in parents:
        match = match_to_db(parent, partidos_db)
        if match is None:
            not_matched.append((parent["home_pinnacle"], parent["away_pinnacle"], parent["start_iso"]))
            continue
        partido_id, same_order = match
        odds = fetch_h2h_odds(parent["parent_id"])
        time.sleep(args.sleep)
        if not odds:
            no_odds.append(parent["parent_id"])
            continue
        if not same_order:
            odds["p_market_home"], odds["p_market_away"] = odds["p_market_away"], odds["p_market_home"]
            odds["decimal_h"], odds["decimal_a"] = odds["decimal_a"], odds["decimal_h"]
            inverted += 1
        odds["pinnacle_parent_id"] = parent["parent_id"]
        odds["fetched_at_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        out[str(partido_id)] = odds

    print(f"\n[pinnacle-wc] resumen:")
    print(f"  con cuotas matcheadas: {len(out)}")
    print(f"  sin match nombre/fecha: {len(not_matched)}")
    print(f"  sin odds para parent : {len(no_odds)}")
    print(f"  invertidos (home/away): {inverted}")

    # Imprimir tabla
    if out:
        print(f"\n[pinnacle-wc] muestra de cuotas:")
        id_to_pair = {p["id"]: (p["home_nombre"], p["away_nombre"]) for p in partidos_db}
        for pid_str, o in list(out.items())[:10]:
            pid = int(pid_str)
            h, a = id_to_pair[pid]
            print(f"  {h:<22} vs {a:<22}  "
                  f"H={o['p_market_home']:.1%}  D={o['p_market_draw']:.1%}  A={o['p_market_away']:.1%}  "
                  f"(decimal {o['decimal_h']:.2f}/{o['decimal_d']:.2f}/{o['decimal_a']:.2f}, overround {o['overround']:.1%})")

    if not_matched:
        print(f"\n[pinnacle-wc] sin match (mostrar 5): {not_matched[:5]}")

    if args.save:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n[pinnacle-wc] guardado: {OUT_PATH}")


if __name__ == "__main__":
    main()
