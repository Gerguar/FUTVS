"""
Genera el paquete de handover para subir a otra sesion de Claude.

Produce en handover/:
  01_HANDOVER.md          - documento narrativo principal
  02_CODE_PYTHON.md       - todos los src/*.py inline con code fences
  03_CODE_WORKFLOWS.md    - todos los .github/workflows/*.yml + netlify.toml + gp.ps1
  04_CODE_WEB.md          - web/index.html (HTML del frontend, recortado/notado)
  05_DATA_SUPABASE.md     - schema + queries de ejemplo
  06_DOCS.md              - README + SUPABASE_SETUP del proyecto
  README_HANDOVER.md      - indice y orden recomendado de upload

Uso:
    python handover/generate_handover.py
"""
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent


def write(filename: str, content: str) -> None:
    p = OUT / filename
    p.write_text(content, encoding="utf-8")
    print(f"  + {p.relative_to(ROOT)}  ({len(content):,} chars)")


def read_file_safe(rel_path: str) -> str:
    p = ROOT / rel_path
    if not p.exists():
        return f"# (archivo no encontrado: {rel_path})"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"# (error leyendo {rel_path}: {e})"


# ----- 01 HANDOVER -----
def gen_handover() -> str:
    return """# FutPronostico — Documento de traspaso

> Generado: """ + datetime.now().strftime("%Y-%m-%d %H:%M") + """

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
│   ├── ingest_fbref_stats.py ← player stats via Understat (archivo conserva el nombre fbref)
│   ├── player_ratings.py     ← actualiza jugadores.rating (EA FC 26 CSV + modelo derivado fallback)
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
    ├── predict.yml           ← cron 6h + retrain semanal (domingos 00:00 UTC)
    ├── backfill.yml          ← manual (re-baja todo el historico)
    ├── sync.yml              ← manual rapido (solo sync equipos/partidos/escudos)
    ├── squads.yml            ← cron semanal lunes 06:00 UTC (squads + metadata)
    ├── fbref-stats.yml       ← cron semanal miercoles 08:00 UTC: Understat + player ratings (EAFC)
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
| `jugadores` | ~3.700 | Plantel real de los 132 equipos. nombre, posicion (POR/DEF/MED/DEL), nacionalidad, fecha_nac. **rating cargado desde EA FC 26 OVR** (89% match) + modelo derivado para el resto. |
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

fbref-stats.yml (cron miercoles 08:00 UTC + dispatch manual)
  1. ingest_fbref_stats.py
     - Player stats por jugador (goles, asist, partidos, minutos)
     - Via Understat (soccerdata)
     - Dedupe payloads para evitar HTTP 500
  2. player_ratings.py --prefer-eafc
     - Calcula rating de cada jugador
     - Fuente primaria: EA FC 26 OVR (CSV publico desde EAFC26-DataHub)
     - Fallback: modelo derivado de stats (minutos, goles, asistencias, edad)
     - Bulk PATCH a jugadores.rating
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
- **resueltos:** HTTP 500 en upserts (dedupe pre-upsert), ratings 70 (EA FC 26 OVR)
- mercado_historico y minutos_por_anio vacios (requieren Transfermarkt/fbref scraping)
- 409 jugadores (11%) siguen en rating 70 por no matchear en EA FC 26 (juveniles, reservas, transferencias recientes)

## 9. Roadmap propuesto

| Prioridad | Item | Costo | Notas |
|---|---|---|---|
| Alta | Fix bug HTTP 500 en player stats (dedupe en supabase_writer) | $0 | ~30 min de codigo |
| Alta | Activar cron semanal del player-stats una vez que el bug este fixed | $0 | 1 linea de YAML |
| Media | Agregar columna xg en estadisticas_jugador y persistirlo (Understat lo tiene) | $0 | SQL + 5 lineas |
| Media | Mejorar rating de jugador con formula derivada (edad + pos + xG) | $0 | Mejora visual |
| Baja | API-Football si queres lesiones + stats premium | $10/mes | +0.02 log loss |
| Baja | football-data Tier Two | €10/mes | Cobertura EUL/EUCL |

## 10. Comandos utiles (PowerShell desde C:\\Users\\facun\\football-forecast)

```powershell
# atajo de commit+push (incluido en el repo)
.\\gp.ps1 "mensaje del commit"

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
"""


# ----- 02 CODE_PYTHON -----
PYTHON_FILES = [
    "src/config.py",
    "src/team_normalize.py",
    "src/data_ingest.py",
    "src/ingest_couk.py",
    "src/ingest_squads.py",
    "src/ingest_fbref_stats.py",
    "src/player_ratings.py",
    "src/elo.py",
    "src/dixon_coles.py",
    "src/features.py",
    "src/xgb_model.py",
    "src/train.py",
    "src/train_dc.py",
    "src/predict.py",
    "src/evaluate.py",
    "src/backtest.py",
    "src/metrics.py",
    "src/supabase_writer.py",
    "src/supabase_sync.py",
]


def gen_code_python() -> str:
    out = ["# FutPronostico — Codigo Python (src/)\n"]
    out.append("Todos los modulos del modelo y pipeline. "
               "El paquete se importa como `src.*` desde la raiz del proyecto.\n")
    for f in PYTHON_FILES:
        out.append(f"\n---\n\n## `{f}`\n\n```python\n")
        out.append(read_file_safe(f))
        out.append("\n```\n")
    return "".join(out)


# ----- 03 CODE_WORKFLOWS -----
WORKFLOW_FILES = [
    ".github/workflows/predict.yml",
    ".github/workflows/backfill.yml",
    ".github/workflows/sync.yml",
    ".github/workflows/squads.yml",
    ".github/workflows/fbref-stats.yml",
    ".github/workflows/evaluate.yml",
]
OTHER_OPS = [
    ("requirements.txt", "txt"),
    ("netlify.toml", "toml"),
    ("gp.ps1", "powershell"),
    (".env.example", "bash"),
    (".gitignore", "gitignore"),
]


def gen_code_workflows() -> str:
    out = ["# FutPronostico — Workflows + Config\n"]
    out.append("GitHub Actions workflows + archivos de configuracion + script PowerShell helper.\n")
    out.append("\n## Workflows GitHub Actions\n")
    for f in WORKFLOW_FILES:
        out.append(f"\n### `{f}`\n\n```yaml\n")
        out.append(read_file_safe(f))
        out.append("\n```\n")
    out.append("\n## Configuracion del repo\n")
    for f, lang in OTHER_OPS:
        out.append(f"\n### `{f}`\n\n```{lang}\n")
        out.append(read_file_safe(f))
        out.append("\n```\n")
    return "".join(out)


# ----- 04 CODE_WEB -----
def gen_code_web() -> str:
    html_content = read_file_safe("web/index.html")
    out = []
    out.append("# FutPronostico — Frontend HTML\n\n")
    out.append("HTML del sitio (publicado por Netlify desde `web/index.html`).\n\n")
    out.append("- Vanilla JS (sin build), Chart.js como dependencia CDN.\n")
    out.append("- Lee live de Supabase usando la **anon key** hardcoded.\n")
    out.append("- Muestra los partidos `estado=programado` y sus pronosticos.\n")
    out.append("- Tiene una pagina de detalle por partido (plantelles, stats, forma).\n\n")
    out.append("Tamano: ~93 KB.\n\n")
    out.append(f"\n## `web/index.html`\n\n```html\n{html_content}\n```\n")
    return "".join(out)


# ----- 05 DATA_SUPABASE -----
def gen_data_supabase() -> str:
    return """# FutPronostico — Schema y queries de ejemplo de Supabase

## Conexion

```python
import urllib.request, json
SB = 'https://dyeouwqtebrvioesrbcf.supabase.co'
SERVICE_KEY = '<tomar de GH Secrets>'  # service_role, bypasea RLS

def get(path: str):
    req = urllib.request.Request(
        f'{SB}/rest/v1/{path}',
        headers={'apikey': SERVICE_KEY, 'Authorization': f'Bearer {SERVICE_KEY}'}
    )
    return json.loads(urllib.request.urlopen(req, timeout=20).read())
```

## Tablas (schema observado via REST)

### ligas
```
id          int (PK)
nombre      text
pais        text
logo_url    text
created_at  timestamp
```

### equipos
```
id            int (PK)
nombre        text
abreviacion   text
liga_id       int (FK -> ligas.id)
pais          text
escudo_url    text
color_prim    text
color_sec     text
fundacion     int
estadio       text
created_at    timestamp
```

### partidos
```
id                    int (PK)
liga_id               int (FK)
equipo_local_id       int (FK -> equipos.id)
equipo_visitante_id   int (FK -> equipos.id)
fecha                 timestamp
temporada             text     (formato '2024/25')
goles_local           int      (NULL si no jugado)
goles_visitante       int      (NULL si no jugado)
estado                text     ('programado' | 'finalizado')
created_at            timestamp
```

### pronosticos
```
id                  int (PK)
partido_id          int (UNIQUE, FK -> partidos.id)
prob_local          float    (0-100)
prob_empate         float    (0-100)
prob_visitante      float    (0-100)
factor_localidad    float    (0-100)
factor_forma        float    (0-100)
factor_h2h          float    (puede ser NULL)
factor_tabla        float    (0-100)
factor_bajas        float    (puede ser NULL)
factor_goles        float    (0-100)
notas               text     ('Modelo IA - DC+Elo+XGBoost - ...')
created_at          timestamp
```

### forma_reciente (VIEW)
Calcula automaticamente desde partidos donde estado='finalizado'.
```
equipo_id   int
forma       text[]   (ej: ['W','W','D','L','W'])
```

### jugadores
```
id              int (PK)
nombre          text
equipo_id       int (FK -> equipos.id)
posicion        text   ('POR' | 'DEF' | 'MED' | 'DEL')
nacionalidad    text
fecha_nac       date
rating          int       (default 70, sin fuente real todavia)
valor_mercado   float     (NULL, requiere Transfermarkt scraping)
notas           text
created_at      timestamp
```

### estadisticas_jugador
```
id                 int (PK)
jugador_id         int (FK -> jugadores.id, ON DELETE CASCADE)
temporada          text
equipo_id          int (FK -> equipos.id)
partidos           int
minutos            int
goles              int
asistencias        int
amarillas          int
rojas              int
paradas_pct        text
pases_pct          text
duelos_ganados     text
intercep_p90       float
created_at         timestamp
```
UNIQUE: (jugador_id, temporada)

### mercado_historico (VACIA)
```
id           int (PK)
jugador_id   int (FK)
anio         int
valor        float    (en millones EUR)
club         text
```

### minutos_por_anio (VACIA)
```
id           int (PK)
jugador_id   int (FK)
anio         int
minutos      int
```

## Queries que usa el HTML

```javascript
// Lista de partidos programados con todo el contexto
sb('partidos?select=id,fecha,'
   + 'equipo_local:equipo_local_id(id,nombre,abreviacion,escudo_url,color_prim,color_sec),'
   + 'equipo_visitante:equipo_visitante_id(id,nombre,abreviacion,escudo_url,color_prim,color_sec),'
   + 'liga:liga_id(nombre),'
   + 'pronosticos(prob_local,prob_empate,prob_visitante,'
   + 'factor_localidad,factor_forma,factor_h2h,factor_tabla,factor_bajas,factor_goles,notas)'
   + '&estado=eq.programado&order=fecha')

// Plantel de un equipo
sb(`jugadores?select=*,estadisticas_jugador(*),mercado_historico(*),minutos_por_anio(*)`
   + `&equipo_id=eq.${equipoId}&order=rating.desc`)

// Forma reciente
sb(`forma_reciente?equipo_id=in.(${m.home.id},${m.away.id})`)
```

## Queries utiles para debug

```python
# Cuantos partidos programados y finalizados
get('partidos?select=estado&estado=eq.programado')
get('partidos?select=estado&estado=eq.finalizado')

# Estado de pronosticos
get('pronosticos?select=partido_id,prob_local,prob_empate,prob_visitante,notas&order=created_at.desc&limit=10')

# Equipos sin escudo (deberian ser 0)
get('equipos?select=id,nombre,escudo_url&escudo_url=is.null')

# Top 10 jugadores con mas goles
get('estadisticas_jugador?select=jugador_id,goles,jugadores(nombre,equipo_id)&order=goles.desc&limit=10')
```
"""


# ----- 06 DOCS -----
def gen_docs() -> str:
    out = ["# FutPronostico — Documentacion del proyecto\n\n"]
    out.append("## `README.md`\n\n")
    out.append(read_file_safe("README.md"))
    out.append("\n\n---\n\n## `SUPABASE_SETUP.md`\n\n")
    out.append(read_file_safe("SUPABASE_SETUP.md"))
    return "".join(out)


# ----- INDICE -----
def gen_readme_handover() -> str:
    return """# README del paquete de Handover

Este folder contiene todo lo necesario para que una nueva sesion de Claude
(o un colaborador nuevo) pueda agarrar el proyecto FutPronostico sin perderse.

## Archivos en orden de upload

1. **`01_HANDOVER.md`** — Documento narrativo principal. Visi[o]n general, decisiones,
   cuentas, schema, roadmap.
2. **`02_CODE_PYTHON.md`** — Codigo Python completo (18 modulos de `src/`).
3. **`03_CODE_WORKFLOWS.md`** — Workflows YAML, requirements, configs.
4. **`04_CODE_WEB.md`** — HTML del frontend (~93 KB).
5. **`05_DATA_SUPABASE.md`** — Schema de Supabase + queries de ejemplo.
6. **`06_DOCS.md`** — README + SUPABASE_SETUP del proyecto.

## Como usarlos

Abri nueva conversacion en Claude, subi los 6 archivos arriba (de a uno o en grupo
si tu cliente lo permite), y arranca con:

> Soy [usuario]. Te paso el contexto completo del proyecto FutPronostico via los
> archivos adjuntos. Empezamos desde aca. Mi pendiente inmediato es: ...

Claude va a tener todo el contexto.

## Tamanos aproximados

(Generados automaticamente por `generate_handover.py`)
"""


def main() -> None:
    print("Generando paquete de handover en handover/ ...")
    files = [
        ("01_HANDOVER.md", gen_handover()),
        ("02_CODE_PYTHON.md", gen_code_python()),
        ("03_CODE_WORKFLOWS.md", gen_code_workflows()),
        ("04_CODE_WEB.md", gen_code_web()),
        ("05_DATA_SUPABASE.md", gen_data_supabase()),
        ("06_DOCS.md", gen_docs()),
        ("README_HANDOVER.md", gen_readme_handover()),
    ]
    for name, content in files:
        write(name, content)
    print("\nListo. Subi los 6 primeros archivos a Claude.")


if __name__ == "__main__":
    main()
