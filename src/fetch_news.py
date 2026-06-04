"""
Fetch weekly football news from NewsAPI and save to web/data/insights_semana.json.

Runs every Monday via GitHub Actions.
Requires: NEWS_API_KEY environment variable.

Output format:
{
  "updated": "2025-06-09T08:00:00Z",
  "week": "2 jun – 8 jun 2025",
  "noticias": [
    {
      "titulo": "...",
      "resumen": "...",
      "fuente": "...",
      "url": "...",
      "fecha": "2025-06-07"
    },
    ...
  ]
}
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path


NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")
OUT_PATH = Path("web/data/insights_semana.json")

# Palabras clave para buscar noticias impactantes de fútbol
QUERIES = [
    "fútbol Champions League",
    "fútbol Mundial 2026",
    "Premier League LaLiga Serie A",
    "Messi Mbappé Haaland Vinicius",
]

# Fuentes de fútbol confiables (NewsAPI source IDs)
FOOTBALL_SOURCES = [
    "marca", "as", "sport", "mundo-deportivo",
    "the-sport-bible", "bleacher-report", "espn",
    "four-four-two", "bbc-sport",
]


def fetch_articles(query: str, from_date: str, to_date: str, page_size: int = 5) -> list[dict]:
    params = urllib.parse.urlencode({
        "q": query,
        "from": from_date,
        "to": to_date,
        "language": "es",
        "sortBy": "popularity",
        "pageSize": page_size,
        "apiKey": NEWS_API_KEY,
    })
    url = f"https://newsapi.org/v2/everything?{params}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FutVersus/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        return data.get("articles", [])
    except Exception as e:
        print(f"  ! Error fetching '{query}': {e}", file=sys.stderr)
        return []


def score_article(a: dict) -> float:
    """Score an article by relevance signals."""
    score = 0.0
    title = (a.get("title") or "").lower()
    desc = (a.get("description") or "").lower()
    combined = title + " " + desc

    # Keywords de alto impacto
    high = ["champions", "mundial", "gol", "récord", "fichaje", "título",
            "messi", "mbappé", "haaland", "vinicius", "balón de oro",
            "eliminado", "campeón", "final", "histórico"]
    for kw in high:
        if kw in combined:
            score += 2.0

    # Penalizar si parece clickbait o sin info
    if not a.get("description") or len(a.get("description", "")) < 50:
        score -= 3.0
    if "[removed]" in (a.get("title") or "") or "[removed]" in (a.get("description") or ""):
        score -= 10.0

    return score


def clean_text(text: str, max_len: int = 160) -> str:
    """Clean and truncate text."""
    if not text:
        return ""
    text = text.strip()
    # Remove source name appended at end (e.g. " - ESPN")
    for sep in [" - ", " | ", " – "]:
        if sep in text:
            parts = text.rsplit(sep, 1)
            if len(parts[1]) < 40:
                text = parts[0].strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "…"
    return text


def main() -> None:
    if not NEWS_API_KEY:
        print("ERROR: NEWS_API_KEY not set", file=sys.stderr)
        sys.exit(1)

    now = datetime.now(timezone.utc)
    # Rango: últimos 7 días
    from_dt = now - timedelta(days=7)
    from_date = from_dt.strftime("%Y-%m-%d")
    to_date = now.strftime("%Y-%m-%d")

    # Label de semana en español
    months_es = ["ene","feb","mar","abr","may","jun","jul","ago","sep","oct","nov","dic"]
    week_label = (
        f"{from_dt.day} {months_es[from_dt.month-1]} – "
        f"{now.day} {months_es[now.month-1]} {now.year}"
    )

    print(f"[fetch-news] Buscando noticias del {week_label}...")

    # Recopilar artículos de todas las queries
    seen_urls: set[str] = set()
    candidates: list[dict] = []

    for q in QUERIES:
        articles = fetch_articles(q, from_date, to_date, page_size=5)
        print(f"  · '{q}': {len(articles)} artículos")
        for a in articles:
            url = a.get("url", "")
            if url in seen_urls or not url:
                continue
            seen_urls.add(url)
            candidates.append(a)

    # Ordenar por score
    candidates.sort(key=score_article, reverse=True)

    # Tomar las mejores 4
    top = candidates[:4]

    noticias = []
    for a in top:
        titulo = clean_text(a.get("title") or "", max_len=100)
        resumen = clean_text(a.get("description") or "", max_len=160)
        fuente = (a.get("source") or {}).get("name") or "Desconocido"
        url = a.get("url") or "#"
        fecha_raw = (a.get("publishedAt") or "")[:10]

        if not titulo or not resumen:
            continue

        noticias.append({
            "titulo": titulo,
            "resumen": resumen,
            "fuente": fuente,
            "url": url,
            "fecha": fecha_raw,
        })

    if not noticias:
        print("! No se encontraron noticias válidas. Usando fallback.", file=sys.stderr)
        noticias = [{
            "titulo": "Sin noticias disponibles esta semana",
            "resumen": "No se pudieron obtener noticias de fútbol para esta semana.",
            "fuente": "FutVersus",
            "url": "#",
            "fecha": to_date,
        }]

    output = {
        "updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "week": week_label,
        "noticias": noticias,
    }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fetch-news] ✓ {len(noticias)} noticias guardadas en {OUT_PATH}")
    for n in noticias:
        print(f"  · {n['titulo'][:80]}")


if __name__ == "__main__":
    main()
