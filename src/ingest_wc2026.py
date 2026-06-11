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
from datetime import datetime, timezone

from .supabase_writer import sb_get, sb_post, sb_patch


FD_BASE = "https://api.football-data.org/v4"
LIGA_SELECCIONES = 7
TEMPORADA = "2026"
EXPECTED_TOTAL_MATCHES = 104
MIN_DEFINED_MATCHES = 72
MATCH_WINDOW_DAYS = 7

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


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def find_existing_match(
    existing: list[dict],
    home_id: int,
    away_id: int,
    fecha_iso: str,
    claimed_ids: set[int] | None = None,
) -> dict | None:
    """Busca el mismo cruce cerca de la fecha nueva para conservar su partido_id."""
    claimed = claimed_ids if claimed_ids is not None else set()
    source_date = _parse_utc(fecha_iso)
    candidates = []
    for row in existing:
        row_id = int(row["id"])
        if row_id in claimed:
            continue
        if row["equipo_local_id"] != home_id or row["equipo_visitante_id"] != away_id:
            continue
        diff_days = abs((_parse_utc(row["fecha"]) - source_date).total_seconds()) / 86400
        if diff_days <= MATCH_WINDOW_DAYS:
            candidates.append((diff_days, row_id, row))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][2]


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
    if len(matches) < EXPECTED_TOTAL_MATCHES:
        raise RuntimeError(
            f"Fixture incompleto: se esperaban {EXPECTED_TOTAL_MATCHES} partidos "
            f"y football-data devolvio {len(matches)}"
        )

    # Indice nombre ES -> equipo_id
    equipos = sb_get(f"equipos?select=id,nombre&liga_id=eq.{LIGA_SELECCIONES}")
    name_to_id = {e["nombre"]: e["id"] for e in equipos}
    print(f"[wc2026] equipos liga {LIGA_SELECCIONES} en DB: {len(name_to_id)}")
    if len(name_to_id) < 48:
        raise RuntimeError(
            f"Faltan selecciones del Mundial en Supabase: hay {len(name_to_id)}, se esperaban 48"
        )

    # Solo comparamos contra el fixture 2026, no amistosos historicos de liga 7.
    existing = sb_get(
        "partidos?select=id,fecha,equipo_local_id,equipo_visitante_id,"
        "estado,goles_local,goles_visitante,grupo"
        f"&liga_id=eq.{LIGA_SELECCIONES}&temporada=eq.{TEMPORADA}&limit=500"
    )
    print(f"[wc2026] partidos liga {LIGA_SELECCIONES} en DB: {len(existing)}")

    nuevos: list[dict] = []
    a_actualizar: list[tuple[int, dict]] = []
    claimed_ids: set[int] = set()
    source_keys: set[tuple[int, int, str]] = set()
    skip_tbd = 0
    defined_matches = 0
    errors: list[str] = []

    for m in matches:
        home_name = m.get("homeTeam", {}).get("name")
        away_name = m.get("awayTeam", {}).get("name")
        if home_name is None or away_name is None:
            skip_tbd += 1
            continue
        defined_matches += 1
        home_es = FD_TO_ES.get(home_name)
        away_es = FD_TO_ES.get(away_name)
        if not home_es or not away_es:
            errors.append(f"sin mapping: {home_name!r} vs {away_name!r}")
            continue
        home_id = name_to_id.get(home_es)
        away_id = name_to_id.get(away_es)
        if not home_id or not away_id:
            errors.append(
                f"sin equipo_id: {home_es!r} (id={home_id}) vs "
                f"{away_es!r} (id={away_id})"
            )
            continue

        fecha_iso = m.get("utcDate")  # ej "2026-06-11T20:00:00Z"
        if not fecha_iso:
            errors.append(f"sin utcDate: {home_name!r} vs {away_name!r}")
            continue
        raw_status = m.get("status")
        estado = FD_STATUS_MAP.get(raw_status)
        if estado is None:
            errors.append(
                f"status desconocido {raw_status!r}: {home_name!r} vs {away_name!r}"
            )
            continue
        score = m.get("score", {}).get("fullTime", {}) or {}
        gl = score.get("home")
        gv = score.get("away")

        # Bug fix 11-jun-2026 (Mexico-Sudafrica 0-0 falso): football-data.org
        # puede marcar status=FINISHED antes de propagar los scores reales,
        # devolviendo home/away en null. Si esto pasa, NO marcamos finalizado
        # (esperamos al proximo cron, max 30 min) y NO inventamos un 0-0.
        if estado == "finalizado" and (gl is None or gv is None):
            estado = "en_curso"

        # group viene como "GROUP_A".."GROUP_L"; lo guardamos como letra A..L.
        grupo_raw = m.get("group") or ""
        grupo = grupo_raw.replace("GROUP_", "") if grupo_raw.startswith("GROUP_") else None

        payload = {
            "liga_id": LIGA_SELECCIONES,
            "temporada": TEMPORADA,
            "fecha": fecha_iso,
            "equipo_local_id": home_id,
            "equipo_visitante_id": away_id,
            "estado": estado,
            "goles_local":     gl,   # None real si la API no propago aun
            "goles_visitante": gv,
            "grupo": grupo,
        }

        source_key = (home_id, away_id, fecha_iso)
        if source_key in source_keys:
            errors.append(f"partido duplicado en fuente: {home_es} vs {away_es} @ {fecha_iso}")
            continue
        source_keys.add(source_key)

        current = find_existing_match(
            existing, home_id, away_id, fecha_iso, claimed_ids
        )
        if current:
            current_id = int(current["id"])
            claimed_ids.add(current_id)
            a_actualizar.append((current_id, payload))
        else:
            nuevos.append(payload)

    if defined_matches < MIN_DEFINED_MATCHES:
        errors.append(
            f"fixture definido incompleto: {defined_matches} partidos con ambos equipos "
            f"(minimo esperado {MIN_DEFINED_MATCHES})"
        )
    if errors:
        for error in errors:
            print(f"  ! {error}")
        raise RuntimeError(f"Fixture Mundial invalido: {len(errors)} errores")

    print(
        f"[wc2026] nuevos={len(nuevos)} actualizar={len(a_actualizar)} "
        f"skip_tbd={skip_tbd}"
    )

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
        sb_post("partidos", chunk, prefer="return=minimal")
        inserted += len(chunk)
    print(f"[wc2026] insertados {inserted} partidos")

    # Patch existentes: conserva partido_id y corrige horario, score, estado y grupo.
    # IMPORTANTE: si goles_local/visitante vienen None, NO los incluimos en el
    # patch — sino sobreescribimos un score real (ya cargado por otro sync o
    # correccion manual) con null.
    patched = 0
    for pid, payload in a_actualizar:
        patch_data = {
            "fecha":  payload["fecha"],
            "estado": payload["estado"],
            "grupo":  payload.get("grupo"),
        }
        if payload["goles_local"] is not None:
            patch_data["goles_local"] = payload["goles_local"]
        if payload["goles_visitante"] is not None:
            patch_data["goles_visitante"] = payload["goles_visitante"]
        sb_patch(f"partidos?id=eq.{pid}", patch_data)
        patched += 1
    print(f"[wc2026] actualizados {patched} partidos existentes")


if __name__ == "__main__":
    main()
