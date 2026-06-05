"""
Integra alertas de lesiones/suspensiones de web/data/insights.json en los
pronósticos del Mundial 2026.

Estrategia:
1. Leer web/data/insights.json (cron Claude cada 6h).
2. Para cada alerta tipo `lesion` o `suspension` (excluyendo `info` que suele
   ser positiva como "suspensión revocada"):
   - Buscar nombres de jugadores en el texto (matching por substring de
     nombre completo normalizado, sin acentos).
   - Mapear jugador -> equipo_id de su selección.
3. Si el jugador es titular (rating >= MIN_RATING_TO_AFFECT), aplicar ajuste
   a los próximos partidos de su equipo:
   - nivel=danger/critico: -3 puntos porcentuales al equipo afectado
   - nivel=warning:        -1.5
4. Si una alerta menciona varios jugadores del mismo equipo, los efectos
   se acumulan (capped a -6pp para no romper la distribución).
5. Output: data/wc2026_ajustes_lesiones.json con
   {partido_id: {p_local_delta, p_empate_delta, p_visitante_delta, reasons}}.

Uso:
    python -m src.integrate_lesiones_mundial --dry-run
    python -m src.integrate_lesiones_mundial
"""
from __future__ import annotations
import argparse
import json
import unicodedata
from collections import defaultdict
from pathlib import Path

from .supabase_writer import sb_get


INSIGHTS_PATH = Path("web/data/insights.json")
OUT_PATH = Path("data/wc2026_ajustes_lesiones.json")

MUNDIAL_TEAM_IDS = (
    111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125,
    126, 127, 129, 130, 132, 133, 134, 135, 136, 141, 142, 145, 146, 148, 150,
    151, 153, 160, 161, 162, 168, 173, 178, 181, 187, 189, 192, 194, 196, 198,
    206, 211, 264,
)

# Puntos porcentuales a restar al equipo afectado segun severidad.
LEVEL_PENALTIES = {
    "critico": 3.0,
    "danger":  3.0,
    "warning": 1.5,
}
# Niveles ignorados (positivos / informativos)
IGNORE_LEVELS = {"info"}

# Rating minimo para que un lesionado mueva el modelo. Suplentes con rating <
# este umbral no impactan (no son titulares clave).
MIN_RATING_TO_AFFECT = 78

# Cap por equipo para que el ajuste no destruya la distribucion (ej. 3
# titulares lesionados podrian dar -9pp; limitamos a -6pp).
MAX_PENALTY_PER_TEAM = 6.0

# ─── MATCHER ESTRICTO ─────────────────────────────────────────────
# Despues del incidente del 5-jun-2026 (Cristian Romero y Leandro Paredes
# marcados como bajas por simple mencion en texto ambiguo), exigimos que
# el texto de la alerta contenga al menos una de estas frases para
# considerar que el jugador esta REALMENTE descartado.
# Si solo hay menciones ambiguas ('en duda', 'llega justo'), no penalizamos.
CONFIRMED_PHRASES = (
    "se pierde el mundial",
    "fuera del mundial",
    "queda fuera",
    "descartado del mundial",
    "descartado para el mundial",
    "no llega al mundial",
    "no estara en el mundial",
    "no estara en la cita",
    "no jugara el mundial",
    "rotura de ligamentos",
    "rotura del cruzado",
    "rotura del lca",
    "rotura del menisco",
    "rotura de fibras",
    "rotura muscular grave",
    "operado",
    "intervenido quirurgicamente",
    "baja confirmada",
    "baja por lesion",
    "lesion grave",
    "tres meses de baja",
    "varias semanas de baja",
    "varios meses fuera",
    "fin de temporada",
    "se perdera el torneo",
    "no podra disputar el mundial",
)

# Frases que indican incertidumbre pero NO descarte. No penalizamos por estas
# (era nuestro fallo anterior). Si quisieramos restar muy poco en estos casos,
# se podria sumar -0.5pp como "en duda", pero por ahora ignoramos.
AMBIGUOUS_PHRASES = (
    "llega justo",
    "en duda",
    "escaso ritmo",
    "trabaja por separado",
    "trabajan por separado",
    "molestias",
    "se recupera",
    "se entrena al margen",
    "carga de minutos",
    "preocupa su estado",
    "podria perderse",
    "podria no llegar",
    "duda hasta ultimo momento",
)

# Override manual: si necesitas forzar/vetar un jugador, edita esta lista.
# Cada entrada es {"equipo_id": int, "jugador": str, "delta_pp": float, "razon": str}.
# delta_pp positivo = penalizacion para ESE equipo (resta de su prob de ganar).
# delta_pp 0 = veto explicito (ignorar matches de ese jugador).
MANUAL_OVERRIDES_PATH = Path("data/lesiones_overrides_manual.json")


def has_confirmed_phrase(text_norm: str) -> bool:
    """True si el texto contiene una frase que CONFIRMA descarte del Mundial."""
    return any(p in text_norm for p in CONFIRMED_PHRASES)


def load_manual_overrides() -> dict[tuple[int, str], dict]:
    """{(equipo_id, jugador_normalized): {delta_pp, razon}}.
    Si delta_pp == 0 -> veto: ignorar al jugador aunque aparezca.
    """
    if not MANUAL_OVERRIDES_PATH.exists():
        return {}
    try:
        data = json.loads(MANUAL_OVERRIDES_PATH.read_text(encoding="utf-8"))
        return {(int(o["equipo_id"]), normalize(o["jugador"])): o for o in data}
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"[lesiones] WARN: overrides invalidos: {e}")
        return {}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn")


def normalize(s: str) -> str:
    # Quita acentos, lowercase, reduce guiones a espacios y colapsa espacios.
    out = strip_accents(s or "").lower()
    out = out.replace("-", " ").replace("'", " ").replace("'", " ")
    return " ".join(out.split())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not INSIGHTS_PATH.exists():
        print(f"[lesiones] no existe {INSIGHTS_PATH}")
        return

    insights = json.loads(INSIGHTS_PATH.read_text(encoding="utf-8"))
    alertas = insights.get("alertas", []) or []
    print(f"[lesiones] insights generado: {insights.get('generated_at_utc','?')}")
    print(f"[lesiones] alertas totales: {len(alertas)}")

    # Filtrar a lesion/suspension con nivel relevante
    rel = [a for a in alertas
           if a.get("tipo") in {"lesion", "suspension"}
           and a.get("nivel", "warning") not in IGNORE_LEVELS]
    print(f"[lesiones] relevantes (lesion/suspension excl. info): {len(rel)}")

    if not rel:
        print("[lesiones] nada que integrar")
        if not args.dry_run:
            OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            OUT_PATH.write_text("{}", encoding="utf-8")
        return

    # Cargar todos los jugadores del Mundial (rating >= umbral)
    ids_str = ",".join(map(str, MUNDIAL_TEAM_IDS))
    players = []
    offset = 0
    while True:
        chunk = sb_get(f"jugadores?select=id,nombre,equipo_id,rating"
                       f"&equipo_id=in.({ids_str})&order=equipo_id&limit=1000&offset={offset}")
        players.extend(chunk)
        if len(chunk) < 1000:
            break
        offset += 1000

    titulares = [p for p in players if p["rating"] >= MIN_RATING_TO_AFFECT]
    print(f"[lesiones] titulares clave (rating>={MIN_RATING_TO_AFFECT}): {len(titulares)} de {len(players)}")

    # Index: nombre completo normalizado -> (rating, equipo_id, nombre original)
    # Tambien indexamos el "apellido principal" (ultimos 2 tokens) como fallback
    # para casos como "de Ligt", "van Dijk" donde el texto puede mencionar solo
    # apellido compuesto.
    name_index: list[tuple[str, int, int, str]] = []  # (norm_full, rating, equipo_id, nombre)
    for p in titulares:
        nf = normalize(p["nombre"])
        if not nf or len(nf) < 4:
            continue
        name_index.append((nf, p["rating"], p["equipo_id"], p["nombre"]))

    # Equipos
    eq_rows = sb_get(f"equipos?select=id,nombre&id=in.({ids_str})")
    id_to_nombre = {e["id"]: e["nombre"] for e in eq_rows}

    # Partidos del Mundial programados
    partidos = sb_get(
        "partidos?select=id,fecha,equipo_local_id,equipo_visitante_id"
        "&estado=eq.programado&liga_id=eq.7&order=fecha"
    )
    by_team: dict[int, list[dict]] = defaultdict(list)
    for m in partidos:
        by_team[m["equipo_local_id"]].append(m)
        by_team[m["equipo_visitante_id"]].append(m)

    # Cargar overrides manuales
    overrides = load_manual_overrides()
    if overrides:
        print(f"[lesiones] overrides manuales cargados: {len(overrides)}")

    # Procesar alertas
    print(f"\n[lesiones] procesando alertas:")
    affected_by_team: dict[int, list[tuple[str, float]]] = defaultdict(list)
    for a in rel:
        text_norm = " " + normalize(a.get("texto", "")) + " "
        level = a.get("nivel", "warning")
        penalty = LEVEL_PENALTIES.get(level, 1.5)

        # MATCHER ESTRICTO: solo procesar alertas con frases que confirman
        # descarte. Esto evita los false positives de comentarios ambiguos.
        if not has_confirmed_phrase(text_norm):
            print(f"  [{level:<8}] descartado (sin frase de confirmacion): "
                  f"{a.get('texto','')[:100]}")
            continue

        matches = []
        seen_player_ids = set()
        # Ordenar por longitud descendente: matchea primero los nombres largos
        # para evitar que "Foyth" matchee a "Juan Foyth" doble.
        sorted_index = sorted(name_index, key=lambda x: -len(x[0]))
        for nf, rating, eid, nombre in sorted_index:
            if (eid, nombre) in seen_player_ids:
                continue
            # Match exacto del nombre completo en el texto (con bordes de palabra)
            if f" {nf} " in text_norm:
                matches.append((nombre, eid, rating))
                seen_player_ids.add((eid, nombre))
                continue
            # Apellido compuesto (ultimos 2 tokens) si tiene 3+ tokens
            parts = nf.split()
            if len(parts) >= 3:
                last_two = " ".join(parts[-2:])
                if last_two != nf and f" {last_two} " in text_norm:
                    matches.append((nombre, eid, rating))
                    seen_player_ids.add((eid, nombre))
                    continue
            # Solo apellido (ultimo token) si tiene 2+ tokens, requiere >=5 letras
            if len(parts) >= 2 and len(parts[-1]) >= 5:
                last = parts[-1]
                if f" {last} " in text_norm:
                    matches.append((nombre, eid, rating))
                    seen_player_ids.add((eid, nombre))
                    continue
        if matches:
            for nm, eid, r in matches:
                # Check de override manual: si esta vetado (delta_pp=0), saltear.
                override = overrides.get((eid, normalize(nm)))
                if override is not None:
                    od = float(override.get("delta_pp", 0))
                    if od == 0:
                        print(f"  [{level:<8}] '{nm}' VETADO por override manual")
                        continue
                    print(f"  [{level:<8}] '{nm}' override manual: -{od}pp ({override.get('razon','')})")
                    affected_by_team[eid].append((nm, od))
                else:
                    print(f"  [{level:<8}] '{nm}' (rating {r}, {id_to_nombre.get(eid,'?')}) -> penalty {penalty}%")
                    affected_by_team[eid].append((nm, penalty))
        else:
            print(f"  [{level:<8}] sin match: {a.get('texto','')[:90]}")

    # Agregar overrides manuales que NO esten ya cubiertos por alertas
    # (ej: Facu quiere forzar manualmente una baja que Claude no detecto).
    for (eid, jug_norm), override in overrides.items():
        od = float(override.get("delta_pp", 0))
        if od <= 0:
            continue
        # Si ya esta en affected, no duplicar
        nombre_real = override.get("jugador", jug_norm)
        already = any(normalize(n) == jug_norm for n, _ in affected_by_team.get(eid, []))
        if not already:
            print(f"  [override] '{nombre_real}' ({id_to_nombre.get(eid,'?')}) -> -{od}pp (manual)")
            affected_by_team[eid].append((nombre_real, od))

    # Construir ajustes por partido_id
    ajustes: dict[str, dict] = {}
    for eid, infos in affected_by_team.items():
        total = min(sum(p for _, p in infos), MAX_PENALTY_PER_TEAM)
        nombres = ", ".join(n for n, _ in infos)
        for m in by_team.get(eid, []):
            pid = str(m["id"])
            ent = ajustes.setdefault(pid, {
                "p_local_delta": 0.0, "p_empate_delta": 0.0,
                "p_visitante_delta": 0.0, "reasons": [],
            })
            if eid == m["equipo_local_id"]:
                ent["p_local_delta"] -= total
                ent["p_empate_delta"] += total * 0.5
                ent["p_visitante_delta"] += total * 0.5
                ent["reasons"].append(f"{id_to_nombre.get(eid,'?')} sin {nombres} (-{total:.1f}pp)")
            else:
                ent["p_visitante_delta"] -= total
                ent["p_empate_delta"] += total * 0.5
                ent["p_local_delta"] += total * 0.5
                ent["reasons"].append(f"{id_to_nombre.get(eid,'?')} sin {nombres} (-{total:.1f}pp)")

    # Round
    for ent in ajustes.values():
        for k in ("p_local_delta", "p_empate_delta", "p_visitante_delta"):
            ent[k] = round(ent[k], 2)

    print(f"\n[lesiones] partidos con ajuste: {len(ajustes)}")
    if ajustes:
        for pid, ent in list(ajustes.items())[:10]:
            print(f"  partido {pid}: H{ent['p_local_delta']:+.1f}  D{ent['p_empate_delta']:+.1f}  A{ent['p_visitante_delta']:+.1f}")
            for r in ent["reasons"]:
                print(f"    - {r}")

    if args.dry_run:
        print("\n(dry-run)")
        return

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(ajustes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[lesiones] guardado: {OUT_PATH}")


if __name__ == "__main__":
    main()
