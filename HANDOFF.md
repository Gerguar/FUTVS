# 🤝 Handoff FutVersus — para próxima sesión de Claude

**Pegá este archivo (o un resumen) al inicio del nuevo chat para que el próximo Claude no arranque a ciegas.**

Última actualización: 4 jun 2026.

---

## 1. ¿Qué es este proyecto?

**FutVersus** (`futversus.com`) — plataforma de análisis estadístico de fútbol con foco en el **Mundial 2026**.

- **Usuario**: Facu (proyectos.gerguar@gmail.com) — habla en español rioplatense, prefiere respuestas honestas y técnicas sin sobreingeniería.
- **Sitio**: pronósticos H/D/A para partidos de las 5 grandes ligas + Mundial 2026, comparador de equipos all-time, sección de insights con Claude API, perfiles de jugadores.
- **Repo**: `Gerguar/FUTVS` (GitHub).
- **Hosting**: Hostinger (deploy automático via FTP cuando se pushea a `web/**`).
- **Branch principal**: `main`.

---

## 2. Stack técnico

| Capa | Tech |
|---|---|
| Frontend | **Single file `web/index.html`** (~3400 líneas: HTML + CSS + JS inline). Vanilla JS + Chart.js (vía CDN). |
| Backend / DB | **Supabase** (PostgREST REST API) |
| ML / Modelo | Python 3.11 — Elo + Dixon-Coles + XGBoost + ensamble lineal |
| CI/CD | GitHub Actions (cron + push triggers) |
| Insights | Anthropic Claude API (claude-sonnet-4-5) con web_search tool |
| Hosting | Hostinger via FTP (`deploy-hostinger.yml`) |

**No usa**: React/Vue, bundler, npm, Docker, k8s. Es deliberadamente simple.

---

## 3. Estructura del repo

```
football-forecast/
├── web/
│   ├── index.html           ← TODO el frontend (HTML/CSS/JS inline)
│   ├── .htaccess            ← SPA fallback + cache headers
│   ├── favicon.ico/png      ← logo FV verde
│   ├── apple-touch-icon.png
│   └── data/
│       ├── insights.json    ← generado por Claude cada 6h
│       └── predictions.json (clubes)
├── src/
│   ├── predict.py           ← modelo CLUBES (XGBoost calibrado)
│   ├── predict_mundial.py   ← modelo MUNDIAL (DC+Elo+Plant+Mercado)
│   ├── dixon_coles.py
│   ├── elo.py
│   ├── features.py          ← 64 features para XGBoost de clubes
│   ├── train.py
│   ├── data_ingest.py       ← football-data.org
│   ├── ingest_couk.py       ← football-data.co.uk (resultados liga)
│   ├── ingest_wc2026.py     ← fixture Mundial
│   ├── ingest_elo_selecciones.py  ← eloratings.net
│   ├── ingest_pinnacle_wc.py      ← cuotas Pinnacle del Mundial
│   ├── ingest_partidos_selecciones_2025.py ← martj42 hist
│   ├── ingest_squads.py     ← plantillas de clubes
│   ├── ingest_fbref_stats.py
│   ├── enrich_jugadores_mundial.py ← EA FC 26 CSV
│   ├── enrich_jugadores_mundial_msmc.py ← API msmc.cc
│   ├── enrich_jugadores_mundial_fallback.py ← imputación (no usar)
│   ├── seed_jugadores_mundial.py
│   ├── seed_h2h_historico.py
│   ├── seed_h2h_manual.py
│   ├── seed_h2h_laliga_bdfutbol.py
│   ├── seed_h2h_premier_11v11.py
│   ├── seed_h2h_seriea_transfermarkt.py
│   ├── seed_h2h_bundesliga_worldfootball.py
│   ├── seed_h2h_ligue1_worldfootball.py
│   ├── integrate_lesiones_mundial.py ← parsea insights → ajustes
│   ├── generate_insights.py ← Claude API + web_search
│   ├── calibrate_pesos_mundial.py ← grid search
│   ├── fit_dc_selecciones.py
│   ├── team_ratings.py      ← top_xi_avg / attack / defense
│   ├── player_ratings.py
│   ├── supabase_writer.py   ← sb_get, sb_post, sb_patch helpers
│   ├── supabase_sync.py
│   ├── replay_elo_selecciones.py
│   ├── config.py            ← Elo/DC/XGB configs
│   └── data/                ← CSVs estáticos (overrides, sedes, etc.)
├── data/
│   ├── matches.parquet      ← 12.500 partidos históricos (clubes)
│   ├── predictions.json
│   ├── dc_state.json        ← Dixon-Coles clubes
│   ├── dc_state_selecciones.json ← Dixon-Coles Mundial
│   ├── elo_state.json
│   ├── elo_state_selecciones.json
│   ├── team_ratings.json    ← top_xi_avg por equipo
│   ├── wc2026_market_odds.json     ← cuotas Pinnacle (refresh cada 6h)
│   ├── wc2026_ajustes_lesiones.json ← parseado de insights
│   ├── wc2026_pesos_calibrados.json
│   └── models/
│       ├── xgb_1x2.json     ← XGBoost serializado
│       ├── calibrator.joblib
│       └── feature_meta.json
├── .github/workflows/       ← 11 workflows
├── HANDOFF.md               ← este archivo
└── requirements.txt
```

---

## 4. Schema Supabase (PostgREST)

URL en `SUPABASE_URL`, key en `SUPABASE_SERVICE_KEY` (.env local + GitHub secrets).

| Tabla | Columnas clave |
|---|---|
| `ligas` | id (1=Champions, 2=LaLiga, 3=Premier, 4=SerieA, 5=Bundesliga, 6=Ligue1, 7=Selecciones FIFA) |
| `equipos` | id, nombre, abreviacion, escudo_url, color_prim/sec, liga_id, pais, fundacion, estadio |
| `equipo_meta` | equipo_id, ano_fundacion, ligas, copas, champions, mundiales_clubes, etc. |
| `jugadores` | id, nombre, equipo_id, posicion (POR/DEF/MED/DEL), nacionalidad, fecha_nac, rating, valor_mercado, notas, **pace/shooting/passing/dribbling/defending/physic** (EA FC 26 campo), **gk_diving/handling/kicking/positioning/reflexes/speed** (EA FC GK) |
| `estadisticas_jugador` | jugador_id, temporada, partidos, minutos, goles, asistencias, amarillas, rojas, xg, xa, shots, npxg, key_passes |
| `mercado_historico` | jugador_id, anio, valor, club |
| `minutos_por_anio` | jugador_id, anio, minutos |
| `partidos` | id, liga_id, equipo_local_id, equipo_visitante_id, fecha, temporada, goles_local, goles_visitante, estado (programado/finalizado), grupo |
| `pronosticos` | partido_id, prob_local/empate/visitante, factor_localidad/forma/h2h/tabla/bajas/goles, notas |
| `stats_partido` | partido_id + stats por equipo (posesion, remates, etc.) |
| `forma_reciente` | equipo_id, forma (array W/D/L) |
| `selecciones_elo` | slug, nombre, elo (scrapeado de eloratings.net) |
| `finales_historicas` | equipo_a_id, equipo_b_id, ganador_id, competencia, anio |
| `h2h_historico` | equipo_a_id, equipo_b_id, victorias_a/b, empates, goleadas_a/b, partidos, fuente |
| `pronosticos`/comparador: tabla pivote canónica con a_id < b_id |

**Estado de población clubes** (importante): los jugadores de clubes (Premier/LaLiga/SerieA/Bundesliga/Ligue1) tienen sólo `nombre`, `equipo_id`, `posicion`, `nacionalidad`, `fecha_nac`. **Todos los demás campos están vacíos** (rating=70 default, attrs EAFC null, stats=0 filas). Mundial sí tiene todo enriquecido.

---

## 5. Modelo de probabilidad — MUNDIAL 2026

**`src/predict_mundial.py`** combina 4 fuentes con pesos lineales:

```
Con mercado:    P = 0.35·DC + 0.20·Elo + 0.10·Plantilla + 0.35·Mercado
Sin mercado:    P = 0.55·DC + 0.30·Elo + 0.15·Plantilla
```

**Componentes:**

1. **Dixon-Coles selecciones** — `data/dc_state_selecciones.json`. Entrenado con martj42 desde 1990 (11.151 partidos, 80 selecciones), time-decay xi=0.0035, home_adv=0.26, rho=-0.13.
2. **Elo selecciones** — tabla Supabase `selecciones_elo` (scrapeada de eloratings.net). Bonus +50 al anfitrión local.
3. **Plantilla** — `data/team_ratings.json` con top_xi_avg derivado de `jugadores.rating`.
4. **Mercado** — `data/wc2026_market_odds.json` cuotas Pinnacle Arcadia API (sin auth, league_id=2686) devigged. Cobertura actual: ~22 de 72 partidos (resto se carga cuando Pinnacle lo publica).

**Ajustes post-mix:**
- **Sede real**: HOST_TEAM_IDS = {130 México, 151 USA, 135 Canadá}. Si participan, NO neutral.
- **Fase**: `< 2026-06-30` = grupos → `p_draw × 1.10`. Eliminación → `× 0.85`.
- **Lesiones**: `data/wc2026_ajustes_lesiones.json` parseado de `web/data/insights.json` con `src/integrate_lesiones_mundial.py`. Solo aplica a jugadores en squad con rating≥78. Danger=-3pp, warning=-1.5pp. Cap por equipo -6pp.

**Cobertura ratings jugadores Mundial**: 1209/1247 (96.9%) con rating real (EA FC 26 CSV + msmc.cc API + overrides manuales del CSV `src/data/mundial_overrides_manual.csv` + 337 cargados manual por Facu vía xlsx).

---

## 6. Modelo de probabilidad — CLUBES

**`src/predict.py` + `src/train.py`** — XGBoost calibrado con isotónica, 64 features.

- Entrenado sobre 4.282 partidos (jun 2024 → feb 2026), 694 validación.
- Hiperparams: `max_depth=4, lr=0.03, n_estimators=2000, subsample=0.8, colsample_bytree=0.8, reg_lambda=2.0, early_stopping=100`.
- Features groups: Elo (5), Dixon-Coles (10), Mercado (5), Goles rolling (8), Fatiga/calendario (13), Plantilla EAFC (9), xG rolling (10), Lineup (5), is_neutral.
- Mercado pesa muchísimo (the_odds_api). Sin lineup/H2H/lesiones nominales.
- Predicciones → `data/predictions.json` + tabla `pronosticos`.

---

## 7. Workflows automáticos (.github/workflows/)

| Workflow | Cron | Frecuencia | Qué hace |
|---|---|---|---|
| **insights** | `10 */6 * * *` | cada 6h | Claude API + web search → `web/data/insights.json` |
| **predict** | `0 */12 * * *` + domingos | cada 12h + retrain semanal | data_ingest + predict.py para CLUBES |
| **mundial** | `20 */6 * * *` | cada 6h | ingest_partidos_selecciones_2025 + ingest_pinnacle_wc + integrate_lesiones + predict_mundial |
| **smart-sync** | `*/30 * * * *` | cada 30 min si hay partido vencido | data_ingest + supabase_sync + ingest_wc2026 + ingest_elo_selecciones + integrate_lesiones + predict_mundial |
| **squads** | `0 6 * * 1` | lunes 06 UTC | ingest_squads de football-data.org |
| **player-stats** | `0 8 * * 3` | miércoles 08 UTC | ingest_fbref_stats (Understat) — **falla silenciosamente, tabla en 0** |
| **deploy-hostinger** | push `web/**` | reactivo | FTP a Hostinger |
| **publish-hostinger** | push `web/**` | reactivo | branch hostinger |
| **backfill** | manual | — | recarga histórica |
| **evaluate** | manual | — | backtest |
| **sync** | manual | — | refresh rápido |

Secrets necesarios: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `FOOTBALL_DATA_TOKEN`, `ANTHROPIC_API_KEY`, `THE_ODDS_API_KEY`, `API_FOOTBALL_KEY`.

---

## 8. Rutas del frontend (SPA router en `web/index.html`)

```js
NavRouter.parse():
  /                  → home (pronósticos)
  /comparador        → comparador con preset por slug (?a=barcelona&b=real-madrid)
  /insights          → insights de Claude
  /goat              → Messi vs Cristiano (estática)
```

Nav superior: 3 items (`Pronósticos 📈`, `Comparador ⚖️`, `Insights ✦`). Logo FV verde + temporada badge.

---

## 9. Trabajo reciente (últimos 30 commits aprox.)

**Rama actual: `main`. Último commit: `ca24147`.**

### Modelo (todas las 5 mejoras del roadmap)
1. ✅ Cuotas Pinnacle integradas (commit `e72fc9d`)
2. ✅ Calibración pesos (mejora 0.04%, no aplicar — commit `f9108a0`)
3. ✅ Sede real anfitriones (commit `7a33ec7`)
4. ✅ Fase de grupos vs eliminación (commit `e0c5125`)
5. ✅ Lesiones desde insights (commit `85c9f91`)
- ✅ Cobertura jugadores Mundial 96.9% (commit `b68d324`)
- ✅ Partidos selecciones 2025 cargados a Supabase (`8be54e7`)

### Frontend / UI
- Router SPA: `/comparador`, `/insights`, `/goat`
- Favicon FV + título "FutVersus"
- Nav reorganizado: 3 items con símbolos a derecha
- Cards de partido: equipos horizontal, % centrados sobre cada segmento (oculta <5%)
- 9 partidos por página, separación 1.6rem
- Mensaje off-season para ligas top sin partidos
- Comparador refactorizado con regla "más partidos gana" (4 H2H historicos cargados de xlsx: LaLiga BDFutbol, Premier 11v11, SerieA Transfermarkt, Bundesliga + Ligue1 worldfootball)
- Detalle partido: cuadro temporada con barras escalas absolutas (max 50 goles, max 95 rating XI), V/E/D real (no %), sin "Últimos 5" duplicado
- Radar partido: 4 vértices (ATAQUE/DEFENSA/MEDIOCAMPO/ARQUERO), top-5 DEL/DEF/MED + top-2 POR por rating, eje fijo 60-90
- Detalle jugador: 5 stats (PJ/G/A/Y/R), radar habilidades arriba, mapa de calor max-width 520px, tabs Mercado/Minutos fusionados
- Home: layout 2-col con sidebar sticky (acertados/ajustados/no_acertados) cubriendo próximos + finalizados con mismo grid
- Hero: contador Mundial 2026 (Tu pronóstico, tu Mundial) + teaser GOAT clickeable
- Página `/goat`: tabla unificada con títulos verticales laterales, barras proporcionales, 4 secciones: Producción ofensiva / Trofeos individuales / Títulos colectivos / Selección
- Sección "Dato histórico" (rotating facts) reemplaza el CTA del home
- Zona horaria local del browser (fix con `_asUTC` agregando `Z` a ISOs sin tz)

---

## 10. Pendientes conocidos / próximos pasos

### En el aire (no urgentes)
- **Persistir expected_goals (λ y μ del DC)** en pronosticos. Hoy se calculan pero se descartan. Opciones: 2 columnas nuevas en Supabase, en `notas` (texto), o JSON paralelo. Facu lo dejó "para más adelante".
- **Bot de Twitter automático**: armar workflow para postear lesiones/pronósticos/resultados. API free tier alcanza. Conversación quedó en "decidir si vale la pena".
- **Enriquecer ratings de jugadores de CLUBES**: hoy todos en 70 default + attrs EAFC null. Sería mismo flujo que Mundial (CSV `ismailoksuz/EAFC26-DataHub` + msmc.cc API).
- **Investigar por qué `player-stats.yml` no popula `estadisticas_jugador`**: tabla en 0 filas, posiblemente el job falla silencioso.
- **Sedes específicas por partido** (no solo "anfitrión vs no"): podría aplicarse home_adv parcial cuando Argentina juega en USA (cerca de su hinchada) vs en Canadá (lejos).

### Verificado y descartado
- ❌ XGBoost para Mundial: calibración mostró 0.04% mejora → no vale la pena.
- ❌ Enriquecer los 38 jugadores que quedan en 70 default: son suplentes 22-26 de selecciones débiles, no mueve la aguja.

---

## 11. Convenciones de trabajo

- **Idioma**: español rioplatense ("vos", "tenés", "che" OK pero medirlo).
- **Honestidad**: Facu valora respuestas honestas. Si una mejora es ruido (0.04%), decirlo. No inventar datos.
- **Commits**: estilo conventional commits flexible (`ui:`, `feat:`, `fix:`, `chore:`). Co-author Claude.
- **No sobreingeniería**: archivo único HTML está OK, no proponer migrar a React.
- **Trabajar con auto mode**: avanzar sin pedir confirmación constante salvo decisiones estratégicas (qué archivar / qué scrapear / dónde poner $).
- **Bash desde `cd /c/Users/facun/football-forecast`**: el cwd a veces salta al de skills, recordar volver.

---

## 12. Setup local (Windows + Git Bash en WSL)

```bash
cd /c/Users/facun/football-forecast
eval "$(grep -v '^#' .env | grep -E 'SUPABASE' | sed 's/^/export /')"
PYTHONIOENCODING=utf-8 python -m src.predict_mundial   # ejemplo
```

Python 3.10 (instalado en `C:\Users\facun\AppData\Local\Programs\Python\Python310\python.exe`).

Dependencias clave: `pandas, numpy, scipy, xgboost, scikit-learn, tweepy?, openpyxl, pyarrow, cloudscraper, truststore`.

`truststore.inject_into_ssl()` se usa para TLS en Windows (`football-data.co.uk` tiene chain incompleta para certifi).

---

## 13. Primera prompt para nuevo Claude

Copiá esto al inicio del próximo chat:

```
Hola, vengo de un chat anterior donde estuvimos trabajando en FutVersus (futversus.com),
mi plataforma de análisis de fútbol con foco en Mundial 2026.

Leé `HANDOFF.md` en el root del repo para entender el contexto completo:
arquitectura, schema Supabase, modelo de probabilidad, workflows automáticos,
commits recientes y pendientes.

Repo: /c/Users/facun/football-forecast
Último commit: ca24147
Hablame en español rioplatense, sin sobreingeniería.

Cuando tengas el contexto cargado, decime "OK, listo" y arranco con
[lo que vas a pedir, ej.: "quiero agregar X"].
```

---

## 14. Datos de contacto / cuentas

- GitHub: `Gerguar/FUTVS`
- Supabase project: en URL del `.env` (no compartir por chat)
- Hostinger: FTP credentials en GitHub secrets
- Anthropic API: key en `.env` y `ANTHROPIC_API_KEY` secret
- Twitter API: pendiente de aplicar si Facu decide hacer el bot

---

¡Suerte en la próxima sesión! 🚀
