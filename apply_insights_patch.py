#!/usr/bin/env python3
"""
apply_insights_patch.py — Aplica los cambios de Insights al web/index.html de FutVS.

Uso:
    python apply_insights_patch.py
    python apply_insights_patch.py --html web/index.html --backup

Qué hace:
  1. Cambia "Estadísticas" → "Insights ✦" en el nav, con onclick a showPage('insights')
  2. Agrega el CSS de Insights antes del </style>
  3. Agrega la página <!-- INSIGHTS --> antes del <!-- DETAIL -->
  4. Agrega el JS de Insights antes del </script> final
  5. (Opcional) guarda una copia .bak del original
"""

import argparse
import shutil
from pathlib import Path
from datetime import datetime

# ──────────────────────────────────────────────────────────────────────────────
# TEXTOS A INSERTAR
# ──────────────────────────────────────────────────────────────────────────────

CSS_INSIGHTS = r"""
/* ── INSIGHTS PAGE ─────────────────────────── */
.ins-page{max-width:920px;margin:0 auto;padding:2.5rem 1.5rem 5rem}
.ins-hero{margin-bottom:2.2rem}
.ins-hero-eyebrow{font-family:'JetBrains Mono',monospace;font-size:.62rem;letter-spacing:2.5px;color:var(--green);text-transform:uppercase;margin-bottom:.4rem}
.ins-hero h1{font-size:clamp(1.5rem,4vw,2.4rem);font-weight:900;letter-spacing:-1px;color:#fff;line-height:1.1;margin-bottom:.45rem}
.ins-hero p{color:var(--muted);font-size:.88rem}
.ins-updated{font-family:'JetBrains Mono',monospace;font-size:.62rem;color:var(--faint);margin-top:.4rem}
.ins-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:1.4rem 1.5rem;margin-bottom:1.1rem}
.ins-card-curious{background:linear-gradient(135deg,rgba(34,197,94,.06),rgba(59,130,246,.05));border-color:rgba(34,197,94,.22)}
.ins-card-title{font-family:'JetBrains Mono',monospace;font-size:.68rem;letter-spacing:2px;color:var(--green);text-transform:uppercase;margin-bottom:.85rem;font-weight:700}
.ins-loading{text-align:center;padding:3rem 1rem;color:var(--faint);font-family:'JetBrains Mono',monospace;font-size:.78rem;letter-spacing:1px}
.ins-spinner{display:inline-block;width:18px;height:18px;border:2px solid var(--border2);border-top-color:var(--green);border-radius:50%;animation:inspin .7s linear infinite;margin-bottom:.6rem}
@keyframes inspin{to{transform:rotate(360deg)}}
.ins-table{width:100%;border-collapse:collapse;font-size:.875rem}
.ins-table th{font-family:'JetBrains Mono',monospace;font-size:.58rem;letter-spacing:1.5px;color:var(--faint);text-transform:uppercase;padding:.4rem .7rem;text-align:left;border-bottom:1px solid var(--border)}
.ins-table td{padding:.55rem .7rem;border-bottom:1px solid rgba(255,255,255,.035);color:var(--text);vertical-align:middle}
.ins-table tr:last-child td{border-bottom:none}
.ins-table tr:hover td{background:rgba(255,255,255,.02)}
.ins-form-dots{display:flex;gap:4px;align-items:center}
.ins-dot{width:18px;height:18px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:.55rem;font-weight:900;flex-shrink:0}
.ins-dot-w{background:rgba(34,197,94,.2);color:var(--green);border:1px solid rgba(34,197,94,.35)}
.ins-dot-d{background:rgba(245,158,11,.15);color:var(--amber);border:1px solid rgba(245,158,11,.3)}
.ins-dot-l{background:rgba(239,68,68,.15);color:var(--red);border:1px solid rgba(239,68,68,.3)}
.ins-dot-u{background:var(--surface2);color:var(--faint);border:1px solid var(--border)}
.ins-team-cell{display:flex;align-items:center;gap:.55rem;font-weight:600}
.ins-team-flag{font-size:1rem}
.ins-list{display:flex;flex-direction:column;gap:.65rem}
.ins-item{display:flex;align-items:flex-start;gap:.8rem;font-size:.875rem;color:var(--muted);line-height:1.55;padding:.7rem .9rem;border-radius:8px;background:rgba(255,255,255,.022)}
.ins-item-good{background:rgba(34,197,94,.055);border:1px solid rgba(34,197,94,.14)}
.ins-item-warn{background:rgba(245,158,11,.055);border:1px solid rgba(245,158,11,.14)}
.ins-item-info{background:rgba(59,130,246,.055);border:1px solid rgba(59,130,246,.14)}
.ins-item strong{color:var(--text)}
.ins-icon{font-size:1.15rem;flex-shrink:0;line-height:1.3}
.ins-opps-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:.9rem;margin-top:.3rem}
.ins-opp{background:var(--surface2);border:1px solid var(--border);border-radius:12px;padding:1.05rem 1.1rem;position:relative;overflow:hidden}
.ins-opp::before{content:'';position:absolute;top:0;left:0;right:0;height:2px}
.ins-opp-gold{border-color:rgba(251,191,36,.3)}.ins-opp-gold::before{background:linear-gradient(90deg,#fbbf24,#f59e0b)}
.ins-opp-silver{border-color:rgba(148,163,184,.3)}.ins-opp-silver::before{background:linear-gradient(90deg,#94a3b8,#64748b)}
.ins-opp-bronze{border-color:rgba(180,120,60,.3)}.ins-opp-bronze::before{background:linear-gradient(90deg,#b47c3c,#8b5e2a)}
.ins-opp-std::before{background:var(--green)}
.ins-opp-medal{font-size:1.4rem;margin-bottom:.35rem;line-height:1}
.ins-opp-match{font-size:.9rem;font-weight:800;color:#fff;margin-bottom:.15rem;line-height:1.25}
.ins-opp-bet{font-size:.75rem;color:var(--muted);margin-bottom:.7rem}
.ins-opp-row{display:flex;justify-content:space-between;font-size:.775rem;color:var(--muted);padding:.18rem 0}
.ins-opp-val{font-family:'JetBrains Mono',monospace;font-weight:700;color:var(--text)}
.ins-opp-edge{margin-top:.65rem;font-family:'JetBrains Mono',monospace;font-size:.72rem;font-weight:900;color:var(--green);background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);padding:.28rem .65rem;border-radius:20px;display:inline-block}
.ins-curious-text{font-size:1.05rem;font-weight:700;color:#fff;line-height:1.5;margin-top:.15rem}
.ins-sources{margin-top:1.8rem;padding:.9rem 1.1rem;background:var(--surface2);border-radius:10px;border:1px solid var(--border);font-size:.78rem;color:var(--muted);line-height:1.6}
.ins-sources strong{color:var(--text)}
.ins-sources-label{font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:2px;color:var(--faint);text-transform:uppercase;margin-bottom:.4rem}
.ins-empty{text-align:center;padding:1.5rem;color:var(--faint);font-size:.82rem}
@media(max-width:700px){.ins-page{padding:1.6rem 1rem 4rem}.ins-card{padding:1rem 1rem}.ins-opps-grid{grid-template-columns:1fr}}
@media(max-width:400px){.ins-table{font-size:.8rem}.ins-dot{width:15px;height:15px;font-size:.5rem}}
/* ── FIN INSIGHTS CSS ── */
"""

HTML_INSIGHTS = """
<!-- INSIGHTS -->
<div id="insights" class="page" style="position:relative;z-index:1">
  <div class="ins-page">
    <div class="ins-hero">
      <div class="ins-hero-eyebrow">FutVS · Análisis automatizado</div>
      <h1>📊 Insights</h1>
      <p>Tendencias, alertas y oportunidades calculadas por el modelo cada 6 horas.</p>
      <div class="ins-updated" id="ins-updated">Cargando...</div>
    </div>
    <div id="ins-loader" class="ins-loading">
      <div class="ins-spinner"></div><br>CARGANDO INSIGHTS...
    </div>
    <div id="ins-content" style="display:none">
      <div class="ins-card ins-card-curious">
        <div class="ins-card-title">🧠 Dato curioso del modelo</div>
        <div class="ins-curious-text" id="ins-curioso"></div>
      </div>
      <div class="ins-card">
        <div class="ins-card-title">🔥 Forma reciente</div>
        <table class="ins-table">
          <thead><tr><th>Equipo</th><th>Últimos 5</th><th>G</th><th>E</th><th>P</th></tr></thead>
          <tbody id="ins-forma-tbody"><tr><td colspan="5" class="ins-empty">Sin datos</td></tr></tbody>
        </table>
      </div>
      <div class="ins-card">
        <div class="ins-card-title">🎯 Rendimiento vs expectativas (xG)</div>
        <div class="ins-list" id="ins-xg-list"><div class="ins-empty">Sin datos suficientes</div></div>
      </div>
      <div class="ins-card">
        <div class="ins-card-title">⚠️ Alertas del modelo</div>
        <div class="ins-list" id="ins-alertas-list"><div class="ins-empty">Sin alertas detectadas</div></div>
      </div>
      <div class="ins-card">
        <div class="ins-card-title">📈 Tendencias detectadas</div>
        <div class="ins-list" id="ins-tendencias-list"><div class="ins-empty">Sin tendencias</div></div>
      </div>
      <div class="ins-card">
        <div class="ins-card-title">💎 Oportunidades del algoritmo <span style="font-size:.6rem;color:var(--faint);font-weight:400;font-family:'Inter',sans-serif">(modelo vs mercado)</span></div>
        <div id="ins-no-opps" class="ins-empty" style="display:none">No se detectaron oportunidades claras en partidos próximos.</div>
        <div class="ins-opps-grid" id="ins-opps-grid"></div>
      </div>
      <div class="ins-sources">
        <div class="ins-sources-label">Fuente de datos</div>
        Los Insights se calculan a partir del modelo <strong>Dixon-Coles + XGBoost</strong> de FutVS,
        cruzado con datos de <strong>football-data.org</strong>, <strong>FBref / StatsBomb</strong>
        y el mercado de apuestas vía <strong>The Odds API</strong>.
        Los datos de xG son provistos por Understat/FBref. Actualización cada 6 horas.
        Los pronósticos son estimaciones estadísticas, no garantías de resultado.
      </div>
    </div>
    <div id="ins-error" style="display:none;text-align:center;padding:3rem 1rem">
      <div style="font-size:2rem;margin-bottom:.8rem">😕</div>
      <div style="color:var(--faint);font-size:.88rem">No se pudieron cargar los insights.<br>Intentá de nuevo más tarde.</div>
    </div>
    <div style="margin-top:1.5rem;text-align:center">
      <button onclick="showPage('home')" style="background:transparent;color:var(--green);border:1px solid var(--green);padding:10px 28px;border-radius:30px;font-size:.85rem;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif">← Volver al inicio</button>
    </div>
  </div>
</div>
<!-- /INSIGHTS -->

"""

JS_INSIGHTS = r"""
// ══════════════════════════════════════════
// INSIGHTS — carga data/insights.json
// ══════════════════════════════════════════
const INSIGHTS_URL = 'data/insights.json'
let insightsData = null, insightsLoaded = false

async function loadInsights() {
  if (insightsLoaded && insightsData) { renderInsights(insightsData); return }
  document.getElementById('ins-loader').style.display = 'block'
  document.getElementById('ins-content').style.display = 'none'
  document.getElementById('ins-error').style.display = 'none'
  try {
    const res = await fetch(INSIGHTS_URL + '?t=' + Date.now())
    if (!res.ok) throw new Error('HTTP ' + res.status)
    insightsData = await res.json()
    insightsLoaded = true
    renderInsights(insightsData)
  } catch(e) {
    console.error('[insights]', e)
    document.getElementById('ins-loader').style.display = 'none'
    document.getElementById('ins-error').style.display = 'block'
  }
}

function renderInsights(d) {
  document.getElementById('ins-loader').style.display = 'none'
  document.getElementById('ins-content').style.display = 'block'
  if (d.generated_at_utc) {
    const dt = new Date(d.generated_at_utc)
    document.getElementById('ins-updated').textContent =
      'Actualizado: ' + dt.toLocaleString('es-AR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',timeZoneName:'short'})
  }
  const curioso = document.getElementById('ins-curioso')
  curioso.textContent = d.dato_curioso || 'El modelo FutVS procesa más de 12.500 partidos históricos para generar cada pronóstico.'
  renderInsForma(d.forma_reciente || [])
  renderInsXg(d.xg_performance || [])
  renderInsAlertas(d.alertas || [])
  renderInsTendencias(d.tendencias || [])
  renderInsOpps(d.oportunidades || [])
}

function insEsc(s) {
  if (typeof s !== 'string') return String(s ?? '')
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

function renderInsForma(rows) {
  const tb = document.getElementById('ins-forma-tbody')
  if (!rows.length) { tb.innerHTML = '<tr><td colspan="5" class="ins-empty">Sin datos de forma</td></tr>'; return }
  const dot = r => {
    if (r==='W') return '<div class="ins-dot ins-dot-w">G</div>'
    if (r==='D') return '<div class="ins-dot ins-dot-d">E</div>'
    if (r==='L') return '<div class="ins-dot ins-dot-l">P</div>'
    return '<div class="ins-dot ins-dot-u">?</div>'
  }
  tb.innerHTML = rows.map(eq => {
    const f = (eq.forma||[]).slice(0,5)
    const esc = eq.escudo ? `<img src="${insEsc(eq.escudo)}" style="width:22px;height:22px;object-fit:contain;border-radius:3px" onerror="this.style.display='none'">` : ''
    return `<tr>
      <td><div class="ins-team-cell">${esc}<span>${insEsc(eq.nombre||eq.slug||'')}</span></div></td>
      <td><div class="ins-form-dots">${f.map(dot).join('')}</div></td>
      <td style="font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--green);font-weight:900">${f.filter(r=>r==='W').length}</td>
      <td style="font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--amber);font-weight:900">${f.filter(r=>r==='D').length}</td>
      <td style="font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--red);font-weight:900">${f.filter(r=>r==='L').length}</td>
    </tr>`
  }).join('')
}

function renderInsXg(items) {
  const el = document.getElementById('ins-xg-list')
  if (!items.length) { el.innerHTML = '<div class="ins-empty">Datos insuficientes de xG</div>'; return }
  el.innerHTML = items.map(it =>
    `<div class="ins-item ${it.tipo==='sobre'?'ins-item-good':''}">
      <span class="ins-icon">${insEsc(it.flag||'⚽')}</span>
      <div>${insEsc(it.texto)}</div>
    </div>`).join('')
}

function renderInsAlertas(items) {
  const el = document.getElementById('ins-alertas-list')
  if (!items.length) { el.innerHTML = '<div class="ins-empty">Sin alertas activas</div>'; return }
  el.innerHTML = items.map(it =>
    `<div class="ins-item ${it.nivel==='warning'?'ins-item-warn':'ins-item-info'}">
      <span class="ins-icon">${insEsc(it.flag||'⚠️')}</span>
      <div>${insEsc(it.texto)}</div>
    </div>`).join('')
}

function renderInsTendencias(items) {
  const el = document.getElementById('ins-tendencias-list')
  if (!items.length) { el.innerHTML = '<div class="ins-empty">Sin tendencias detectadas</div>'; return }
  el.innerHTML = items.map(it => {
    const icon = it.tipo==='over'?'🎯':it.tipo==='cs'?'🧱':'📈'
    return `<div class="ins-item">
      <span class="ins-icon">${insEsc(it.flag||icon)}</span>
      <div>${insEsc(it.texto)}</div>
    </div>`
  }).join('')
}

function renderInsOpps(items) {
  const grid = document.getElementById('ins-opps-grid')
  const noEl = document.getElementById('ins-no-opps')
  if (!items.length) { grid.innerHTML=''; noEl.style.display='block'; return }
  noEl.style.display = 'none'
  const medals = ['🥇','🥈','🥉','4️⃣','5️⃣']
  const cls    = ['ins-opp-gold','ins-opp-silver','ins-opp-bronze','ins-opp-std','ins-opp-std']
  grid.innerHTML = items.map((o,i) => {
    const ko = o.kickoff ? (() => { try { const d=new Date(o.kickoff); return `<div style="font-size:.68rem;color:var(--faint);margin-top:.5rem">${d.toLocaleString('es-AR',{day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit'})}</div>` } catch{return ''} })() : ''
    return `<div class="ins-opp ${cls[i]||'ins-opp-std'}">
      <div class="ins-opp-medal">${medals[i]||'🔹'}</div>
      ${o.competition?`<div style="font-size:.68rem;color:var(--faint);margin-bottom:.5rem">${insEsc(o.competition)}</div>`:''}
      <div class="ins-opp-match">${insEsc(o.partido)}</div>
      <div class="ins-opp-bet">Apuesta: <strong style="color:var(--text)">${insEsc(o.apuesta)}</strong></div>
      <div class="ins-opp-row"><span>Prob. modelo</span><span class="ins-opp-val">${o.p_modelo}%</span></div>
      <div class="ins-opp-row"><span>Cuota implícita</span><span class="ins-opp-val">${o.p_mercado}%</span></div>
      ${o.xg_home!=null?`<div class="ins-opp-row"><span>xG</span><span class="ins-opp-val">${(o.xg_home||0).toFixed(1)}–${(o.xg_away||0).toFixed(1)}</span></div>`:''}
      <div class="ins-opp-edge">+${o.edge}% valor</div>
      ${ko}
    </div>`
  }).join('')
}

;(function(){
  const _orig = window.showPage
  window.showPage = function(page) { _orig(page); if (page==='insights') loadInsights() }
})()
// ── FIN INSIGHTS JS ──
"""


# ──────────────────────────────────────────────────────────────────────────────
# APLICAR PATCH
# ──────────────────────────────────────────────────────────────────────────────

def patch(html_path: Path, backup: bool) -> None:
    src = html_path.read_text(encoding="utf-8")
    orig = src

    # 1 — Nav: reemplazar enlace Estadísticas
    old_nav = '<a href="#">Estadísticas</a>'
    new_nav = '<a href="#" onclick="showPage(\'insights\');return false">Insights ✦</a>'
    if old_nav in src:
        src = src.replace(old_nav, new_nav, 1)
        print("[patch] ✅ Nav: Estadísticas → Insights ✦")
    else:
        print("[patch] ⚠️  Nav: no se encontró '<a href=\"#\">Estadísticas</a>' — revisá manualmente")

    # 2 — CSS: insertar antes del primer </style>
    css_marker = "</style>"
    if "ins-page" in src:
        print("[patch] ⏭  CSS: ya existe el bloque ins-page, salteando")
    elif css_marker in src:
        src = src.replace(css_marker, CSS_INSIGHTS + css_marker, 1)
        print("[patch] ✅ CSS de Insights insertado")
    else:
        print("[patch] ⚠️  CSS: no se encontró </style>")

    # 3 — HTML: insertar antes de <!-- DETAIL -->
    detail_marker = "<!-- DETAIL -->"
    if "<!-- INSIGHTS -->" in src:
        print("[patch] ⏭  HTML: página Insights ya existe, salteando")
    elif detail_marker in src:
        src = src.replace(detail_marker, HTML_INSIGHTS + detail_marker, 1)
        print("[patch] ✅ Página Insights insertada")
    else:
        print("[patch] ⚠️  HTML: no se encontró '<!-- DETAIL -->' — revisá manualmente")

    # 4 — JS: insertar antes del último </script>
    script_end = "</script>"
    if "loadInsights" in src:
        print("[patch] ⏭  JS: loadInsights ya existe, salteando")
    elif script_end in src:
        # Insertar antes del último </script>
        idx = src.rfind(script_end)
        src = src[:idx] + JS_INSIGHTS + "\n" + src[idx:]
        print("[patch] ✅ JS de Insights insertado")
    else:
        print("[patch] ⚠️  JS: no se encontró </script>")

    if src == orig:
        print("[patch] ℹ️  Sin cambios realizados")
        return

    if backup:
        bak = html_path.with_suffix(".html.bak")
        shutil.copy2(html_path, bak)
        print(f"[patch] 💾 Backup guardado en {bak}")

    html_path.write_text(src, encoding="utf-8")
    print(f"[patch] ✅ {html_path} actualizado ({len(src):,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser(description="Aplica el patch de Insights a web/index.html")
    ap.add_argument("--html",   default="web/index.html", help="Ruta al index.html")
    ap.add_argument("--backup", action="store_true",       help="Guardar copia .bak antes de modificar")
    args = ap.parse_args()

    html_path = Path(args.html)
    if not html_path.exists():
        print(f"[patch] ❌ No se encontró {html_path}")
        return

    print(f"[patch] Aplicando sobre {html_path} ...")
    patch(html_path, args.backup)


if __name__ == "__main__":
    main()
