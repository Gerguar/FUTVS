# 🤝 Handoff FutVersus — para próxima sesión de Claude

**Pegá este archivo (o un resumen) al inicio del nuevo chat para que el próximo Claude no arranque a ciegas.**

Última actualización: **7 jun 2026** (sesión cerrada por tokens, ver §15 — DECISIONES PENDIENTES).

---

## 1. ¿Qué es este proyecto?

**FutVersus** (`futversus.com`) — plataforma de análisis estadístico de fútbol con foco en el **Mundial 2026** (arranca 11 de junio 2026).

- **Usuario**: Facu (proyectos.gerguar@gmail.com). Habla español rioplatense, prefiere respuestas honestas y técnicas sin sobreingeniería. Valora "auto mode" — avanzar sin pedir confirmación constante salvo decisiones estratégicas.
- **Sitio**: pronósticos H/D/A para partidos del Mundial + 5 grandes ligas, comparador de equipos, insights con Claude API, ranking de jugadores, perfiles individuales.
- **Repo**: `Gerguar/FUTVS` (GitHub) — **PRIVADO** desde 6-jun-2026.
- **Hosting**: Hostinger Business via FTP (auto-deploy en push a `web/**`).
- **Branch principal**: `main`.

---

## 2. Stack técnico

| Capa | Tech |
|---|---|
| Frontend | **Single file `web/index.html`** (~4500 líneas: HTML + CSS + JS inline). Vanilla JS + Chart.js 4.4.1 (CDN con SRI). |
| Backend / DB | **Supabase** (PostgREST REST API) — RLS activada desde 6-jun. |
| ML / Modelo | Python 3.11 — Elo + Dixon-Coles + XGBoost + ensamble lineal |
| CI/CD | GitHub Actions (cron + push triggers) |
| Insights | Anthropic Claude API — **claude-haiku-4-5-20251001** ($1/$5 por 1M tokens) con web_search_20260209 |
| Bot Twitter | `@FutVersus_` con tweepy + pricing pay-per-use ($0.015/tweet sin URL) |
| Hosting | Hostinger Business + LiteSpeed (FTP en `deploy-hostinger.yml`) |

**No usa**: React/Vue, bundler, npm, Docker, k8s. Es deliberadamente simple.

---

## 3. Estructura del repo

```
football-forecast/
├── web/
│   ├── index.html              ← TODO el frontend
│   ├── .htaccess               ← SPA fallback + headers (ojo: Hostinger bloquea 3, ver §13)
│   ├── favicon.ico/png
│   └── data/
│       ├── insights.json       ← generado por Claude cada 6h
│       ├── insights_semana.json ← weekly news de NewsAPI
│       ├── predictions.json    (clubes — vacío en off-season)
│       └── claude_debug.json   ← último error de Claude API si falla
├── src/
│   ├── predict.py              ← modelo CLUBES (XGBoost calibrado, 64 features)
│   ├── predict_mundial.py      ← modelo MUNDIAL (DC+Elo+Plant+Mercado). xG expuesto en notas.
│   ├── generate_insights.py    ← ⚠️ REESCRITO POR OTRO CHAT (ver §15)
│   ├── dixon_coles.py / elo.py
│   ├── features.py             ← 64 features XGBoost clubes
│   ├── train.py
│   ├── data_ingest.py / ingest_couk.py / ingest_wc2026.py
│   ├── ingest_partidos_selecciones_2025.py  ← martj42, ahora auto-crea equipos en liga 8 (no-Mundial)
│   ├── ingest_elo_selecciones.py
│   ├── ingest_pinnacle_wc.py   ← cuotas Pinnacle del Mundial
│   ├── ingest_squads.py
│   ├── ingest_fbref_stats.py   ← ⚠️ falla silenciosamente, estadisticas_jugador estaba en 0 (ver §16)
│   ├── enrich_jugadores_mundial.py
│   ├── seed_*.py               ← historicos H2H y plantillas
│   ├── integrate_lesiones_mundial.py  ← matcher estricto + overrides
│   ├── generate_insights.py    ← (ver arriba)
│   ├── twitter_bot.py          ← Bot @FutVersus_ con cooldown 6h
│   ├── twitter_templates.py    ← plantillas tweets + 48 banderas Mundial
│   ├── supabase_writer.py      ← sb_get, sb_post, sb_patch
│   ├── supabase_sync.py
│   └── config.py / player_ratings.py / team_ratings.py
├── data/
│   ├── matches.parquet         ← 12.500 partidos clubes
│   ├── predictions.json        ← clubes (vacío off-season)
│   ├── dc_state.json / dc_state_selecciones.json
│   ├── elo_state.json / elo_state_selecciones.json
│   ├── team_ratings.json
│   ├── wc2026_market_odds.json
│   ├── wc2026_ajustes_lesiones.json    ← brasil(rodrygo,militao,estevao) + austria(baumgartner) + escocia(gilmour)
│   ├── lesiones_overrides_manual.json  ← overrides manuales + vetos (Yamal, Romero, Paredes)
│   ├── twitter_state.json
│   └── models/
├── .github/workflows/          ← 13 workflows
├── .gitattributes              ← .htaccess en LF (LiteSpeed-safe)
├── HANDOFF.md                  ← este archivo
└── requirements.txt
```

---

## 4. Schema Supabase (PostgREST)

URL en `SUPABASE_URL`, key en `SUPABASE_SERVICE_KEY` (.env local + GitHub secrets).

| Tabla | Columnas clave |
|---|---|
| `ligas` | 1=Champions, 2=LaLiga, 3=Premier, 4=SerieA, 5=Bundesliga, 6=Ligue1, 7=Selecciones Mundial, **8=Otras selecciones FIFA** (creada 5-jun para rivales no-Mundial: Zambia, Mauritania, Puerto Rico, etc) |
| `equipos` | id, nombre, abreviacion, escudo_url, color_prim/sec, liga_id, pais, fundacion, estadio |
| `equipo_meta` | equipo_id + metadata histórica |
| `jugadores` | id, nombre, equipo_id, posicion, nacionalidad, **fecha_nac** (cargada 7-jun), rating, valor_mercado, pace/shooting/passing/dribbling/defending/physic, gk_* |
| `estadisticas_jugador` | jugador_id, temporada (incluye `'carrera'` para totales Transfermarkt), partidos, goles, asistencias, amarillas, rojas, xg, xa, etc. **1247 filas con temporada='carrera' cargadas 7-jun** |
| `mercado_historico` | jugador_id, anio, valor, club |
| `minutos_por_anio` | jugador_id, anio, minutos |
| `partidos` | id, liga_id, equipo_local_id, equipo_visitante_id, fecha, temporada, goles_local, goles_visitante, estado, grupo |
| `pronosticos` | partido_id, prob_local/empate/visitante, factor_* (localidad/forma/h2h/tabla/bajas/goles), notas (con `xG esperado: X.XX-Y.YY`) |
| `stats_partido` | stats por equipo (posesion, remates, etc.) |
| `forma_reciente` | **VISTA Postgres** que computa W/D/L auto desde `partidos` |
| `selecciones_elo` | slug, nombre, elo (scrapeado de eloratings.net) |
| `finales_historicas` / `h2h_historico` | históricos cabeza a cabeza |

**RLS activada** en todas las tablas con policy `FOR SELECT TO anon, authenticated` (cualquiera lee, solo `service_role` escribe). Ver §13.

---

## 5. Modelo de probabilidad — MUNDIAL 2026

**`src/predict_mundial.py`** combina 4 fuentes con pesos lineales:

```
Con mercado:    P = 0.35·DC + 0.20·Elo + 0.10·Plantilla + 0.35·Mercado
Sin mercado:    P = 0.55·DC + 0.30·Elo + 0.15·Plantilla
```

**Componentes**: Dixon-Coles selecciones (martj42, xi=0.0035, home_adv=0.26), Elo selecciones (con +50 anfitrión), Plantilla (top_xi_avg de jugadores.rating), Mercado (Pinnacle devigged).

**Ajustes post-mix**: HOST_TEAM_IDS={130 México, 151 USA, 135 Canadá}, fase grupos `p_draw × 1.10` vs eliminación `× 0.85`, lesiones desde JSON (-3pp/-1.5pp con cap -6pp por equipo).

**xG ahora se expone en `notas`** (commit 49cb003) — formato `"xG esperado: 1.69-0.35"`. El frontend lo parsea para los factors GOLES en proporción correcta.

**Cobertura ratings jugadores Mundial**: 1247/1247 (100%) con rating + EA FC 26 + **carrera completa Transfermarkt** desde 7-jun.

---

## 6. Modelo de probabilidad — CLUBES

**`src/predict.py` + `src/train.py`** — XGBoost calibrado con isotónica, 64 features. Hiperparams `max_depth=4, lr=0.03, n_estimators=2000`. Entrenado sobre 4.282 partidos. Sin lineup/H2H/lesiones nominales. Predicciones → `data/predictions.json` + tabla `pronosticos`.

**Estado off-season**: hoy `predictions.json` está vacío porque ligas europeas terminaron en mayo. Volverá en agosto.

---

## 7. Workflows automáticos (.github/workflows/)

13 workflows totales (consumo: **~580 min/mes**, holgado bajo límite 2000 min/mes de repo privado).

| Workflow | Cron | Qué hace |
|---|---|---|
| **insights** | `30 */6 * * *` | Claude (Haiku 4.5) + web_search → `insights.json` + `insights_semana.json` |
| **mundial** | `20 */6 * * *` | ingest selecciones + Pinnacle + integrate_lesiones + predict_mundial |
| **smart-sync** | `*/30 * * * *` | si hay partido vencido: refresh resultados + sync |
| **twitter** | `*/15 * * * *` | bot @FutVersus_: prematch / postmortem / lesiones con cooldown 6h |
| **predict** | `0 */12 * * *` + domingos | retrain clubes + predict |
| **weekly-news** | `0 8 * * 1` | NewsAPI top deportivos → `insights_semana.json` |
| **squads** | `0 6 * * 1` | football-data.org ingest plantillas |
| **player-stats** | `0 8 * * 3` | fbref stats (⚠️ falla silenciosamente — ver §16) |
| **deploy-hostinger** | push `web/**` | FTP a Hostinger (intermitente, ver §13) |
| **backfill / evaluate / sync / publish-hostinger** | manual | utilitarios |

Secrets: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FOOTBALL_DATA_TOKEN`, `ANTHROPIC_API_KEY`, `THE_ODDS_API_KEY`, `API_FOOTBALL_KEY`, `TWITTER_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_SECRET`, `NEWS_API_KEY`, `FTP_HOST/USERNAME/PASSWORD`.

---

## 8. Rutas del frontend (SPA router en `web/index.html`)

```js
NavRouter.parse():
  /                          → home (pronósticos)
  /comparador                → comparador con preset (?a=barcelona&b=real-madrid)
  /insights                  → insights de Claude
  /goat                      → Messi vs Cristiano
  /ranking                   → ranking jugadores
  /partido/:slug             → detalle (mexico-vs-sudafrica-2026-06-11)
  /estadisticas              → dummy
  /glosario                  → dummy
  /blog                      → dummy
  /sugerir-partido           → dummy
  /colaboraciones            → dummy
  /prensa                    → dummy
  /sobre-nosotros            → dummy
  /metodologia               → dummy
  /pautas-editoriales        → dummy
  /privacidad                → dummy
  /terminos-de-uso           → dummy
  /cookies                   → dummy
```

Nav superior 4 items: `Pronósticos 📈 / Comparador ⚖️ / Ranking 🏆 / Insights ✦`. Logo FV verde + badge Temporada arriba a la derecha en mobile.

---

## 9. CAMBIOS PRINCIPALES — sesión 4 al 7 jun 2026

### Bot de Twitter (@FutVersus_)
- ✅ MVP completo con tweepy + workflow cada 15 min (commits `1c38be4`, `d38bffa`)
- ✅ Cooldown 6h anti-falsos-positivos (`7d3ca65`)
- ✅ Matcher estricto + overrides manuales en `integrate_lesiones` (`1f9d5d8`)
- ✅ Vetos (Yamal, Romero, Paredes — los 3 jugarán el Mundial) (`e832b67`)
- ✅ Tweets sin URL ($0.015 vs $0.20) + CTA "↗ bio" (`c4c2b3d`, `3b54ac4`)
- 4 tweets reales posteados: Rodrygo, Eder Militão, Estevão (Brasil), Christoph Baumgartner (Austria), Billy Gilmour (Escocia).

### Frontend
- ✅ Rutas `/partido/slug` con botón "🔗 Compartir" (`d0af68e`)
- ✅ "¿Cómo se llegó a esta probabilidad?" rediseño con **dots de fuerza** (no barras) y datos reales por factor (`140f310`)
- ✅ Comparativa por línea top 5/2 con marca estrella (`1b0b6d0`)
- ✅ Ranking jugadores dedup ES/EN (Brasil/Brazil) (`cc63b9c`)
- ✅ Footer mobile grid 2×2 + hero ocultar teaser GOAT + badge "Temporada" derecha (`cadd806`, `01df72d`)
- ✅ Footer redes: solo X (link real a @FutVersus_) + ✉ a /colaboraciones (`f8e6da5`)
- ✅ Detalle jugador: card "🌐 Carrera" con Nacionalidad, Edad, PJ, G, A, Y, R (`92c7577`)
- ✅ Radar habilidades: padding interno (datos no se salen del cuadro) (`a41f1ba`)

### Datos cargados
- ✅ xG real en pronosticos.notas (modelo Mundial) (`49cb003`)
- ✅ 1247 fechas de nacimiento + stats carrera Transfermarkt (commits del 7-jun)
- ✅ ingest_partidos_selecciones_2025 ahora auto-crea equipos liga 8 para rivales no-Mundial (`8208dd2`)
- ✅ +408 partidos cargados que antes se descartaban silenciosamente

### Seguridad — sesión 6-jun (ver §13)
- ✅ RLS Supabase: 14 tablas con policy SELECT-only para anon
- ✅ XSS escape en weekly news + factors (`58a7f4f`)
- ✅ SRI en Chart.js (`699959a`)
- ✅ Repo cambiado a PRIVADO
- ⚠️ HSTS, X-Frame-Options, Permissions-Policy bloqueados por Hostinger WAF — declarados en .htaccess pero no se aplican (ver §13)

---

## 10. CONVENCIONES DE TRABAJO

- **Idioma**: español rioplatense ("vos", "tenés"). Honestidad sobre todo.
- **Commits**: estilo conventional commits flexible (`ui:`, `feat:`, `fix:`, `chore:`, `security:`). Co-author Claude.
- **No sobreingeniería**: archivo único HTML está OK, no proponer migrar a React.
- **Auto mode**: avanzar sin pedir confirmación constante salvo decisiones estratégicas (qué archivar / dónde poner $ / decisiones de seguridad).
- **Bash**: hago `cd /c/Users/facun/football-forecast` al inicio (el cwd a veces salta).

---

## 11. Setup local

```bash
cd /c/Users/facun/football-forecast
eval "$(grep -v '^#' .env | grep -E 'SUPABASE' | sed 's/^/export /')"
PYTHONIOENCODING=utf-8 python -m src.predict_mundial   # ejemplo
```

Python 3.10 en `C:\Users\facun\AppData\Local\Programs\Python\Python310\python.exe`.

`truststore.inject_into_ssl()` para TLS en Windows.

Deps clave: `pandas, numpy, scipy, xgboost, scikit-learn, openpyxl, pyarrow, cloudscraper, truststore, tweepy>=4.14, python-dotenv`.

---

## 12. CREDENCIALES Y TOKENS

### En `.env` local (Facu)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (rol service_role, bypasea RLS)
- `FOOTBALL_DATA_TOKEN`, `API_FOOTBALL_KEY`
- `GITHUB_TOKEN` (PAT fine-grained) — **expira en 90 días desde 6-jun-2026 (~5-sep-2026)**. Permite a Claude disparar workflows desde local. Renovar antes que expire.

### En GitHub Secrets (no expuestos en código)
- `ANTHROPIC_API_KEY` — modelo actual `claude-haiku-4-5-20251001`. **Cuidado**: Facu cargó créditos $X, monitorear consumo.
- `TWITTER_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_SECRET` para @FutVersus_
- `NEWS_API_KEY` para weekly news
- `FTP_HOST/USERNAME/PASSWORD` para Hostinger deploy

### Anon Supabase key
- Pública por diseño, hardcodeada en `web/index.html` línea 1858. **Está bien** que esté ahí (es el patrón Supabase). Su seguridad la dan las RLS, no su privacidad.

---

## 13. LIMITACIONES CONOCIDAS DE INFRAESTRUCTURA

### Hostinger Business filtra 3 headers HTTP
Probado exhaustivamente: HSTS, X-Frame-Options, Permissions-Policy **NO se aplican** aunque estén en `.htaccess`. Hostinger los filtra a nivel WAF.

Opciones para futuro:
- **A. Ticket de soporte a Hostinger**: pedir habilitación (texto del ticket en el chat del 6-jun-2026).
- **B. Cloudflare delante**: free tier, 20 min setup, soluciona + da CDN + DDoS + rate limit.

### Deploy FTP intermitente
`deploy-hostinger.yml` falla ~30% de los runs por `Timeout (control socket)`. Workaround: re-run manual. Ya está `state-name: .ftp-deploy-sync-state-v2.json` para evitar cache de sync.

### CORS Supabase abierto
PostgREST refleja cualquier Origin. Cualquier sitio puede LEER tu DB (no escribir, RLS lo bloquea). Aceptado por ahora. Cloudflare lo cerraría.

### Repo es PRIVADO
GitHub Actions: 580 min/mes uso vs 2000 min/mes límite. Holgado.

### Anthropic API
- Modelo actual `claude-haiku-4-5-20251001` ($1 in / $5 out por 1M tokens).
- Web search: `web_search_20260209` + beta header `web-search-2026-02-09`.
- Run de insights: ~$0.05 c/u con web_search incluido.
- Cron cada 6h → ~$15/mes. Si se acaba el saldo, las secciones quedan vacías y Facu tiene que recargar en `console.anthropic.com/settings/billing`.

---

## 14. AUDITORÍA DE SEGURIDAD — 6/7-jun-2026

### Hecho ✅
1. RLS Supabase aplicada (SQL en el chat). Anon = read-only en 14 tablas.
2. HSTS, X-Frame-Options, Permissions-Policy agregados al .htaccess (no se aplican, ver §13).
3. XSS escape en weekly news (`safeUrl()` + `insEsc()` en titulo/fuente/url).
4. XSS escape en factors del partido (name, desc, labels, locTeam).
5. SRI en Chart.js (`sha384-dug+JxfBvk...`).
6. Repo cambiado a privado.

### Pendiente (decisiones de Facu)
- Backup Supabase: NO por ahora.
- Cloudflare delante para resolver headers + CORS: pendiente decisión.
- Ticket soporte Hostinger: pendiente envío.

---

## 15. ⚠️ DECISIONES PENDIENTES — ACCIÓN INMEDIATA EN EL PRÓXIMO CHAT

### A. `src/generate_insights.py` fue sobrescrito por otro chat

Entre el 5 y 7 de junio alguien (probablemente otro chat de Claude en una sesión paralela de Facu) **reescribió completamente** `src/generate_insights.py` con una versión más simple. Yo le agregué el filtro `FORMA_LIGAS=(7,)` recién (commit `ad9936d`) para que "Forma reciente" no mezcle clubes.

**Features que tenía mi versión y se perdieron:**
| Feature | Mi versión (perdida) | Versión actual |
|---|---|---|
| Modelo Claude | `claude-haiku-4-5-20251001` ($0.018/run) | `claude-sonnet-4-5` ($0.085/run) ← 5x más caro |
| Web search tool | `web_search_20260209` | NO usa web_search |
| Prompt estricto anti-falsos-positivos | Sí (frases canónicas) | Prompt genérico |
| Vetos manuales (Yamal, Romero, Paredes, etc) | Sí, lee `lesiones_overrides_manual.json` | No |
| Fallback partidos Mundial cuando `predictions.json` vacío | Sí | No |
| `_write_debug()` para diagnosticar HTTP errors | Sí | No |
| Tendencias mínimo 3 items garantizadas | Sí | No |
| `build_forma_section` con GF/GC desde Transfermarkt | Sí | `build_forma_reciente` nuevo (GF/GC de ventana 365d) |

**Le pregunté a Facu 4 opciones y dismisseó** (sin tokens). El próximo chat debe **preguntarle de nuevo**:
1. Restaurar mi versión completa (recuperar todo lo perdido) — ~10 min.
2. Mezclar: dejar arquitectura nueva pero re-agregar features (Haiku, web_search, prompt estricto, overrides, fallback Mundial) — ~20 min.
3. Dejar como está (perdemos features, costo Claude sube ~5x).
4. Investigar qué commit sobrescribió antes de tocar.

**Recomendación**: opción 2 (mezcla).

### B. Headers de seguridad bloqueados por Hostinger

Pendiente: decidir si abrir ticket de soporte a Hostinger o instalar Cloudflare delante. Texto del ticket ya redactado, en el chat del 6-jun.

---

## 16. PENDIENTES DEL HANDOFF ORIGINAL (siguen abiertos)

- **Enriquecer ratings de jugadores de CLUBES**: hoy todos en 70 default + attrs EAFC null. Premier/LaLiga/SerieA/Bundesliga/Ligue1. Mismo flujo que Mundial pero a escala. No urgente (off-season).
- **Investigar `player-stats.yml`** (FBref) que no popula `estadisticas_jugador` para clubes. Fallaba silencioso.
- **Sedes específicas por partido** del Mundial: hoy solo "anfitrión vs no". Podría aplicar home_adv parcial cuando Argentina juega en USA vs en Canadá.
- **Persistir `expected_goals` en columnas propias** (hoy está en `notas` como texto).
- **Bot Twitter**: migrar a clubes después del Mundial (cambiar `FORMA_LIGAS` y filtros).

---

## 17. PRIMERA PROMPT PARA NUEVO CLAUDE

Copiá esto al inicio del próximo chat:

```
Hola, soy Facu / proyectos.gerguar@gmail.com, vengo de un chat anterior
trabajando en FutVersus (futversus.com), mi plataforma de análisis de
fútbol con foco en Mundial 2026.

Repo: /c/Users/facun/football-forecast
Último commit: ad9936d (fix forma reciente solo selecciones Mundial)

Leé `HANDOFF.md` en el root del repo COMPLETO antes de arrancar — está
actualizado al 7-jun-2026 e incluye:
- Stack, schema Supabase, modelo, workflows.
- Cambios hechos del 4 al 7 jun (bot Twitter, ruta /partido/, dots de
  fuerza en factors, datos de carrera Transfermarkt, auditoría de
  seguridad RLS+XSS+SRI+repo privado).
- §13 limitaciones Hostinger (bloquea 3 headers).
- §15 DECISIONES PENDIENTES: principalmente decidir qué hacer con
  src/generate_insights.py que fue sobrescrito por otro chat.

Hablame en español rioplatense, sin sobreingeniería.

Cuando tengas el contexto cargado decime "OK, listo" y arranco con
[lo que vayas a pedir, ej: "decidamos qué hacer con generate_insights"].
```

---

## 18. DATOS DE CONTACTO

- GitHub: `Gerguar/FUTVS` (privado)
- Supabase project: en `.env` (no compartir)
- Hostinger: FTP en GitHub secrets
- Anthropic API: key en GitHub Secrets + `console.anthropic.com/settings/billing`
- Twitter: `@FutVersus_` + keys en GitHub Secrets

---

¡Suerte en la próxima sesión! 🚀
