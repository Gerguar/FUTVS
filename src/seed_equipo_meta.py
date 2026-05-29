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
        titulos_champions=15, titulos_internacionales=2, supercopas=19,
        titulos_mundial_clubes=9, descensos=0,
    ),
    "Barcelona": dict(
        ano_fundacion=1899, capacidad_estadio=99354, socios=140000,
        titulos_liga=27, titulos_copa_nacional=31,
        titulos_champions=5, titulos_internacionales=4, supercopas=19,
        titulos_mundial_clubes=3, descensos=0,
    ),
    "Atlético Madrid": dict(
        ano_fundacion=1903, capacidad_estadio=70460, socios=130000,
        titulos_liga=11, titulos_copa_nacional=10,
        titulos_champions=0, titulos_internacionales=4, supercopas=5,
        titulos_mundial_clubes=1, descensos=1,
    ),
    "Athletic": dict(
        ano_fundacion=1898, capacidad_estadio=53289, socios=45000,
        titulos_liga=8, titulos_copa_nacional=24,
        titulos_champions=0, titulos_internacionales=0, supercopas=3,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Valencia": dict(
        ano_fundacion=1919, capacidad_estadio=49430, socios=50000,
        titulos_liga=6, titulos_copa_nacional=8,
        titulos_champions=0, titulos_internacionales=2, supercopas=3,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Sevilla FC": dict(
        ano_fundacion=1890, capacidad_estadio=43883, socios=50000,
        titulos_liga=1, titulos_copa_nacional=5,
        titulos_champions=0, titulos_internacionales=7, supercopas=2,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Real Sociedad": dict(
        ano_fundacion=1909, capacidad_estadio=39500, socios=36000,
        titulos_liga=2, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Villarreal": dict(
        ano_fundacion=1923, capacidad_estadio=23500, socios=23000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=1, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),

    # === PREMIER LEAGUE ===
    "Man United": dict(
        ano_fundacion=1878, capacidad_estadio=74310,
        titulos_liga=20, titulos_copa_nacional=13,
        titulos_champions=3, titulos_internacionales=2, supercopas=23,
        titulos_mundial_clubes=2, descensos=0,
    ),
    "Liverpool": dict(
        ano_fundacion=1892, capacidad_estadio=61276,
        titulos_liga=20, titulos_copa_nacional=8,
        titulos_champions=6, titulos_internacionales=3, supercopas=20,
        titulos_mundial_clubes=1, descensos=0,
    ),
    "Man. City": dict(
        ano_fundacion=1880, capacidad_estadio=53400,
        titulos_liga=10, titulos_copa_nacional=7,
        titulos_champions=1, titulos_internacionales=1, supercopas=8,
        titulos_mundial_clubes=1, descensos=0,
    ),
    "Arsenal": dict(
        ano_fundacion=1886, capacidad_estadio=60704,
        titulos_liga=13, titulos_copa_nacional=14,
        titulos_champions=0, titulos_internacionales=1, supercopas=17,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Chelsea": dict(
        ano_fundacion=1905, capacidad_estadio=40173,
        titulos_liga=6, titulos_copa_nacional=8,
        titulos_champions=2, titulos_internacionales=4, supercopas=6,
        titulos_mundial_clubes=1, descensos=0,
    ),
    "Tottenham": dict(
        ano_fundacion=1882, capacidad_estadio=62850,
        titulos_liga=2, titulos_copa_nacional=8,
        titulos_champions=0, titulos_internacionales=3, supercopas=7,
        titulos_mundial_clubes=0, descensos=0,
    ),

    # === SERIE A ===
    "Juventus": dict(
        ano_fundacion=1897, capacidad_estadio=41507,
        titulos_liga=36, titulos_copa_nacional=15,
        titulos_champions=2, titulos_internacionales=4, supercopas=11,
        titulos_mundial_clubes=2, descensos=1,
    ),
    "AC Milán": dict(
        ano_fundacion=1899, capacidad_estadio=75817,
        titulos_liga=19, titulos_copa_nacional=5,
        titulos_champions=7, titulos_internacionales=2, supercopas=12,
        titulos_mundial_clubes=4, descensos=0,
    ),
    "Inter Milán": dict(
        ano_fundacion=1908, capacidad_estadio=75817,
        titulos_liga=20, titulos_copa_nacional=9,
        titulos_champions=3, titulos_internacionales=3, supercopas=8,
        titulos_mundial_clubes=3, descensos=0,
    ),
    "Napoli": dict(
        ano_fundacion=1926, capacidad_estadio=54726,
        titulos_liga=3, titulos_copa_nacional=6,
        titulos_champions=0, titulos_internacionales=1, supercopas=2,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Roma": dict(
        ano_fundacion=1927, capacidad_estadio=70634,
        titulos_liga=3, titulos_copa_nacional=9,
        titulos_champions=0, titulos_internacionales=0, supercopas=2,
        titulos_mundial_clubes=0, descensos=0,
    ),

    # === BUNDESLIGA ===
    "Bayern Múnich": dict(
        ano_fundacion=1900, capacidad_estadio=75000, socios=360000,
        titulos_liga=33, titulos_copa_nacional=20,
        titulos_champions=6, titulos_internacionales=2, supercopas=13,
        titulos_mundial_clubes=4, descensos=0,
    ),
    "Dortmund": dict(
        ano_fundacion=1909, capacidad_estadio=81365, socios=175000,
        titulos_liga=8, titulos_copa_nacional=5,
        titulos_champions=1, titulos_internacionales=1, supercopas=6,
        titulos_mundial_clubes=1, descensos=0,
    ),

    # === LIGUE 1 ===
    "PSG": dict(
        ano_fundacion=1970, capacidad_estadio=47929,
        titulos_liga=12, titulos_copa_nacional=15,
        titulos_champions=1, titulos_internacionales=1, supercopas=13,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Marseille": dict(
        ano_fundacion=1899, capacidad_estadio=67394,
        titulos_liga=9, titulos_copa_nacional=10,
        titulos_champions=1, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=1,
    ),

    # === LA LIGA (resto) ===
    "Real Betis": dict(
        ano_fundacion=1907, capacidad_estadio=60721,
        titulos_liga=1, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=7,
    ),
    "Espanyol": dict(
        ano_fundacion=1900, capacidad_estadio=40000,
        titulos_liga=0, titulos_copa_nacional=4,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=3,
    ),
    "Celta": dict(
        ano_fundacion=1923, capacidad_estadio=29000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Mallorca": dict(
        ano_fundacion=1916, capacidad_estadio=23142,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Osasuna": dict(
        ano_fundacion=1920, capacidad_estadio=23576,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Rayo Vallecano": dict(
        ano_fundacion=1924, capacidad_estadio=14708,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Getafe": dict(
        ano_fundacion=1983, capacidad_estadio=17000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Girona": dict(
        ano_fundacion=1930, capacidad_estadio=14624,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Alavés": dict(
        ano_fundacion=1921, capacidad_estadio=19840,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Levante": dict(
        ano_fundacion=1909, capacidad_estadio=26354,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Elche": dict(
        ano_fundacion=1923, capacidad_estadio=31388,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=7,
    ),
    "Real Oviedo": dict(
        ano_fundacion=1926, capacidad_estadio=30500,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),

    # === PREMIER LEAGUE (resto) ===
    "Newcastle": dict(
        ano_fundacion=1892, capacidad_estadio=52305,
        titulos_liga=4, titulos_copa_nacional=6,
        titulos_champions=0, titulos_internacionales=1, supercopas=1,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Aston Villa": dict(
        ano_fundacion=1874, capacidad_estadio=42657,
        titulos_liga=7, titulos_copa_nacional=7,
        titulos_champions=1, titulos_internacionales=0, supercopas=2,
        titulos_mundial_clubes=0, descensos=3,
    ),
    "Everton": dict(
        ano_fundacion=1878, capacidad_estadio=52888,
        titulos_liga=9, titulos_copa_nacional=5,
        titulos_champions=0, titulos_internacionales=1, supercopas=9,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "West Ham": dict(
        ano_fundacion=1895, capacidad_estadio=62500,
        titulos_liga=0, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=2, supercopas=1,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Nottingham": dict(
        ano_fundacion=1865, capacidad_estadio=30445,
        titulos_liga=1, titulos_copa_nacional=2,
        titulos_champions=2, titulos_internacionales=0, supercopas=2,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Wolverhampton": dict(
        ano_fundacion=1877, capacidad_estadio=31750,
        titulos_liga=3, titulos_copa_nacional=4,
        titulos_champions=0, titulos_internacionales=0, supercopas=4,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Leeds United": dict(
        ano_fundacion=1919, capacidad_estadio=37608,
        titulos_liga=3, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=2, supercopas=2,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Sunderland": dict(
        ano_fundacion=1879, capacidad_estadio=49000,
        titulos_liga=6, titulos_copa_nacional=2,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Burnley": dict(
        ano_fundacion=1882, capacidad_estadio=21944,
        titulos_liga=2, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=2,
        titulos_mundial_clubes=0, descensos=9,
    ),
    "Crystal Palace": dict(
        ano_fundacion=1905, capacidad_estadio=25486,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Fulham": dict(
        ano_fundacion=1879, capacidad_estadio=29589,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Brighton Hove": dict(
        ano_fundacion=1901, capacidad_estadio=31800,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "Bournemouth": dict(
        ano_fundacion=1899, capacidad_estadio=11307,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "Brentford": dict(
        ano_fundacion=1889, capacidad_estadio=17250,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=1,
    ),

    # === SERIE A (resto) ===
    "Lazio": dict(
        ano_fundacion=1900, capacidad_estadio=70634,
        titulos_liga=2, titulos_copa_nacional=7,
        titulos_champions=0, titulos_internacionales=1, supercopas=6,
        titulos_mundial_clubes=0, descensos=3,
    ),
    "Fiorentina": dict(
        ano_fundacion=1926, capacidad_estadio=43147,
        titulos_liga=2, titulos_copa_nacional=6,
        titulos_champions=0, titulos_internacionales=1, supercopas=1,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Torino": dict(
        ano_fundacion=1906, capacidad_estadio=27958,
        titulos_liga=7, titulos_copa_nacional=5,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Atalanta": dict(
        ano_fundacion=1907, capacidad_estadio=19000,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=1, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Bologna": dict(
        ano_fundacion=1909, capacidad_estadio=38279,
        titulos_liga=7, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Cagliari": dict(
        ano_fundacion=1920, capacidad_estadio=16416,
        titulos_liga=1, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Verona": dict(
        ano_fundacion=1903, capacidad_estadio=39211,
        titulos_liga=1, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=7,
    ),
    "Genoa": dict(
        ano_fundacion=1893, capacidad_estadio=36599,
        titulos_liga=9, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=7,
    ),
    "Udinese": dict(
        ano_fundacion=1896, capacidad_estadio=25144,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Parma": dict(
        ano_fundacion=1913, capacidad_estadio=22885,
        titulos_liga=0, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=2, supercopas=2,
        titulos_mundial_clubes=0, descensos=3,
    ),
    "Lecce": dict(
        ano_fundacion=1908, capacidad_estadio=31559,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=7,
    ),
    "Sassuolo": dict(
        ano_fundacion=1920, capacidad_estadio=21584,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "Cremonese": dict(
        ano_fundacion=1903, capacidad_estadio=16003,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Como 1907": dict(
        ano_fundacion=1907, capacidad_estadio=13602,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "AC Pisa": dict(
        ano_fundacion=1909, capacidad_estadio=17000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),

    # === BUNDESLIGA (resto) ===
    "RB Leipzig": dict(
        ano_fundacion=2009, capacidad_estadio=47069,
        titulos_liga=0, titulos_copa_nacional=2,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Bremen": dict(
        ano_fundacion=1899, capacidad_estadio=42100,
        titulos_liga=4, titulos_copa_nacional=6,
        titulos_champions=0, titulos_internacionales=1, supercopas=3,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "Stuttgart": dict(
        ano_fundacion=1893, capacidad_estadio=60449,
        titulos_liga=5, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "M'gladbach": dict(
        ano_fundacion=1900, capacidad_estadio=54042,
        titulos_liga=5, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=2, supercopas=0,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "HSV": dict(
        ano_fundacion=1887, capacidad_estadio=57000,
        titulos_liga=6, titulos_copa_nacional=3,
        titulos_champions=1, titulos_internacionales=1, supercopas=1,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "1. FC Köln": dict(
        ano_fundacion=1948, capacidad_estadio=50000,
        titulos_liga=3, titulos_copa_nacional=4,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Wolfsburg": dict(
        ano_fundacion=1945, capacidad_estadio=30000,
        titulos_liga=1, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Freiburg": dict(
        ano_fundacion=1904, capacidad_estadio=34700,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Mainz": dict(
        ano_fundacion=1905, capacidad_estadio=33305,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Augsburg": dict(
        ano_fundacion=1907, capacidad_estadio=30660,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Hoffenheim": dict(
        ano_fundacion=1899, capacidad_estadio=30150,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "Union Berlin": dict(
        ano_fundacion=1966, capacidad_estadio=22012,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),
    "St. Pauli": dict(
        ano_fundacion=1910, capacidad_estadio=29546,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Heidenheim": dict(
        ano_fundacion=1911, capacidad_estadio=15000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=0,
    ),

    # === LIGUE 1 (resto) ===
    "Olympique Lyon": dict(
        ano_fundacion=1950, capacidad_estadio=59186,
        titulos_liga=7, titulos_copa_nacional=5,
        titulos_champions=0, titulos_internacionales=0, supercopas=8,
        titulos_mundial_clubes=0, descensos=1,
    ),
    "Lille": dict(
        ano_fundacion=1944, capacidad_estadio=50186,
        titulos_liga=4, titulos_copa_nacional=6,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Nantes": dict(
        ano_fundacion=1943, capacidad_estadio=35322,
        titulos_liga=8, titulos_copa_nacional=4,
        titulos_champions=0, titulos_internacionales=0, supercopas=3,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Nice": dict(
        ano_fundacion=1904, capacidad_estadio=36178,
        titulos_liga=4, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "RC Lens": dict(
        ano_fundacion=1906, capacidad_estadio=38223,
        titulos_liga=1, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Strasbourg": dict(
        ano_fundacion=1906, capacidad_estadio=26109,
        titulos_liga=1, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Stade Rennais": dict(
        ano_fundacion=1901, capacidad_estadio=29778,
        titulos_liga=0, titulos_copa_nacional=3,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Auxerre": dict(
        ano_fundacion=1905, capacidad_estadio=18541,
        titulos_liga=1, titulos_copa_nacional=4,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=2,
    ),
    "Toulouse": dict(
        ano_fundacion=1970, capacidad_estadio=33150,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "FC Metz": dict(
        ano_fundacion=1932, capacidad_estadio=30000,
        titulos_liga=0, titulos_copa_nacional=2,
        titulos_champions=0, titulos_internacionales=0, supercopas=1,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Lorient": dict(
        ano_fundacion=1926, capacidad_estadio=18890,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=3,
    ),
    "Le Havre": dict(
        ano_fundacion=1872, capacidad_estadio=25178,
        titulos_liga=0, titulos_copa_nacional=1,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=6,
    ),
    "Brest": dict(
        ano_fundacion=1950, capacidad_estadio=15931,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=4,
    ),
    "Angers SCO": dict(
        ano_fundacion=1919, capacidad_estadio=18752,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=5,
    ),
    "Paris FC": dict(
        ano_fundacion=1969, capacidad_estadio=20000,
        titulos_liga=0, titulos_copa_nacional=0,
        titulos_champions=0, titulos_internacionales=0, supercopas=0,
        titulos_mundial_clubes=0, descensos=3,
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

    # --- CONMEBOL ---
    "Colombia": dict(ano_fundacion=1924, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=6),
    "Ecuador":  dict(ano_fundacion=1925, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=4),
    "Paraguay": dict(ano_fundacion=1906, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=8),
    "Chile":    dict(ano_fundacion=1895, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=9),
    "Perú":     dict(ano_fundacion=1922, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=5),
    "Bolivia":  dict(ano_fundacion=1925, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=3),
    "Venezuela":dict(ano_fundacion=1926, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),

    # --- UEFA ---
    "Noruega":         dict(ano_fundacion=1902, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=3),
    "Turquía":         dict(ano_fundacion=1923, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=2),
    "Suiza":           dict(ano_fundacion=1895, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=12),
    "Dinamarca":       dict(ano_fundacion=1889, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=6),
    "Austria":         dict(ano_fundacion=1904, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=7),
    "Serbia":          dict(ano_fundacion=1919, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=3),
    "Escocia":         dict(ano_fundacion=1873, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=8),
    "Ucrania":         dict(ano_fundacion=1991, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Grecia":          dict(ano_fundacion=1926, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=3),
    "Polonia":         dict(ano_fundacion=1919, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=9),
    "República Checa": dict(ano_fundacion=1901, mundiales_ganados=0, finales_mundial=2, copas_continentales=1, apariciones_mundial=9),
    "Suecia":          dict(ano_fundacion=1904, mundiales_ganados=0, finales_mundial=1, copas_continentales=0, apariciones_mundial=12),
    "Hungría":         dict(ano_fundacion=1901, mundiales_ganados=0, finales_mundial=2, copas_continentales=0, apariciones_mundial=9),
    "Eslovenia":       dict(ano_fundacion=1920, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=2),
    "Irlanda":         dict(ano_fundacion=1921, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=3),
    "Israel":          dict(ano_fundacion=1928, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=1),
    "Rumanía":         dict(ano_fundacion=1909, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=7),
    "Eslovaquia":      dict(ano_fundacion=1938, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Albania":         dict(ano_fundacion=1930, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Georgia":         dict(ano_fundacion=1990, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Finlandia":       dict(ano_fundacion=1907, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Bulgaria":        dict(ano_fundacion=1923, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=7),
    "Islandia":        dict(ano_fundacion=1947, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Irlanda del Norte": dict(ano_fundacion=1880, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=3),

    # --- CAF ---
    "Senegal":         dict(ano_fundacion=1960, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=3),
    "Nigeria":         dict(ano_fundacion=1945, mundiales_ganados=0, finales_mundial=0, copas_continentales=3, apariciones_mundial=6),
    "Argelia":         dict(ano_fundacion=1962, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=4),
    "Egipto":          dict(ano_fundacion=1921, mundiales_ganados=0, finales_mundial=0, copas_continentales=7, apariciones_mundial=3),
    "Costa de Marfil": dict(ano_fundacion=1960, mundiales_ganados=0, finales_mundial=0, copas_continentales=3, apariciones_mundial=3),
    "RD del Congo":    dict(ano_fundacion=1919, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=1),
    "Túnez":           dict(ano_fundacion=1957, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=6),
    "Camerún":         dict(ano_fundacion=1959, mundiales_ganados=0, finales_mundial=0, copas_continentales=5, apariciones_mundial=8),
    "Malí":            dict(ano_fundacion=1960, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Sudáfrica":       dict(ano_fundacion=1991, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=3),
    "Ghana":           dict(ano_fundacion=1957, mundiales_ganados=0, finales_mundial=0, copas_continentales=4, apariciones_mundial=4),
    "Cabo Verde":      dict(ano_fundacion=1982, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),

    # --- CONCACAF ---
    "Canadá":      dict(ano_fundacion=1912, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=2),
    "Panamá":      dict(ano_fundacion=1937, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Costa Rica":  dict(ano_fundacion=1921, mundiales_ganados=0, finales_mundial=0, copas_continentales=3, apariciones_mundial=6),
    "Honduras":    dict(ano_fundacion=1951, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=3),
    "Jamaica":     dict(ano_fundacion=1910, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Haití":       dict(ano_fundacion=1904, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Curazao":     dict(ano_fundacion=1921, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "El Salvador": dict(ano_fundacion=1935, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=2),

    # --- AFC ---
    "Japón":               dict(ano_fundacion=1921, mundiales_ganados=0, finales_mundial=0, copas_continentales=4, apariciones_mundial=7),
    "Corea del Sur":       dict(ano_fundacion=1928, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=11),
    "Irán":                dict(ano_fundacion=1920, mundiales_ganados=0, finales_mundial=0, copas_continentales=3, apariciones_mundial=6),
    "Australia":           dict(ano_fundacion=1961, mundiales_ganados=0, finales_mundial=0, copas_continentales=5, apariciones_mundial=6),
    "Uzbekistán":          dict(ano_fundacion=1946, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Jordania":            dict(ano_fundacion=1949, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Irak":                dict(ano_fundacion=1948, mundiales_ganados=0, finales_mundial=0, copas_continentales=1, apariciones_mundial=1),
    "Arabia Saudita":      dict(ano_fundacion=1956, mundiales_ganados=0, finales_mundial=0, copas_continentales=3, apariciones_mundial=6),
    "Emiratos Árabes Unidos": dict(ano_fundacion=1971, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
    "Omán":                dict(ano_fundacion=1978, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=0),
    "Qatar":               dict(ano_fundacion=1960, mundiales_ganados=0, finales_mundial=0, copas_continentales=2, apariciones_mundial=1),
    "China":               dict(ano_fundacion=1924, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),

    # --- OFC ---
    "Nueva Zelanda": dict(ano_fundacion=1891, mundiales_ganados=0, finales_mundial=0, copas_continentales=5, apariciones_mundial=2),

    # --- UEFA (Balcanes) ---
    "Bosnia y Herzegovina": dict(ano_fundacion=1992, mundiales_ganados=0, finales_mundial=0, copas_continentales=0, apariciones_mundial=1),
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
        "titulos_champions", "titulos_internacionales", "supercopas",
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
