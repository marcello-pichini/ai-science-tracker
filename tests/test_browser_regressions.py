"""Execute the page scripts against a small DOM for navigation and print lifecycle checks."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

HARNESS = r'''
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function page(name, hash = "", archived = []) {
  const listeners = {}, elements = new Map();
  const classes = () => ({add() {}, remove() {}, toggle() {}});
  const node = id => ({id, classList:classes(), open:false, textContent:'', value:'',
    setAttribute() {}, addEventListener() {}, scrollIntoView() {}, querySelector() {return null;}});
  const list = node('lista'); list.childNodes = [];
  Object.defineProperty(list, 'innerHTML', {set(html) {
    this.childNodes = [...html.matchAll(/<article class="voce" id="([^"]+)"/g)].map(m => {
      const article = node(m[1]); article.details = node(); return article;
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
  const pending = {then() {return this;}, catch() {return this;}};
  let loaded;
  const startup = {then(fn) {loaded = fn; return pending;}};
  const context = vm.createContext({document, location, history, URL, URLSearchParams, Intl,
    matchMedia:() => ({matches:true}), innerWidth:1280, addEventListener,
    window:{addEventListener}, Promise:{all:() => startup}, fetch:url => {
      requested.push(url);
      return url === 'data/archived-discoveries.json' ? Promise.resolve({ok:true, json:() => Promise.resolve(archived)}) : pending;
    }});
  vm.runInContext(fs.readFileSync('assets/catalog-ui.js', 'utf8'), context);
  const html = fs.readFileSync(name, 'utf8');
  vm.runInContext([...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].at(-1)[1], context);
  const run = code => vm.runInContext(code, context);
  const dispatch = type => [...(listeners[type] || [])].forEach(x => x.fn());
  return {run, dispatch, list, location, history, redirects, requested, load:records => loaded([records, null])};
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

    def test_organization_grouping_uses_first_comma_semicolon_or_and(self):
        self.run_js(r'''
for (const [name, fn] of [['index.html', 'orgDi'], ['profile.html', 'leadOrg']]) {
  const p = page(name);
  for (const organization of [' First lab; Second lab', 'First lab, Second lab', 'First lab AND Second lab', 'First lab and Second lab', 'First lab']) {
    assert.equal(p.run(fn + '(' + JSON.stringify({organization}) + ')'), 'First lab', name + ': ' + organization);
  }
}
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
