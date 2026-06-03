#!/usr/bin/env python3
"""
add_hero_cards.py — Agrega las cards de comparación (Messi vs Ronaldo, River vs Boca)
al hero del home de FutVS.

Uso:
    python add_hero_cards.py
    python add_hero_cards.py --html web/index.html
"""

import argparse
from pathlib import Path

CSS_HERO_CARDS = r"""
/* ── HERO COMPARISON CARDS ─────────────────────────── */
.hero{position:relative;text-align:center;overflow:hidden;min-height:340px;display:flex;align-items:center;justify-content:center}
.hero-inner{position:relative;z-index:2;display:flex;align-items:center;justify-content:space-between;width:100%;max-width:1200px;margin:0 auto;padding:3.5rem 1.5rem;gap:1.2rem}
.hero-center{text-align:center;flex:1;min-width:0}
.cmp-card{background:rgba(13,16,20,.84);border:1px solid rgba(255,255,255,.1);border-radius:14px;padding:.9rem 1.05rem;width:210px;flex-shrink:0;backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px)}
.cmp-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:.6rem;padding-bottom:.55rem;border-bottom:1px solid rgba(255,255,255,.07)}
.cmp-players{display:flex;align-items:center;gap:5px}
.cmp-name{font-size:.6rem;font-weight:800;color:#fff;letter-spacing:.3px}
.cmp-sep{font-size:.52rem;color:#4b5563}
.cmp-badge{font-size:.5rem;font-family:'JetBrains Mono',monospace;color:#22c55e;background:rgba(34,197,94,.12);border:1px solid rgba(34,197,94,.25);padding:2px 7px;border-radius:20px;letter-spacing:1px;text-transform:uppercase;white-space:nowrap}
.cmp-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.cmp-row{display:grid;grid-template-columns:1fr auto auto;gap:3px;align-items:center;padding:3.5px 0;border-bottom:1px solid rgba(255,255,255,.035)}
.cmp-row:last-child{border-bottom:none}
.cmp-cat{color:#6b7280;font-size:.6rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmp-val{font-family:'JetBrains Mono',monospace;font-weight:700;font-size:.68rem;text-align:right;min-width:32px;white-space:nowrap}
.cmp-footer{margin-top:.55rem;padding-top:.5rem;border-top:1px solid rgba(255,255,255,.05);font-size:.56rem;color:#4b5563;line-height:1.5}
.cmp-footer strong{font-weight:700}
@media(max-width:900px){.cmp-card{display:none}}
@media(max-width:700px){.hero-inner{padding:2.5rem 1rem}}
/* ── FIN HERO CARDS CSS ── */
"""

HTML_HERO_CARDS_LEFT = """
    <!-- CARD MESSI VS RONALDO -->
    <div class="cmp-card">
      <div class="cmp-header">
        <div class="cmp-players">
          <div class="cmp-dot" style="background:#22c55e"></div>
          <span class="cmp-name">Messi</span>
          <span class="cmp-sep">vs</span>
          <span class="cmp-name" style="color:#f59e0b">Cristiano</span>
          <div class="cmp-dot" style="background:#f59e0b"></div>
        </div>
        <span class="cmp-badge">GOAT</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🏅 Balón de Oro</span>
        <span class="cmp-val" style="color:#22c55e">8</span>
        <span class="cmp-val" style="color:#f59e0b">5</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">⚽ Goles oficiales</span>
        <span class="cmp-val" style="color:#22c55e">850+</span>
        <span class="cmp-val" style="color:#f59e0b">930+</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🎯 Asistencias</span>
        <span class="cmp-val" style="color:#22c55e">380+</span>
        <span class="cmp-val" style="color:#f59e0b">250+</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🌍 Copa del Mundo</span>
        <span class="cmp-val" style="color:#22c55e">🇦🇷 1</span>
        <span class="cmp-val" style="color:#ef4444">✖ 0</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🏆 Champions</span>
        <span class="cmp-val" style="color:#22c55e">4</span>
        <span class="cmp-val" style="color:#f59e0b">5</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🎖️ Títulos totales</span>
        <span class="cmp-val" style="color:#22c55e">45+</span>
        <span class="cmp-val" style="color:#f59e0b">35+</span>
      </div>
      <div class="cmp-footer">
        Más goles: <strong style="color:#f59e0b">Cristiano</strong><br>
        Más asistencias: <strong style="color:#22c55e">Messi</strong>
      </div>
    </div>"""

HTML_HERO_CARDS_RIGHT = """
    <!-- CARD RIVER VS BOCA -->
    <div class="cmp-card">
      <div class="cmp-header">
        <div class="cmp-players">
          <div class="cmp-dot" style="background:#dc2626"></div>
          <span class="cmp-name" style="color:#fca5a5">River</span>
          <span class="cmp-sep">vs</span>
          <span class="cmp-name" style="color:#fbbf24">Boca</span>
          <div class="cmp-dot" style="background:#1d4ed8"></div>
        </div>
        <span class="cmp-badge">CLÁSICO</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🏆 Libertadores</span>
        <span class="cmp-val" style="color:#fca5a5">4</span>
        <span class="cmp-val" style="color:#fbbf24">6</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🇦🇷 Torneos locales</span>
        <span class="cmp-val" style="color:#fca5a5">38+</span>
        <span class="cmp-val" style="color:#fbbf24">35+</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">⚡ Superclásicos</span>
        <span class="cmp-val" style="color:#fca5a5;font-size:.55rem">Parejo</span>
        <span class="cmp-val" style="color:#fbbf24;font-size:.55rem">Parejo</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🌐 Intercontinental</span>
        <span class="cmp-val" style="color:#fca5a5">1</span>
        <span class="cmp-val" style="color:#fbbf24">3</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🏟️ Final Madrid 2018</span>
        <span class="cmp-val" style="color:#22c55e;font-size:.6rem">✔ Ganó</span>
        <span class="cmp-val" style="color:#ef4444;font-size:.6rem">✖ Perdió</span>
      </div>
      <div class="cmp-row">
        <span class="cmp-cat">🔥 Rivalidad</span>
        <span class="cmp-val" style="color:#f59e0b;font-size:.58rem;grid-column:2/-1">Eterna ⚡</span>
      </div>
      <div class="cmp-footer">
        Más Libertadores: <strong style="color:#fbbf24">Boca</strong><br>
        Más ligas arg.: <strong style="color:#fca5a5">River</strong>
      </div>
    </div>"""


OLD_HERO = """  <div class="hero">
    <div class="hero-bg"></div><div class="hero-overlay"></div>
    <div class="hero-content">
      <div class="hero-eyebrow">Análisis estadístico de fútbol</div>
      <h1>Pronósticos de <span>Fútbol</span></h1>
      <p>Análisis inteligente para los próximos partidos de élite</p>
      <div class="hero-sub">DATOS ACTUALIZADOS · FACTORES PONDERADOS · ESTADÍSTICAS REALES</div>
    </div>
  </div>"""

NEW_HERO = """  <div class="hero">
    <div class="hero-bg"></div><div class="hero-overlay"></div>
    <div class="hero-inner">""" + HTML_HERO_CARDS_LEFT + """
      <div class="hero-center">
        <div class="hero-eyebrow">Análisis estadístico de fútbol</div>
        <h1>Pronósticos de <span>Fútbol</span></h1>
        <p>Análisis inteligente para los próximos partidos de élite</p>
        <div class="hero-sub">DATOS ACTUALIZADOS · FACTORES PONDERADOS · ESTADÍSTICAS REALES</div>
      </div>""" + HTML_HERO_CARDS_RIGHT + """
    </div>
  </div>"""


def patch(html_path: Path) -> None:
    src = html_path.read_text(encoding='utf-8')

    # 1 — CSS
    css_marker = '</style>'
    if 'cmp-card' in src:
        print('[patch] ⏭  CSS: cards ya existen, salteando')
    elif css_marker in src:
        src = src.replace(css_marker, CSS_HERO_CARDS + css_marker, 1)
        print('[patch] ✅ CSS de hero cards insertado')
    else:
        print('[patch] ⚠️  CSS: no se encontró </style>')

    # 2 — HTML: reemplazar hero
    if 'hero-inner' in src:
        print('[patch] ⏭  HTML: hero-inner ya existe, salteando')
    elif OLD_HERO in src:
        src = src.replace(OLD_HERO, NEW_HERO, 1)
        print('[patch] ✅ Hero reemplazado con cards')
    else:
        print('[patch] ⚠️  HTML: hero original no encontrado exacto')
        # Intentar busqueda flexible
        if 'hero-content' in src and 'hero-eyebrow' in src:
            print('[patch] ℹ️  El hero existe pero con estructura diferente — revisá manualmente')

    html_path.write_text(src, encoding='utf-8')
    print(f'[patch] ✅ {html_path} guardado ({len(src):,} bytes)')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', default='web/index.html')
    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.exists():
        print(f'[patch] ❌ No se encontró {html_path}')
        return
    print(f'[patch] Aplicando hero cards sobre {html_path} ...')
    patch(html_path)


if __name__ == '__main__':
    main()
