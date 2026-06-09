# 🤝 Handoff FutVersus — para próxima sesión de Claude

**Pegá este archivo (o un resumen) al inicio del nuevo chat para que el próximo Claude no arranque a ciegas.**

Última actualización: **9 jun 2026** (sesión cerrada por tokens). Ver §15 — DECISIONES PENDIENTES.

---

## 1. ¿Qué es este proyecto?

**FutVersus** (`futversus.com`) — plataforma de análisis estadístico de fútbol con foco en el **Mundial 2026** (arranca 11 de junio 2026).

- **Usuario**: Facu (proyectos.gerguar@gmail.com). Habla español rioplatense, prefiere respuestas honestas y técnicas sin sobreingeniería. Valora "auto mode" — avanzar sin pedir confirmación constante salvo decisiones estratégicas.
- **Sitio**: pronósticos H/D/A para partidos del Mundial + 5 grandes ligas, comparador de equipos, insights con Claude + NewsAPI, ranking de jugadores, perfiles individuales.
- **Repo**: `Gerguar/FUTVS` (GitHub) — **PRIVADO** desde 6-jun-2026.
- **Hosting**: Hostinger Business via FTP (auto-deploy en push a `web/**`).
- **Branch principal**: `main`.

---

## 2. Stack técnico

| Capa | Tech |
|---|---|
| Frontend | **Single file `web/index.html`** (~5000 líneas: HTML + CSS + JS inline). Vanilla JS + Chart.js 4.4.1 (CDN con SRI). |
| Backend / DB | **Supabase** (PostgREST REST API) — RLS activada desde 6-jun. |
| ML / Modelo | Python 3.11 — Elo + Dixon-Coles + XGBoost + ensamble lineal |
| CI/CD | GitHub Actions (cron + push triggers) |
| Insights | **Claude API** (claude-sonnet-4-5) para xG / tendencias / dato curioso + **NewsAPI** para alertas |
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
│       ├── insights.json       ← generado cada 6h (Claude + NewsAPI)
│       ├── insights_semana.json ← weekly news de NewsAPI
│       ├── predictions.json    (clubes — vacío en off-season)
│       └── claude_debug.json   ← último error de Claude API si falla
├── src/
│   ├── predict.py              ← modelo CLUBES (XGBoost, 64 features)
│   ├── predict_mundial.py      ← modelo MUNDIAL (DC+Elo+Plant+Mercado). xG en notas.
│   ├── generate_insights.py    ← Claude + NewsAPI (alertas) + fallback Mundial
│   ├── fetch_news.py           ← Cliente NewsAPI con filtros antiestafa
│   ├── dixon_coles.py / elo.py
│   ├── features.py             ← 64 features XGBoost clubes
│   ├── ingest_partidos_selecciones_2025.py  ← martj42, auto-crea equipos liga 8
│   ├── ingest_pinnacle_wc.py   ← cuotas Pinnacle del Mundial
│   ├── ingest_fbref_stats.py   ← ⚠️ falla silenciosamente
│   ├── integrate_lesiones_mundial.py  ← matcher estricto + overrides
│   ├── twitter_bot.py          ← Bot @FutVersus_ con cooldown 6h
│   ├── twitter_templates.py    ← plantillas + 48 banderas Mundial
│   ├── supabase_writer.py
│   └── config.py / player_ratings.py / team_ratings.py
├── data/
│   ├── matches.parquet         ← 12.500 partidos clubes
│   ├── wc2026_market_odds.json ← Pinnacle 22 partidos del Mundial
│   ├── wc2026_ajustes_lesiones.json ← brasil + austria + escocia + argentina
│   ├── lesiones_overrides_manual.json ← vetos (Yamal, Romero, Paredes) + overrides
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
| `ligas` | 1=Champions, 2=LaLiga, 3=Premier, 4=SerieA, 5=Bundesliga, 6=Ligue1, 7=Selecciones Mundial, **8=Otras selecciones FIFA** (rivales no-Mundial) |
| `equipos` | id, nombre, abreviacion, escudo_url, color_prim/sec, liga_id, pais |
| `equipo_meta` | equipo_id + metadata histórica (ano_fundacion, capacidad_estadio, socios, títulos, etc.) — usado por comparador |
| `jugadores` | id, nombre, equipo_id, posicion, nacionalidad, **fecha_nac** (cargada 7-jun), rating, valor_mercado, EA FC attrs |
| `estadisticas_jugador` | jugador_id, temporada (incluye `'carrera'` para totales Transfermarkt). **1247 con temporada='carrera'** |
| `mercado_historico` / `minutos_por_anio` | data histórica del jugador |
| `partidos` | id, liga_id, equipo_local_id, equipo_visitante_id, fecha, goles_local, goles_visitante, estado, grupo |
| `pronosticos` | partido_id, prob_*, factor_*, notas (con `xG esperado: X-Y`) |
| `forma_reciente` | **VISTA Postgres** que computa W/D/L auto desde `partidos` |
| `selecciones_elo` | slug, nombre, elo (eloratings.net) |
| `h2h_historico` | históricos H2H |

**RLS activada** en todas las tablas con policy `FOR SELECT TO anon, authenticated`.

---

## 5. Modelo de probabilidad — MUNDIAL 2026

**`src/predict_mundial.py`** combina 4 fuentes con pesos lineales:

```
Con mercado:    P = 0.35·DC + 0.20·Elo + 0.10·Plantilla + 0.35·Mercado
Sin mercado:    P = 0.55·DC + 0.30·Elo + 0.15·Plantilla
```

**Ajustes post-mix**: HOST_TEAM_IDS={130 México, 151 USA, 135 Canadá}, fase grupos `p_draw × 1.10` vs eliminación `× 0.85`, lesiones desde JSON.

**xG ahora se expone en `notas`** (commit 49cb003) — formato `"xG esperado: 1.69-0.35"`. El frontend lo parsea para los factors GOLES.

---

## 6. Workflows automáticos

13 workflows totales (consumo: **~580 min/mes**, bajo límite 2000 min/mes).

| Workflow | Cron | Qué hace |
|---|---|---|
| **insights** | `30 */6 * * *` | Claude + NewsAPI → `insights.json` (xG/tendencias/dato + alertas) |
| **mundial** | `20 */6 * * *` | ingest selecciones + Pinnacle + integrate_lesiones + predict_mundial |
| **smart-sync** | `*/30 * * * *` | si hay partido vencido: refresh resultados |
| **twitter** | `*/15 * * * *` | bot @FutVersus_: prematch / postmortem / lesiones |
| **predict** | `0 */12 * * *` + domingos | retrain clubes + predict |
| **weekly-news** | `0 8 * * 1` | NewsAPI → `insights_semana.json` |
| **squads / player-stats / deploy-hostinger** | | varios |

Secrets necesarios: `SUPABASE_*`, `FOOTBALL_DATA_TOKEN`, `ANTHROPIC_API_KEY`, `THE_ODDS_API_KEY`, `API_FOOTBALL_KEY`, `TWITTER_*`, `NEWS_API_KEY`, `FTP_*`.

---

## 7. Rutas del frontend (SPA router)

```js
NavRouter.parse():
  /                          → home (pronósticos próximos)
  /comparador                → comparador con preset Barcelona vs Atlético + slugs via ?a=&b=
  /insights                  → insights de Claude + NewsAPI
  /goat                      → Messi vs Cristiano
  /ranking                   → ranking jugadores
  /finalizados               → ⭐ NUEVO: partidos finalizados con filtros
  /partido/:slug             → detalle (mexico-vs-sudafrica-2026-06-11)
  /estadisticas, /glosario, /blog, /sugerir-partido, /colaboraciones,
  /prensa, /sobre-nosotros, /metodologia, /pautas-editoriales,
  /privacidad, /terminos-de-uso, /cookies → páginas dummy del footer
```

---

## 8. CAMBIOS PRINCIPALES — sesión 8-9 jun 2026

### Alertas del modelo: Claude → NewsAPI
Detectamos que Claude inventaba alertas (Neymar rodilla=falso, De Bruyne sanción=inventado, Mbappé "4 días"=desactualizado). Solución:
- ✅ `build_alertas_from_newsapi()` reemplaza generación con Claude.
- ✅ 7 queries qInTitle con keywords (lesion, baja, descartado, rotura, etc.).
- ✅ Filtros antiestafa:
  - `ALERTA_OTROS_DEPORTES`: basket, beisbol, ciclismo, Tour de Francia, F1, NBA, etc.
  - `ALERTA_NO_ES_ALERTA`: homenajes, gestos, VPN, ofertas, criptos.
  - `ANCLAS_CONTEXT`: exige terms explícitos de fútbol (no países solos).
- ✅ Deduplica por primeras 5 palabras, máx 4 alertas, ordenadas por nivel (critical/warning/info).
- ✅ Workflow `insights.yml` ahora pasa `NEWS_API_KEY` como env var.
- Commits: `5a2af06`, `2e3cd4d`, `6faaf1f`.

### Oportunidades del algoritmo: fallback Mundial
La sección estaba vacía porque `predictions.json` (clubes off-season) no tenía `market_probabilities`. Fix:
- ✅ Si `predictions.json` vacío → levanta partidos PROGRAMADOS del Mundial desde Supabase + cuotas Pinnacle de `data/wc2026_market_odds.json` (22 partidos).
- ✅ También parsea xG de `notas` para `expected_goals`.
- Detecta 2 oportunidades: Empate Portugal-RD Congo (+12.7pp), Victoria Panamá (+12.0pp).
- Commit: `406cf18`.

### Forma reciente: solo selecciones Mundial
El `generate_insights.py` reescrito perdió el filtro de liga. Restauré: solo equipos `liga_id=7`. Ventana 365 días para tener los últimos 5 de selecciones (juegan poco vs clubes). Commit: `ad9936d`.

### UI Home
- ✅ Filtro **Mundial 2026 como default** al cargar la home (en lugar de "Todos"). Commit `5e8e465`.
- ✅ Stats sidebar: `Partidos\nacertados` en 2 líneas + porcentaje grande + `diff ≤ 10pp` en ajustados. Commits `234a3f1`, `d743e39`, `2d8e756`, `baebca3`.
- ✅ Sidebar mobile: al costado de los partidos (sticky), no horizontal arriba. Commits `6d69242`.
- ✅ Home centrado a 1100px (mismo que facts). Sidebar sobresale a la **izquierda** en viewports ≥1400px (float + margin negativo). En menores queda inline. Commits `237c405`, `a9dc27f`.
- ✅ **Partidos finalizados sacados del home**. Reemplazo por CTA "Ver partidos finalizados →" al lado de la paginación. Commits `57e1551`, `5cb8feb`.
- ✅ **Nueva sección home-extra** debajo de partidos: 2 cols (Comparador con 5 versus clásicos + Ranking con top 5 jugadores). Commit `64bb408`.

### Nueva ruta `/finalizados`
- ✅ Lista todos los partidos con resultado, ordenados por fecha desc.
- ✅ Filtros de liga (Todos / Mundial / Champions / LaLiga / Premier / SerieA).
- ✅ Default Mundial 2026.
- ✅ Paginación de 12.
- ✅ Botón ← Inicio.
- Commit `57e1551`.

### Comparador
- ✅ Preset Barcelona vs Atlético de Madrid al abrir. Commit `a182e15`.
- ✅ Nuevos pesos diferenciados por modo. Commits `7942b21`, `702ee50`:
  - **Clubes**: liga 1.2 / copa_nac 1 / champions 6 / internacionales 2.4 / supercopas 0.8 / mundial_clubes 5 / antiguedad 0.05/año / estadio 0.04/1k / socios 0.04/1k / h2h_victoria 0.8 / h2h_goleada 2 / h2h_final 3.
  - **Selecciones**: mundial_sel 5 / final_mundial 1 / copa_continental 2 / aparicion_mundial 0.3 / h2h_victoria 0.3 / h2h_goleada 1 / h2h_final 2.
- ✅ Tabla comparativa más grande (escudos 56px, píldoras valor 34px alto). Commits `cac2d53`, `508fe5d`.
- ✅ Comparador mobile: selectores horizontales (uno al lado del otro, no apilados). Commit `3341547`.

---

## 9. Cambios anteriores (3-7 jun) — resumen ultra-corto

- **Bot Twitter @FutVersus_** completo con cooldown 6h, vetos manuales (Yamal/Romero/Paredes), tweets sin URL ($0.015), CTA "↗ bio". Posteó 5 alertas reales (Rodrygo, Militão, Estevão, Baumgartner, Gilmour).
- **Frontend**: rutas `/partido/slug`, "¿Cómo se llegó?" rediseñado con dots de fuerza, comparativa por línea top 5/2, ranking dedup ES/EN.
- **Datos**: xG real en notas, 1247 jugadores con fecha de nacimiento + stats carrera Transfermarkt, +408 partidos cargados que se descartaban.
- **Seguridad**: RLS Supabase activada, XSS escape, SRI en Chart.js, repo cambiado a privado. Hostinger filtra 3 headers (HSTS, X-Frame, Permissions-Policy) — declarados pero no aplican (ver §13).

---

## 10. CONVENCIONES DE TRABAJO

- **Idioma**: español rioplatense ("vos", "tenés"). Honestidad sobre todo.
- **Commits**: estilo conventional commits flexible (`ui:`, `feat:`, `fix:`, `chore:`, `security:`). Co-author Claude.
- **No sobreingeniería**: archivo único HTML está OK.
- **Auto mode**: avanzar sin pedir confirmación constante.
- **Bash**: hago `cd /c/Users/facun/football-forecast` al inicio.

---

## 11. Setup local

```bash
cd /c/Users/facun/football-forecast
eval "$(grep -v '^#' .env | grep -E 'SUPABASE' | sed 's/^/export /')"
PYTHONIOENCODING=utf-8 python -m src.predict_mundial   # ejemplo
```

Python 3.10 en `C:\Users\facun\AppData\Local\Programs\Python\Python310\python.exe`.

---

## 12. CREDENCIALES Y TOKENS

### En `.env` local (Facu)
- `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` (service_role, bypasea RLS)
- `FOOTBALL_DATA_TOKEN`, `API_FOOTBALL_KEY`
- `GITHUB_TOKEN` (PAT fine-grained) — **expira ~5-sep-2026**. Permite a Claude disparar workflows desde local.

### En GitHub Secrets
- `ANTHROPIC_API_KEY` — modelo actual `claude-sonnet-4-5` ($3 in / $15 out por 1M tokens).
- `TWITTER_API_KEY/SECRET/ACCESS_TOKEN/ACCESS_SECRET` para @FutVersus_
- `NEWS_API_KEY` para weekly news Y alertas
- `FTP_HOST/USERNAME/PASSWORD` para Hostinger deploy

### Anon Supabase key
- Pública por diseño, hardcodeada en `web/index.html` línea ~1858. **Está bien** que esté ahí.

---

## 13. LIMITACIONES CONOCIDAS

### Hostinger Business filtra 3 headers HTTP
HSTS, X-Frame-Options, Permissions-Policy **NO se aplican** vía `.htaccess`. Hostinger los filtra a nivel WAF. Opciones:
- Ticket de soporte (texto redactado en historial)
- Cloudflare delante (free, ~20 min setup, soluciona + CDN + DDoS)

### Deploy FTP intermitente
`deploy-hostinger.yml` falla ~30% por timeout. Workaround: re-run manual. Ya tiene `state-name: v2`.

### CORS Supabase abierto
PostgREST refleja cualquier Origin. Solo lectura (RLS bloquea writes). Aceptado.

### Anthropic API
- Modelo actual `claude-sonnet-4-5` ($3 in / $15 out por 1M tokens).
- Run de insights: ~$0.05-0.10 c/u.
- Cron cada 6h → ~$15-20/mes.
- Si se acaba el saldo, las secciones de Claude quedan vacías. Recargar en `console.anthropic.com/settings/billing`.

---

## 14. AUDITORÍA DE SEGURIDAD

### Hecho ✅
1. RLS Supabase aplicada (anon = read-only).
2. HSTS / X-Frame-Options / Permissions-Policy declarados (no se aplican por Hostinger).
3. XSS escape en weekly news (`safeUrl()` + `insEsc()`) + factors.
4. SRI en Chart.js.
5. Repo cambiado a privado.

### Pendiente
- Backup Supabase: NO por ahora.
- Cloudflare delante: pendiente decisión.

---

## 15. ⚠️ DECISIONES PENDIENTES — ACCIÓN INMEDIATA EN EL PRÓXIMO CHAT

### A. `src/generate_insights.py` — features perdidas
Entre el 5 y 7 de junio alguien (probablemente otro chat de Claude en una sesión paralela de Facu) **reescribió** `src/generate_insights.py` con una versión más simple. En esta sesión le agregamos:
- ✅ Filtro `FORMA_LIGAS=(7,)` para forma reciente solo selecciones Mundial.
- ✅ `build_alertas_from_newsapi()` para alertas reales (no inventadas).
- ✅ Fallback Mundial en `load_predictions()` para oportunidades.

**Pero todavía falta** (features de la versión vieja perdidas):
- ❌ Modelo Claude `claude-haiku-4-5-20251001` (más barato 5x). Actual: `claude-sonnet-4-5` ($0.085/run vs $0.018/run).
- ❌ `web_search_20260209` tool en Claude — sin esto, las tendencias y dato curioso siguen siendo "inventados" por el modelo aunque las alertas ahora son reales.
- ❌ Lectura de `lesiones_overrides_manual.json` desde el prompt para que Claude no proponga jugadores vetados.
- ❌ `_write_debug()` para diagnosticar HTTP errors.
- ❌ Tendencias mínimo 3 items garantizadas con prompt estricto.

**Recomendación**: opción 2 del HANDOFF anterior — "Dejar la nueva + agregar features faltantes". ~20 min de trabajo.

### B. Headers de seguridad bloqueados por Hostinger
Decidir: ticket de soporte a Hostinger O Cloudflare delante. Texto del ticket ya redactado, en historial del 6-jun.

### C. Cloudflare delante (cierra muchas cosas en un solo paso)
Resuelve simultáneamente: headers bloqueados + CORS abierto + sin rate limit + sin CDN edge. Free tier alcanza. ~20 min setup.

---

## 16. PENDIENTES DEL HANDOFF ORIGINAL (siguen abiertos)

- **Enriquecer ratings de jugadores de CLUBES**: hoy todos en 70 default. No urgente (off-season).
- **Investigar `player-stats.yml`** (FBref) que falla silencioso.
- **Sedes específicas por partido** del Mundial: home_adv parcial cuando Argentina juega en USA vs Canadá.
- **Persistir `expected_goals` en columnas propias** (hoy en `notas` como texto).
- **Bot Twitter**: migrar a clubes post-Mundial.

---

## 17. ESTADO ACTUAL DEL SITIO

### Funciona perfecto
- Home con filtro Mundial default, sidebar de stats sticky a la izquierda (sobresale en pantallas ≥1400px).
- Comparador con preset Barcelona vs Atlético, tabla grande, pesos diferenciados por modo.
- /finalizados como nueva ruta.
- Sección home-extra: Comparador + Ranking debajo de partidos.
- Insights con alertas de NewsAPI verificables (no más Neymar lesión de rodilla falso).
- Oportunidades del algoritmo con 2 detectadas (Portugal-RD Congo, Ghana-Panamá).
- Bot Twitter funcionando (cooldown 6h, vetos manuales).

### Último commit antes del cierre
`3341547` — ui(comparador mobile): selectores horizontales sin desbordar.

---

## 18. PRIMERA PROMPT PARA NUEVO CLAUDE

Copiá esto al inicio del próximo chat:

```
Hola, soy Facu / proyectos.gerguar@gmail.com, vengo de un chat anterior
trabajando en FutVersus (futversus.com), mi plataforma de análisis de
fútbol con foco en Mundial 2026.

Repo: /c/Users/facun/football-forecast
Último commit: 3341547 (ui comparador mobile selectores horizontales)

Leé `HANDOFF.md` en el root del repo COMPLETO antes de arrancar — está
actualizado al 9-jun-2026 e incluye:
- Stack, schema Supabase, modelo, workflows.
- Cambios del 8-9 jun (alertas via NewsAPI, oportunidades Mundial,
  nueva ruta /finalizados, sección home-extra, comparador rediseñado,
  sidebar sobresaliendo a la izquierda).
- §13 limitaciones Hostinger (bloquea 3 headers).
- §15 DECISIONES PENDIENTES:
   * A) Restaurar features perdidas en generate_insights.py (Haiku 4.5,
     web_search, vetos manuales, debug). ~20 min.
   * B/C) Cloudflare delante (cierra headers + CORS + rate limit + CDN
     en un solo paso). ~20 min setup.

Hablame en español rioplatense, sin sobreingeniería.

Cuando tengas el contexto cargado decime "OK, listo" y arranco con
[lo que vayas a pedir, ej: "decidamos qué hacer con Cloudflare"].
```

---

## 19. DATOS DE CONTACTO

- GitHub: `Gerguar/FUTVS` (privado)
- Supabase project: en `.env` (no compartir)
- Hostinger: FTP en GitHub secrets, plan Business
- Anthropic API: `console.anthropic.com/settings/billing`
- Twitter: `@FutVersus_` + keys en GitHub Secrets

---

¡Suerte en la próxima sesión! 🚀
