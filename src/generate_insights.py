"""
src/generate_insights.py
Genera data/insights.json y data/insights_semana.json a partir de:
  - data/predictions.json  (predicciones + odds de mercado)
  - Supabase               (partidos finalizados, forma, equipos)

Formato de salida para insights.json:
{
  "generated_at_utc": "...",
  "dato_curioso": "...",
  "forma_reciente": [ { "slug": "...", "nombre": "...", "escudo": "...",
                        "forma": ["W","D","L",...], "gf": 5, "gc": 3 } ],
  "xg_performance": [ { "tipo": "sobre"|"bajo", "flag": "🔥", "texto": "..." } ],
  "alertas": [ { "nivel": "warning"|"info", "flag": "⚠️", "texto": "..." } ],
  "tendencias": [ { "tipo": "over"|"cs"|"other", "flag": "🎯", "texto": "..." } ],
  "oportunidades": [ { "partido": "...", "competition": "...", "apuesta": "...",
                        "p_modelo": 62, "p_mercado": 45, "edge": 17,
                        "xg_home": 1.8, "xg_away": 0.9, "kickoff": "..." } ]
}

Formato de salida para insights_semana.json:
{
  "week": "2026-W23",
  "noticias": [ { "titulo": "...", "fuente": "FutVS Model", "fecha": "...", "url": "" } ]
}
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).resolve().parents[1]
DATA_DIR    = ROOT / "data"
PREDS_PATH  = DATA_DIR / "predictions.json"
OUT_INSIGHTS = DATA_DIR / "insights.json"
OUT_SEMANA   = DATA_DIR / "insights_semana.json"

# ── Supabase ────────────────────────────────────────────────────────────────
SB_URL  = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY  = os.environ.get("SUPABASE_SERVICE_KEY", "")

def sb_get(path: str) -> list[dict]:
    if not SB_URL or not SB_KEY:
        return []
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[insights] sb_get error ({path}): {e}")
        return []

# ── Helpers ─────────────────────────────────────────────────────────────────
def load_predictions() -> dict:
    if not PREDS_PATH.exists():
        return {"matches": []}
    return json.loads(PREDS_PATH.read_text())

def isoweek(dt: datetime) -> str:
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"

# ── Forma reciente desde Supabase ───────────────────────────────────────────
def build_forma_reciente() -> list[dict]:
    """
    Consulta partidos finalizados de los últimos 60 días + equipos,
    calcula W/D/L, goles a favor/en contra por equipo.
    Devuelve lista ordenada por diferencia de goles desc.
    """
    # Partidos finalizados recientes con equipos
    cutoff = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    rows = sb_get(
        "partidos?select=id,fecha,goles_local,goles_visitante,"
        "equipo_local:equipo_local_id(id,nombre,escudo_url),"
        "equipo_visitante:equipo_visitante_id(id,nombre,escudo_url)"
        f"&estado=eq.finalizado&fecha=gte.{cutoff}&order=fecha.desc&limit=200"
    )

    teams: dict[int, dict] = {}  # id -> {nombre, escudo, gf, gc, forma}

    def ensure(eq: dict) -> None:
        tid = eq["id"]
        if tid not in teams:
            teams[tid] = {
                "id": tid,
                "nombre": eq.get("nombre", ""),
                "escudo": eq.get("escudo_url", ""),
                "gf": 0, "gc": 0,
                "partidos": [],  # list of (fecha, resultado)
            }

    for p in rows:
        gl  = p.get("goles_local")
        gv  = p.get("goles_visitante")
        eql = p.get("equipo_local")
        eqv = p.get("equipo_visitante")
        fecha = p.get("fecha", "")

        if gl is None or gv is None or not eql or not eqv:
            continue

        ensure(eql)
        ensure(eqv)

        # Local
        rl = "W" if gl > gv else ("D" if gl == gv else "L")
        teams[eql["id"]]["gf"] += gl
        teams[eql["id"]]["gc"] += gv
        teams[eql["id"]]["partidos"].append((fecha, rl))

        # Visitante
        rv = "W" if gv > gl else ("D" if gv == gl else "L")
        teams[eqv["id"]]["gf"] += gv
        teams[eqv["id"]]["gc"] += gl
        teams[eqv["id"]]["partidos"].append((fecha, rv))

    result = []
    for t in teams.values():
        # Ordenar por fecha desc, tomar últimos 5
        sorted_p = sorted(t["partidos"], key=lambda x: x[0], reverse=True)
        forma = [r for _, r in sorted_p[:5]]
        result.append({
            "slug":   t["nombre"].lower().replace(" ", "_"),
            "nombre": t["nombre"],
            "escudo": t["escudo"],
            "forma":  forma,
            "gf":     t["gf"],
            "gc":     t["gc"],
        })

    # Ordenar: primero por forma (más W), luego por diferencia
    result.sort(key=lambda x: (x["forma"].count("W"), x["gf"] - x["gc"]), reverse=True)
    return result[:20]  # top 20 equipos

# ── xG Performance ──────────────────────────────────────────────────────────
def build_xg_performance(preds: dict) -> list[dict]:
    """
    Compara goles_local/visitante reales (Supabase) con xG esperado (predictions.json).
    Solo para partidos ya finalizados que aparecían en el JSON.
    """
    matches = preds.get("matches", [])
    if not matches:
        return []

    # Partidos finalizados recientes desde Supabase con nombres de equipo
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    finalizados = sb_get(
        "partidos?select=fecha,goles_local,goles_visitante,"
        "equipo_local:equipo_local_id(nombre),"
        "equipo_visitante:equipo_visitante_id(nombre)"
        f"&estado=eq.finalizado&fecha=gte.{cutoff}&limit=100"
    )

    # Índice por (home_name_lower, away_name_lower)
    idx: dict[tuple, dict] = {}
    for p in finalizados:
        eql = (p.get("equipo_local") or {}).get("nombre", "").lower()
        eqv = (p.get("equipo_visitante") or {}).get("nombre", "").lower()
        if eql and eqv:
            idx[(eql, eqv)] = p

    items = []
    # Acumuladores por equipo: xG total vs goles reales
    xg_acc: dict[str, list] = defaultdict(list)  # nombre -> list of (xg, goles_reales)

    for m in matches:
        home_name = (m.get("home") or {}).get("name", "").lower()
        away_name = (m.get("away") or {}).get("name", "").lower()
        xg = m.get("expected_goals") or {}
        xg_h = xg.get("home")
        xg_a = xg.get("away")

        real = idx.get((home_name, away_name))
        if not real or xg_h is None or xg_a is None:
            continue

        gl = real.get("goles_local", 0) or 0
        gv = real.get("goles_visitante", 0) or 0

        h_name = (m.get("home") or {}).get("name", home_name.title())
        a_name = (m.get("away") or {}).get("name", away_name.title())

        xg_acc[h_name].append((xg_h, gl))
        xg_acc[a_name].append((xg_a, gv))

    # Generar insights de xG
    for nombre, datos in xg_acc.items():
        if len(datos) < 2:
            continue
        total_xg  = sum(x for x, _ in datos)
        total_gol = sum(g for _, g in datos)
        diff = total_gol - total_xg
        if abs(diff) < 1.5:
            continue  # diferencia no significativa
        tipo = "sobre" if diff > 0 else "bajo"
        flag = "🔥" if diff > 0 else "📉"
        texto = (
            f"{nombre} convirtió {total_gol} goles vs {total_xg:.1f} xG esperados "
            f"({'sobreperformando' if diff > 0 else 'rindiendo por debajo'} en {len(datos)} partidos)"
        )
        items.append({"tipo": tipo, "flag": flag, "texto": texto})

    # Si no hay datos de partidos finalizados cruzados, usar solo los próximos
    if not items:
        # Equipos con xG muy alto en próximos partidos como curiosidad
        for m in matches[:5]:
            xg = m.get("expected_goals") or {}
            xg_h = xg.get("home", 0) or 0
            xg_a = xg.get("away", 0) or 0
            if xg_h >= 2.0:
                h_name = (m.get("home") or {}).get("name", "Local")
                items.append({
                    "tipo": "sobre",
                    "flag": "⚡",
                    "texto": f"{h_name} tiene xG proyectado de {xg_h:.1f} en su próximo partido — uno de los más altos de la jornada."
                })
                break

    return items[:6]

# ── Alertas del modelo ───────────────────────────────────────────────────────
def build_alertas(preds: dict) -> list[dict]:
    """
    Detecta partidos donde la prob del modelo difiere mucho del mercado (>15pp).
    También alerta sobre partidos con incertidumbre muy alta (empate favorito).
    """
    matches = preds.get("matches", [])
    alertas = []

    for m in matches:
        probs   = m.get("probabilities") or {}
        market  = m.get("market_probabilities") or {}
        if not probs or not market:
            continue

        h_name = (m.get("home") or {}).get("name", "Local")
        a_name = (m.get("away") or {}).get("name", "Visitante")
        comp   = (m.get("competition") or {}).get("name", "")
        kickoff = m.get("kickoff_ts_utc", "")

        for outcome, label in [("home", h_name), ("away", a_name), ("draw", "Empate")]:
            p_mod = (probs.get(outcome) or 0) * 100
            p_mkt = (market.get(outcome) or 0) * 100
            if p_mkt == 0:
                continue
            diff = p_mod - p_mkt
            if diff > 18:
                alertas.append({
                    "nivel": "warning",
                    "flag": "⚠️",
                    "texto": (
                        f"Divergencia modelo vs mercado: {label} en {h_name} vs {a_name} "
                        f"({comp}) — modelo le da {p_mod:.0f}% pero el mercado solo {p_mkt:.0f}%."
                    )
                })
            elif diff < -18:
                alertas.append({
                    "nivel": "info",
                    "flag": "🔍",
                    "texto": (
                        f"Mercado sobrevalora a {label} en {h_name} vs {a_name} "
                        f"({comp}) — modelo {p_mod:.0f}% vs mercado {p_mkt:.0f}%."
                    )
                })

        # Alerta: partido muy equilibrado (max prob < 40%)
        max_p = max(probs.get("home", 0), probs.get("draw", 0), probs.get("away", 0))
        if max_p < 0.38:
            alertas.append({
                "nivel": "info",
                "flag": "⚖️",
                "texto": f"Partido muy abierto: {h_name} vs {a_name} ({comp}) — ningún resultado supera el 38% de probabilidad."
            })

    # Limitar y deduplicar
    seen = set()
    unique = []
    for a in alertas:
        if a["texto"] not in seen:
            seen.add(a["texto"])
            unique.append(a)

    # Priorizar warnings sobre infos
    unique.sort(key=lambda x: 0 if x["nivel"] == "warning" else 1)
    return unique[:6]

# ── Tendencias detectadas ────────────────────────────────────────────────────
def build_tendencias(preds: dict) -> list[dict]:
    """
    Detecta tendencias en los próximos partidos:
    - Partidos con p_over_2.5 alta → tendencia de goles
    - Partidos con p_btts alta → ambos anotan
    - Equipos con Elo muy dispar → dominio esperado
    """
    matches = preds.get("matches", [])
    tendencias = []

    over_count  = 0
    btts_count  = 0
    total       = 0

    high_elo_diff = []

    for m in matches:
        derived = m.get("derived") or {}
        p_over  = derived.get("p_over_2_5", 0) or 0
        p_btts  = derived.get("p_btts", 0) or 0
        ratings = m.get("ratings") or {}
        elo_diff = abs(ratings.get("elo_diff", 0) or 0)
        h_name = (m.get("home") or {}).get("name", "Local")
        a_name = (m.get("away") or {}).get("name", "Visitante")
        comp   = (m.get("competition") or {}).get("name", "")

        total += 1
        if p_over > 0.62:
            over_count += 1
        if p_btts > 0.58:
            btts_count += 1

        # Partido individual con over muy alto
        if p_over > 0.70:
            tendencias.append({
                "tipo": "over",
                "flag": "🎯",
                "texto": f"{h_name} vs {a_name} ({comp}) — modelo proyecta {p_over*100:.0f}% de probabilidad de más de 2.5 goles."
            })

        # Partido individual con btts muy alto
        if p_btts > 0.68:
            tendencias.append({
                "tipo": "btts",
                "flag": "⚽",
                "texto": f"{h_name} vs {a_name} ({comp}) — ambos equipos tienen {p_btts*100:.0f}% de probabilidad de anotar."
            })

        # Dominio Elo
        if elo_diff > 250:
            favor  = h_name if (ratings.get("elo_diff", 0) or 0) > 0 else a_name
            rival  = a_name if favor == h_name else h_name
            high_elo_diff.append({
                "tipo": "dominio",
                "flag": "💪",
                "texto": f"{favor} tiene ventaja Elo de {elo_diff:.0f} puntos sobre {rival} ({comp}) — diferencia histórica significativa.",
                "diff": elo_diff,
            })

    # Tendencia global de la jornada
    if total >= 3:
        pct_over = over_count / total
        if pct_over >= 0.60:
            tendencias.insert(0, {
                "tipo": "over",
                "flag": "📈",
                "texto": f"Jornada de goles: {over_count} de {total} partidos analizados tienen más del 60% de probabilidad de superar 2.5 goles."
            })
        if btts_count >= max(2, total // 2):
            tendencias.append({
                "tipo": "btts",
                "flag": "🔄",
                "texto": f"Tendencia BTTS: en {btts_count} de los próximos {total} partidos se espera que ambos equipos anoten."
            })

    # Agregar los de mayor Elo diff
    high_elo_diff.sort(key=lambda x: x["diff"], reverse=True)
    for item in high_elo_diff[:2]:
        tendencias.append({k: v for k, v in item.items() if k != "diff"})

    # Deduplicar
    seen = set()
    unique = []
    for t in tendencias:
        if t["texto"] not in seen:
            seen.add(t["texto"])
            unique.append(t)

    return unique[:6]

# ── Oportunidades del algoritmo ──────────────────────────────────────────────
def build_oportunidades(preds: dict) -> list[dict]:
    """
    Partidos donde el modelo supera al mercado por más de 12pp en algún resultado.
    Ordenados por 'edge' descendente.
    """
    matches = preds.get("matches", [])
    opps = []

    for m in matches:
        probs   = m.get("probabilities") or {}
        market  = m.get("market_probabilities") or {}
        if not probs or not market:
            continue

        h_name  = (m.get("home") or {}).get("name", "Local")
        a_name  = (m.get("away") or {}).get("name", "Visitante")
        comp    = (m.get("competition") or {}).get("name", "")
        kickoff = m.get("kickoff_ts_utc", "")
        xg      = m.get("expected_goals") or {}

        for outcome, label in [
            ("home", f"Victoria {h_name}"),
            ("away", f"Victoria {a_name}"),
            ("draw", "Empate"),
        ]:
            p_mod = (probs.get(outcome) or 0) * 100
            p_mkt = (market.get(outcome) or 0) * 100
            if p_mkt <= 0:
                continue
            edge = p_mod - p_mkt
            if edge < 12:
                continue

            opps.append({
                "partido":     f"{h_name} vs {a_name}",
                "competition": comp,
                "apuesta":     label,
                "p_modelo":    round(p_mod, 1),
                "p_mercado":   round(p_mkt, 1),
                "edge":        round(edge, 1),
                "xg_home":    xg.get("home"),
                "xg_away":    xg.get("away"),
                "kickoff":    kickoff,
            })

    opps.sort(key=lambda x: x["edge"], reverse=True)
    # Un partido puede tener múltiples outcomes — limitar a 1 por partido
    seen_partidos = set()
    unique = []
    for o in opps:
        if o["partido"] not in seen_partidos:
            seen_partidos.add(o["partido"])
            unique.append(o)

    return unique[:5]

# ── insights_semana.json ─────────────────────────────────────────────────────
def build_semana(
    oportunidades: list[dict],
    tendencias: list[dict],
    alertas: list[dict],
) -> dict:
    """
    Genera el JSON liviano que consume el cuadrito del home.
    Incluye un resumen textual de los hallazgos de la semana.
    """
    now = datetime.now(timezone.utc)
    week = isoweek(now)
    fecha_str = now.date().isoformat()

    noticias = []

    # Oportunidades como noticias
    for o in oportunidades[:3]:
        noticias.append({
            "titulo": f"⚡ Oportunidad vs mercado: {o['apuesta']} en {o['partido']} (+{o['edge']:.0f}pp edge)",
            "fuente": "FutVS Modelo",
            "fecha":  fecha_str,
            "url":    "",
        })

    # Tendencias como noticias
    for t in tendencias[:2]:
        noticias.append({
            "titulo": t["flag"] + " " + t["texto"],
            "fuente": "FutVS Análisis",
            "fecha":  fecha_str,
            "url":    "",
        })

    # Alertas como noticias
    for a in alertas[:2]:
        noticias.append({
            "titulo": a["flag"] + " " + a["texto"],
            "fuente": "FutVS Modelo",
            "fecha":  fecha_str,
            "url":    "",
        })

    if not noticias:
        noticias.append({
            "titulo": "📊 Sin divergencias significativas esta semana — el modelo y el mercado están alineados.",
            "fuente": "FutVS Modelo",
            "fecha":  fecha_str,
            "url":    "",
        })

    return {"week": week, "noticias": noticias}

# ── dato_curioso ─────────────────────────────────────────────────────────────
DATOS_CURIOSOS = [
    "El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico.",
    "El método Dixon-Coles fue publicado en 1997 y sigue siendo una de las bases más sólidas para predicción de fútbol.",
    "Un Elo de 2000 puntos equivale a estar entre los mejores equipos del planeta — el promedio de la Premier League ronda los 1.600.",
    "El xG (goles esperados) fue popularizado en análisis profesional alrededor de 2012 y hoy es estándar en los grandes clubes.",
    "En promedio, el equipo local gana el 46% de los partidos en las ligas top de Europa.",
    "La corrección de Dixon-Coles penaliza resultados 0-0 y 1-0, capturando que son más comunes de lo que Poisson predice.",
    "El modelo calibra probabilidades con histórico de 6 temporadas — más de 40.000 minutos de fútbol analizado.",
    "En la Champions League, los equipos de local ganan solo el 38% de los partidos — la ventaja de localía es menor que en ligas domésticas.",
]

def pick_dato_curioso() -> str:
    now = datetime.now(timezone.utc)
    # Rota según la semana del año para que sea consistente durante la semana
    idx = now.isocalendar()[1] % len(DATOS_CURIOSOS)
    return DATOS_CURIOSOS[idx]

# ── Main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    print("[insights] generando insights...", flush=True)
    preds = load_predictions()
    now   = datetime.now(timezone.utc)

    print("[insights] forma reciente desde Supabase...", flush=True)
    forma = build_forma_reciente()
    print(f"[insights] {len(forma)} equipos con forma", flush=True)

    print("[insights] xG performance...", flush=True)
    xg_perf = build_xg_performance(preds)

    print("[insights] alertas...", flush=True)
    alertas = build_alertas(preds)

    print("[insights] tendencias...", flush=True)
    tendencias = build_tendencias(preds)

    print("[insights] oportunidades...", flush=True)
    opps = build_oportunidades(preds)

    insights = {
        "generated_at_utc": now.isoformat(),
        "dato_curioso":     pick_dato_curioso(),
        "forma_reciente":   forma,
        "xg_performance":   xg_perf,
        "alertas":          alertas,
        "tendencias":       tendencias,
        "oportunidades":    opps,
    }

    OUT_INSIGHTS.write_text(json.dumps(insights, indent=2, ensure_ascii=False))
    print(f"[insights] → {OUT_INSIGHTS}", flush=True)

    semana = build_semana(opps, tendencias, alertas)
    OUT_SEMANA.write_text(json.dumps(semana, indent=2, ensure_ascii=False))
    print(f"[insights] → {OUT_SEMANA}", flush=True)

    print(f"[insights] listo: {len(xg_perf)} xG, {len(alertas)} alertas, "
          f"{len(tendencias)} tendencias, {len(opps)} oportunidades", flush=True)


if __name__ == "__main__":
    main()
