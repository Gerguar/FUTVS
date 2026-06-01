"""
generate_insights.py — Genera web/data/insights.json para la página Insights de FutVS.

Fuentes:
  1. data/predictions.json      → probabilidades, xG, elo, odds de mercado
  2. Supabase forma_reciente    → últimos 5 W/D/L por equipo
  3. data/matches.parquet       → historial para tendencias estadísticas
  4. Claude API + web_search    → alertas y tendencias reales (lesiones, suspensiones, etc.)

Uso:
  python -m src.generate_insights --out web/data/insights.json
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

import pandas as pd

# ──────────────────────────────────────────────────────────────────────────────
# CONFIG
# ──────────────────────────────────────────────────────────────────────────────

PATHS = {
    "predictions": Path("data/predictions.json"),
    "matches":     Path("data/matches.parquet"),
    "out":         Path("web/data/insights.json"),
}

SB_URL        = os.environ.get("SUPABASE_URL", "")
SB_KEY        = os.environ.get("SUPABASE_SERVICE_KEY", "")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

VALUE_THRESHOLD      = 0.06
MIN_MATCHES_TEND     = 5
WINDOW_TEND          = 10

FLAG_BY_SLUG: dict[str, str] = {
    "argentina": "🇦🇷", "spain": "🇪🇸", "brasil": "🇧🇷", "brazil": "🇧🇷",
    "france": "🇫🇷", "germany": "🇩🇪", "england": "🏴󠁧󠁢󠁥󠁮󠁧󠁿", "portugal": "🇵🇹",
    "netherlands": "🇳🇱", "italy": "🇮🇹", "japan": "🇯🇵", "south_korea": "🇰🇷",
    "korea_republic": "🇰🇷", "morocco": "🇲🇦", "canada": "🇨🇦", "mexico": "🇲🇽",
    "usa": "🇺🇸", "united_states": "🇺🇸", "croatia": "🇭🇷", "senegal": "🇸🇳",
    "ecuador": "🇪🇨", "switzerland": "🇨🇭", "denmark": "🇩🇰", "sweden": "🇸🇪",
    "poland": "🇵🇱", "australia": "🇦🇺", "ghana": "🇬🇭", "cameroon": "🇨🇲",
    "serbia": "🇷🇸", "costa_rica": "🇨🇷", "saudi_arabia": "🇸🇦", "iran": "🇮🇷",
    "qatar": "🇶🇦", "tunisia": "🇹🇳", "colombia": "🇨🇴", "uruguay": "🇺🇾",
    "chile": "🇨🇱", "paraguay": "🇵🇾", "venezuela": "🇻🇪", "peru": "🇵🇪",
    "egypt": "🇪🇬", "nigeria": "🇳🇬", "ivory_coast": "🇨🇮", "belgium": "🇧🇪",
    "austria": "🇦🇹", "turkey": "🇹🇷", "ukraine": "🇺🇦", "czechia": "🇨🇿",
    "slovakia": "🇸🇰", "slovenia": "🇸🇮", "albania": "🇦🇱", "scotland": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "romania": "🇷🇴", "norway": "🇳🇴", "israel": "🇮🇱", "georgia": "🇬🇪",
    "new_zealand": "🇳🇿", "jamaica": "🇯🇲", "honduras": "🇭🇳", "panama": "🇵🇦",
    "real_madrid": "⚪", "fc_barcelona": "🔵🔴", "manchester_city": "🩵",
    "arsenal": "🔴", "liverpool": "🔴", "chelsea": "🔵", "barcelona": "🔵🔴",
    "atletico_madrid": "🔴⚪", "bayern_munich": "🔴", "borussia_dortmund": "🟡",
    "inter_milan": "🔵⚫", "ac_milan": "🔴⚫", "paris_sg": "🔵🔴",
}

def flag(slug: str) -> str:
    clean = slug.lower().replace(" ", "_").replace("-", "_")
    return FLAG_BY_SLUG.get(clean, "⚽")


# ──────────────────────────────────────────────────────────────────────────────
# SUPABASE
# ──────────────────────────────────────────────────────────────────────────────

def sb_get(path: str) -> list:
    if not SB_URL or not SB_KEY:
        return []
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
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
        return []
    with open(p) as f:
        data = json.load(f)
    return data.get("matches", [])

def load_matches_df() -> pd.DataFrame:
    p = PATHS["matches"]
    if not p.exists():
        return pd.DataFrame()
    try:
        return pd.read_parquet(p)
    except Exception as e:
        print(f"[insights] error leyendo parquet: {e}")
        return pd.DataFrame()

def load_forma_supabase() -> dict[str, list[str]]:
    rows = sb_get("forma_reciente?select=equipo_id,forma")
    return {str(r.get("equipo_id", "")): r.get("forma", []) or [] for r in rows}

def load_equipos_supabase() -> dict[str, dict]:
    rows = sb_get("equipos?select=id,nombre,abreviacion,pais,escudo_url")
    return {str(r["id"]): r for r in rows}


# ──────────────────────────────────────────────────────────────────────────────
# CLAUDE API — ALERTAS Y TENDENCIAS CON WEB SEARCH
# ──────────────────────────────────────────────────────────────────────────────

def _claude_request(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 1500) -> dict:
    """Llamada base a la API de Claude."""
    body: dict = {
        "model": "claude-sonnet-4-5",
        "max_tokens": max_tokens,
        "messages": messages,
    }
    if tools:
        body["tools"] = tools

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "x-api-key":         ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
            "anthropic-beta":    "web-search-2025-03-05",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def _extract_text(resp: dict) -> str:
    """Extrae todo el texto de una respuesta de Claude."""
    return "".join(
        block.get("text", "")
        for block in resp.get("content", [])
        if block.get("type") == "text"
    ).strip()


def build_alertas_tendencias_claude(predictions: list[dict]) -> tuple[list[dict], list[dict], str]:
    """
    Usa Claude con web_search para generar:
    - alertas: suspensiones, lesiones, racha negativa
    - tendencias: estadísticas recientes reales
    - dato_curioso: un insight destacado

    Retorna (alertas, tendencias, dato_curioso).
    Si falla, retorna listas vacías y string vacío.
    """
    if not ANTHROPIC_KEY:
        return [], [], ""

    # Armar contexto de partidos próximos
    partidos_ctx = []
    for m in predictions[:8]:
        partidos_ctx.append(
            f"{m.get('home',{}).get('name','?')} vs {m.get('away',{}).get('name','?')}"
            + (f" ({m.get('competition',{}).get('name','')})" if m.get('competition') else "")
        )

    partidos_str = "\n".join(f"- {p}" for p in partidos_ctx) if partidos_ctx else "- Partidos internacionales próximos"

    prompt = f"""Sos el analista de datos de FutVS, un sitio de pronósticos de fútbol.

Partidos próximos a analizar:
{partidos_str}

Usá web search para buscar información REAL y ACTUAL sobre:
1. Suspensiones o tarjetas amarillas acumuladas de jugadores clave
2. Lesiones confirmadas de titulares
3. Equipos en mala racha reciente (últimos 4-5 partidos)
4. Tendencias estadísticas reales: equipos que marcan primero frecuentemente, equipos con muchos goles en contra, partidos con Over 2.5 frecuentes
5. Un dato curioso o estadística sorprendente del fútbol actual

Respondé ÚNICAMENTE con un JSON válido con esta estructura exacta (sin texto extra, sin markdown, sin backticks):
{{
  "alertas": [
    {{
      "tipo": "suspension",
      "equipo": "Nombre del equipo",
      "flag": "🏳️",
      "texto": "Descripción concreta de la alerta.",
      "nivel": "warning"
    }}
  ],
  "tendencias": [
    {{
      "tipo": "over",
      "equipo": "Nombre del equipo",
      "flag": "🏳️",
      "texto": "Descripción concreta de la tendencia.",
      "valor": 75,
      "n": 8
    }}
  ],
  "dato_curioso": "Un dato sorprendente y concreto en máximo 2 oraciones."
}}

Reglas:
- Máximo 4 alertas y 4 tendencias
- Solo información verificable y reciente (últimas 2-4 semanas)
- Texto en español rioplatense, tono analítico
- Si no encontrás info real sobre un equipo específico, usá equipos del fútbol europeo o internacional actual
- El JSON debe ser parseable directamente con json.loads()"""

    tools = [{"type": "web_search_20250305", "name": "web_search"}]

    try:
        print("[insights] Llamando a Claude con web search...")
        resp = _claude_request(
            messages=[{"role": "user", "content": prompt}],
            tools=tools,
            max_tokens=2000,
        )

        # Si Claude necesita hacer búsquedas, el stop_reason será "tool_use"
        # Necesitamos continuar la conversación hasta obtener la respuesta final
        messages = [{"role": "user", "content": prompt}]
        max_turns = 5

        for turn in range(max_turns):
            stop_reason = resp.get("stop_reason", "")
            print(f"[insights] Claude turn {turn+1}, stop_reason: {stop_reason}")

            if stop_reason == "end_turn":
                break

            if stop_reason == "tool_use":
                # Claude usó web search, continuamos la conversación
                assistant_content = resp.get("content", [])
                messages.append({"role": "assistant", "content": assistant_content})

                # Agregar resultados de herramientas (Claude los maneja internamente)
                tool_results = []
                for block in assistant_content:
                    if block.get("type") == "tool_use":
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block["id"],
                            "content": "Search completed.",
                        })

                if tool_results:
                    messages.append({"role": "user", "content": tool_results})

                resp = _claude_request(messages=messages, tools=tools, max_tokens=2000)
            else:
                break

        text = _extract_text(resp)
        if not text:
            print("[insights] Claude no devolvió texto")
            return [], [], ""

        # Extraer JSON robusto
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                candidate = part.strip()
                if candidate.startswith("json"):
                    candidate = candidate[4:].strip()
                if candidate.startswith("{"):
                    text = candidate
                    break
        if not text.startswith("{"):
            idx = text.find("{")
            if idx != -1:
                text = text[idx:]
        idx_end = text.rfind("}")
        if idx_end != -1:
            text = text[:idx_end+1]
        text = text.strip()

        parsed = json.loads(text)
        alertas    = parsed.get("alertas", [])
        tendencias = parsed.get("tendencias", [])
        dato       = parsed.get("dato_curioso", "")

        print(f"[insights] Claude generó: {len(alertas)} alertas, {len(tendencias)} tendencias")
        return alertas, tendencias, dato

    except json.JSONDecodeError as e:
        print(f"[insights] Error parseando JSON de Claude: {e}")
        print(f"[insights] Respuesta recibida: {text[:300] if 'text' in dir() else 'N/A'}")
        return [], [], ""
    except Exception as e:
        print(f"[insights] Error llamando a Claude: {e}")
        return [], [], ""


# ──────────────────────────────────────────────────────────────────────────────
# OPORTUNIDADES (modelo vs mercado)
# ──────────────────────────────────────────────────────────────────────────────

def build_oportunidades(predictions: list[dict]) -> list[dict]:
    opps = []
    for m in predictions:
        probs  = m.get("probabilities", {})
        market = m.get("market_probabilities")
        if not market:
            continue
        home_name = m.get("home", {}).get("name", "?")
        away_name = m.get("away", {}).get("name", "?")
        for side, label, slug in [
            ("home", home_name, str(m.get("home", {}).get("id", "")).lower()),
            ("away", away_name, str(m.get("away", {}).get("id", "")).lower()),
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
                })
    opps.sort(key=lambda x: x["edge"], reverse=True)
    return opps[:5]


# ──────────────────────────────────────────────────────────────────────────────
# TENDENCIAS ESTADÍSTICAS (parquet fallback)
# ──────────────────────────────────────────────────────────────────────────────

def build_tendencias_estadisticas(df: pd.DataFrame, predictions: list[dict]) -> list[dict]:
    """Calcula tendencias desde el parquet histórico como fallback."""
    if df.empty:
        return []
    needed = {"home_team", "away_team", "home_goals", "away_goals"}
    if not needed.issubset(df.columns):
        return []

    df = df.dropna(subset=["home_goals", "away_goals"]).copy()
    df["total_goals"] = df["home_goals"] + df["away_goals"]

    pred_teams = set()
    for m in predictions:
        pred_teams.add(str(m.get("home", {}).get("id", "")).lower())
        pred_teams.add(str(m.get("away", {}).get("id", "")).lower())

    tendencias = []
    for slug in list(pred_teams)[:20]:
        mask = (
            df["home_team"].str.lower().str.replace(" ", "_") == slug
        ) | (
            df["away_team"].str.lower().str.replace(" ", "_") == slug
        )
        sub = df[mask].copy()
        if "date" in sub.columns:
            sub = sub.sort_values("date", ascending=False)
        sub = sub.head(WINDOW_TEND)
        if len(sub) < MIN_MATCHES_TEND:
            continue

        n = len(sub)
        nombre = slug.replace("_", " ").title()
        over_pct = round((sub["total_goals"] > 2.5).mean() * 100)
        if over_pct >= 70:
            tendencias.append({
                "tipo": "over", "equipo": nombre, "flag": flag(slug),
                "valor": over_pct, "n": n,
                "texto": f"El {over_pct}% de los partidos de {nombre} terminaron con +2.5 goles.",
            })

        cs_home = ((df["home_team"].str.lower().str.replace(" ", "_") == slug) & (df["away_goals"] == 0))
        cs_away = ((df["away_team"].str.lower().str.replace(" ", "_") == slug) & (df["home_goals"] == 0))
        cs_total = (cs_home | cs_away).sum()
        cs_pct = round(cs_total / n * 100)
        if cs_pct >= 50:
            tendencias.append({
                "tipo": "cs", "equipo": nombre, "flag": flag(slug),
                "valor": cs_pct, "n": n,
                "texto": f"{nombre} mantuvo el arco en cero en {cs_total} de sus últimos {n} partidos.",
            })

    seen = set()
    result = []
    for t in sorted(tendencias, key=lambda x: x["valor"], reverse=True):
        if t["equipo"] not in seen:
            seen.add(t["equipo"])
            result.append(t)
        if len(result) >= 4:
            break
    return result


# ──────────────────────────────────────────────────────────────────────────────
# FORMA RECIENTE
# ──────────────────────────────────────────────────────────────────────────────

def build_forma_section(predictions, forma_sb, equipos_sb) -> list[dict]:
    if forma_sb and equipos_sb:
        rows = []
        for eid, eq in equipos_sb.items():
            forma_raw = forma_sb.get(eid, [])
            if not forma_raw:
                continue
            forma_norm = [r.upper() if r.upper() in ("W","D","L") else "?" for r in forma_raw[:5]]
            wins = forma_norm.count("W")
            rows.append({
                "slug":   eq.get("abreviacion", "").lower(),
                "nombre": eq.get("nombre", ""),
                "pais":   eq.get("pais", ""),
                "escudo": eq.get("escudo_url", ""),
                "forma":  forma_norm,
                "wins":   wins,
                "draws":  forma_norm.count("D"),
            })
        rows.sort(key=lambda x: (x["wins"], x["draws"]), reverse=True)
        return rows[:8]
    return []


# ──────────────────────────────────────────────────────────────────────────────
# XG PERFORMANCE
# ──────────────────────────────────────────────────────────────────────────────

def build_xg_performance(df: pd.DataFrame, predictions: list[dict]) -> list[dict]:
    if df.empty:
        return []
    xg_cols = {"xg_home", "xg_away", "home_goals", "away_goals", "home_team", "away_team"}
    if not xg_cols.issubset(df.columns):
        return []
    sub = df.dropna(subset=["xg_home","xg_away","home_goals","away_goals"]).tail(200)
    if sub.empty:
        return []

    perf: dict[str, list[float]] = defaultdict(list)
    for _, row in sub.iterrows():
        home = str(row["home_team"]).lower().replace(" ","_")
        away = str(row["away_team"]).lower().replace(" ","_")
        perf[home].append(float(row["home_goals"]) - float(row["xg_home"]))
        perf[away].append(float(row["away_goals"]) - float(row["xg_away"]))

    pred_teams = set()
    for m in predictions:
        pred_teams.add(str(m.get("home",{}).get("id","")).lower())
        pred_teams.add(str(m.get("away",{}).get("id","")).lower())

    result = []
    for slug in pred_teams:
        vals = perf.get(slug, [])
        if len(vals) < 3:
            continue
        avg = sum(vals) / len(vals)
        if abs(avg) > 0.15:
            nombre = slug.replace("_"," ").title()
            result.append({
                "equipo": nombre, "slug": slug, "flag": flag(slug),
                "avg_over_xg": round(avg, 2),
                "tipo": "sobre" if avg > 0 else "bajo",
                "texto": (
                    f"{nombre} genera un {abs(int(avg*100))}% más goles de los esperados (xG)."
                    if avg > 0 else
                    f"{nombre} recibe un {abs(int(avg*100))}% menos goles de los esperados."
                ),
                "n": len(vals),
            })

    result.sort(key=lambda x: abs(x["avg_over_xg"]), reverse=True)
    return result[:4]


# ──────────────────────────────────────────────────────────────────────────────
# DATO CURIOSO FALLBACK
# ──────────────────────────────────────────────────────────────────────────────

def dato_curioso_fallback(predictions, tendencias, oportunidades) -> str:
    if oportunidades:
        o = oportunidades[0]
        return (f"El modelo detecta un {o['edge']}% de ventaja a favor de {o['apuesta']} "
                f"en {o['partido']} comparado con las cuotas del mercado.")
    if tendencias:
        return tendencias[0]["texto"]
    if predictions:
        by_xg = sorted(
            predictions,
            key=lambda m: (m.get("expected_goals",{}).get("home") or 0) +
                          (m.get("expected_goals",{}).get("away") or 0),
            reverse=True
        )
        m = by_xg[0]
        xg = m.get("expected_goals", {})
        total = round((xg.get("home") or 0) + (xg.get("away") or 0), 1)
        home  = m.get("home",{}).get("name","?")
        away  = m.get("away",{}).get("name","?")
        return (f"El partido con mayor expectativa de goles es {home} vs {away}, "
                f"con {total} goles esperados según el modelo Dixon-Coles.")
    return "El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico."


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(PATHS["out"]))
    ap.add_argument("--no-claude", action="store_true")
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

    # Claude con web search para alertas, tendencias y dato curioso
    alertas_claude    = []
    tendencias_claude = []
    dato_curioso      = ""

    if ANTHROPIC_KEY and not args.no_claude:
        alertas_claude, tendencias_claude, dato_curioso = build_alertas_tendencias_claude(predictions)

    # Fallbacks estadísticos si Claude no devolvió datos
    print("[insights] Calculando tendencias estadísticas (parquet)...")
    tendencias_stat = build_tendencias_estadisticas(df, predictions)

    # Usar Claude si tiene datos, sino el estadístico
    tendencias_final = tendencias_claude if tendencias_claude else tendencias_stat

    # Dato curioso fallback
    if not dato_curioso:
        dato_curioso = dato_curioso_fallback(predictions, tendencias_final, oportunidades)

    print("[insights] Calculando xG performance...")
    xg_perf = build_xg_performance(df, predictions)

    print("[insights] Calculando forma reciente...")
    forma = build_forma_section(predictions, forma_sb, equipos_sb)

    # Asegurar que el directorio de salida existe
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out = {
        "schema_version":    "1.1",
        "generated_at_utc":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dato_curioso":      dato_curioso,
        "forma_reciente":    forma,
        "oportunidades":     oportunidades,
        "tendencias":        tendencias_final,
        "alertas":           alertas_claude,
        "xg_performance":    xg_perf,
        "meta": {
            "n_partidos_analizados": len(predictions),
            "n_equipos_con_forma":   len(forma_sb),
            "n_tendencias":          len(tendencias_final),
            "n_alertas":             len(alertas_claude),
            "n_oportunidades":       len(oportunidades),
            "claude_used":           bool(ANTHROPIC_KEY and not args.no_claude),
            "claude_web_search":     bool(alertas_claude or tendencias_claude),
        }
    }

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[insights] ✅ Escrito en {out_path}")
    print(f"  oportunidades:   {len(oportunidades)}")
    print(f"  tendencias:      {len(tendencias_final)} ({'Claude' if tendencias_claude else 'estadístico'})")
    print(f"  alertas:         {len(alertas_claude)} ({'Claude' if alertas_claude else 'ninguna'})")
    print(f"  xg_perf:         {len(xg_perf)}")
    print(f"  forma equipos:   {len(forma)}")
    print(f"  claude_used:     {out['meta']['claude_used']}")


if __name__ == "__main__":
    main()
