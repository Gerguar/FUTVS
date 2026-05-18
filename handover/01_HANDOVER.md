# FutPronostico — Documento de traspaso

> Generado: 2026-05-18 17:58

## 1. Objetivo del proyecto

Sistema de pronostico de partidos de futbol profesional. Genera probabilidades 1X2
(local/empate/visitante) con modelo Dixon-Coles + Elo + XGBoost (sin calibrador,
empiricamente lo empeoraba).

- Frontend: HTML estatico en Netlify, lee live de Supabase.
- Backend: GitHub Actions corre cada 6h y mantiene la base actualizada.
- Datos: football-data.org (current + UCL) + football-data.co.uk (6 historicas) +
  Understat (player stats).

## 2. Cuentas y credenciales

Todas bajo `proyectos.gerguar@gmail.com`.

| Servicio | URL | Notas |
|---|---|---|
| GitHub | https://github.com/Gerguar/FUTVS | Privado |
| Supabase | https://supabase.com/dashboard/project/dyeouwqtebrvioesrbcf | OAuth via GitHub |
| Netlify | https://futpronostico.netlify.app/ | OAuth via GitHub, conectado al repo |
| football-data.org | API free tier | Token en GH Secret |

### GitHub Secrets (Settings -> Secrets -> Actions)

```
FOOTBALL_DATA_TOKEN     ← del registro en football-data.org
SUPABASE_URL            = https://dyeouwqtebrvioesrbcf.supabase.co
SUPABASE_SERVICE_KEY    = (la service_role key del proyecto Supabase — bypasea RLS)
```

Service_role key actual:

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR5ZW91d3F0ZWJydmlvZXNyYmNmIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3ODYxMTgzMiwiZXhwIjoyMDk0MTg3ODMyfQ.SeSXQAKVAHO5CI5L7C0rdp_34bWSu8vSvVS-FG_-GDQ
```

Anon key (en el HTML, public read-only):

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR5ZW91d3F0ZWJydmlvZXNyYmNmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg2MTE4MzIsImV4cCI6MjA5NDE4NzgzMn0.t_9uVZLKl-khTfjnOvlebTUIYZ9C2fMVDM-6ZqMDMaA
```

## 3. Estructura del repo

```
football-forecast/
├── README.md
├── requirements.txt
├── gp.ps1                    ← atajo PowerShell para commit+push
├── netlify.toml
├── SUPABASE_SETUP.md
│
├── src/
│   ├── config.py             ← COMPETITIONS, hiperparametros, paths
│   ├── team_normalize.py     ← mapeo nombres → slug canonico (real_madrid, etc.)
│   ├── data_ingest.py        ← ingest football-data.org (current season + UCL)
│   ├── ingest_couk.py        ← ingest football-data.co.uk (6 años historicas)
│   ├── ingest_squads.py      ← squads + metadata equipos + logos ligas
│   ├── ingest_fbref_stats.py ← player stats via Understat (renombrado pero archivo igual)
│   ├── elo.py                ← rating Elo dinamico
│   ├── dixon_coles.py        ← Poisson bivariado con corrección DC
│   ├── features.py           ← feature engineering snapshot temporal
│   ├── xgb_model.py          ← XGBoost multiclase + isotonic (calibrador desactivado)
│   ├── train.py              ← train del pipeline completo
│   ├── train_dc.py           ← train DC + calibrador (descartado experimentalmente)
│   ├── predict.py            ← predicciones, con fallback DC si XGB falla
│   ├── evaluate.py           ← backtest honesto
│   ├── backtest.py           ← rolling-origin backtest
│   ├── metrics.py            ← log_loss, brier, accuracy, calibration
│   ├── supabase_writer.py    ← escribe pronosticos + helpers HTTP (sb_get/sb_post/sb_patch)
│   └── supabase_sync.py      ← crea/actualiza equipos + partidos + resultados
│
├── web/index.html            ← HTML del frontend (90KB, vanilla JS)
│
├── data/
│   ├── matches.parquet       ← ~12.500 partidos combinados (slug = team_id)
│   ├── dc_state.json
│   ├── elo_state.json
│   ├── models/               ← xgb_1x2.json, calibrator.joblib, feature_meta.json
│   ├── predictions.json      ← output del ultimo predict
│   └── backtest_report.json
│
└── .github/workflows/
    ├── predict.yml           ← cron 6h (ingest+train+predict+sync+writer)
    ├── backfill.yml          ← manual (re-baja todo el historico)
    ├── sync.yml              ← manual rapido (solo sync equipos/partidos/escudos)
    ├── squads.yml            ← cron semanal (squads + metadata)
    ├── fbref-stats.yml       ← manual (player stats via Understat)
    └── evaluate.yml          ← manual (backtest)
```

## 4. Schema Supabase

### Tablas (lo que tiene cada una hoy)

| Tabla | Filas aprox | Estado |
|---|---|---|
| `ligas` | 6 | Champions, La Liga, Premier, Serie A, Bundesliga, Ligue 1. logo_url cargado. |
| `equipos` | 132 | Todos los equipos top 6 competiciones. nombre, abreviacion, liga_id, pais, escudo_url, color_prim, color_sec, fundacion, estadio. |
| `partidos` | ~250 | "programado" o "finalizado". goles_local/visitante se actualizan auto cuando football-data marca FINISHED. |
| `pronosticos` | 1:1 con partidos programados | UNIQUE en partido_id. prob_local/empate/visitante (0-100), factor_* (0-100), notas |
| `forma_reciente` | VIEW | Calcula W/D/L ultimos 5 desde partidos automaticamente. |
| `jugadores` | ~4500 | Plantel real de los 132 equipos. nombre, posicion (POR/DEF/MED/DEL), nacionalidad, fecha_nac. rating en 70 default. |
| `estadisticas_jugador` | ~867 + bug 500s | Cargando via Understat. UNIQUE en (jugador_id, temporada). |
| `mercado_historico` | 0 | VACIA. Requiere Transfermarkt scraping. |
| `minutos_por_anio` | 0 | VACIA. Requiere fbref scraping (bloqueado en GH) o API paga. |

### SQL items creados manualmente

```sql
create unique index if not exists pronosticos_partido_id_uq
  on pronosticos (partido_id);

create unique index if not exists estadisticas_jugador_jugador_temporada_uq
  on estadisticas_jugador (jugador_id, temporada);
```

### View forma_reciente (definicion)

```sql
SELECT equipo_id,
       array_agg(resultado) AS forma
FROM ( SELECT todos.equipo_id, todos.resultado, todos.fecha,
              row_number() OVER (PARTITION BY todos.equipo_id
                                 ORDER BY todos.fecha DESC) AS rn
       FROM ( SELECT partidos.equipo_local_id AS equipo_id, partidos.fecha,
                     CASE WHEN goles_local>goles_visitante THEN 'W'
                          WHEN goles_local=goles_visitante THEN 'D'
                          ELSE 'L' END AS resultado
              FROM partidos WHERE estado='finalizado'
              UNION ALL
              SELECT equipo_visitante_id, fecha,
                     CASE WHEN goles_visitante>goles_local THEN 'W'
                          WHEN goles_visitante=goles_local THEN 'D'
                          ELSE 'L' END
              FROM partidos WHERE estado='finalizado'
       ) todos
) ranked
WHERE rn <= 5
GROUP BY equipo_id;
```

## 5. Modelo: estado y metricas

| Aspecto | Detalle |
|---|---|
| Pipeline | Dixon-Coles + Elo (estructural) → XGBoost (clasificador final) |
| Calibrador isotonico | **Desactivado**. Empeoraba el modelo (+0.034 log loss). |
| Training data | ~12.500 partidos: 6 temporadas top 5 ligas (co.uk) + actual + UCL (.org) |
| Identificador equipos | SLUG canonico (real_madrid, bayern_munich, etc.) — `team_normalize.py` |
| Features clave | Elo diff, DC lambdas, rolling xGD (proxy goles), descanso, fatigue, odds historicas |
| Metricas honestas (backtest 30d) | log_loss 1.015, brier 0.61, accuracy 51% |
| Benchmark mercado bookmakers | log_loss 0.997, accuracy 51.5% |
| Gap al mercado | 0.018 log loss (excelente para modelo gratis sin odds live) |

## 6. Workflow operativo

```
predict.yml (cron cada 6h, también dispatch manual)
  1. data_ingest.py --days-ahead 14 --skip-couk
  2. train.py (solo domingos 00:00 UTC o dispatch manual)
  3. predict.py --horizon 14 --snapshot 24h (con fallback DC)
  4. supabase_sync.py --horizon 14 (crea/updatea equipos + partidos + resultados)
  5. supabase_writer.py --mode from-json (upsert en pronosticos)

squads.yml (cron lunes 06:00 UTC + dispatch manual)
  ingest_squads.py
  - Fetch /competitions/{code}/teams para top 6
  - Crea equipos faltantes, update metadata (fundacion, estadio, escudo)
  - Reemplaza plantelles (jugadores)
  - Update logos de ligas
```

## 7. Decisiones tomadas (importantes)

1. **Calibrador isotonico descartado** — Honest holdout disjoint mostro que empeora DC. DC ya viene bien calibrado de fabrica.
2. **Slugs como ID universal** — Permite unificar football-data.org + football-data.co.uk.
3. **football-data.co.uk para historico** — Free, sin auth, incluye odds de 5 bookmakers en CSVs.
4. **The Odds API descartado** — Free tier (500 req/mes) insuficiente.
5. **Modo on-demand removido** — Antes calculabamos probs para matchups hardcodeados. Ahora todos los partidos vienen de fixtures reales.
6. **fbref bloqueado en GH Actions** — IPs de datacenter rechazadas. Migramos a Understat.
7. **forma_reciente es VIEW** — Auto-calcula desde partidos. No escribirle.

## 8. Estado al cierre de esta sesion

✅ Funcionando OK:
- Sistema end-to-end automatico, cron cada 6h
- 132 equipos, 6 ligas, ~250 partidos en Supabase con metadata completa
- ~4.500 jugadores cargados (sin stats todavia)
- Modelo en produccion con log_loss honesto 1.015
- HTML deployado en Netlify, lee live

⚠️ Pendientes / bugs:
- player-stats workflow: Understat funciona desde GH Actions! Pero hay **HTTP 500 en algunos upserts**.
  Probable causa: dos players de Understat matchean (fuzzy) al mismo jugador en Supabase,
  generando duplicados (jugador_id, temporada) que violan el unique index.
  Fix probable: dedupar antes del upsert, manteniendo el mejor match.
- rating de jugadores siempre 70 default
- mercado_historico y minutos_por_anio vacios

## 9. Roadmap propuesto

| Prioridad | Item | Costo | Notas |
|---|---|---|---|
| Alta | Fix bug HTTP 500 en player stats (dedupe en supabase_writer) | $0 | ~30 min de codigo |
| Alta | Activar cron semanal del player-stats una vez que el bug este fixed | $0 | 1 linea de YAML |
| Media | Agregar columna xg en estadisticas_jugador y persistirlo (Understat lo tiene) | $0 | SQL + 5 lineas |
| Media | Mejorar rating de jugador con formula derivada (edad + pos + xG) | $0 | Mejora visual |
| Baja | API-Football si queres lesiones + stats premium | $10/mes | +0.02 log loss |
| Baja | football-data Tier Two | €10/mes | Cobertura EUL/EUCL |

## 10. Comandos utiles (PowerShell desde C:\Users\facun\football-forecast)

```powershell
# atajo de commit+push (incluido en el repo)
.\gp.ps1 "mensaje del commit"

# correr modelo localmente (requiere env vars de .env)
python -m src.data_ingest --backfill --since 2020-07-01
python -m src.train
python -m src.predict --horizon 14
python -m src.evaluate --test-days 30
```

## 11. Para nueva sesion de Claude — orden de upload

Subi estos archivos en orden:

1. `01_HANDOVER.md`  ← este documento (overview general)
2. `02_CODE_PYTHON.md`  ← todo el codigo Python del modelo
3. `03_CODE_WORKFLOWS.md`  ← workflows YAML + scripts auxiliares
4. `04_CODE_WEB.md`  ← HTML del frontend
5. `05_DATA_SUPABASE.md`  ← schema + queries de ejemplo de Supabase
6. `06_DOCS.md`  ← README + SUPABASE_SETUP del proyecto

Una vez subidos, decile a Claude:

> "Soy Facu / proyectos.gerguar@gmail.com. Te paso el contexto completo del proyecto
> FutPronostico. Empezamos desde aca. Mi pendiente inmediato es: [tu pregunta]"

Y va a entender exactamente donde estamos.
