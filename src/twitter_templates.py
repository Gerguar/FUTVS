"""
Plantillas de tweets + utilitarios (banderas, clasificacion acierto, formato).

Mantener este archivo "tonto": solo datos + funciones puras. La logica de
estado (que ya se posteo, throttles, etc.) vive en src/twitter_bot.py.

Reglas de la cuenta (TOS X 2022):
- La bio DEBE decir "Automated account · Managed by @TU_HANDLE".
- No DMs, no replies, no follows automaticos en MVP.
"""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
from typing import Iterable

# ─────────────────────────────────────────────────────────────
# Banderas por nombre de seleccion (Mundial 2026, 48 equipos)
# Se matchea por nombre normalizado (lowercase, sin acentos) contra
# equipos.nombre de Supabase. Si no encuentra, default a '⚽'.
# ─────────────────────────────────────────────────────────────
FLAGS_BY_NAME: dict[str, str] = {
    # Conmebol
    "argentina": "🇦🇷", "brasil": "🇧🇷", "uruguay": "🇺🇾", "colombia": "🇨🇴",
    "ecuador": "🇪🇨", "paraguay": "🇵🇾",
    # Concacaf (3 anfitriones)
    "mexico": "🇲🇽", "estados unidos": "🇺🇸", "canada": "🇨🇦",
    "panama": "🇵🇦", "costa rica": "🇨🇷", "honduras": "🇭🇳", "jamaica": "🇯🇲",
    "haiti": "🇭🇹", "curacao": "🇨🇼", "surinam": "🇸🇷", "trinidad y tobago": "🇹🇹",
    # UEFA
    "espana": "🇪🇸", "francia": "🇫🇷", "alemania": "🇩🇪", "italia": "🇮🇹",
    "inglaterra": "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "paises bajos": "🇳🇱", "portugal": "🇵🇹", "belgica": "🇧🇪",
    "croacia": "🇭🇷", "suiza": "🇨🇭", "dinamarca": "🇩🇰", "polonia": "🇵🇱",
    "austria": "🇦🇹", "noruega": "🇳🇴", "suecia": "🇸🇪", "ucrania": "🇺🇦",
    "republica checa": "🇨🇿", "turquia": "🇹🇷", "serbia": "🇷🇸", "escocia": "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "gales": "🏴󠁧󠁢󠁷󠁬󠁳󠁿",
    "irlanda": "🇮🇪", "hungria": "🇭🇺", "grecia": "🇬🇷", "rumania": "🇷🇴",
    # AFC
    "japon": "🇯🇵", "corea del sur": "🇰🇷", "iran": "🇮🇷", "australia": "🇦🇺",
    "arabia saudita": "🇸🇦", "qatar": "🇶🇦", "irak": "🇮🇶", "emiratos arabes unidos": "🇦🇪",
    "uzbekistan": "🇺🇿", "jordania": "🇯🇴",
    # CAF
    "marruecos": "🇲🇦", "senegal": "🇸🇳", "egipto": "🇪🇬", "tunez": "🇹🇳",
    "argelia": "🇩🇿", "nigeria": "🇳🇬", "ghana": "🇬🇭", "camerun": "🇨🇲",
    "costa de marfil": "🇨🇮", "mali": "🇲🇱", "sudafrica": "🇿🇦", "cabo verde": "🇨🇻",
    # OFC
    "nueva zelanda": "🇳🇿",
}


def _norm(s: str) -> str:
    """Normalizacion para matchear FLAGS_BY_NAME: lowercase + sin acentos."""
    import unicodedata
    n = unicodedata.normalize("NFD", (s or "").lower())
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return " ".join(n.split())


def flag_for(team_name: str) -> str:
    """Devuelve emoji de bandera para un nombre de seleccion. Fallback '⚽'."""
    return FLAGS_BY_NAME.get(_norm(team_name), "⚽")


# ─────────────────────────────────────────────────────────────
# Clasificacion de acierto (mismo criterio que web/index.html L2009-2031)
# top1 == real            -> "acertado"
# diff(top1, top2) <= 10pp -> "ajustado"
# resto                    -> "no_acertado"
# ─────────────────────────────────────────────────────────────

def classify_result(prob_local: float, prob_empate: float, prob_visitante: float,
                    goles_local: int, goles_visitante: int) -> str:
    probs = [(prob_local, "H"), (prob_empate, "D"), (prob_visitante, "A")]
    probs_sorted = sorted(probs, key=lambda x: -x[0])
    top1_val, top1_outcome = probs_sorted[0]
    top2_val = probs_sorted[1][0]
    real = ("H" if goles_local > goles_visitante
            else "A" if goles_local < goles_visitante
            else "D")
    if top1_outcome == real:
        return "acertado"
    if (top1_val - top2_val) <= 10.0:
        return "ajustado"
    return "no_acertado"


# ─────────────────────────────────────────────────────────────
# Formateadores de tweet
# ─────────────────────────────────────────────────────────────

# IMPORTANTE: desde el 20-abr-2026 X cobra $0.20 por tweet con URL
# (vs $0.015 sin URL). Por eso *no* incluimos links en los tweets — el
# trafico al sitio depende del link en la bio de @FutVersus_ y de hashtags
# como #FutVersus / #Mundial2026 que la gente pueda googlear.
#
# CTA = call to action. Texto que invita a visitar el sitio SIN incluir URL.
# Ojo: poner "futversus.com" o cualquier patron de URL hace que X lo cobre
# como tweet con link ($0.20). Usar solo texto plano y emoji.

CTA = "🔎 Pronóstico completo y datos en nuestra web - ↗ bio"
HASHTAGS = "#FutVersus #Mundial2026"


def _fmt_hour_ar(iso_utc: str) -> str:
    """Formato HH:MM en hora Argentina (UTC-3) desde un ISO en UTC.
    Supabase a veces devuelve los timestamps sin tz info (naive); en ese caso
    los tratamos como UTC (mismo criterio que el frontend con _asUTC)."""
    s = iso_utc.replace("Z", "+00:00") if iso_utc.endswith("Z") else iso_utc
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    ar = dt.astimezone(timezone(timedelta(hours=-3)))
    return ar.strftime("%H:%M")


def _round1(x: float) -> str:
    """Redondeo a 1 decimal, mostrando entero cuando aplica (67.0 -> 67)."""
    r = round(float(x), 1)
    return f"{int(r)}" if r == int(r) else f"{r:.1f}"


def tweet_prematch(home_name: str, away_name: str,
                   prob_local: float, prob_empate: float, prob_visitante: float,
                   kickoff_iso_utc: str, partido_id: int,
                   competicion: str = "MUNDIAL 2026") -> str:
    """
    Pronostico pre-partido. ~200 chars sin URL (ver nota sobre pricing arriba).

    ⚽ MUNDIAL 2026 · 16:00 ART
    🇲🇽 México vs 🇿🇦 Sudáfrica

    🟢 Local        67.7%
    🟡 Empate       23.0%
    🔴 Visitante     9.3%

    #FutVersus #Mundial2026
    """
    fh = flag_for(home_name)
    fa = flag_for(away_name)
    hour = _fmt_hour_ar(kickoff_iso_utc)
    return (
        f"⚽ {competicion} · {hour} ART\n"
        f"{fh} {home_name} vs {fa} {away_name}\n"
        f"\n"
        f"🟢 {home_name:<14} {_round1(prob_local)}%\n"
        f"🟡 Empate          {_round1(prob_empate)}%\n"
        f"🔴 {away_name:<14} {_round1(prob_visitante)}%\n"
        f"\n"
        f"{CTA}\n"
        f"{HASHTAGS}"
    )


def tweet_pick_of_day(home_name: str, away_name: str,
                      prob_local: float, prob_empate: float, prob_visitante: float,
                      kickoff_iso_utc: str, partido_id: int,
                      competicion: str = "MUNDIAL 2026") -> str:
    """
    Pick del dia. ~220 chars sin URL.

    ⭐ PARTIDO DEL DIA · MUNDIAL 2026 · 16:00 ART
    🇦🇷 Argentina vs 🇲🇦 Marruecos

    🟢 Argentina       58.4%
    🟡 Empate          24.1%
    🔴 Marruecos       17.5%

    🔎 Analisis completo y factores en nuestra web - ↗ bio
    #FutVersus #Mundial2026
    """
    fh = flag_for(home_name)
    fa = flag_for(away_name)
    hour = _fmt_hour_ar(kickoff_iso_utc)
    return (
        f"⭐ PARTIDO DEL DÍA · {competicion} · {hour} ART\n"
        f"{fh} {home_name} vs {fa} {away_name}\n"
        f"\n"
        f"🟢 {home_name:<14} {_round1(prob_local)}%\n"
        f"🟡 Empate          {_round1(prob_empate)}%\n"
        f"🔴 {away_name:<14} {_round1(prob_visitante)}%\n"
        f"\n"
        f"🔎 Análisis completo y factores en nuestra web - ↗ bio\n"
        f"{HASHTAGS}"
    )


def tweet_postmortem(home_name: str, away_name: str,
                     prob_local: float, prob_empate: float, prob_visitante: float,
                     goles_local: int, goles_visitante: int,
                     partido_id: int,
                     competicion: str = "MUNDIAL 2026") -> str:
    """
    Post-mortem. Texto solo lo justo (sin floreos).

    ✅ ACERTAMOS · MUNDIAL 2026
    🇲🇽 México 2-0 🇿🇦 Sudáfrica
    Habíamos dado 67.7% al local · 1ro de 3.

    futversus.com/partido/74
    """
    klass = classify_result(prob_local, prob_empate, prob_visitante,
                            goles_local, goles_visitante)
    if klass == "acertado":
        header = "✅ ACERTAMOS"
    elif klass == "ajustado":
        header = "🟡 AJUSTADO"
    else:
        header = "❌ NO ACERTAMOS"

    fh = flag_for(home_name)
    fa = flag_for(away_name)

    # Detalle del pronostico segun la clasificacion:
    # - ajustado  -> el modelo no marcaba un favorito claro.
    # - resto     -> nombrar el top-1 (equipo o empate) y su probabilidad.
    if klass == "ajustado":
        detalle = "Nuestro pronóstico era un partido ajustado, probabilidades muy similares."
    else:
        # top-1: el outcome de mayor probabilidad (equipo o empate).
        probs = [(prob_local, home_name),
                 (prob_empate, None),  # None = empate
                 (prob_visitante, away_name)]
        probs_sorted = sorted(probs, key=lambda x: -x[0])
        top_val, top_team = probs_sorted[0]
        if top_team is None:
            detalle = f"Dábamos como más probable el empate con el {_round1(top_val)}% de probabilidad."
        else:
            detalle = f"Dábamos como probable ganador a {top_team} con el {_round1(top_val)}% de probabilidad."

    return (
        f"{header} · {competicion}\n"
        f"{fh} {home_name} {goles_local}-{goles_visitante} {away_name} {fa}\n"
        f"\n"
        f"{detalle}\n"
        f"\n"
        f"📊 Análisis detallado del partido en nuestra web - ↗ bio\n"
        f"{HASHTAGS}"
    )


def tweet_lesion(jugador: str, equipo_name: str, severidad: str,
                 delta_pp: float, contexto: str = "") -> str:
    """
    Alerta de lesion (cuando aparece un ajuste nuevo en wc2026_ajustes_lesiones).

    🚨 BAJA · 🇪🇸 España
    Lamine Yamal sale del próximo partido.
    Impacto en nuestro modelo: -3.0pp para España.

    Más detalles: futversus.com/insights
    """
    flag = flag_for(equipo_name)
    if severidad in ("critico", "danger"):
        head = "🚨 BAJA"
    else:
        head = "⚠️  EN DUDA"
    extra = f"\n{contexto}" if contexto else ""
    return (
        f"{head} · {flag} {equipo_name}\n"
        f"{jugador}.{extra}\n"
        f"\n"
        f"Impacto en el modelo: -{abs(delta_pp):.1f}pp para {equipo_name}.\n"
        f"\n"
        f"🔍 Análisis completo del impacto en nuestra web - ↗ bio\n"
        f"{HASHTAGS}"
    )


def truncate_safe(text: str, max_len: int = 280) -> str:
    """X cuenta links como 23 chars. Asumimos 1 link por tweet ~> usar 280."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# ─────────────────────────────────────────────────────────────
# Sanity check
# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Test rapido de las plantillas con datos de ejemplo
    print("─── PREMATCH ───")
    t = tweet_prematch(
        home_name="México", away_name="Sudáfrica",
        prob_local=67.7, prob_empate=23.0, prob_visitante=9.3,
        kickoff_iso_utc="2026-06-11T19:00:00Z", partido_id=74,
    )
    print(t)
    print(f"\n[{len(t)} chars]\n")

    print("─── POSTMORTEM (acertado) ───")
    t = tweet_postmortem(
        home_name="México", away_name="Sudáfrica",
        prob_local=67.7, prob_empate=23.0, prob_visitante=9.3,
        goles_local=2, goles_visitante=0, partido_id=74,
    )
    print(t)
    print(f"\n[{len(t)} chars]\n")

    print("─── POSTMORTEM (ajustado) ───")
    t = tweet_postmortem(
        home_name="Brasil", away_name="Argentina",
        prob_local=38.0, prob_empate=29.0, prob_visitante=33.0,
        goles_local=1, goles_visitante=2, partido_id=99,
    )
    print(t)
    print(f"\n[{len(t)} chars]\n")

    print("─── LESION ───")
    t = tweet_lesion(
        jugador="Lamine Yamal", equipo_name="España",
        severidad="danger", delta_pp=3.0,
        contexto="Lesión muscular, llega justo al debut.",
    )
    print(t)
    print(f"\n[{len(t)} chars]\n")
