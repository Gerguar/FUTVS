# FutPronostico — Schema y queries de ejemplo de Supabase

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
