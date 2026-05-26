"""
Ingesta del ranking Elo de selecciones desde eloratings.net (TSV publico).

eloratings.net mantiene un Elo dinamico desde 1872, calibrado para futbol de
selecciones. Es la fuente mas usada academicamente.

Endpoint publico: https://www.eloratings.net/World.tsv (~30 KB, ~244 selecciones).

Formato TSV (sin headers, columnas observadas):
    0  rank
    1  rank (duplicado)
    2  code (2 letras, ej AR, BR, EN)
    3  elo actual
    ... muchas mas columnas de historico

Guarda en Supabase tabla `selecciones_elo` (slug, code, nombre, elo, ranking).
Solo escribe rows con upsert (merge-duplicates por slug).

Uso:
    python -m src.ingest_elo_selecciones
    python -m src.ingest_elo_selecciones --dry-run
"""
from __future__ import annotations
import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

from .supabase_writer import sb_post


ELO_TSV_URL = "https://www.eloratings.net/World.tsv"

# Mapeo codigo eloratings -> (slug canonico, nombre legible). Cubre los ~70
# paises mas relevantes (todos los del Mundial 2026 + tier 1 de cada confederacion).
# Para codigos no listados, el script usa slug = code.lower() y nombre = code,
# y se puede refinar despues sin perder data.
CODE_MAP: dict[str, tuple[str, str]] = {
    # UEFA
    "ES": ("espana",          "España"),
    "FR": ("francia",         "Francia"),
    "EN": ("inglaterra",      "Inglaterra"),
    "DE": ("alemania",        "Alemania"),
    "IT": ("italia",          "Italia"),
    "PT": ("portugal",        "Portugal"),
    "NL": ("paises_bajos",    "Países Bajos"),
    "BE": ("belgica",         "Bélgica"),
    "HR": ("croacia",         "Croacia"),
    "DK": ("dinamarca",       "Dinamarca"),
    "CH": ("suiza",           "Suiza"),
    "PL": ("polonia",         "Polonia"),
    "AT": ("austria",         "Austria"),
    "TR": ("turquia",         "Turquía"),
    "NO": ("noruega",         "Noruega"),
    "SE": ("suecia",          "Suecia"),
    "CZ": ("republica_checa", "República Checa"),
    "SK": ("eslovaquia",      "Eslovaquia"),
    "RS": ("serbia",          "Serbia"),
    "RO": ("rumania",         "Rumanía"),
    "GR": ("grecia",          "Grecia"),
    "UA": ("ucrania",         "Ucrania"),
    "HU": ("hungria",         "Hungría"),
    "SI": ("eslovenia",       "Eslovenia"),
    "AL": ("albania",         "Albania"),
    "GE": ("georgia",         "Georgia"),
    "FI": ("finlandia",       "Finlandia"),
    "IE": ("irlanda",         "Irlanda"),
    "SQ": ("escocia",         "Escocia"),  # eloratings usa SQ para Scotland (no SC = Saint Kitts)
    "WL": ("gales",           "Gales"),
    "NI": ("irlanda_norte",   "Irlanda del Norte"),
    "IL": ("israel",          "Israel"),
    "BG": ("bulgaria",        "Bulgaria"),
    "IS": ("islandia",        "Islandia"),
    "MK": ("macedonia_norte", "Macedonia del Norte"),
    # CONMEBOL
    "AR": ("argentina",       "Argentina"),
    "BR": ("brasil",          "Brasil"),
    "UY": ("uruguay",         "Uruguay"),
    "CO": ("colombia",        "Colombia"),
    "EC": ("ecuador",         "Ecuador"),
    "PY": ("paraguay",        "Paraguay"),
    "VE": ("venezuela",       "Venezuela"),
    "BO": ("bolivia",         "Bolivia"),
    "PE": ("peru",            "Perú"),
    "CL": ("chile",           "Chile"),
    # CONCACAF
    "US": ("estados_unidos",  "Estados Unidos"),
    "CA": ("canada",          "Canadá"),
    "MX": ("mexico",          "México"),
    "PA": ("panama",          "Panamá"),
    "CR": ("costa_rica",      "Costa Rica"),
    "HN": ("honduras",        "Honduras"),
    "JM": ("jamaica",         "Jamaica"),
    "CW": ("curazao",         "Curazao"),
    "HT": ("haiti",           "Haití"),
    "SV": ("el_salvador",     "El Salvador"),
    # AFC
    "JP": ("japon",           "Japón"),
    "KR": ("corea_sur",       "Corea del Sur"),
    "AU": ("australia",       "Australia"),
    "IR": ("iran",            "Irán"),
    "SA": ("arabia_saudita",  "Arabia Saudita"),
    "IQ": ("irak",            "Irak"),
    "QA": ("qatar",           "Qatar"),
    "UZ": ("uzbekistan",      "Uzbekistán"),
    "JO": ("jordania",        "Jordania"),
    "AE": ("emiratos_arabes", "Emiratos Árabes Unidos"),
    "CN": ("china",           "China"),
    "OM": ("oman",            "Omán"),
    # Balcanes / Europa Este adicionales
    "BA": ("bosnia",          "Bosnia y Herzegovina"),
    # CAF
    "CV": ("cabo_verde",      "Cabo Verde"),
    "CD": ("rdc",             "RD del Congo"),
    "MA": ("marruecos",       "Marruecos"),
    "SN": ("senegal",         "Senegal"),
    "EG": ("egipto",          "Egipto"),
    "DZ": ("argelia",         "Argelia"),
    "GH": ("ghana",           "Ghana"),
    "NG": ("nigeria",         "Nigeria"),
    "CI": ("costa_marfil",    "Costa de Marfil"),
    "TN": ("tunez",           "Túnez"),
    "CM": ("camerun",         "Camerún"),
    "ZA": ("sudafrica",       "Sudáfrica"),
    "ML": ("mali",            "Malí"),
    # OFC
    "NZ": ("nueva_zelanda",   "Nueva Zelanda"),
}


def resolve_code(code: str) -> tuple[str, str]:
    """Devuelve (slug, nombre) para un codigo. Fallback: slug=code.lower(), nombre=code."""
    if code in CODE_MAP:
        return CODE_MAP[code]
    return (code.lower(), code)


def fetch_elo_tsv(url: str = ELO_TSV_URL) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (FutVS)"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_rows(tsv_text: str) -> list[dict]:
    out: list[dict] = []
    seen_slugs: set[str] = set()
    now_iso = datetime.now(timezone.utc).isoformat()
    for line in tsv_text.strip().split("\n"):
        if not line:
            continue
        cols = line.split("\t")
        if len(cols) < 4:
            continue
        try:
            rank = int(cols[0])
            code = cols[2].strip()
            elo = int(cols[3])
        except (ValueError, IndexError):
            continue
        if not code:
            continue
        slug, nombre = resolve_code(code)
        # Evitar duplicados (eloratings empata rankings: dos paises con rank=5 con mismo elo).
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)
        out.append({
            "slug": slug,
            "code": code,
            "nombre": nombre,
            "elo": elo,
            "ranking": rank,
            "ultima_actualizacion": now_iso,
        })
    return out


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true",
                   help="No escribe a Supabase, solo imprime.")
    p.add_argument("--limit", type=int, default=None,
                   help="Cap para debug.")
    args = p.parse_args()

    print(f"[elo] descargando {ELO_TSV_URL}")
    text = fetch_elo_tsv()
    rows = parse_rows(text)
    print(f"[elo] parseadas {len(rows)} selecciones")

    if args.limit:
        rows = rows[: args.limit]

    # Top 10 sanity check
    print()
    print(f"{'Rank':>4s}  {'Code':<4s} {'Slug':<22s} {'Nombre':<22s} {'Elo':>5s}")
    print("-" * 70)
    for r in rows[:10]:
        print(f"{r['ranking']:>4d}  {r['code']:<4s} {r['slug']:<22s} {r['nombre'][:22]:<22s} {r['elo']:>5d}")
    print("...")

    if args.dry_run:
        print()
        print(f"[elo] DRY-RUN: no se escribe Supabase.")
        # Mostrar cuantos quedaron sin mapeo
        unmapped = [r for r in rows if r["nombre"] == r["code"]]
        print(f"[elo] sin nombre en CODE_MAP: {len(unmapped)}")
        if unmapped:
            print("[elo] codigos sin mapeo (primeros 30):")
            for r in unmapped[:30]:
                print(f"      {r['code']} (rank {r['ranking']}, elo {r['elo']})")
        return

    # Upsert por slug. Chunks de 100 para no pasar limits.
    BATCH = 100
    total_saved = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i:i + BATCH]
        try:
            sb_post(
                "selecciones_elo",
                chunk,
                prefer="resolution=merge-duplicates,return=minimal",
            )
            total_saved += len(chunk)
        except Exception as e:
            print(f"  ! error chunk {i}-{i+len(chunk)}: {e}")
    print(f"[elo] guardado en selecciones_elo: {total_saved}/{len(rows)}")


if __name__ == "__main__":
    main()
