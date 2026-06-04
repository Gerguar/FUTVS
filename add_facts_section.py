#!/usr/bin/env python3
"""
add_facts_section.py — Reemplaza la sección CTA del home por datos históricos rotativos.

Uso:
    python add_facts_section.py
    python add_facts_section.py --html web/index.html
"""

import argparse
from pathlib import Path

CSS_FACTS = r"""
/* ── FACTS SECTION ─────────────────────────── */
.facts-section{position:relative;z-index:1;padding:2.5rem 1rem 2rem;text-align:center}
.facts-eyebrow{font-family:'JetBrains Mono',monospace;font-size:.6rem;letter-spacing:2.5px;color:var(--green);text-transform:uppercase;margin-bottom:1.2rem;font-weight:700}
.fact-card{max-width:720px;margin:0 auto;background:var(--surface);border:1px solid var(--border);border-radius:16px;padding:1.8rem 2rem;position:relative;overflow:hidden;cursor:pointer;transition:border-color .2s}
.fact-card:hover{border-color:rgba(34,197,94,.35)}
.fact-card::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--green),transparent)}
.fact-emoji{font-size:2rem;margin-bottom:.7rem;display:block;line-height:1}
.fact-text{font-size:1.05rem;font-weight:700;color:#fff;line-height:1.55;margin-bottom:.9rem}
.fact-text em{color:var(--green);font-style:normal}
.fact-meta{font-family:'JetBrains Mono',monospace;font-size:.6rem;color:var(--faint);letter-spacing:1.5px;text-transform:uppercase}
.fact-nav{display:flex;align-items:center;justify-content:center;gap:.6rem;margin-top:1rem}
.fact-dot{width:6px;height:6px;border-radius:50%;background:var(--border2);cursor:pointer;transition:background .2s}
.fact-dot.active{background:var(--green)}
.fact-hint{font-family:'JetBrains Mono',monospace;font-size:.58rem;color:var(--faint);margin-top:.8rem;letter-spacing:1px}
@media(max-width:600px){.fact-card{padding:1.4rem 1.2rem}.fact-text{font-size:.95rem}}
/* ── FIN FACTS CSS ── */
"""

HTML_FACTS = """
<!-- FACTS SECTION -->
<div class="facts-section">
  <div class="facts-eyebrow">&#128200; Dato hist&#243;rico</div>
  <div class="fact-card" onclick="nextFact()" title="Click para ver otro dato">
    <span class="fact-emoji" id="fact-emoji">&#9917;</span>
    <div class="fact-text" id="fact-text">Cargando...</div>
    <div class="fact-meta" id="fact-meta"></div>
  </div>
  <div class="fact-nav" id="fact-nav"></div>
  <div class="fact-hint">&#128073; Click para ver otro dato</div>
</div>
<!-- /FACTS SECTION -->"""

JS_FACTS = r"""
// ── FACTS SECTION ──────────────────────────────────────────────
const FACTS = [
  { e:'⚽', t:'Messi registró más asistencias en <em>2011</em> que muchos mediocampistas de élite durante toda su carrera.', m:'Lionel Messi · 2011' },
  { e:'🔥', t:'<em>Haaland</em> necesitó menos partidos que Cristiano para alcanzar los 100 goles en ligas europeas.', m:'Comparativa histórica' },
  { e:'🏆', t:'<em>River</em> ganó más títulos locales, pero Boca tiene más Copas Libertadores.', m:'Superclásico · Historia' },
  { e:'📈', t:'En la temporada <em>2011/12</em>, Messi participó directamente en 105 goles entre Liga y Champions.', m:'Lionel Messi · 2011/12' },
  { e:'🎯', t:'<em>Ronaldo</em> es el máximo goleador de la historia de la Champions League con más de 140 goles.', m:'Champions League · All-time' },
  { e:'🧤', t:'<em>Gianluigi Buffon</em> mantuvo su arco invicto por 974 minutos consecutivos en Serie A en 2015/16.', m:'Gianluigi Buffon · 2015/16' },
  { e:'🏅', t:'<em>Messi</em> es el único jugador en ganar el Balón de Oro ocho veces en la historia.', m:'Balón de Oro · All-time' },
  { e:'⚡', t:'<em>Mbappe</em> se convirtió en el jugador más joven en anotar en una final del Mundial a los 19 años.', m:'Kylian Mbappé · 2018' },
  { e:'📊', t:'El <em>Barcelona</em> de Guardiola (2011) ganó 14 de los 17 títulos posibles en dos temporadas.', m:'FC Barcelona · 2009-2011' },
  { e:'🌍', t:'<em>Brasil</em> es el único país en participar en todas las ediciones de la Copa del Mundo (22 torneos).', m:'Brasil · FIFA World Cup' },
  { e:'🔴', t:'El <em>Liverpool</em> completó la remontada más épica de la Champions en 2019, eliminando al Barcelona 4-0 en Anfield.', m:'Liverpool FC · 2019' },
  { e:'💥', t:'<em>Cristiano</em> anotó 17 hat-tricks en la Liga española, más que ningún otro jugador extranjero.', m:'Cristiano Ronaldo · La Liga' },
  { e:'🏟️', t:'El <em>Real Madrid</em> ganó 5 Champions League consecutivas entre 1956 y 1960.', m:'Real Madrid · 1956-1960' },
  { e:'🎖️', t:'<em>Messi</em> es el máximo goleador de la historia de La Liga con más de 474 goles.', m:'Lionel Messi · La Liga' },
  { e:'🥇', t:'<em>Pelé</em> es el único jugador en ganar tres Copas del Mundo (1958, 1962, 1970).', m:'Pelé · FIFA World Cup' },
  { e:'📉', t:'El <em>Manchester City</em> de Guardiola (2022/23) ganó el triplete con 115 puntos en la Premier League.', m:'Manchester City · 2022/23' },
  { e:'⚽', t:'<em>Lewandowski</em> anotó 5 goles en 9 minutos contra el Wolfsburg en 2015, récord de la Bundesliga.', m:'Robert Lewandowski · 2015' },
  { e:'🔥', t:'<em>Xavi Hernández</em> completó más de 91% de sus pases durante toda su carrera en el Barcelona.', m:'Xavi Hernández · FC Barcelona' },
  { e:'🧠', t:'<em>Iniesta</em> anotó el gol que le dio a España su primera Copa del Mundo en el minuto 116 de la final.', m:'Andrés Iniesta · 2010' },
  { e:'🏆', t:'La <em>Selección Argentina</em> no perdió ningún partido en las eliminatorias de Qatar 2022.', m:'Argentina · Eliminatorias 2022' },
  { e:'💫', t:'<em>Zidane</em> anotó uno de los mejores goles de una final de Champions con una volea de zurda en 2002.', m:'Zinedine Zidane · 2002' },
  { e:'📊', t:'<em>Neymar</em> es el máximo goleador histórico de la Selección de Brasil con más de 79 goles.', m:'Neymar Jr · Brasil' },
  { e:'🎯', t:'<em>Van Dijk</em> fue el primer defensor en ganar el premio al Mejor Jugador de la UEFA en 2019.', m:'Virgil van Dijk · 2019' },
  { e:'⚡', t:'El <em>Bayern Munich</em> de 2019/20 ganó la Champions sin perder un solo partido en el torneo.', m:'Bayern Munich · 2019/20' },
  { e:'🌟', t:'<em>Modric</em> fue el primer jugador en 10 años en romper el duopolio Messi-Ronaldo del Balón de Oro (2018).', m:'Luka Modric · 2018' },
  { e:'⚽', t:'<em>Ibrahimovic</em> anotó con 41 años en la Serie A, siendo uno de los goleadores más longevos del fútbol de élite.', m:'Zlatan Ibrahimovic · AC Milan' },
  { e:'🏅', t:'<em>Boca Juniors</em> es el equipo argentino con más títulos internacionales: 6 Libertadores y 3 Intercontinentales.', m:'Boca Juniors · Historia' },
  { e:'🔴', t:'<em>River Plate</em> ganó la Copa Libertadores 2018 en el Santiago Bernabéu, un hecho sin precedentes en la historia.', m:'River Plate · 2018' },
  { e:'📈', t:'<em>Messi</em> anotó 91 goles en el año 2012, un récord Guinness que sigue vigente.', m:'Lionel Messi · 2012' },
  { e:'💥', t:'<em>Cristiano</em> es el único jugador en anotar en 5 Copas del Mundo diferentes (2006-2022).', m:'Cristiano Ronaldo · FIFA World Cup' },
  { e:'🧤', t:'<em>Casillas</em> fue portero titular en tres Eurocopas y un Mundial con la Selección de España.', m:'Iker Casillas · España' },
  { e:'🏆', t:'La <em>España</em> de 2008-2012 ganó tres torneos internacionales consecutivos: Euro, Mundial y Euro.', m:'España · 2008-2012' },
  { e:'🎖️', t:'<em>Suárez</em> anotó 25 goles en la temporada 2015/16 del Barcelona y ganó la Bota de Oro.', m:'Luis Suárez · 2015/16' },
  { e:'📉', t:'El <em>Atletico de Madrid</em> ganó La Liga 2013/14 sin ser favorito, interrumpiendo 10 años de dominio Real-Barça.', m:'Atlético de Madrid · 2013/14' },
  { e:'⚡', t:'<em>De Bruyne</em> registró 20 asistencias en una sola temporada de Premier League, un récord histórico.', m:'Kevin De Bruyne · 2019/20' },
  { e:'🌍', t:'<em>Alemania</em> es el país europeo con más finales de Copa del Mundo jugadas (4 ganadas, 4 perdidas).', m:'Alemania · FIFA World Cup' },
  { e:'⚽', t:'<em>Ronaldinho</em> ganó el Balón de Oro en 2005 con uno de los fútboles más creativos que se recuerdan.', m:'Ronaldinho · 2005' },
  { e:'🔥', t:'El <em>Chelsea</em> de Abramovich ganó la Champions 2012 como visitante en el estadio del Bayern Munich.', m:'Chelsea FC · 2012' },
  { e:'🏟️', t:'<em>Anfield</em> es el estadio con mayor racha invicta en liga europea: más de 50 partidos sin perder (2019-2021).', m:'Liverpool FC · Anfield' },
  { e:'💫', t:'<em>Messi</em> ganó su primera Copa del Mundo en Qatar 2022 a los 35 años, completando su leyenda.', m:'Lionel Messi · Qatar 2022' },
  { e:'📊', t:'<em>Thiago Alcantara</em> completó más del 93% de sus pases en la Champions 2019/20 con el Bayern.', m:'Thiago Alcântara · 2019/20' },
  { e:'🥇', t:'<em>Maradona</em> anotó el "Gol del Siglo" y el "Gol de la Mano de Dios" en el mismo partido (1986).', m:'Diego Maradona · México 1986' },
  { e:'🏆', t:'<em>San Lorenzo</em> ganó la Copa Libertadores 2014, el único título internacional del club argentino.', m:'San Lorenzo · 2014' },
  { e:'🎯', t:'<em>Salah</em> anotó 32 goles en su primera temporada en la Premier League (2017/18), récord histórico.', m:'Mohamed Salah · 2017/18' },
  { e:'⚡', t:'El <em>PSG</em> pagó 222 millones de euros por Neymar en 2017, el traspaso más caro de la historia.', m:'Neymar Jr · PSG · 2017' },
  { e:'🌟', t:'<em>Riquelme</em> es considerado el último "10 clásico" del fútbol argentino y uno de los mejores de su generación.', m:'Juan Román Riquelme · Argentina' },
  { e:'⚽', t:'<em>Lewandowski</em> superó el récord de Müller de goles en una temporada de Bundesliga con 41 en 2020/21.', m:'Robert Lewandowski · 2020/21' },
  { e:'🔴', t:'<em>Gerrard</em> nunca ganó la Premier League con el Liverpool a pesar de jugar 17 temporadas en el club.', m:'Steven Gerrard · Liverpool FC' },
  { e:'📈', t:'<em>Benzema</em> ganó el Balón de Oro 2022 a los 34 años, la edad más avanzada en conseguirlo en décadas.', m:'Karim Benzema · 2022' },
  { e:'💥', t:'El <em>Inter de Milan</em> de Mourinho ganó el triplete en 2010: Liga, Copa y Champions.', m:'Inter de Milán · 2009/10' },
  { e:'🧠', t:'<em>Pirlo</em> jugó de mediocampista pero anotó más de 50 goles en Serie A a lo largo de su carrera.', m:'Andrea Pirlo · Serie A' },
  { e:'🏅', t:'<em>Neuer</em> revolucionó el rol del portero moderno, siendo considerado el mejor en su posición de la última década.', m:'Manuel Neuer · Bayern Munich' },
  { e:'🔥', t:'El <em>Dortmund</em> de Klopp (2011/12) ganó la Bundesliga con el equipo más joven de Europa.', m:'Borussia Dortmund · 2011/12' },
  { e:'🏆', t:'<em>Independiente</em> es el club con más Copas Libertadores en la historia: 7 títulos entre 1964 y 1984.', m:'CA Independiente · Historia' },
  { e:'🎖️', t:'<em>Xavi</em> y <em>Iniesta</em> forman el mejor centro del campo de la historia según múltiples analistas.', m:'España · FC Barcelona' },
  { e:'📉', t:'El <em>Leicester City</em> ganó la Premier League 2015/16 con cuotas de 5000-1 antes de la temporada.', m:'Leicester City · 2015/16' },
  { e:'⚡', t:'<em>Messi</em> debutó en el Barcelona con 17 años y fue expulsado en su primer partido oficial por Liga.', m:'Lionel Messi · 2004' },
  { e:'🌍', t:'<em>Francia</em> ganó el Mundial 2018 con la selección más joven en la historia del torneo.', m:'Francia · Rusia 2018' },
  { e:'⚽', t:'<em>Cruyff</em> inventó la "Vuelta de Cruyff" en el Mundial 1974, uno de los regates más imitados de la historia.', m:'Johan Cruyff · 1974' },
  { e:'🔥', t:'<em>Müller</em> es el máximo goleador histórico del Bayern Munich con más de 570 goles en todas las competiciones.', m:'Thomas Müller / Gerd Müller · Bayern' },
  { e:'🏟️', t:'El <em>Camp Nou</em> tiene capacidad para más de 99.000 espectadores, siendo el estadio más grande de Europa.', m:'FC Barcelona · Camp Nou' },
  { e:'💫', t:'<em>Bale</em> anotó una de las mejores chilenas de la historia en la final de la Champions 2018 contra el Liverpool.', m:'Gareth Bale · 2018' },
  { e:'📊', t:'<em>Busquets</em> es el jugador con más títulos en la historia del FC Barcelona con más de 30 trofeos.', m:'Sergio Busquets · FC Barcelona' },
  { e:'🥇', t:'<em>Di Stéfano</em> es el único jugador en anotar en cinco finales consecutivas de Copa de Europa (1956-1960).', m:'Alfredo Di Stéfano · Real Madrid' },
  { e:'🏆', t:'El <em>Real Madrid</em> ganó 14 Champions League, más que cualquier otro club en la historia.', m:'Real Madrid · Champions League' },
  { e:'🎯', t:'<em>Lamine Yamal</em> se convirtió en el jugador más joven en anotar en una Eurocopa con apenas 17 años.', m:'Lamine Yamal · Euro 2024' },
  { e:'⚡', t:'<em>Vinicius Jr</em> fue el primer brasileño en ganar el Balón de Oro desde Ronaldinho en 2005.', m:'Vinicius Jr · 2024' },
  { e:'🌟', t:'<em>Ter Stegen</em> fue el portero menos goleado de La Liga en dos temporadas consecutivas (2018-2020).', m:'Marc-André ter Stegen · La Liga' },
  { e:'⚽', t:'<em>Ronaldo Nazário</em> anotó 2 goles en la final del Mundial 2002 con una rodilla casi destruida.', m:'Ronaldo Nazário · 2002' },
  { e:'🔴', t:'El <em>AC Milan</em> ganó 7 Champions League, siendo el segundo club más exitoso en la historia del torneo.', m:'AC Milan · Champions League' },
  { e:'📈', t:'<em>Mbappé</em> es el máximo goleador de la historia de la Selección Francesa superando a Thierry Henry.', m:'Kylian Mbappé · Francia' },
  { e:'💥', t:'<em>Aguero</em> anotó el gol más dramático de la historia de la Premier League en el minuto 93+20.', m:'Sergio Agüero · Manchester City · 2012' },
  { e:'🧤', t:'<em>Alisson</em> anotó un gol de cabeza en el minuto 95 para clasificar al Liverpool a la Champions en 2021.', m:'Alisson Becker · 2021' },
  { e:'🏅', t:'<em>Maradona</em> lideró al Napoli a ganar dos ligas italianas, siendo un fenómeno cultural en la ciudad.', m:'Diego Maradona · SSC Napoli' },
  { e:'🔥', t:'El <em>Atlético de Madrid</em> eliminó al Barcelona y al Real Madrid en la misma edición de la Champions (2016).', m:'Atlético de Madrid · 2015/16' },
  { e:'🏆', t:'<em>Estudiantes de La Plata</em> ganó 3 Copas Libertadores consecutivas (1968, 1969, 1970).', m:'Estudiantes LP · Historia' },
  { e:'🎖️', t:'<em>Cech</em> acumuló 202 clean sheets en la Premier League, más que ningún otro portero en la historia.', m:'Petr Cech · Premier League' },
  { e:'📉', t:'<em>Eto\'o</em> ganó la Champions League con dos clubes diferentes: Barcelona (2006, 2009) e Inter (2010).', m:'Samuel Eto\'o · Champions League' },
  { e:'⚡', t:'<em>Robben</em> anotó el gol ganador de la Champions 2013 en el minuto 89 contra el Dortmund.', m:'Arjen Robben · 2013' },
  { e:'🌍', t:'<em>Italia</em> no clasificó al Mundial 2018 por primera vez desde 1958, un shock histórico para el fútbol europeo.', m:'Italia · Eliminatorias 2018' },
  { e:'⚽', t:'El <em>Barcelona</em> de Messi anotó más de 100 goles en Liga en cuatro temporadas diferentes.', m:'FC Barcelona · La Liga' },
  { e:'🔥', t:'<em>Haaland</em> anotó 36 goles en su primera temporada en la Premier League (2022/23), récord absoluto.', m:'Erling Haaland · 2022/23' },
  { e:'🏟️', t:'El <em>Bernabéu</em> fue reformado con una cubierta retráctil única en el mundo, costando más de 900M de euros.', m:'Real Madrid · Santiago Bernabéu' },
  { e:'💫', t:'<em>Lautaro Martínez</em> fue el máximo goleador del Mundial 2026, consagrándose con Argentina.', m:'Lautaro Martínez · 2026' },
  { e:'📊', t:'El <em>Napoli</em> de Spalletti ganó el Scudetto 2022/23 con la mayor diferencia de puntos en décadas en Serie A.', m:'SSC Napoli · 2022/23' },
  { e:'🥇', t:'<em>Beckham</em> es el único inglés en ganar ligas en cuatro países diferentes: Inglaterra, España, EE.UU. y Francia.', m:'David Beckham · Historia' },
  { e:'🏆', t:'<em>Racing Club</em> fue el primer equipo argentino en ganar la Copa Intercontinental en 1967.', m:'Racing Club · 1967' },
  { e:'🎯', t:'<em>Lewandowski</em> es el primer polaco en ganar el premio al Mejor Jugador del Mundo de la FIFA.', m:'Robert Lewandowski · 2020' },
  { e:'⚡', t:'<em>Toni Kroos</em> completó el 93% de sus pases en toda su carrera en el Real Madrid, una cifra extraordinaria.', m:'Toni Kroos · Real Madrid' },
  { e:'🌟', t:'El <em>Borussia Dortmund</em> formó la delantera más cara jamás vendida: Dembélé, Pulisic y Sancho por +300M.', m:'Borussia Dortmund · Traspasos' },
  { e:'⚽', t:'<em>Ronaldo Nazário</em> anotó 15 goles en 9 partidos de Mundial, una eficiencia histórica.', m:'Ronaldo Nazário · FIFA World Cup' },
  { e:'🔴', t:'<em>Casemiro</em> ganó 5 Champions League con el Real Madrid, siendo pieza clave en el mediocampo defensivo.', m:'Casemiro · Real Madrid' },
  { e:'📈', t:'<em>Messi</em> tiene más asistencias de gol que cualquier jugador en la historia de La Liga.', m:'Lionel Messi · La Liga' },
  { e:'💥', t:'El <em>Manchester United</em> de Ferguson ganó la Champions 1999 con dos goles en el tiempo de descuento.', m:'Manchester United · 1999' },
  { e:'🧠', t:'<em>Guardiola</em> es el entrenador con más títulos en Champions League ganando como jugador y como DT.', m:'Pep Guardiola · Historia' },
  { e:'🏅', t:'<em>Drogba</em> anotó el gol del empate en el minuto 88 de la final de la Champions 2012 y el penalti decisivo.', m:'Didier Drogba · Chelsea 2012' },
  { e:'🔥', t:'<em>Figo</em> fue silbado con una cabeza de cerdo al volver al Camp Nou tras su polémica salida al Real Madrid.', m:'Luis Figo · 2000' },
  { e:'🏆', t:'La <em>Copa Libertadores</em> fue ganada por equipos argentinos en 25 de sus ediciones, más que ningún otro país.', m:'Argentina · Copa Libertadores' },
  { e:'🎖️', t:'<em>Cannavaro</em> es el último defensor en ganar el Balón de Oro (2006), año en que Italia ganó el Mundial.', m:'Fabio Cannavaro · 2006' },
  { e:'📉', t:'<em>Mancini</em> transformó a Italia de equipo mediocre a campeón de la Eurocopa 2021 invicto en el torneo.', m:'Roberto Mancini · Italia 2021' },
  { e:'⚡', t:'<em>Boca Juniors</em> jugó y ganó la Copa Intercontinental en tres ocasiones: 1977, 2000 y 2003.', m:'Boca Juniors · Historia' },
  { e:'🌍', t:'<em>Argentina</em> es el único país campeón del mundo con Menotti (1978) y con Bilardo (1986), estilos opuestos.', m:'Argentina · Mundiales' },
]

let _factIdx = Math.floor(Math.random() * FACTS.length)

function renderFact() {
  const f = FACTS[_factIdx]
  document.getElementById('fact-emoji').textContent = f.e
  document.getElementById('fact-text').innerHTML = f.t
  document.getElementById('fact-meta').textContent = f.m
}

function nextFact() {
  _factIdx = (_factIdx + 1) % FACTS.length
  const card = document.querySelector('.fact-card')
  card.style.opacity = '0'
  card.style.transform = 'translateY(6px)'
  setTimeout(() => {
    renderFact()
    card.style.transition = 'opacity .3s,transform .3s'
    card.style.opacity = '1'
    card.style.transform = 'translateY(0)'
  }, 180)
}

document.addEventListener('DOMContentLoaded', () => {
  const card = document.querySelector('.fact-card')
  if (card) { card.style.transition = 'opacity .3s,transform .3s'; renderFact() }
})
// ── FIN FACTS JS ──
"""

# Bloque CTA original a reemplazar — buscaremos por marcador <!-- CTA -->
OLD_CTA_MARKER = "<!-- CTA -->"
NEW_CTA = HTML_FACTS + "\n  <!-- CTA -->"

def patch(html_path: Path) -> None:
    src = html_path.read_text(encoding='utf-8')

    # 1 — CSS
    if 'facts-section' in src:
        print('[patch] ⏭  CSS: facts ya existe, salteando')
    elif '</style>' in src:
        src = src.replace('</style>', CSS_FACTS + '</style>', 1)
        print('[patch] ✅ CSS de facts insertado')
    else:
        print('[patch] ⚠️  CSS: no se encontró </style>')

    # 2 — HTML: reemplazar bloque CTA
    # Buscar el bloque completo entre <!-- CTA --> y <!-- /CTA -->
    if '<!-- FACTS SECTION -->' in src:
        print('[patch] ⏭  HTML: facts ya existe, salteando')
    else:
        # Intentar reemplazar todo el bloque CTA
        start_marker = '<!-- CTA -->'
        end_marker = '<!-- /CTA -->'
        if start_marker in src and end_marker in src:
            start_idx = src.find(start_marker)
            end_idx = src.find(end_marker) + len(end_marker)
            src = src[:start_idx] + HTML_FACTS + '\n' + src[end_idx:]
            print('[patch] ✅ Bloque CTA reemplazado por Facts')
        elif start_marker in src:
            src = src.replace(start_marker, HTML_FACTS + '\n  ' + start_marker, 1)
            print('[patch] ✅ Facts insertado antes del CTA marker')
        else:
            print('[patch] ⚠️  HTML: no se encontró <!-- CTA --> — revisá manualmente')

    # 3 — JS: antes del último </script>
    if 'FACTS =' in src:
        print('[patch] ⏭  JS: facts ya existe, salteando')
    elif '</script>' in src:
        idx = src.rfind('</script>')
        src = src[:idx] + JS_FACTS + '\n' + src[idx:]
        print('[patch] ✅ JS de facts insertado')
    else:
        print('[patch] ⚠️  JS: no se encontró </script>')

    html_path.write_text(src, encoding='utf-8')
    print(f'[patch] ✅ {html_path} guardado ({len(src):,} bytes)')


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', default='web/index.html')
    args = ap.parse_args()
    html_path = Path(args.html)
    if not html_path.exists():
        print(f'[patch] ❌ No se encontró {html_path}')
        return
    print(f'[patch] Aplicando facts section sobre {html_path} ...')
    patch(html_path)

if __name__ == '__main__':
    main()
