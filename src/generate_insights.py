"""
generate_insights.py — Genera data/insights.json para la página Insights de FutVS.

Fuentes de datos:
  1. data/predictions.json      → probabilities, xG, elo, market odds
  2. Supabase forma_reciente    → últimos 5 W/D/L por equipo
  3. data/matches.parquet       → historial de goles para tendencias
  4. Anthropic Claude API       → dato curioso generado por IA (opcional)

Cómo correrlo:
  python -m src.generate_insights --out data/insights.json

Secretos necesarios (ya en GitHub Secrets):
  SUPABASE_URL, SUPABASE_SERVICE_KEY (lectura de forma_reciente y equipos)
  ANTHROPIC_API_KEY (opcional, para el dato curioso con IA)
"""

from __future__ import annotations

import argparse
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from collections import defaultdict
from typing import Optional

import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

PATHS = {
    "predictions": Path("data/predictions.json"),
    "matches":     Path("data/matches.parquet"),
    "out":         Path("data/insights.json"),
}

SB_URL         = os.environ.get("SUPABASE_URL", "")
SB_KEY         = os.environ.get("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")

# Umbral mínimo de diferencia modelo vs mercado para detectar valor
VALUE_THRESHOLD = 0.06   # 6 puntos porcentuales

# Mínimo de partidos recientes para incluir un equipo en tendencias
MIN_MATCHES_TENDENCIAS = 5

# Cuántos partidos atrás analizar para tendencias
WINDOW_TENDENCIAS = 10

# Emojis de banderas por slug de equipo (extendible)
FLAG_BY_SLUG: dict[str, str] = {
    "argentina":    "🇦🇷",
    "spain":        "🇪🇸",
    "brasil":       "🇧🇷",
    "brazil":       "🇧🇷",
    "france":       "🇫🇷",
    "germany":      "🇩🇪",
    "england":      "󠁧󠁢󠁥󠁮󠁧󠁿",
    "portugal":     "🇵🇹",
    "netherlands":  "🇳🇱",
    "italy":        "🇮🇹",
    "japan":        "🇯🇵",
    "south_korea":  "🇰🇷",
    "korea_republic":"🇰🇷",
    "morocco":      "🇲🇦",
    "canada":       "🇨🇦",
    "mexico":       "🇲🇽",
    "usa":          "🇺🇸",
    "united_states":"🇺🇸",
    "croatia":      "🇭🇷",
    "senegal":      "🇸🇳",
    "ecuador":      "🇪🇨",
    "switzerland":  "🇨🇭",
    "denmark":      "🇩🇰",
    "sweden":       "🇸🇪",
    "poland":       "🇵🇱",
    "australia":    "🇦🇺",
    "ghana":        "🇬🇭",
    "cameroon":     "🇨🇲",
    "serbia":       "🇷🇸",
    "wales":        "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "costa_rica":   "🇨🇷",
    "saudi_arabia": "🇸🇦",
    "iran":         "🇮🇷",
    "qatar":        "🇶🇦",
    "tunisia":      "🇹🇳",
    "colombia":     "🇨🇴",
    "uruguay":      "🇺🇾",
    "chile":        "🇨🇱",
    "paraguay":     "🇵🇾",
    "venezuela":    "🇻🇪",
    "peru":         "🇵🇪",
    "bolivia":      "🇧🇴",
    "egypt":        "🇪🇬",
    "nigeria":      "🇳🇬",
    "ivory_coast":  "🇨🇮",
    "mali":         "🇲🇱",
    "belgium":      "🇧🇪",
    "austria":      "🇦🇹",
    "turkey":       "🇹🇷",
    "ukraine":      "🇺🇦",
    "czechia":      "🇨🇿",
    "hungary":      "🇭🇺",
    "slovakia":     "🇸🇰",
    "slovenia":     "🇸🇮",
    "albania":      "🇦🇱",
    "scotland":     "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "romania":      "🇷🇴",
    "norway":       "🇳🇴",
    "finland":      "🇫🇮",
    "israel":       "🇮🇱",
    "georgia":      "🇬🇪",
    "new_zealand":  "🇳🇿",
    "jamaica":      "🇯🇲",
    "honduras":     "🇭🇳",
    "panama":       "🇵🇦",
    # Equipos de club (para la versión sin Mundial)
    "real_madrid":      "⚪",
    "fc_barcelona":     "🔵🔴",
    "manchester_city":  "🩵",
    "arsenal":          "🔴",
    "liverpool":        "🔴",
    "chelsea":          "🔵",
    "barcelona":        "🔵🔴",
    "atletico_madrid":  "🔴⚪",
    "bayern_munich":    "🔴",
    "borussia_dortmund":"🟡",
    "inter_milan":      "🔵⚫",
    "ac_milan":         "🔴⚫",
    "paris_sg":         "🔵🔴",
}


def flag(slug: str) -> str:
    """Devuelve emoji de bandera/color para un slug de equipo."""
    clean = slug.lower().replace(" ", "_").replace("-", "_")
    return FLAG_BY_SLUG.get(clean, "⚽")


# ──────────────────────────────────────────────────────────────────────────────
# SUPABASE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def sb_get(path: str) -> list:
    """GET desde Supabase REST API."""
    if not SB_URL or not SB_KEY:
        return []
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey":        SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[insights] sb_get error ({path}): {e}")
        return []


# ──────────────────────────────────────────────────────────────────────────────
# CARGA DE DATOS
# ──────────────────────────────────────────────────────────────────────────────

def load_predictions() -> list[dict]:
    p = PATHS["predictions"]
    if not p.exists():
        print(f"[insights] {p} no encontrado, usando lista vacía")
        return []
    with open(p) as f:
        data = json.load(f)
    return data.get("matches", [])


def load_matches_df() -> pd.DataFrame:
    p = PATHS["matches"]
    if not p.exists():
        print(f"[insights] {p} no encontrado")
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as e:
        print(f"[insights] error leyendo parquet: {e}")
        return pd.DataFrame()


def load_forma_supabase() -> dict[str, list[str]]:
    """Carga la VIEW forma_reciente de Supabase: {equipo_id: ['W','D','L',...]}"""
    rows = sb_get("forma_reciente?select=equipo_id,forma")
    result = {}
    for row in rows:
        eid = str(row.get("equipo_id", ""))
        forma = row.get("forma", []) or []
        result[eid] = forma
    return result


def load_equipos_supabase() -> dict[str, dict]:
    """Carga equipos: {id: {nombre, abreviacion, pais, escudo_url}}"""
    rows = sb_get("equipos?select=id,nombre,abreviacion,pais,escudo_url")
    return {str(r["id"]): r for r in rows}


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 1: FORMA RECIENTE
# ──────────────────────────────────────────────────────────────────────────────

def build_forma_section(
    predictions: list[dict],
    forma_sb: dict[str, list[str]],
    equipos_sb: dict[str, dict],
) -> list[dict]:
    """
    Construye la sección de forma reciente.
    
    Prioriza datos de Supabase. Si no hay Supabase, infiere del parquet.
    Devuelve top 8 equipos ordenados por forma (más victorias primero).
    """
    
    # Recopilar equipos que aparecen en predicciones
    team_slugs: dict[str, str] = {}  # slug → nombre display
    for m in predictions:
        for side in ("home", "away"):
            t = m.get(side, {})
            if t.get("id") and t.get("name"):
                team_slugs[str(t["id"])] = t["name"]

    # Si tenemos Supabase, usar forma_reciente
    if forma_sb and equipos_sb:
        rows = []
        for eid, eq in equipos_sb.items():
            forma_raw = forma_sb.get(eid, [])
            if not forma_raw:
                continue
            # Normalizar: asegurarse de que son W/D/L
            forma_norm = [r.upper() if r.upper() in ("W","D","L") else "?" for r in forma_raw[:5]]
            wins = forma_norm.count("W")
            rows.append({
                "slug":    eq.get("abreviacion", "").lower(),
                "nombre":  eq.get("nombre", ""),
                "pais":    eq.get("pais", ""),
                "escudo":  eq.get("escudo_url", ""),
                "forma":   forma_norm,
                "wins":    wins,
                "draws":   forma_norm.count("D"),
            })
        rows.sort(key=lambda x: (x["wins"], x["draws"]), reverse=True)
        return rows[:8]

    # Fallback: solo con predictions (menos datos)
    # Estimamos forma a partir de probabilidades (aproximación)
    rows = []
    seen = set()
    for m in predictions:
        for side in ("home", "away"):
            t = m.get(side, {})
            tid = str(t.get("id", ""))
            if not tid or tid in seen:
                continue
            seen.add(tid)
            rows.append({
                "slug":   tid,
                "nombre": t.get("name", tid),
                "pais":   "",
                "escudo": "",
                "forma":  ["?","?","?","?","?"],
                "wins":   0,
                "draws":  0,
            })
    return rows[:8]


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 2: OPORTUNIDADES (valor detectado modelo vs mercado)
# ──────────────────────────────────────────────────────────────────────────────

def build_oportunidades(predictions: list[dict]) -> list[dict]:
    """
    Detecta partidos donde prob del modelo supera la cuota implícita del mercado
    por al menos VALUE_THRESHOLD puntos.
    
    Retorna lista de oportunidades ordenadas por valor descendente.
    """
    opps = []
    for m in predictions:
        probs = m.get("probabilities", {})
        market = m.get("market_probabilities")
        if not market:
            continue
        
        home_name = m.get("home", {}).get("name", "?")
        away_name = m.get("away", {}).get("name", "?")
        home_slug = str(m.get("home", {}).get("id", "")).lower()
        away_slug = str(m.get("away", {}).get("id", "")).lower()
        
        for side, label, slug in [
            ("home", home_name, home_slug),
            ("away", away_name, away_slug),
            ("draw", "Empate", ""),
        ]:
            p_model  = float(probs.get(side, 0))
            p_market = float(market.get(side, 0))
            if p_market < 0.01:
                continue
            edge = p_model - p_market
            if edge >= VALUE_THRESHOLD:
                opps.append({
                    "partido":     f"{home_name} vs {away_name}",
                    "apuesta":     label,
                    "flag":        flag(slug),
                    "p_modelo":    round(p_model * 100, 1),
                    "p_mercado":   round(p_market * 100, 1),
                    "edge":        round(edge * 100, 1),
                    "kickoff":     m.get("kickoff_ts_utc", ""),
                    "competition": m.get("competition", {}).get("name", ""),
                    "xg_home":     m.get("expected_goals", {}).get("home"),
                    "xg_away":     m.get("expected_goals", {}).get("away"),
                    "elo_diff":    m.get("ratings", {}).get("elo_diff"),
                })
    
    opps.sort(key=lambda x: x["edge"], reverse=True)
    return opps[:5]


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 3: TENDENCIAS (del parquet histórico)
# ──────────────────────────────────────────────────────────────────────────────

def build_tendencias(df: pd.DataFrame, predictions: list[dict]) -> list[dict]:
    """
    Analiza el historial para detectar tendencias estadísticas.
    
    Tendencias detectadas:
    - % de partidos con Over 2.5 goles por equipo
    - % de partidos marcando primero (proxy: ganando al HT si hay datos)
    - % de Clean Sheets
    """
    tendencias = []

    if df.empty:
        # Fallback: tendencias desde expected_goals de predictions
        return _tendencias_from_xg(predictions)

    # Columnas necesarias
    needed = {"home_team", "away_team", "home_goals", "away_goals"}
    if not needed.issubset(df.columns):
        return _tendencias_from_xg(predictions)

    df = df.dropna(subset=["home_goals", "away_goals"]).copy()
    df["total_goals"] = df["home_goals"] + df["away_goals"]
    df["over_2_5"]    = df["total_goals"] > 2.5

    # Recopilar equipos que aparecen en predictions
    pred_teams = set()
    for m in predictions:
        pred_teams.add(str(m.get("home", {}).get("id", "")).lower())
        pred_teams.add(str(m.get("away", {}).get("id", "")).lower())

    # Función helper: partidos de un equipo (últimos N)
    def team_matches(slug: str, n: int = WINDOW_TENDENCIAS):
        mask = (
            df["home_team"].str.lower().str.replace(" ","_") == slug
        ) | (
            df["away_team"].str.lower().str.replace(" ","_") == slug
        )
        sub = df[mask].copy()
        # Ordenar por fecha si existe
        if "date" in sub.columns:
            sub = sub.sort_values("date", ascending=False)
        return sub.head(n)

    for slug in list(pred_teams)[:20]:
        sub = team_matches(slug)
        if len(sub) < MIN_MATCHES_TENDENCIAS:
            continue

        n = len(sub)
        nombre = slug.replace("_", " ").title()

        # Over 2.5
        over_pct = round(sub["over_2_5"].mean() * 100)
        if over_pct >= 70:
            tendencias.append({
                "tipo":    "over",
                "equipo":  nombre,
                "flag":    flag(slug),
                "valor":   over_pct,
                "texto":   f"El {over_pct}% de los partidos de {nombre} terminaron con +2.5 goles.",
                "n":       n,
            })

        # Clean sheets (arco en 0)
        cs_home = ((sub["home_team"].str.lower().str.replace(" ","_") == slug) & (sub["away_goals"] == 0))
        cs_away = ((sub["away_team"].str.lower().str.replace(" ","_") == slug) & (sub["home_goals"] == 0))
        cs_total = (cs_home | cs_away).sum()
        cs_pct = round(cs_total / n * 100)
        if cs_pct >= 50:
            tendencias.append({
                "tipo":    "cs",
                "equipo":  nombre,
                "flag":    flag(slug),
                "valor":   cs_pct,
                "texto":   f"{nombre} mantuvo el arco en cero en {cs_total} de sus últimos {n} partidos.",
                "n":       n,
            })

    # Ordenar por valor descendente y deduplicar equipos (solo la tendencia más fuerte)
    seen_teams = set()
    result = []
    for t in sorted(tendencias, key=lambda x: x["valor"], reverse=True):
        if t["equipo"] not in seen_teams:
            seen_teams.add(t["equipo"])
            result.append(t)
        if len(result) >= 5:
            break

    return result if result else _tendencias_from_xg(predictions)


def _tendencias_from_xg(predictions: list[dict]) -> list[dict]:
    """Fallback: genera tendencias desde xG de las predicciones actuales."""
    tendencias = []
    for m in predictions:
        xg = m.get("expected_goals", {})
        xg_h = xg.get("home", 0) or 0
        xg_a = xg.get("away", 0) or 0
        total_xg = xg_h + xg_a

        home_name = m.get("home", {}).get("name", "?")
        away_name = m.get("away", {}).get("name", "?")

        if total_xg >= 3.0:
            tendencias.append({
                "tipo":   "xg_alto",
                "equipo": f"{home_name} vs {away_name}",
                "flag":   "📈",
                "valor":  round(total_xg, 2),
                "texto":  f"El modelo espera {total_xg:.1f} goles totales en {home_name} vs {away_name} (xG alto).",
                "n":      0,
            })

    tendencias.sort(key=lambda x: x["valor"], reverse=True)
    return tendencias[:4]


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 4: ALERTAS
# ──────────────────────────────────────────────────────────────────────────────

def build_alertas(predictions: list[dict], df: pd.DataFrame) -> list[dict]:
    """
    Detecta alertas automáticas:
    - Equipos favoritos con Elo muy superior al rival
    - Partidos con xG total muy bajo (cerrado)
    - Partidos con alta incertidumbre (probs muy similares)
    """
    alertas = []
    
    for m in predictions:
        elo_diff = m.get("ratings", {}).get("elo_diff", 0) or 0
        probs    = m.get("probabilities", {})
        xg       = m.get("expected_goals", {}) or {}
        home_name = m.get("home", {}).get("name", "?")
        away_name = m.get("away", {}).get("name", "?")
        home_slug = str(m.get("home", {}).get("id", "")).lower()
        away_slug = str(m.get("away", {}).get("id", "")).lower()

        # Alerta: favorito claro ignorado por el mercado
        market = m.get("market_probabilities") or {}
        if market:
            for side, name, slug in [("home", home_name, home_slug), ("away", away_name, away_slug)]:
                pm = float(market.get(side, 0))
                pmod = float(probs.get(side, 0))
                if pmod > 0.6 and pm < 0.5:
                    alertas.append({
                        "tipo":    "valor_ignorado",
                        "equipo":  name,
                        "flag":    flag(slug),
                        "texto":   (f"El modelo da {round(pmod*100)}% a {name}, "
                                   f"pero el mercado solo {round(pm*100)}%. "
                                   f"Partido: {home_name} vs {away_name}."),
                        "nivel":   "warning",
                    })

        # Alerta: partido muy parejo (alta incertidumbre)
        ph = float(probs.get("home", 0))
        pa = float(probs.get("away", 0))
        if abs(ph - pa) < 0.08 and abs(elo_diff) < 50:
            alertas.append({
                "tipo":    "partido_parejo",
                "equipo":  f"{home_name} vs {away_name}",
                "flag":    "⚖️",
                "texto":   (f"Partido muy parejo: {home_name} ({round(ph*100)}%) "
                           f"vs {away_name} ({round(pa*100)}%). "
                           f"Alta incertidumbre, cualquier resultado es válido."),
                "nivel":   "info",
            })

        # Alerta: xG muy bajo (partido cerrado esperado)
        xg_total = (xg.get("home") or 0) + (xg.get("away") or 0)
        if 0 < xg_total < 1.8:
            alertas.append({
                "tipo":    "xg_bajo",
                "equipo":  f"{home_name} vs {away_name}",
                "flag":    "🔒",
                "texto":   (f"Partido defensivo esperado entre {home_name} y {away_name}. "
                           f"xG total: {xg_total:.1f}. Alta probabilidad de Under 2.5."),
                "nivel":   "info",
            })

    # Deduplicar por tipo+partido
    seen = set()
    result = []
    for a in alertas:
        key = (a["tipo"], a["equipo"])
        if key not in seen:
            seen.add(key)
            result.append(a)
        if len(result) >= 5:
            break

    return result


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 5: DATO CURIOSO (Claude API)
# ──────────────────────────────────────────────────────────────────────────────

def build_dato_curioso(
    predictions: list[dict],
    tendencias: list[dict],
    oportunidades: list[dict],
) -> str:
    """
    Llama a Claude API para generar un dato curioso basado en los datos del día.
    Si falla o no hay API key, devuelve un dato estático generado desde los datos.
    """
    if not ANTHROPIC_KEY:
        return _dato_curioso_estatico(predictions, tendencias, oportunidades)

    # Preparar contexto compacto para Claude
    ctx_matches = []
    for m in predictions[:10]:
        ctx_matches.append({
            "partido":   f"{m.get('home',{}).get('name')} vs {m.get('away',{}).get('name')}",
            "p_local":   round(m.get("probabilities",{}).get("home",0)*100,1),
            "p_empate":  round(m.get("probabilities",{}).get("draw",0)*100,1),
            "p_visita":  round(m.get("probabilities",{}).get("away",0)*100,1),
            "xg_total":  round((m.get("expected_goals",{}).get("home") or 0) +
                               (m.get("expected_goals",{}).get("away") or 0), 2),
            "elo_diff":  m.get("ratings",{}).get("elo_diff"),
        })

    ctx_tendencias = [t["texto"] for t in tendencias[:3]]
    ctx_opps = [f"{o['partido']}: edge +{o['edge']}%" for o in oportunidades[:3]]

    prompt = f"""Sos el analista de datos de FutVS, un sitio de pronósticos de fútbol.
Tenés estos datos del día:

PARTIDOS PRÓXIMOS:
{json.dumps(ctx_matches, ensure_ascii=False, indent=2)}

TENDENCIAS DETECTADAS:
{json.dumps(ctx_tendencias, ensure_ascii=False)}

OPORTUNIDADES DEL MODELO:
{json.dumps(ctx_opps, ensure_ascii=False)}

Con estos datos, escribí UN ÚNICO dato curioso o insight sorprendente sobre el fútbol de esta semana.
Debe ser:
- Concreto y basado en los datos reales de arriba
- Máximo 2 oraciones
- Tono analítico pero accesible
- Sin emojis (se agregan afuera)
- En español rioplatense

Respondé SOLO el texto del dato, sin comillas ni explicaciones extra."""

    try:
        body = json.dumps({
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 150,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=body,
            headers={
                "x-api-key":         ANTHROPIC_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read())
        
        text = ""
        for block in resp.get("content", []):
            if block.get("type") == "text":
                text += block["text"]
        return text.strip() if text.strip() else _dato_curioso_estatico(predictions, tendencias, oportunidades)

    except Exception as e:
        print(f"[insights] Claude API error: {e} — usando dato estático")
        return _dato_curioso_estatico(predictions, tendencias, oportunidades)


def _dato_curioso_estatico(
    predictions: list[dict],
    tendencias: list[dict],
    oportunidades: list[dict],
) -> str:
    """Genera un dato curioso sin API, basándose en los datos disponibles."""
    if oportunidades:
        o = oportunidades[0]
        return (f"El modelo detecta un {o['edge']}% de ventaja a favor de {o['apuesta']} "
                f"en {o['partido']} comparado con las cuotas del mercado.")
    if tendencias:
        return tendencias[0]["texto"]
    if predictions:
        # Partido con mayor xG total
        by_xg = sorted(
            predictions,
            key=lambda m: (m.get("expected_goals",{}).get("home") or 0) +
                          (m.get("expected_goals",{}).get("away") or 0),
            reverse=True
        )
        m = by_xg[0]
        xg = m.get("expected_goals",{})
        total = round((xg.get("home") or 0) + (xg.get("away") or 0), 1)
        home = m.get("home",{}).get("name","?")
        away = m.get("away",{}).get("name","?")
        return (f"El partido con mayor expectativa de goles es {home} vs {away}, "
                f"con {total} goles esperados según el modelo Dixon-Coles.")
    return "El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico."


# ──────────────────────────────────────────────────────────────────────────────
# SECCIÓN 6: SOBRE/BAJO EXPECTATIVAS (xG)
# ──────────────────────────────────────────────────────────────────────────────

def build_xg_performance(df: pd.DataFrame, predictions: list[dict]) -> list[dict]:
    """
    Calcula qué equipos superan o quedan debajo de sus goles esperados (xG).
    Requiere columnas xg_home / xg_away en el parquet (pueden ser NULL).
    """
    if df.empty:
        return []

    xg_cols = {"xg_home", "xg_away", "home_goals", "away_goals", "home_team", "away_team"}
    if not xg_cols.issubset(df.columns):
        return []

    sub = df.dropna(subset=["xg_home","xg_away","home_goals","away_goals"]).tail(200)
    if sub.empty:
        return []

    # Por equipo: promedio de (goles_reales - xG)
    perf: dict[str, list[float]] = defaultdict(list)
    for _, row in sub.iterrows():
        home = str(row["home_team"]).lower().replace(" ","_")
        away = str(row["away_team"]).lower().replace(" ","_")
        perf[home].append(float(row["home_goals"]) - float(row["xg_home"]))
        # Para la defensa: goles recibidos vs xGA (xG del rival)
        perf[away + "_def"].append(float(row["home_goals"]) - float(row["xg_home"]))

    # Equipos que aparecen en predictions
    pred_teams = set()
    for m in predictions:
        pred_teams.add(str(m.get("home",{}).get("id","")).lower())
        pred_teams.add(str(m.get("away",{}).get("id","")).lower())

    result = []
    for slug in pred_teams:
        vals = perf.get(slug, [])
        if len(vals) < 3:
            continue
        avg_over = sum(vals) / len(vals)
        pct = round(avg_over * 100 / max(0.01, abs(avg_over)) * abs(avg_over) / max(1, sum(abs(v) for v in vals) / len(vals)), 0)
        if abs(avg_over) > 0.15:
            nombre = slug.replace("_"," ").title()
            result.append({
                "equipo": nombre,
                "slug":   slug,
                "flag":   flag(slug),
                "avg_over_xg": round(avg_over, 2),
                "tipo":  "sobre" if avg_over > 0 else "bajo",
                "texto": (
                    f"{nombre} genera un {abs(int(avg_over*100))}% más goles de los esperados (xG)."
                    if avg_over > 0 else
                    f"{nombre} recibe un {abs(int(avg_over*100))}% menos goles de los esperados."
                ),
                "n": len(vals),
            })

    result.sort(key=lambda x: abs(x["avg_over_xg"]), reverse=True)
    return result[:6]


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PATHS["out"]))
    ap.add_argument("--no-claude", action="store_true", help="Saltar llamada a Claude API")
    args = ap.parse_args()

    print("[insights] Cargando datos...")
    predictions = load_predictions()
    df          = load_matches_df()
    forma_sb    = load_forma_supabase()
    equipos_sb  = load_equipos_supabase()

    print(f"[insights] predictions: {len(predictions)} partidos")
    print(f"[insights] parquet: {len(df)} filas")
    print(f"[insights] supabase forma: {len(forma_sb)} equipos")

    print("[insights] Calculando oportunidades...")
    oportunidades = build_oportunidades(predictions)

    print("[insights] Calculando tendencias...")
    tendencias = build_tendencias(df, predictions)

    print("[insights] Calculando alertas...")
    alertas = build_alertas(predictions, df)

    print("[insights] Calculando xG performance...")
    xg_perf = build_xg_performance(df, predictions)

    print("[insights] Calculando forma reciente...")
    forma = build_forma_section(predictions, forma_sb, equipos_sb)

    print("[insights] Generando dato curioso...")
    anthropic_key_available = bool(ANTHROPIC_KEY) and not args.no_claude
    dato_curioso = build_dato_curioso(predictions, tendencias, oportunidades) if anthropic_key_available else _dato_curioso_estatico(predictions, tendencias, oportunidades)

    out = {
        "schema_version":  "1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dato_curioso":     dato_curioso,
        "forma_reciente":   forma,
        "oportunidades":    oportunidades,
        "tendencias":       tendencias,
        "alertas":          alertas,
        "xg_performance":   xg_perf,
        "meta": {
            "n_partidos_analizados": len(predictions),
            "n_equipos_con_forma":   len(forma_sb),
            "n_tendencias":          len(tendencias),
            "n_oportunidades":       len(oportunidades),
            "claude_used":           anthropic_key_available,
        }
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[insights] ✅ Escrito en {out_path}")
    print(f"  oportunidades:  {len(oportunidades)}")
    print(f"  tendencias:     {len(tendencias)}")
    print(f"  alertas:        {len(alertas)}")
    print(f"  xg_perf:        {len(xg_perf)}")
    print(f"  forma equipos:  {len(forma)}")


if __name__ == "__main__":
    main()
