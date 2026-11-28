import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

from test_browser_regressions import HARNESS

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

    def run_profile(self, code):
        setup = r"""
const p = page('profile.html', '?family=one&compare=two&field=invalid&year=20');
p.run(fs.readFileSync('assets/family-outcomes.js', 'utf8'));
const rows = records.slice(0, 2).map((r, i) => ({...r, evidence:{test_type:'direct test', tested:'Measured result', unknown:i ? '<Unresolved second limit>' : 'First limit'}}));
const models = {families:[{id:'one',name:'One',discoveries:rows.map(r => r.id)}, {id:'two',name:'Two',discoveries:['d1']}],models:[]};
p.run('data = ' + JSON.stringify({discoveries:rows,models}) + '; renderComparison(data.models.families[0], data.discoveries, data.models);');
"""
        result = subprocess.run(['node', '-e', HARNESS + setup + code], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_comparison_ignores_filters_absent_from_the_controls(self):
        self.run_profile(r"""
const html = p.run('document.getElementById("family-comparison").innerHTML');
assert.ok(html.includes('2 distinct linked records'), 'Unknown field and partial year must match the visible All controls');
p.history.replaceState(null, '', '/profile.html?family=one&compare=two&year=2030');
p.run('renderComparison(data.models.families[0], data.discoveries, data.models)');
assert.ok(p.run('document.getElementById("family-comparison").innerHTML').includes('2 distinct linked records'), 'Unknown year alone must also match the visible All years control');
p.history.replaceState(null, '', '/profile.html?family=one&compare=two&field=biology&year=2025');
p.run('data.discoveries.push({...data.discoveries[0], id:"unlinked", field:"biology"}); renderComparison(data.models.families[0], data.discoveries, data.models)');
assert.ok(p.run('document.getElementById("family-comparison").innerHTML').includes('0 distinct linked records'), 'A valid empty selection must remain empty');
""")

    def test_comparison_excerpts_preserve_stored_caveats(self):
        self.run_profile(r"""
p.history.replaceState(null, '', '/profile.html?family=one&compare=two');
p.run('renderComparison(data.models.families[0], data.discoveries, data.models)');
const html = p.run('document.getElementById("family-comparison").innerHTML');
assert.ok(html.includes('First limit') && html.includes('&lt;Unresolved second limit&gt;'), 'Stored unknowns must accompany tested-result excerpts');
assert.ok(!html.includes('<Unresolved second limit>'));
p.run('data.discoveries[0].evidence = undefined; renderComparison(data.models.families[0], data.discoveries, data.models)');
assert.ok(p.run('document.getElementById("family-comparison").innerHTML').includes('Not annotated in this catalog'));
""")

    def test_family_member_disclosures_are_exposed_by_print_handler(self):
        self.run_profile(r"""
const summary = p.run('familySummary(data.discoveries, "One")');
const comparison = p.run('document.getElementById("family-comparison").innerHTML');
for (const html of [summary, comparison]) {
  assert.ok([...html.matchAll(/<details([^>]*)>/g)].every(match => match[1].includes('source-details')), 'Every exact-member disclosure must use the shared print lifecycle');
}
""")

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
