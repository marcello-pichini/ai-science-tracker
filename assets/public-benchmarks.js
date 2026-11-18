/* Independently licensed evidence: no cross-benchmark ranking or model-name joins. */
(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? 'Not reported' : Number(value).toLocaleString('en-GB', {maximumFractionDigits: 4});
  const date = value => value ? new Date(value.slice(0, 10) + 'T00:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}) : 'Not reported';
  const link = (url, label) => `<a href="${escape(url)}">${escape(label)}</a>`;
  let registry, current, serial = 0;
  const cache = new Map();
  function updateURL() {
    const url = new URL(location.href);
    url.searchParams.set('evidence', current.id);
    url.searchParams.set('evidence-slice', el('metric-slice').value);
    history.replaceState(null, '', url);
  }
  function details(record) {
    return `<details class="source-details"><summary>Configuration and source values</summary>${Object.entries(record.details).map(([key,value]) => `<p><b>${escape(key)}:</b> ${escape(typeof value === 'object' && value !== null ? JSON.stringify(value) : value ?? 'Not reported')}</p>`).join('')}<p>Record: ${escape(record.id)}. ${link(record.source_url, 'Original numerical source')}.</p></details>`;
  }
  function render() {
    if (!current) return;
    const group = el('metric-slice').value, query = el('metric-search').value.trim().toLowerCase();
    const rows = current.records.filter(r => r.comparison_group === group &&
      `${r.model} ${JSON.stringify(r.details)}`.toLowerCase().includes(query));
    const units = [...new Set(rows.map(r => r.unit))].join(', ');
    el('metric-count').textContent = `${rows.length} of ${current.records.length} source observations shown · ${units || 'no matching observations'} · retrieved ${date(current.retrieved_on)}. Source order retained; counts are not unique models.`;
    el('metric-results').innerHTML = `<caption>${escape(current.name)} — ${escape(group)}</caption><thead><tr><th scope="col">Exact source label and configuration</th><th scope="col">Source score</th><th scope="col">Source date</th></tr></thead><tbody>${rows.map(r => `<tr><th scope="row">${escape(r.model)}${details(r)}</th><td>${number(r.value)} ${escape(r.unit)}<small>${escape(r.direction)}</small></td><td>${date(r.date)}<small>${escape(r.date_basis)}</small></td></tr>`).join('') || '<tr><td colspan="3">No source observations match this search.</td></tr>'}</tbody>`;
  }
  async function selectSource(preferredSlice) {
    const request = ++serial, source = registry.sources.find(s => s.id === el('metric-source').value);
    current = null;
    el('metric-slice').disabled = true; el('metric-search').disabled = true;
    el('metric-results').innerHTML = '';
    el('metric-count').textContent = `Loading ${source.name}…`;
    el('metric-context').innerHTML = `<h3>${escape(source.name)}</h3><p>${escape(source.scope)}</p><p>${escape(source.selection)}</p><p><b>Maintenance:</b> ${escape(source.maintenance)}</p><p><b>Attribution:</b> ${escape(source.attribution)}. ${link(source.license_url, source.license)} · ${link(source.license_notice, 'Full license notice')} · ${link(source.path, 'Download this attributed JSON')} · ${link(source.source_url, 'Original source')}.</p>`;
    try {
      let data = cache.get(source.id);
      if (!data) {
        const response = await fetch(source.path + '?v=' + source.sha256.slice(0, 12));
        if (!response.ok) throw Error('Numerical source unavailable');
        const text = await response.text();
        const hash = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
        const actual = [...new Uint8Array(hash)].map(b => b.toString(16).padStart(2, '0')).join('');
        if (actual !== source.sha256) throw Error('Numerical source hash differs from registry');
        data = JSON.parse(text);
        if (data.id !== source.id || !data.records?.length || data.license !== source.license || data.records.length !== source.record_count) throw Error('Numerical snapshot does not match registry');
        cache.set(source.id, data);
      }
      if (request !== serial) return;
      current = data;
      const groups = [...new Set(data.records.map(r => r.comparison_group))];
      el('metric-slice').innerHTML = groups.map(group => `<option value="${escape(group)}">${escape(group)}</option>`).join('');
      if (groups.includes(preferredSlice)) el('metric-slice').value = preferredSlice;
      el('metric-slice').disabled = false; el('metric-search').disabled = false;
      el('metric-search').value = '';
      render();
    } catch (error) {
      if (request !== serial) return;
      el('metric-count').textContent = 'This numerical snapshot could not load. Use its attributed JSON download or select another source. Reload to retry.';
      el('metric-results').innerHTML = '';
    }
  }
  el('metric-source').addEventListener('change', async () => {await selectSource(); if (current) updateURL();});
  el('metric-slice').addEventListener('change', () => {render(); updateURL();});
  el('metric-search').addEventListener('input', render);
  fetch('data/benchmarks/index.json', {cache:'no-cache'}).then(response => {
    if (!response.ok) throw Error('Benchmark registry unavailable');
    return response.json();
  }).then(async data => {
    registry = data;
    if (!registry.sources?.length) throw Error('Benchmark registry is empty');
    el('metric-source').innerHTML = registry.sources.map(s => `<option value="${escape(s.id)}">${escape(s.name)}</option>`).join('');
    el('metric-source').disabled = false;
    el('metric-directory').innerHTML = registry.sources.map(s => `<details class="source-details"><summary>${escape(s.name)} · ${escape(s.license)} · ${s.record_count} observations</summary><p>${escape(s.scope)}</p><p><b>Selection:</b> ${escape(s.selection)}</p><p><b>Maintenance:</b> ${escape(s.maintenance)}</p><p><b>Credit:</b> ${escape(s.attribution)}. ${link(s.license_url, s.license)} · ${link(s.license_notice, 'License text')} · ${link(s.path, 'Attributed JSON')} · ${link(s.source_url, 'Original source')}.</p></details>`).join('');
    const params = new URLSearchParams(location.search);
    if (registry.sources.some(s => s.id === params.get('evidence'))) el('metric-source').value = params.get('evidence');
    await selectSource(params.get('evidence-slice'));
  }).catch(() => {
    el('metric-count').textContent = 'Additional metric sources could not load. Read the source and license directory or reload to retry.';
  });
})();
