#!/usr/bin/env python3
"""
add_pagination.py (v2) — Agrega paginación de 9 partidos por página al home de FutVS.

Uso:
    python add_pagination.py
    python add_pagination.py --html web/index.html --per-page 9
"""

import argparse
from pathlib import Path

CSS_PAGINATION = r"""
/* ── PAGINACIÓN ─────────────────────────── */
.pagination{display:flex;align-items:center;justify-content:center;gap:.5rem;padding:1rem 1rem 2.5rem;position:relative;z-index:1;flex-wrap:wrap}
.pg-btn{background:transparent;border:1px solid var(--border);color:var(--muted);width:36px;height:36px;border-radius:8px;cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:.82rem;font-weight:700;transition:all .18s;display:flex;align-items:center;justify-content:center}
.pg-btn:hover:not(:disabled){border-color:var(--green);color:var(--green)}
.pg-btn.active{background:var(--green);border-color:var(--green);color:#080a0c}
.pg-btn:disabled{opacity:.3;cursor:not-allowed}
.pg-info{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:var(--faint);letter-spacing:1px;margin:0 .4rem}
/* ── FIN PAGINACIÓN CSS ── */
"""

HTML_PAGINATION = """
  <div id="pagination-bar" class="pagination" style="display:none"></div>"""

# Código JS nuevo que reemplaza renderMatches y filterMatches
JS_PAGINATION = r"""// ── PAGINACIÓN ──
const PAGE_SIZE = {PAGE_SIZE}
let currentPage = 1
let currentFilter = 'all'

function renderMatches(filter) {
  if (filter !== undefined) { currentFilter = filter; currentPage = 1 }
  const c = document.getElementById('matches-container')
  let list = currentFilter==='all' ? matches : matches.filter(m=>m.leagueKey===currentFilter)
  // Subfiltro por grupo: solo aplica cuando estamos en el filtro Mundial
  if (currentFilter === 'mundial' && currentGroupFilter !== 'all') {
    list = list.filter(m => m.grupo === currentGroupFilter)
  }
  if (!list.length) {
    const OFFSEASON = {laliga:'La Liga',premier:'Premier League',seriea:'Serie A',bundesliga:'Bundesliga',ligue1:'Ligue 1'}
    const isOffseason = OFFSEASON[currentFilter] && !matches.some(m => m.leagueKey === currentFilter)
    const msg = isOffseason
      ? `${OFFSEASON[currentFilter]} arranca en agosto.<br><span style="font-size:.78rem;color:var(--faint)">Mientras tanto: Mundial 2026 desde el 11 de junio.</span>`
      : 'No hay partidos disponibles'
    c.innerHTML = `<div class="loader" style="color:var(--faint);text-align:center;padding:2rem">${msg}</div>`
    document.getElementById('pagination-bar').style.display = 'none'
    return
  }
  const upcoming = list.filter(m => m.status !== 'finalizado')
  const finished = list.filter(m => m.status === 'finalizado')
    .sort((a,b) => new Date(b.kickoffIso) - new Date(a.kickoffIso))
  const allSorted = [...upcoming, ...finished]
  const totalPages = Math.ceil(allSorted.length / PAGE_SIZE)
  if (currentPage > totalPages) currentPage = totalPages
  const start = (currentPage - 1) * PAGE_SIZE
  const pageItems = allSorted.slice(start, start + PAGE_SIZE)
  // Separar upcoming y finished dentro de la página actual
  const pageUpcoming = pageItems.filter(m => m.status !== 'finalizado')
  const pageFinished = pageItems.filter(m => m.status === 'finalizado')
  let html = pageUpcoming.map(matchCardHtml).join('')
  if (pageFinished.length) {
    html += `<div class="matches-divider">Finalizados (últimos 7 días) · ${pageFinished.length}</div>`
    html += pageFinished.map(matchCardHtml).join('')
  }
  c.innerHTML = html
  renderPagination(totalPages, allSorted.length)
}

function goToPage(p) {
  currentPage = p
  renderMatches()
  document.getElementById('matches-container').scrollIntoView({behavior:'smooth', block:'start'})
}

function renderPagination(totalPages, total) {
  const bar = document.getElementById('pagination-bar')
  if (totalPages <= 1) { bar.style.display = 'none'; return }
  bar.style.display = 'flex'
  const start = (currentPage - 1) * PAGE_SIZE + 1
  const end = Math.min(currentPage * PAGE_SIZE, total)
  let html = ''
  html += `<button class="pg-btn" onclick="goToPage(${currentPage-1})" ${currentPage===1?'disabled':''}>‹</button>`
  for (let i = 1; i <= totalPages; i++) {
    if (totalPages > 7) {
      const show = i===1 || i===totalPages || Math.abs(i-currentPage)<=1
      if (!show) {
        if (i===2 || i===totalPages-1) html += `<span class="pg-info">…</span>`
        continue
      }
    }
    html += `<button class="pg-btn ${i===currentPage?'active':''}" onclick="goToPage(${i})">${i}</button>`
  }
  html += `<button class="pg-btn" onclick="goToPage(${currentPage+1})" ${currentPage===totalPages?'disabled':''}>›</button>`
  html += `<span class="pg-info">${start}–${end} de ${total}</span>`
  bar.innerHTML = html
}

function filterMatches(key,btn) {
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  const gf = document.getElementById('group-filters')
  if (gf) {
    if (key === 'mundial') {
      gf.classList.add('visible')
      currentGroupFilter = 'all'
      document.querySelectorAll('.group-btn').forEach((b,i)=>b.classList.toggle('active', i===0))
    } else {
      gf.classList.remove('visible')
    }
  }
  renderMatches(key)
}
function filterByGroup(g, btn) {
  currentGroupFilter = g
  document.querySelectorAll('.group-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  renderMatches('mundial')
}"""

OLD_BLOCK = """function renderMatches(filter) {
  const c = document.getElementById('matches-container')
  let list = filter==='all' ? matches : matches.filter(m=>m.leagueKey===filter)
  // Subfiltro por grupo: solo aplica cuando estamos en el filtro Mundial
  if (filter === 'mundial' && currentGroupFilter !== 'all') {
    list = list.filter(m => m.grupo === currentGroupFilter)
  }
  if (!list.length) {
    // Ligas top-5 fuera de temporada (mayo-agosto): no es un bug, no hay fixture cargado.
    const OFFSEASON = {laliga:'La Liga',premier:'Premier League',seriea:'Serie A',bundesliga:'Bundesliga',ligue1:'Ligue 1'}
    const isOffseason = OFFSEASON[filter] && !matches.some(m => m.leagueKey === filter)
    const msg = isOffseason
      ? `${OFFSEASON[filter]} arranca en agosto.<br><span style="font-size:.78rem;color:var(--faint)">Mientras tanto: Mundial 2026 desde el 11 de junio.</span>`
      : 'No hay partidos disponibles'
    c.innerHTML = `<div class="loader" style="color:var(--faint);text-align:center;padding:2rem">${msg}</div>`
    return
  }
  const upcoming = list.filter(m => m.status !== 'finalizado')
  // Finalizados ordenados por fecha del partido descendente (mas reciente primero).
  const finished = list.filter(m => m.status === 'finalizado')
    .sort((a,b) => new Date(b.kickoffIso) - new Date(a.kickoffIso))
  let html = upcoming.map(matchCardHtml).join('')
  if (finished.length) {
    html += `<div class="matches-divider">Finalizados (últimos 7 días) · ${finished.length}</div>`
    html += finished.map(matchCardHtml).join('')
  }
  c.innerHTML = html
}
function filterMatches(key,btn) {
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  // Mostrar/ocultar la sub-fila de grupos segun si esta seleccionado Mundial
  const gf = document.getElementById('group-filters')
  if (gf) {
    if (key === 'mundial') {
      gf.classList.add('visible')
      // Reset al sub-filtro 'TODOS' cada vez que entras al filtro Mundial
      currentGroupFilter = 'all'
      document.querySelectorAll('.group-btn').forEach((b,i)=>b.classList.toggle('active', i===0))
    } else {
      gf.classList.remove('visible')
    }
  }
  renderMatches(key)
}
function filterByGroup(g, btn) {
  currentGroupFilter = g
  document.querySelectorAll('.group-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  renderMatches('mundial')
}"""


def patch(html_path: Path, per_page: int) -> None:
    src = html_path.read_text(encoding="utf-8")
    new_js = JS_PAGINATION.replace("{PAGE_SIZE}", str(per_page))

    # 1 — CSS
    css_marker = "</style>"
    if "pg-btn" in src:
        print("[patch] ⏭  CSS: paginación ya existe, salteando")
    elif css_marker in src:
        src = src.replace(css_marker, CSS_PAGINATION + css_marker, 1)
        print("[patch] ✅ CSS de paginación insertado")
    else:
        print("[patch] ⚠️  CSS: no se encontró </style>")

    # 2 — HTML pagination-bar
    bar_marker = "<!-- CTA -->"
    if 'id="pagination-bar"' in src:
        print("[patch] ⏭  HTML: pagination-bar ya existe, salteando")
    elif bar_marker in src:
        src = src.replace(bar_marker, HTML_PAGINATION + "\n  " + bar_marker, 1)
        print("[patch] ✅ pagination-bar insertado")
    else:
        print("[patch] ⚠️  HTML: no se encontró <!-- CTA -->")

    # 3 — JS: reemplazar bloque completo
    if "currentPage" in src:
        print("[patch] ⏭  JS: paginación ya existe, salteando")
    elif OLD_BLOCK in src:
        src = src.replace(OLD_BLOCK, new_js, 1)
        print("[patch] ✅ renderMatches + filterMatches reemplazados con versión paginada")
    else:
        print("[patch] ⚠️  JS: no se encontró el bloque exacto — revisá manualmente")

    html_path.write_text(src, encoding="utf-8")
    print(f"[patch] ✅ {html_path} guardado ({len(src):,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", default="web/index.html")
    ap.add_argument("--per-page", type=int, default=9)
    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.exists():
        print(f"[patch] ❌ No se encontró {html_path}")
        return
    print(f"[patch] Aplicando paginación ({args.per_page} partidos/página) sobre {html_path} ...")
    patch(html_path, args.per_page)


if __name__ == "__main__":
    main()
