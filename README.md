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
