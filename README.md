# FutVersus — fútbol internacional

Plataforma de análisis y pronóstico probabilístico para fútbol internacional. Hoy el foco operativo está en el Mundial 2026, pero la base del producto sigue preparada para competiciones internacionales y ligas después del Mundial.

Implementa la receta del documento de referencia:
**Dixon-Coles + Elo + XGBoost multiclase calibrado**, con backtesting temporal (rolling-origin), evaluación por log loss / Brier / curvas de calibración, y odds de mercado como feature.

## Arquitectura

```
┌──────────────────────┐
│ GitHub Actions cron  │
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
│      FutVersus       │
│  Hostinger + web/    │
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
├── web/                 # Frontend publicado en Hostinger
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

## Deploy en Hostinger

El sitio público vive en `web/` y se despliega en Hostinger desde GitHub Actions.

Hay dos flujos históricos de Hostinger en el repo: deploy directo por FTP y publicación a rama `hostinger`. Antes de simplificar uno de los dos, confirmar cuál está usando producción.

Ver **HOSTINGER_DEPLOY.md** y **HANDOFF.md** para el estado operativo actual.

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
