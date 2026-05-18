# FutPronostico — Documentacion del proyecto

## `README.md`

# Football Forecast — Champions / Internacionales

Sistema híbrido de pronóstico 1X2 para competiciones internacionales (UCL, Europa League, Libertadores, etc.).

Implementa la receta del documento de referencia:
**Dixon-Coles + Elo + XGBoost multiclase calibrado**, con backtesting temporal (rolling-origin), evaluación por log loss / Brier / curvas de calibración, y odds de mercado como feature.

## Arquitectura

```
┌──────────────────────┐
│ GitHub Actions cron  │  (gratis, corre cada 6h)
│  - fetch fixtures    │
│  - fetch odds        │
│  - actualiza Elo/DC  │
│  - reentrena/predice │
│  - upsert Supabase   │
└──────────┬───────────┘
           │  service_role key (GitHub Secret)
           ▼
┌──────────────────────┐
│      Supabase        │
│   pronosticos table  │
└──────────┬───────────┘
           │  anon key (read-only, RLS)
           ▼
┌──────────────────────┐
│  futpronostico_v9    │
│  .html (sin cambios) │
└──────────────────────┘
```

> Ver **SUPABASE_SETUP.md** para configurar la integración con tu DB.

## Estructura

```
football-forecast/
├── src/                 # Modelo y pipeline
│   ├── config.py        # Ligas, ventanas, paths, snapshots temporales
│   ├── data_ingest.py   # Fetch fixtures/results/odds desde APIs
│   ├── elo.py           # Rating Elo online
│   ├── dixon_coles.py   # Modelo Poisson con corrección DC
│   ├── features.py      # Feature engineering con snapshot temporal
│   ├── xgb_model.py     # XGBoost multiclase 1X2
│   ├── calibration.py   # Calibración isotónica
│   ├── backtest.py      # Rolling-origin backtest
│   ├── metrics.py       # log loss, Brier, calibration curve
│   ├── train.py         # Entry point de entrenamiento
│   └── predict.py       # Entry point de inferencia → JSON
├── data/                # Estado persistente + output
│   ├── matches.parquet
│   ├── elo_state.json
│   ├── models/
│   └── predictions.json # ← consumido por la web
├── web/                 # Frontend estático (Netlify)
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── .github/workflows/
│   └── predict.yml      # Cron job
└── tests/               # Tests de no-leakage temporal
```

## Setup local

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows PowerShell
pip install -r requirements.txt

# Variables de entorno necesarias (.env)
# FOOTBALL_DATA_TOKEN=...        # https://www.football-data.org/ (free)
# THE_ODDS_API_KEY=...           # https://the-odds-api.com/ (free tier)

# Backfill histórico (una vez)
python -m src.data_ingest --backfill --since 2018-08-01

# Entrenar y calibrar
python -m src.train

# Generar predicciones de los próximos partidos
python -m src.predict --horizon 7d --out data/predictions.json
```

## Deploy en Netlify

1. Subir este repo a GitHub.
2. En Netlify: New site → conectar el repo → **Publish directory: `web`**, Build command: vacío.
3. En GitHub → Settings → Secrets → agregar `FOOTBALL_DATA_TOKEN` y `THE_ODDS_API_KEY`.
4. El workflow corre solo cada 6 horas y commitea `data/predictions.json`. Netlify rebuildea.

## Metodología (resumen)

| Capa | Qué hace | Por qué |
|------|----------|---------|
| **Elo dinámico** | Rating online por equipo, ajustado por margen y localía. | Estabiliza fuerza con pocos datos, sirve como prior. |
| **Dixon-Coles** | Poisson bivariado con corrección para scorelines bajos y ponderación temporal exponencial. | Genera intensidades λ_home / λ_away y matriz de scoreline. |
| **Feature engineering** | Snapshot temporal estricto a `t-24h` / `t-60min`. Rolling/EWMA de xG, descanso, congestión, fatiga, viaje, odds. | Evita data leakage temporal. |
| **XGBoost multiclase** | Combina Elo + DC + contexto + odds para producir P(H), P(D), P(A). | Captura no linealidades e interacciones. |
| **Calibración isotónica** | Ajusta probabilidades sobre bloque temporal separado. | Sin esto, las probabilidades del boosting no son confiables. |
| **Backtest rolling-origin** | Entrena en pasado, calibra en bloque siguiente, testea en el próximo. | Imita operación real. |

## Métricas que reportamos

- **Log loss** (principal)
- **Brier score**
- **Accuracy**
- **Calibration curve** (reliability diagram)
- **Log loss rolling** por matchday (detección de drift)

## Límites éticos

Esto es un **forecast probabilístico**. No es asesoramiento financiero ni una promesa de rentabilidad. El gambling tiene riesgos documentados; usar con responsabilidad.


---

## `SUPABASE_SETUP.md`

# Integración con Supabase — guía de setup

El modelo escribe sus predicciones directamente en la tabla `pronosticos`. La página web (`futpronostico_v9.html`) sigue leyendo de Supabase como hasta hoy: no se modifica el HTML.

## 0) Seguridad primero

- **Rotá la service_role key.** La compartiste en chat — pedile a Supabase una nueva (Project Settings → API → "Generate new service_role secret"). La nueva la usás solo en GitHub Secrets, **nunca** en el HTML, ni en código, ni en chat.
- **`anon key` es la que va en el HTML.** Esa es de lectura y respeta RLS. Es correcto que esté ahí.
- **`service_role` bypasea RLS.** Tratala como contraseña de admin.

## 1) SQL — una sola vez

Para que el upsert por `partido_id` funcione, en Supabase → SQL Editor:

```sql
create unique index if not exists pronosticos_partido_id_uq
  on pronosticos (partido_id);
```

## 2) GitHub Secrets

En el repo del modelo (Settings → Secrets and variables → Actions → New repository secret):

| Nombre | Valor |
|---|---|
| `SUPABASE_URL` | `https://dyeouwqtebrvioesrbcf.supabase.co` |
| `SUPABASE_SERVICE_KEY` | la **nueva** service_role key que vas a generar |
| `FOOTBALL_DATA_TOKEN` | tu token de football-data.org |
| `THE_ODDS_API_KEY` | tu key de the-odds-api.com (opcional) |

## 3) Cómo se mapean los datos

### Equipos
El alias está hardcodeado en `src/supabase_writer.py::TEAM_ALIAS`. Para tus 12 equipos:

| Nombre football-data.org | Supabase equipos.id |
|---|---|
| Real Madrid CF | 1 |
| FC Barcelona | 2 |
| Club Atlético de Madrid | 3 |
| FC Bayern München | 4 |
| Borussia Dortmund | 5 |
| Arsenal FC | 6 |
| Manchester City FC | 7 |
| Liverpool FC | 8 |
| Chelsea FC | 9 |
| FC Internazionale Milano | 10 |
| AC Milan | 11 |
| Paris Saint-Germain FC | 12 |

Si querés sumar equipos, los agregás manualmente en `equipos` y agregás la línea correspondiente en `TEAM_ALIAS`.

### Probabilidades
`probabilities.home/draw/away` (0–1) → `prob_local/prob_empate/prob_visitante` (0–100, floats).

### Factores derivados
| Campo | Cómo se calcula |
|---|---|
| `factor_localidad` | 75 si hay localía real, 50 si es neutral |
| `factor_forma` | sigmoide del spread de probabilidades del modelo |
| `factor_tabla` | sigmoide de la diferencia de Elo |
| `factor_goles` | sigmoide de la diferencia de λ esperadas (Dixon-Coles) |
| `factor_h2h` | `NULL` (no lo modelamos directo) |
| `factor_bajas` | `NULL` (no tenemos data de lesiones) |
| `notas` | `"Modelo IA - DC+Elo+XGBoost - xG esperado A 1.84 - 1.42 B - d-Elo +33"` |

El HTML interpreta los factores: ≥65 favorece local, ≤40 favorece visitante.

## 4) Flujo de partidos (importante)

El writer **no crea partidos nuevos**. Solo actualiza pronósticos de partidos que ya existan en `partidos`.

Workflow:
1. Vos cargás un partido manualmente en Supabase (con `equipo_local_id`, `equipo_visitante_id`, `fecha`, `liga_id`, `estado='programado'`).
2. El cron de GitHub Actions corre cada 6h, predice, y hace upsert en `pronosticos` para los partidos que matcheen por `(equipo_local_id, equipo_visitante_id, fecha ±6h)`.
3. Tu HTML lee el resultado actualizado automáticamente.

Si querés que el modelo cree partidos automáticamente cuando aparezcan en football-data.org, decímelo y lo extendemos.

## 5) Probarlo en local

```bash
# (en C:\Users\facun\football-forecast)
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Setear variables (PowerShell)
$env:SUPABASE_URL="https://dyeouwqtebrvioesrbcf.supabase.co"
$env:SUPABASE_SERVICE_KEY="<TU_NUEVA_KEY>"
$env:FOOTBALL_DATA_TOKEN="<TU_TOKEN>"

# Backfill histórico (1 vez)
python -m src.data_ingest --backfill --since 2018-08-01

# Entrenar el modelo
python -m src.train

# Generar predicciones
python -m src.predict --horizon 14 --snapshot 24h --out data/predictions.json

# Subir a Supabase (primero dry-run para inspeccionar)
python -m src.supabase_writer --predictions data/predictions.json --dry-run

# Si está OK, sin --dry-run:
python -m src.supabase_writer --predictions data/predictions.json
```

## 6) Monitoreo

Cada corrida del workflow imprime un resumen:
```
[supabase-writer] resumen: {'total': 18, 'applied': 4, 'skipped_team': 12, 'skipped_no_partido': 2, 'errors': 0}
```

- `applied`: pronósticos escritos en Supabase.
- `skipped_team`: predicción de un equipo que no está en tu DB (no es error, es esperable con 12 equipos).
- `skipped_no_partido`: no encontré un partido en Supabase con esos equipos + fecha. Si esperabas tenerlo, revisá la columna `fecha` y los IDs.
- `errors`: problemas reales (network, schema, etc.). Si > 0, revisá los logs de Actions.
