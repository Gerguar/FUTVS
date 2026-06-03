#!/usr/bin/env python3
"""
add_pagination.py — Agrega paginación de 9 partidos por página al home de FutVS.

Uso:
    python add_pagination.py
    python add_pagination.py --html web/index.html --per-page 9
"""

import argparse
from pathlib import Path

# ── CSS de paginación ──────────────────────────────────────────────────────────

CSS_PAGINATION = r"""
/* ── PAGINACIÓN ─────────────────────────── */
.pagination{display:flex;align-items:center;justify-content:center;gap:.5rem;padding:1rem 1rem 2.5rem;position:relative;z-index:1}
.pg-btn{background:transparent;border:1px solid var(--border);color:var(--muted);width:36px;height:36px;border-radius:8px;cursor:pointer;font-family:'JetBrains Mono',monospace;font-size:.82rem;font-weight:700;transition:all .18s;display:flex;align-items:center;justify-content:center}
.pg-btn:hover:not(:disabled){border-color:var(--green);color:var(--green)}
.pg-btn.active{background:var(--green);border-color:var(--green);color:#080a0c}
.pg-btn:disabled{opacity:.3;cursor:not-allowed}
.pg-btn-arrow{width:36px;height:36px;font-size:1rem}
.pg-info{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:var(--faint);letter-spacing:1px;margin:0 .4rem}
/* ── FIN PAGINACIÓN CSS ── */
"""

# ── HTML del contenedor de paginación (va debajo de matches-container) ─────────

HTML_PAGINATION = """
  <div id="pagination-bar" class="pagination" style="display:none"></div>"""

# ── JS: reemplaza renderMatches con versión paginada ──────────────────────────

OLD_RENDER_MATCHES = """function renderMatches(filter) {
  const c = document.getElementById('matches-container')
  const list = filter==='all' ?
    matches : matches.filter(m=>m.leagueKey===filter)
  if (!list.length) {
    c.innerHTML = `<div class="loader" style="color:var(--faint)">No hay partidos disponibles</div>`
    return
  }
  c.innerHTML = list.map(m=>`"""

NEW_RENDER_MATCHES = """// ── PAGINACIÓN ──
const PAGE_SIZE = 9
let currentPage = 1
let currentFilter = 'all'

function renderMatches(filter) {
  if (filter !== undefined) { currentFilter = filter; currentPage = 1 }
  const c = document.getElementById('matches-container')
  const list = currentFilter==='all' ?
    matches : matches.filter(m=>m.leagueKey===currentFilter)
  if (!list.length) {
    c.innerHTML = `<div class="loader" style="color:var(--faint)">No hay partidos disponibles</div>`
    document.getElementById('pagination-bar').style.display = 'none'
    return
  }
  const totalPages = Math.ceil(list.length / PAGE_SIZE)
  if (currentPage > totalPages) currentPage = totalPages
  const start = (currentPage - 1) * PAGE_SIZE
  const pageList = list.slice(start, start + PAGE_SIZE)
  renderPagination(totalPages, list.length)
  c.innerHTML = pageList.map(m=>`"""

OLD_FILTER_MATCHES = """function filterMatches(key,btn) {
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  renderMatches(key)
}"""

NEW_FILTER_MATCHES = """function filterMatches(key,btn) {
  document.querySelectorAll('.filter-btn').forEach(b=>b.classList.remove('active'))
  btn.classList.add('active')
  renderMatches(key)
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
  // Anterior
  html += `<button class="pg-btn pg-btn-arrow" onclick="goToPage(${currentPage-1})" ${currentPage===1?'disabled':''}>‹</button>`
  // Páginas
  for (let i = 1; i <= totalPages; i++) {
    if (totalPages > 7) {
      // Mostrar: primera, última, actual y vecinas, con "..." en el medio
      const show = i===1 || i===totalPages || Math.abs(i-currentPage)<=1
      if (!show) {
        if (i===2 || i===totalPages-1) { html += `<span class="pg-info">…</span>`; }
        continue
      }
    }
    html += `<button class="pg-btn ${i===currentPage?'active':''}" onclick="goToPage(${i})">${i}</button>`
  }
  // Siguiente
  html += `<button class="pg-btn pg-btn-arrow" onclick="goToPage(${currentPage+1})" ${currentPage===totalPages?'disabled':''}>›</button>`
  // Info
  html += `<span class="pg-info">${start}-${end} de ${total}</span>`
  bar.innerHTML = html
}"""


def patch(html_path: Path, per_page: int) -> None:
    src = html_path.read_text(encoding="utf-8")

    # Ajustar PAGE_SIZE si se pide un valor distinto de 9
    new_render = NEW_RENDER_MATCHES.replace("const PAGE_SIZE = 9", f"const PAGE_SIZE = {per_page}")

    # 1 — CSS
    css_marker = "</style>"
    if "pagination" in src and "pg-btn" in src:
        print("[patch] ⏭  CSS: paginación ya existe, salteando")
    elif css_marker in src:
        src = src.replace(css_marker, CSS_PAGINATION + css_marker, 1)
        print("[patch] ✅ CSS de paginación insertado")
    else:
        print("[patch] ⚠️  CSS: no se encontró </style>")

    # 2 — HTML del pagination-bar (después de matches-container, antes del CTA)
    bar_marker = "<!-- CTA -->"
    if 'id="pagination-bar"' in src:
        print("[patch] ⏭  HTML: pagination-bar ya existe, salteando")
    elif bar_marker in src:
        src = src.replace(bar_marker, HTML_PAGINATION + "\n  " + bar_marker, 1)
        print("[patch] ✅ pagination-bar insertado")
    else:
        print("[patch] ⚠️  HTML: no se encontró <!-- CTA -->")

    # 3 — JS: reemplazar renderMatches
    if "currentPage" in src:
        print("[patch] ⏭  JS: paginación ya existe, salteando")
    elif OLD_RENDER_MATCHES in src:
        src = src.replace(OLD_RENDER_MATCHES, new_render, 1)
        print("[patch] ✅ renderMatches reemplazado con versión paginada")
    else:
        print("[patch] ⚠️  JS: no se encontró renderMatches original exacto")

    # 4 — JS: reemplazar filterMatches y agregar goToPage + renderPagination
    if "goToPage" in src:
        print("[patch] ⏭  JS: goToPage ya existe, salteando")
    elif OLD_FILTER_MATCHES in src:
        src = src.replace(OLD_FILTER_MATCHES, NEW_FILTER_MATCHES, 1)
        print("[patch] ✅ filterMatches + goToPage + renderPagination insertados")
    else:
        print("[patch] ⚠️  JS: no se encontró filterMatches original exacto")

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
