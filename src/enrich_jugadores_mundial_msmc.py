"""
Enriquece los jugadores del Mundial 2026 que quedaron en rating=70 con la API
api.msmc.cc/api/fc26 (proxy de EA FC 26).

Estrategia: para cada jugador con rating=70 default, probar variaciones del
nombre hasta encontrar match real. Validar por nacionalidad (Nation en API
== nombre de la selección en DB).

Sin estimaciones ni overrides. Los que no encontremos quedan en 70 default
explícitamente.

Uso:
    python -m src.enrich_jugadores_mundial_msmc --dry-run
    python -m src.enrich_jugadores_mundial_msmc
"""
from __future__ import annotations
import argparse
import json
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

from .supabase_writer import sb_get, _sb_url, _headers


MUNDIAL_TEAM_IDS = (
    111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    126, 127, 129, 130, 132, 133, 134, 135, 136, 141, 142, 145, 146, 148, 150,
    151, 153, 160, 161, 162, 168, 173, 178, 181, 187, 189, 192, 194, 196, 198,
    206, 211, 264,
)

API_URL = "https://api.msmc.cc/api/fc26/player/name/{name}"

# Mapeo nombre seleccion (DB) -> Nation que devuelve la API (en ingles)
DB_TO_API_NATION = {
    "Argentina": "Argentina", "Brasil": "Brazil", "España": "Spain",
    "Francia": "France", "Inglaterra": "England", "Portugal": "Portugal",
    "Alemania": "Germany", "Países Bajos": "Netherlands", "Bélgica": "Belgium",
    "Italia": "Italy", "Croacia": "Croatia", "Uruguay": "Uruguay",
    "Colombia": "Colombia", "Ecuador": "Ecuador", "Senegal": "Senegal",
    "Marruecos": "Morocco", "Japón": "Japan", "Corea del Sur": "Korea Republic",
    "Estados Unidos": "United States", "México": "Mexico", "Sudáfrica": "South Africa",
    "República Checa": "Czech Republic", "Canadá": "Canada", "Noruega": "Norway",
    "Turquía": "Turkey", "Suiza": "Switzerland", "Austria": "Austria",
    "Panamá": "Panama", "Paraguay": "Paraguay", "Australia": "Australia",
    "Irán": "Iran", "Argelia": "Algeria", "Uzbekistán": "Uzbekistan",
    "Suecia": "Sweden", "Jordania": "Jordan", "Egipto": "Egypt",
    "Costa de Marfil": "Côte d'Ivoire", "Túnez": "Tunisia", "Irak": "Iraq",
    "Nueva Zelanda": "New Zealand", "Arabia Saudita": "Saudi Arabia",
    "Haití": "Haiti", "RD del Congo": "DR Congo", "Bosnia y Herzegovina": "Bosnia and Herzegovina",
    "Cabo Verde": "Cape Verde", "Ghana": "Ghana", "Curazao": "Curaçao",
    "Qatar": "Qatar", "Escocia": "Scotland",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def name_variations(name: str) -> list[str]:
    """Solo 2-3 variantes principales para minimizar requests y rate limit.
    La API msmc requiere matching exacto, no fuzzy."""
    name = name.strip()
    no_acc = strip_accents(name)
    out = [name]
    if no_acc != name:
        out.append(no_acc)
    if "-" in name:
        out.append(no_acc.replace("-", " "))
    # Para nombres asiáticos: reverso (sin acentos)
    parts = no_acc.split()
    if len(parts) >= 2 and len(parts) <= 3:
        out.append(" ".join(reversed(parts)))
    # Dedup
    seen = set()
    return [v for v in out if v and not (v in seen or seen.add(v))]


def name_overlap(api_name: str, db_name: str) -> float:
    """Score [0..1] de cuántos tokens del db_name aparecen en el api_name."""
    a = set(strip_accents(api_name).lower().replace("-", " ").split())
    b = set(strip_accents(db_name).lower().replace("-", " ").split())
    if not b:
        return 0.0
    return len(a & b) / len(b)


_RATE_LIMIT_BACKOFF = [10, 30, 60]


def fetch_player(name: str, timeout: int = 10) -> tuple[dict | None, str]:
    """Devuelve (data, status):
      status in: 'ok', 'not_found', 'rate_limit', 'error'.
    Maneja 429 con backoff exponencial (espera + reintento hasta 3 veces).
    """
    url = API_URL.format(name=urllib.parse.quote(name))
    for attempt, wait in enumerate([0] + _RATE_LIMIT_BACKOFF):
        if wait > 0:
            print(f"    rate_limit, esperando {wait}s y reintentando {name!r}...")
            time.sleep(wait)
        req = urllib.request.Request(url, headers={"User-Agent": "FutVS-mundial/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            if isinstance(data, dict) and data.get("OVR"):
                return data, "ok"
            return None, "not_found"
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None, "not_found"
            if e.code == 429 and attempt < len(_RATE_LIMIT_BACKOFF):
                continue  # backoff
            print(f"  ! API {e.code} para {name!r}")
            return None, "error"
        except Exception as e:
            print(f"  ! err para {name!r}: {type(e).__name__}")
            return None, "error"
    return None, "rate_limit"


def nation_matches(api_nation: str, db_nation: str) -> bool:
    """Tolerante a tildes/case."""
    a = strip_accents((api_nation or "").lower().strip())
    b = strip_accents((db_nation or "").lower().strip())
    return a == b or a in b or b in a


def to_int(v) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except (ValueError, TypeError):
        return None


def build_payload(api_data: dict, posicion: str) -> dict:
    """Mapea respuesta API a payload jugadores. Los stats vienen como strings."""
    ovr = to_int(api_data.get("OVR"))
    if ovr is None:
        return {}
    payload: dict = {"rating": ovr}
    is_gk = posicion == "POR" or (api_data.get("Position") == "GK")
    if is_gk:
        # API usa GK-specific keys
        gk_map = {
            "DIV": "gk_diving",  "HAN": "gk_handling",
            "KIC": "gk_kicking", "POS": "gk_positioning",
            "REF": "gk_reflexes", "SPD": "gk_speed",
        }
        for k, dst in gk_map.items():
            v = to_int(api_data.get(k))
            if v is not None:
                payload[dst] = v
    else:
        field_map = {
            "PAC": "pace", "SHO": "shooting", "PAS": "passing",
            "DRI": "dribbling", "DEF": "defending", "PHY": "physic",
        }
        for k, dst in field_map.items():
            v = to_int(api_data.get(k))
            if v is not None:
                payload[dst] = v
    return payload


def patch_jugador(jid: int, payload: dict) -> None:
    req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/jugadores?id=eq.{jid}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers({"Content-Type": "application/json", "Prefer": "return=minimal"}),
        method="PATCH",
    )
    urllib.request.urlopen(req, timeout=15).read()


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="Procesar solo los primeros N (debug).")
    p.add_argument("--sleep", type=float, default=0.5, help="Delay entre requests (s).")
    args = p.parse_args()

    # Traer jugadores con rating=70 de las 48 selecciones
    eq = sb_get(f"equipos?select=id,nombre&id=in.({','.join(map(str, MUNDIAL_TEAM_IDS))})")
    id_to_nombre = {e["id"]: e["nombre"] for e in eq}

    players: list[dict] = []
    offset = 0
    while True:
        chunk = sb_get(f"jugadores?select=id,nombre,equipo_id,posicion,rating"
                       f"&equipo_id=in.({','.join(map(str, MUNDIAL_TEAM_IDS))})"
                       f"&rating=eq.70&order=equipo_id&limit=1000&offset={offset}")
        players.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000
    if args.limit:
        players = players[:args.limit]
    print(f"[msmc] {len(players)} jugadores con rating=70 a procesar (delay={args.sleep}s)")
    print(f"[msmc] estimado: ~{len(players) * args.sleep * 2.5 / 60:.1f} min con variaciones")

    matched = 0
    nation_mismatch = 0
    not_found = 0
    updates: list[tuple[int, dict, dict, str]] = []  # (jid, payload, api_data, db_name)

    for i, pl in enumerate(players):
        db_nation = id_to_nombre.get(pl["equipo_id"], "")
        api_nation = DB_TO_API_NATION.get(db_nation, db_nation)
        nombre = pl["nombre"]

        api_data = None
        any_rate_limit = False
        for variant in name_variations(nombre):
            cand, status = fetch_player(variant)
            time.sleep(args.sleep)
            if status == "rate_limit":
                any_rate_limit = True
                break  # ya esperamos, no insistir con más variantes
            if not cand:
                continue
            # Validar nacionalidad Y nombre (>=50% de tokens del db_name en api.Name)
            if not nation_matches(cand.get("Nation", ""), api_nation):
                continue
            overlap = name_overlap(cand.get("Name", ""), nombre)
            if overlap < 0.5:
                continue
            api_data = cand
            break
        if not api_data:
            not_found += 1
            if any_rate_limit:
                # Esperar un poco más antes del próximo jugador si tuvimos rate limit
                time.sleep(5)
            continue

        payload = build_payload(api_data, pl["posicion"])
        if not payload:
            continue
        matched += 1
        updates.append((pl["id"], payload, api_data, nombre))

        if (i + 1) % 25 == 0:
            print(f"  [{i+1}/{len(players)}] matches: {matched}, not_found: {not_found}")

    print(f"\n[msmc] resumen:")
    print(f"  matched      : {matched}")
    print(f"  not_found    : {not_found}")
    print(f"  total proc.  : {len(players)}")

    if updates:
        print(f"\n[msmc] muestra de matches (primeros 10):")
        for jid, pl, api, nm in updates[:10]:
            print(f"  {nm:<28} -> API: {api.get('Name','?'):<28} OVR={pl['rating']} Team={api.get('Team','?')}")

    if args.dry_run:
        print("\n(dry-run)")
        return

    if not updates:
        print("\n[msmc] nada que actualizar")
        return

    print(f"\n[msmc] aplicando {len(updates)} PATCH...")
    ok = 0
    for jid, payload, _, _ in updates:
        try:
            patch_jugador(jid, payload)
            ok += 1
        except Exception as e:
            print(f"  ! {jid}: {e}")
    print(f"[msmc] OK: {ok}/{len(updates)}")


if __name__ == "__main__":
    main()
