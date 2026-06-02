"""
Paso 5: Predice los 72 partidos programados del Mundial 2026 y los guarda en
`pronosticos`.

Modelo (MVP):
  P(H/D/A) = 0.55 * P_dixon_coles + 0.30 * P_elo + 0.15 * P_plantilla

donde:
  - P_dixon_coles: probabilidades del DC entrenado para selecciones
    (paso 3, data/dc_state_selecciones.json) con is_neutral=True.
  - P_elo: derivado del Elo en selecciones_elo via formula clasica:
        p_h = 1 / (1 + 10^((elo_a - elo_h) / 400))
        p_a = 1 - p_h
        p_d = base_draw * (1 - 2 * |0.5 - p_h|)  con base_draw=0.30
        (renormalizado a sumar 1)
  - P_plantilla: refleja la diferencia de calidad de plantilla
        (top_xi_avg de team_ratings.json). Sigmoidal centrada en 0:
        p_h_plantilla = sigmoid(diff_xi / 4)

Factores (para que el frontend muestre la composicion):
  - factor_localidad: 0 (todos los partidos del Mundial son neutrales).
  - factor_forma:     boost ratings de plantilla (0-10).
  - factor_h2h:       reservado, 0 por ahora (sin H2H estructurado por dia).
  - factor_tabla:     reservado, 0 (no aplica en fase de grupos).
  - factor_bajas:     reservado, 0 (paso futuro con lesiones).
  - factor_goles:     atk_diff entre selecciones (paso 2).

Uso:
    python -m src.predict_mundial --dry-run
    python -m src.predict_mundial
"""
from __future__ import annotations
import argparse
import json
import math
import os
import urllib.request
from dataclasses import asdict
from pathlib import Path

from .dixon_coles import DixonColesState
from .supabase_writer import sb_get, sb_post, _sb_url, _headers
from .team_normalize import canonical


DC_PATH = Path("data/dc_state_selecciones.json")
TEAM_RATINGS_PATH = Path("data/team_ratings.json")
MARKET_ODDS_PATH = Path("data/wc2026_market_odds.json")

# Pesos cuando hay cuotas de mercado (Pinnacle) para el partido.
# Mercado pesa fuerte porque integra info que el modelo no ve (forma, lesiones, motivacion).
W_DC_M, W_ELO_M, W_PLANT_M, W_MKT = 0.35, 0.20, 0.10, 0.35
# Pesos cuando NO hay mercado (fallback original).
W_DC, W_ELO, W_PLANTILLA = 0.55, 0.30, 0.15
BASE_DRAW = 0.30  # baseline para empates antes de ajustar por brecha de favoritismo


def load_dc_selecciones() -> DixonColesState:
    d = json.loads(DC_PATH.read_text(encoding="utf-8"))
    # Las claves del JSON son ints serializados como strings, hay que castear.
    d["attack"] = {int(k): v for k, v in d["attack"].items()}
    d["defence"] = {int(k): v for k, v in d["defence"].items()}
    d["teams"] = [int(t) for t in d["teams"]]
    return DixonColesState(**d)


def elo_probs(elo_h: float, elo_a: float) -> tuple[float, float, float]:
    """P(H), P(D), P(A) desde Elo (campo neutral). base_draw modulado por brecha."""
    p_h_raw = 1.0 / (1 + 10 ** ((elo_a - elo_h) / 400))
    p_a_raw = 1.0 - p_h_raw
    gap = abs(0.5 - p_h_raw) * 2.0   # 0 = parejo, 1 = paliza segura
    p_d = BASE_DRAW * (1.0 - gap * 0.6)  # menos empates cuando es paliza
    # Renormalizar
    p_h = p_h_raw * (1.0 - p_d)
    p_a = p_a_raw * (1.0 - p_d)
    s = p_h + p_d + p_a
    return p_h / s, p_d / s, p_a / s


def plantilla_probs(top_xi_h: float | None, top_xi_a: float | None) -> tuple[float, float, float]:
    """Probabilidades H/D/A a partir del diff de XI promedio."""
    if top_xi_h is None or top_xi_a is None:
        return 0.40, 0.20, 0.40  # neutro si no hay datos
    diff = top_xi_h - top_xi_a
    p_h = 1.0 / (1.0 + math.exp(-diff / 4.0))
    p_a = 1.0 - p_h
    gap = abs(0.5 - p_h) * 2.0
    p_d = BASE_DRAW * (1.0 - gap * 0.5)
    p_h_n = p_h * (1.0 - p_d)
    p_a_n = p_a * (1.0 - p_d)
    s = p_h_n + p_d + p_a_n
    return p_h_n / s, p_d / s, p_a_n / s


def patch_partido_pronostico(partido_id: int, payload: dict) -> None:
    """Upsert por partido_id: borra existente y crea. Idempotente."""
    # Borrar pronostico existente del partido (si lo hay)
    del_req = urllib.request.Request(
        f"{_sb_url()}/rest/v1/pronosticos?partido_id=eq.{partido_id}",
        headers=_headers({"Prefer": "return=minimal"}),
        method="DELETE",
    )
    try:
        urllib.request.urlopen(del_req, timeout=20).read()
    except urllib.error.HTTPError as e:
        if e.code not in (200, 204, 404):
            raise
    # Insertar nuevo
    sb_post("pronosticos", [payload], prefer="return=minimal")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    # 1. Cargar DC selecciones
    dc = load_dc_selecciones()
    print(f"[predict-mundial] DC selecciones: {len(dc.teams)} selecciones entrenadas, "
          f"home_adv={dc.home_adv:.3f}")

    # 2. Cargar team_ratings (incluye 48 mundiales por slug canonical)
    team_ratings = json.loads(TEAM_RATINGS_PATH.read_text(encoding="utf-8"))
    print(f"[predict-mundial] team_ratings: {len(team_ratings)} equipos")

    # 3. Elo desde Supabase (por slug)
    elo_rows = sb_get("selecciones_elo?select=slug,elo")
    elo_by_slug = {r["slug"]: r["elo"] for r in elo_rows}
    print(f"[predict-mundial] elo: {len(elo_by_slug)} selecciones")

    # 3b. Cuotas del mercado (Pinnacle) si las generamos
    market_odds: dict[str, dict] = {}
    if MARKET_ODDS_PATH.exists():
        market_odds = json.loads(MARKET_ODDS_PATH.read_text(encoding="utf-8"))
        print(f"[predict-mundial] market_odds: {len(market_odds)} partidos con cuotas")
    else:
        print(f"[predict-mundial] market_odds: sin archivo (correr ingest_pinnacle_wc primero)")

    # 4. Equipos (id -> nombre, slug)
    eq = sb_get("equipos?select=id,nombre&liga_id=eq.7")
    id_to_nombre = {e["id"]: e["nombre"] for e in eq}
    id_to_slug = {e["id"]: canonical(e["nombre"]) for e in eq}

    # 5. Partidos programados de selecciones (liga 7)
    partidos = sb_get(
        "partidos?select=id,fecha,equipo_local_id,equipo_visitante_id,liga_id"
        "&estado=eq.programado&liga_id=eq.7&order=fecha"
    )
    print(f"[predict-mundial] partidos programados de selecciones: {len(partidos)}\n")

    payloads = []
    skipped: list[tuple[str, str, str]] = []
    for m in partidos:
        h_id = m["equipo_local_id"]
        a_id = m["equipo_visitante_id"]
        h_name = id_to_nombre.get(h_id, f"?{h_id}")
        a_name = id_to_nombre.get(a_id, f"?{a_id}")
        h_slug = id_to_slug.get(h_id, "")
        a_slug = id_to_slug.get(a_id, "")

        # DC (neutral)
        if h_id in dc.attack and a_id in dc.attack:
            dc_probs = dc.probs_1x2(h_id, a_id, is_neutral=True)
            p_h_dc, p_d_dc, p_a_dc = dc_probs["H"], dc_probs["D"], dc_probs["A"]
        else:
            skipped.append((h_name, a_name, "no_dc"))
            p_h_dc = p_d_dc = p_a_dc = 1/3

        # Elo
        elo_h = elo_by_slug.get(h_slug)
        elo_a = elo_by_slug.get(a_slug)
        if elo_h is not None and elo_a is not None:
            p_h_elo, p_d_elo, p_a_elo = elo_probs(elo_h, elo_a)
        else:
            p_h_elo = p_d_elo = p_a_elo = 1/3

        # Plantilla
        tr_h = team_ratings.get(h_slug, {})
        tr_a = team_ratings.get(a_slug, {})
        xi_h = tr_h.get("top_xi_avg")
        xi_a = tr_a.get("top_xi_avg")
        p_h_pl, p_d_pl, p_a_pl = plantilla_probs(xi_h, xi_a)

        # Mercado (Pinnacle) si hay
        mk = market_odds.get(str(m["id"]))
        if mk:
            p_h_mk = mk["p_market_home"]
            p_d_mk = mk["p_market_draw"]
            p_a_mk = mk["p_market_away"]
            p_h = W_DC_M*p_h_dc + W_ELO_M*p_h_elo + W_PLANT_M*p_h_pl + W_MKT*p_h_mk
            p_d = W_DC_M*p_d_dc + W_ELO_M*p_d_elo + W_PLANT_M*p_d_pl + W_MKT*p_d_mk
            p_a = W_DC_M*p_a_dc + W_ELO_M*p_a_elo + W_PLANT_M*p_a_pl + W_MKT*p_a_mk
            mix_label = f"4-fuentes (peso mercado={W_MKT:.2f})"
        else:
            p_h = W_DC*p_h_dc + W_ELO*p_h_elo + W_PLANTILLA*p_h_pl
            p_d = W_DC*p_d_dc + W_ELO*p_d_elo + W_PLANTILLA*p_d_pl
            p_a = W_DC*p_a_dc + W_ELO*p_a_elo + W_PLANTILLA*p_a_pl
            mix_label = "3-fuentes (sin mercado)"
        s = p_h + p_d + p_a
        p_h, p_d, p_a = p_h/s, p_d/s, p_a/s

        # Factores (porcentajes 0-100 que el frontend muestra)
        elo_diff = (elo_h - elo_a) if (elo_h is not None and elo_a is not None) else 0
        xi_diff = ((xi_h or 0) - (xi_a or 0))
        atk_h = tr_h.get("attack_score") or 0
        atk_a = tr_a.get("attack_score") or 0
        dfn_h = tr_h.get("defense_score") or 0
        dfn_a = tr_a.get("defense_score") or 0

        notas_parts = [
            f"DC: {p_h_dc:.0%}/{p_d_dc:.0%}/{p_a_dc:.0%}",
            f"Elo: {p_h_elo:.0%}/{p_d_elo:.0%}/{p_a_elo:.0%} (Δ{elo_diff:+.0f})",
            f"Plantilla: {p_h_pl:.0%}/{p_d_pl:.0%}/{p_a_pl:.0%} (XIΔ{xi_diff:+.1f})",
        ]
        if mk:
            notas_parts.append(
                f"Mercado: {mk['p_market_home']:.0%}/{mk['p_market_draw']:.0%}/{mk['p_market_away']:.0%}"
            )
        notas_parts.append("Campo neutral.")
        notas = ". ".join(notas_parts)

        payload = {
            "partido_id": m["id"],
            "prob_local":     round(p_h * 100, 1),
            "prob_empate":    round(p_d * 100, 1),
            "prob_visitante": round(p_a * 100, 1),
            "factor_localidad": 0,             # neutral
            "factor_forma":     round(xi_diff, 1),  # diff de XI
            "factor_h2h":       0,             # reservado
            "factor_tabla":     0,             # no aplica fase grupos
            "factor_bajas":     0,             # reservado (paso futuro)
            "factor_goles":     round(atk_h - atk_a, 1),  # diff de ataque
            "notas": notas,
        }
        payloads.append((m["id"], h_name, a_name, payload))

    # Reporte
    print(f"[predict-mundial] payloads listos: {len(payloads)}")
    if skipped:
        print(f"[predict-mundial] avisos (sin DC entrenado): {skipped}")
    print(f"\nMuestra (primeros 10):")
    for pid, h, a, pl in payloads[:10]:
        print(f"  {h:<14} {pl['prob_local']:>5.1f} / {pl['prob_empate']:>5.1f} / "
              f"{pl['prob_visitante']:>5.1f} {a:<14}")

    if args.dry_run:
        print("\n(dry-run)")
        return

    print(f"\n[predict-mundial] guardando {len(payloads)} pronosticos...")
    ok = 0
    for pid, h, a, payload in payloads:
        try:
            patch_partido_pronostico(pid, payload)
            ok += 1
        except Exception as e:
            print(f"  ! {h} vs {a}: {e}")
    print(f"[predict-mundial] OK: {ok}/{len(payloads)}")


if __name__ == "__main__":
    main()
