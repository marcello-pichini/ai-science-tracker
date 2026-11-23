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
assert.equal(u.searchParams.get('entry'), 'https://aisciencetracker.org/share/test%20%26%20%CE%B1%3F.html');
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

    def test_source_links_describe_versions_and_hide_duplicates(self):
        self.run_js('''
const article = 'https://doi.org/10.1234/example';
const preprint = 'https://arxiv.org/abs/2601.00001';
const evidence = {publication_status: 'Peer-reviewed paper'};
const render = (source_url, source_type, paper_url) => ui.sourceLinks({source_url, source_type, paper_url, evidence});
const separate = render(preprint, 'paper', article);
assert.ok(separate.includes(preprint + '\\" rel=\\"noopener\\">Preprint</a>'));
assert.ok(separate.includes(article + '\\" rel=\\"noopener\\">Published article</a>'));
assert.equal(render(article, 'paper', article).match(/<a /g).length, 1);
assert.ok(render('https://example.org/news?x=1&y=2', 'press release', article).includes('x=1&amp;y=2\\" rel=\\"noopener\\">Press release</a>'));
assert.ok(ui.sourceLinks({source_url: article, source_type: 'paper'}).includes('Scientific article'));
const doiVersions = ui.sourceLinks({source_url: 'https://doi.org/10.64898/2026.01.29.702616', source_type: 'paper', paper_url: article, evidence: {publication_status: 'Preprint'}});
assert.ok(doiVersions.includes(article + '\\" rel=\\"noopener\\">Scientific article</a>'));
assert.ok(!ui.sourceLinks({source_url: 'https://doi.org/10.1101/gad.123456', source_type: 'paper', evidence}).includes('Preprint'));

''')

    def test_csv_export_escapes_and_blocks_formula_cells(self):
        self.run_js('''
const r = {id:'a', title:'=HYPERLINK("x")', summary:'one, "two"\\nthree', field:'biology', ai_technology:'', organization:'Org', source_url:'https://e.org', source_type:'blog', publication_date:'2025-01-02', added_date:'2025-01-03', verification_status:'verified', paper_url:'', relevance:{impact:5,validation:4,novelty:3}};
const lines = ui.toCsv([r]);
assert.ok(lines.startsWith(ui.csvColumns.join(',') + '\\r\\n'));
assert.ok(lines.includes("'=HYPERLINK(\\"\\"x\\"\\")"));
assert.ok(lines.includes('"one, ""two""\\nthree"'));
assert.ok(lines.includes('https://aisciencetracker.org/share/a.html'));
''')

    def test_reference_has_no_invented_metadata_and_field_year_counts(self):
        self.run_js('''
const r = {id:'x y', title:'T', organization:'O', publication_date:'2025-02-03', source_url:'https://e.org/s'};
const text = ui.reference(r, '13 Nov 2026');
assert.equal(text, 'T. O, announced 3 Feb 2025. Source: https://e.org/s. Catalog entry: AI Science Tracker, https://aisciencetracker.org/share/x%20y.html (accessed 13 Nov 2026).');
const m = ui.fieldYear([{field:'b', publication_date:'2021-01-01'}, {field:'b', publication_date:'2021-05-01'}, {field:'c', publication_date:'2020-01-01'}]);
assert.equal(m.cells['b|2021'], 2); assert.deepEqual(m.fields, ['b','c']); assert.deepEqual(m.years, ['2020','2021']);
''')

    def test_source_concentration_counts_hosts_without_www(self):
        self.run_js('''
const r = u => ({source_url:u});
const s = ui.sourceConcentration([r('https://www.a.org/1'), r('https://a.org/2'), r('https://b.org/x'), r('not a url')], 1);
assert.deepEqual(s, {top:1, entries:2, total:4, websites:2});
''')

    def test_evidence_block_is_optional_and_escaped(self):
        self.run_js('''
const base = {verification_status:'verified', source_type:'blog', paper_url:'', relevance:{impact:3,validation:3,novelty:3}};
assert.ok(!ui.sourceDetails(base).includes('Evidence context'));
const html = ui.sourceDetails({...base, evidence:{publication_status:'Preprint', tested:'12 <b>samples</b>', unknown:'Not reported', ai_role:'Not reported', evidence_urls:['https://e.org']}});
assert.ok(html.includes('Evidence context') && html.includes('12 &lt;b&gt;samples&lt;/b&gt;') && html.includes('Preprint'));
assert.ok(html.includes('does not distinguish information absent from reviewed material from information not assessed'));
assert.ok(html.includes('not a scientific finding of absence'));
assert.ok(!ui.sourceDetails({...base, evidence:{publication_status:'Preprint', tested:'12 samples', unknown:'Long-term effects', ai_role:'Candidate selection'}}).includes('legacy label'));
''')

    def test_evidence_sources_link_only_valid_http_urls_and_escape_attributes(self):
        self.run_js(r'''
const html = ui.evidenceBlock({evidence:{publication_status:'Published', tested:'Samples', unknown:'Follow-up', ai_role:'Design',
 evidence_urls:['https://doi.org/10.1038/test?x=1&y="quoted"', 'http://example.org/source', 'javascript:alert(1)', '//example.org', 'https://', 'https://example.org/\" onclick=\"bad']}});
assert.ok(html.includes('href="https://doi.org/10.1038/test?x=1&amp;y=&quot;quoted&quot;"'));
assert.ok(html.includes('href="http://example.org/source"'));
assert.ok(!html.includes('javascript:') && !html.includes('href="//') && !html.includes('href="https://"'));
assert.ok(!html.includes('" onclick="'));
assert.ok(!ui.evidenceBlock({evidence:{evidence_urls:[]}}).includes('Evidence sources:'));
''')

    def test_score_is_capped_by_evidence_and_matches_the_generator(self):
        self.run_js('''
const r = (i, v, n) => ({relevance:{impact:i, validation:v, novelty:n}});
assert.equal(ui.score(r(3, 3, 3)), 60);
assert.equal(ui.score(r(5, 1, 5)), 40);
assert.equal(ui.score(r(5, 2, 5)), 60);
assert.equal(ui.score(r(5, 5, 5)), 100);
''')
        import json, sys
        sys.path.insert(0, str(ROOT / 'scripts'))
        from generate_share import score
        records = json.loads((ROOT / 'data/discoveries.json').read_text())
        js = subprocess.run(['node', '-e', "require('./assets/catalog-ui.js'); const d = require('./data/discoveries.json'); process.stdout.write(JSON.stringify(d.map(r => CatalogUI.score(r))));"],
                            cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertEqual(json.loads(js), [score(r) for r in records])

    def test_citation_line_is_optional_and_never_a_score(self):
        self.run_js('''
assert.equal(ui.citationLine({}), '');
assert.ok(ui.citationLine({citation:{top_1:true, top_10:true, percentile:99.9, cited_by:12}}).includes('top 1%'));
assert.ok(ui.citationLine({citation:{top_1:false, top_10:false, percentile:41.6, cited_by:3}}).includes('percentile 42'));
''')

    def test_organization_delimiter_preserves_institution_names(self):
        self.run_js("""
assert.equal(ui.leadOrganization('Huazhong University of Science and Technology; Sichuan University'), 'Huazhong University of Science and Technology');
assert.equal(ui.leadOrganization('University of California, Berkeley; MIT'), 'University of California, Berkeley');
assert.equal(ui.leadOrganization('Washington and Lee University'), 'Washington and Lee University');
""")

    def test_citation_counts_are_numeric_and_snapshot_provenance_is_visible(self):
        self.run_js("""
const citation = {doi:'10.1234/example', cited_by:12, percentile:91.2, top_1:false, top_10:true, checked:'2026-11-15'};
const html = ui.citationLine({citation});
assert.ok(html.includes('15 Nov 2026'));
assert.ok(html.includes('https://api.openalex.org/works/https://doi.org/10.1234/example'));
assert.ok(html.includes('12 citations'));
assert.equal(ui.citationLine({citation:{...citation,cited_by:'<b>12</b>'}}), '');
assert.equal(ui.citationLine({citation:{...citation,percentile:Infinity}}), '');
assert.equal(ui.citationLine({citation:{...citation,cited_by:-1}}), '');
""")
