/* Independently licensed evidence: no cross-benchmark ranking or model-name joins. */
(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? 'Not reported' : Number(value).toLocaleString('en-GB', {maximumFractionDigits: 4});
  const date = value => value ? new Date(value.slice(0, 10) + 'T00:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}) : 'Not reported';
  const link = (url, label) => `<a href="${escape(url)}">${escape(label)}</a>`;
  let registry = null, current = null;
  const snapshots = new Map();
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
    el('metric-count-summary').textContent = `${rows.length} source observations shown`;
    el('metric-results').innerHTML = `<caption>${escape(current.name)} — ${escape(group)}</caption><thead><tr><th scope="col">Exact source label and configuration</th><th scope="col">Source score</th><th scope="col">Source date</th></tr></thead><tbody>${rows.map(r => `<tr><th scope="row">${escape(r.model)}${details(r)}</th><td>${number(r.value)} ${escape(r.unit)}<small>${escape(r.direction)}</small></td><td>${date(r.date)}<small>${escape(r.date_basis)}</small></td></tr>`).join('') || '<tr><td colspan="3">No source observations match this search.</td></tr>'}</tbody>`;
  }
  function selectSource(preferredSlice, clearQuery = true) {
    if (!registry) return;
    const source = registry.sources.find(s => s.id === el('metric-source').value);
    current = snapshots.get(source.id);
    el('metric-context').innerHTML = `<h3>${escape(source.name)}</h3><p>${escape(source.scope)}</p><p>${escape(source.selection)}</p><p><b>Maintenance:</b> ${escape(source.maintenance)}</p><p><b>Attribution:</b> ${escape(source.attribution)}. ${link(source.license_url, source.license)} · ${link(source.license_notice, 'Full license notice')} · ${link(source.path + '?v=' + source.sha256, 'Download this attributed JSON')} · ${link(source.source_url, 'Original source')}.</p>`;
    const groups = [...new Set(current.records.map(r => r.comparison_group))];
    el('metric-slice').innerHTML = groups.map(group => `<option value="${escape(group)}">${escape(group)}</option>`).join('');
    el('metric-slice').value = groups.includes(preferredSlice) ? preferredSlice : groups[0];
    el('metric-slice').disabled = false; el('metric-search').disabled = false;
    if (clearQuery) el('metric-search').value = '';
    render();
  }
  el('metric-source').addEventListener('change', () => {selectSource(); if (current) updateURL();});
  el('metric-slice').addEventListener('change', () => {if (!current) return; render(); updateURL();});
  el('metric-search').addEventListener('input', render);
  globalThis.PublicBenchmarks = {reset() {
    registry = null; current = null; snapshots.clear();
    ['metric-source','metric-slice','metric-context','metric-count','metric-count-summary','metric-results','metric-directory'].forEach(id => el(id).replaceChildren());
    ['metric-source','metric-slice','metric-search'].forEach(id => {el(id).disabled = true;});
  }, init(loaded) {
    const data = loaded.data['benchmark-registry'];
    if (!data?.sources?.length) throw Error('Benchmark registry is empty');
    const next = new Map();
    for (const source of data.sources) {
      const id = 'benchmark-' + source.id, value = loaded.data[id];
      if (!value || value.id !== source.id || !value.records?.length || value.license !== source.license || value.records.length !== source.record_count || loaded.hashes[id] !== source.sha256) throw Error('Numerical snapshot does not match registry');
      next.set(source.id, value);
    }
    registry = data; snapshots.clear(); next.forEach((value, id) => snapshots.set(id, value));
    el('metric-source').innerHTML = registry.sources.map(s => `<option value="${escape(s.id)}">${escape(s.name)}</option>`).join('');
    el('metric-source').disabled = false;
    el('metric-directory').innerHTML = registry.sources.map(s => `<details class="source-details"><summary>${escape(s.name)} · ${escape(s.license)} · ${s.record_count} observations</summary><p>${escape(s.scope)}</p><p><b>Selection:</b> ${escape(s.selection)}</p><p><b>Maintenance:</b> ${escape(s.maintenance)}</p><p><b>Credit:</b> ${escape(s.attribution)}. ${link(s.license_url, s.license)} · ${link(s.license_notice, 'License text')} · ${link(s.path, 'Attributed JSON')} · ${link(s.source_url, 'Original source')}.</p></details>`).join('');
    const params = new URLSearchParams(location.search);
    el('metric-source').value = registry.sources.some(s => s.id === params.get('evidence')) ? params.get('evidence') : registry.sources[0].id;
    selectSource(params.get('evidence-slice'), false);
  }};
})();
