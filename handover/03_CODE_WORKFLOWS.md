# FutPronostico — Workflows + Config
GitHub Actions workflows + archivos de configuracion + script PowerShell helper.

## Workflows GitHub Actions

### `.github/workflows/predict.yml`

```yaml
name: predict

on:
  schedule:
    # Cada 6 horas
    - cron: "0 */6 * * *"
    # Reentreno semanal completo: domingos 00:00 UTC
    - cron: "0 0 * * 0"
  workflow_dispatch: {}

jobs:
  predict:
    runs-on: ubuntu-latest
    permissions:
      contents: write

    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - name: Install deps
        run: pip install -r requirements.txt

      - name: Ingest matches + odds
        env:
          FOOTBALL_DATA_TOKEN: ${{ secrets.FOOTBALL_DATA_TOKEN }}
          THE_ODDS_API_KEY: ${{ secrets.THE_ODDS_API_KEY }}
        run: python -m src.data_ingest --days-ahead 14 --skip-couk

      - name: Train full pipeline XGBoost (weekly o manual)
        if: github.event.schedule == '0 0 * * 0' || github.event_name == 'workflow_dispatch'
        run: python -m src.train || echo "[train] fallo no critico - predict cae a DC fallback"

      - name: Predict (real fixtures upcoming)
        run: python -m src.predict --horizon 14 --snapshot 24h --out data/predictions.json

      - name: Sincronizar partidos proximos a Supabase
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.supabase_sync --horizon 14

      - name: Push predictions to Supabase (from-json)
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.supabase_writer --mode from-json --predictions data/predictions.json

      - name: Commit state
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/predictions.json data/elo_state.json data/dc_state.json data/matches.parquet data/models/ || true
          if ! git diff --cached --quiet; then
            git commit -m "chore: refresh predictions $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          else
            echo "no changes"
          fi

```

### `.github/workflows/backfill.yml`

```yaml
name: backfill (manual)

on:
  workflow_dispatch:
    inputs:
      since:
        description: "Fecha desde football-data.org (free tier = temp. actual)"
        required: true
        default: "2025-07-01"
      couk_seasons:
        description: "Temporadas de football-data.co.uk (anios inicio, csv)"
        required: true
        default: "2020,2021,2022,2023,2024,2025"

jobs:
  backfill:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - env:
          FOOTBALL_DATA_TOKEN: ${{ secrets.FOOTBALL_DATA_TOKEN }}
          THE_ODDS_API_KEY: ${{ secrets.THE_ODDS_API_KEY }}
        run: |
          # Borramos el parquet viejo para evitar match_ids huerfanos con el id-format anterior.
          rm -f data/matches.parquet
          python -m src.data_ingest --backfill \
            --since ${{ inputs.since }} \
            --couk-seasons ${{ inputs.couk_seasons }}
      - run: python -m src.train || echo "[train] fallo no critico - predict cae a fallback"
      - run: python -m src.predict --horizon 14 --snapshot 24h --out data/predictions.json
      - env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.supabase_sync --horizon 14
      - env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.supabase_writer --mode from-json --predictions data/predictions.json
      - run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add -A data/
          git commit -m "chore: backfill since ${{ inputs.since }}" || echo "nothing"
          git push || true

```

### `.github/workflows/sync.yml`

```yaml
name: sync (manual)

# Workflow rapido (~3 min) para refrescar partidos proximos y escudos en Supabase
# sin re-entrenar el modelo ni regenerar predicciones.
#
# Util cuando:
#  - Agregaste un mapeo nuevo en team_normalize.py y queres refrescar equipos
#  - Cambiaste algo en supabase_sync.py
#  - Queres traer escudos nuevos de fixtures recien aparecidos

on:
  workflow_dispatch:
    inputs:
      horizon:
        description: "Dias hacia adelante para sincronizar partidos"
        required: true
        default: "14"

jobs:
  sync:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Ingest fixtures proximos (con escudos)
        env:
          FOOTBALL_DATA_TOKEN: ${{ secrets.FOOTBALL_DATA_TOKEN }}
        run: python -m src.data_ingest --days-ahead ${{ inputs.horizon }} --skip-couk

      - name: Sincronizar a Supabase
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.supabase_sync --horizon ${{ inputs.horizon }}

      - name: Commit parquet actualizado
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/matches.parquet || true
          if ! git diff --cached --quiet; then
            git commit -m "chore: sync $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          else
            echo "no changes"
          fi

```

### `.github/workflows/squads.yml`

```yaml
name: squads (semanal + manual)

# Sincroniza plantillas (jugadores) y metadata de equipos (fundacion, estadio)
# desde football-data.org. Las plantillas cambian poco: corremos esto una vez
# por semana (lunes a las 06:00 UTC), o manualmente cuando hace falta.

on:
  schedule:
    - cron: "0 6 * * 1"  # Lunes 06:00 UTC
  workflow_dispatch: {}

jobs:
  squads:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Sincronizar plantillas + metadata
        env:
          FOOTBALL_DATA_TOKEN: ${{ secrets.FOOTBALL_DATA_TOKEN }}
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.ingest_squads

```

### `.github/workflows/fbref-stats.yml`

```yaml
name: player-stats (semanal + manual)

# Ingest de estadisticas de jugadores desde Understat (via soccerdata).
# Understat funciona desde GH Actions (fbref nos bloqueo, ese ya esta deprecado).
#
# Corre miercoles a las 08:00 UTC (despues de squads del lunes y predict del martes,
# asi cuando llegan los stats los plantelles y partidos ya estan frescos).

on:
  schedule:
    - cron: "0 8 * * 3"  # Miercoles 08:00 UTC
  workflow_dispatch:
    inputs:
      season:
        description: "Temporada (ej: 2024-25 o 2024)"
        required: true
        default: "2024-25"
      temporada_label:
        description: "Etiqueta en Supabase (default: 'YYYY/YY')"
        required: false
        default: ""

jobs:
  fbref:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Sincronizar stats de jugadores desde fbref
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: |
          SEASON="${{ inputs.season || '2024-25' }}"
          LABEL="${{ inputs.temporada_label }}"
          if [ -z "$LABEL" ]; then
            python -m src.ingest_fbref_stats --season "$SEASON"
          else
            python -m src.ingest_fbref_stats --season "$SEASON" --temporada-label "$LABEL"
          fi

      - name: Actualizar rating de jugadores
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.player_ratings --prefer-eafc

      - name: Refrescar team_ratings.json
        env:
          SUPABASE_URL: ${{ secrets.SUPABASE_URL }}
          SUPABASE_SERVICE_KEY: ${{ secrets.SUPABASE_SERVICE_KEY }}
        run: python -m src.team_ratings

      - name: Refrescar team_xg.parquet (xG por partido para DC)
        run: python -m src.ingest_xg --seasons 2024,2023,2022,2021,2020

      - name: Commit team_ratings.json + team_xg.parquet
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add data/team_ratings.json data/team_xg.parquet || true
          if ! git diff --cached --quiet; then
            git commit -m "chore: refresh team_ratings + team_xg $(date -u +%Y-%m-%dT%H:%M:%SZ)"
            git push
          else
            echo "no changes"
          fi

```

### `.github/workflows/evaluate.yml`

```yaml
name: evaluate (manual)

on:
  workflow_dispatch:
    inputs:
      test_days:
        description: "Dias finales del dataset que usar como TEST"
        required: true
        default: "30"

jobs:
  evaluate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: pip
      - run: pip install -r requirements.txt
      - name: Evaluacion del modelo (entrena calibrador honesto internamente)
        run: python -m src.evaluate --test-days ${{ inputs.test_days }}

```

### `.github/workflows/deploy-hostinger.yml`

```yaml
name: deploy-hostinger

# Auto-deploy de web/ a Hostinger via FTP.
#
# Se dispara cuando:
#  - Push a main que toque archivos en web/
#  - Manual (workflow_dispatch)
#
# Asi los commits del cron (que solo cambian data/) NO disparan deploy,
# solo cambios reales del HTML/CSS/JS.

on:
  push:
    branches: [main]
    paths:
      - 'web/**'
  workflow_dispatch: {}

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Sync web/ a Hostinger via FTP
        uses: SamKirkland/FTP-Deploy-Action@v4.3.5
        with:
          server: ${{ secrets.FTP_HOST }}
          username: ${{ secrets.FTP_USERNAME }}
          password: ${{ secrets.FTP_PASSWORD }}
          local-dir: ./web/
          # En Hostinger el HTML del sitio queda en /nodejs/ segun lo que vimos
          server-dir: ./nodejs/
          protocol: ftp
          port: 21
          # No borra archivos extra en el servidor, solo sube los nuestros.
          dangerous-clean-slate: false
          # Excluye basura que no debe ir al hosting.
          exclude: |
            **/.git*
            **/.git*/**
            **/node_modules/**
            **/.DS_Store

      - name: Resumen
        run: |
          echo "Deploy completado a https://futversus.com/"
          echo "Archivos en web/ subidos a /nodejs/ del FTP."

```

## Configuracion del repo

### `requirements.txt`

```txt
pandas>=2.1
numpy>=1.26
scipy>=1.11
scikit-learn>=1.4
xgboost>=2.0
pyarrow>=14.0
requests>=2.31
python-dotenv>=1.0
tenacity>=8.2
pydantic>=2.5
soccerdata>=1.7
rapidfuzz>=3.5

```

### `netlify.toml`

```toml
[build]
  publish = "web"
  command = ""
  # Skip deploy si el commit no toca archivos de web/ (lee Netlify automaticamente).
  # Asi los commits del cron de GitHub Actions que solo actualizan data/ no gastan
  # deploys de Netlify.
  ignore = "git diff --quiet $CACHED_COMMIT_REF $COMMIT_REF -- web/"

[[headers]]
  for = "/predictions.json"
  [headers.values]
    Cache-Control = "public, max-age=300"

[[headers]]
  for = "/*"
  [headers.values]
    X-Content-Type-Options = "nosniff"
    Referrer-Policy = "strict-origin-when-cross-origin"

```

### `gp.ps1`

```powershell
# Atajo para commit + push del proyecto FUTVS
# Uso:
#   .\gp.ps1 "mensaje del commit"
#
# Hace en orden: pull --rebase, add ., commit, push
# Si algun paso falla, frena y muestra el error.

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Mensaje
)

$ErrorActionPreference = "Stop"
Set-Location -Path "C:\Users\facun\football-forecast"

Write-Host ""
Write-Host "==> git pull --rebase --autostash" -ForegroundColor Cyan
git pull --rebase --autostash
if ($LASTEXITCODE -ne 0) { Write-Host "Pull fallo." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "==> git add ." -ForegroundColor Cyan
git add .

Write-Host ""
Write-Host "==> git commit -m `"$Mensaje`"" -ForegroundColor Cyan
git commit -m $Mensaje
if ($LASTEXITCODE -ne 0) {
    Write-Host "Nada que commitear o error en commit." -ForegroundColor Yellow
    exit 0
}

Write-Host ""
Write-Host "==> git push" -ForegroundColor Cyan
git push
if ($LASTEXITCODE -ne 0) { Write-Host "Push fallo." -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Listo. Cambios pusheados al repo." -ForegroundColor Green

```

### `.env.example`

```bash
# Copiar a .env y completar.
# https://www.football-data.org/  (registro gratuito, free tier 10 req/min, incluye UCL/UEL/UECL + ligas top)
FOOTBALL_DATA_TOKEN=

# https://the-odds-api.com/ (free tier 500 req/mes)
THE_ODDS_API_KEY=

# Supabase — proyecto donde escribimos `pronosticos`.
# La SERVICE key bypasea RLS, NUNCA commitearla. Solo va en GitHub Secrets.
SUPABASE_URL=https://dyeouwqtebrvioesrbcf.supabase.co
SUPABASE_SERVICE_KEY=

```

### `.gitignore`

```gitignore
.venv/
__pycache__/
*.pyc
.env
.pytest_cache/
.ipynb_checkpoints/
.DS_Store
.idea/
.vscode/
downloaded_files/
data/eafc26_ratings_cache.json
# Mantenemos data/ commiteable porque la consume Netlify.
# Si tu dataset crece mucho, considerar Git LFS o mover predictions.json a un bucket.

```
