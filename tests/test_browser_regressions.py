"""Execute the page scripts against a small DOM for navigation and print lifecycle checks."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(name, hash = "", archived = [], staticPages = [], storage = new Map()) {
  const listeners = {}, elements = new Map(), timers = [];
  const classes = () => ({add() {}, remove() {}, toggle() {}});
  const node = id => ({id, classList:classes(), open:false, textContent:'', value:'', attributes:{}, handlers:{}, listenerCounts:{}, childNodes:[],
    append() {}, click() {}, remove() {}, replaceChildren(...children) {this.childNodes = children; this.innerHTML = ''; this.textContent = '';},
    setAttribute(k, v) {this.attributes[k] = v;}, addEventListener(k, fn) {this.handlers[k] = fn; this.listenerCounts[k] = (this.listenerCounts[k] || 0) + 1;},
    focus(options) {document.activeElement = this; this.focusOptions = options;},
    querySelectorAll() {return [];}, scrollIntoView(options) {this.scrollOptions = options;}, contains(child) {return child === this || child === this.heading;}, querySelector(selector) {return selector === 'h3' ? this.heading || null : null;}});
  const list = node('lista'); list.childNodes = [];
  Object.defineProperty(list, 'innerHTML', {set(html) {
    this.childNodes = [...html.matchAll(/<(?:article class="voce"|tr) id="([^"]+)"/g)].map(m => {
      const article = node(m[1]); article.details = node(); if (html.includes('<article')) article.heading = node(); return article;
    });
  }});
  list.replaceChildren = (...children) => {list.childNodes = children;};
  elements.set('lista', list);
  const document = {
    body:{append() {}}, createElement:() => node(),
    getElementById(id) {return list.childNodes.find(n => n.id === id) || elements.get(id) || (elements.set(id, node(id)), elements.get(id));},
    querySelectorAll(selector) {
      if (selector.startsWith('.source-details')) return list.childNodes.map(n => n.details).filter(n => !selector.includes(':not') || !n.open);
      if (selector === '.voce') return list.childNodes;
      return [];
    }
  };
  // Unknown record IDs must remain absent, as they do in the browser.
  const getById = document.getElementById;
  document.getElementById = id => /^d\d+$/.test(id) ? list.childNodes.find(n => n.id === id) || null : getById(id);
  const location = new URL('https://example.org/index.html' + hash);
  const redirects = [], requested = [];
  location.replace = url => redirects.push(url);
  const history = {replaceState(_, __, url) {location.href = new URL(url, location).href;}};
  const addEventListener = (name, fn, capture = false) => (listeners[name] ||= []).push({fn, capture});
  let failure;
  let requestedComponents = [];
  const pending = {then() {return this;}, catch(fn) {failure = fn; return this;}};
  let loaded;
  const startup = {then(fn) {loaded = fn; return pending;}};
  const context = vm.createContext({document, location, history, URL, URLSearchParams, Intl,
    localStorage:{getItem:key=>storage.get(key), setItem:(key,value)=>storage.set(key,value)},
    matchMedia:() => ({matches:true}), innerWidth:1280, addEventListener, setTimeout:fn => timers.push(fn),
    window:{addEventListener}, Promise, CatalogData:{run(ids, render, options) {requestedComponents = ids; loaded = render; failure = () => options.clear?.(); return pending;}}, fetch:url => {
      requested.push(url);
      if (url.startsWith('profiles/family-') || url.startsWith('profiles/org-')) return Promise.resolve({ok:staticPages.includes(url)});
      return url === 'data/archived-discoveries.json' ? Promise.resolve({ok:true, json:() => Promise.resolve(archived)}) : pending;
    }});
  vm.runInContext(fs.readFileSync('assets/catalog-ui.js', 'utf8'), context);
  vm.runInContext(fs.readFileSync('assets/catalog-entities.js', 'utf8'), context);
  context.CatalogEntities.configure(JSON.parse(fs.readFileSync('data/entity-aliases.json','utf8')));
  const html = fs.readFileSync(name, 'utf8');
  vm.runInContext([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1], context);
  const run = code => vm.runInContext(code, context);
  const dispatch = (type, event) => [...(listeners[type] || [])].forEach(x => x.fn(event));
  return {run, dispatch, list, location, history, redirects, requested, get requestedComponents(){return requestedComponents;}, flushTimers:() => timers.splice(0).forEach(fn => fn()), load:(records, models = null, citations = null) => loaded({data:{vulnerabilities:records, discoveries:name === 'models.html' ? models : records, 'discoveries-list':records, models:name === 'models.html' ? records : models, citations, 'archived-discoveries':archived, 'entity-aliases':JSON.parse(fs.readFileSync('data/entity-aliases.json','utf8'))}}), fail:() => failure(new Error("Network error"))};
}
const records = Array.from({length:90}, (_, i) => ({id:'d'+i, title:'Discovery '+i,
 summary:'Summary', ai_technology:'AI', field:i === 89 ? 'biology' : 'medicine',
 organization:'First lab', publication_date:'2025-01-01', added_date:'2025-01-02',
 source_url:'https://example.org/paper', source_type:'paper', verification_status:'verified',
 relevance:{impact:3, validation:3, novelty:3}}));
'''


class BrowserRegressionTests(unittest.TestCase):
    def run_js(self, code):
        result = subprocess.run(['node', '-e', HARNESS + code], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_source_status_round_trips_counts_exports_and_reset(self):
        self.run_js(r'''
const entries = records.map((r, i) => ({...r, verification_status:i < 50 ? 'needs verification' : 'verified'}));
const p = page('index.html', '?status=needs%20verification');
p.run('items = ' + JSON.stringify(entries) + '; grafici = () => {}; readFilters(["medicine", "biology"], ["First lab"], ["2025"], []); lista(); Blob = class { constructor(parts) {this.text = parts.join("");} }; URL.createObjectURL = blob => {globalThis.download = blob.text; return "blob:test";};');
assert.equal(p.run('state.status'), 'needs verification');
assert.equal(p.run('$("status").value'), 'needs verification');
assert.equal(p.list.childNodes.length, 40, 'Pagination must not change the selected denominator');
assert.equal(p.run('$("conta").textContent'), '50 of 90 discoveries, 40 shown');
assert.ok(p.run('$("selection-summary").innerHTML').includes('0 checked · 50 need a source check'));
assert.equal(new URLSearchParams(p.location.search).get('status'), 'needs verification');
p.run('$("dl-json").handlers.click();');
assert.deepEqual(JSON.parse(p.run('download')).map(r => r.id), entries.slice(0, 50).map(r => r.id));
p.run('$("dl-csv").handlers.click();');
assert.deepEqual(p.run('download').trim().split('\n').slice(1).map(row => row.split(',')[0]), entries.slice(0, 50).map(r => r.id));
p.run('vaiA("d89");');
assert.equal(p.run('state.status'), '', 'A direct entry link must clear a conflicting source-status filter');
assert.equal(p.location.search, '');
assert.equal(p.location.hash, '#discovery=d89');
p.run('state.status = "verified"; lista(); $("reset").handlers.click();');
assert.equal(p.run('$("status").value'), '');
assert.equal(p.run('selezione().length'), 90);
p.history.replaceState(null, '', '/index.html?status=unsupported');
p.run('readFilters([], [], [], []);');
assert.equal(p.run('state.status'), '', 'Unknown source-status query values must not create invisible filters');
''')

    def test_banner_search_uses_the_same_selection_and_focuses_results(self):
        self.run_js(r'''
const p = page('index.html');
p.run('$("banner-q").value = "Discovery 89"; $("banner-q").handlers.input({target:$("banner-q")}); riepilogo = spettro = grafici = featured = () => {};');
p.load(records);
assert.equal(p.run('state.q'), 'Discovery 89', 'Typing during loading must survive catalog initialization');
assert.equal(p.run('$("q").value'), 'Discovery 89');
p.run('$("quick-search").handlers.submit({preventDefault(){}});');
assert.deepEqual(p.list.childNodes.map(r => r.id), ['d89']);
assert.equal(p.run('document.activeElement.id'), 't-elenco');
assert.equal(new URLSearchParams(p.location.search).get('q'), 'Discovery 89');
p.run('$("q").value = "Summary"; $("q").handlers.input({target:$("q")});');
assert.equal(p.run('$("banner-q").value'), 'Summary');
p.run('$("reset").handlers.click();');
assert.equal(p.run('$("q").value'), '');
assert.equal(p.run('$("banner-q").value'), '');
''')

    def test_loading_preserves_explicit_query_edits_over_the_initial_url(self):
        self.run_js(r'''
for (const control of ['banner-q', 'q']) {
  for (const value of ['Discovery 89', '']) {
    const p = page('index.html', '?q=Discovery%201');
    p.run('riepilogo = spettro = grafici = featured = () => {};');
    p.run('$(' + JSON.stringify(control) + ').value = ' + JSON.stringify(value) + '; $(' + JSON.stringify(control) + ').handlers.input({target:$(' + JSON.stringify(control) + ')});');
    p.load(records);
    assert.equal(p.run('state.q'), value, 'An explicit edit must override the initial URL, including an empty edit');
    assert.equal(p.run('$("banner-q").value'), value);
    assert.equal(p.run('$("q").value'), value);
    assert.equal(new URLSearchParams(p.location.search).get('q'), value || null);
    assert.equal(p.run('selezione().length'), value ? 1 : 90);
    if (value) assert.deepEqual(p.list.childNodes.map(r => r.id), ['d89']);
  }
}
const untouched = page('index.html', '?q=Discovery%201');
untouched.run('riepilogo = spettro = grafici = featured = () => {};');
untouched.load(records);
assert.equal(untouched.run('state.q'), 'Discovery 1', 'Without an explicit edit the initial URL must still initialize the search');
assert.equal(untouched.run('$("banner-q").value'), 'Discovery 1');
assert.equal(untouched.run('$("q").value'), 'Discovery 1');
assert.equal(untouched.run('selezione().length'), 11);
''')

    def test_closed_chart_disclosures_redraw_only_when_opened_and_keep_filters(self):
        self.run_js(r'''
const p = page('index.html');
p.run('globalThis.draws = []; riepilogo = featured = () => {}; spettro = () => draws.push("spectrum"); grafici = () => draws.push("overview");');
p.load(records);
assert.equal(p.run('draws.length'), 0, 'Closed charts must not measure hidden widths at startup');
p.run('state.status = "verified"; $("overview").open = true; $("overview").handlers.toggle();');
assert.equal(p.run('$("overview").open'), true);
assert.equal(p.run('draws.join(",")'), 'overview');
p.run('$("timeline-overview").open = true; $("timeline-overview").handlers.toggle();');
assert.equal(p.run('draws.join(",")'), 'overview,spectrum');
assert.equal(p.run('state.status'), 'verified', 'Disclosure changes must retain the selected source status');
p.run('$("overview").open = false; $("overview").handlers.toggle();');
assert.equal(p.run('draws.length'), 2, 'Closing a chart must not redraw its hidden contents');
p.history.replaceState(null, '', '/index.html#overview'); p.dispatch('hashchange');
assert.equal(p.run('$("overview").open'), true, 'A changed overview fragment must reveal its destination');
const direct = page('index.html', '#overview');
assert.equal(direct.run('$("overview").open'), true, 'A direct overview fragment must reveal its destination');
''')

    def test_discovery_navigation_repositions_the_focused_heading(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; grafici = () => {}; lista(); vaiA("d89");');
const entry = p.list.childNodes.find(n => n.id === 'd89');
p.flushTimers();
assert.equal(entry.heading.scrollOptions.block, 'center');
assert.equal(entry.heading.scrollOptions.behavior, 'instant');
''')

    def test_discovery_navigation_does_not_animate_over_deferred_records(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; grafici = () => {}; lista(); ridotto.matches = false;');
p.run('CatalogUI.focusEntry = (entry, options) => { globalThis.navigation = {id:entry.id, ...options}; }; vaiA("d89");');
assert.equal(p.run('navigation.id'), 'd89');
assert.equal(p.run('navigation.block'), 'center');
assert.equal(p.run('navigation.behavior'), 'instant', 'Estimated offscreen heights must not shift an animated destination');
''')

    def test_corrected_organization_query_uses_preserved_static_profile(self):
        self.run_js(r'''
(async () => {
  const p = page('profile.html', '?org=Old%20Lab', [], ['profiles/org-old-lab.html']);
  p.load(records, {families:[], models:[]});
  for (let i=0; i<8; i++) await Promise.resolve();
  assert.deepEqual(p.redirects, ['profiles/org-old-lab.html']);
})().catch(error => {console.error(error); process.exitCode=1;});
''')

    def test_print_opens_all_disclosures_and_restores_reader_state(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; lista(); limite = 80; lista();');
p.list.childNodes[3].details.open = true;
const original = [...p.list.childNodes];
p.history.replaceState(null, '', '/index.html#discovery=d3');
const url = p.location.href;
p.dispatch('beforeprint');
assert.equal(p.list.childNodes.length, 90, 'Print must include every filtered entry');
assert.equal(p.list.childNodes.filter(n => n.details.open).length, 90, 'Print must expose evidence details after rendering');
assert.equal(p.location.href, url, 'Printing must preserve the discovery URL');
p.dispatch('afterprint');
assert.equal(p.run('limite'), 80, 'Printing must restore the reader page limit');
assert.deepEqual(p.list.childNodes, original, 'Restore the original nodes and their disclosure choices');
assert.equal(p.list.childNodes[3].details.open, true);
assert.equal(p.list.childNodes[4].details.open, false);
assert.equal(p.location.href, url);
''')

    def test_print_shortcut_loads_full_evidence_before_printing(self):
        self.run_js(r'''
(async () => {
  const p = page('index.html');
  p.run('riepilogo = spettro = grafici = featured = () => {};');
  p.load(records);
  const full = records.map(r => ({...r, evidence:{ai_role:'Role ' + r.id, tested:'Tested', unknown:'Unknown', publication_status:'Preprint', test_type:'direct test'}}));
  p.run('globalThis.printed = []; print = () => printed.push(document.getElementById("lista").childNodes.length); CatalogData.load = async () => ({data:{discoveries:' + JSON.stringify(full) + '}});');
  assert.ok(!p.run('details(items[0])').includes('Role d0'), 'The list starts without evidence prose');
  let prevented = false;
  p.dispatch('keydown', {key:'p', ctrlKey:true, preventDefault() {prevented = true;}});
  assert.ok(prevented, 'The shortcut waits for the full component');
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(p.run('printed.length'), 1, 'Print runs once after loading');
  assert.ok(p.run('details(items[89])').includes('Role d89'), 'Every listed entry has full evidence before printing');
  prevented = false;
  p.dispatch('keydown', {key:'p', ctrlKey:true, preventDefault() {prevented = true;}});
  assert.equal(prevented, false, 'Once loaded, printing proceeds normally');
  const failing = page('index.html');
  failing.run('riepilogo = spettro = grafici = featured = () => {};'); failing.load(records);
  failing.run('globalThis.printed = 0; print = () => printed++; CatalogData.load = async () => { throw Error("offline"); };');
  failing.dispatch('keydown', {key:'p', metaKey:true, preventDefault() {}});
  for (let i = 0; i < 8; i++) await Promise.resolve();
  assert.equal(failing.run('printed'), 1, 'A failed load still prints what is there');
})().catch(error => {console.error(error); process.exitCode = 1;});
''')

    def test_opening_excluded_discovery_updates_query_and_survives_reload(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; grafici = () => {}; state.field = "medicine"; state.ord = "asc"; lista(); vaiA("d89");');
assert.equal(p.location.search, '?sort=asc', 'Cleared filters must not survive in the URL');
assert.equal(p.location.hash, '#discovery=d89');
p.run('readFilters(["biology", "medicine"], ["First lab"], ["2025"], []); ancora = "d89"; lista();');
assert.ok(p.list.childNodes.some(n => n.id === 'd89'), 'Reloaded filters must still show the linked discovery');
''')

    def test_organization_grouping_preserves_internal_commas_and_conjunctions(self):
        self.run_js(r'''
for (const [name, fn] of [['index.html', 'orgDi'], ['profile.html', 'leadOrg']]) {
  const p = page(name);
  for (const [organization, expected] of [[' First lab; Second lab', 'First lab'], ['University of California, Berkeley', 'University of California, Berkeley'], ['Science and Technology Lab', 'Science and Technology Lab']]) {
    assert.equal(p.run(fn + '(' + JSON.stringify({organization}) + ')'), expected, name + ': ' + organization);
  }
}
''')

    def test_initial_and_changed_fragments_open_filtered_and_paginated_records(self):
        self.run_js(r'''
for (const hash of ['#discovery=d89', '#scoperta=d89']) {
  const p = page('index.html', hash);
  p.history.replaceState(null, '', '/index.html?field=medicine' + hash);
  p.run('riepilogo = spettro = grafici = featured = () => {};');
  p.load(records);
  assert.ok(p.list.childNodes.some(n => n.id === 'd89'), 'Startup must reveal a record excluded by filters');
  assert.equal(p.location.search, '');
  assert.equal(p.run('document.activeElement === document.getElementById("d89").heading'), true);
}
const p = page('index.html');
p.run('riepilogo = spettro = grafici = featured = () => {};'); p.load(records);
p.history.replaceState(null, '', '/index.html#scoperta=d89'); p.dispatch('hashchange');
assert.ok(p.list.childNodes.some(n => n.id === 'd89'), 'Changed fragments must reveal records beyond the first page');
assert.equal(p.location.hash, '#discovery=d89');
for (const hash of ['#%', '#discovery=%FF']) {
  p.history.replaceState(null, '', '/index.html' + hash); p.dispatch('hashchange');
  assert.ok(p.list.childNodes.some(n => n.id === 'd89'));
}
''')

    def test_selection_exports_share_visible_sort_and_source_schema_shape(self):
        self.run_js(r'''
const entries = [
  {...records[0], publication_date:'2025-03-01', added_date:'2025-04-01', citation:{cited_by_count:4}},
  {...records[1], publication_date:'2025-02-01', added_date:'2025-04-01', relevance:{impact:5, validation:5, novelty:5}},
  {...records[2], publication_date:'2025-01-01', added_date:'2025-05-01'}
];
const p = page('index.html');
p.run('items = ' + JSON.stringify(entries) + '; Blob = class { constructor(parts) {this.text = parts.join("");} }; URL.createObjectURL = blob => {globalThis.download = blob.text; return "blob:test";}; setTimeout = () => {};');
for (const [sort, ids] of [['desc', ['d0','d1','d2']], ['asc', ['d2','d1','d0']], ['relevance', ['d1','d0','d2']], ['added', ['d2','d0','d1']]]) {
  p.run('state.ord = ' + JSON.stringify(sort) + '; lista(); $("dl-json").handlers.click();');
  const exported = JSON.parse(p.run('download'));
  assert.deepEqual(exported.map(s => s.id), ids, sort + ': JSON order');
  assert.deepEqual(p.list.childNodes.map(s => s.id), ids, sort + ': visible order');
  assert.ok(exported.every(s => !Object.hasOwn(s, 'citation')), 'View citations must not leak into source-schema JSON');
  p.run('$("dl-csv").handlers.click();');
  const csv = p.run('download');
  assert.deepEqual(csv.trim().split('\n').slice(1).map(row => row.split(',')[0]), ids, sort + ': CSV order');
}
assert.equal(p.run('items[0].citation.cited_by_count'), 4, 'Export must preserve view enrichment');
''')

    def test_view_citations_include_snapshot_date_without_mutating_sidecar(self):
        self.run_js(r'''
for (const name of ['index.html', 'profile.html']) {
  const p = page(name);
  p.run(name === 'index.html' ? 'riepilogo = spettro = grafici = featured = () => {};' : 'directory = () => {};');
  const cited = {cited_by_count:4};
  const entries = [{...records[0]}];
  p.load(entries, {families:[], models:[]}, {checked:'2026-11-15', records:{d0:cited}});
  assert.equal(entries[0].citation.checked, '2026-11-15');
  assert.notEqual(entries[0].citation, cited);
  assert.ok(!Object.hasOwn(cited, 'checked'));
}
''')

    def test_models_print_expands_filtered_rows_and_restores_nodes_and_focus(self):
        self.run_js(r'''
const models = Array.from({length:180}, (_, i) => ({name:'Model ' + i, organization:i < 150 ? 'Lab' : 'Other', date:'2025-01-01', domain:'Language', access:'Open', family:''}));
const p = page('models.html');
p.run('D = {models:' + JSON.stringify(models) + '}; aggiornaNuvola = () => {}; state.lab = "Lab"; render(); mostrati = 100; render(); $("lista").childNodes[3].focus();');
const original = [...p.list.childNodes];
const focused = p.run('document.activeElement');
p.dispatch('beforeprint');
assert.equal(p.list.childNodes.length, 150, 'Printing must include every matching release');
p.dispatch('beforeprint');
p.dispatch('afterprint');
assert.equal(p.run('mostrati'), 100);
assert.deepEqual(p.list.childNodes, original, 'Print must restore the original row nodes');
assert.equal(p.run('document.activeElement'), focused, 'Print must restore focus');
p.run('render();');
assert.equal(p.list.childNodes.length, 100);
''')

    def test_archived_discovery_links_redirect_only_for_known_archived_ids(self):
        self.run_js(r'''
(async () => {
  for (const hash of ['#discovery=retired%20entry', '#scoperta=retired%20entry']) {
    const p = page('index.html', hash, [{id:'retired entry', source_url:'https://untrusted.example/'}]);
    p.run('riepilogo = spettro = grafici = featured = () => {};');
    p.load(records);
    await new Promise(setImmediate);
    assert.deepEqual(p.redirects, ['share/retired%20entry.html'], 'Archived anchors must use the fixed local share destination');
  }
  const changed = page('index.html', '', [{id:'retired entry'}]);
  changed.run('riepilogo = spettro = grafici = featured = () => {};'); changed.load(records);
  changed.history.replaceState(null, '', '/index.html#scoperta=retired%20entry'); changed.dispatch('hashchange');
  await new Promise(setImmediate);
  assert.deepEqual(changed.redirects, ['share/retired%20entry.html'], 'Changed legacy fragments must also resolve archives');
  const stale = page('index.html', '', [{id:'retired entry'}]);
  stale.run('riepilogo = spettro = grafici = featured = () => {};'); stale.load(records);
  stale.history.replaceState(null, '', '/index.html#discovery=retired%20entry'); stale.dispatch('hashchange');
  stale.history.replaceState(null, '', '/index.html#discovery=d1'); stale.dispatch('hashchange');
  await new Promise(setImmediate);
  assert.deepEqual(stale.redirects, [], 'Late archive responses must not replace newer active navigation');
  for (const id of ['unknown', 'd0']) {
    const p = page('index.html', '#discovery=' + id, [{id:'different archive'}]);
    p.run('riepilogo = spettro = grafici = featured = () => {};');
    p.load(records);
    await new Promise(setImmediate);
    assert.deepEqual(p.redirects, [], 'Unknown and active anchors must keep current navigation');
    assert.ok(p.requestedComponents.includes('archived-discoveries'), 'Archives share the initial validated snapshot; no later unversioned fetch');
    assert.equal(p.requested.includes('data/archived-discoveries.json'), false);
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
''')

    def test_legacy_organization_urls_only_map_known_historical_groups(self):
        self.run_js(r'''
const entries = [{...records[0], organization:'MIT; Imperial College London'}, {...records[1], organization:'Other lab'}];
for (const [oldName, expected] of [['MIT; Imperial College London', 'Massachusetts Institute of Technology'], ['MIT;bogus', '']]) {
  const p = page('index.html');
  p.history.replaceState(null, '', '/index.html?org=' + encodeURIComponent(oldName));
  p.run('items = ' + JSON.stringify(entries) + '; readFilters(["medicine"], ["Massachusetts Institute of Technology", "Other lab"], ["2025"], []); lista();');
  assert.equal(p.run('state.org'), expected, 'Only actual historical organization keys should map to current groups');
  assert.equal(p.list.childNodes.length, expected ? 1 : 2);
  const profile = page('profile.html');
  profile.run('setMeta = timeline = () => {}; labView(' + JSON.stringify(oldName) + ', ' + JSON.stringify(entries) + ', {families:[], models:[]});');
  assert.equal(profile.run('$("page-title").textContent'), expected || 'Not found');
}
''')

    def test_ambiguous_legacy_organization_profiles_offer_actual_names(self):
        self.run_js(r'''
const entries = [{...records[0], organization:'University of California, Berkeley'}, {...records[1], organization:'University of California, Los Angeles'}];
const p = page('profile.html');
p.run('setMeta = timeline = () => {}; labView("University of California", ' + JSON.stringify(entries) + ', {families:[], models:[]});');
const html = p.run('$("content").innerHTML');
for (const entry of entries) assert.ok(html.includes('href="profile.html?org=' + encodeURIComponent(entry.organization) + '"'), 'Ambiguous legacy names must offer each actual organization');
assert.equal(p.run('$("page-title").textContent'), 'Choose an organization');
''')

    def test_archive_only_organization_query_preserves_the_known_uni_page(self):
        self.run_js(r'''
(async () => {
  const oldOrg = 'Mass General Brigham; Harvard Medical School';
  const uni = {id:'2024-03-uni-pathology-foundation-model', organization:oldOrg};
  for (const [name, archived, expected] of [
    [oldOrg, [uni], ['share/2024-03-uni-pathology-foundation-model.html']],
    ['Mass General Brigham;bogus', [uni], []],
    [oldOrg, [uni, {...uni, id:'another-retired-entry'}], []]
  ]) {
    const p = page('profile.html', '', archived);
    p.run('archiveData = ' + JSON.stringify(archived) + '; labView(' + JSON.stringify(name) + ', [], {families:[], models:[]});');
    await new Promise(setImmediate);
    assert.deepEqual(p.redirects, expected, 'Only one exact archived historical organization match may redirect');
    assert.equal(p.run('$("page-title").textContent'), 'Not found');
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
''')

    def test_archived_only_family_profile_uses_existing_static_alias(self):
        self.run_js(r'''
(async () => {
  for (const [id, exists] of [['perch', true], ['unknown', false], ['../unsafe family', true]]) {
    const url = 'profiles/family-' + encodeURIComponent(id) + '.html';
    const p = page('profile.html', '', [], exists ? [url] : []);
    p.history.replaceState(null, '', '/profile.html?family=' + encodeURIComponent(id));
    p.run('familyView(' + JSON.stringify(id) + ', [], {families:[], models:[]});');
    await new Promise(setImmediate);
    assert.deepEqual(p.redirects, exists ? [url] : [], 'Only existing static family aliases should redirect');
    assert.ok(p.requested.includes(url), 'Lookup must encode the family ID into one local path');
    assert.equal(p.run('$("page-title").textContent'), 'Not found', 'Failed aliases preserve a useful not-found view');
  }
  const stale = page('profile.html', '', [], ['profiles/family-perch.html']);
  stale.history.replaceState(null, '', '/profile.html?family=perch');
  stale.run('familyView("perch", [], {families:[], models:[]});');
  stale.history.replaceState(null, '', '/profile.html?org=Other');
  await new Promise(setImmediate);
  assert.deepEqual(stale.redirects, [], 'Late family alias checks must not override newer navigation');
})().catch(error => {console.error(error); process.exitCode = 1;});
''')

    def test_malformed_fragment_does_not_abort_catalog_startup(self):
        self.run_js(r'''
for (const hash of ['#%', '#discovery=%E0%A4%A', '#%FF']) {
  const p = page('index.html', hash);
  p.run('riepilogo = spettro = grafici = featured = () => {};');
  p.load(records);
  assert.equal(p.list.childNodes.length, 40, 'Invalid fragments must still show the catalog');
  assert.equal(p.run('state.field'), '');
}
const legacy = page('index.html', '#computer%20science');
legacy.run('riepilogo = spettro = grafici = featured = () => {};');
legacy.load([{...records[0], field:'computer science'}]);
assert.equal(legacy.run('state.field'), 'computer science');
''')

    def test_discovery_chart_navigation_focuses_the_result_heading(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; grafici = () => {}; lista(); vaiA("d89");');
assert.equal(p.run('document.activeElement === document.getElementById("d89").heading'), true);
assert.equal(p.run('document.activeElement.attributes.tabindex'), '-1');
assert.equal(p.run('document.activeElement.focusOptions.preventScroll'), true);
assert.equal(p.run('document.getElementById("d89").scrollOptions.block'), 'center');
''')

    def test_models_chart_and_pagination_focus_results(self):
        self.run_js(r'''
const models = Array.from({length:180}, (_, i) => ({name:'Model ' + i, organization:'Lab', date:'2025-01-01', domain:'Language', access:'Open', link:'', compute_flop:'', parameters:'', family:''}));
const p = page('models.html');
p.run('D = {models:' + JSON.stringify(models) + '}; grafici = aggiornaNuvola = () => {}; render();');
p.run('$(' + JSON.stringify('altro') + ').handlers.click({target:{id:"piu-righe"}});');
assert.equal(p.run('document.activeElement.id === slug(D.models[60].name)'), true, 'Pagination must focus the first newly shown model');
p.run('vaiA(D.models[179]);');
assert.equal(p.run('document.activeElement.id === slug(D.models[179].name)'), true, 'Scatter activation must focus the selected release');
assert.equal(p.run('document.activeElement.attributes.tabindex'), '-1');
''')

    def test_late_discovery_render_failure_clears_families_and_recovers_changed_membership(self):
        self.run_js(r'''
const p = page('index.html', '?q=Discovery');
const family = id => ({id,name:id,discoveries:['d0'],discovery_count:1});
p.run('featured = () => { $("featured-list").innerHTML = "failed featured"; throw Error("late featured failure"); };');
assert.throws(() => p.load([{...records[0]}], {families:[family('old-family')]}), /late featured/);
assert.equal(p.run('famDi.d0.id'), 'old-family');
p.fail();
for (const expression of ['items.length','Object.keys(famDi).length','Object.keys(famIds).length','archiveData.length','sp.length']) assert.equal(p.run(expression),0,expression);
assert.equal(p.run('spSvg'),null);
for(const id of ['featured-list','selection-summary','charts','spettro','cat']) assert.equal(p.run('$('+JSON.stringify(id)+').innerHTML'),'');
p.run('featured = () => {};');
p.load([{...records[0]}], {families:[family('new-family')]});
assert.equal(p.run('famDi.d0.id'),'new-family');assert.equal(p.run('JSON.stringify(famIds.d0)'), '["new-family"]');
const card=p.run('voce(items[0])');assert.ok(card.includes('new-family'));assert.ok(!card.includes('old-family'));
p.run('state.family="new-family";');assert.equal(p.run('items.filter(passa).length'),1);
p.run('state.family="old-family";');assert.equal(p.run('items.filter(passa).length'),0);
assert.equal(p.run('state.q'),'Discovery');
''')

    def test_failed_consumer_load_clears_records_and_preserves_query(self):
        self.run_js(r'''
for (const name of ['models.html', 'profile.html', 'index.html']) {
  const p = page(name, '?q=retain'); p.fail();
  assert.equal(p.location.search, '?q=retain');
  assert.equal(p.run(name === 'models.html' ? 'D' : name === 'profile.html' ? 'data' : 'items.length'), name === 'index.html' ? 0 : null);
}
''')

    def test_models_late_failure_resets_snapshot_caches_and_retry_handlers(self):
        self.run_js(r'''
const p = page('models.html', '?q=Model');
const snapshot = id => ({models:[{name:'Model '+id,organization:'Lab',date:'2025-01-01',domain:'Language',family:id}],families:[{id,name:id,discoveries:['d0'],discovery_count:1,model_count:0}],linked_discoveries:['d0'],generated:'2026-11-14',source:{}});
p.run('const originalCharts = grafici; nuvola = () => { pts = [{m:D.models[0]}]; nuvSvg = {}; $("nuvola").innerHTML = "failed scatter"; }; grafici = () => { $("charts").innerHTML = "failed charts"; }; aggiornaNuvola = () => {}; const originalRender = render; render = () => { originalRender(); throw Error("late render failure"); };');
assert.throws(() => p.load(snapshot('old'), [records[0]]), /late render/);
p.fail();
assert.equal(p.run('D'), null);
assert.equal(p.run('Object.keys(discoveries).length + Object.keys(perFam).length + Object.keys(famNome).length + pts.length'), 0);
assert.equal(p.run('nuvSvg'), null);
for (const id of ['nuvola','families','charts','fonte','conta','altro']) assert.equal(p.run('$('+JSON.stringify(id)+').innerHTML') || '', '');
assert.equal(p.run('$("lead").textContent'), 'No validated catalog snapshot loaded.');
p.run('render = originalRender; render(); families(); vaiA({name:"stale"}); $("families").handlers.click({target:{closest(){return {};}}});');
p.run('render = originalRender;');
p.load(snapshot('new'), [records[0]]);
assert.equal(p.run('Object.keys(perFam).join(",")'), 'new');
assert.equal(p.run('Object.keys(famNome).join(",")'), 'new');
assert.equal(p.run('$("families").listenerCounts.click'), 1);
assert.equal(p.run('state.q'), 'Model');
p.load({...snapshot('empty'),models:[],families:[],linked_discoveries:[]}, []);
assert.equal(p.run('Object.keys(perFam).length + Object.keys(discoveries).length'), 0);
assert.equal(p.run('$("families").listenerCounts.click'), 1);
p.run('grafici = originalCharts; grafici();');
assert.ok(!p.run('$("charts").innerHTML').includes('NaN'));
''')

    def test_security_retry_replaces_products_and_clears_report_cache(self):
        self.run_js(r'''
const p = page('security.html', '?product=Retained&q=needle');
const entry = product => ({id:product,product,ai_system:'System',disclosure_date:'2026-11-01',cves:[],source_url:'https://example.org/report'});
p.run('charts = () => {}; render = () => {throw Error("late security failure");};');
assert.throws(() => p.load([entry('Removed')]), /late security/);
p.fail();
assert.equal(p.run('reports.size'), 0);
assert.equal(p.run('$("product").innerHTML'), '');
p.run('render = () => {}; openHash = () => {};');
p.load([entry('Retained')]); p.load([entry('Retained')]);
const options = p.run('$("product").innerHTML');
assert.equal((options.match(/<option>Retained/g) || []).length, 1);
assert.ok(!options.includes('Removed'));
assert.equal(p.run('$("product").value'), 'Retained');
assert.equal(p.run('$("q").value'), 'needle');
''')

    def test_security_remediation_shows_verified_ranges_and_preserves_unknowns(self):
        self.run_js(r'''
const storage = new Map();
const p = page('security.html', '', [], [], storage);
const vulnerabilities = JSON.parse(fs.readFileSync('data/vulnerabilities.json','utf8'));
const openWebUI = vulnerabilities.find(record => record.id === 'ghsl-2026-002');
const firefox = vulnerabilities.find(record => record.id === 'cve-2026-2796');
const mozillaFirefox = vulnerabilities.find(record => record.id === 'cve-2026-2797');
const sqlite = vulnerabilities.find(record => record.id === 'cve-2025-6965');
p.run('charts = () => {};');
p.load([openWebUI, firefox, mozillaFirefox, sqlite]);
p.run('$("my-product").value = "Open WebUI"; $("my-version").value = "v0.8.5"; $("my-product-form").handlers.submit({preventDefault(){}});');
assert.deepEqual(JSON.parse(storage.get('ast-security-my-products')), [['Open WebUI', 'v0.8.5']]);
const reopened = page('security.html', '', [], [], storage);
assert.equal(reopened.run('myProducts.get("Open WebUI")'), 'v0.8.5');
let html = p.run('$("cases").innerHTML');
assert.match(html, /What to update.*Open WebUI/);
assert.match(html, /Matches the advisory’s affected version range/);
assert.doesNotMatch(html, /Firefox/);
p.run('myProducts.set("Open WebUI", "0.8.10"); render();');
assert.match(p.run('$("cases").innerHTML'), /Outside the advisory’s listed affected range/);
p.run('myProducts.set("Open WebUI", "0.8.6-rc1"); render();');
assert.match(p.run('$("cases").innerHTML'), /Comparison unavailable/);
p.run('myProducts.set("Firefox", "147.0.0"); render();');
html = p.run('$("cases").innerHTML');
assert.match(html, /Affected versions not confirmed in this summary/);
assert.match(html, /Fixed in:<\/strong> Firefox 148/);
assert.match(html, /Saved version 147\.0\.0:<\/strong> Comparison unavailable/);
assert.match(html, /id="cve-2026-2797"/, 'Firefox watchlist includes a Mozilla Firefox product label');
assert.doesNotMatch(html, /id="cve-2025-6965"/);
assert.match(p.run('versionMatch("3.50.1", {upper_bound:"3.50.2", inclusive:false})'), /^Matches/);
assert.match(p.run('versionMatch("3.50.2", {upper_bound:"3.50.2", inclusive:false})'), /^Outside/);
p.run('$("reset").handlers.click();');
assert.equal(p.run('$("only-my-products").checked'), false);
assert.equal(p.run('myProducts.has("Open WebUI")'), true);
p.run('$("my-product-list").handlers.click({target:{closest:()=>({dataset:{removeProduct:"Open WebUI"}})}});');
assert.deepEqual(JSON.parse(storage.get('ast-security-my-products')), [['Firefox', '147.0.0']]);
''')

    def test_models_snapshot_without_download_date_still_renders(self):
        self.run_js(r'''
for (const downloaded of [undefined, '2026-11-13']) {
  const p = page('models.html');
  p.run('nuvola = grafici = families = render = () => {};');
  p.load({models:[], families:[], linked_discoveries:[], generated:'2026-11-14', source:{name:'Epoch AI', url:'https://epoch.ai/data/ai-models', license:'CC BY 4.0', license_url:'https://creativecommons.org/licenses/by/4.0/', original_records:42, csv_sha256:'a'.repeat(64), downloaded}}, []);
  const html = p.run('$("fonte").innerHTML');
  assert.ok(html.includes('42 records') && html.includes('href="data/models.json"'));
  assert.equal(html.includes('Downloaded on'), Boolean(downloaded));
  assert.equal(html.includes('13 Nov 2026'), Boolean(downloaded));
  assert.ok(!html.includes('undefined') && !html.includes('Invalid Date'));
}
''')
