"""Evidence presentation, selection denominator and optional provenance contracts."""
import copy
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from generate_share import validate_discovery_context, CSV_DISCOVERY, run_catalog_ui, discovery_article, esc


class EvidenceContextTests(unittest.TestCase):
    def test_static_clinical_simulation_and_math_context_preserves_stored_claims(self):
        records = json.loads((ROOT / 'data/discoveries.json').read_text())
        wanted = {'2020-01-cadedb-colonoscopy-adenomas', '2020-10-ferminet', '2024-07-alphaproof-imo'}
        samples = [r for r in records if r['id'] in wanted]
        samples.append(next(r for r in records if r.get('evidence', {}).get('tested') == r['summary']))
        self.assertEqual(len(samples), 4)
        ui = run_catalog_ui(samples)
        for record in samples:
            with self.subTest(record=record['id']):
                article = discovery_article(record, None, ui[record['id']])
                visible_context = article.split('<details')[0]
                self.assertIn('Source check:</b> Source checked' if record['verification_status'] == 'verified' else 'Source check:</b> Needs source check', visible_context)
                for key in ('tested', 'unknown', 'ai_role'):
                    self.assertIn(esc(record['evidence'][key]), visible_context)
                self.assertEqual(article.count(esc(record['evidence']['tested'])), 1)
                self.assertNotIn('chiuso', article)

    def test_optional_annotations_require_sources_targets_and_honest_dates(self):
        records = [{'id': 'a', 'follow_up': [{'id': 'journal', 'kind': 'publication', 'date': '2025', 'date_precision': 'year', 'note': 'Journal version, not replication.', 'source_urls': ['https://example.org/paper'], 'recorded_date': '2026-11-16'}], 'relationships': [{'type': 'extends', 'target_id': 'b', 'reason': 'Extends the stated result.', 'source_urls': ['https://example.org/paper']}]}, {'id': 'b'}]
        validate_discovery_context(records)
        for field, value in [('date', '2025-01-01'), ('source_urls', []), ('source_urls', ['https://example.org/path with space']), ('date', '2025-13'), ('kind', 'confirmed')]:
            bad = copy.deepcopy(records)
            bad[0]['follow_up'][0][field] = value
            with self.assertRaises(ValueError):
                validate_discovery_context(bad)
        bad = copy.deepcopy(records)
        bad[0]['relationships'][0]['target_id'] = 'missing'
        with self.assertRaises(ValueError):
            validate_discovery_context(bad)

    def test_shared_rendering_selection_counts_and_export_columns(self):
        code = r'''
require('./assets/catalog-ui.js'); const assert = require('node:assert/strict'); const ui = CatalogUI;
assert.equal(ui.contextDate('2025'), '2025');
assert.equal(ui.contextDate('2025-03'), 'Mar 2025');
assert.equal(ui.contextDate('2025-03-04'), '4 Mar 2025');
assert.equal(ui.contextDate(null), 'Date unknown');
const rows = Array.from({length: 45}, (_, i) => ({id:String(i), relevance:{impact:1,validation:1,novelty:1}, evidence:i < 42 ? {test_type:'direct test',publication_status:'Preprint'} : undefined}));
assert.deepEqual(ui.selectionCounts(rows,'test_type'), [['direct test',42],['Not annotated in this catalog',3]]);
assert.deepEqual(ui.selectionCounts([],'test_type'), []);
assert.equal(ui.evidenceValue({evidence:{test_type:'not reported'}},'test_type'),'Test context unspecified in annotation');
const html = ui.sourceDetails(rows[0]);
assert.ok(html.indexOf('Evidence sources and annotation context') < html.indexOf('editorial details'));
assert.ok(html.includes('Review scope and date are not recorded'));
assert.ok(html.includes('No follow-up recorded; this is not a claim that no follow-up exists'));
assert.equal(ui.historyBlock({}), '', 'Compact lists must not repeat empty history controls');
assert.ok(!html.includes('<summary>Follow-up and relationships</summary>'));
assert.ok(ui.historyBlock({follow_up_review:{date:'2026-11-18',scope:'Primary publication'}}).includes('Primary publication'), 'An actual bounded review must remain visible even without events');
assert.deepEqual(ui.reviewCoverage([{verification_status:'verified',evidence:{},source_review:{date:'2026-11-18',scope:'Abstract'}},{verification_status:'needs verification',evidence:{}},{verification_status:'verified',source_review:{date:'2026-11-18'}}]), {total:3,annotated:2,reviewed:1,checked:2});
assert.deepEqual(ui.reviewCoverage([]), {total:0,annotated:0,reviewed:0,checked:0});
assert.ok(ui.sourceBadge({verification_status:'needs verification'}).includes('Needs source check'));
const context = ui.readingContext({summary:'Same measured result',evidence:{tested:'Same measured result',ai_role:'AI <screening>',unknown:'Clinical benefit not assessed'}});
assert.ok(context.includes('AI &lt;screening&gt;') && context.includes('Clinical benefit not assessed'));
assert.ok(!context.includes('Same measured result'), 'A tested field identical to the displayed finding must not be repeated');
assert.ok(ui.evidenceBlock({evidence:{unknown:'Not reported.'}}).includes('not a scientific finding of absence'), 'Punctuated legacy gaps must retain the review limitation');
assert.ok(ui.evidenceBlock({evidence:{ai_role:'Not reported'}}).includes('not a scientific finding of absence'), 'Legacy AI-role gaps use the same warning');
assert.ok(!ui.evidenceBlock({evidence:{unknown:'Not stated in the reviewed material'}}).includes('legacy label'), 'Explicit review gaps must keep their narrower meaning');
assert.ok(!ui.evidenceBlock({evidence:{tested:'Measured result'}}).includes('legacy label'), 'Absent AI-role text must not invent a legacy label');

const history = ui.historyBlock({id:'a', follow_up:[{id:'x',kind:'publication',date:'2025',note:'<unsafe>',recorded_date:'2026-11-16',source_urls:['javascript:bad','https://example.org']}],relationships:[{type:'extends',target_id:'b',reason:'bounded',source_urls:[]}]});
assert.ok(history.includes('&lt;unsafe&gt;') && !history.includes('javascript:'));
assert.ok(history.includes('share/b.html') && history.includes('do not merge catalog counts'));
process.stdout.write(JSON.stringify(ui.csvColumns));
'''
        result = subprocess.run(['node', '-e', code], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout), CSV_DISCOVERY)
        source = (ROOT / 'index.html').read_text()
        self.assertLess(source.index('CatalogUI.selectionCounts(out, key)'), source.index('out = out.slice(0, limite)'))
        for key in ('test', 'publication'):
            self.assertIn(f'pick("{key}"', source)
            self.assertIn(f'["{key}", state.{key}]', source)

    def test_current_catalog_optional_annotations_validate(self):
        records = json.loads((ROOT / 'data/discoveries.json').read_text()) + json.loads((ROOT / 'data/archived-discoveries.json').read_text())
        validate_discovery_context(records)
