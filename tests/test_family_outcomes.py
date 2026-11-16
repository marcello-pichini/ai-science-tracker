import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class FamilyOutcomeTests(unittest.TestCase):
    def test_subsets_examples_missing_values_and_overlaps(self):
        code = """
const assert = require('node:assert/strict');
const f = require('./assets/family-outcomes.js');
const rows = [
 {id:'b', field:'Biology', publication_date:'2025-02-01', evidence:{test_type:'direct test'}},
 {id:'a', field:'Biology', publication_date:'2025-02-01'},
 {id:'c', field:'Physics', publication_date:'2024-01-01', evidence:{test_type:'not reported'}}
];
assert.deepEqual(f.examples(rows).map(r => r.id), ['a','b','c']);
assert.equal(f.summary(rows).fields.reduce((n,g) => n + g.members.length,0), rows.length);
assert.equal(f.summary(rows).tests.length, 3);
assert.equal(f.testContext(rows[2]), 'Test context unspecified in annotation');
assert.equal(f.testContext(rows[1]), 'Not annotated in this catalog');
assert.deepEqual(f.select({discoveries:['a','a','b','missing']},rows,'Biology','2025').map(r => r.id),['b','a']);
assert.equal(f.select({discoveries:['c']}, rows, 'Biology').length,0);
assert.deepEqual(f.summary([]), {fields:[],tests:[],annotations:[]});
"""
        subprocess.run(['node', '-e', code], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_static_summary_preserves_members_and_limits(self):
        sys.path.insert(0, str(ROOT / 'scripts'))
        spec = importlib.util.spec_from_file_location('family_share', ROOT / 'scripts/generate_share.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        rows = [{'id': 'b', 'title': 'B', 'field': 'Physics', 'publication_date': '2025-01-01'},
                {'id': 'a', 'title': 'A', 'field': 'Biology', 'publication_date': '2025-01-01',
                 'evidence': {'test_type': 'not reported'}}]
        html = module.family_summary(rows, '<Family>')
        self.assertIn('Where &lt;Family&gt; appears', html)
        self.assertIn('not verified model-version assignments or causal attribution', html)
        self.assertIn('Test context unspecified in annotation', html)
        self.assertIn('Not annotated in this catalog', html)
        examples = html.split('<h3>Examples</h3>')[1]
        self.assertLess(examples.index('discovery=a'), examples.index('discovery=b'))

    def test_report_group_deduplicates_case_urls_and_preserves_case_identity(self):
        records = json.loads((ROOT / 'data/vulnerabilities.json').read_text())
        groups = {}
        for record in records:
            for url in {record[key] for key in ('source_url', 'ai_source_url', 'advisory_url')}:
                groups.setdefault(url, []).append(record)
        largest = max(groups.values(), key=len)
        self.assertGreater(len(largest), 1)
        self.assertEqual(len(largest), len({r['id'] for r in largest}))
        page = (ROOT / 'security.html').read_text()
        self.assertIn('record.summary,record.ai_role,...record.cves', page)
        self.assertIn('new Set(group.flatMap(r => r.cves)).size', page)
        self.assertIn('Human involvement is only described', page)
        self.assertIn('installed patches or current safety', page)
