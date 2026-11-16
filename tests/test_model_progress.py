"""Model-progress import and descriptive comparison regressions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('model_progress_import', ROOT / 'scripts/import_model_progress.py')
IMPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(IMPORT)


class ModelProgressTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads((ROOT / 'data/model-progress.json').read_text())
        cls.models = {r['id']: r for r in cls.data['models']}

    def test_source_snapshot_preserves_versions_missingness_and_configurations(self):
        self.assertEqual(len(self.models), 569)
        self.assertEqual(sum(r['eci'] is not None for r in self.models.values()), 207)
        self.assertEqual(len(self.data['labs']), 8)
        self.assertTrue({'GPT-6 Astra', 'GPT-6.1 Sol', 'GPT-6.1 Terra', 'GPT-6 Luna'} <= self.models.keys())
        self.assertEqual(self.data['unmatched_benchmark_rows'], {})
        self.assertIn('CC BY 4.0', self.data['license'])
        for record in self.models.values():
            if record['eci'] is not None:
                if record['eci_low'] is not None:
                    self.assertLessEqual(record['eci_low'], record['eci'])
                if record['eci_high'] is not None:
                    self.assertGreaterEqual(record['eci_high'], record['eci'])
            for benchmark in record['benchmarks'].values():
                self.assertEqual(benchmark['score'], max(c['score'] for c in benchmark['configurations']))
                self.assertTrue(any(c['variant'] == benchmark['variant'] and c['score'] == benchmark['score'] for c in benchmark['configurations']))
        self.assertTrue(any(r['eci'] is None for r in self.models.values()))

    def test_existing_requested_lab_catalog_releases_are_retained(self):
        original = json.loads((ROOT / 'data/models.json').read_text())['models']
        expected = {r['name'] for r in original if IMPORT.lab_for(r['organization'])}
        retained = {r['name'] for m in self.models.values() for r in m['catalog_releases']}
        self.assertLessEqual(expected, retained)

    def test_source_numbers_reject_nonfinite_and_keep_zero(self):
        self.assertIsNone(IMPORT.number(''))
        self.assertEqual(IMPORT.number('0'), 0)
        for value in ('nan', 'inf', '-inf'):
            with self.assertRaises(ValueError):
                IMPORT.number(value)
        self.assertIsNone(IMPORT.lab_for('OpenAI; Anthropic'))
        self.assertEqual(IMPORT.lab_for('Google DeepMind'), 'Google DeepMind')

    def test_comparison_facts(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node is unavailable')
        code = r"""
const assert=require('node:assert/strict');
const {comparisonFacts,linkedComparison}=require('./assets/model-progress-facts.js');
const tasks=[{id:'a'},{id:'b'},{id:'c'},{id:'d'}];
const a={id:'base',lab:'Lab',date:'2026-09-22',date_basis:'Release',eci:163.75,eci_low:161.33,eci_high:166.42,benchmarks:{a:{score:0},b:{score:90},c:{score:50}}};
const b={id:'new',lab:'Lab',date:'2026-09-29',date_basis:'Release',eci:168.48,eci_low:165.49,eci_high:171.8,benchmarks:{a:{score:10},b:{score:80},c:{score:50}}};
const linked=linkedComparison(new URLSearchParams('model=new'),[b,a],'2025-11-16');
assert.deepEqual(linked,{model:'new',baseline:'base',lab:'Lab',period:'recent'});
assert.equal(linkedComparison(new URLSearchParams('model=missing'),[a,b],'2025-11-16'),null);
assert.equal(linkedComparison(new URLSearchParams('model=new&baseline=base'),[a,{...b,lab:'Other'}],'2025-11-16').lab,'All labs');
assert.equal(linkedComparison(new URLSearchParams('model=new&baseline='),[a,b],'2025-11-16').baseline,'');
assert.equal(linkedComparison(new URLSearchParams('model=new'),[{...b,date:'2020-01-01'}],'2025-11-16').period,'all');
assert.equal(linkedComparison(new URLSearchParams('model=new&period=recent'),[{...b,date:'2020-01-01'}],'2025-11-16').period,'recent');
assert.equal(linkedComparison(new URLSearchParams('model='+encodeURIComponent('Exact + / model')),[{...b,id:'Exact + / model'}],'2025-11-16').model,'Exact + / model');
const f=comparisonFacts(a,b,tasks);
assert.ok(Math.abs(f.delta-4.73)<1e-9);
assert.equal(f.signedDays,7);
assert.deepEqual([f.common,f.higher,f.lower,f.unchanged],[3,1,1,1]);
assert.equal(f.intervalsOverlap,true);
assert.equal(comparisonFacts(b,a,tasks).signedDays,-7);
assert.equal(comparisonFacts(a,{...b,eci:null,eci_low:null},tasks).delta,null);
assert.equal(comparisonFacts(a,{...b,eci_low:null},tasks).intervalsOverlap,null);
assert.equal(comparisonFacts(a,{...b,date:a.date},tasks).signedDays,0);
assert.equal(comparisonFacts(a,{...b,lab:'Other'},tasks).differentLabs,true);
assert.equal(comparisonFacts(a,{...b,date_basis:'Publication'},tasks).differentDateBases,true);
assert.equal(comparisonFacts(a,a,tasks).sameModel,true);
assert.equal(comparisonFacts(a,{...b,eci_low:170,eci_high:175},tasks).intervalsOverlap,false);
assert.equal(comparisonFacts(null,b,tasks).delta,null);
"""
        subprocess.run([node, '-e', code], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_cadence_dates_and_cross_lab_selection(self):
        code = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const {linkedComparison}=require('./assets/model-progress-facts.js');
const elements=new Map();
const context=vm.createContext({linkedComparison,URLSearchParams,console,document:{activeElement:{id:''},getElementById(id){if(!elements.has(id))elements.set(id,{});return elements.get(id);}}});
const renderer=fs.readFileSync('assets/model-progress.js','utf8').split("document.addEventListener('click'")[0];
vm.runInContext(renderer,context);
context.snapshot=JSON.parse(fs.readFileSync('data/model-progress.json','utf8'));
vm.runInContext(`D=snapshot;models=D.models;lookup=new Map(models.map(m=>[m.id,m]));start='2025-11-16';end=D.fetched_on;computeCadence();showCadence('Anthropic');render=()=>{};chooseModel(models.findIndex(m=>m.lab==='Anthropic'));`,context);
const html=elements.get('cadence').innerHTML;
assert.ok(html.includes('16 Nov 2025')&&html.includes('16 Nov 2026'));
assert.ok(!html.includes('${'));
assert.equal(vm.runInContext('state.lab',context),'All labs');
assert.equal(vm.runInContext('lookup.get(state.baseline).lab',context),'OpenAI');
assert.equal(vm.runInContext('lookup.get(state.model).lab',context),'Anthropic');
vm.runInContext(`const shared=new URLSearchParams({model:state.model,baseline:state.baseline,lab:state.lab,period:state.period});const restored=linkedComparison(shared,models,start);if(JSON.stringify(restored)!==JSON.stringify({model:state.model,baseline:state.baseline,lab:state.lab,period:state.period}))throw Error('Shared selection changed');`,context);
"""
        subprocess.run(['node', '-e', code], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_public_page_uses_production_assets(self):
        html = (ROOT / 'model-progress.html').read_text()
        self.assertNotIn('plans/', html)
        self.assertNotIn('noindex', html)
        self.assertNotIn('<base ', html)
        self.assertIn('model-progress.html', html)
        for asset in ('model-progress.js', 'model-progress-facts.js'):
            digest = hashlib.sha256((ROOT / 'assets' / asset).read_bytes()).hexdigest()[:12]
            self.assertIn(f'assets/{asset}?v={digest}', html)
