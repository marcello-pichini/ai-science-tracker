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
"""], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
