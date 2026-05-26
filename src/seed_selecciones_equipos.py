"""
Toma el TOP N de selecciones_elo y las inserta en `equipos` con liga_id=7
(Selecciones FIFA). Asi quedan disponibles para ser equipo_local/visitante
en partidos del Mundial, eliminatorias, amistosos, etc.

Tambien actualiza las columnas elo_externo, elo_ranking, elo_actualizado_at
en `equipos` para todas las selecciones que insertamos (sync desde
selecciones_elo).

Uso:
    python -m src.seed_selecciones_equipos              # top 80 (default)
    python -m src.seed_selecciones_equipos --top 100
    python -m src.seed_selecciones_equipos --dry-run
"""
from __future__ import annotations
import argparse

from .supabase_writer import sb_get, sb_post, sb_patch


LIGA_SELECCIONES = 7
DEFAULT_TOP = 80

# slug canonico -> codigo ISO2 (o ISO 3166-2 si es region) para flagcdn.com.
# flagcdn URL: https://flagcdn.com/w160/<iso>.png (PNG ancho 160px, retina-ready).
SLUG_TO_ISO: dict[str, str] = {
    "argentina":"ar","brasil":"br","francia":"fr","espana":"es","alemania":"de",
    "italia":"it","portugal":"pt","paises_bajos":"nl","belgica":"be","croacia":"hr",
    "dinamarca":"dk","suiza":"ch","polonia":"pl","austria":"at","turquia":"tr",
    "noruega":"no","suecia":"se","republica_checa":"cz","eslovaquia":"sk","serbia":"rs",
    "rumania":"ro","grecia":"gr","ucrania":"ua","hungria":"hu","eslovenia":"si",
    "albania":"al","georgia":"ge","finlandia":"fi","irlanda":"ie","israel":"il",
    "bulgaria":"bg","islandia":"is","macedonia_norte":"mk","bosnia":"ba",
    # Reino Unido subdivisiones (flagcdn soporta gb-eng, gb-sct, gb-wls, gb-nir)
    "inglaterra":"gb-eng","escocia":"gb-sct","gales":"gb-wls","irlanda_norte":"gb-nir",
    # CONMEBOL
    "uruguay":"uy","colombia":"co","ecuador":"ec","paraguay":"py","venezuela":"ve",
    "bolivia":"bo","peru":"pe","chile":"cl",
    # CONCACAF
    "estados_unidos":"us","canada":"ca","mexico":"mx","panama":"pa","costa_rica":"cr",
    "honduras":"hn","jamaica":"jm","curazao":"cw","haiti":"ht","el_salvador":"sv",
    # AFC
    "japon":"jp","corea_sur":"kr","australia":"au","iran":"ir","arabia_saudita":"sa",
    "irak":"iq","qatar":"qa","uzbekistan":"uz","jordania":"jo","emiratos_arabes":"ae",
    "china":"cn","oman":"om",
    # CAF
    "marruecos":"ma","senegal":"sn","egipto":"eg","argelia":"dz","ghana":"gh",
    "nigeria":"ng","costa_marfil":"ci","tunez":"tn","camerun":"cm","sudafrica":"za",
    "mali":"ml","cabo_verde":"cv","rdc":"cd",
    # OFC
    "nueva_zelanda":"nz",
}

def flag_url(slug: str) -> str | None:
    iso = SLUG_TO_ISO.get(slug)
    if not iso:
        return None
    return f"https://flagcdn.com/w160/{iso}.png"

# Colores oficiales aproximados por slug. Para slugs no listados se usa default gris.
TEAM_COLORS: dict[str, tuple[str, str]] = {
    "argentina":       ("#75AADB", "#FFFFFF"),
    "brasil":          ("#FEDF00", "#009C3B"),
    "francia":         ("#0055A4", "#FFFFFF"),
    "inglaterra":      ("#FFFFFF", "#CE1124"),
    "espana":          ("#AA151B", "#F1BF00"),
    "alemania":        ("#000000", "#DD0000"),
    "italia":          ("#0066CC", "#FFFFFF"),
    "portugal":        ("#006600", "#FF0000"),
    "paises_bajos":    ("#FF6900", "#FFFFFF"),
    "belgica":         ("#000000", "#FAE042"),
    "croacia":         ("#FF0000", "#FFFFFF"),
    "dinamarca":       ("#C8102E", "#FFFFFF"),
    "suiza":           ("#FF0000", "#FFFFFF"),
    "polonia":         ("#DC143C", "#FFFFFF"),
    "austria":         ("#ED2939", "#FFFFFF"),
    "turquia":         ("#E30A17", "#FFFFFF"),
    "noruega":         ("#BA0C2F", "#FFFFFF"),
    "suecia":          ("#006AA7", "#FECC02"),
    "uruguay":         ("#5DADEC", "#FFFFFF"),
    "colombia":        ("#FCD116", "#003893"),
    "ecuador":         ("#FFD100", "#0072CE"),
    "paraguay":        ("#D52B1E", "#0038A8"),
    "venezuela":       ("#7B1F2F", "#FFCC00"),
    "bolivia":         ("#00853F", "#FFD700"),
    "peru":            ("#D91023", "#FFFFFF"),
    "chile":           ("#D52B1E", "#FFFFFF"),
    "estados_unidos":  ("#0A3161", "#B31942"),
    "canada":          ("#FF0000", "#FFFFFF"),
    "mexico":          ("#006847", "#CE1126"),
    "panama":          ("#005AA7", "#D31C2D"),
    "costa_rica":      ("#002B7F", "#CE1126"),
    "honduras":        ("#00BBE6", "#FFFFFF"),
    "jamaica":         ("#009B3A", "#FED100"),
    "curazao":         ("#002B7F", "#F9E300"),
    "japon":           ("#BC002D", "#FFFFFF"),
    "corea_sur":       ("#003478", "#C60C30"),
    "australia":       ("#FFD100", "#006A4E"),
    "iran":            ("#239F40", "#DA0000"),
    "arabia_saudita":  ("#006C35", "#FFFFFF"),
    "irak":            ("#CE1126", "#FFFFFF"),
    "qatar":           ("#8A1538", "#FFFFFF"),
    "uzbekistan":      ("#0099B5", "#1EB53A"),
    "jordania":        ("#000000", "#CE1126"),
    "emiratos_arabes": ("#00732F", "#FF0000"),
    "marruecos":       ("#C1272D", "#006233"),
    "senegal":         ("#00853F", "#FDEF42"),
    "egipto":          ("#CE1126", "#000000"),
    "argelia":         ("#006233", "#D21034"),
    "ghana":           ("#CE1126", "#FCD116"),
    "nigeria":         ("#008751", "#FFFFFF"),
    "costa_marfil":    ("#F77F00", "#009E60"),
    "tunez":           ("#E70013", "#FFFFFF"),
    "camerun":         ("#007A5E", "#CE1126"),
    "sudafrica":       ("#007A4D", "#FFB81C"),
    "nueva_zelanda":   ("#000000", "#FFFFFF"),
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--top", type=int, default=DEFAULT_TOP,
                   help=f"Cuantas selecciones tomar (default {DEFAULT_TOP}).")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # 1. Leer top N de selecciones_elo
    selecciones = sb_get(
        f"selecciones_elo?select=slug,code,nombre,elo,ranking,ultima_actualizacion"
        f"&order=ranking&limit={args.top}"
    )
    print(f"[seed] top {len(selecciones)} de selecciones_elo (ranking 1..{args.top})")

    # 2. Leer equipos existentes en liga 7 para evitar duplicados
    existentes = sb_get(f"equipos?select=id,nombre,abreviacion&liga_id=eq.{LIGA_SELECCIONES}")
    by_name = {e["nombre"]: e for e in existentes}
    print(f"[seed] ya existen {len(existentes)} selecciones en equipos liga_id={LIGA_SELECCIONES}")

    # 3. Upsert: nuevas selecciones -> POST, existentes -> PATCH (solo Elo)
    nuevas: list[dict] = []
    a_actualizar: list[tuple[int, dict]] = []
    for s in selecciones:
        col_p, col_s = TEAM_COLORS.get(s["slug"], ("#1f2937", "#FFFFFF"))
        # Abreviacion: codigo eloratings (2 letras) en mayuscula, o las primeras 3 del nombre.
        abrev = s["code"][:3].upper() if s["code"] else s["nombre"][:3].upper()
        payload = {
            "nombre": s["nombre"],
            "abreviacion": abrev,
            "liga_id": LIGA_SELECCIONES,
            "pais": "Internacional",
            "color_prim": col_p,
            "color_sec": col_s,
            "escudo_url": flag_url(s["slug"]),  # bandera del pais via flagcdn.com
            "elo_externo": s["elo"],
            "elo_ranking": s["ranking"],
            "elo_actualizado_at": s["ultima_actualizacion"],
        }
        if s["nombre"] in by_name:
            a_actualizar.append((by_name[s["nombre"]]["id"], payload))
        else:
            nuevas.append(payload)

    print(f"[seed] nuevas: {len(nuevas)} | a actualizar: {len(a_actualizar)}")

    if args.dry_run:
        print()
        print("Primeras 10 nuevas:")
        for n in nuevas[:10]:
            print(f"  + {n['nombre']:<22s} [{n['abreviacion']}] elo={n['elo_externo']} rank={n['elo_ranking']}")
        if a_actualizar:
            print()
            print("Primeras 10 a actualizar:")
            for eid, n in a_actualizar[:10]:
                print(f"  ~ id={eid} {n['nombre']:<22s} elo={n['elo_externo']} rank={n['elo_ranking']}")
        return

    # Insert nuevas (chunks 50)
    BATCH = 50
    inserted = 0
    for i in range(0, len(nuevas), BATCH):
        chunk = nuevas[i:i + BATCH]
        try:
            sb_post("equipos", chunk, prefer="return=minimal")
            inserted += len(chunk)
        except Exception as e:
            print(f"  ! error insert chunk {i}: {e}")
    print(f"[seed] insertadas {inserted} selecciones en equipos")

    # Patch existentes (Elo + bandera si no estaba)
    patched = 0
    for eid, payload in a_actualizar:
        patch_data = {
            "elo_externo": payload["elo_externo"],
            "elo_ranking": payload["elo_ranking"],
            "elo_actualizado_at": payload["elo_actualizado_at"],
        }
        if payload.get("escudo_url"):
            patch_data["escudo_url"] = payload["escudo_url"]
        try:
            sb_patch(f"equipos?id=eq.{eid}", patch_data)
            patched += 1
        except Exception as e:
            print(f"  ! error patch id={eid}: {e}")
    print(f"[seed] actualizado Elo+bandera en {patched} selecciones ya existentes")


if __name__ == "__main__":
    main()
