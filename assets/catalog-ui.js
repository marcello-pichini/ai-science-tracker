/* Shared source explanations, correction drafts and descriptive catalog metrics. */
globalThis.CatalogUI = {
  // Validation level of each source-stated test type (methodology.html, "Evidence level").
  testLevels: {'not reported':1, 'retrospective or benchmark':2, 'direct test':3, 'prospective or independent check':4, 'replication or operational use':5},
  // Relevance 20-100: mean of the three subscores x 20, but never more than one level above the evidence (validation + 1) x 20.
  score(record) {
    const r = record.relevance;
    return Math.min(Math.round((r.impact + r.validation + r.novelty) / 3 * 20), (r.validation + 1) * 20);
  },
  citationLine(record) {
    const c = record.citation;
    if (!c) return '';
    const band = c.top_1 ? 'in the top 1%' : c.top_10 ? 'in the top 10%' : `at percentile ${Math.round(c.percentile)}`;
    return `<p>Citations: ${band} of works of the same type, year and subfield (OpenAlex, ${c.cited_by} citations). Attention, not a measure of correctness; not part of the score.</p>`;
  },
  sourceDetails(record) {
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const checked = record.verification_status === 'verified';
    return `<details class="source-details"><summary>${checked ? 'Source checked' : 'Needs source check'} · editorial details</summary>
      <p>${checked ? 'The source page was checked against this entry.' : 'The source has not been fully checked or contains conflicting information.'} Independent confirmation is not assessed by this label.</p>
      <p>Source type: ${esc(record.source_type)}. Paper: ${record.paper_url ? 'linked separately' : 'not linked in this catalog; this does not mean no paper exists'}.</p>
      ${this.evidenceBlock(record)}
      ${this.citationLine(record)}
      <p>Editorial assessment: Impact ${esc(record.relevance.impact)}/5 · Validation ${esc(record.relevance.validation)}/5 · Novelty ${esc(record.relevance.novelty)}/5. Impact and novelty are editorial judgments; validation follows the annotated test type where one exists. Not an evidence grade. <a href="methodology.html">Scoring criteria</a>.</p></details>`;
  },
  // Optional, source-stated context for pilot records; absent for most entries. It never feeds the relevance score.
  evidenceBlock(record) {
    const e = record.evidence;
    if (!e) return '';
    const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const rows = [['Publication status', e.publication_status], ['Test type', e.test_type], ['Tested', e.tested], ['Still unknown', e.unknown], ['AI role', e.ai_role]]
      .map(([label, value]) => `<li><b>${label}:</b> ${esc(value)}</li>`).join('');
    const links = (e.evidence_urls || []).filter(url => {
      try { return /^https?:\/\//i.test(url) && ['http:', 'https:'].includes(new URL(url).protocol); } catch { return false; }
    }).map(url => `<a href="${esc(url)}" rel="noopener">${esc(url)}</a>`);
    const legacy = [e.publication_status, e.tested, e.unknown, e.ai_role].includes('Not reported');
    return `<p><b>Evidence context</b> (pilot; stated by the cited sources, not an editorial judgment):</p><ul class="evidence-context">${rows}</ul>${links.length ? `<p>Evidence sources: ${links.join(' · ')}</p>` : ''}${legacy ? '<p>The legacy label “Not reported” does not distinguish information absent from reviewed material from information not assessed. It is not a scientific finding of absence.</p>' : ''}`;
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
    label.append(caption, select); button.type = 'button'; button.textContent = 'Open selected entry';
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
        status.textContent = `${order.indexOf(i) + 1} of ${points.length}. ${lines.join('. ')}`;
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
      caption.textContent = multipleDates || !points[i].date ? `${group.length} nearby entries. Choose an entry ` : `${points[i].date}: ${group.length} entries. Choose an entry `;
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
