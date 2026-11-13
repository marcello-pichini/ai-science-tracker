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
  entryUrl(record) {
    return 'https://marcello-pichini.github.io/ai-science-tracker/index.html#discovery=' + encodeURIComponent(record.id);
  },
  // Plain catalog reference; deliberately carries no authors, DOI or publisher, which the catalog does not hold.
  reference(record, accessed) {
    const date = new Date(record.publication_date + 'T12:00:00').toLocaleDateString('en-GB', {day:'numeric', month:'short', year:'numeric'});
    return `${record.title}. ${record.organization}, announced ${date}. Source: ${record.source_url}. Catalog entry: AI Science Tracker, ${this.entryUrl(record)} (accessed ${accessed}).`;
  },
  csvColumns: ['id', 'title', 'summary', 'field', 'ai_technology', 'organization', 'source_url', 'source_type', 'publication_date', 'added_date', 'verification_status', 'paper_url', 'impact', 'validation', 'novelty', 'catalog_entry_url'],
  // Cells starting with = + - @ get a leading apostrophe so spreadsheets do not run them as formulas.
  toCsv(records) {
    const cell = value => {
      let text = String(value ?? '');
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    };
    const rows = records.map(r => [r.id, r.title, r.summary, r.field, r.ai_technology, r.organization, r.source_url, r.source_type,
      r.publication_date, r.added_date, r.verification_status, r.paper_url, r.relevance.impact, r.relevance.validation, r.relevance.novelty, this.entryUrl(r)]);
    return [this.csvColumns, ...rows].map(row => row.map(cell).join(',')).join('\r\n') + '\r\n';
  },
  fieldYear(records) {
    const cells = {}, fields = new Set(), years = new Set();
    for (const record of records) {
      const field = record.field, year = record.publication_date.slice(0, 4);
      fields.add(field); years.add(year);
      cells[field + '|' + year] = (cells[field + '|' + year] || 0) + 1;
    }
    return {cells, fields:[...fields].sort(), years:[...years].sort()};
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
