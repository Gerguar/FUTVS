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
    """Devuelve {'matches': [...]} con partidos para alimentar 'oportunidades'.

    1) Si predictions.json tiene matches, los usa (clubes).
    2) Si no (off-season de clubes), levanta partidos PROGRAMADOS del Mundial
       desde Supabase + cuotas Pinnacle desde data/wc2026_market_odds.json.
       Eso permite que la seccion 'Oportunidades del algoritmo' funcione
       durante el Mundial."""
    if PREDS_PATH.exists():
        try:
            data = json.loads(PREDS_PATH.read_text())
            if data.get("matches"):
                return data
        except Exception:
            pass

    # Fallback Mundial: levantar partidos programados liga 7 + sus pronosticos
    print("[insights] predictions.json vacio — usando fallback Mundial", flush=True)
    try:
        rows = sb_get(
            "partidos?select=id,fecha,equipo_local:equipo_local_id(nombre),"
            "equipo_visitante:equipo_visitante_id(nombre),"
            "pronosticos(prob_local,prob_empate,prob_visitante,notas)"
            "&estado=eq.programado&liga_id=eq.7&order=fecha&limit=50"
        )
    except Exception as e:
        print(f"[insights] fallback Mundial falló: {e}", flush=True)
        return {"matches": []}

    # Cargar cuotas Pinnacle (devigged) mapeadas por partido_id
    market_path = DATA_DIR / "wc2026_market_odds.json"
    market_by_id = {}
    if market_path.exists():
        try:
            market_by_id = json.loads(market_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    print(f"[insights] fallback: {len(rows)} partidos Mundial | {len(market_by_id)} con Pinnacle", flush=True)

    matches = []
    for r in rows:
        h = (r.get("equipo_local") or {}).get("nombre", "?")
        a = (r.get("equipo_visitante") or {}).get("nombre", "?")
        pr = r.get("pronosticos")
        if isinstance(pr, list):
            pr = pr[0] if pr else None
        if not pr:
            continue
        # Probabilidades del MODELO
        prob_h = float(pr.get("prob_local") or 0) / 100.0
        prob_d = float(pr.get("prob_empate") or 0) / 100.0
        prob_a = float(pr.get("prob_visitante") or 0) / 100.0
        if prob_h + prob_d + prob_a < 0.5:
            continue

        # Probabilidades del MERCADO (Pinnacle devigged)
        m = market_by_id.get(str(r["id"])) or {}
        if m:
            market_probabilities = {
                "home": float(m.get("p_market_home") or 0),
                "draw": float(m.get("p_market_draw") or 0),
                "away": float(m.get("p_market_away") or 0),
            }
        else:
            market_probabilities = None

        # xG esperado parseado del campo notas (formato 'xG esperado: 1.69-0.35')
        xg_home = xg_away = None
        notas = pr.get("notas") or ""
        import re
        m_xg = re.search(r"xG[^0-9]*([\d.]+)\s*-\s*([\d.]+)", notas, re.IGNORECASE)
        if m_xg:
            try:
                xg_home = float(m_xg.group(1))
                xg_away = float(m_xg.group(2))
            except ValueError:
                pass

        matches.append({
            "home": {"name": h},
            "away": {"name": a},
            "competition": {"name": "Mundial 2026"},
            "kickoff_ts_utc": r.get("fecha", ""),
            "probabilities": {"home": prob_h, "draw": prob_d, "away": prob_a},
            **({"market_probabilities": market_probabilities} if market_probabilities else {}),
            **({"expected_goals": {"home": xg_home, "away": xg_away}} if xg_home is not None else {}),
        })

    return {"matches": matches}

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

# ── Alertas desde NewsAPI (en vez de Claude, para evitar alucinaciones) ──────
# Decision del 7-jun-2026: las alertas se alimentan SOLO de NewsAPI porque
# Claude sin web_search inventaba lesiones (Neymar rodilla, De Bruyne sancion,
# etc). Aca consultamos NewsAPI con keywords especificas y filtramos las que
# realmente son alertas (lesiones, sanciones, bajas confirmadas).

ALERTA_QUERIES = [
    # Queries SIMPLES de 1 palabra. NewsAPI las usa con qInTitle (matchea
    # solo titulo). El filtro de futbol (is_football_news) y la lista de
    # keywords de ALERTA_KEYWORDS hacen el resto del filtrado.
    "lesion",
    "lesionado",
    "baja",
    "descartado",
    "rotura",
    "desgarro",
    "operado",
    "suspendido",
    "sancion",
]

# Mapeo keyword -> nivel + flag (orden importa: las criticas primero)
ALERTA_KEYWORDS = [
    # (keyword en titulo lowercase, nivel, flag emoji)
    ("se pierde el mundial",  "critical", "🚨"),
    ("descartado del mundial","critical", "🚨"),
    ("fuera del mundial",     "critical", "🚨"),
    ("rotura de ligament",    "critical", "🚨"),
    ("operad",                "critical", "🚨"),  # operado/operada/operada
    ("baja confirmada",       "critical", "🚨"),
    ("baja para el mundial",  "critical", "🚨"),
    ("queda fuera",           "critical", "🚨"),
    ("se perdera el mundial", "critical", "🚨"),
    ("no jugara el mundial",  "critical", "🚨"),
    ("lesion grave",          "critical", "🚨"),
    ("rotura",                "warning",  "⚠️"),
    ("desgarro",              "warning",  "⚠️"),
    ("lesionado",             "warning",  "⚠️"),
    ("lesion",                "warning",  "⚠️"),
    ("baja",                  "warning",  "⚠️"),
    ("sancion",               "warning",  "⚠️"),
    ("suspendido",            "warning",  "⚠️"),
    ("amarillas",             "warning",  "⚠️"),
    ("convocatoria",          "info",     "🔍"),
    ("convocados",            "info",     "🔍"),
    ("lista de",              "info",     "🔍"),
    ("en duda",               "info",     "🔍"),
]

# Anti-falso-positivo: si el titulo o descripcion menciona DEPORTES NO-FUTBOL,
# se descarta aunque tenga "lesion" o "baja".
ALERTA_OTROS_DEPORTES = [
    "basket", "básket", "basquet", "básquet", "nba", "wnba", "euroliga",
    "mlb", "beisbol", "béisbol", "baseball", "softball",
    "nfl", "futbol americano", "fútbol americano",
    "hockey", "nhl", "rugby", "padel", "pádel", "tenis", "tennis",
    "boxeo", "ufc", "mma", "natacion", "natación", "atletismo",
    "f1 ", "formula 1", "fórmula 1", "motogp", "nascar", "indycar",
    "ciclismo", "ciclista", "tour de francia", "giro de italia", "vuelta a espana", "vuelta a españa",
    "esports", "voley", "vóley", "voleibol", "handball",
    "halterofilia", "remo", "judo", "karate", "taekwondo", "esgrima",
]

# Anti-falso-positivo: titulares que NO son alertas reales aunque contengan
# la palabra "lesion" o similares (notas positivas, anecdotas, homenajes).
ALERTA_NO_ES_ALERTA = [
    "homenaje", "emociona", "gesto a", "saluda a", "visita a", "ayuda a",
    "se reune con", "se reúne con", "regala", "regalo", "felicit",
    "celebra", "festeja", "campeon ", "campeón ", "trofeo", "premio",
    "leyenda", "historico", "histórico", "recuerda", "recuerdo",
    "documental", "entrevista", "biograf",
    # Anti-publicidad / non-news
    "vpn", "oferta", "descuento", "cuesta menos", "precio", "mejor precio",
    "cupon", "cupón", "promocion", "promoción", "rebaja",
    # Politica / economia / tecnologia con "baja" o "lesion" metaforico
    "bolsa baja", "inflacion", "inflación", "criptomoneda", "bitcoin",
]

# Reusar filtros antiestafa de fetch_news para no duplicar codigo.
def _clasificar_alerta(titulo: str, descripcion: str = "") -> tuple[str, str] | None:
    """Devuelve (nivel, flag) si el titulo es una alerta REAL del Mundial 2026,
    None si no aplica o es falso positivo."""
    t = titulo.lower()
    d = (descripcion or "").lower()
    combined = t + " " + d

    # 1. Filtro otros deportes (basket, beisbol, etc).
    for kw in ALERTA_OTROS_DEPORTES:
        if kw in combined:
            return None

    # 2. Filtro "no es alerta" (homenajes, gestos, etc).
    for kw in ALERTA_NO_ES_ALERTA:
        if kw in t:  # solo titulo (descripcion puede tener contexto adicional)
            return None

    # 3. Buscar keyword de alerta.
    matched = None
    for kw, nivel, flag in ALERTA_KEYWORDS:
        if kw in t:
            matched = (nivel, flag)
            break
    if matched is None:
        return None

    # 4. Filtro de relevancia FUERTE: solo terminos que aseguran contexto futbol.
    # Los nombres de paises solos (España, Francia) NO sirven porque aparecen
    # en cualquier nota (VPN España, Tour de Francia, etc).
    ANCLAS_CONTEXT = [
        # Terminos explicitos de futbol
        "fútbol", "futbol", "soccer",
        # Competiciones futbol
        "mundial 2026", "copa mundial", "mundialista", "mundialistas",
        "fifa", "uefa", "conmebol", "concacaf", "afc ", "ofc ",
        "champions league", "premier league", "laliga", "la liga",
        "serie a", "bundesliga", "ligue 1", "copa america", "copa américa",
        "eurocopa", "libertadores", "sudamericana", "europa league",
        # Roles deportivos clave
        "seleccion", "selección", "convocatoria", "convocado", "convocados",
        "amistoso", "amistosos", "eliminatorias", "eliminatoria",
        # Nombres jugadores top
        "cristiano ronaldo", "messi", "mbappe", "mbappé", "haaland",
        "vinicius", "vinícius", "lamine yamal", "bellingham", "pedri",
        "rodrygo", "militao", "militão", "neymar", "endrick", "raphinha",
        "harry kane", "lewandowski", "salah", "de bruyne", "modric",
        # Clubes grandes
        "real madrid", "fc barcelona", "atletico de madrid", "atlético de madrid",
        "bayern munich", "bayern múnich", "borussia dortmund",
        "manchester united", "manchester city", "liverpool fc",
        "arsenal fc", "chelsea fc", "tottenham hotspur",
        "psg", "paris saint-germain", "ac milan", "ac milán",
        "inter de milan", "inter de milán", "juventus", "ssc napoli",
        # Combinaciones "seleccion + pais" para asegurar contexto
        "seleccion argentina", "selección argentina", "argentina futbol",
        "seleccion brasil", "selección brasil", "brasil futbol",
        "albiceleste", "canarinha", "la roja", "les bleus", "azzurri",
        "tres leones", "the three lions",
    ]
    if not any(a in combined for a in ANCLAS_CONTEXT):
        return None

    return matched

def _normalizar_titulo(titulo: str, max_len: int = 140) -> str:
    """Limpia un titulo de NewsAPI: saca fuente al final, trunca con elipsis."""
    titulo = (titulo or "").strip()
    for sep in [" - ", " | ", " — "]:
        if sep in titulo:
            parts = titulo.rsplit(sep, 1)
            # Si lo de la derecha es corto, es el nombre del medio
            if len(parts[1]) < 40:
                titulo = parts[0].strip()
    if len(titulo) > max_len:
        titulo = titulo[:max_len].rsplit(" ", 1)[0] + "…"
    return titulo

def build_alertas_from_newsapi() -> list[dict]:
    """Genera alertas desde NewsAPI usando queries especificas de lesiones,
    bajas, sanciones. Filtra titulos no-futbol y deduplica por jugador.
    Devuelve hasta 4 alertas ordenadas por nivel (critical > warning > info)."""
    from . import fetch_news as fn
    if not fn.NEWS_API_KEY:
        print("[insights] NEWS_API_KEY ausente — no se generan alertas", flush=True)
        return []

    now = datetime.now(timezone.utc)
    from_date = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")
    sources_csv = ",".join(fn.FOOTBALL_SOURCES)

    seen_urls: set[str] = set()
    candidatos: list[dict] = []

    total_bajados = 0
    total_no_futbol = 0
    total_sin_keyword = 0
    for q in ALERTA_QUERIES:
        try:
            arts = fn.fetch_articles(q, from_date, to_date, page_size=8, sources=sources_csv)
            arts += fn.fetch_articles(q, from_date, to_date, page_size=5, sources=None)
        except Exception as e:
            print(f"[insights] error fetch alertas '{q}': {e}", flush=True)
            continue

        kept_q = 0
        total_bajados += len(arts)
        for a in arts:
            url = a.get("url") or ""
            if not url or url in seen_urls:
                continue
            ok, razon = fn.is_football_news(a)
            if not ok:
                total_no_futbol += 1
                continue
            titulo = (a.get("title") or "").strip()
            if not titulo:
                continue
            desc = (a.get("description") or "").strip()
            clas = _clasificar_alerta(titulo, desc)
            if not clas:
                total_sin_keyword += 1
                continue
            nivel, flag = clas
            seen_urls.add(url)
            candidatos.append({
                "nivel": nivel,
                "flag": flag,
                "texto": _normalizar_titulo(titulo),
                "fuente": (a.get("source") or {}).get("name") or "",
                "fuente_url": url,
                "fecha": (a.get("publishedAt") or "")[:10],
            })
            kept_q += 1
        print(f"[insights] q='{q}': bajados={len(arts)} candidatos+={kept_q}", flush=True)

    print(f"[insights] TOTAL bajados={total_bajados} | no_futbol={total_no_futbol} | sin_keyword={total_sin_keyword} | candidatos={len(candidatos)}", flush=True)

    # Ordenar: critical primero, despues warning, despues info
    rank = {"critical": 0, "warning": 1, "info": 2}
    candidatos.sort(key=lambda x: rank.get(x["nivel"], 9))

    # Deduplicar por titulo casi identico (mismo jugador en distintos medios)
    # Estrategia simple: comparar primeras 5 palabras del titulo normalizado.
    seen_keys: set[str] = set()
    unique: list[dict] = []
    for c in candidatos:
        key = " ".join(c["texto"].lower().split()[:5])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(c)
        if len(unique) >= 4:
            break

    print(f"[insights] alertas NewsAPI: {len(unique)} (de {len(candidatos)} candidatos)", flush=True)
    return unique

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

    # 3. Noticias y análisis con Claude + web search (xg/tendencias/dato)
    ai = build_ai_insights()

    xg_perf    = ai.get("xg_performance", [])
    tendencias = ai.get("tendencias", [])
    noticias   = ai.get("noticias_semana", [])
    dato       = ai.get("dato_curioso") or pick_dato_curioso()

    # 3.b. ALERTAS desde NewsAPI (NO desde Claude — evita alucinaciones).
    # Decision del 7-jun-2026 despues de detectar 3 alertas falsas inventadas
    # por Claude (Neymar lesion rodilla, De Bruyne sancion, Mbappe 4 dias).
    alertas = build_alertas_from_newsapi()

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
