/* Literal, inspectable search across independently counted collections. */
globalThis.CatalogSearch = {
  normalize(value) {
    return String(value ?? '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ').trim();
  },
  match(fields, query) {
    const normalized = this.normalize(query);
    const words = normalized.split(' ').filter(Boolean);
    if (!words.length) return [];
    const entries = Object.entries(fields).map(([label, value]) => [label, this.normalize(value)]);
    const doi = query.trim().replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '');
    if (/^10\.\d{4,9}\/\S+$/i.test(doi)) {
      return Object.entries(fields).filter(([, value]) => (String(value ?? '').match(/10\.\d{4,9}\/[^\s<>"']+/gi) || [])
        .some(candidate => candidate.toLowerCase() === doi.toLowerCase())).map(([label]) => label);
    }
    if (/^cve \d{4} \d{4,}$/.test(normalized)) {
      const exact = normalized;
      return entries.filter(([, value]) => (' ' + value + ' ').includes(' ' + exact + ' ')).map(([label]) => label);
    }
    return words.every(word => entries.some(([, value]) => value.includes(word)))
      ? entries.filter(([, value]) => words.some(word => value.includes(word))).map(([label]) => label) : [];
  },
  results(records, query) {
    const normalized = this.normalize(query);
    return records.map(record => {
      const reasons = this.match(record.fields, query);
      const title = this.normalize(record.title);
      const exactIdentifier = [record.fields.Identifier, record.fields.DOI]
        .filter(Boolean).some(value => this.normalize(value) === normalized);
      const exactFamily = String(record.fields['Model family'] || '').split(' · ')
        .some(name => this.normalize(name) === normalized);
      const rank = exactIdentifier ? 0
        : title === normalized ? 1
        : title.startsWith(normalized + ' ') ? 2
        : exactFamily ? 3
        : (' ' + title + ' ').includes(' ' + normalized + ' ') ? 4 : 5;
      return {...record, reasons, rank};
    }).filter(record => record.reasons.length).sort((a, b) => a.rank - b.rank);
  },
  collections(discoveries, vulnerabilities, models, progress, citations = {}) {
    const familyNames = new Map();
    for (const family of models.families) {
      for (const id of family.discoveries || []) {
        if (!familyNames.has(id)) familyNames.set(id, []);
        familyNames.get(id).push(family.name);
      }
    }
    const scientific = discoveries.map(r => ({id:r.id, title:r.title, href:'share/' + encodeURIComponent(r.id) + '.html',
      explorer:'index.html#discovery=' + encodeURIComponent(r.id),
      fields:{'Organization aliases':globalThis.CatalogEntities?.organization(r.organization).label, Title:r.title, Identifier:r.id, Summary:r.summary, Field:r.field, Organization:r.organization, Technology:r.ai_technology,
        DOI:citations.records?.[r.id]?.doi, 'Model family':(familyNames.get(r.id) || []).join(' · '),
        Sources:[r.source_url, r.paper_url, ...(r.evidence?.evidence_urls || [])].join(' '),
        'AI contribution':r.evidence?.ai_role, 'Test and limits':[r.evidence?.tested, r.evidence?.unknown].join(' ')}}));
    const cases = vulnerabilities.map(r => ({id:r.id, title:r.title, href:'profiles/security-' + encodeURIComponent(r.id) + '.html',
      explorer:'security.html#' + encodeURIComponent(r.id),
      fields:{Title:r.title, Identifier:[r.id,...r.cves].join(' '), Summary:r.summary, Product:r.product,
        'AI system':r.ai_system, 'Source-attributed vendor group':globalThis.CatalogEntities?.system(r.ai_system).label, 'AI contribution':r.ai_role, Organization:r.organization,
        Sources:[r.source_url,r.ai_source_url,r.advisory_url,...(r.evidence_urls || [])].join(' ')}}));
    const releases = models.models.map((r, i) => ({id:String(i), title:r.name,
      href:'models.html?q=' + encodeURIComponent(r.name), fields:{Name:r.name, Organization:r.organization, Family:r.family, Domain:r.domain, Source:r.link}}));
    const activeIds = new Set(discoveries.map(r => r.id));
    const families = models.families.map(r => {
      const interactive = 'profile.html?family=' + encodeURIComponent(r.id);
      const hasStatic = (r.discoveries || []).some(id => activeIds.has(id));
      return {id:r.id, title:r.name, href:hasStatic ? 'profiles/family-' + encodeURIComponent(r.id) + '.html' : interactive,
        explorer:hasStatic ? interactive : null, fields:{Name:r.name, Identifier:r.id}};
    });
    const inventory = (progress?.models || []).map(r => ({id:r.id, title:r.name,
      href:'model-progress.html?model=' + encodeURIComponent(r.id),
      fields:{Name:r.name, Identifier:r.id, Lab:r.lab, Organization:r.organization,
        'Evaluation configuration':(r.variants || []).join(' '), 'Catalog labels':(r.catalog_releases || []).map(x => x.name).join(' ')}}));
    return [
      {title:'Scientific discoveries',unit:'catalog entries',records:scientific},
      {title:'Vulnerability cases',unit:'cases, which may have multiple or no CVEs',records:cases},
      {title:'Model inventory',unit:'source entries; overlapping labels may remain',records:inventory},
      {title:'Notable model releases',unit:'releases in the selected Epoch import',records:releases},
      {title:'Model families',unit:'families; name links do not establish exact-version use',records:families}
    ];
  }
};

if (typeof document !== 'undefined') {
  const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const query = document.getElementById('search-query'), output = document.getElementById('search-results');
  let collections = null;
  const render = () => {
    if (!collections) return;
    const value = query.value.trim(), params = new URLSearchParams();
    if (value) params.set('q', value);
    history.replaceState(null, '', location.pathname + (params.size ? '?' + params : ''));
    if (!CatalogSearch.normalize(value)) {
      output.replaceChildren();
      document.getElementById('search-status').textContent = 'Enter a query to search. ' + collections.map(g => `${g.records.length} ${g.title.toLowerCase()} available`).join(' · ') + '.';
      return;
    }
    output.innerHTML = collections.map((group, i) => {
      const matches = CatalogSearch.results(group.records, value);
      return `<section class="search-group" aria-labelledby="search-group-${i}"><h3 id="search-group-${i}">${esc(group.title)} · ${matches.length} of ${group.records.length}</h3><p class="nota">Counting unit: ${esc(group.unit)}.</p>` +
        (matches.length ? `<ol>${matches.map(r => `<li><a href="${esc(r.href)}">${esc(r.title)}</a><p class="descr">Matched: ${esc(r.reasons.join(' · '))}${r.explorer ? ` · <a href="${esc(r.explorer)}" aria-label="Open in explorer: ${esc(r.title)}">Open in explorer</a>` : ''}</p></li>`).join('')}</ol>` : '<p>No matching records in this collection.</p>') + '</section>';
    }).join('');
    document.getElementById('search-status').textContent = `Results for “${value}”. Counts are separate; model collections can overlap and must not be added together.`;
  };
  query.value = new URLSearchParams(location.search).get('q') || '';
  document.getElementById('global-search').addEventListener('submit', e => {e.preventDefault(); render();});
  document.getElementById('clear-search').addEventListener('click', () => {query.value = ''; render(); query.focus();});
  CatalogData.run(['discoveries','vulnerabilities','models','model-progress','entity-aliases','citations'], loaded => {
    CatalogEntities.configure(loaded.data['entity-aliases']);
    collections = CatalogSearch.collections(loaded.data.discoveries, loaded.data.vulnerabilities, loaded.data.models,
      loaded.data['model-progress'], loaded.data.citations);
    render();
  }, {clear:() => {collections = null; output.replaceChildren();}, controls:'#global-search button, #clear-search'});
}
