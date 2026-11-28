"""Literal retrieval must disclose matches and preserve independent counting units."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CatalogSearchTests(unittest.TestCase):
    def test_normalization_match_reasons_and_missing_values(self):
        result = subprocess.run(['node', '-e', """
require('./assets/catalog-search.js');
const assert = require('node:assert/strict'), s = CatalogSearch;
assert.equal(s.normalize('CVE–2026–1234'), 'cve 2026 1234');
assert.deepEqual(s.match({Title:'A café model', DOI:'10.1234/test', Limit:null}, 'CAFE'), ['Title']);
assert.deepEqual(s.match({Title:'A model', DOI:'10.1234/test'}, '10.1234/test'), ['DOI']);
assert.deepEqual(s.match({Identifier:'CVE-2026-22796'}, 'CVE-2026-2796'), []);
assert.deepEqual(s.match({Identifier:'CVE-2026-2796', Note:'Related CVE-2026-22796'}, 'cve–2026–2796'), ['Identifier']);
assert.deepEqual(s.match({Source:'https://doi.org/10.1234/test-extension'}, '10.1234/test'), []);
assert.deepEqual(s.match({Source:'https://doi.org/10.1234/test'}, 'https://doi.org/10.1234/test'), ['Source']);
assert.deepEqual(s.match({Title:'A model', Organization:'Lab'}, 'model lab'), ['Title','Organization']);
assert.deepEqual(s.match({Title:'A model'}, 'model absent'), []);
assert.deepEqual(s.match({Title:'A model'}, '---'), []);
const groups = s.collections([],[],{models:[],families:[]},{models:[]});
assert.equal(groups.length, 5);
assert.ok(groups.every(g => g.records.length === 0));
const cases = s.collections([], [{id:'CVE-2026-1',title:'Case',products:['acme:lib'],classes:['SQL injection'],advisory:'https://vendor.example/unique-advisory'}], {models:[],families:[]}, {models:[]})[1];
assert.deepEqual(s.match(cases.records[0].fields, 'unique-advisory'), ['Sources'], 'Advisory evidence is a searchable source');
assert.deepEqual(s.match(cases.records[0].fields, 'sql injection'), ['Weakness']);
assert.equal(cases.records[0].href, 'security.html?q=CVE-2026-1');
const linked = s.collections([{id:'discovery'}], [], {models:[], families:[
  {id:'active', discoveries:['discovery']}, {id:'archive-only', discoveries:['archived']}
]});
assert.equal(linked[0].records[0].href, 'share/discovery.html');
assert.equal(linked[0].records[0].explorer, '/#discovery=discovery');
assert.equal(linked[4].records[0].href, 'profiles/family-active.html');
assert.equal(linked[4].records[1].href, 'profile.html?family=archive-only');
const science = s.collections([
  {id:'other',title:'Other study',summary:'Used AlphaFold 3'},
  {id:'exact',title:'AlphaFold 3: molecular complexes',source_url:'https://publisher.example/article'}
],[],{models:[],families:[]},null,{records:{exact:{doi:'10.1234/full-id'},other:{doi:'10.1234/other'}}})[0].records;
assert.equal(s.results(science, 'AlphaFold 3')[0].id, 'exact');
assert.deepEqual(s.results(science, 'https://doi.org/10.1234/full-id').map(r => r.id), ['exact']);
assert.equal(s.results(science, '10.1234/full').length, 0);
"""], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
