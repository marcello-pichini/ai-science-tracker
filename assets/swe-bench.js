/* Independent source runs: no name-based joins or changes to ECI comparisons. */
(() => {
  const el = id => document.getElementById(id);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const number = value => value == null ? 'Not reported' : Number(value).toLocaleString('en-GB', {maximumFractionDigits: 2});
  const displayDate = value => new Date(value + 'T00:00:00Z').toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
  let data;
  function render() {
    const version = el('swe-version').value, query = el('swe-search').value.trim().toLowerCase();
    const rows = data.records.filter(r => (version === 'all' || r.agent_version === version) && `${r.name} ${r.organization || ''} ${r.settings.join(' ')}`.toLowerCase().includes(query))
      .sort((a,b) => b.score - a.score || a.id.localeCompare(b.id));
    el('swe-count').textContent = `${rows.length} of ${data.records.length} evaluation runs shown. Snapshot retrieved ${displayDate(data.fetched_on)}; latest included evaluation ${displayDate(data.records.map(r => r.evaluation_date).sort().at(-1))}.`;
    el('swe-results').innerHTML = `<thead><tr><th>Model / evaluation settings</th><th>Agent version</th><th>Resolved</th><th>Mean cost / task</th><th>Evaluation date</th></tr></thead><tbody>${rows.map(r => `<tr><th scope="row">${escape(r.name)}<small>${escape(r.organization || 'Organization not reported')}</small><details class="source-details"><summary>Source configuration</summary><p>${escape(r.id)}</p><ul>${r.settings.map(s => `<li>${escape(s)}</li>`).join('')}</ul><p>Reasoning effort: ${escape(r.reasoning_effort || 'Not reported')}. Source team check: ${r.source_checked === true ? 'Marked checked by source' : r.source_checked === false ? 'Marked unchecked by source' : 'Not stated'}. <a href="https://www.swebench.com/">Official leaderboard</a></p></details></th><td>${escape(r.agent_version)}</td><td>${number(r.score)}%</td><td>${r.mean_cost_usd == null ? 'Not reported' : '$' + number(r.mean_cost_usd)}</td><td>${displayDate(r.evaluation_date)}</td></tr>`).join('') || '<tr><td colspan="5">No evaluation runs match these filters.</td></tr>'}</tbody>`;
  }
  el('swe-version').addEventListener('change', render);
  el('swe-search').addEventListener('input', render);
  fetch('data/swe-bench.json').then(r => {if (!r.ok) throw Error('SWE-bench export unavailable'); return r.json();}).then(value => {
    if (!value.records?.length) throw Error('SWE-bench export is empty');
    data = value;
    const versions = [...new Set(data.records.map(r => r.agent_version))].sort((a,b) => b.localeCompare(a, 'en', {numeric:true}));
    el('swe-version').innerHTML = versions.map(v => `<option value="${escape(v)}">mini-SWE-agent ${escape(v)}</option>`).join('') + '<option value="all">All versions (settings differ)</option>';
    el('swe-version').disabled = false; el('swe-search').disabled = false;
    render();
  }).catch(error => {
    el('swe-count').textContent = 'SWE-bench data could not load. Use the attributed JSON download or reload to retry.';
    el('swe-results').innerHTML = '';
    console.error(error);
  });
})();
