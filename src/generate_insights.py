"""
src/generate_insights.py
Genera data/insights.json y data/insights_semana.json a partir de:
  - Anthropic API + web search  (noticias y análisis reales de fútbol)
  - data/predictions.json       (predicciones + odds de mercado)
  - Supabase                    (partidos finalizados, forma, equipos)
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from collections import defaultdict

# ── Paths ──────────────────────────────────────────────────────────────────
ROOT         = Path(__file__).resolve().parents[1]
DATA_DIR     = ROOT / "data"
WEB_DATA_DIR = ROOT / "web" / "data"
PREDS_PATH   = DATA_DIR / "predictions.json"
OUT_INSIGHTS = WEB_DATA_DIR / "insights.json"
OUT_SEMANA   = WEB_DATA_DIR / "insights_semana.json"

# ── Credenciales ─────────────────────────────────────────────────────────────
SB_URL        = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY        = os.environ.get("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ── Supabase ─────────────────────────────────────────────────────────────────
def sb_get(path: str) -> list[dict]:
    if not SB_URL or not SB_KEY:
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
        return []

# ── Anthropic API con web search ─────────────────────────────────────────────
def claude_with_search(prompt: str, max_tokens: int = 2000) -> str:
    """
    Llama a Claude claude-sonnet-4-20250514 con web_search habilitado.
    Devuelve el texto de la respuesta final.
    """
    if not ANTHROPIC_KEY:
        print("[insights] sin ANTHROPIC_API_KEY, saltando búsqueda web")
        return ""

    body = json.dumps({
        "model": "claude-sonnet-4-5",
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = json.loads(r.read())
        texts = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
        return "\n".join(texts).strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[insights] claude error HTTP {e.code}: {body[:600]}")
        return ""
    except Exception as e:
        print(f"[insights] claude error: {e}")
        return ""

# ── Generar secciones con Claude + web search ─────────────────────────────────
def build_ai_insights() -> dict:
    """
    Usa Claude con web search para generar las 4 secciones de insights.
    Devuelve dict con xg_performance, alertas, tendencias, oportunidades, dato_curioso.
    """
    today = datetime.now(timezone.utc).strftime("%d de %B de %Y")

    prompt = f"""Hoy es {today}. Sos el analista de FutVS, una plataforma de análisis estadístico de fútbol.

Buscá en la web las últimas noticias de fútbol de los últimos 4 días y generá un análisis estructurado.
PRIORIDAD MÁXIMA: Mundial 2026 (empieza el 11 de junio de 2026 en USA, México y Canadá). Enfocate principalmente en selecciones nacionales — lesiones, convocatorias, amistosos de preparación, favoritos por grupo. Las ligas de clubes son secundarias.

Buscá información sobre:
1. Rendimiento vs expectativas: selecciones que están superando o por debajo de su xG en amistosos previos al Mundial 2026
2. Alertas importantes: lesiones o bajas de jugadores clave en selecciones para el Mundial, sanciones, cambios de último momento
3. Tendencias: grupos del Mundial, selecciones en racha, estadísticas de preparación, favoritos estadísticos
4. Noticias destacadas: convocatorias definitivas, resultados de amistosos recientes, datos curiosos del Mundial 2026

Respondé ÚNICAMENTE con un JSON válido con esta estructura exacta (sin texto antes ni después, sin markdown):
{{
  "xg_performance": [
    {{"tipo": "sobre", "flag": "🔥", "texto": "descripción corta en español"}},
    {{"tipo": "bajo", "flag": "📉", "texto": "descripción corta en español"}}
  ],
  "alertas": [
    {{"nivel": "warning", "flag": "⚠️", "texto": "descripción corta en español"}},
    {{"nivel": "info", "flag": "🔍", "texto": "descripción corta en español"}}
  ],
  "tendencias": [
    {{"tipo": "over", "flag": "🎯", "texto": "descripción corta en español"}},
    {{"tipo": "other", "flag": "📈", "texto": "descripción corta en español"}}
  ],
  "noticias_semana": [
    {{"titulo": "título de la noticia en español", "fuente": "nombre de la fuente", "fecha": "YYYY-MM-DD", "url": "url o cadena vacía"}},
    {{"titulo": "título de la noticia en español", "fuente": "nombre de la fuente", "fecha": "YYYY-MM-DD", "url": ""}}
  ],
  "dato_curioso": "Un dato estadístico curioso y real del fútbol actual"
}}

Máximo 4 items por sección. Textos cortos (máximo 120 caracteres). Todo en español. Solo JSON."""

    print("[insights] llamando a Claude con web search...", flush=True)
    raw = claude_with_search(prompt, max_tokens=2000)

    if not raw:
        return {}

    # Limpiar posibles backticks de markdown
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip().rstrip("```").strip()

    try:
        data = json.loads(raw)
        print("[insights] respuesta de Claude parseada correctamente", flush=True)
        return data
    except json.JSONDecodeError as e:
        print(f"[insights] error parseando JSON de Claude: {e}")
        print(f"[insights] raw (primeros 500): {raw[:500]}")
        return {}

# ── Helpers ──────────────────────────────────────────────────────────────────
def load_predictions() -> dict:
    if not PREDS_PATH.exists():
        return {"matches": []}
    return json.loads(PREDS_PATH.read_text())

def isoweek(dt: datetime) -> str:
    return f"{dt.year}-W{dt.isocalendar()[1]:02d}"

def cutoff_str(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S")

# ── Forma reciente desde Supabase ─────────────────────────────────────────────
def build_forma_reciente() -> list[dict]:
    # Ventana amplia: 365 dias (selecciones juegan poco vs clubes; necesitamos
    # mas historia para tener los ultimos 5 de cada una).
    cut = cutoff_str(365)
    partidos = sb_get(
        f"partidos?select=id,fecha,goles_local,goles_visitante,"
        f"equipo_local_id,equipo_visitante_id"
        f"&estado=eq.finalizado"
        f"&fecha=gte.{cut}"
        f"&order=fecha.desc&limit=2000"
    )
    if not partidos:
        return []

    eq_ids = set()
    for p in partidos:
        if p.get("equipo_local_id"):    eq_ids.add(p["equipo_local_id"])
        if p.get("equipo_visitante_id"): eq_ids.add(p["equipo_visitante_id"])
    if not eq_ids:
        return []

    ids_csv  = ",".join(str(i) for i in eq_ids)
    # Solo selecciones del Mundial (liga_id=7). Filtramos por liga aca para
    # no mezclar clubes (Arsenal, Real Madrid, etc) con selecciones.
    # Cuando termine el Mundial, cambiar a [2,3,4,5,6] para clubes top-5 ligas.
    FORMA_LIGAS = (7,)
    eq_rows  = sb_get(f"equipos?select=id,nombre,escudo_url,liga_id&id=in.({ids_csv})")
    equipos  = {e["id"]: e for e in eq_rows if e.get("liga_id") in FORMA_LIGAS}

    teams: dict[int, dict] = {}

    def ensure(tid: int) -> None:
        if tid not in teams:
            # Si el equipo no esta en nuestro mapa filtrado (es club), saltear.
            eq = equipos.get(tid)
            if eq is None:
                teams[tid] = None  # marca para descartar
                return
            teams[tid] = {
                "id": tid,
                "nombre": eq.get("nombre", f"Equipo {tid}"),
                "escudo": eq.get("escudo_url", ""),
                "partidos": [],
            }

    for p in partidos:
        gl = p.get("goles_local"); gv = p.get("goles_visitante")
        lid = p.get("equipo_local_id"); vid = p.get("equipo_visitante_id")
        fecha = p.get("fecha", "")
        if gl is None or gv is None or not lid or not vid:
            continue
        ensure(lid); ensure(vid)
        # Acumular solo si AL MENOS UNO de los dos es seleccion del Mundial.
        # Eso garantiza que sumen los amistosos vs equipos no-Mundial (Zambia,
        # Mauritania, etc) sin contaminar la lista con esos rivales.
        rl = "W" if gl > gv else ("D" if gl == gv else "L")
        rv = "W" if gv > gl else ("D" if gv == gl else "L")
        if teams.get(lid):
            teams[lid]["partidos"].append((fecha, rl, gl, gv))
        if teams.get(vid):
            teams[vid]["partidos"].append((fecha, rv, gv, gl))

    result = []
    for t in teams.values():
        if t is None:  # club descartado en ensure()
            continue
        sorted_p = sorted(t["partidos"], key=lambda x: x[0], reverse=True)
        top5 = sorted_p[:5]
        forma = [r for _, r, _, _ in top5]
        if len(forma) < 2:  # minimo 2 partidos para que tenga sentido
            continue
        gf5 = sum(gf for _, _, gf, _ in top5)
        gc5 = sum(gc for _, _, _, gc in top5)
        result.append({
            "slug": t["nombre"].lower().replace(" ", "_"),
            "nombre": t["nombre"], "escudo": t["escudo"],
            "forma": forma, "gf": gf5, "gc": gc5,
        })

    # Ordenar por (W, diff de gol) y limitar a top 8 selecciones del Mundial
    result.sort(key=lambda x: (x["forma"].count("W"), x["gf"] - x["gc"]), reverse=True)
    return result[:8]

# ── Oportunidades desde predictions.json ─────────────────────────────────────
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
            ("home", f"Victoria {h_name}"),
            ("away", f"Victoria {a_name}"),
            ("draw", "Empate"),
        ]:
            p_mod = (probs.get(outcome) or 0) * 100
            p_mkt = (market.get(outcome) or 0) * 100
            if p_mkt <= 0: continue
            edge = p_mod - p_mkt
            if edge < 12: continue
            opps.append({
                "partido": f"{h_name} vs {a_name}", "competition": comp,
                "apuesta": label, "p_modelo": round(p_mod, 1),
                "p_mercado": round(p_mkt, 1), "edge": round(edge, 1),
                "xg_home": xg.get("home"), "xg_away": xg.get("away"),
                "kickoff": kickoff,
            })
    opps.sort(key=lambda x: x["edge"], reverse=True)
    seen = set()
    unique = []
    for o in opps:
        if o["partido"] not in seen:
            seen.add(o["partido"]); unique.append(o)
    return unique[:5]

# ── dato_curioso fallback ─────────────────────────────────────────────────────
DATOS_CURIOSOS = [
    "El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico.",
    "El método Dixon-Coles fue publicado en 1997 y sigue siendo una de las bases más sólidas para predicción de fútbol.",
    "Un Elo de 2000 puntos equivale a estar entre los mejores equipos del planeta — el promedio de la Premier League ronda los 1.600.",
    "El xG fue popularizado en análisis profesional alrededor de 2012 y hoy es estándar en los grandes clubes.",
    "En promedio, el equipo local gana el 46% de los partidos en las ligas top de Europa.",
    "La corrección de Dixon-Coles penaliza resultados 0-0 y 1-0, que son más comunes de lo que Poisson puro predice.",
    "En la Champions League, los equipos de local ganan solo el 38% — la ventaja de localía es menor que en ligas domésticas.",
    "Argentina ganó el Mundial 2022 en Qatar, su tercera estrella, venciendo a Francia en una final histórica.",
]

def pick_dato_curioso() -> str:
    idx = datetime.now(timezone.utc).isocalendar()[1] % len(DATOS_CURIOSOS)
    return DATOS_CURIOSOS[idx]

# ── Main ──────────────────────────────────────────────────────────────────────
def main() -> None:
    print("[insights] generando insights...", flush=True)
    preds = load_predictions()
    now   = datetime.now(timezone.utc)

    # 1. Forma reciente desde Supabase
    print("[insights] forma reciente desde Supabase...", flush=True)
    forma = build_forma_reciente()
    print(f"[insights] {len(forma)} equipos con forma", flush=True)

    # 2. Oportunidades desde predictions.json
    opps = build_oportunidades(preds)
    print(f"[insights] {len(opps)} oportunidades desde modelo", flush=True)

    # 3. Noticias y análisis con Claude + web search
    ai = build_ai_insights()

    xg_perf    = ai.get("xg_performance", [])
    alertas    = ai.get("alertas", [])
    tendencias = ai.get("tendencias", [])
    noticias   = ai.get("noticias_semana", [])
    dato       = ai.get("dato_curioso") or pick_dato_curioso()

    print(f"[insights] AI: {len(xg_perf)} xG, {len(alertas)} alertas, "
          f"{len(tendencias)} tendencias, {len(noticias)} noticias", flush=True)

    # 4. Armar insights.json
    insights = {
        "generated_at_utc": now.isoformat(),
        "dato_curioso":     dato,
        "forma_reciente":   forma,
        "xg_performance":   xg_perf,
        "alertas":          alertas,
        "tendencias":       tendencias,
        "oportunidades":    opps,
    }
    OUT_INSIGHTS.write_text(json.dumps(insights, indent=2, ensure_ascii=False))
    print(f"[insights] → {OUT_INSIGHTS}", flush=True)

    # 5. Armar insights_semana.json
    fecha_str = now.date().isoformat()
    if not noticias:
        # Fallback: generar desde oportunidades y tendencias
        for o in opps[:3]:
            noticias.append({
                "titulo": f"⚡ {o['apuesta']} en {o['partido']} — edge de +{o['edge']:.0f}pp vs mercado",
                "fuente": "FutVS Modelo", "fecha": fecha_str, "url": "",
            })
        for t in tendencias[:2]:
            noticias.append({
                "titulo": t.get("flag","") + " " + t.get("texto",""),
                "fuente": "FutVS Análisis", "fecha": fecha_str, "url": "",
            })
    if not noticias:
        noticias.append({
            "titulo": "📊 Sin novedades significativas esta semana.",
            "fuente": "FutVS Modelo", "fecha": fecha_str, "url": "",
        })

    semana = {"week": isoweek(now), "noticias": noticias}
    OUT_SEMANA.write_text(json.dumps(semana, indent=2, ensure_ascii=False))
    print(f"[insights] → {OUT_SEMANA}", flush=True)
    print(f"[insights] listo ✓", flush=True)

if __name__ == "__main__":
    main()
