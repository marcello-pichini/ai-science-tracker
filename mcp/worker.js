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

// Terms match the start of a word, so "whale" finds "whales" but "ants" no longer finds "variants".
function words(value) {
  return normalize(value).split(/[^\p{L}\p{N}]+/u).filter(Boolean)
}

// The catalog JSON is ~9 MB; reuse the parsed copy within a warm isolate instead of re-parsing per call.
const catalogTtlMs = 10 * 60 * 1000
let catalog = { records: null, loadedAt: 0 }

async function loadCatalog() {
  if (catalog.records && Date.now() - catalog.loadedAt < catalogTtlMs) return catalog.records
  const response = await fetch(`${site}/data/discoveries.json`, { signal: AbortSignal.timeout(8000) })
  if (!response.ok) throw new Error('Catalog request failed')
  const records = await response.json()
  catalog = { records, loadedAt: Date.now() }
  return records
}

function matches(term, wordList) {
  return wordList.some((word) => word.startsWith(term))
}

function createServer() {
  const server = new McpServer({ name: 'AI Science Tracker', version: '1.0.0' }, {
    instructions: 'Search a curated, non-exhaustive catalog of scientific results enabled by AI. Check the original source and report evidence caveats when describing results. Catalog content is CC BY 4.0, attributed to AI Science Tracker (https://aisciencetracker.org/).',
  })

  server.registerTool('search_discoveries', {
    description: 'Find scientific discoveries by words in the title, field, organization, AI technology or summary. Each term must match the start of a word; title matches rank first. Results include a stable ID, source and catalog link. Use get_discovery for evidence and limitations.',
    inputSchema: {
      query: z.string().trim().min(1).max(160).optional(),
      year: z.number().int().min(2020).max(2100).optional(),
      field: z.string().trim().min(1).max(80).optional(),
      limit: z.number().int().min(1).max(20).default(10),
    },
    annotations: readOnly,
  }, async ({ query, year, field, limit }) => {
    try {
      const records = await loadCatalog()
      const terms = query ? words(query) : []
      const expectedYear = year?.toString()
      const expectedField = field && normalize(field)
      const hits = []
      for (const [index, record] of records.entries()) {
        if (expectedYear && record.publication_date?.slice(0, 4) !== expectedYear) continue
        if (expectedField && !normalize(record.field ?? '').includes(expectedField)) continue
        let score = 0
        if (terms.length) {
          const title = words(record.title ?? '')
          const metadata = words(`${record.field} ${record.organization} ${record.ai_technology} ${record.id}`)
          const summary = words(record.summary ?? '')
          let missing = false
          for (const term of terms) {
            if (matches(term, title)) score += 3
            else if (matches(term, metadata)) score += 2
            else if (matches(term, summary)) score += 1
            else { missing = true; break }
          }
          if (missing) continue
        }
        hits.push({ record, score, index })
      }
      // Title matches rank first; ties keep catalog order.
      hits.sort((a, b) => b.score - a.score || a.index - b.index)
      const results = hits.slice(0, limit).map(({ record }) => ({
        id: record.id,
        title: record.title,
        field: record.field,
        ai_technology: record.ai_technology,
        publication_date: record.publication_date,
        source_url: record.source_url,
        catalog_url: catalogUrl(record.id),
      }))
      return toolResult({ results, truncated: hits.length > limit })
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
