/**
 * netlify/edge-functions/seo.js
 * Intercepta rutas de partidos y comparador para inyectar
 * meta tags Open Graph dinámicos antes de servir el HTML.
 *
 * Rutas manejadas:
 *   /partido/:slug   → meta tags del partido específico
 *   /comparador      → meta tags genéricos del comparador
 *   /insights        → meta tags de insights
 *   /ranking         → meta tags de ranking
 */

const SB_URL = 'https://dyeouwqtebrvioesrbcf.supabase.co'
const SB_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImR5ZW91d3F0ZWJydmlvZXNyYmNmIiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzg2MTE4MzIsImV4cCI6MjA5NDE4NzgzMn0.t_9uVZLKl-khTfjnOvlebTUIYZ9C2fMVDM-6ZqMDMaA'
const SITE   = 'https://futversus.com'
const SITE_NAME = 'FutVS'
const DEFAULT_IMG = `${SITE}/og-default.svg`

// ── Helpers ──────────────────────────────────────────────────────────────────
function slugify(s) {
  return (s || '').toLowerCase()
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')
}

function matchSlug(m) {
  const date = (m.kickoff_time || m.fecha || '').slice(0, 10)
  const h = slugify(m.home_name || m.equipo_local || 'local')
  const a = slugify(m.away_name || m.equipo_visitante || 'visit')
  return `${h}-vs-${a}-${date}`
}

async function sbGet(path) {
  try {
    const res = await fetch(`${SB_URL}/rest/v1/${path}`, {
      headers: { apikey: SB_KEY, Authorization: `Bearer ${SB_KEY}` }
    })
    if (!res.ok) return null
    return res.json()
  } catch { return null }
}

function injectMeta(html, tags) {
  const meta = `
    <title>${tags.title}</title>
    <meta name="description" content="${tags.desc}">
    <!-- Open Graph -->
    <meta property="og:type" content="website">
    <meta property="og:site_name" content="${SITE_NAME}">
    <meta property="og:title" content="${tags.title}">
    <meta property="og:description" content="${tags.desc}">
    <meta property="og:url" content="${tags.url}">
    <meta property="og:image" content="${tags.img || DEFAULT_IMG}">
    <meta property="og:image:width" content="1200">
    <meta property="og:image:height" content="630">
    <!-- Twitter Card -->
    <meta name="twitter:card" content="summary_large_image">
    <meta name="twitter:title" content="${tags.title}">
    <meta name="twitter:description" content="${tags.desc}">
    <meta name="twitter:image" content="${tags.img || DEFAULT_IMG}">
    <!-- Canonical -->
    <link rel="canonical" href="${tags.url}">
  `
  // Reemplazar el bloque <title> existente y agregar metas después de <head>
  return html
    .replace(/<title>[^<]*<\/title>/, '')
    .replace(/<head>/, `<head>${meta}`)
}

// ── Meta tags por ruta ───────────────────────────────────────────────────────
async function getPartidoMeta(slug, url) {
  // Buscar partido por slug en Supabase
  const rows = await sbGet(
    `partidos?select=id,fecha,equipo_local:equipo_local_id(nombre,escudo_url),equipo_visitante:equipo_visitante_id(nombre,escudo_url),liga:liga_id(nombre)&orden=fecha&limit=200`
  )

  let partido = null
  if (rows) {
    partido = rows.find(p => {
      const h = slugify(p.equipo_local?.nombre || '')
      const a = slugify(p.equipo_visitante?.nombre || '')
      const d = (p.fecha || '').slice(0, 10)
      return `${h}-vs-${a}-${d}` === slug
    })
  }

  if (!partido) {
    // Fallback con datos del slug
    const parts = slug.split('-vs-')
    const home = parts[0]?.replace(/-/g, ' ') || 'Local'
    const rest = parts[1]?.split('-') || []
    const away = rest.slice(0, -3).join(' ') || 'Visitante'
    return {
      title: `${home} vs ${away} — Pronóstico y estadísticas | FutVS`,
      desc: `Predicción, probabilidades y análisis estadístico para ${home} vs ${away}. Modelo Dixon-Coles + Elo + XGBoost.`,
      url: `${SITE}/partido/${slug}`,
      img: DEFAULT_IMG,
    }
  }

  const home = partido.equipo_local?.nombre || 'Local'
  const away = partido.equipo_visitante?.nombre || 'Visitante'
  const liga = partido.liga?.nombre || ''
  const fecha = partido.fecha ? new Date(partido.fecha).toLocaleDateString('es-AR', { day: 'numeric', month: 'long', year: 'numeric' }) : ''

  return {
    title: `${home} vs ${away} — Pronóstico ${fecha} | FutVS`,
    desc: `Predicción estadística para ${home} vs ${away}${liga ? ` (${liga})` : ''}${fecha ? ` el ${fecha}` : ''}. Probabilidades, xG esperado y análisis del modelo FutVS.`,
    url: `${SITE}/partido/${slug}`,
    img: partido.equipo_local?.escudo_url || DEFAULT_IMG,
  }
}

function getComparadorMeta(searchParams) {
  const a = searchParams.get('a')?.replace(/-/g, ' ') || ''
  const b = searchParams.get('b')?.replace(/-/g, ' ') || ''

  if (a && b) {
    const titleA = a.charAt(0).toUpperCase() + a.slice(1)
    const titleB = b.charAt(0).toUpperCase() + b.slice(1)
    return {
      title: `${titleA} vs ${titleB} — Comparador histórico | FutVS`,
      desc: `Comparación estadística e histórica entre ${titleA} y ${titleB}: títulos, head-to-head, Elo y más.`,
      url: `${SITE}/comparador?a=${a.replace(/ /g, '-')}&b=${b.replace(/ /g, '-')}`,
      img: DEFAULT_IMG,
    }
  }

  return {
    title: 'Comparador de equipos — FutVS',
    desc: 'Compará cualquier equipo o selección: estadísticas históricas, head-to-head, títulos y rankings Elo.',
    url: `${SITE}/comparador`,
    img: DEFAULT_IMG,
  }
}

const STATIC_META = {
  '/insights': {
    title: 'Insights de fútbol — Análisis semanal | FutVS',
    desc: 'Análisis semanal de fútbol: rendimiento vs xG, alertas del modelo, tendencias y oportunidades detectadas por el algoritmo FutVS.',
    url: `${SITE}/insights`,
  },
  '/ranking': {
    title: 'Ranking mundial de jugadores — FutVS',
    desc: 'Ranking global de los mejores jugadores del mundo basado en estadísticas reales. Filtrá por posición, país o liga.',
    url: `${SITE}/ranking`,
  },
  '/': {
    title: 'FutVS — Pronósticos de fútbol con inteligencia estadística',
    desc: 'Predicciones de fútbol basadas en Dixon-Coles, Elo y XGBoost. Premier League, La Liga, Champions League y más.',
    url: SITE,
  },
}

// ── Handler principal ────────────────────────────────────────────────────────
export default async function handler(request, context) {
  const url     = new URL(request.url)
  const path    = url.pathname
  const params  = url.searchParams

  // Solo para bots / crawlers (chequear User-Agent)
  // Para usuarios normales dejamos pasar directo (más rápido)
  const ua = request.headers.get('user-agent') || ''
  const isBot = /bot|crawler|spider|facebookexternalhit|twitterbot|whatsapp|telegram|slack|discord|linkedin|googlebot|bingbot|preview/i.test(ua)

  // Para usuarios normales, servir el HTML sin tocar (performance)
  if (!isBot) return context.next()

  // Obtener el HTML base
  const response = await context.next()
  if (!response.ok) return response

  const html = await response.text()

  let tags
  const partidoMatch = path.match(/^\/partido\/([^\/]+)\/?$/)

  if (partidoMatch) {
    tags = await getPartidoMeta(decodeURIComponent(partidoMatch[1]), url)
  } else if (path.startsWith('/comparador')) {
    tags = getComparadorMeta(params)
  } else if (STATIC_META[path]) {
    tags = { ...STATIC_META[path], img: DEFAULT_IMG }
  } else {
    return response
  }

  const newHtml = injectMeta(html, tags)

  return new Response(newHtml, {
    status: response.status,
    headers: {
      ...Object.fromEntries(response.headers),
      'content-type': 'text/html; charset=utf-8',
    },
  })
}

export const config = {
  path: ['/', '/partido/*', '/comparador', '/comparador/*', '/insights', '/ranking'],
}
