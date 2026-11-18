/* Component metadata from the same exact-byte manifest used by collection views. */
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const displayDate = value => /^\d{4}-\d{2}-\d{2}(?:T.*)?$/.test(value || '') ? new Date(value.slice(0, 10) + 'T12:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}) : 'Not recorded';
  const dates = value => Object.entries(value).map(([key, date]) => `${esc(key.replaceAll('_', ' '))}: ${typeof date === 'object' && date ? displayDate(date.first) + '–' + displayDate(date.last) : displayDate(date)}`).join('<br>');
  CatalogData.run([], loaded => {
    const components = loaded.manifest.components;
    document.getElementById('dataset-components').innerHTML = Object.entries(components).filter(([id]) => !id.endsWith('-csv')).map(([id, component]) => {
      const csv = components[id + '-csv'];
      const source = component.source_urls.map((url, i) => `<a href="${esc(url)}">Source ${i + 1}</a>`).join(' · ') || 'Catalog source-label classification';
      const license = component.license_url ? `<a href="${esc(component.license_url)}">${esc(component.license)}</a>` : esc(component.license);
      const format = `<a href="${esc(component.path)}?v=${esc(component.sha256)}">${component.path.endsWith('.csv') ? 'CSV' : 'JSON'}</a>${csv ? ` · <a href="${esc(csv.path)}?v=${esc(csv.sha256)}">CSV</a>` : ''}`;
      const doi = component.catalog_doi ? `<a href="${esc(component.catalog_doi)}">Catalog DOI</a>` : 'No component-specific DOI assigned here';
      return `<tr><th scope="row">${esc(component.label)}</th><td>${component.count} ${esc(component.unit)}</td><td>${dates(component.dates)}<br>${source}</td><td>${format}<details class="source-details"><summary>SHA-256</summary><code>${esc(component.sha256)}</code>${csv ? `<p>CSV: <code>${esc(csv.sha256)}</code></p>` : ''}</details></td><td>${license}</td><td>${esc(component.coverage)}</td><td>${doi}<br><a href="${esc(component.release_url)}">Repository releases</a><small>${esc(component.doi_note)}</small></td></tr>`;
    }).join('');
  }, {clear:() => document.getElementById('dataset-components').replaceChildren()});
})();
