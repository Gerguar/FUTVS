#!/usr/bin/env python3
"""
add_footer_pages.py — Agrega las 11 páginas del footer a web/index.html de FutVS.

Páginas que genera:
  RECURSOS:   estadisticas (redirect a insights), glosario, blog
  CONTACTO:   sugerir, colaboraciones, prensa
  FUTVS:      nosotros, metodologia, pautas
  LEGAL:      privacidad, terminos, cookies

Uso:
    python add_footer_pages.py
    python add_footer_pages.py --html web/index.html --backup
"""

import argparse
import shutil
from pathlib import Path

# ─── CSS COMPARTIDO ────────────────────────────────────────────────────────────

CSS_PAGES = r"""
/* ── PÁGINAS FOOTER ─────────────────────────── */
.fp-page{max-width:860px;margin:0 auto;padding:2.5rem 1.5rem 5rem}
.fp-back{background:transparent;color:var(--green);border:1px solid rgba(34,197,94,.35);padding:8px 22px;border-radius:30px;font-size:.82rem;font-weight:700;cursor:pointer;font-family:'Inter',sans-serif;margin-bottom:2rem;display:inline-block}
.fp-back:hover{background:rgba(34,197,94,.08)}
.fp-eyebrow{font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:2.5px;color:var(--green);text-transform:uppercase;margin-bottom:.4rem}
.fp-title{font-size:clamp(1.6rem,4vw,2.4rem);font-weight:900;letter-spacing:-1px;color:#fff;margin-bottom:.5rem}
.fp-lead{color:var(--muted);font-size:.95rem;line-height:1.65;margin-bottom:2rem;max-width:620px}
.fp-card{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:1.4rem 1.6rem;margin-bottom:1rem}
.fp-card-title{font-family:'JetBrains Mono',monospace;font-size:.65rem;letter-spacing:2px;color:var(--green);text-transform:uppercase;margin-bottom:.75rem;font-weight:700}
.fp-card p{color:var(--muted);font-size:.9rem;line-height:1.7}
.fp-card p+p{margin-top:.7rem}
.fp-card strong{color:var(--text)}
.fp-divider{border:none;border-top:1px solid var(--border);margin:1.8rem 0}
.fp-grid-2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.fp-tag{display:inline-block;font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:1.5px;background:rgba(34,197,94,.1);border:1px solid rgba(34,197,94,.2);color:var(--green);padding:.22rem .65rem;border-radius:20px;text-transform:uppercase;margin:.15rem}
.fp-table{width:100%;border-collapse:collapse;font-size:.875rem;margin-top:.5rem}
.fp-table th{font-family:'JetBrains Mono',monospace;font-size:.58rem;letter-spacing:1.5px;color:var(--faint);text-transform:uppercase;padding:.4rem .6rem;text-align:left;border-bottom:1px solid var(--border)}
.fp-table td{padding:.6rem .6rem;border-bottom:1px solid rgba(255,255,255,.035);color:var(--muted);font-size:.875rem;line-height:1.5}
.fp-table td strong{color:var(--text)}
.fp-table tr:last-child td{border-bottom:none}
.fp-form-group{margin-bottom:1rem}
.fp-form-group label{display:block;font-size:.8rem;color:var(--muted);margin-bottom:.4rem;font-weight:600}
.fp-input,.fp-textarea,.fp-select{width:100%;background:var(--bg);border:1px solid var(--border2);border-radius:8px;padding:.65rem .9rem;color:var(--text);font-size:.9rem;font-family:'Inter',sans-serif;outline:none;transition:border-color .2s}
.fp-input:focus,.fp-textarea:focus,.fp-select:focus{border-color:rgba(34,197,94,.5)}
.fp-textarea{resize:vertical;min-height:110px}
.fp-select option{background:var(--bg)}
.fp-btn{background:var(--green);color:#080a0c;border:none;padding:.75rem 2rem;border-radius:30px;font-size:.88rem;font-weight:800;cursor:pointer;font-family:'Inter',sans-serif;transition:opacity .2s}
.fp-btn:hover{opacity:.88}
.fp-alert{background:rgba(34,197,94,.08);border:1px solid rgba(34,197,94,.2);border-radius:10px;padding:.9rem 1.1rem;font-size:.85rem;color:var(--muted);margin-top:1rem;display:none}
.fp-alert.show{display:block}
.fp-blog-item{display:flex;gap:1.2rem;padding:1.1rem 0;border-bottom:1px solid var(--border);align-items:flex-start}
.fp-blog-item:last-child{border-bottom:none}
.fp-blog-date{font-family:'JetBrains Mono',monospace;font-size:.65rem;color:var(--faint);white-space:nowrap;padding-top:.15rem}
.fp-blog-body{}
.fp-blog-tag{font-family:'JetBrains Mono',monospace;font-size:.58rem;letter-spacing:1px;color:var(--green);text-transform:uppercase;margin-bottom:.25rem}
.fp-blog-headline{font-size:.95rem;font-weight:700;color:var(--text);margin-bottom:.3rem;line-height:1.3}
.fp-blog-snippet{font-size:.82rem;color:var(--muted);line-height:1.55}
.fp-stat-row{display:flex;gap:1.5rem;margin-bottom:1.4rem;flex-wrap:wrap}
.fp-stat{background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:.9rem 1.2rem;flex:1;min-width:120px}
.fp-stat-val{font-family:'JetBrains Mono',monospace;font-size:1.4rem;font-weight:900;color:var(--green);margin-bottom:.15rem}
.fp-stat-lbl{font-size:.72rem;color:var(--faint)}
.fp-step{display:flex;gap:1rem;margin-bottom:.9rem;align-items:flex-start}
.fp-step-num{background:rgba(34,197,94,.15);color:var(--green);border:1px solid rgba(34,197,94,.3);border-radius:50%;width:28px;height:28px;display:flex;align-items:center;justify-content:center;font-family:'JetBrains Mono',monospace;font-size:.75rem;font-weight:900;flex-shrink:0;margin-top:.1rem}
.fp-step-text{color:var(--muted);font-size:.9rem;line-height:1.65}
.fp-step-text strong{color:var(--text)}
@media(max-width:600px){.fp-page{padding:1.5rem 1rem 4rem}.fp-grid-2{grid-template-columns:1fr}.fp-stat-row{gap:.7rem}}
/* ── FIN PÁGINAS FOOTER CSS ── */
"""

# ─── HTML DE LAS 11 PÁGINAS ───────────────────────────────────────────────────

PAGES_HTML = """
<!-- ESTADISTICAS (redirect a insights) -->
<div id="estadisticas" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Recursos</div>
    <div class="fp-title">📊 Estadísticas</div>
    <div class="fp-lead">Las estadísticas detalladas se muestran en la sección Insights, donde encontrás forma reciente, rendimiento vs expectativas y oportunidades del algoritmo.</div>
    <div style="text-align:center;padding:2rem 0">
      <button onclick="showPage('insights')" style="background:var(--green);color:#080a0c;border:none;padding:.85rem 2.4rem;border-radius:30px;font-size:.95rem;font-weight:800;cursor:pointer;font-family:'Inter',sans-serif">Ver Insights →</button>
    </div>
  </div>
</div>
<!-- /ESTADISTICAS -->

<!-- GLOSARIO -->
<div id="glosario" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Recursos</div>
    <div class="fp-title">📖 Glosario</div>
    <div class="fp-lead">Términos estadísticos y conceptos clave del modelo FutVS.</div>

    <div class="fp-card">
      <div class="fp-card-title">Modelo</div>
      <table class="fp-table">
        <thead><tr><th>Término</th><th>Definición</th></tr></thead>
        <tbody>
          <tr><td><strong>Dixon-Coles</strong></td><td>Modelo de regresión de Poisson bivariado (1997) que estima goles esperados por equipo, con corrección para resultados de baja anotación (0-0, 1-0, 0-1, 1-1).</td></tr>
          <tr><td><strong>Elo</strong></td><td>Sistema de rating dinámico que actualiza la fuerza de cada equipo después de cada partido según el resultado y la diferencia de goles.</td></tr>
          <tr><td><strong>XGBoost</strong></td><td>Algoritmo de gradient boosting que combina features de Dixon-Coles, Elo y ratings de jugadores para generar la probabilidad final 1X2.</td></tr>
          <tr><td><strong>Calibración isotónica</strong></td><td>Técnica que ajusta las probabilidades del modelo para que sean más realistas: si el modelo dice 60%, debería ocurrir aproximadamente el 60% de las veces.</td></tr>
          <tr><td><strong>Log Loss</strong></td><td>Métrica de evaluación de probabilidades. Menor es mejor. Un modelo aleatorio obtiene ~1.099. Los bookmakers top rondan 0.95-0.98. FutVS: ~1.015.</td></tr>
          <tr><td><strong>Brier Score</strong></td><td>Error cuadrático medio entre probabilidades predichas y resultados reales. Menor es mejor. Complementa al Log Loss.</td></tr>
        </tbody>
      </table>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Pronósticos</div>
      <table class="fp-table">
        <thead><tr><th>Término</th><th>Definición</th></tr></thead>
        <tbody>
          <tr><td><strong>1X2</strong></td><td>Mercado de resultado final: 1 = victoria local, X = empate, 2 = victoria visitante.</td></tr>
          <tr><td><strong>xG (Expected Goals)</strong></td><td>Goles esperados basados en la calidad de las ocasiones de gol, no solo en las anotadas.</td></tr>
          <tr><td><strong>Over/Under 2.5</strong></td><td>Apuesta sobre si el partido tendrá más (Over) o menos (Under) de 2.5 goles totales.</td></tr>
          <tr><td><strong>BTTS</strong></td><td>Both Teams To Score — ambos equipos anotan al menos un gol.</td></tr>
          <tr><td><strong>Edge</strong></td><td>Ventaja estimada del modelo sobre el mercado: diferencia entre la probabilidad del modelo y la implícita en las cuotas del bookmaker.</td></tr>
          <tr><td><strong>Devig</strong></td><td>Proceso de eliminar el margen del bookmaker (overround) para obtener probabilidades implícitas limpias.</td></tr>
        </tbody>
      </table>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Fuentes de datos</div>
      <table class="fp-table">
        <thead><tr><th>Fuente</th><th>Qué aporta</th></tr></thead>
        <tbody>
          <tr><td><strong>football-data.org</strong></td><td>Fixtures, resultados y clasificaciones de las 6 ligas top + Champions League.</td></tr>
          <tr><td><strong>football-data.co.uk</strong></td><td>Histórico de 6 años con odds de hasta 5 bookmakers.</td></tr>
          <tr><td><strong>Understat / FBref</strong></td><td>Estadísticas de jugadores: xG, asistencias, minutos jugados.</td></tr>
          <tr><td><strong>EA FC 26</strong></td><td>Ratings de jugadores (OVR) usados como proxy de calidad del plantel.</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>
<!-- /GLOSARIO -->

<!-- BLOG -->
<div id="blog" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Recursos</div>
    <div class="fp-title">✍️ Blog</div>
    <div class="fp-lead">Artículos sobre metodología, análisis de temporada y fútbol estadístico.</div>

    <div class="fp-card">
      <div class="fp-blog-item">
        <div class="fp-blog-date">May 2025</div>
        <div class="fp-blog-body">
          <div class="fp-blog-tag">Metodología</div>
          <div class="fp-blog-headline">¿Cómo funciona el modelo Dixon-Coles?</div>
          <div class="fp-blog-snippet">El modelo de Poisson bivariado desarrollado por Mark Dixon y Stuart Coles en 1997 sigue siendo una de las referencias en predicción de fútbol. Explicamos cómo lo implementamos y por qué le añadimos Elo y XGBoost encima.</div>
        </div>
      </div>
      <div class="fp-blog-item">
        <div class="fp-blog-date">Abr 2025</div>
        <div class="fp-blog-body">
          <div class="fp-blog-tag">Análisis</div>
          <div class="fp-blog-headline">Por qué el Log Loss importa más que el accuracy</div>
          <div class="fp-blog-snippet">Un modelo que dice "gana el local" en todos los partidos puede tener 45% de accuracy. Pero predice probabilidades pésimas. Te explicamos por qué evaluamos con Log Loss y cómo interpretarlo.</div>
        </div>
      </div>
      <div class="fp-blog-item">
        <div class="fp-blog-date">Mar 2025</div>
        <div class="fp-blog-body">
          <div class="fp-blog-tag">Datos</div>
          <div class="fp-blog-headline">El problema del leakage temporal en modelos deportivos</div>
          <div class="fp-blog-snippet">Usar datos futuros para entrenar el modelo es el error más común en machine learning deportivo. Explicamos cómo implementamos rolling-origin backtest para garantizar evaluaciones honestas.</div>
        </div>
      </div>
    </div>
    <div style="text-align:center;margin-top:1.5rem">
      <div style="font-size:.8rem;color:var(--faint);font-family:'JetBrains Mono',monospace">MÁS ARTÍCULOS PRÓXIMAMENTE</div>
    </div>
  </div>
</div>
<!-- /BLOG -->

<!-- SUGERIR PARTIDO -->
<div id="sugerir" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Contacto</div>
    <div class="fp-title">🗳️ Sugerir partido</div>
    <div class="fp-lead">¿Hay un partido que querés ver analizado y no está en FutVS? Mandanos la sugerencia y lo evaluamos para incorporarlo.</div>

    <div class="fp-card">
      <div class="fp-card-title">Enviar sugerencia</div>
      <div class="fp-form-group">
        <label>Equipo local</label>
        <input class="fp-input" type="text" id="sug-local" placeholder="ej. Real Madrid">
      </div>
      <div class="fp-form-group">
        <label>Equipo visitante</label>
        <input class="fp-input" type="text" id="sug-visit" placeholder="ej. Manchester City">
      </div>
      <div class="fp-form-group">
        <label>Liga / Competición</label>
        <select class="fp-select" id="sug-liga">
          <option value="">Seleccioná una liga</option>
          <option>Champions League</option>
          <option>Premier League</option>
          <option>La Liga</option>
          <option>Serie A</option>
          <option>Bundesliga</option>
          <option>Ligue 1</option>
          <option>Europa League</option>
          <option>Copa del Rey</option>
          <option>FA Cup</option>
          <option>Otra</option>
        </select>
      </div>
      <div class="fp-form-group">
        <label>Comentario (opcional)</label>
        <textarea class="fp-textarea" id="sug-comentario" placeholder="¿Por qué es interesante este partido?"></textarea>
      </div>
      <button class="fp-btn" onclick="enviarSugerencia()">Enviar sugerencia</button>
      <div class="fp-alert" id="sug-ok">✅ ¡Sugerencia recibida! La revisamos a la brevedad.</div>
    </div>

    <div class="fp-card" style="margin-top:.5rem">
      <div class="fp-card-title">¿Qué partidos cubre FutVS?</div>
      <p>Actualmente cubrimos las <strong>6 ligas top de Europa</strong> más la <strong>UEFA Champions League</strong>. Las sugerencias más votadas pueden incorporarse en futuras actualizaciones.</p>
    </div>
  </div>
</div>
<!-- /SUGERIR PARTIDO -->

<!-- COLABORACIONES -->
<div id="colaboraciones" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Contacto</div>
    <div class="fp-title">🤝 Colaboraciones</div>
    <div class="fp-lead">FutVS es un proyecto independiente abierto a colaboraciones con periodistas, analistas, desarrolladores y medios deportivos.</div>

    <div class="fp-grid-2">
      <div class="fp-card">
        <div class="fp-card-title">📝 Periodismo de datos</div>
        <p>Si trabajás en un medio y querés usar nuestros modelos para análisis de partidos, contactanos. Podemos proveer datos y visualizaciones.</p>
      </div>
      <div class="fp-card">
        <div class="fp-card-title">💻 Desarrollo</div>
        <p>Si sos desarrollador o data scientist y querés contribuir al modelo, al frontend o a las fuentes de datos, el proyecto está en GitHub.</p>
      </div>
      <div class="fp-card">
        <div class="fp-card-title">🎙️ Podcasts y contenido</div>
        <p>Disponibles para aparecer en podcasts o programas de fútbol estadístico para explicar cómo funcionan los modelos predictivos.</p>
      </div>
      <div class="fp-card">
        <div class="fp-card-title">🏢 Institucional</div>
        <p>Si representás una organización deportiva interesada en análisis estadístico avanzado, escribinos para explorar posibilidades.</p>
      </div>
    </div>

    <div class="fp-card" style="margin-top:.5rem;text-align:center">
      <div class="fp-card-title">Contacto directo</div>
      <p>Escribinos a <strong style="color:var(--green)">proyectos.gerguar@gmail.com</strong> con el asunto <strong>"Colaboración FutVS"</strong>.</p>
    </div>
  </div>
</div>
<!-- /COLABORACIONES -->

<!-- PRENSA -->
<div id="prensa" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Contacto</div>
    <div class="fp-title">📰 Prensa</div>
    <div class="fp-lead">Información para medios de comunicación, bloggers y creadores de contenido sobre FutVS.</div>

    <div class="fp-card">
      <div class="fp-card-title">Sobre FutVS</div>
      <p>FutVS es un sistema de análisis estadístico de fútbol que combina el modelo <strong>Dixon-Coles</strong>, ratings <strong>Elo</strong> y <strong>XGBoost</strong> para generar pronósticos 1X2 de los principales campeonatos europeos.</p>
      <p style="margin-top:.7rem">El sistema procesa más de <strong>12.500 partidos históricos</strong> y se actualiza automáticamente cada 6 horas.</p>
    </div>

    <div class="fp-stat-row">
      <div class="fp-stat"><div class="fp-stat-val">12.5K+</div><div class="fp-stat-lbl">Partidos analizados</div></div>
      <div class="fp-stat"><div class="fp-stat-val">6</div><div class="fp-stat-lbl">Ligas cubiertas</div></div>
      <div class="fp-stat"><div class="fp-stat-val">6h</div><div class="fp-stat-lbl">Frecuencia de actualización</div></div>
      <div class="fp-stat"><div class="fp-stat-val">1.015</div><div class="fp-stat-lbl">Log Loss (modelo)</div></div>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Tecnología</div>
      <div style="display:flex;flex-wrap:wrap;gap:.3rem;margin-top:.2rem">
        <span class="fp-tag">Python</span><span class="fp-tag">XGBoost</span><span class="fp-tag">Dixon-Coles</span>
        <span class="fp-tag">GitHub Actions</span><span class="fp-tag">Supabase</span><span class="fp-tag">Netlify</span>
        <span class="fp-tag">football-data.org</span><span class="fp-tag">Understat</span><span class="fp-tag">EA FC 26</span>
      </div>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Contacto de prensa</div>
      <p>Para entrevistas, datos o consultas de medios: <strong style="color:var(--green)">proyectos.gerguar@gmail.com</strong><br>
      Asunto sugerido: <strong>"Prensa FutVS"</strong></p>
    </div>
  </div>
</div>
<!-- /PRENSA -->

<!-- SOBRE NOSOTROS -->
<div id="nosotros" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">FutVS</div>
    <div class="fp-title">👋 Sobre nosotros</div>
    <div class="fp-lead">FutVS nació de la intersección entre la pasión por el fútbol y el análisis de datos.</div>

    <div class="fp-card">
      <div class="fp-card-title">El proyecto</div>
      <p>FutVS es un proyecto personal de análisis estadístico de fútbol. Lo que empezó como un experimento para entender si los modelos de Poisson realmente funcionan en la práctica, terminó en un sistema completo con pipeline automatizado, base de datos, y frontend público.</p>
      <p>La motivación es simple: el fútbol tiene demasiado ruido narrativo. Los modelos estadísticos no son perfectos, pero son más honestos que la mayoría de los análisis intuitivos.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Stack técnico</div>
      <div class="fp-step">
        <div class="fp-step-num">1</div>
        <div class="fp-step-text"><strong>Ingesta de datos</strong> — GitHub Actions corre cada 6h bajando fixtures, resultados y odds de football-data.org y football-data.co.uk.</div>
      </div>
      <div class="fp-step">
        <div class="fp-step-num">2</div>
        <div class="fp-step-text"><strong>Modelo</strong> — Dixon-Coles estima goles esperados. Elo trackea la fuerza relativa de cada equipo. XGBoost combina todo más ratings de jugadores (EA FC 26).</div>
      </div>
      <div class="fp-step">
        <div class="fp-step-num">3</div>
        <div class="fp-step-text"><strong>Persistencia</strong> — Los pronósticos se guardan en Supabase (PostgreSQL). El frontend lee live con la anon key.</div>
      </div>
      <div class="fp-step">
        <div class="fp-step-num">4</div>
        <div class="fp-step-text"><strong>Frontend</strong> — Vanilla JS desplegado en Netlify. Sin build steps, sin dependencias pesadas. Un solo HTML de ~90KB.</div>
      </div>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Contacto</div>
      <p>Si tenés preguntas, sugerencias o simplemente querés hablar de modelos predictivos: <strong style="color:var(--green)">proyectos.gerguar@gmail.com</strong></p>
    </div>
  </div>
</div>
<!-- /SOBRE NOSOTROS -->

<!-- METODOLOGÍA -->
<div id="metodologia" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">FutVS</div>
    <div class="fp-title">🔬 Metodología</div>
    <div class="fp-lead">Cómo el modelo genera probabilidades 1X2 para cada partido.</div>

    <div class="fp-card">
      <div class="fp-card-title">Paso 1 — Dixon-Coles</div>
      <p>Ajustamos un modelo de <strong>Poisson bivariado</strong> con corrección Dixon-Coles sobre ~12.500 partidos históricos. Para cada equipo estimamos un parámetro de <strong>ataque</strong> y uno de <strong>defensa</strong>, más una ventaja de local global.</p>
      <p>La corrección τ (tau) ajusta la probabilidad de resultados bajos (0-0, 1-0, 0-1, 1-1) que el Poisson clásico subestima. Los partidos más recientes ponderan más (decaimiento exponencial con ξ=0.0035).</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Paso 2 — Elo</div>
      <p>Paralelamente mantenemos un <strong>rating Elo dinámico</strong> por equipo. Se actualiza después de cada partido según resultado y diferencia de goles (margin factor). Captura tendencias recientes que el DC de ventana larga puede perder.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Paso 3 — Features y XGBoost</div>
      <p>Con DC + Elo construimos un vector de ~49 features por partido: probabilidades DC, lambdas, diferencias Elo, forma reciente (últimos 5 y 10 partidos), fatiga, momentum, y <strong>ratings de plantel</strong> (ataque, defensa, XI promedio vía EA FC 26).</p>
      <p>Un <strong>XGBoost multiclase</strong> entrenado sobre esto genera las probabilidades finales 1X2. Se evalúa con Log Loss en un holdout temporal honesto (sin leakage).</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Evaluación</div>
      <table class="fp-table">
        <thead><tr><th>Modelo</th><th>Log Loss</th><th>Referencia</th></tr></thead>
        <tbody>
          <tr><td>Aleatorio (1/3 cada uno)</td><td>1.099</td><td>Piso</td></tr>
          <tr><td>Prior histórico (frecuencias)</td><td>~1.06</td><td>Baseline simple</td></tr>
          <tr><td><strong>FutVS (producción)</strong></td><td><strong>~1.015</strong></td><td>✅ Actual</td></tr>
          <tr><td>Bookmakers top 5 ligas</td><td>0.95–0.98</td><td>Techo práctico</td></tr>
        </tbody>
      </table>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Actualización</div>
      <p>El pipeline corre automáticamente <strong>cada 6 horas</strong> vía GitHub Actions. El modelo completo se reentrena <strong>cada domingo</strong>. Los pronósticos tienen un horizonte de 14 días.</p>
    </div>
  </div>
</div>
<!-- /METODOLOGÍA -->

<!-- PAUTAS EDITORIALES -->
<div id="pautas" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">FutVS</div>
    <div class="fp-title">📋 Pautas editoriales</div>
    <div class="fp-lead">Criterios que definen qué partidos cubrimos, cómo presentamos los datos y qué significa cada pronóstico.</div>

    <div class="fp-card">
      <div class="fp-card-title">¿Qué partidos cubrimos?</div>
      <p>FutVS cubre exclusivamente partidos de las <strong>6 ligas top de Europa</strong> (Premier League, La Liga, Serie A, Bundesliga, Ligue 1) más la <strong>UEFA Champions League</strong>. Estas competiciones tienen suficiente data histórica para que el modelo sea confiable.</p>
      <p>No cubrimos ligas de acceso sin suficiente historial, amistosos, ni partidos de categorías inferiores.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">¿Qué significa una probabilidad?</div>
      <p>Una probabilidad de <strong>65% para victoria local</strong> no significa que el equipo local <em>va a ganar</em>. Significa que, en partidos con condiciones similares, el local gana aproximadamente 65 de cada 100 veces.</p>
      <p>El fútbol tiene alta varianza. El modelo calibra incertidumbre, no garantiza resultados.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Esto NO es asesoramiento de apuestas</div>
      <p>FutVS es una herramienta de <strong>análisis estadístico con fines informativos</strong>. No recomendamos apostar dinero basándose en nuestros pronósticos. Las probabilidades son estimaciones del modelo, no garantías.</p>
      <p>Si identificamos "oportunidades vs mercado" en Insights, es un análisis académico de diferencia entre modelos, no una recomendación de apuesta.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Fuentes de datos</div>
      <p>Todos los datos históricos provienen de fuentes públicas: <strong>football-data.org</strong>, <strong>football-data.co.uk</strong>, <strong>Understat</strong> y <strong>EA FC 26</strong>. Los datos se usan para fines no comerciales, de acuerdo con los términos de cada fuente.</p>
    </div>
  </div>
</div>
<!-- /PAUTAS EDITORIALES -->

<!-- PRIVACIDAD -->
<div id="privacidad" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Legal</div>
    <div class="fp-title">🔒 Política de Privacidad</div>
    <div class="fp-lead">Cómo FutVS maneja (o no maneja) tus datos personales.</div>

    <div class="fp-card">
      <div class="fp-card-title">Datos que recopilamos</div>
      <p>FutVS <strong>no recopila datos personales</strong> de los usuarios. El sitio no tiene registro, login, ni formularios que almacenen información identificable.</p>
      <p>Las sugerencias de partido enviadas a través del formulario se envían por email directamente y no se almacenan en ninguna base de datos del sitio.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Terceros</div>
      <p>El sitio carga fuentes de <strong>Google Fonts</strong>, lo que implica que Google puede registrar la solicitud de fuente (dirección IP, timestamp). Consultá la política de privacidad de Google para más detalle.</p>
      <p>Los datos de partidos y pronósticos se leen de <strong>Supabase</strong> (base de datos PostgreSQL en la nube). Supabase puede registrar logs de acceso a nivel de infraestructura.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Cookies</div>
      <p>FutVS no utiliza cookies propias. Ver sección <button onclick="showPage('cookies')" style="background:none;border:none;color:var(--green);cursor:pointer;font-size:.9rem;font-family:'Inter',sans-serif;padding:0;text-decoration:underline">Cookies</button> para más detalle.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Contacto</div>
      <p>Para consultas sobre privacidad: <strong style="color:var(--green)">proyectos.gerguar@gmail.com</strong></p>
      <p style="margin-top:.5rem;font-size:.8rem;color:var(--faint)">Última actualización: Junio 2025</p>
    </div>
  </div>
</div>
<!-- /PRIVACIDAD -->

<!-- TÉRMINOS DE USO -->
<div id="terminos" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Legal</div>
    <div class="fp-title">📄 Términos de uso</div>
    <div class="fp-lead">Al usar FutVS aceptás los siguientes términos.</div>

    <div class="fp-card">
      <div class="fp-card-title">Uso permitido</div>
      <p>FutVS es una herramienta de <strong>análisis estadístico con fines informativos y educativos</strong>. Podés consultar los pronósticos, compartir el sitio y usar la información para análisis personales.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Sin garantías</div>
      <p>Los pronósticos son estimaciones estadísticas basadas en datos históricos. <strong>FutVS no garantiza la exactitud, completitud ni vigencia</strong> de la información presentada. Los resultados pasados no garantizan resultados futuros.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">No es asesoramiento financiero</div>
      <p>Nada en FutVS constituye asesoramiento financiero, de inversión ni de apuestas. <strong>Usá los datos bajo tu propia responsabilidad.</strong> FutVS no se hace responsable de decisiones tomadas basándose en su contenido.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Propiedad intelectual</div>
      <p>El código fuente de FutVS es de uso personal del autor. Los datos de partidos pertenecen a sus respectivas fuentes (football-data.org, Understat, etc.).</p>
      <p style="margin-top:.5rem;font-size:.8rem;color:var(--faint)">Última actualización: Junio 2025</p>
    </div>
  </div>
</div>
<!-- /TÉRMINOS DE USO -->

<!-- COOKIES -->
<div id="cookies" class="page" style="position:relative;z-index:1">
  <div class="fp-page">
    <button class="fp-back" onclick="showPage('home')">← Inicio</button>
    <div class="fp-eyebrow">Legal</div>
    <div class="fp-title">🍪 Política de Cookies</div>
    <div class="fp-lead">FutVS tiene una política de cookies muy simple: casi no usamos ninguna.</div>

    <div class="fp-card">
      <div class="fp-card-title">Cookies propias</div>
      <p>FutVS <strong>no utiliza cookies propias</strong>. No guardamos preferencias, sesiones ni identificadores de usuario en cookies.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">Cookies de terceros</div>
      <table class="fp-table">
        <thead><tr><th>Servicio</th><th>Por qué</th><th>Tipo</th></tr></thead>
        <tbody>
          <tr><td><strong>Google Fonts</strong></td><td>Carga de tipografías (Inter, JetBrains Mono)</td><td>Técnica</td></tr>
          <tr><td><strong>Supabase</strong></td><td>Lectura de datos de partidos vía API REST</td><td>Técnica</td></tr>
        </tbody>
      </table>
      <p style="margin-top:.8rem;font-size:.82rem;color:var(--faint)">Ninguna de estas cookies se usa para tracking, publicidad ni perfilado de usuarios.</p>
    </div>

    <div class="fp-card">
      <div class="fp-card-title">¿Cómo desactivarlas?</div>
      <p>Podés bloquear cookies de terceros desde la configuración de tu navegador. Esto puede afectar la carga de fuentes tipográficas (el sitio seguirá funcionando con fuentes del sistema).</p>
      <p style="margin-top:.5rem;font-size:.8rem;color:var(--faint)">Última actualización: Junio 2025</p>
    </div>
  </div>
</div>
<!-- /COOKIES -->
"""

# ─── JS: showPage patches + sugerencia form ────────────────────────────────────

JS_PAGES = r"""
// ── PÁGINAS FOOTER ──────────────────────────────
function enviarSugerencia() {
  const local = document.getElementById('sug-local').value.trim()
  const visit = document.getElementById('sug-visit').value.trim()
  const liga  = document.getElementById('sug-liga').value
  const com   = document.getElementById('sug-comentario').value.trim()
  if (!local || !visit || !liga) { alert('Completá equipo local, visitante y liga.'); return }
  const subject = encodeURIComponent(`Sugerencia FutVS: ${local} vs ${visit}`)
  const body    = encodeURIComponent(`Partido: ${local} vs ${visit}\nLiga: ${liga}\nComentario: ${com || '(sin comentario)'}`)
  window.location.href = `mailto:proyectos.gerguar@gmail.com?subject=${subject}&body=${body}`
  document.getElementById('sug-ok').classList.add('show')
}
// ── FIN PÁGINAS FOOTER JS ──
"""

# ─── PATCH DEL FOOTER (agrega onclick a todos los links) ──────────────────────

FOOTER_REPLACEMENTS = [
    # RECURSOS
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Estadísticas</a>',
        'href="#" onclick="showPage(\'estadisticas\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Estadísticas</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Glosario</a>',
        'href="#" onclick="showPage(\'glosario\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Glosario</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Blog</a>',
        'href="#" onclick="showPage(\'blog\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Blog</a>',
    ),
    # CONTACTO
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Sugerir partido</a>',
        'href="#" onclick="showPage(\'sugerir\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Sugerir partido</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Colaboraciones</a>',
        'href="#" onclick="showPage(\'colaboraciones\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Colaboraciones</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Prensa</a>',
        'href="#" onclick="showPage(\'prensa\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Prensa</a>',
    ),
    # FUTVS
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Sobre nosotros</a>',
        'href="#" onclick="showPage(\'nosotros\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Sobre nosotros</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Metodología</a>',
        'href="#" onclick="showPage(\'metodologia\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Metodología</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Pautas editoriales</a>',
        'href="#" onclick="showPage(\'pautas\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Pautas editoriales</a>',
    ),
    # LEGAL
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Privacidad</a>',
        'href="#" onclick="showPage(\'privacidad\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Privacidad</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Términos de uso</a>',
        'href="#" onclick="showPage(\'terminos\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Términos de uso</a>',
    ),
    (
        'href="#" style="color:var(--muted);text-decoration:none;font-size:.88rem">Cookies</a>',
        'href="#" onclick="showPage(\'cookies\');return false" style="color:var(--muted);text-decoration:none;font-size:.88rem">Cookies</a>',
    ),
    # NAV — Estadísticas
    (
        '<a href="#">Estadísticas</a>',
        '<a href="#" onclick="showPage(\'estadisticas\');return false">Estadísticas</a>',
    ),
]


def patch(html_path: Path, backup: bool) -> None:
    src = html_path.read_text(encoding="utf-8")

    if backup:
        bak = html_path.with_suffix(".html.bak")
        import shutil as _sh
        _sh.copy2(html_path, bak)
        print(f"[patch] 💾 Backup → {bak}")

    # 1 — CSS
    css_marker = "</style>"
    if "fp-page" in src:
        print("[patch] ⏭  CSS: ya existe, salteando")
    elif css_marker in src:
        src = src.replace(css_marker, CSS_PAGES + css_marker, 1)
        print("[patch] ✅ CSS de páginas footer insertado")
    else:
        print("[patch] ⚠️  CSS: no se encontró </style>")

    # 2 — HTML páginas (antes de <!-- DETAIL -->)
    detail_marker = "<!-- DETAIL -->"
    if "<!-- GLOSARIO -->" in src:
        print("[patch] ⏭  HTML: páginas ya existen, salteando")
    elif detail_marker in src:
        src = src.replace(detail_marker, PAGES_HTML + detail_marker, 1)
        print("[patch] ✅ 11 páginas insertadas antes de <!-- DETAIL -->")
    else:
        print("[patch] ⚠️  HTML: no se encontró <!-- DETAIL -->")

    # 3 — JS (antes del último </script>)
    script_end = "</script>"
    if "enviarSugerencia" in src:
        print("[patch] ⏭  JS: ya existe, salteando")
    elif script_end in src:
        idx = src.rfind(script_end)
        src = src[:idx] + JS_PAGES + "\n" + src[idx:]
        print("[patch] ✅ JS de páginas footer insertado")
    else:
        print("[patch] ⚠️  JS: no se encontró </script>")

    # 4 — Footer + nav links
    cambios = 0
    for old, new in FOOTER_REPLACEMENTS:
        if old in src:
            src = src.replace(old, new, 1)
            cambios += 1
    print(f"[patch] ✅ {cambios}/{len(FOOTER_REPLACEMENTS)} links del footer/nav actualizados")

    html_path.write_text(src, encoding="utf-8")
    print(f"[patch] ✅ {html_path} guardado ({len(src):,} bytes)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html",   default="web/index.html")
    ap.add_argument("--backup", action="store_true")
    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.exists():
        print(f"[patch] ❌ No se encontró {html_path}")
        return
    print(f"[patch] Aplicando sobre {html_path} ...")
    patch(html_path, args.backup)


if __name__ == "__main__":
    main()
