import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js'
import { WebStandardStreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js'
import { z } from 'zod'

const site = 'https://aisciencetracker.org'
const readOnly = { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false }

function toolResult(value, isError = false) {
  const result = { content: [{ type: 'text', text: JSON.stringify(value) }], isError }
  if (!isError) result.structuredContent = value
  return result
}

function brief(text = '') {
  return text.length <= 280 ? text : `${text.slice(0, 280).replace(/\s+\S*$/, '')}…`
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

function stripMarks(text) {
  return hasMarks.test(text) ? text.normalize('NFD').replace(/\p{M}/gu, '') : text
}

function spellFold(text) {
  return text.replace(spellingPattern, (match) => spellings.get(match))
}

// Folds a whole lowercase text in one pass: per-word folding made indexing the catalog ~10x slower.
function fold(text) {
  return spellFold(stripMarks(text))
}

function words(value) {
  return stripMarks(normalize(value)).split(/[^\p{L}\p{N}]+/u).filter(Boolean)
}

// Query words that carry no topic; dropped unless the query has nothing else.
const stopwords = new Set(('a an and are as at be by can do does for from has have how in into is it its of on or ' +
  'that the their this to was what when where which who why with about using used new study studies ' +
  'help helps find finds found discover discovers discovered show shows ' +
  // Every record is AI-enabled, so these words filter nothing useful and only drop records that say "ML".
  'ai artificial intelligence').split(' '))

// Query-side plural folding: the match is a word-start prefix, so "antibiotic" also finds "antibiotics".
function singular(term) {
  if (abbreviations.has(term.slice(0, -1)) && term.endsWith('s')) return term.slice(0, -1)
  return term.length > 4 && term.endsWith('s') && !/(ss|us|is)$/.test(term) ? term.slice(0, -1) : term
}

// A phrase in a record or query also yields its abbreviation, so "LLM" and "large language model" meet.
const phrases = [
  ['llm', 'large language model'], ['llm', 'large language models'],
  ['ml', 'machine learning'], ['dl', 'deep learning'], ['rl', 'reinforcement learning'],
  ['gnn', 'graph neural network'], ['cnn', 'convolutional neural network'],
  ['ai', 'artificial intelligence'], ['nlp', 'natural language processing'],
  ['mri', 'magnetic resonance imaging'], ['ct', 'computed tomography'],
].map(([abbr, phrase]) => [abbr, ` ${words(phrase).map(spellFold).join(' ')} `])
const abbreviations = new Set(phrases.map(([abbr]) => abbr))

// Spelling variants and names in other languages that refer to the same thing.
const synonymGroups = [
  ['nasca', 'nazca'], ['herculaneum', 'ercolano'], ['vesuvius', 'vesuvio'],
  ['covid', 'sars', 'coronavirus'], ['cancer', 'tumor', 'oncology'],
  ['exoplanet', 'extrasolar'], ['earthquake', 'seismic', 'seismicity'],
].map((group) => group.map(fold))
const synonyms = new Map(synonymGroups.flatMap((group) => group.map((word) => [word, group])))

// A field becomes one padded string of words (" w1 w2 ... abbr "), so a word-start match is a substring
// check for " term"; splitting into arrays and sets made indexing too slow for a Worker. The original
// spelling is kept and the American-folded copy appended, so "swell" still finds "swelling" ("sweling").
function tokens(value) {
  const plain = stripMarks(value.toLowerCase())
  const separators = hasMarks.test(value) ? /[^\p{L}\p{N}]+/gu : /[^a-z0-9]+/g
  let text = ` ${plain.replace(separators, ' ')} `
  const folded = spellFold(text)
  if (folded !== text) text += folded.slice(1)
  for (const [abbr, phrase] of phrases) if (text.includes(phrase)) text += `${abbr} `
  return text
}

function queryTerms(query, { dropStopwords = true } = {}) {
  let joined = ` ${words(query).map(spellFold).join(' ')} `
  for (const [abbr, phrase] of phrases) joined = joined.replaceAll(phrase, ` ${abbr} `)
  const all = [...new Set(joined.trim().split(' ').filter(Boolean).map(singular))]
  const topical = dropStopwords ? all.filter((term) => !stopwords.has(term)) : all
  return topical.length ? topical : all
}

// Short terms such as "ai" or "ml" must match a whole word, or "ai" would find "air".
function termMatches(term, text) {
  const alternatives = synonyms.get(term) ?? [term]
  return alternatives.some((alt) => text.includes(alt.length <= 3 ? ` ${alt} ` : ` ${alt}`))
}

// The catalog JSON is ~11 MB; reuse the parsed and tokenized copy within a warm isolate. Concurrent
// requests share one download, and a failed refresh keeps serving the previous copy.
const catalogTtlMs = 10 * 60 * 1000
let catalog = { entries: null, loadedAt: 0 }
let pending = null

async function loadCatalog() {
  if (catalog.entries && Date.now() - catalog.loadedAt < catalogTtlMs) return catalog.entries
  pending ??= fetchCatalog().finally(() => { pending = null })
  try {
    return await pending
  } catch (error) {
    if (catalog.entries) return catalog.entries
    throw error
  }
}

async function fetchCatalog() {
  const response = await fetch(`${site}/data/discoveries.json`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error('Catalog request failed')
  const records = await response.json()
  const entries = records.map((record) => ({
    record,
    fields: {
      title: tokens(record.title ?? ''),
      metadata: tokens(`${record.field ?? ''} ${record.ai_technology ?? ''} ${record.id.replace(/-/g, ' ')}`),
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
  const server = new McpServer({ name: 'AI Science Tracker', version: '1.2.0' }, {
    instructions: 'Search a curated, non-exhaustive catalog of scientific results enabled by AI. Check the original source and report evidence caveats when describing results. Catalog content is CC BY 4.0, attributed to AI Science Tracker (https://aisciencetracker.org/).',
  })

  server.registerTool('search_discoveries', {
    description: 'Find scientific discoveries by words in the title, field, organization, AI technology or summary. Terms match the start of a word, ignore accents and British/American spelling, and expand common abbreviations (LLM, ML) and variants (Nasca/Nazca, Herculaneum/Ercolano). Common words such as "how" or "new" are ignored; if no record matches every term, a longer query returns the records matching most of them, flagged partial_match. Title matches rank first. Filter by year, field (see list_fields) or organization. Page with offset. Results include a stable ID, short summary, source and catalog link. Use get_discovery for evidence and limitations.',
    inputSchema: {
      query: z.string().trim().min(1).max(160).optional(),
      year: z.number().int().min(2020).max(2100).optional(),
      field: z.string().trim().min(1).max(80).optional(),
      organization: z.string().trim().min(1).max(120).optional(),
      limit: z.number().int().min(1).max(20).default(10),
      offset: z.number().int().min(0).max(10000).default(0),
    },
    annotations: readOnly,
  }, async ({ query, year, field, organization, limit, offset }) => {
    const terms = query ? queryTerms(query) : []
    if (query && !terms.length) return toolResult({ error: 'The query has no searchable words.' }, true)
    try {
      const entries = await loadCatalog()
      // Organization names keep every word: "New York University" must not lose "new".
      const orgTerms = organization ? queryTerms(organization, { dropStopwords: false }) : []
      const expectedYear = year?.toString()
      const expectedField = field && normalize(field)
      const needed = terms.length > 2 ? Math.ceil(terms.length / 2) : terms.length
      const hits = []
      for (const [index, entry] of entries.entries()) {
        const { record } = entry
        if (expectedYear && record.publication_date?.slice(0, 4) !== expectedYear) continue
        if (expectedField && !normalize(record.field ?? '').includes(expectedField)) continue
        if (!orgTerms.every((term) => inField(term, entry, 'organization'))) continue
        let score = 0
        let matched = 0
        for (const term of terms) {
          if (inField(term, entry, 'title')) score += 3
          else if (inField(term, entry, 'metadata') || inField(term, entry, 'organization')) score += 2
          else if (inField(term, entry, 'summary')) score += 1
          else continue
          matched += 1
        }
        if (matched >= needed) hits.push({ record, score, matched, index })
      }
      // Every term must match; with no such record, a longer query falls back to records matching most terms.
      const full = hits.filter((hit) => hit.matched === terms.length)
      const partial = !full.length && terms.length > 2
      const ranked = partial ? hits : full
      // More matched terms first, then title matches; ties keep catalog order.
      ranked.sort((a, b) => b.matched - a.matched || b.score - a.score || a.index - b.index)
      const results = ranked.slice(offset, offset + limit).map(({ record }) => ({
        id: record.id,
        title: record.title,
        field: record.field,
        organization: record.organization,
        ai_technology: record.ai_technology,
        publication_date: record.publication_date,
        summary: brief(record.summary),
        source_url: record.source_url,
        catalog_url: catalogUrl(record.id),
      }))
      const answer = { results, total: ranked.length, offset, truncated: ranked.length > offset + limit }
      if (partial) answer.partial_match = 'No record matched every term; results match most of them.'
      return toolResult(answer)
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
    // IDs are lowercase slugs; some contain "--" or end in "-". No "." or "/" can reach the URL path.
    inputSchema: { id: z.string().trim().min(1).max(200).regex(/^[a-z0-9][a-z0-9-]*$/) },
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
  async fetch(request, env = {}) {
    const url = new URL(request.url)
    if (url.pathname !== '/mcp') return new Response('Not found', { status: 404 })
    const origin = request.headers.get('Origin')
    if (origin && origin !== url.origin) return new Response('Forbidden origin', { status: 403 })
    // Per-client limit protects the free Workers quota; the binding is absent in local tests.
    const client = request.headers.get('CF-Connecting-IP') ?? 'local'
    if (env.LIMITER && !(await env.LIMITER.limit({ key: client })).success) {
      return new Response('Too many requests', { status: 429, headers: { 'Retry-After': '60' } })
    }

    const server = createServer()
    const transport = new WebStandardStreamableHTTPServerTransport({
      enableJsonResponse: true,
      maxRequestBodySize: 16 * 1024,
    })
    await server.connect(transport)
    return transport.handleRequest(request)
  },
}

export { fold, queryTerms, tokens, termMatches, loadCatalog }
