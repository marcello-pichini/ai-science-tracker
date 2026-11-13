/* Shared source explanations, correction drafts and descriptive catalog metrics. */
globalThis.CatalogUI = {
  sourceDetails(record) {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const checked = record.verification_status === 'verified';
    return `<details class="source-details"><summary>${checked ? 'Source checked' : 'Needs source check'} · editorial details</summary>
      <p>${checked ? 'The source page was checked against this entry.' : 'The source has not been fully checked or contains conflicting information.'} Independent confirmation is not assessed by this label.</p>
      <p>Source type: ${esc(record.source_type)}. Paper: ${record.paper_url ? 'linked separately' : 'not linked in this catalog; this does not mean no paper exists'}.</p>
      <p>Editorial assessment: Impact ${esc(record.relevance.impact)}/5 · Validation ${esc(record.relevance.validation)}/5 · Novelty ${esc(record.relevance.novelty)}/5. These are editorial judgments, not an evidence grade. <a href="methodology.html">Scoring criteria</a>.</p></details>`;
  },
  correctionUrl(record) {
    const query = new URLSearchParams({template:'correction.yml', title:`[Correction] ${record.id}`, record_id:record.id,
      entry:'https://marcello-pichini.github.io/ai-science-tracker/index.html#discovery=' + encodeURIComponent(record.id), source:record.source_url});
    return 'https://github.com/marcello-pichini/ai-science-tracker/issues/new?' + query;
  },
  annualStats(records) {
    const years = {};
    for (const record of records) {
      const year = record.publication_date.slice(0, 4), r = record.relevance;
      const group = years[year] ||= {count:0, total:0};
      group.count++;
      group.total += Math.round((r.impact + r.validation + r.novelty) / 3 * 20);
    }
    return Object.keys(years).sort().map(year => ({year, count:years[year].count, mean:Math.round(years[year].total / years[year].count)}));
  }
};

// Print all evidence details, then restore the reader's open/closed choices.
if (typeof window !== 'undefined') {
  let closedBeforePrint = [];
  window.addEventListener('beforeprint', () => {
    closedBeforePrint = [...document.querySelectorAll('.source-details:not([open])')];
    closedBeforePrint.forEach(details => { details.open = true; });
  });
  window.addEventListener('afterprint', () => {
    closedBeforePrint.forEach(details => { details.open = false; });
    closedBeforePrint = [];
  });
}
