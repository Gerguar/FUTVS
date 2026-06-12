"""
Genera web/selecciones/<slug>.html para cada selección en selecciones_elo.
Usa datos de Supabase: selecciones_elo, equipos, jugadores.
"""
from __future__ import annotations
import os, json, re, unicodedata
from pathlib import Path
import urllib.request, urllib.parse

SB_URL = os.environ["SUPABASE_URL"].rstrip("/")
SB_KEY = os.environ["SUPABASE_SERVICE_KEY"]

OUT_DIR = Path(__file__).resolve().parents[1] / "web" / "selecciones"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ── helpers ──────────────────────────────────────────────────────────────────

def sb_get(path: str) -> list[dict]:
    url = f"{SB_URL}/rest/v1/{path}"
    req = urllib.request.Request(url, headers={
        "apikey": SB_KEY,
        "Authorization": f"Bearer {SB_KEY}",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def fmt_elo(elo: int) -> str:
    return f"{elo:,}".replace(",", ".")


# ── datos ────────────────────────────────────────────────────────────────────

print("Cargando selecciones_elo...")
selecciones = sb_get("selecciones_elo?select=*&order=ranking.asc")

print("Cargando equipos...")
equipos = sb_get("equipos?select=id,nombre,pais,escudo_url,color_prim,color_sec,elo_externo,elo_ranking")

print("Cargando jugadores (top por seleccion)...")
jugadores_all = sb_get(
    "jugadores?select=id,nombre,equipo_id,posicion,rating,valor_mercado,pace,shooting,passing,dribbling,defending,physic"
    "&rating=not.is.null&order=rating.desc&limit=2000"
)

# índices
equipos_by_pais  = {}
equipos_by_nombre = {}
for eq in equipos:
    if eq.get("pais"):
        equipos_by_pais[eq["pais"].lower()] = eq
    equipos_by_nombre[eq["nombre"].lower()] = eq

jugadores_by_equipo: dict[int, list] = {}
for j in jugadores_all:
    eid = j.get("equipo_id")
    if eid:
        jugadores_by_equipo.setdefault(eid, []).append(j)

# ── template HTML ─────────────────────────────────────────────────────────────

def posicion_label(p: str | None) -> str:
    if not p: return "—"
    p = p.upper()
    if "GK" in p or "POR" in p: return "POR"
    if "CB" in p or "DF" in p or "DEF" in p: return "DEF"
    if "MF" in p or "CM" in p or "DM" in p or "AM" in p or "MED" in p: return "MED"
    if "FW" in p or "ST" in p or "LW" in p or "RW" in p or "DEL" in p: return "DEL"
    return p[:3]

def fmt_valor(v) -> str:
    if not v: return "—"
    v = float(v)
    if v >= 1_000_000: return f"€{v/1_000_000:.1f}M"
    if v >= 1_000: return f"€{v/1_000:.0f}K"
    return f"€{v:.0f}"

def stars(rating: int | None) -> str:
    if not rating: return ""
    filled = min(5, rating // 20)
    return "★" * filled + "☆" * (5 - filled)

def build_page(sel: dict, equipo: dict | None, jugadores: list) -> str:
    nombre    = sel["nombre"]
    code      = sel.get("code", "")
    elo       = sel.get("elo", 0)
    ranking   = sel.get("ranking", "—")
    slug      = slugify(nombre)
    color     = (equipo or {}).get("color_prim") or "#22c55e"
    escudo    = (equipo or {}).get("escudo_url") or ""
    top5      = jugadores[:5]

    # barra de rating relativa (max elo ~2200)
    elo_pct   = min(100, int(elo / 2200 * 100))

    jugadores_html = ""
    for j in top5:
        rating_val = j.get("rating") or 0
        jugadores_html += f"""
        <div style="display:flex;align-items:center;gap:1rem;padding:.75rem 0;border-bottom:1px solid rgba(255,255,255,.07)">
          <div style="min-width:42px;height:42px;border-radius:50%;background:{color}22;border:2px solid {color}44;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:.75rem;font-weight:700;color:{color}">{rating_val}</div>
          <div style="flex:1;min-width:0">
            <div style="font-weight:700;font-size:.9rem;color:#e8eaed;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{j['nombre']}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:.65rem;color:#6b7280;letter-spacing:1px">{posicion_label(j.get('posicion'))} · {fmt_valor(j.get('valor_mercado'))}</div>
          </div>
          <div style="font-size:.75rem;color:#f59e0b;letter-spacing:-1px">{stars(rating_val)}</div>
        </div>"""

    if not jugadores_html:
        jugadores_html = '<div style="color:#6b7280;font-size:.85rem;padding:1rem 0">Sin datos de plantilla disponibles</div>'

    escudo_html = f'<img src="{escudo}" alt="{nombre}" style="width:80px;height:80px;object-fit:contain;filter:drop-shadow(0 4px 12px rgba(0,0,0,.5))">' if escudo else f'<div style="width:80px;height:80px;border-radius:50%;background:{color}33;border:2px solid {color};display:flex;align-items:center;justify-content:center;font-size:2rem">{code}</div>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{nombre} · Mundial 2026 · FutVS</title>
  <meta name="description" content="Análisis estadístico de {nombre} para el Mundial 2026. Elo rating {elo}, ranking #{ranking} mundial. Plantilla, jugadores clave y pronósticos.">
  <meta property="og:title" content="{nombre} · Mundial 2026 · FutVS">
  <meta property="og:description" content="Elo {elo} · Ranking mundial #{ranking} · Análisis y plantilla completa">
  <meta property="og:url" content="https://futversus.com/seleccion/{slug}">
  <meta property="og:type" content="article">
  <link rel="canonical" href="https://futversus.com/seleccion/{slug}">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800;900&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --green:#22c55e;--bg:#080a0c;--card:#0d1117;--border:rgba(255,255,255,.08);
      --muted:#9ca3af;--faint:#4b5563;--sel:{color};
    }}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{background:var(--bg);color:#e8eaed;font-family:'Inter',sans-serif;min-height:100vh}}
    a{{color:var(--green);text-decoration:none}}
    a:hover{{text-decoration:underline}}
    .nav{{display:flex;align-items:center;justify-content:space-between;padding:1rem 2rem;border-bottom:1px solid var(--border);position:sticky;top:0;background:rgba(8,10,12,.95);backdrop-filter:blur(8px);z-index:100}}
    .nav-logo{{font-size:1.3rem;font-weight:900;font-style:italic;color:#fff}}
    .nav-logo span{{color:var(--green)}}
    .nav-links{{display:flex;gap:1.5rem;font-size:.85rem;color:var(--muted)}}
    .hero{{padding:3rem 2rem 2rem;max-width:900px;margin:0 auto;display:flex;align-items:center;gap:2rem;flex-wrap:wrap}}
    .hero-badge{{font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:2px;color:var(--sel);text-transform:uppercase;margin-bottom:.5rem;font-weight:700}}
    .hero-title{{font-size:clamp(2rem,6vw,3.2rem);font-weight:900;letter-spacing:-1.5px;line-height:1.1}}
    .elo-bar{{height:6px;border-radius:3px;background:rgba(255,255,255,.08);overflow:hidden;margin-top:.5rem;width:200px}}
    .elo-fill{{height:100%;border-radius:3px;background:linear-gradient(90deg,var(--sel),{color}88);width:{elo_pct}%;transition:width .8s ease}}
    .card{{background:var(--card);border:1px solid var(--border);border-radius:16px;padding:1.5rem}}
    .card-title{{font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:2px;color:var(--faint);text-transform:uppercase;margin-bottom:1.2rem;font-weight:700}}
    .stat-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1.5rem}}
    .stat-item{{background:rgba(255,255,255,.03);border:1px solid var(--border);border-radius:10px;padding:1rem;text-align:center}}
    .stat-value{{font-family:'JetBrains Mono',monospace;font-size:1.6rem;font-weight:900;color:var(--sel);line-height:1}}
    .stat-label{{font-size:.7rem;color:var(--faint);margin-top:.4rem;letter-spacing:1px;text-transform:uppercase}}
    .main{{max-width:900px;margin:0 auto;padding:0 2rem 4rem;display:grid;grid-template-columns:1fr 1fr;gap:1.5rem}}
    .back-link{{max-width:900px;margin:1.5rem auto;padding:0 2rem;display:block;font-size:.85rem;color:var(--muted)}}
    .footer{{border-top:1px solid var(--border);padding:2rem;text-align:center;font-size:.8rem;color:var(--faint)}}
    @media(max-width:640px){{
      .main{{grid-template-columns:1fr}}
      .hero{{flex-direction:column;text-align:center}}
      .nav-links{{display:none}}
    }}
  </style>
</head>
<body>
  <nav class="nav">
    <a href="https://futversus.com" class="nav-logo">FUT<span>VS</span></a>
    <div class="nav-links">
      <a href="https://futversus.com">Pronósticos</a>
      <a href="https://futversus.com/comparador">Comparador</a>
      <a href="https://futversus.com/ranking">Ranking</a>
    </div>
  </nav>

  <a href="https://futversus.com" class="back-link">← Volver a FutVS</a>

  <div class="hero">
    {escudo_html}
    <div>
      <div class="hero-badge">🌍 Mundial 2026 · Selección</div>
      <h1 class="hero-title">{nombre}</h1>
      <div style="font-family:'JetBrains Mono',monospace;font-size:.85rem;color:var(--muted);margin-top:.5rem">
        Elo <span style="color:{color};font-weight:700">{fmt_elo(elo)}</span> · Ranking mundial <span style="color:{color};font-weight:700">#{ranking}</span>
      </div>
      <div class="elo-bar"><div class="elo-fill"></div></div>
    </div>
  </div>

  <div class="main">
    <div>
      <div class="stat-grid">
        <div class="stat-item">
          <div class="stat-value">{fmt_elo(elo)}</div>
          <div class="stat-label">Elo rating</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">#{ranking}</div>
          <div class="stat-label">Ranking mundial</div>
        </div>
      </div>

      <div class="card">
        <div class="card-title">📊 Sobre este ranking</div>
        <p style="font-size:.85rem;color:var(--muted);line-height:1.7">
          El Elo de <strong style="color:#e8eaed">{nombre}</strong> refleja su rendimiento histórico
          ponderado por importancia del partido, resultado y margen de victoria.
          Un Elo de <strong style="color:{color}">{fmt_elo(elo)}</strong> la posiciona entre las
          {'mejores selecciones del mundo' if ranking <= 10 else 'selecciones de alto nivel' if ranking <= 20 else 'selecciones participantes'} del Mundial 2026.
        </p>
        <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)">
          <a href="https://futversus.com/ranking" style="font-size:.82rem;font-weight:700">Ver ranking completo →</a>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-title">⚽ Jugadores destacados</div>
      {jugadores_html}
      <div style="margin-top:1rem;padding-top:1rem;border-top:1px solid var(--border)">
        <a href="https://futversus.com/comparador?a={slugify(nombre)}" style="font-size:.82rem;font-weight:700">Comparar con otra selección →</a>
      </div>
    </div>
  </div>

  <footer class="footer">
    <div>© 2026 <a href="https://futversus.com">FutVS</a> · Análisis estadístico de fútbol · <a href="https://futversus.com">Ver todos los pronósticos</a></div>
  </footer>
</body>
</html>"""


# ── generar páginas ──────────────────────────────────────────────────────────

generated = 0
for sel in selecciones:
    nombre = sel.get("nombre", "")
    if not nombre:
        continue

    slug = slugify(nombre)

    # buscar equipo asociado (por nombre o país)
    equipo = equipos_by_nombre.get(nombre.lower()) or equipos_by_pais.get(nombre.lower())

    # jugadores del equipo
    jugadores: list = []
    if equipo:
        jugadores = jugadores_by_equipo.get(equipo["id"], [])

    html = build_page(sel, equipo, jugadores)
    out_path = OUT_DIR / f"{slug}.html"
    out_path.write_text(html, encoding="utf-8")
    print(f"  ✓ {slug}.html  (elo={sel.get('elo')}, ranking=#{sel.get('ranking')}, jugadores={len(jugadores)})")
    generated += 1

# índice de selecciones
index_items = ""
for sel in selecciones:
    nombre = sel.get("nombre", "")
    slug   = slugify(nombre)
    elo    = sel.get("elo", 0)
    ranking = sel.get("ranking", "—")
    index_items += f'<li><a href="/seleccion/{slug}">{nombre}</a> <span style="color:#6b7280;font-size:.8rem">· Elo {elo} · #{ranking}</span></li>\n'

index_html = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Selecciones Mundial 2026 · FutVS</title>
  <meta name="description" content="Análisis estadístico de las 32 selecciones del Mundial 2026. Elo ratings, rankings y plantillas.">
  <link rel="canonical" href="https://futversus.com/selecciones">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@700;900&family=JetBrains+Mono:wght@400;700&display=swap" rel="stylesheet">
  <style>
    body{{background:#080a0c;color:#e8eaed;font-family:'Inter',sans-serif;max-width:700px;margin:0 auto;padding:2rem}}
    a{{color:#22c55e}}
    li{{margin:.5rem 0;font-size:.95rem}}
    h1{{font-size:2rem;font-weight:900;margin-bottom:1.5rem}}
  </style>
</head>
<body>
  <a href="https://futversus.com" style="font-size:.85rem;color:#6b7280">← FutVS</a>
  <h1 style="margin-top:1rem">🌍 Selecciones · Mundial 2026</h1>
  <ul style="list-style:none;padding:0">{index_items}</ul>
</body>
</html>"""

(OUT_DIR / "index.html").write_text(index_html, encoding="utf-8")
print(f"\n✅ {generated} páginas generadas en web/selecciones/")
print(f"   + índice en web/selecciones/index.html")
