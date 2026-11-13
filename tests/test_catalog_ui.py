import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class CatalogUiTests(unittest.TestCase):
    def run_js(self, code):
        self.assertTrue((ROOT / 'assets/catalog-ui.js').is_file(), 'Shared catalog behavior is not implemented yet')
        result = subprocess.run(['node', '-e', "require('./assets/catalog-ui.js'); const assert = require('node:assert/strict'); const ui = globalThis.CatalogUI;\n" + code], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_year_metrics_do_not_confuse_count_with_relevance(self):
        self.run_js('''
const entries = [
 {publication_date:'2021-02-01', relevance:{impact:5,validation:5,novelty:5}},
 {publication_date:'2020-01-01', relevance:{impact:1,validation:2,novelty:4}},
 {publication_date:'2021-01-01', relevance:{impact:1,validation:1,novelty:1}}
];
assert.deepEqual(ui.annualStats(entries), [
 {year:'2020', count:1, mean:47}, {year:'2021',count:2,mean:60}
]);
assert.deepEqual(ui.annualStats([]), []);
''')

    def test_correction_draft_preserves_identifiers_and_does_not_submit(self):
        self.run_js('''
const d = {id:'test & α?', title:'A title & another', source_url:'https://example.org/paper?q=a&b=c'};
const u = new URL(ui.correctionUrl(d));
assert.equal(u.origin, 'https://github.com');
assert.equal(u.pathname, '/marcello-pichini/ai-science-tracker/issues/new');
assert.equal(u.searchParams.get('template'), 'correction.yml');
assert.equal(u.searchParams.get('record_id'), d.id);
assert.equal(u.searchParams.get('source'), d.source_url);
assert.equal(u.searchParams.get('entry'), 'https://marcello-pichini.github.io/ai-science-tracker/index.html#discovery=test%20%26%20%CE%B1%3F');
''')

    def test_correction_prefills_target_required_form_fields(self):
        # Catches a renamed form field that silently drops the record context.
        import re
        form = (ROOT / '.github/ISSUE_TEMPLATE/correction.yml').read_text()
        fields = dict(re.findall(r'(?ms)^    id: (\w+)\n(.*?)(?=^  - type:|\Z)', form))
        for field in ('record_id', 'entry', 'source', 'correction'):
            self.assertIn(field, fields)
            self.assertRegex(fields[field], r'required: true')

    def test_source_details_escape_data_and_keep_verification_distinct(self):
        self.run_js('''
const d = {verification_status:'verified', source_type:'<img src=x onerror=bad>', paper_url:'', relevance:{impact:5,validation:1,novelty:4}};
const html = ui.sourceDetails(d);
assert.ok(html.includes('Source checked'));
assert.ok(html.includes('Independent confirmation is not assessed'));
assert.ok(html.includes('not linked in this catalog'));
assert.ok(html.includes('Impact 5/5'));
assert.ok(html.includes('Validation 1/5'));
assert.ok(!html.includes('<img'));
assert.ok(html.includes('&lt;img'));
assert.ok(ui.sourceDetails({...d,verification_status:'needs verification'}).includes('Needs source check'));
assert.ok(!ui.sourceDetails({...d,paper_url:'https://example.org/preprint'}).includes('peer-reviewed'));
''')

    def test_csv_export_escapes_and_blocks_formula_cells(self):
        self.run_js('''
const r = {id:'a', title:'=HYPERLINK("x")', summary:'one, "two"\\nthree', field:'biology', ai_technology:'', organization:'Org', source_url:'https://e.org', source_type:'blog', publication_date:'2025-01-02', added_date:'2025-01-03', verification_status:'verified', paper_url:'', relevance:{impact:5,validation:4,novelty:3}};
const lines = ui.toCsv([r]);
assert.ok(lines.startsWith(ui.csvColumns.join(',') + '\\r\\n'));
assert.ok(lines.includes("'=HYPERLINK(\\"\\"x\\"\\")"));
assert.ok(lines.includes('"one, ""two""\\nthree"'));
assert.ok(lines.includes('#discovery=a'));
''')

    def test_reference_has_no_invented_metadata_and_field_year_counts(self):
        self.run_js('''
const r = {id:'x y', title:'T', organization:'O', publication_date:'2025-02-03', source_url:'https://e.org/s'};
const text = ui.reference(r, '13 Nov 2026');
assert.equal(text, 'T. O, announced 3 Feb 2025. Source: https://e.org/s. Catalog entry: AI Science Tracker, https://marcello-pichini.github.io/ai-science-tracker/index.html#discovery=x%20y (accessed 13 Nov 2026).');
const m = ui.fieldYear([{field:'b', publication_date:'2021-01-01'}, {field:'b', publication_date:'2021-05-01'}, {field:'c', publication_date:'2020-01-01'}]);
assert.equal(m.cells['b|2021'], 2); assert.deepEqual(m.fields, ['b','c']); assert.deepEqual(m.years, ['2020','2021']);
''')
