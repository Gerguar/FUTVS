"""
Ingesta del fixture del Mundial 2026 desde football-data.org (free tier
permite acceso a la competition CURRENT que es la WC 2026 hasta agosto 2026).

El endpoint devuelve 104 matches: 72 de fase de grupos (con equipos definidos)
+ 32 de eliminatorias (con equipos TBD = None mientras no se definan).

Solo cargamos los matches con ambos equipos definidos. Las eliminatorias se
agregan despues a medida que terminen las fases anteriores (vol a correr este
script con el smart-sync diario captura los cambios).

Dedupe: por (liga_id, fecha, equipo_local_id, equipo_visitante_id). Si el mismo
match aparece con los mismos 2 equipos en la misma fecha -> UPDATE; si no -> INSERT.

Uso:
    python -m src.ingest_wc2026
    python -m src.ingest_wc2026 --dry-run
"""
from __future__ import annotations
import argparse
import json
import os
import urllib.error
import urllib.request

from .supabase_writer import sb_get, sb_post, sb_patch


FD_BASE = "https://api.football-data.org/v4"
LIGA_SELECCIONES = 7
TEMPORADA = "2026"

# Nombre que devuelve football-data.org -> nombre en mi tabla `equipos`.
FD_TO_ES: dict[str, str] = {
    "Algeria":            "Argelia",
    "Argentina":          "Argentina",
    "Australia":          "Australia",
    "Austria":            "Austria",
    "Belgium":            "Bélgica",
    "Bosnia-Herzegovina": "Bosnia y Herzegovina",
    "Brazil":             "Brasil",
    "Canada":             "Canadá",
    "Cape Verde Islands": "Cabo Verde",
    "Colombia":           "Colombia",
    "Congo DR":           "RD del Congo",
    "Croatia":            "Croacia",
    "Curaçao":            "Curazao",
    "Czechia":            "República Checa",
    "Ecuador":            "Ecuador",
    "Egypt":              "Egipto",
    "England":            "Inglaterra",
    "France":             "Francia",
    "Germany":            "Alemania",
    "Ghana":              "Ghana",
    "Haiti":              "Haití",
    "Iran":               "Irán",
    "Iraq":               "Irak",
    "Ivory Coast":        "Costa de Marfil",
    "Japan":              "Japón",
    "Jordan":             "Jordania",
    "Mexico":             "México",
    "Morocco":            "Marruecos",
    "Netherlands":        "Países Bajos",
    "New Zealand":        "Nueva Zelanda",
    "Norway":             "Noruega",
    "Panama":             "Panamá",
    "Paraguay":           "Paraguay",
    "Portugal":           "Portugal",
    "Qatar":              "Qatar",
    "Saudi Arabia":       "Arabia Saudita",
    "Scotland":           "Escocia",
    "Senegal":            "Senegal",
    "South Africa":       "Sudáfrica",
    "South Korea":        "Corea del Sur",
    "Spain":              "España",
    "Sweden":             "Suecia",
    "Switzerland":        "Suiza",
    "Tunisia":            "Túnez",
    "Turkey":             "Turquía",
    "United States":      "Estados Unidos",
    "Uruguay":            "Uruguay",
    "Uzbekistan":         "Uzbekistán",
}

# Status football-data -> nuestro `estado`
FD_STATUS_MAP = {
    "SCHEDULED": "programado",
    "TIMED":     "programado",
    "POSTPONED": "programado",
    "IN_PLAY":   "en_curso",
    "PAUSED":    "en_curso",
    "FINISHED":  "finalizado",
    "SUSPENDED": "suspendido",
    "CANCELLED": "suspendido",
    "AWARDED":   "finalizado",
}


def fetch_wc_matches() -> list[dict]:
    token = os.environ.get("FOOTBALL_DATA_TOKEN")
    if not token:
        raise RuntimeError("Falta FOOTBALL_DATA_TOKEN en el entorno")
    url = f"{FD_BASE}/competitions/WC/matches?dateFrom=2026-05-01&dateTo=2026-08-01"
    req = urllib.request.Request(url, headers={"X-Auth-Token": token})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read())
    return data.get("matches", [])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    matches = fetch_wc_matches()
    print(f"[wc2026] football-data devolvio {len(matches)} matches del Mundial 2026")

    # Indice nombre ES -> equipo_id
    equipos = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_SELECCIONES}")
    name_to_id = {e["nombre"]: e["id"] for e in equipos}
    print(f"[wc2026] equipos liga {LIGA_SELECCIONES} en DB: {len(name_to_id)}")

    # Indice de partidos existentes (dedupe por fecha+local+visitante)
    existing = sb_get(f"partidos?select=id,fecha,equipo_local_id,equipo_visitante_id&liga_id=eq.{LIGA_SELECCIONES}")
    by_key: dict[tuple, dict] = {}
    for r in existing:
        key = (r["fecha"][:10], r["equipo_local_id"], r["equipo_visitante_id"])
        by_key[key] = r
    print(f"[wc2026] partidos liga {LIGA_SELECCIONES} en DB: {len(existing)}")

    nuevos: list[dict] = []
    a_actualizar: list[tuple[int, dict]] = []
    skip_tbd = 0
    skip_no_team = 0

    for m in matches:
        home_name = m.get("homeTeam", {}).get("name")
        away_name = m.get("awayTeam", {}).get("name")
        if home_name is None or away_name is None:
            skip_tbd += 1
            continue
        home_es = FD_TO_ES.get(home_name)
        away_es = FD_TO_ES.get(away_name)
        if not home_es or not away_es:
            skip_no_team += 1
            print(f"  ! sin mapping: {home_name!r} vs {away_name!r}")
            continue
        home_id = name_to_id.get(home_es)
        away_id = name_to_id.get(away_es)
        if not home_id or not away_id:
            skip_no_team += 1
            print(f"  ! sin equipo_id: {home_es!r} (id={home_id}) vs {away_es!r} (id={away_id})")
            continue

        fecha_iso = m.get("utcDate")  # ej "2026-06-11T20:00:00Z"
        estado = FD_STATUS_MAP.get(m.get("status"), "programado")
        score = m.get("score", {}).get("fullTime", {}) or {}
        gl = score.get("home")
        gv = score.get("away")

        payload = {
            "liga_id": LIGA_SELECCIONES,
            "temporada": TEMPORADA,
            "fecha": fecha_iso,
            "equipo_local_id": home_id,
            "equipo_visitante_id": away_id,
            "estado": estado,
            "goles_local": gl if gl is not None else 0,
            "goles_visitante": gv if gv is not None else 0,
        }

        key = (fecha_iso[:10], home_id, away_id)
        if key in by_key:
            a_actualizar.append((by_key[key]["id"], payload))
        else:
            nuevos.append(payload)

    print(f"[wc2026] nuevos={len(nuevos)} actualizar={len(a_actualizar)} skip_tbd={skip_tbd} skip_no_team={skip_no_team}")

    if args.dry_run:
        print()
        print("Primeros 8 nuevos:")
        id_to_name = {e["id"]: e["nombre"] for e in equipos}
        for n in nuevos[:8]:
            h = id_to_name.get(n["equipo_local_id"], n["equipo_local_id"])
            a = id_to_name.get(n["equipo_visitante_id"], n["equipo_visitante_id"])
            print(f"  + {n['fecha'][:16]:<17s} {h:<22s} vs {a:<22s} estado={n['estado']}")
        return

    # Insert nuevos en chunks
    inserted = 0
    BATCH = 50
    for i in range(0, len(nuevos), BATCH):
        chunk = nuevos[i:i + BATCH]
        try:
            sb_post("partidos", chunk, prefer="return=minimal")
            inserted += len(chunk)
        except Exception as e:
            print(f"  ! error insert: {e}")
    print(f"[wc2026] insertados {inserted} partidos")

    # Patch existentes (cambia score/estado si cambio)
    patched = 0
    for pid, payload in a_actualizar:
        patch_data = {
            "estado": payload["estado"],
            "goles_local": payload["goles_local"],
            "goles_visitante": payload["goles_visitante"],
        }
        try:
            sb_patch(f"partidos?id=eq.{pid}", patch_data)
            patched += 1
        except Exception as e:
            print(f"  ! error patch id={pid}: {e}")
    print(f"[wc2026] actualizados {patched} partidos existentes")


if __name__ == "__main__":
    main()
