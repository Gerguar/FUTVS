"""
src/generate_sitemap.py
Genera web/sitemap.xml con todas las URLs de partidos y páginas estáticas.
Se corre junto con el workflow de predict para mantenerlo actualizado.
"""
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

SITE     = "https://futversus.com"
ROOT     = Path(__file__).resolve().parents[1]
OUT_PATH = ROOT / "web" / "sitemap.xml"

SB_URL = os.environ.get("SUPABASE_URL", "https://dyeouwqtebrvioesrbcf.supabase.co").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")

def slugify(s):
    import unicodedata, re
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    s = s.lower()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    return s.strip('-')

def sb_get(path):
    if not SB_KEY:
        return []
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Accept": "application/json",
        "Prefer": "count=none",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[sitemap] sb error: {e}")
        return []

def main():
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")

    # Páginas estáticas
    static_urls = [
        {"loc": SITE,                      "priority": "1.0", "changefreq": "daily"},
        {"loc": f"{SITE}/comparador",      "priority": "0.8", "changefreq": "weekly"},
        {"loc": f"{SITE}/ranking",         "priority": "0.8", "changefreq": "daily"},
        {"loc": f"{SITE}/insights",        "priority": "0.7", "changefreq": "daily"},
        {"loc": f"{SITE}/sobre-nosotros",  "priority": "0.4", "changefreq": "monthly"},
        {"loc": f"{SITE}/metodologia",     "priority": "0.5", "changefreq": "monthly"},
        {"loc": f"{SITE}/glosario",        "priority": "0.4", "changefreq": "monthly"},
    ]

    # Partidos: últimos 30 días + próximos 60 días
    cutoff_past  = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    cutoff_fut   = (now + timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S")

    partidos = sb_get(
        f"partidos?select=id,fecha,"
        f"equipo_local:equipo_local_id(nombre),"
        f"equipo_visitante:equipo_visitante_id(nombre)"
        f"&fecha=gte.{cutoff_past}&fecha=lte.{cutoff_fut}"
        f"&order=fecha&limit=500"
    )

    partido_urls = []
    for p in partidos:
        home = (p.get("equipo_local") or {}).get("nombre", "")
        away = (p.get("equipo_visitante") or {}).get("nombre", "")
        fecha = (p.get("fecha") or "")[:10]
        if not home or not away or not fecha:
            continue
        slug = f"{slugify(home)}-vs-{slugify(away)}-{fecha}"
        # Partidos futuros tienen más prioridad (más clicks)
        priority = "0.9" if fecha >= today else "0.6"
        partido_urls.append({
            "loc": f"{SITE}/partido/{slug}",
            "priority": priority,
            "changefreq": "daily" if fecha >= today else "monthly",
            "lastmod": today,
        })

    print(f"[sitemap] {len(static_urls)} páginas estáticas, {len(partido_urls)} partidos")

    # Generar XML
    lines = ['<?xml version="1.0" encoding="UTF-8"?>']
    lines.append('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">')

    for u in static_urls + partido_urls:
        lines.append("  <url>")
        lines.append(f"    <loc>{u['loc']}</loc>")
        if "lastmod" in u:
            lines.append(f"    <lastmod>{u['lastmod']}</lastmod>")
        else:
            lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append(f"    <changefreq>{u['changefreq']}</changefreq>")
        lines.append(f"    <priority>{u['priority']}</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")

    OUT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"[sitemap] → {OUT_PATH} ({len(partido_urls) + len(static_urls)} URLs)")

if __name__ == "__main__":
    main()
