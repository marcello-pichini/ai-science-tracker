"""Execute the page scripts against a small DOM for navigation and print lifecycle checks."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(name, hash = "", archived = [], staticPages = []) {
  const listeners = {}, elements = new Map();
  const classes = () => ({add() {}, remove() {}, toggle() {}});
  const node = id => ({id, classList:classes(), open:false, textContent:'', value:'', attributes:{}, handlers:{}, childNodes:[],
    append() {}, click() {}, remove() {}, replaceChildren(...children) {this.childNodes = children;},
    setAttribute(k, v) {this.attributes[k] = v;}, addEventListener(k, fn) {this.handlers[k] = fn;},
    focus(options) {document.activeElement = this; this.focusOptions = options;},
    scrollIntoView(options) {this.scrollOptions = options;}, querySelector(selector) {return selector === 'h3' ? this.heading || null : null;}});
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
  const pending = {then() {return this;}, catch(fn) {failure = fn; return this;}};
  let loaded;
  const startup = {then(fn) {loaded = fn; return pending;}};
  const context = vm.createContext({document, location, history, URL, URLSearchParams, Intl,
    matchMedia:() => ({matches:true}), innerWidth:1280, addEventListener,
    window:{addEventListener}, Promise:{all:() => startup}, fetch:url => {
      requested.push(url);
      if (url.startsWith('profiles/family-')) return Promise.resolve({ok:staticPages.includes(url)});
      return url === 'data/archived-discoveries.json' ? Promise.resolve({ok:true, json:() => Promise.resolve(archived)}) : pending;
    }});
  vm.runInContext(fs.readFileSync('assets/catalog-ui.js', 'utf8'), context);
  const html = fs.readFileSync(name, 'utf8');
  vm.runInContext([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1], context);
  const run = code => vm.runInContext(code, context);
  const dispatch = type => [...(listeners[type] || [])].forEach(x => x.fn());
  return {run, dispatch, list, location, history, redirects, requested, load:(records, models = null, citations = null) => loaded([records, models, citations]), fail:() => failure(new Error("Network error"))};
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

    def test_discovery_navigation_does_not_animate_over_deferred_records(self):
        self.run_js(r'''
const p = page('index.html');
p.run('items = ' + JSON.stringify(records) + '; grafici = () => {}; lista(); ridotto.matches = false;');
p.run('CatalogUI.focusEntry = (entry, options) => { globalThis.navigation = {id:entry.id, ...options}; }; vaiA("d89");');
assert.equal(p.run('navigation.id'), 'd89');
assert.equal(p.run('navigation.block'), 'center');
assert.equal(p.run('navigation.behavior'), 'instant', 'Estimated offscreen heights must not shift an animated destination');
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
    assert.equal(p.requested.includes('data/archived-discoveries.json'), id === 'unknown');
  }
})().catch(error => {console.error(error); process.exitCode = 1;});
''')

    def test_legacy_organization_urls_only_map_known_historical_groups(self):
        self.run_js(r'''
const entries = [{...records[0], organization:'MIT; Imperial College London'}, {...records[1], organization:'Other lab'}];
for (const [oldName, expected] of [['MIT; Imperial College London', 'MIT'], ['MIT;bogus', '']]) {
  const p = page('index.html');
  p.history.replaceState(null, '', '/index.html?org=' + encodeURIComponent(oldName));
  p.run('items = ' + JSON.stringify(entries) + '; readFilters(["medicine"], ["MIT", "Other lab"], ["2025"], []); lista();');
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
    p.run('labView(' + JSON.stringify(name) + ', [], {families:[], models:[]});');
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

    def test_failed_data_load_offers_public_recovery_links(self):
        self.run_js(r'''
for (const name of ['models.html', 'profile.html']) {
  const p = page(name); p.fail();
  const html = p.run(name === 'models.html' ? '$("families").innerHTML' : '$("content").innerHTML');
  for (const link of [name, 'data/models.json', 'data/discoveries.json', 'profiles/index.html']) assert.ok(html.includes('href="' + link + '"'), name + ': missing ' + link);
  assert.ok(!html.includes('python3'));
}
const profile = page('profile.html');
profile.history.replaceState(null, '', '/profile.html?org=First%20lab&source=one');
profile.fail();
assert.ok(profile.run('$("content").innerHTML').includes('href="profile.html?org=First%20lab&amp;source=one"'), 'Reload must preserve the selected profile');
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
