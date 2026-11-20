/* Shared source explanations, correction drafts and descriptive catalog metrics. */
globalThis.AST_t ||= (en, vars) => {
  const table = globalThis.AST_MESSAGES;
  let s = table && Object.prototype.hasOwnProperty.call(table, en) && typeof table[en] === 'string' ? table[en] : en;
  if (vars) for (const key of Object.keys(vars)) s = s.split('{' + key + '}').join(String(vars[key]));
  return s;
};
globalThis.CatalogUI = {
  // Semicolons separate organizations; commas and conjunctions can belong to a name.
  leadOrganization(name) { return name.split(';')[0].trim(); },
  messages: null,
  dateLocale: 'en-GB',
  t(en, vars) {
    const table = this.messages || globalThis.AST_MESSAGES;
    let s = table && Object.prototype.hasOwnProperty.call(table, en) && typeof table[en] === 'string' ? table[en] : en;
    if (vars) for (const key of Object.keys(vars)) s = s.split('{' + key + '}').join(String(vars[key]));
    return s;
  },
  sitePath(path) {
    const root = globalThis.AST_SITE_ROOT || '';
    return /^(share|profiles|data|api|og)\//.test(path) ? root + path : path;
  },
  // Validation follows the catalog test category; definitions and precedence are in methodology.html.
  testLevels: {'not reported':1, 'retrospective or benchmark':2, 'direct test':3, 'prospective or independent check':4, 'replication or operational use':5},
  // Relevance 20-100: mean of the three subscores x 20, but never more than one level above the evidence (validation + 1) x 20.
  score(record) {
    const r = record.relevance;
    return Math.min(Math.round((r.impact + r.validation + r.novelty) / 3 * 20), (r.validation + 1) * 20);
  },
  citationLine(record) {
    const c = record.citation;
    if (!c || !Number.isSafeInteger(c.cited_by) || c.cited_by < 0 ||
        !Number.isFinite(c.percentile) || c.percentile < 0 || c.percentile > 100 ||
        typeof c.top_1 !== 'boolean' || typeof c.top_10 !== 'boolean') return '';
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const band = c.top_1 ? this.t('in the top 1%') : c.top_10 ? this.t('in the top 10%') : this.t('at percentile {n}', {n: Math.round(c.percentile)});
    const checked = /^\d{4}-\d{2}-\d{2}$/.test(c.checked || '') && !Number.isNaN(Date.parse(c.checked));
    const asOf = checked ? this.t('as of {date}', {date: new Intl.DateTimeFormat(this.dateLocale || 'en-GB', {day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}).format(new Date(c.checked + 'T12:00:00Z'))}) : this.t('snapshot date unavailable');
    const source = /^10\.\d{4,9}\/\S+$/.test(c.doi || '')
      ? `<a href="${esc('https://api.openalex.org/works/https://doi.org/' + encodeURI(c.doi))}" rel="noopener">${this.t('OpenAlex work metrics')}</a>` : 'OpenAlex';
    return `<p>${this.t('Citations:')} ${band} ${this.t('of works of the same type, year and subfield')} (${source}, ${esc(c.cited_by)} ${this.t('citations')}; ${asOf}). ${this.t('Attention, not a measure of correctness; not part of the score.')}</p>`;
  },
  sourceStatus(record) {
    return record.verification_status === 'verified' ? this.t('Source checked') : this.t('Needs source check');
  },
  sourceBadge(record) {
    return `<p class="source-status"><b>${this.t('Source check:')}</b> ${this.sourceStatus(record)}. <span>${this.t('Not independent scientific confirmation.')}</span></p>`;
  },
  reviewCoverage(records) {
    return {total:records.length, annotated:records.filter(r => r.evidence).length,
      reviewed:records.filter(r => r.source_review?.date && r.source_review?.scope).length,
      checked:records.filter(r => r.verification_status === 'verified').length};
  },
  readingContext(record) {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const e = record.evidence;
    if (!e) return `<p class="evidence-strip">${this.t('AI contribution, test and limitation are not annotated in this catalog; this does not establish their absence from the source.')}</p>`;
    const rows = [[this.t('AI contribution'), this.evidenceValue(record, 'ai_role')],
      ...(e.tested && e.tested === record.summary ? [] : [[this.t('Test and result'), this.evidenceValue(record, 'tested')]]),
      [this.t('Limitation / still unknown'), this.evidenceValue(record, 'unknown')]];
    return `<dl class="reading-context">${rows.map(([label,value]) => `<div><dt>${label}</dt><dd>${esc(value)}</dd></div>`).join('')}</dl>`;
  },
  sourceDetails(record) {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const checked = record.verification_status === 'verified';
    const status = checked ? this.t('Source checked') : this.t('Needs source check');
    const checkedSentence = checked ? this.t('The source page was checked against this entry.') : this.t('The source has not been fully checked or contains conflicting information.');
    const review = record.source_review
      ? `${this.t('Review date:')} ${esc(this.contextDate(record.source_review.date))}. ${this.t('Review scope:')} ${esc(record.source_review.scope)}.`
      : this.t('Review scope and date are not recorded; source checked does not establish full-text review.');
    return `${this.evidenceSummary(record)}${this.readingContext(record)}${record.evidence ? `<details class="source-details"><summary>${this.t('Evidence sources and annotation context')}</summary>${this.evidenceBlock(record, false)}</details>` : ''}<details class="source-details"><summary>${status} · ${this.t('editorial details')}</summary>
      <p>${checkedSentence} ${this.t('Independent confirmation is not assessed by this label.')}</p>
      <p>${this.t('Source type:')} ${esc(record.source_type)}. ${this.t('Paper:')} ${record.paper_url ? this.t('linked separately') : this.t('not linked in this catalog; this does not mean no paper exists')}.</p>
      <p>${review}</p>
      ${this.citationLine(record)}${!record.follow_up?.length && !record.relationships?.length && !record.follow_up_review ? this.historyAbsence() : ''}
      <p>${this.t('Editorial assessment:')} ${this.t('Impact')} ${esc(record.relevance.impact)}/5 · ${this.t('Validation')} ${esc(record.relevance.validation)}/5 · ${this.t('Novelty')} ${esc(record.relevance.novelty)}/5. ${this.t('Impact and novelty are editorial judgments; validation follows the annotated test type where one exists. Not an evidence grade.')} <a href="methodology.html">${this.t('Scoring criteria')}</a>.</p></details>${this.historyBlock(record)}`;
  },
  // Source descriptions stay separate from the editorial test category that sets validation.
  evidenceBlock(record, includeRows = true) {
    const e = record.evidence;
    if (!e) return '';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const rows = [['Publication status', e.publication_status], ['Test type', e.test_type], ['Tested', e.tested], ['Still unknown', e.unknown], ['AI role', e.ai_role]]
      .map(([label, value]) => `<li><b>${this.t(label)}:</b> ${esc(label === 'Publication status' || label === 'Test type' ? this.t(String(value ?? '')) : value)}</li>`).join('');
    const links = (e.evidence_urls || []).filter(url => {
      try { return /^https?:\/\//i.test(url) && ['http:', 'https:'].includes(new URL(url).protocol); } catch { return false; }
    }).map(url => `<a href="${esc(url)}" rel="noopener">${esc(url)}</a>`);
    const legacy = [e.publication_status, e.tested, e.unknown, e.ai_role].some(value => /^Not reported\.?$/.test(value));
    return `<p><b>${this.t('Evidence context')}</b> ${this.t('(descriptions follow the cited sources; test type is a catalog classification):')}</p>${includeRows ? `<ul class="evidence-context">${rows}</ul>` : ''}${links.length ? `<p>${this.t('Evidence sources:')} ${links.join(' · ')}</p>` : ''}${legacy ? `<p>${this.t('The legacy label “Not reported” does not distinguish information absent from reviewed material from information not assessed. It is not a scientific finding of absence.')}</p>` : ''}`;
  },
  evidenceValue(record, key) {
    const value = record.evidence?.[key];
    if (!value) return this.t('Not annotated in this catalog');
    if (key === 'test_type' && value === 'not reported') return this.t('Test context unspecified in annotation');
    if (key === 'publication_status' && value === 'Not reported') return this.t('Publication status unspecified in annotation');
    if (key === 'test_type' || key === 'publication_status') return this.t(String(value));
    return value;
  },
  evidenceSummary(record) {
    const esc = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    return `<p class="evidence-strip"><b>${this.t('Publication:')}</b> ${esc(this.evidenceValue(record, 'publication_status'))} · <b>${this.t('Test context:')}</b> ${esc(this.evidenceValue(record, 'test_type'))}. ${this.t('Catalog categories, not an evidence grade.')}</p>`;
  },
  selectionCounts(records, key) {
    const counts = {};
    records.forEach(record => { const value = this.evidenceValue(record, key); counts[value] = (counts[value] || 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  },
  contextDate(value) {
    if (!value) return 'Date unknown';
    if (/^\d{4}$/.test(value)) return value;
    const options = value.length === 7 ? {month:'short', year:'numeric'} : {day:'numeric', month:'short', year:'numeric'};
    return new Intl.DateTimeFormat(this.dateLocale || 'en-GB', {...options, timeZone:'UTC'}).format(new Date(value + (value.length === 7 ? '-01' : '') + 'T12:00:00Z'));
  },
  historyAbsence() {
    return `<p>${this.t('No follow-up recorded; this is not a claim that no follow-up exists. Follow-up review scope and date are not recorded. No source-supported relationships recorded.')}</p>`;
  },
  historyBlock(record) {
    if (!record.follow_up?.length && !record.relationships?.length && !record.follow_up_review) return '';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const sources = urls => (urls || []).filter(url => { try { return /^https?:\/\//i.test(url) && ['http:', 'https:'].includes(new URL(url).protocol); } catch { return false; } }).map(url => `<a href="${esc(url)}" rel="noopener">${this.t('Source')}</a>`).join(' · ');
    const events = (record.follow_up || []).map(event => `<li id="event-${esc(record.id)}-${esc(event.id)}"><b>${esc(event.kind)}</b> · ${esc(this.contextDate(event.date))}: ${esc(event.note)} ${sources(event.source_urls)}. ${this.t('Recorded {date}.', {date: esc(this.contextDate(event.recorded_date))})}</li>`).join('');
    const review = record.follow_up_review;
    const relationships = (record.relationships || []).map(link => `<li><a href="${this.sitePath('share/' + encodeURIComponent(link.target_id) + '.html')}">${esc(link.target_id)}</a> · ${esc(link.type)}: ${esc(link.reason)} ${sources(link.source_urls)}</li>`).join('');
    return `<details class="source-details"><summary>${this.t('Follow-up and relationships')}</summary>${events ? `<ul>${events}</ul>` : `<p>${this.t('No follow-up recorded; this is not a claim that no follow-up exists.')}</p>`}${review ? `<p>${this.t('Follow-up checked {date} within scope: {scope}.', {date: esc(this.contextDate(review.date)), scope: esc(review.scope)})}</p>` : `<p>${this.t('Follow-up review scope and date are not recorded.')}</p>`}${relationships ? `<p>${this.t('Directed relationships from this entry; they do not merge catalog counts.')}</p><ul>${relationships}</ul>` : `<p>${this.t('No source-supported relationships recorded.')}</p>`}</details>`;
  },
  correctionUrl(record) {
    const query = new URLSearchParams({template:'correction.yml', title:`[Correction] ${record.id}`, record_id:record.id,
      entry:'https://aisciencetracker.org/share/' + encodeURIComponent(record.id) + '.html', source:record.source_url});
    return 'https://github.com/marcello-pichini/ai-science-tracker/issues/new?' + query;
  },
  entryUrl(record) {
    return 'https://aisciencetracker.org/share/' + encodeURIComponent(record.id) + '.html';
  },
  // Plain catalog reference; deliberately carries no authors, DOI or publisher, which the catalog does not hold.
  reference(record, accessed) {
    const date = new Date(record.publication_date + 'T12:00:00').toLocaleDateString(this.dateLocale || 'en-GB', {day:'numeric', month:'short', year:'numeric'});
    return `${record.title}. ${record.organization}, ${this.t('announced')} ${date}. ${this.t('Source:')} ${record.source_url}. ${this.t('Catalog entry:')} AI Science Tracker, ${this.entryUrl(record)} (${this.t('accessed')} ${accessed}).`;
  },
  csvColumns: ['id', 'title', 'summary', 'field', 'ai_technology', 'organization', 'source_url', 'source_type', 'publication_date', 'added_date', 'verification_status', 'paper_url', 'impact', 'validation', 'novelty', 'catalog_entry_url', 'publication_status', 'test_type', 'tested', 'unknown', 'ai_role', 'evidence_urls', 'source_review', 'follow_up', 'follow_up_review', 'relationships'],
  // Cells starting with = + - @ get a leading apostrophe so spreadsheets do not run them as formulas.
  toCsv(records) {
    const cell = value => {
      let text = String(value ?? '');
      if (/^[=+\-@\t\r]/.test(text)) text = "'" + text;
      return /[",\n\r]/.test(text) ? '"' + text.replace(/"/g, '""') + '"' : text;
    };
    const rows = records.map(r => [r.id, r.title, r.summary, r.field, r.ai_technology, r.organization, r.source_url, r.source_type,
      r.publication_date, r.added_date, r.verification_status, r.paper_url, r.relevance.impact, r.relevance.validation, r.relevance.novelty, this.entryUrl(r), ...['publication_status', 'test_type', 'tested', 'unknown', 'ai_role'].map(k => r.evidence?.[k] || ''), JSON.stringify(r.evidence?.evidence_urls || []), ...['source_review', 'follow_up', 'follow_up_review', 'relationships'].map(k => JSON.stringify(r[k] ?? null))]);
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
  // Counts entries per source website (host without "www."); top is the number of busiest hosts to total.
  sourceConcentration(records, top = 8) {
    const hosts = {};
    for (const record of records) {
      let host = '';
      try { host = new URL(record.source_url).hostname.replace(/^www\./, ''); } catch { host = ''; }
      if (host) hosts[host] = (hosts[host] || 0) + 1;
    }
    const counts = Object.values(hosts).sort((a, b) => b - a);
    return {top: Math.min(top, counts.length), entries: counts.slice(0, top).reduce((sum, n) => sum + n, 0), total: records.length, websites: counts.length};
  },
  focusEntry(element, scrollOptions) {
    if (!element) return;
    const target = element.querySelector('h3') || element;
    target.setAttribute('tabindex', '-1');
    target.focus({preventScroll:true});
    element.scrollIntoView(scrollOptions);
  },
  // Keep keyboard focus on the equivalent control when a chart is redrawn.
  restoreChartFocus(container, control) {
    const match = [...container.querySelectorAll(control.tagName)].find(node =>
      Object.keys(control.dataset).every(key => node.dataset[key] === control.dataset[key]));
    match?.focus({preventScroll:true});
  },
  chartInteraction(svg, points, {describe, open, showTip, hideTip, penalty = () => 0, radius = 24}) {
    const status = document.createElement('p');
    status.className = 'vis-nascosto'; status.setAttribute('role', 'status'); status.setAttribute('aria-atomic', 'true');
    const chooser = document.createElement('div'); chooser.className = 'chart-choice'; chooser.hidden = true;
    const label = document.createElement('label'), select = document.createElement('select'), button = document.createElement('button');
    const caption = document.createElement('span');
    label.append(caption, select); button.type = 'button'; button.textContent = this.t('Open selected entry');
    chooser.append(label, button); svg.after(status, chooser);
    const order = points.map((_, i) => i).sort((a, b) => points[a].x - points[b].x);
    let current = -1;
    const clear = () => {
      svg.querySelector('.su')?.classList.remove('su'); current = -1; hideTip(); status.textContent = '';
    };
    const choose = (i, x, y) => {
      if (i < 0) return;
      const lines = describe(points[i]);
      if (i !== current) {
        svg.querySelector('.su')?.classList.remove('su');
        svg.querySelector(`[data-i="${i}"]`).classList.add('su'); current = i;
        status.textContent = this.t('{n} of {total}. {detail}', {n: order.indexOf(i) + 1, total: points.length, detail: lines.join('. ')});
      }
      if (x == null) {
        const rect = svg.querySelector(`[data-i="${i}"]`).getBoundingClientRect(); x = rect.left + rect.width / 2; y = rect.top;
      }
      showTip(lines, x, y);
    };
    const nearest = e => {
      const p = svg.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
      const v = p.matrixTransform(svg.getScreenCTM().inverse());
      let best = -1, distance = Infinity;
      points.forEach((point, i) => {
        const d = (point.y == null ? Math.abs(point.x - v.x) : Math.hypot(point.x - v.x, point.y - v.y)) + penalty(point);
        if (d < distance) { distance = d; best = i; }
      });
      return distance < radius ? best : -1;
    };
    svg.addEventListener('pointermove', e => { const i = nearest(e); if (i >= 0) choose(i, e.clientX, e.clientY); else clear(); });
    svg.addEventListener('pointerleave', hideTip); svg.addEventListener('blur', hideTip);
    svg.addEventListener('click', e => {
      const i = nearest(e); if (i < 0) return;
      choose(i, e.clientX, e.clientY);
      // Nearby marks share a chooser within 8 CSS pixels; dates keep their true positions.
      const matrix = svg.getScreenCTM(), screen = points.map(point => {
        const p = svg.createSVGPoint(); p.x = point.x; p.y = point.y ?? 0; return p.matrixTransform(matrix);
      });
      const group = order.filter(j => (points[i].y == null && points[i].date && points[j].date === points[i].date) ||
        Math.hypot(screen[j].x - screen[i].x, screen[j].y - screen[i].y) <= 8);
      if (group.length === 1) { chooser.hidden = true; open(points[i]); return; }
      const multipleDates = new Set(group.map(j => points[j].date)).size > 1;
      caption.textContent = multipleDates || !points[i].date ? this.t('{n} nearby entries. Choose an entry ', {n: group.length}) : this.t('{date}: {n} entries. Choose an entry ', {date: points[i].date, n: group.length});
      select.replaceChildren(...group.map(j => {
        const option = document.createElement('option'); option.value = j;
        option.textContent = describe(points[j])[0] + (multipleDates && points[j].date ? ` — ${points[j].date}` : ''); return option;
      }));
      select.value = String(i); chooser.hidden = false; select.focus({preventScroll:true});
    });
    select.addEventListener('change', () => choose(+select.value));
    button.addEventListener('click', () => open(points[+select.value]));
    chooser.addEventListener('keydown', e => { if (e.key === 'Escape') { e.preventDefault(); chooser.hidden = true; clear(); svg.focus({preventScroll:true}); } });
    svg.addEventListener('keydown', e => {
      if (['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key) && order.length) {
        e.preventDefault(); chooser.hidden = true;
        const pos = current < 0 ? (e.key === 'ArrowLeft' ? order.length : -1) : order.indexOf(current);
        const n = e.key === 'Home' ? 0 : e.key === 'End' ? order.length - 1 : Math.max(0, Math.min(order.length - 1, pos + (e.key === 'ArrowLeft' ? -1 : 1)));
        choose(order[n]);
      } else if ((e.key === 'Enter' || e.key === ' ') && current >= 0) { e.preventDefault(); open(points[current]); }
      else if (e.key === 'Escape') { chooser.hidden = true; clear(); }
    });
  },
  annualStats(records) {
    const years = {};
    for (const record of records) {
      const year = record.publication_date.slice(0, 4), r = record.relevance;
      const group = years[year] ||= {count:0, total:0};
      group.count++;
      group.total += this.score(record);
    }
    return Object.keys(years).sort().map(year => ({year, count:years[year].count, mean:Math.round(years[year].total / years[year].count)}));
  }
};

// Print all evidence details, then restore the reader's open/closed choices.
if (typeof window !== 'undefined') {
  let closedBeforePrint = [];
  window.addEventListener('beforeprint', () => {
    CatalogUI.beforePrint?.();
    closedBeforePrint = [...document.querySelectorAll('.source-details:not([open])')];
    closedBeforePrint.forEach(details => { details.open = true; });
  });
  window.addEventListener('afterprint', () => {
    closedBeforePrint.forEach(details => { details.open = false; });
    closedBeforePrint = [];
    CatalogUI.afterPrint?.();
  });
}
