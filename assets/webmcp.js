/* WebMCP: offer the catalog to in-browser AI agents as read-only tools. Inert where unsupported. */
(() => {
  const context = globalThis.document?.modelContext ?? globalThis.navigator?.modelContext;
  if (!context?.registerTool) return;
  const site = location.origin;
  const cache = {};
  const load = name => (cache[name] ??= fetch(`${site}/data/${name}.json`).then(r => {
    if (!r.ok) throw new Error(`Could not load ${name}`);
    return r.json();
  }));
  const fold = value => String(value ?? '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
  // Every query word must appear in one of the record's text fields; title matches rank first.
  const search = (records, fields, query, limit) => {
    const words = fold(query).split(/[^\p{L}\p{N}.\/-]+/u).filter(Boolean);
    const hits = [];
    for (const r of records) {
      const texts = fields.map(f => fold(Array.isArray(r[f]) ? r[f].join(' ') : r[f]));
      if (words.every(w => texts.some(t => t.includes(w)))) hits.push([words.filter(w => texts[0].includes(w)).length, r]);
    }
    hits.sort((a, b) => b[0] - a[0]);
    return {total: hits.length, results: hits.slice(0, limit).map(h => h[1])};
  };
  const schema = (description, extra = {}) => ({type: 'object', properties: {
    query: {type: 'string', description},
    limit: {type: 'integer', minimum: 1, maximum: 20, default: 10, description: 'Maximum number of results.'},
    ...extra}, required: ['query']});
  const annotations = {readOnlyHint: true, untrustedContentHint: false};

  context.registerTool({
    name: 'search_discoveries',
    description: 'Search AI Science Tracker, a curated catalog of scientific results enabled by AI. Matches every word in the title, summary, field, organization, AI technology or source links (a DOI works). Returns the stable ID, date, field, organization, summary, original source and catalog page. Figures are reported by the sources; cite the original source.',
    inputSchema: schema('English words or a DOI, for example "antibiotics" or "10.1016/j.cell.2025.07.033".',
      {year: {type: 'integer', description: 'Optional publication year.'}}),
    annotations,
    execute: async ({query, limit = 10, year}) => {
      let records = await load('discoveries');
      if (year) records = records.filter(r => String(r.publication_date).startsWith(String(year)));
      const found = search(records, ['title', 'summary', 'field', 'organization', 'ai_technology', 'source_url', 'paper_url'], query, limit);
      return {total: found.total, results: found.results.map(r => ({id: r.id, title: r.title, publication_date: r.publication_date,
        field: r.field, organization: r.organization, summary: r.summary, source_url: r.source_url,
        catalog_url: `${site}/share/${encodeURIComponent(r.id)}.html`}))};
    }
  });

  context.registerTool({
    name: 'search_vulnerabilities',
    description: 'Search the preview of the global vulnerability dataset: vulnerabilities known to be exploited and critical ones published in the last 12 months. Matches words in the ID, title, products, category and weakness classes. Absence is not safety.',
    inputSchema: schema('English words or a CVE ID, for example "OpenSSL" or "CVE-2026-34197".'),
    annotations,
    execute: async ({query, limit = 10}) => {
      const found = search(await load('vulnerabilities-preview'), ['title', 'id', 'products', 'category', 'classes'], query, limit);
      return {total: found.total, results: found.results.map(r => ({...r, catalog_url: `${site}/security.html?q=${encodeURIComponent(r.id)}`}))};
    }
  });

  context.registerTool({
    name: 'get_discovery',
    description: 'Get one AI Science Tracker discovery by its stable ID, with original source, summary, evidence notes and caveats.',
    inputSchema: {type: 'object', properties: {id: {type: 'string', pattern: '^[a-z0-9][a-z0-9-]*$',
      description: 'Stable ID returned by search_discoveries.'}}, required: ['id']},
    annotations,
    execute: async ({id}) => {
      const r = await fetch(`${site}/api/v1/discoveries/${encodeURIComponent(id)}.json`);
      if (!r.ok) throw new Error('No public discovery has this ID.');
      return r.json();
    }
  });
})();
