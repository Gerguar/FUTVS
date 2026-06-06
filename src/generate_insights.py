"""
src/generate_insights.py
Genera data/insights.json y data/insights_semana.json a partir de:
  - data/predictions.json  (predicciones + odds de mercado)
  - Supabase               (partidos finalizados, forma, equipos)
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parents[1]
DATA_DIR     = ROOT / "data"
PREDS_PATH   = DATA_DIR / "predictions.json"
OUT_INSIGHTS = DATA_DIR / "insights.json"
OUT_SEMANA   = DATA_DIR / "insights_semana.json"

# ── Supabase ────────────────────────────────────────────────────────────────
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def sb_get(path: str) -> list[dict]:
    if not SB_URL or not SB_KEY:
        print(f"[insights] sin credenciales Supabase, saltando query")
        return []
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Accept": "application/json",
        "Prefer": "count=none",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[insights] sb_get error: {e}")
        print(f"[insights] url intentada: {url[:120]}")
        return []

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_predictions() -> dict:
    if not PREDS_PATH.exists():
        return {"matches": []}
    return json.loads(PREDS_PATH.read_text())

def isoweek(dt: datetime) -> str:
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"

def cutoff_str(days: int) -> str:
    """Fecha ISO sin timezone explícita para que PostgREST no se queje con el +"""
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")

# ── Forma reciente desde Supabase ───────────────────────────────────────────
def build_forma_reciente() -> list[dict]:
    cut = cutoff_str(60)

    # Query simple sin joins embebidos — traemos IDs y goles
    partidos = sb_get(
        f"partidos?select=id,fecha,goles_local,goles_visitante,"
        f"equipo_local_id,equipo_visitante_id"
        f"&estado=eq.finalizado"
        f"&fecha=gte.{cut}"
        f"&order=fecha.desc&limit=300"
    )
    if not partidos:
        return []

    # IDs únicos de equipos presentes
    eq_ids = set()
    for p in partidos:
        if p.get("equipo_local_id"):
            eq_ids.add(p["equipo_local_id"])
        if p.get("equipo_visitante_id"):
            eq_ids.add(p["equipo_visitante_id"])

    if not eq_ids:
        return []

    # Traer datos de equipos en una sola query usando in
    ids_csv = ",".join(str(i) for i in eq_ids)
    equipos_rows = sb_get(
        f"equipos?select=id,nombre,escudo_url&id=in.({ids_csv})"
    )
    equipos = {e["id"]: e for e in equipos_rows}

    # Calcular forma
    teams: dict[int, dict] = {}

    def ensure(tid: int) -> None:
        if tid not in teams:
            eq = equipos.get(tid, {})
            teams[tid] = {
                "id":       tid,
                "nombre":   eq.get("nombre", f"Equipo {tid}"),
                "escudo":   eq.get("escudo_url", ""),
                "gf": 0, "gc": 0,
                "partidos": [],
            }

    for p in partidos:
        gl    = p.get("goles_local")
        gv    = p.get("goles_visitante")
        lid   = p.get("equipo_local_id")
        vid   = p.get("equipo_visitante_id")
        fecha = p.get("fecha", "")
        if gl is None or gv is None or not lid or not vid:
            continue

        ensure(lid)
        ensure(vid)

        rl = "W" if gl > gv else ("D" if gl == gv else "L")
        teams[lid]["gf"] += gl
        teams[lid]["gc"] += gv
        teams[lid]["partidos"].append((fecha, rl))

        rv = "W" if gv > gl else ("D" if gv == gl else "L")
        teams[vid]["gf"] += gv
        teams[vid]["gc"] += gl
        teams[vid]["partidos"].append((fecha, rv))

    result = []
    for t in teams.values():
        sorted_p = sorted(t["partidos"], key=lambda x: x[0], reverse=True)
        forma = [r for _, r in sorted_p[:5]]
        if not forma:
            continue
        result.append({
            "slug":   t["nombre"].lower().replace(" ", "_"),
            "nombre": t["nombre"],
            "escudo": t["escudo"],
            "forma":  forma,
            "gf":     t["gf"],
            "gc":     t["gc"],
        })

    result.sort(key=lambda x: (x["forma"].count("W"), x["gf"] - x["gc"]), reverse=True)
    return result[:20]

# ── xG Performance ───────────────────────────────────────────────────────────
def build_xg_performance(preds: dict) -> list[dict]:
    matches = preds.get("matches", [])
    if not matches:
        return []

    cut = cutoff_str(30)
    finalizados = sb_get(
        f"partidos?select=fecha,goles_local,goles_visitante,"
        f"equipo_local_id,equipo_visitante_id"
        f"&estado=eq.finalizado&fecha=gte.{cut}&limit=100"
    )
    if not finalizados:
        # Sin datos reales, usar xG de próximos partidos como curiosidad
        items = []
        for m in matches[:5]:
            xg = m.get("expected_goals") or {}
            xg_h = xg.get("home", 0) or 0
            if xg_h >= 2.0:
                h_name = (m.get("home") or {}).get("name", "Local")
                comp   = (m.get("competition") or {}).get("name", "")
                items.append({
                    "tipo": "sobre", "flag": "⚡",
                    "texto": f"{h_name} tiene xG proyectado de {xg_h:.1f} en su próximo partido ({comp}) — uno de los más altos de la jornada."
                })
                break
        return items

    # Obtener nombres de equipos
    eq_ids = set()
    for p in finalizados:
        if p.get("equipo_local_id"):    eq_ids.add(p["equipo_local_id"])
        if p.get("equipo_visitante_id"): eq_ids.add(p["equipo_visitante_id"])

    eq_map = {}
    if eq_ids:
        ids_csv = ",".join(str(i) for i in eq_ids)
        eq_rows = sb_get(f"equipos?select=id,nombre&id=in.({ids_csv})")
        eq_map  = {e["id"]: e["nombre"] for e in eq_rows}

    # Índice por (home_lower, away_lower)
    idx: dict[tuple, dict] = {}
    for p in finalizados:
        hn = eq_map.get(p.get("equipo_local_id"), "").lower()
        an = eq_map.get(p.get("equipo_visitante_id"), "").lower()
        if hn and an:
            idx[(hn, an)] = p

    xg_acc: dict[str, list] = defaultdict(list)
    for m in matches:
        h_name = (m.get("home") or {}).get("name", "")
        a_name = (m.get("away") or {}).get("name", "")
        xg = m.get("expected_goals") or {}
        xg_h = xg.get("home")
        xg_a = xg.get("away")
        real = idx.get((h_name.lower(), a_name.lower()))
        if not real or xg_h is None or xg_a is None:
            continue
        gl = real.get("goles_local", 0) or 0
        gv = real.get("goles_visitante", 0) or 0
        xg_acc[h_name].append((xg_h, gl))
        xg_acc[a_name].append((xg_a, gv))

    items = []
    for nombre, datos in xg_acc.items():
        if len(datos) < 2:
            continue
        total_xg  = sum(x for x, _ in datos)
        total_gol = sum(g for _, g in datos)
        diff = total_gol - total_xg
        if abs(diff) < 1.5:
            continue
        tipo  = "sobre" if diff > 0 else "bajo"
        flag  = "🔥" if diff > 0 else "📉"
        texto = (
            f"{nombre} convirtió {total_gol} goles vs {total_xg:.1f} xG esperados "
            f"({'sobreperformando' if diff > 0 else 'rindiendo por debajo'} en {len(datos)} partidos)"
        )
        items.append({"tipo": tipo, "flag": flag, "texto": texto})

    return items[:6]

# ── Alertas ───────────────────────────────────────────────────────────────────
def build_alertas(preds: dict) -> list[dict]:
    matches = preds.get("matches", [])
    alertas = []
    for m in matches:
        probs  = m.get("probabilities") or {}
        market = m.get("market_probabilities") or {}
        if not probs or not market:
            continue
        h_name = (m.get("home") or {}).get("name", "Local")
        a_name = (m.get("away") or {}).get("name", "Visitante")
        comp   = (m.get("competition") or {}).get("name", "")

        for outcome, label in [("home", h_name), ("away", a_name), ("draw", "Empate")]:
            p_mod = (probs.get(outcome) or 0) * 100
            p_mkt = (market.get(outcome) or 0) * 100
            if p_mkt == 0:
                continue
            diff = p_mod - p_mkt
            if diff > 18:
                alertas.append({
                    "nivel": "warning", "flag": "⚠️",
                    "texto": f"Divergencia modelo vs mercado: {label} en {h_name} vs {a_name} ({comp}) — modelo {p_mod:.0f}% vs mercado {p_mkt:.0f}%."
                })
            elif diff < -18:
                alertas.append({
                    "nivel": "info", "flag": "🔍",
                    "texto": f"Mercado sobrevalora a {label} en {h_name} vs {a_name} ({comp}) — modelo {p_mod:.0f}% vs mercado {p_mkt:.0f}%."
                })

        max_p = max(probs.get("home", 0), probs.get("draw", 0), probs.get("away", 0))
        if max_p < 0.38:
            alertas.append({
                "nivel": "info", "flag": "⚖️",
                "texto": f"Partido muy abierto: {h_name} vs {a_name} ({comp}) — ningún resultado supera el 38%."
            })

    seen = set()
    unique = []
    for a in alertas:
        if a["texto"] not in seen:
            seen.add(a["texto"])
            unique.append(a)
    unique.sort(key=lambda x: 0 if x["nivel"] == "warning" else 1)
    return unique[:6]

# ── Tendencias ────────────────────────────────────────────────────────────────
def build_tendencias(preds: dict) -> list[dict]:
    matches = preds.get("matches", [])
    tendencias = []
    over_count = btts_count = total = 0
    high_elo = []

    for m in matches:
        derived  = m.get("derived") or {}
        p_over   = derived.get("p_over_2_5", 0) or 0
        p_btts   = derived.get("p_btts", 0) or 0
        ratings  = m.get("ratings") or {}
        elo_diff = abs(ratings.get("elo_diff", 0) or 0)
        h_name   = (m.get("home") or {}).get("name", "Local")
        a_name   = (m.get("away") or {}).get("name", "Visitante")
        comp     = (m.get("competition") or {}).get("name", "")
        total   += 1
        if p_over > 0.62: over_count += 1
        if p_btts > 0.58: btts_count += 1

        if p_over > 0.70:
            tendencias.append({"tipo": "over", "flag": "🎯",
                "texto": f"{h_name} vs {a_name} ({comp}) — {p_over*100:.0f}% de probabilidad de más de 2.5 goles."})
        if p_btts > 0.68:
            tendencias.append({"tipo": "btts", "flag": "⚽",
                "texto": f"{h_name} vs {a_name} ({comp}) — {p_btts*100:.0f}% de probabilidad de que ambos anoten."})
        if elo_diff > 250:
            favor = h_name if (ratings.get("elo_diff", 0) or 0) > 0 else a_name
            rival = a_name if favor == h_name else h_name
            high_elo.append({"tipo": "dominio", "flag": "💪", "diff": elo_diff,
                "texto": f"{favor} tiene ventaja Elo de {elo_diff:.0f} pts sobre {rival} ({comp})."})

    if total >= 3:
        if over_count / total >= 0.60:
            tendencias.insert(0, {"tipo": "over", "flag": "📈",
                "texto": f"Jornada de goles: {over_count}/{total} partidos con más del 60% de chances de superar 2.5 goles."})
        if btts_count >= max(2, total // 2):
            tendencias.append({"tipo": "btts", "flag": "🔄",
                "texto": f"Tendencia BTTS: en {btts_count}/{total} partidos se espera que ambos equipos anoten."})

    high_elo.sort(key=lambda x: x["diff"], reverse=True)
    for item in high_elo[:2]:
        tendencias.append({k: v for k, v in item.items() if k != "diff"})

    seen = set()
    unique = []
    for t in tendencias:
        if t["texto"] not in seen:
            seen.add(t["texto"])
            unique.append(t)
    return unique[:6]

# ── Oportunidades ─────────────────────────────────────────────────────────────
def build_oportunidades(preds: dict) -> list[dict]:
    matches = preds.get("matches", [])
    opps = []
    for m in matches:
        probs  = m.get("probabilities") or {}
        market = m.get("market_probabilities") or {}
        if not probs or not market:
            continue
        h_name  = (m.get("home") or {}).get("name", "Local")
        a_name  = (m.get("away") or {}).get("name", "Visitante")
        comp    = (m.get("competition") or {}).get("name", "")
        kickoff = m.get("kickoff_ts_utc", "")
        xg      = m.get("expected_goals") or {}

        for outcome, label in [
            ("home",  f"Victoria {h_name}"),
            ("away",  f"Victoria {a_name}"),
            ("draw",  "Empate"),
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
    seen_p = set()
    unique = []
    for o in opps:
        if o["partido"] not in seen_p:
            seen_p.add(o["partido"])
            unique.append(o)
    return unique[:5]

# ── insights_semana.json ──────────────────────────────────────────────────────
def build_semana(opps: list, tendencias: list, alertas: list) -> dict:
    now       = datetime.now(timezone.utc)
    fecha_str = now.date().isoformat()
    noticias  = []

    for o in opps[:3]:
        noticias.append({
            "titulo": f"⚡ Oportunidad vs mercado: {o['apuesta']} en {o['partido']} (+{o['edge']:.0f}pp edge)",
            "fuente": "FutVS Modelo", "fecha": fecha_str, "url": "",
        })
    for t in tendencias[:2]:
        noticias.append({
            "titulo": t["flag"] + " " + t["texto"],
            "fuente": "FutVS Análisis", "fecha": fecha_str, "url": "",
        })
    for a in alertas[:2]:
        noticias.append({
            "titulo": a["flag"] + " " + a["texto"],
            "fuente": "FutVS Modelo", "fecha": fecha_str, "url": "",
        })

    if not noticias:
        noticias.append({
            "titulo": "📊 Sin divergencias significativas esta semana — modelo y mercado alineados.",
            "fuente": "FutVS Modelo", "fecha": fecha_str, "url": "",
        })

    return {"week": isoweek(now), "noticias": noticias}

# ── dato_curioso ──────────────────────────────────────────────────────────────
DATOS_CURIOSOS = [
    "El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico.",
    "El método Dixon-Coles fue publicado en 1997 y sigue siendo una de las bases más sólidas para predicción de fútbol.",
    "Un Elo de 2000 puntos equivale a estar entre los mejores equipos del planeta — el promedio de la Premier League ronda los 1.600.",
    "El xG (goles esperados) fue popularizado en análisis profesional alrededor de 2012 y hoy es estándar en los grandes clubes.",
    "En promedio, el equipo local gana el 46% de los partidos en las ligas top de Europa.",
    "La corrección de Dixon-Coles penaliza resultados 0-0 y 1-0, que son más comunes de lo que Poisson puro predice.",
    "El modelo calibra probabilidades con histórico de 6 temporadas — más de 40.000 minutos de fútbol analizado.",
    "En la Champions League, los equipos de local ganan solo el 38% de los partidos — la ventaja de localía es menor que en ligas domésticas.",
]

def pick_dato_curioso() -> str:
    idx = datetime.now(timezone.utc).isocalendar()[1] % len(DATOS_CURIOSOS)
    return DATOS_CURIOSOS[idx]

# ── Main ──────────────────────────────────────────────────────────────────────
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

    print(
        f"[insights] listo: {len(xg_perf)} xG, {len(alertas)} alertas, "
        f"{len(tendencias)} tendencias, {len(opps)} oportunidades",
        flush=True
    )

if __name__ == "__main__":
    main()
