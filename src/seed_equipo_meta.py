"""
Carga inicial de equipo_meta + finales_historicas.

Datos manuales (basados en Wikipedia / fuentes oficiales a 2025) para las
top entidades del proyecto: clubes top 5 ligas europeas + selecciones top.

Para los demas equipos se completa despues o se scrapea Wikipedia.

Uso:
    python -m src.seed_equipo_meta --dry-run
    python -m src.seed_equipo_meta
"""
from __future__ import annotations
import argparse

from .supabase_writer import sb_get, sb_post


# ── Datos por NOMBRE de equipo (debe coincidir con equipos.nombre) ──
# Source: Wikipedia infoboxes a noviembre 2025.
EQUIPO_META: dict[str, dict] = {
    # === LA LIGA ===
    "Real Madrid": dict(
        ano_fundacion=1902, capacidad_estadio=81044, socios=95000,
        titulos_liga=36, titulos_copa_nacional=20,
        titulos_continental=15,  # UEFA Champions League
        titulos_mundial_clubes=9,  # 4 Intercontinental + 5 Mundial Clubes FIFA
        descensos=0,
    ),
    "Barcelona": dict(
        ano_fundacion=1899, capacidad_estadio=99354, socios=140000,
        titulos_liga=27, titulos_copa_nacional=31,
        titulos_continental=5, titulos_mundial_clubes=3, descensos=0,
    ),
    "Atlético Madrid": dict(
        ano_fundacion=1903, capacidad_estadio=70460, socios=130000,
        titulos_liga=11, titulos_copa_nacional=10,
        titulos_continental=3,  # 0 UCL + 3 UEL/Recopa
        titulos_mundial_clubes=1, descensos=1,
    ),
    "Athletic": dict(
        ano_fundacion=1898, capacidad_estadio=53289, socios=45000,
        titulos_liga=8, titulos_copa_nacional=24,
        titulos_continental=0, titulos_mundial_clubes=0, descensos=0,
    ),
    "Valencia": dict(
        ano_fundacion=1919, capacidad_estadio=49430, socios=50000,
        titulos_liga=6, titulos_copa_nacional=8,
        titulos_continental=4, titulos_mundial_clubes=0, descensos=0,
    ),
    "Sevilla FC": dict(
        ano_fundacion=1890, capacidad_estadio=43883, socios=50000,
        titulos_liga=1, titulos_copa_nacional=5,
        titulos_continental=7,  # 7 UEL — record absoluto
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Real Sociedad": dict(
        ano_fundacion=1909, capacidad_estadio=39500, socios=36000,
        titulos_liga=2, titulos_copa_nacional=3,
        titulos_continental=0, titulos_mundial_clubes=0, descensos=0,
    ),
    "Villarreal": dict(
        ano_fundacion=1923, capacidad_estadio=23500, socios=23000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_continental=1, titulos_mundial_clubes=0, descensos=0,
    ),

    # === PREMIER LEAGUE ===
    "Man United": dict(
        ano_fundacion=1878, capacidad_estadio=74310,
        titulos_liga=20, titulos_copa_nacional=13,
        titulos_continental=4,  # 3 UCL + 1 UEL
        titulos_mundial_clubes=2, descensos=0,
    ),
    "Liverpool": dict(
        ano_fundacion=1892, capacidad_estadio=61276,
        titulos_liga=20, titulos_copa_nacional=8,
        titulos_continental=9,  # 6 UCL + 3 UEFA Cup
        titulos_mundial_clubes=1, descensos=0,
    ),
    "Man. City": dict(
        ano_fundacion=1880, capacidad_estadio=53400,
        titulos_liga=10, titulos_copa_nacional=7,
        titulos_continental=1, titulos_mundial_clubes=1, descensos=0,
    ),
    "Arsenal": dict(
        ano_fundacion=1886, capacidad_estadio=60704,
        titulos_liga=13, titulos_copa_nacional=14,
        titulos_continental=0, titulos_mundial_clubes=0, descensos=0,
    ),
    "Chelsea": dict(
        ano_fundacion=1905, capacidad_estadio=40173,
        titulos_liga=6, titulos_copa_nacional=8,
        titulos_continental=4,  # 2 UCL + 2 UEL
        titulos_mundial_clubes=1, descensos=0,
    ),
    "Tottenham": dict(
        ano_fundacion=1882, capacidad_estadio=62850,
        titulos_liga=2, titulos_copa_nacional=8,
        titulos_continental=3,  # 2 UEFA Cup + 1 UEL
        titulos_mundial_clubes=0, descensos=0,
    ),

    # === SERIE A ===
    "Juventus": dict(
        ano_fundacion=1897, capacidad_estadio=41507,
        titulos_liga=36, titulos_copa_nacional=15,
        titulos_continental=5,  # 2 UCL + 3 UEFA Cup
        titulos_mundial_clubes=2, descensos=1,
    ),
    "AC Milán": dict(
        ano_fundacion=1899, capacidad_estadio=75817,
        titulos_liga=19, titulos_copa_nacional=5,
        titulos_continental=7,  # 7 UCL
        titulos_mundial_clubes=4, descensos=0,
    ),
    "Inter Milán": dict(
        ano_fundacion=1908, capacidad_estadio=75817,
        titulos_liga=20, titulos_copa_nacional=9,
        titulos_continental=6,  # 3 UCL + 3 UEFA Cup
        titulos_mundial_clubes=3, descensos=0,
    ),
    "Napoli": dict(
        ano_fundacion=1926, capacidad_estadio=54726,
        titulos_liga=3, titulos_copa_nacional=6,
        titulos_continental=1, titulos_mundial_clubes=0, descensos=2,
    ),
    "Roma": dict(
        ano_fundacion=1927, capacidad_estadio=70634,
        titulos_liga=3, titulos_copa_nacional=9,
        titulos_continental=1, titulos_mundial_clubes=0, descensos=0,
    ),

    # === BUNDESLIGA ===
    "Bayern Múnich": dict(
        ano_fundacion=1900, capacidad_estadio=75000, socios=360000,
        titulos_liga=33, titulos_copa_nacional=20,
        titulos_continental=7,  # 6 UCL + 1 UEFA Cup
        titulos_mundial_clubes=4, descensos=0,
    ),
    "Dortmund": dict(
        ano_fundacion=1909, capacidad_estadio=81365, socios=175000,
        titulos_liga=8, titulos_copa_nacional=5,
        titulos_continental=2,  # 1 UCL + 1 Recopa
        titulos_mundial_clubes=1, descensos=0,
    ),

    # === LIGUE 1 ===
    "PSG": dict(
        ano_fundacion=1970, capacidad_estadio=47929,
        titulos_liga=12, titulos_copa_nacional=15,
        titulos_continental=2,  # 1 Recopa + 1 UCL 2025
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Marseille": dict(
        ano_fundacion=1899, capacidad_estadio=67394,
        titulos_liga=9, titulos_copa_nacional=10,
        titulos_continental=1, titulos_mundial_clubes=0, descensos=1,
    ),

    # === SELECCIONES TOP FIFA ===
    "Argentina": dict(
        ano_fundacion=1893,
        mundiales_ganados=3,    # 1978, 1986, 2022
        finales_mundial=6,
        copas_continentales=16, # 16 Copas America
        apariciones_mundial=19,
    ),
    "Brasil": dict(
        ano_fundacion=1914,
        mundiales_ganados=5,    # 1958, 1962, 1970, 1994, 2002
        finales_mundial=7,
        copas_continentales=9,  # 9 Copas America
        apariciones_mundial=22,
    ),
    "Alemania": dict(
        ano_fundacion=1900,
        mundiales_ganados=4,    # 1954, 1974, 1990, 2014
        finales_mundial=8,
        copas_continentales=3,  # 3 Euros
        apariciones_mundial=21,
    ),
    "Italia": dict(
        ano_fundacion=1898,
        mundiales_ganados=4,    # 1934, 1938, 1982, 2006
        finales_mundial=6,
        copas_continentales=2,  # 2 Euros
        apariciones_mundial=18,
    ),
    "Francia": dict(
        ano_fundacion=1904,
        mundiales_ganados=2,    # 1998, 2018
        finales_mundial=4,
        copas_continentales=2,  # 2 Euros (1984, 2000)
        apariciones_mundial=16,
    ),
    "Uruguay": dict(
        ano_fundacion=1900,
        mundiales_ganados=2,    # 1930, 1950
        finales_mundial=2,
        copas_continentales=15, # 15 Copas America
        apariciones_mundial=14,
    ),
    "España": dict(
        ano_fundacion=1909,
        mundiales_ganados=1,    # 2010
        finales_mundial=1,
        copas_continentales=4,  # 4 Euros (1964, 2008, 2012, 2024)
        apariciones_mundial=16,
    ),
    "Inglaterra": dict(
        ano_fundacion=1872,
        mundiales_ganados=1,    # 1966
        finales_mundial=1,
        copas_continentales=0,  # 0 Euros (subcampeon 2020, 2024)
        apariciones_mundial=16,
    ),
    "Países Bajos": dict(
        ano_fundacion=1889,
        mundiales_ganados=0,
        finales_mundial=3,      # 1974, 1978, 2010
        copas_continentales=1,  # Euro 1988
        apariciones_mundial=11,
    ),
    "Portugal": dict(
        ano_fundacion=1914,
        mundiales_ganados=0,
        finales_mundial=0,
        copas_continentales=1,  # Euro 2016
        apariciones_mundial=8,
    ),
    "Croacia": dict(
        ano_fundacion=1912,
        mundiales_ganados=0,
        finales_mundial=1,      # 2018
        copas_continentales=0,
        apariciones_mundial=6,
    ),
    "Bélgica": dict(
        ano_fundacion=1895,
        mundiales_ganados=0, finales_mundial=0,
        copas_continentales=0, apariciones_mundial=14,
    ),
    "México": dict(
        ano_fundacion=1927,
        mundiales_ganados=0, finales_mundial=0,
        copas_continentales=12,  # Copas Oro / CONCACAF
        apariciones_mundial=17,
    ),
    "Estados Unidos": dict(
        ano_fundacion=1913,
        mundiales_ganados=0, finales_mundial=0,
        copas_continentales=7,   # Copas Oro
        apariciones_mundial=11,
    ),
    "Marruecos": dict(
        ano_fundacion=1955,
        mundiales_ganados=0, finales_mundial=0,
        copas_continentales=1,   # AFCON 1976
        apariciones_mundial=6,
    ),
}


# ── Finales H2H notables ──
# (equipo_a_nombre, equipo_b_nombre, ganador_nombre_o_None, competencia, anio, marcador)
FINALES_H2H = [
    # Real Madrid vs Barcelona — finales clasicas
    ("Real Madrid", "Barcelona", "Real Madrid", "Copa del Rey 2010-11", 2011, "1-0"),
    ("Real Madrid", "Barcelona", "Real Madrid", "Copa del Rey 2013-14", 2014, "2-1"),
    ("Real Madrid", "Barcelona", "Barcelona", "Copa del Rey 2008-09", 2009, "1-4"),
    ("Real Madrid", "Barcelona", "Real Madrid", "Supercopa España 2017", 2017, "5-1 global"),
    ("Real Madrid", "Barcelona", "Barcelona", "Supercopa España 2018", 2018, "5-1 global"),

    # Argentina vs Brasil
    ("Argentina", "Brasil", "Argentina", "Copa América 2021", 2021, "1-0"),
    ("Argentina", "Brasil", "Brasil", "Copa América 2007", 2007, "0-3"),
    ("Argentina", "Brasil", "Brasil", "Copa América 2004", 2004, "2-2 (4-2 pen)"),
    ("Argentina", "Brasil", "Argentina", "Copa América 1937", 1937, "2-0"),

    # Alemania vs Italia / Francia
    ("Alemania", "Italia", "Italia", "Mundial 1982 (final)", 1982, "3-1"),
    ("Alemania", "Italia", "Italia", "Mundial 2006 (semifinal)", 2006, "0-2"),
    ("Alemania", "Italia", None,    "Eurocopa 2012 (semifinal)", 2012, "1-2 (gana ITA)"),
    ("Francia", "Italia",  "Italia", "Mundial 2006 (final)", 2006, "1-1 (3-5 pen)"),
    ("Francia", "Italia",  "Francia","Eurocopa 2000 (final)", 2000, "2-1"),

    # Brasil vs Italia
    ("Brasil", "Italia", "Brasil", "Mundial 1994 (final)", 1994, "0-0 (3-2 pen)"),
    ("Brasil", "Italia", "Brasil", "Mundial 1970 (final)", 1970, "4-1"),

    # Brasil vs Alemania
    ("Brasil", "Alemania", "Brasil", "Mundial 2002 (final)", 2002, "2-0"),

    # AC Milan vs Inter
    ("AC Milán", "Inter Milán", "Inter Milán", "Supercopa Italia 2022", 2022, "3-0"),
    ("AC Milán", "Inter Milán", "AC Milán", "Copa Italia 1976-77", 1977, "2-0"),
]


def index_equipos_by_name() -> dict[str, dict]:
    """Devuelve {nombre: equipo_row} para todos los equipos en Supabase."""
    rows = sb_get("equipos?select=id,nombre,liga_id")
    return {r["nombre"]: r for r in rows}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    by_name = index_equipos_by_name()
    print(f"[seed-meta] equipos en DB: {len(by_name)}")

    # ── Parte 1: equipo_meta ──
    # PostgREST exige que todos los objetos del array tengan EXACTAMENTE las
    # mismas keys. Normalizamos con TODAS las columnas (los faltantes -> None).
    ALL_KEYS = [
        "ano_fundacion", "capacidad_estadio", "socios",
        "titulos_liga", "titulos_copa_nacional", "titulos_continental",
        "titulos_mundial_clubes", "descensos",
        "mundiales_ganados", "finales_mundial", "copas_continentales",
        "apariciones_mundial",
    ]
    payloads: list[dict] = []
    missing: list[str] = []
    for nombre, meta in EQUIPO_META.items():
        eq = by_name.get(nombre)
        if not eq:
            missing.append(nombre)
            continue
        row = {"equipo_id": eq["id"]}
        for k in ALL_KEYS:
            row[k] = meta.get(k)  # None si no lo define
        payloads.append(row)

    print(f"[seed-meta] payloads listos: {len(payloads)} | sin match en equipos: {len(missing)}")
    if missing:
        for m in missing:
            print(f"  ! sin match: {m!r}")

    if args.dry_run:
        print("\nPrimeros 5 payloads:")
        for p in payloads[:5]:
            print(f"  {p}")
    else:
        try:
            sb_post(
                "equipo_meta?on_conflict=equipo_id",
                payloads,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            print(f"[seed-meta] equipo_meta: upsert OK ({len(payloads)} filas)")
        except Exception as e:
            print(f"  ! error upsert equipo_meta: {e}")

    # ── Parte 2: finales_historicas ──
    finales_payloads: list[dict] = []
    finales_missing: list[tuple] = []
    for (a, b, ganador, comp, anio, marc) in FINALES_H2H:
        ea = by_name.get(a)
        eb = by_name.get(b)
        if not ea or not eb:
            finales_missing.append((a, b))
            continue
        ganador_id = None
        if ganador == a: ganador_id = ea["id"]
        elif ganador == b: ganador_id = eb["id"]
        finales_payloads.append({
            "equipo_a_id": ea["id"],
            "equipo_b_id": eb["id"],
            "ganador_id": ganador_id,
            "competencia": comp,
            "anio": anio,
            "marcador": marc,
        })
    print(f"\n[seed-meta] finales_historicas: {len(finales_payloads)} para cargar | {len(finales_missing)} sin match")
    for m in finales_missing:
        print(f"  ! finales sin equipo: {m}")

    if args.dry_run:
        print("\nPrimeras 5 finales:")
        for f in finales_payloads[:5]:
            print(f"  {f}")
        return

    try:
        # Para finales: borramos lo que haya y reinsertamos (no hay PK natural).
        # Como es la primera carga, es seguro.
        sb_post("finales_historicas", finales_payloads, prefer="return=minimal")
        print(f"[seed-meta] finales_historicas: insertadas {len(finales_payloads)} filas")
    except Exception as e:
        print(f"  ! error insert finales_historicas: {e}")


if __name__ == "__main__":
    main()
