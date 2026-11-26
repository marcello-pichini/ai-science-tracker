import assert from 'node:assert/strict'
import test from 'node:test'
import { Client } from '@modelcontextprotocol/sdk/client/index.js'
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js'
import worker, { fold, queryTerms, tokens, termMatches, loadCatalog } from './worker.js'

test('search terms fold spelling, accents, abbreviations and synonyms', () => {
  const matchesText = (term, text) => termMatches(term, tokens(text))
  assert.equal(fold('tumours'), 'tumors')
  assert.equal(fold('optimisation'), 'optimization')
  assert.equal(fold('paediatric'), 'pediatric')
  assert.equal(fold('Gödel'.toLowerCase()), 'godel')
  assert.deepEqual(queryTerms('Large Language Models for chemistry'), ['llm', 'chemistr'])
  assert.deepEqual(queryTerms('how AI helps discover new antibiotics'), ['antibiotic'])
  assert.deepEqual(queryTerms('AI'), ['ai'])
  assert.deepEqual(queryTerms('studies of whales'), ['whale'])
  assert.deepEqual(queryTerms('what did GPT-5 discover'), ['gpt5'])
  assert.deepEqual(queryTerms('recent discoveries in archaeology'), ['archeolog'])
  assert.ok(matchesText(queryTerms('ancient scrolls deciphered')[2], 'Deciphering a burned scroll'))
  assert.ok(matchesText(queryTerms('oncology')[0], 'A tumour atlas'))
  assert.ok(matchesText('gpt5', 'GPT-5 proposes a proof'))
  assert.ok(matchesText(queryTerms('COVID-19')[0], 'COVID-19 detection from coughs'))
  assert.ok(!matchesText('gpt5', 'GPT-4 and 5 other models'))
  assert.deepEqual(queryTerms('LLMs and GNNs'), ['llm', 'gnn'])
  assert.deepEqual(queryTerms('New York University', { dropStopwords: false }), ['new', 'york', 'universit'])
  assert.deepEqual(queryTerms('the'), ['the'])
  assert.deepEqual(queryTerms('???'), [])
  assert.ok(matchesText('swell', 'Swelling of the tissue'))
  assert.ok(matchesText('promis', 'A promising compound'))
  assert.ok(matchesText(queryTerms('modelling')[0], 'Climate modeling at scale'))
  assert.ok(matchesText(queryTerms('modeling')[0], 'Climate modelling at scale'))
  assert.ok(matchesText(queryTerms('optimising')[0], 'Optimizing reactors'))
  assert.ok(matchesText('nasca', 'AI finds 303 new Nazca geoglyphs'))
  assert.ok(matchesText('ercolano', 'A Herculaneum scroll read'))
  assert.ok(matchesText('llm', 'A large language model proposes catalysts'))
  assert.ok(matchesText(queryTerms('tumour')[0], 'Tumor boundaries from MRI'))
  assert.ok(!matchesText('ai', 'Air quality forecasts'))
  assert.ok(!matchesText('ants', 'Rare variants in cohorts'))
})

const origin = 'https://aisciencetracker.org'
const endpoint = new URL('https://mcp.aisciencetracker.org/mcp')
const discovery = {
  id: '2025-04-example',
  title: 'AI-guided materials testing',
  field: 'Materials science',
  publication_date: '2025-04-11',
  ai_technology: 'Example model',
  source_url: 'https://example.org/paper',
  summary: 'A candidate was tested in one laboratory.',
  evidence: { unknown: 'Independent replication is pending.' },
}

test('MCP clients can search and retrieve public discoveries with provenance', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url) => {
    switch (String(url)) {
      case origin + '/data/discoveries.json':
        return Response.json([discovery, {
          ...discovery,
          id: '2024-04-example',
          publication_date: '2024-04-11',
        }, {
          ...discovery,
          id: '2023-04-laboratory-example',
          title: 'Laboratory robots run catalyst trials',
          paper_url: 'https://doi.org/10.1234/lab.5678',
          organization: 'Example Lab; Partner University',
          publication_date: '2023-04-11',
        }])
      case origin + '/api/v1/discoveries/' + discovery.id + '.json':
        return Response.json(discovery)
      case origin + '/api/v1/discoveries/2026-10-model--fonc-2026-1.json':
        return Response.json({ ...discovery, id: '2026-10-model--fonc-2026-1' })
      case origin + '/api/v1/discoveries/unknown.json':
        return new Response(null, { status: 404 })
      default:
        throw new Error('Unexpected upstream URL')
    }
  })

  const client = new Client({ name: 'catalog-test', version: '1.0.0' })
  t.after(() => client.close())
  await client.connect(new StreamableHTTPClientTransport(endpoint, {
    fetch: (url, options) => worker.fetch(new Request(url, options)),
  }))

  const { tools } = await client.listTools()
  assert.deepEqual(tools.map((tool) => tool.name).sort(), ['get_discovery', 'list_fields', 'search_discoveries'])
  assert.ok(tools.every((tool) => tool.annotations.readOnlyHint))
  assert.ok(tools.every((tool) => tool.title && Object.values(tool.inputSchema.properties ?? {}).every((p) => p.description)))

  const search = await client.callTool({
    name: 'search_discoveries',
    arguments: { query: 'AI guided', year: 2025, limit: 1 },
  })
  const { results } = JSON.parse(search.content[0].text)
  assert.deepEqual(results.map((row) => row.id), [discovery.id])
  assert.equal(results[0].source_url, discovery.source_url)
  assert.equal(results[0].summary, discovery.summary)

  const loose = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { query: 'laboratory robots quantum gravity' },
  })).content[0].text)
  assert.ok(loose.partial_match)
  assert.equal(loose.results[0].id, '2023-04-laboratory-example')
  const byDoi = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { query: 'see https://doi.org/10.1234/Lab.5678.' },
  })).content[0].text)
  assert.deepEqual(byDoi.results.map((row) => row.id), ['2023-04-laboratory-example'])
  const symbols = await client.callTool({ name: 'search_discoveries', arguments: { query: '???' } })
  assert.equal(symbols.isError, true)

  const search_ids = async (query) => JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { query },
  })).content[0].text).results.map((row) => row.id)
  // whole-word prefixes: "test" finds "testing"/"tested", "sting" finds nothing
  assert.deepEqual(await search_ids('sting'), [])
  // summary-only matches count, but a title match ranks first
  assert.deepEqual(await search_ids('laboratory'), ['2023-04-laboratory-example', discovery.id, '2024-04-example'])
  const truncated = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { query: 'laboratory', limit: 2 },
  })).content[0].text)
  assert.equal(truncated.truncated, true)
  assert.equal(truncated.results.length, 2)
  assert.equal(truncated.total, 3)

  const byOrg = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { organization: 'Example Lab' },
  })).content[0].text)
  assert.deepEqual(byOrg.results.map((row) => row.id), ['2023-04-laboratory-example'])

  const byField = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { field: 'Materials science research' },
  })).content[0].text)
  assert.equal(byField.total, 3)

  const fields = JSON.parse((await client.callTool({ name: 'list_fields', arguments: {} })).content[0].text)
  assert.deepEqual(fields, { fields: [{ name: 'Materials science', count: 3 }], total: 3 })

  const get = await client.callTool({ name: 'get_discovery', arguments: { id: discovery.id } })
  const record = JSON.parse(get.content[0].text)
  assert.equal(record.evidence.unknown, discovery.evidence.unknown)
  assert.equal(record.catalog_url, origin + '/share/' + discovery.id + '.html')
  assert.equal(record.source_url, discovery.source_url)

  const missing = await client.callTool({ name: 'get_discovery', arguments: { id: 'unknown' } })
  assert.equal(missing.isError, true)
  const doubleHyphen = await client.callTool({ name: 'get_discovery', arguments: { id: '2026-10-model--fonc-2026-1' } })
  assert.equal(doubleHyphen.isError, false)
  assert.equal(doubleHyphen.structuredContent.id, '2026-10-model--fonc-2026-1')
  const page2 = JSON.parse((await client.callTool({
    name: 'search_discoveries', arguments: { query: 'laboratory', limit: 2, offset: 2 },
  })).content[0].text)
  assert.deepEqual(page2.results.map((row) => row.id), ['2024-04-example'])
  assert.equal(page2.truncated, false)
  const traversal = await client.callTool({ name: 'get_discovery', arguments: { id: '../private' } })
  assert.equal(traversal.isError, true)
})

test('foreign browser origins and unrelated paths cannot call the Worker', async () => {
  const crossOrigin = await worker.fetch(new Request(endpoint, {
    method: 'POST',
    headers: { Origin: 'https://example.org' },
  }))
  assert.equal(crossOrigin.status, 403)
  const other = await worker.fetch(new Request(new URL('/admin', endpoint)))
  assert.equal(other.status, 404)
  for (const method of ['GET', 'DELETE']) {
    const response = await worker.fetch(new Request(endpoint, { method }))
    assert.equal(response.status, 405)
    assert.equal(response.headers.get('Allow'), 'POST')
  }
})

test('a failed catalog refresh keeps serving the previous copy', async (t) => {
  let calls = 0
  t.mock.method(globalThis, 'fetch', async () => {
    calls += 1
    return calls === 1 ? Response.json([discovery]) : new Response(null, { status: 503 })
  })
  t.mock.timers.enable({ apis: ['Date'], now: 1e13 })
  const first = await loadCatalog()
  t.mock.timers.tick(11 * 60 * 1000)
  assert.equal(await loadCatalog(), first)
  assert.equal(calls, 2)
})

test('the Worker answers 429 when the rate limiter refuses a client', async () => {
  const env = { LIMITER: { limit: async () => ({ success: false }) } }
  const response = await worker.fetch(new Request(endpoint, { method: 'POST' }), env)
  assert.equal(response.status, 429)
})
