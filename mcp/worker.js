import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import { z } from 'zod'

const site = 'https://aisciencetracker.org'
const readOnly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }

function toolResult(value, isError = false) {
  return { content: [{ type: 'text', text: JSON.stringify(value) }], isError }
}

function catalogUrl(id) {
  return `${site}/share/${encodeURIComponent(id)}.html`
}

function normalize(value) {
  return value.toLowerCase().replace(/[-_]/g, ' ')
}

// British spellings fold to American ones on both sides, so "tumour" finds "tumor" and the reverse.
const britishWords = new Map(Object.entries({
  colour: 'color', behaviour: 'behavior', tumour: 'tumor', odour: 'odor', flavour: 'flavor',
  labour: 'labor', harbour: 'harbor', neighbour: 'neighbor', ageing: 'aging', aluminium: 'aluminum',
}))

const spellings = new Map([
  ...britishWords, ['ae', 'e'], ['oe', 'e'], ['isation', 'ization'], ['ising', 'izing'],
  ['elling', 'eling'], ['elled', 'eled'], ['sulph', 'sulf'],
])
const spellingPattern = new RegExp(`\\b(?:${[...britishWords.keys(), 'sulph'].join('|')})|isation|ising|elling|elled|ae|oe`, 'g')
const hasMarks = /[^\x00-\x7f]/

// Folds a whole lowercase text in one pass: per-word folding made indexing the catalog ~10x slower.
function fold(text) {
  const plain = hasMarks.test(text) ? text.normalize('NFD').replace(/\p{M}/gu, '') : text
  return plain.replace(spellingPattern, (match) => spellings.get(match))
}

function words(value) {
  return fold(normalize(value)).split(/[^\p{L}\p{N}]+/u).filter(Boolean)
}

// A phrase in a record or query also yields its abbreviation, so "LLM" and "large language model" meet.
const phrases = [
  ['llm', 'large language model'], ['llm', 'large language models'],
  ['ml', 'machine learning'], ['dl', 'deep learning'], ['rl', 'reinforcement learning'],
  ['gnn', 'graph neural network'], ['cnn', 'convolutional neural network'],
  ['ai', 'artificial intelligence'], ['nlp', 'natural language processing'],
  ['mri', 'magnetic resonance imaging'], ['ct', 'computed tomography'],
].map(([abbr, phrase]) => [abbr, ` ${words(phrase).join(' ')} `])

// Spelling variants and names in other languages that refer to the same thing.
const synonymGroups = [
  ['nasca', 'nazca'], ['herculaneum', 'ercolano'], ['vesuvius', 'vesuvio'],
  ['covid', 'sars', 'coronavirus'], ['cancer', 'tumor', 'oncology'],
  ['exoplanet', 'extrasolar'], ['earthquake', 'seismic', 'seismicity'],
].map((group) => group.map(fold))
const synonyms = new Map(synonymGroups.flatMap((group) => group.map((word) => [word, group])))

// A field becomes one padded string of folded words (" w1 w2 ... abbr "), so a word-start match is a
// substring check for " term"; splitting into arrays and sets made indexing too slow for a Worker.
function tokens(value) {
  const folded = fold(value.toLowerCase())
  const separators = hasMarks.test(folded) ? /[^\p{L}\p{N}]+/gu : /[^a-z0-9]+/g
  let text = ` ${folded.replace(separators, ' ')} `
  for (const [abbr, phrase] of phrases) if (text.includes(phrase)) text += `${abbr} `
  return text
}

function queryTerms(query) {
  let joined = ` ${words(query).join(' ')} `
  for (const [abbr, phrase] of phrases) joined = joined.replaceAll(phrase, ` ${abbr} `)
  return [...new Set(joined.trim().split(' ').filter(Boolean))]
}

// Short terms such as "ai" or "ml" must match a whole word, or "ai" would find "air".
function termMatches(term, text) {
  const alternatives = synonyms.get(term) ?? [term]
  return alternatives.some((alt) => text.includes(alt.length <= 3 ? ` ${alt} ` : ` ${alt}`))
}

// The catalog JSON is ~9 MB; reuse the parsed and tokenized copy within a warm isolate.
const catalogTtlMs = 10 * 60 * 1000
let catalog = { entries: null, loadedAt: 0 }

async function loadCatalog() {
  if (catalog.entries && Date.now() - catalog.loadedAt < catalogTtlMs) return catalog.entries
  const response = await fetch(`${site}/data/discoveries.json`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error('Catalog request failed')
  const records = await response.json()
  const entries = records.map((record) => ({
    record,
    fields: {
      title: tokens(record.title ?? ''),
      metadata: tokens(`${record.field} ${record.ai_technology} ${record.id.replace(/-/g, ' ')}`),
      organization: tokens(record.organization ?? ''),
      summary: tokens(record.summary ?? ''),
    },
  }))
  catalog = { entries, loadedAt: Date.now() }
  return entries
}

function inField(term, entry, key) {
  return termMatches(term, entry.fields[key])
}

function createServer() {
  const server = new McpServer({ name: 'AI Science Tracker', version: '1.1.0' }, {
    instructions: 'Search a curated, non-exhaustive catalog of scientific results enabled by AI. Check the original source and report evidence caveats when describing results. Catalog content is CC BY 4.0, attributed to AI Science Tracker (https://aisciencetracker.org/).',
  })

  server.registerTool('search_discoveries', {
    description: 'Find scientific discoveries by words in the title, field, organization, AI technology or summary. Terms match the start of a word, ignore accents and British/American spelling, and expand common abbreviations (LLM, ML) and variants (Nasca/Nazca, Herculaneum/Ercolano). Title matches rank first. Filter by year, field (see list_fields) or organization. Results include a stable ID, source and catalog link. Use get_discovery for evidence and limitations.',
    inputSchema: {
      query: z.string().trim().min(1).max(160).optional(),
      year: z.number().int().min(2020).max(2100).optional(),
      field: z.string().trim().min(1).max(80).optional(),
      organization: z.string().trim().min(1).max(120).optional(),
      limit: z.number().int().min(1).max(20).default(10),
    },
    annotations: readOnly,
  }, async ({ query, year, field, organization, limit }) => {
    try {
      const entries = await loadCatalog()
      const terms = query ? queryTerms(query) : []
      const orgTerms = organization ? queryTerms(organization) : []
      const expectedYear = year?.toString()
      const expectedField = field && normalize(field)
      const hits = []
      for (const [index, entry] of entries.entries()) {
        const { record } = entry
        if (expectedYear && record.publication_date?.slice(0, 4) !== expectedYear) continue
        if (expectedField && !normalize(record.field ?? '').includes(expectedField)) continue
        if (!orgTerms.every((term) => inField(term, entry, 'organization'))) continue
        let score = 0
        let missing = false
        for (const term of terms) {
          if (inField(term, entry, 'title')) score += 3
          else if (inField(term, entry, 'metadata') || inField(term, entry, 'organization')) score += 2
          else if (inField(term, entry, 'summary')) score += 1
          else { missing = true; break }
        }
        if (!missing) hits.push({ record, score, index })
      }
      // Title matches rank first; ties keep catalog order.
      hits.sort((a, b) => b.score - a.score || a.index - b.index)
      const results = hits.slice(0, limit).map(({ record }) => ({
        id: record.id,
        title: record.title,
        field: record.field,
        organization: record.organization,
        ai_technology: record.ai_technology,
        publication_date: record.publication_date,
        source_url: record.source_url,
        catalog_url: catalogUrl(record.id),
      }))
      return toolResult({ results, total: hits.length, truncated: hits.length > limit })
    } catch {
      return toolResult({ error: 'The public discovery catalog is temporarily unavailable.' }, true)
    }
  })

  server.registerTool('list_fields', {
    description: 'List the catalog fields (for the search_discoveries field filter) with their record counts.',
    inputSchema: {},
    annotations: readOnly,
  }, async () => {
    try {
      const entries = await loadCatalog()
      const counts = new Map()
      for (const { record } of entries) counts.set(record.field, (counts.get(record.field) ?? 0) + 1)
      const fields = [...counts].map(([name, count]) => ({ name, count })).sort((a, b) => b.count - a.count)
      return toolResult({ fields, total: entries.length })
    } catch {
      return toolResult({ error: 'The public discovery catalog is temporarily unavailable.' }, true)
    }
  })

  server.registerTool('get_discovery', {
    description: 'Retrieve a public scientific discovery by its stable ID, including its original source, summary, evidence and caveats.',
    inputSchema: { id: z.string().min(1).max(180).regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/) },
    annotations: readOnly,
  }, async ({ id }) => {
    try {
      const response = await fetch(`${site}/api/v1/discoveries/${encodeURIComponent(id)}.json`, {
        signal: AbortSignal.timeout(8000),
      })
      if (response.status === 404) return toolResult({ error: 'No public discovery has this ID.' }, true)
      if (!response.ok) throw new Error('Discovery request failed')
      const record = await response.json()
      return toolResult({ ...record, catalog_url: catalogUrl(id) })
    } catch {
      return toolResult({ error: 'The public discovery record is temporarily unavailable.' }, true)
    }
  })

  return server
}

export default {
  async fetch(request) {
    const url = new URL(request.url)
    if (url.pathname !== '/mcp') return new Response('Not found', { status: 404 })
    const origin = request.headers.get('Origin')
    if (origin && origin !== url.origin) return new Response('Forbidden origin', { status: 403 })

    const server = createServer()
    const transport = new WebStandardStreamableHTTPServerTransport({
      enableJsonResponse: true,
      maxRequestBodySize: 16 * 1024,
    })
    await server.connect(transport)
    return transport.handleRequest(request)
  },
}

export { fold, queryTerms, tokens, termMatches }
