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
const {linkedComparison,comparisonFacts}=require('./assets/model-progress-facts.js');
const elements=new Map();
const context=vm.createContext({linkedComparison,comparisonFacts,URLSearchParams,console,document:{activeElement:{id:''},getElementById(id){if(!elements.has(id))elements.set(id,{});return elements.get(id);}}});
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
vm.runInContext(`renderInventory();`,context);
assert.ok(elements.get('model-inventory').innerHTML.includes('Interval unavailable'));
assert.ok(!elements.get('model-inventory').innerHTML.includes('Not available–Not available'));
assert.equal(vm.runInContext('interval({eci_low:null,eci_high:10})',context),'Lower bound unavailable–10');
assert.equal(vm.runInContext('interval({eci_low:0,eci_high:null})',context),'0–Upper bound unavailable');
vm.runInContext(`state.lab='All labs';state.baseline=models.find(m=>m.lab==='Anthropic').id;chooseModel(models.findIndex(m=>m.lab==='Anthropic'&&m.id!==state.baseline));`,context);
assert.equal(vm.runInContext('state.lab',context),'All labs');
vm.runInContext(`const unscored=models.find(m=>m.eci==null);renderReadout(unscored,unscored);`,context);
assert.ok(elements.get('comparison-readout').innerHTML.includes('ECI comparison is unavailable'));
assert.ok(!elements.get('comparison-readout').innerHTML.includes('difference is zero'));
vm.runInContext('renderReadout(undefined,models[0]);',context);
assert.ok(elements.get('comparison-readout').innerHTML.includes('Choose a baseline and a comparison model'));
assert.ok(!elements.get('comparison-readout').innerHTML.includes('ECI comparison is unavailable'));
const labels=[{x:161.42,width:232.51,anchor:'end'},{x:145.31,width:218.5,anchor:'start'}].map(data=>({...data,
  getBBox(){return {x:this.x-(this.anchor==='end'?this.width:0),width:this.width};},
  getAttribute(){return this.x;},setAttribute(key,value){this[key]=value;}}));
context.plotLabels=labels;
vm.runInContext("fitPlotLabels({querySelectorAll(){return plotLabels;}},297);",context);
assert.ok(labels.every(label=>label.getBBox().x>=4&&label.getBBox().x+label.width<=293),'Long selected model labels must remain inside the chart');
"""
        subprocess.run(['node', '-e', code], cwd=ROOT, check=True, capture_output=True, text=True)

    def test_cadence_click_preserves_keyboard_focus(self):
        code = r"""
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const elements=new Map(),handlers={},body={id:''};
const document={activeElement:body,addEventListener(type,fn){handlers[type]=fn;},getElementById(id){
  if(!elements.has(id))elements.set(id,{id,focus(){document.activeElement=this;}});
  return elements.get(id);
}};
Object.defineProperty(document.getElementById('cadence'),'innerHTML',{set(html){this.html=html;document.activeElement=body;}});
const context=vm.createContext({document,console});
vm.runInContext(fs.readFileSync('assets/model-progress.js','utf8').split("document.addEventListener('keydown'")[0],context);
context.snapshot=JSON.parse(fs.readFileSync('data/model-progress.json','utf8'));
vm.runInContext(`D=snapshot;models=D.models;start='2025-11-16';end=D.fetched_on;computeCadence();showCadence('OpenAI');`,context);
const firstDate=vm.runInContext(`cadenceStats.find(s=>s.lab==='Anthropic').dates[0]`,context);
for(const [id,dataset] of [['cadence-lab-2',{cadence:'Anthropic'}],['cadence-date-2-0',{cadence:'Anthropic',date:firstDate}]]){
  assert.ok(elements.get('cadence').html.includes('id="'+id+'"'),'Cadence controls need stable focus targets');
  const control=document.getElementById(id);control.dataset=dataset;document.activeElement=control;
  handlers.click({target:{closest(){return control;}}});
  assert.equal(document.activeElement.id,id,'Activating cadence must preserve the active control');
}
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
