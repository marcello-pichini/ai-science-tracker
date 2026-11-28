"""Coherent raw-byte snapshots, exact aliases and changed-review provenance."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from dataset_manifest import build_manifest, stamp_pages, write_component_jsonld, write_discovery_list
from validate_review_patch import validate_review_patch
from entities import organization


class DatasetTrustTests(unittest.TestCase):
    def node(self, code):
        result = subprocess.run(['node', '-e', code], cwd=ROOT, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_bytes_retry_as_a_whole_then_search_current_exact_doi(self):
        self.node(r'''
const assert=require('node:assert/strict'), crypto=require('node:crypto');
const loader=require('./assets/catalog-data.js'); require('./assets/catalog-search.js');
const current=[{id:'new',title:'New result',source_url:'https://doi.org/10.64898/2026.10.21.755545'}];
const bytes=Buffer.from(JSON.stringify(current)), old=Buffer.from('[]');
const sha=crypto.createHash('sha256').update(bytes).digest('hex');
const m={schema_version:1,snapshot_sha256:'a'.repeat(64),components:{discoveries:{path:'data/discoveries.json',sha256:sha,bytes:bytes.length}}};
let dataCalls=0, calls=[];
const fetch=async (url, options)=>{
 calls.push(url);
 if(new URL(url).pathname.endsWith('manifest.json')){assert.equal(options.cache,'no-store');return {ok:true,json:async()=>m};}
 assert.equal(new URL(url).searchParams.get('v'),sha);
 assert.equal(options.cache,dataCalls===0?'default':'reload','Cached data first, bypass the cache on retry');
 return {ok:true,arrayBuffer:async()=>Uint8Array.from(++dataCalls===1?old:bytes).buffer};
};
(async()=>{
 const loaded=await loader.load(['discoveries'],{fetch,crypto:crypto.webcrypto});
 assert.equal(dataCalls,2);assert.equal(loaded.recovered,true);assert.equal(loaded.hashes.discoveries,sha);
 const results=CatalogSearch.collections(loaded.data.discoveries,[],{models:[],families:[]},{models:[]});
 assert.equal(results[0].records.filter(r=>CatalogSearch.match(r.fields,'10.64898/2026.10.21.755545').length).length,1);
 const target={dataset:{}};loader.observe(target,loaded);assert.equal(target.dataset.componentSha256,JSON.stringify({discoveries:sha}));
 assert.equal(target.dataset.snapshotSha256,m.snapshot_sha256);assert.equal(target.dataset.loadState,'ready');
 let rejected=0;await assert.rejects(loader.load(['discoveries'],{crypto:crypto.webcrypto,fetch:async url=>new URL(url).pathname.endsWith('manifest.json')?{ok:true,json:async()=>m}:{ok:true,arrayBuffer:async()=>{rejected++;return Uint8Array.from(old).buffer;}}}),/mismatch/);
 assert.equal(rejected,2,'Persistent stale bytes must stop after two attempts');
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_manifest_drift_discards_first_set_and_failures_are_bounded(self):
        self.node(r'''
const assert=require('node:assert/strict'),crypto=require('node:crypto'),loader=require('./assets/catalog-data.js');
const bytes=Buffer.from('[]'),sha=crypto.createHash('sha256').update(bytes).digest('hex');
const manifest=id=>({schema_version:1,snapshot_sha256:id.repeat(64),components:{discoveries:{path:'data/discoveries.json',sha256:sha,bytes:bytes.length}}});
(async()=>{
 let n=0,values=0;
 const loaded=await loader.load(['discoveries'],{crypto:crypto.webcrypto,fetch:async url=>new URL(url).pathname.endsWith('manifest.json')?{ok:true,json:async()=>manifest(++n===1?'a':'b')}:{ok:true,arrayBuffer:async()=>{values++;return Uint8Array.from(bytes).buffer;}}});
 assert.equal(loaded.snapshot,'b'.repeat(64));assert.equal(values,2);assert.deepEqual(loaded.data.discoveries,[]);
 let attempts=0;await assert.rejects(loader.load(['discoveries'],{crypto:crypto.webcrypto,fetch:async()=>{attempts++;return {ok:false};}}),/manifest unavailable/);assert.equal(attempts,2);
 await assert.rejects(loader.load(['discoveries'],{crypto:{},fetch:()=>assert.fail('No request without SHA256')}),/Secure SHA-256/);
 assert.throws(()=>loader.validateManifest({...manifest('a'),components:{x:{path:'../private.json',sha256:sha,bytes:2}}}),/descriptor/);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_failure_ui_clears_old_results_disables_controls_and_retry_recovers(self):
        self.node(r'''
const assert=require('node:assert/strict'),crypto=require('node:crypto');
const nodes=new Map();
function node(id=''){return {id,dataset:{},disabled:false,children:[],textContent:'',handlers:{},setAttribute(){},addEventListener(k,v){this.handlers[k]=v;},append(...items){this.children.push(...items);},before(v){nodes.set(v.id,v);},replaceChildren(...items){this.children=items;this.textContent='';}};}
const control=node('control');const main=node('main');const root=node('html');
global.document={currentScript:null,documentElement:root,getElementById:id=>nodes.get(id),createElement:()=>node(),createTextNode:text=>({textContent:text}),querySelector:()=>main,querySelectorAll:()=>[control]};
global.crypto=crypto.webcrypto;
const loader=require('./assets/catalog-data.js');
const bytes=Buffer.from('[]'),sha=crypto.createHash('sha256').update(bytes).digest('hex');
const m={schema_version:1,snapshot_sha256:'c'.repeat(64),components:{discoveries:{path:'data/discoveries.json',sha256:sha,bytes:bytes.length}}};
let broken=true,oldResults=['old'],rendered=0;
global.fetch=async url=>new URL(url).pathname.endsWith('manifest.json')?{ok:true,json:async()=>m}:{ok:true,arrayBuffer:async()=>Uint8Array.from(broken?Buffer.from('[ ]'):bytes).buffer};
(async()=>{
 await loader.run(['discoveries'],()=>{rendered++;oldResults=['current'];},{clear:()=>{oldResults=[];}});
 assert.equal(rendered,0);assert.deepEqual(oldResults,[]);assert.equal(root.dataset.loadState,'failed');assert.equal(control.disabled,true);assert.equal(root.dataset.snapshotSha256,undefined);
 const status=nodes.get('data-snapshot-status');assert.ok(status.children[0].textContent.includes('consistent data snapshot could not be loaded'));
 const retry=status.children.find(n=>n.textContent==='Retry');assert.ok(retry.handlers.click);broken=false;await retry.handlers.click();
 assert.equal(root.dataset.loadState,'ready');assert.equal(control.disabled,false);assert.deepEqual(oldResults,['current']);assert.equal(rendered,1);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_progress_late_failure_rolls_back_shared_loader_and_swe_then_recovers(self):
        self.node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),crypto=require('node:crypto');
const nodes=new Map(),created=[],events={},errors=[];
function detach(node){node.connected=false;for(const child of node.children)detach(child);if(nodes.get(node.id)===node)nodes.delete(node.id);}
function make(id='',tag='div',inMain=true){
 let html='',text='';
 const n={id,tag,inMain,connected:true,dataset:{},disabled:false,value:'',children:[],handlers:{},clientWidth:400,
  setAttribute(k,v){this[k]=v;},addEventListener(k,f){this.handlers[k]=f;},focus(){document.activeElement=this;},
  append(...xs){for(const x of xs){x.inMain=this.inMain;x.connected=true;this.children.push(x);}},before(x){x.inMain=false;x.connected=true;nodes.set(x.id,x);},
  replaceChildren(...xs){for(const child of this.children)detach(child);this.children=[];html='';text='';this.append(...xs);},
  querySelector(){return {querySelectorAll(){return [];}};},querySelectorAll(){return [];}};
 Object.defineProperty(n,'innerHTML',{get(){return html;},set(value){this.replaceChildren();html=value;
  for(const m of value.matchAll(/<(button|select|input|svg|g)[^>]*\bid="([^"]+)"[^>]*>/g)){
   const child=make(m[2],m[1],this.inMain);child.disabled=/\bdisabled\b/.test(m[0]);
   for(const d of m[0].matchAll(/data-([a-z]+)="([^"]*)"/g))child.dataset[d[1]]=d[2];this.children.push(child);
  }
 }});
 Object.defineProperty(n,'textContent',{get(){return text;},set(value){this.replaceChildren();text=String(value);}});
 if(id)nodes.set(id,n);created.push(n);return n;
}
const body=make('body','body',false),root=make('html','html',false),main=make('main');
const document={currentScript:{src:'https://example.org/assets/catalog-data.js'},documentElement:root,activeElement:body,
 getElementById:id=>nodes.get(id),createElement:tag=>make('',tag,false),createTextNode:text=>{const n=make('','text',false);n.textContent=text;return n;},
 querySelector:()=>main,querySelectorAll:()=>[...nodes.values()].filter(n=>n.connected&&n.inMain&&['button','select','input'].includes(n.tag)),
 addEventListener(k,f){events[k]=f;}};
const html=fs.readFileSync('model-progress.html','utf8');
for(const m of html.matchAll(/<([a-z]+)[^>]*\bid="([^"]+)"[^>]*>/g)){const n=make(m[2],m[1]);n.disabled=/\bdisabled\b/.test(m[0]);}
const location=new URL('https://example.org/model-progress.html?model=GPT-6.1+Sol&baseline=GPT-6+Sol');
let fresh=false;
function payload(){
 const metric={id:'fixture',name:'Fixture metric',license:'MIT',retrieved_on:'2026-11-18',records:[{id:'source-row',model:'Exact metric label',value:fresh?3:1,unit:'points',direction:'Higher is better',comparison_group:'Original slice',date:null,date_basis:'Not reported',details:{},source_url:'https://example.org/metric'}]};
 const registry={sources:[{id:metric.id,name:metric.name,license:metric.license,record_count:1,sha256:crypto.createHash('sha256').update(JSON.stringify(metric)).digest('hex'),path:'data/benchmarks/fixture.json',source_url:'https://example.org/metric',license_url:'https://example.org/license',license_notice:'docs/license.txt'}]};
 const model=(id,name,eci)=>({id,name,lab:'OpenAI',date:'2026-11-01',date_basis:'Source date',eci,eci_low:eci-1,eci_high:eci+1,benchmarks:{task:{score:0,variant:'exact run'}},variants:[],catalog_releases:[]});
 return {'benchmark-registry':registry,'benchmark-fixture':metric,'model-progress':{fetched_on:'2026-11-18',labs:['OpenAI'],benchmarks:[{id:'task',name:'Task',domain:'Code'}],source_url:'https://example.org/source',models:[model('GPT-6 Sol','Baseline model',10),model('GPT-6.1 Sol',fresh?'Recovered model':'Failed model',fresh?30:20)]},
 'swe-bench':{fetched_on:'2026-11-18',records:[{id:fresh?'fresh-run':'old-run',name:fresh?'Fresh SWE':'Failed SWE',agent_version:'2.0',score:fresh?99:12,mean_cost_usd:null,evaluation_date:'2026-02-26',settings:[]}]}};
}
const fetch=async url=>{
 const data=payload(),raw=Object.fromEntries(Object.entries(data).map(([k,v])=>[k,Buffer.from(JSON.stringify(v))]));
 const components=Object.fromEntries(Object.entries(raw).map(([id,b])=>[id,{path:id.startsWith('benchmark-')?'data/benchmarks/'+(id==='benchmark-registry'?'index':id.slice(10))+'.json':'data/'+id+'.json',group:id.startsWith('benchmark-')?'public-benchmarks':undefined,bytes:b.length,sha256:crypto.createHash('sha256').update(b).digest('hex')}]));
 if(new URL(url).pathname.endsWith('manifest.json'))return {ok:true,json:async()=>({schema_version:1,snapshot_sha256:(fresh?'f':'a').repeat(64),components})};
 const part=new URL(url).pathname.split('/').at(-1).replace('.json','');const id=new URL(url).pathname.includes('/benchmarks/')?(part==='index'?'benchmark-registry':'benchmark-'+part):part;assert.equal(new URL(url).searchParams.get('v'),components[id].sha256);
 return {ok:true,arrayBuffer:async()=>Uint8Array.from(raw[id]).buffer};
};
const context=vm.createContext({document,location,history:{replaceState(_a,_b,url){location.href=new URL(url,location).href;}},fetch,crypto:crypto.webcrypto,URL,URLSearchParams,TextDecoder,AbortController,setTimeout,clearTimeout,Intl,console:{error:e=>errors.push(e)},window:{addEventListener(){}},matchMedia:()=>({matches:false})});
for(const path of ['assets/catalog-data.js','assets/model-progress-facts.js','assets/swe-bench.js','assets/public-benchmarks.js','assets/model-progress.js'])vm.runInContext(fs.readFileSync(path,'utf8'),context);
vm.runInContext("state.query='model';$('model-search').value='model'; const realShowCadence=showCadence; showCadence=(...args)=>{realShowCadence(...args);throw Error('late cadence layout failure');};",context);
const waitFor=async state=>{const deadline=Date.now()+1500;while(root.dataset.loadState!==state&&Date.now()<deadline)await new Promise(r=>setTimeout(r,1));assert.equal(root.dataset.loadState,state);};
(async()=>{
 await waitFor('failed');
 assert.equal(vm.runInContext('D',context),null);assert.equal(vm.runInContext('models.length+lookup.size+cadenceStats.length',context),0);
 assert.equal(vm.runInContext('start===undefined&&end===undefined&&selectedDay===null&&selectedCadence===null',context),true);
 for(const id of ['comparison','lab-tabs','comparison-presets','plot-data','selection-coverage','plot-caption','model-history','swe-results','swe-count','metric-context','metric-results','metric-directory','cadence','release-list'])assert.equal(nodes.get(id).innerHTML,'',id);
 assert.ok(created.some(n=>n.id==='baseline-model'),'Real comparison renderer must create controls before the injected late failure');
 for(const n of created.filter(n=>['baseline-model','comparison-model','lab-0','preset-0','date-picker','row-0'].includes(n.id)))assert.equal(n.disabled,true,'Failed dynamic control: '+n.id);
 assert.ok(document.querySelectorAll().every(n=>n.disabled));assert.equal(root.dataset.snapshotSha256,undefined);
 nodes.get('metric-search').handlers.input();nodes.get('metric-source').handlers.change();assert.equal(nodes.get('metric-results').innerHTML,'','Metric private data must be discarded');
 nodes.get('swe-version').handlers.change();assert.equal(nodes.get('swe-results').innerHTML,'','SWE private data must be reset, not just hidden');
 assert.doesNotThrow(()=>events.click({target:{closest:()=>created.find(n=>n.id==='row-0')}}));
 const status=nodes.get('data-snapshot-status'),retry=status.children.find(n=>n.textContent==='Retry');assert.equal(retry.disabled,false);
 fresh=true;vm.runInContext('showCadence=realShowCadence;',context);retry.handlers.click();await waitFor('ready');
 assert.equal(root.dataset.snapshotSha256,'f'.repeat(64));assert.equal(vm.runInContext('lookup.get("GPT-6.1 Sol").eci',context),30);
 assert.ok(nodes.get('comparison').innerHTML.includes('Recovered model'));assert.ok(!nodes.get('comparison').innerHTML.includes('Failed model'));
 assert.ok(nodes.get('metric-results').innerHTML.includes('Exact metric label'));assert.ok(nodes.get('metric-results').innerHTML.includes('3 points'));
 assert.ok(JSON.parse(root.dataset.componentSha256)['benchmark-fixture']);
 assert.ok(nodes.get('swe-results').innerHTML.includes('Fresh SWE'));assert.ok(!nodes.get('swe-results').innerHTML.includes('Failed SWE'));
 for(const id of ['theme','lab-select','baseline-model','comparison-model','swe-search','swe-version','metric-source','metric-slice','metric-search'])assert.equal(nodes.get(id).disabled,false,id+' must recover');
 assert.equal(vm.runInContext('state.query',context),'model');assert.equal(nodes.get('model-search').value,'model');assert.deepEqual(errors,[]);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_same_manifest_attempt_resolves_benchmark_group_and_retries_all_members(self):
        self.node(r'''
const assert=require('node:assert/strict'),crypto=require('node:crypto'),loader=require('./assets/catalog-data.js');
let fresh=false;const counts={};
const files=()=>({'model-progress':{models:[]},'benchmark-registry':{sources:[{id:'first'},...(fresh?[{id:'second'}]:[])]},'benchmark-first':{records:[{value:0}]},...(fresh?{'benchmark-second':{records:[{value:2}]}}:{})});
const raw=()=>Object.fromEntries(Object.entries(files()).map(([id,v])=>[id,Buffer.from(JSON.stringify(v))]));
const descriptor=(id,bytes)=>({path:id==='model-progress'?'data/model-progress.json':'data/benchmarks/'+(id==='benchmark-registry'?'index':id.slice(10))+'.json',group:id==='model-progress'?undefined:'public-benchmarks',bytes:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')});
const fetch=async url=>{
 const path=new URL(url).pathname;
 if(path.endsWith('manifest.json'))return {ok:true,json:async()=>({schema_version:1,snapshot_sha256:(fresh?'b':'a').repeat(64),components:Object.fromEntries(Object.entries(raw()).map(([id,bytes])=>[id,descriptor(id,bytes)]))})};
 const part=path.split('/').at(-1).slice(0,-5),id=path.includes('/benchmarks/')?(part==='index'?'benchmark-registry':'benchmark-'+part):part;
 counts[id]=(counts[id]||0)+1;const bytes=raw()[id];assert.equal(new URL(url).searchParams.get('v'),descriptor(id,bytes).sha256);
 if(id==='benchmark-first'&&!fresh){fresh=true;return {ok:true,arrayBuffer:async()=>Uint8Array.from(Buffer.from('{}')).buffer};}
 return {ok:true,arrayBuffer:async()=>Uint8Array.from(bytes).buffer};
};
(async()=>{
 const loaded=await loader.load(['model-progress'],{groups:['public-benchmarks'],fetch,crypto:crypto.webcrypto});
 assert.equal(loaded.recovered,true);assert.equal(counts['model-progress'],2);assert.equal(counts['benchmark-registry'],2);assert.equal(counts['benchmark-first'],2);assert.equal(counts['benchmark-second'],1);
 assert.deepEqual(Object.keys(loaded.hashes).sort(),['model-progress','benchmark-registry','benchmark-first','benchmark-second'].sort());
 for(const path of ['data/benchmarks/../secret.json','data/benchmarks/nested/secret.json','//example.org/file.json','data/benchmarks/%2e%2e.json'])assert.throws(()=>loader.validateManifest({schema_version:1,snapshot_sha256:'a'.repeat(64),components:{x:{path,sha256:'a'.repeat(64),bytes:1}}}),/descriptor/);
})().catch(e=>{console.error(e);process.exitCode=1;});
''')

    def test_all_metric_sources_keep_controls_url_labels_licenses_and_reset_without_fetch(self):
        self.node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const nodes=new Map();const node=id=>{if(!nodes.has(id))nodes.set(id,{value:'',disabled:true,textContent:'',innerHTML:'',handlers:{},replaceChildren(){this.innerHTML='';this.textContent='';},addEventListener(k,f){this.handlers[k]=f;}});return nodes.get(id);};
const registry=JSON.parse(fs.readFileSync('data/benchmarks/index.json')),data={'benchmark-registry':registry},hashes={};
for(const source of registry.sources){data['benchmark-'+source.id]=JSON.parse(fs.readFileSync(source.path));hashes['benchmark-'+source.id]=source.sha256;}
const chosen=data['benchmark-charxiv'].records.at(-1).comparison_group;
const location=new URL('https://example.org/model-progress.html?model=Exact+Epoch+ID&evidence=charxiv&evidence-slice='+encodeURIComponent(chosen));
const context=vm.createContext({document:{getElementById:node},location,URL,URLSearchParams,history:{replaceState(_a,_b,url){location.href=new URL(url,location).href;}},fetch(){throw Error('Renderer must not fetch independent bytes');}});
vm.runInContext(fs.readFileSync('assets/public-benchmarks.js','utf8'),context);context.PublicBenchmarks.init({data,hashes});
assert.equal(node('metric-source').value,'charxiv');assert.equal(node('metric-slice').value,chosen);
for(const source of registry.sources){
 node('metric-source').value=source.id;node('metric-source').handlers.change();
 const component=data['benchmark-'+source.id],rows=component.records.filter(r=>r.comparison_group===node('metric-slice').value);
 assert.ok(node('metric-count').textContent.startsWith(rows.length+' of '+component.records.length+' '));
 assert.ok(node('metric-context').innerHTML.includes(source.license));assert.ok(node('metric-results').innerHTML.includes(rows[0].model.replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;')));
 assert.equal(location.searchParams.get('evidence'),source.id);assert.equal(location.searchParams.get('model'),'Exact Epoch ID');
 const slice=component.records.at(-1).comparison_group;node('metric-slice').value=slice;node('metric-slice').handlers.change();assert.equal(location.searchParams.get('evidence-slice'),slice);
 assert.equal(node('metric-source').disabled,false);assert.equal(node('metric-slice').disabled,false);assert.equal(node('metric-search').disabled,false);
}
context.PublicBenchmarks.reset();node('metric-search').handlers.input();node('metric-source').handlers.change();
for(const id of ['metric-results','metric-directory','metric-context','metric-count'])assert.equal(node(id).innerHTML,'');
assert.equal(node('metric-source').disabled,true);assert.equal(node('metric-slice').disabled,true);assert.equal(node('metric-search').disabled,true);
const html=fs.readFileSync('model-progress.html','utf8');assert.match(html,/<details class="source-details" id="metric-observations"><summary>/);assert.ok(!html.includes('id="metric-observations" open'));
''')

    def test_complete_manifest_hashes_exact_bytes_and_preserves_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(ROOT / 'data', root / 'data')
            write_discovery_list(root)
            first = build_manifest(root)
            self.assertEqual(first, build_manifest(root))
            self.assertEqual(set(first['components']), {'discoveries','discoveries-list','archived-discoveries','vulnerabilities-preview','vulnerabilities-overview','models','model-progress','swe-bench','citations','entity-aliases','discoveries-csv','catalog-summary','benchmark-registry'} | {'benchmark-' + source['id'] for source in json.loads((root / 'data/benchmarks/index.json').read_text())['sources']})
            for key, component in first['components'].items():
                raw = (root / component['path']).read_bytes()
                self.assertEqual(component['sha256'], hashlib.sha256(raw).hexdigest())
                self.assertEqual(component['bytes'], len(raw))
            for key in ('model-progress','swe-bench','citations','entity-aliases'):
                path = root / first['components'][key]['path']
                original = path.read_bytes()
                path.write_bytes(original + b'\n')
                self.assertNotEqual(first['snapshot_sha256'], build_manifest(root)['snapshot_sha256'], key)
                path.write_bytes(original)
            summary = first['components']['catalog-summary']
            self.assertIn('overlapping year/field aggregate rows', summary['unit'])
            self.assertIn('never add', summary['coverage'])
            source = first['components']['benchmark-charxiv']
            self.assertEqual(source['license'], 'CC BY-SA 4.0')
            self.assertFalse(source['hugging_face_export'])
            self.assertIn('source_observation_dates', source['dates'])
            self.assertIn('source_date_basis', source)
            (root / 'dataset.html').write_text('<html><head></head><body>Catalog-only CC BY 4.0</body></html>')
            write_component_jsonld(root, first)
            graph = json.loads(re.search(r'<script id="component-datasets" type="application/ld\+json">(.*?)</script>', (root / 'dataset.html').read_text(), re.S)[1])['@graph']
            self.assertEqual(len(graph), len(json.loads((root / 'data/benchmarks/index.json').read_text())['sources']))
            self.assertEqual({row['@id']:row['license'] for row in graph}, {'https://aisciencetracker.org/' + row['path']:row['license_url'] for row in first['components'].values() if row.get('group') == 'public-benchmarks' and row.get('license_url')})
            # Google's Dataset rich result requires a creator on every Dataset node.
            self.assertTrue(all(row['creator']['name'] for row in graph))
            self.assertTrue(all(row['publisher']['name'] == 'AI Science Tracker' for row in graph))
            once = (root / 'dataset.html').read_bytes()
            write_component_jsonld(root, first)
            self.assertEqual(once, (root / 'dataset.html').read_bytes())
            swe = first['components']['swe-bench']
            self.assertEqual(swe['license'], 'CC BY-NC 4.0')
            self.assertFalse(swe['hugging_face_export'])
            self.assertIn('evaluation_dates', swe['dates'])
            self.assertIn('snapshot_retrieved_on', swe['dates'])
            self.assertNotIn('swe-bench.json', (ROOT / 'scripts/build_hf_dataset.py').read_text())
            (root / 'index.html').write_text('<html lang="en"><body>kept</body></html>')
            stamp_pages(root, first['snapshot_sha256'])
            one = (root / 'index.html').read_bytes()
            stamp_pages(root, first['snapshot_sha256'])
            self.assertEqual(one, (root / 'index.html').read_bytes())

    def test_dataset_matrix_exposes_all_component_downloads_and_csv_units(self):
        code = r'''
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const manifest=JSON.parse(fs.readFileSync(0,'utf8')),table={innerHTML:'',replaceChildren(){this.innerHTML='';}};
vm.runInNewContext(fs.readFileSync('assets/dataset.js','utf8'),{document:{getElementById:()=>table},CatalogData:{run(_ids,render){render({manifest});}}});
for(const component of Object.values(manifest.components))assert.ok(table.innerHTML.includes(component.path+'?v='+component.sha256),component.path);
assert.match(table.innerHTML,/catalog-summary\.csv\?v=[a-f0-9]{64}">CSV<\/a>/);
assert.ok(table.innerHTML.includes('overlapping year/field aggregate rows'));assert.ok(table.innerHTML.includes('never add the year and field'));
assert.ok(table.innerHTML.includes('CC BY-SA 4.0'));assert.ok(table.innerHTML.includes('Per-component terms; no blanket catalog license'));
'''
        result = subprocess.run(['node', '-e', code], cwd=ROOT, input=json.dumps(build_manifest(ROOT)), text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_entities_preserve_literals_and_only_join_reviewed_exact_aliases(self):
        self.node(r'''
const assert=require('node:assert/strict'),fs=require('node:fs'),entities=require('./assets/catalog-entities.js');
entities.configure(JSON.parse(fs.readFileSync('data/entity-aliases.json')));
const d=JSON.parse(fs.readFileSync('data/discoveries.json'));
const before=JSON.stringify(d);
assert.equal(entities.organization('MIT; Other').id,'org-mit');assert.equal(entities.organization('Massachusetts Institute of Technology').id,'org-mit');
assert.equal(entities.organization('MIT-like Institute').id,null);
assert.equal(entities.organization('University of California, Berkeley').label,'University of California, Berkeley');
assert.equal(entities.organization('Not stated in the abstract reviewed').kind,'unknown affiliation');
assert.equal(entities.organization('Affiliation not reported').kind,'unknown affiliation');
const literal=d.filter(r=>['MIT','Massachusetts Institute of Technology'].includes(r.organization.split(';')[0].trim()));
assert.equal(d.filter(r=>entities.organization(r.organization).id==='org-mit').length,literal.length);
assert.ok(literal.length > 0);
const aliases=entities.map.systems.find(r=>r.id==='vendor-aisle').aliases;
assert.ok(aliases.length > 1);for(const alias of aliases)assert.equal(entities.system(alias).id,'vendor-aisle');
assert.equal(entities.system('Potential AISLE-like model').id,null);
assert.equal(before,JSON.stringify(d),'Source labels must not be rewritten');
''')
        self.assertEqual(organization('MIT')['label'], 'Massachusetts Institute of Technology')
        self.assertEqual(organization('Not stated in the abstract reviewed')['kind'], 'unknown affiliation')

    def test_static_alias_profiles_preserve_old_urls_and_unknown_is_not_an_institution(self):
        import generate_share as generator
        original_root = generator.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'assets').mkdir()
            for filename in ('styles.css', 'assets/catalog-ui.js'):
                shutil.copyfile(ROOT / filename, root / filename)
            (root / 'index.html').write_text('<header class="header"></header><footer class="footer"></footer>')
            records = [dict(json.loads((ROOT / 'data/discoveries.json').read_text())[0], id='alias-a', organization='MIT'),
                       dict(json.loads((ROOT / 'data/discoveries.json').read_text())[0], id='alias-b', organization='Massachusetts Institute of Technology'),
                       dict(json.loads((ROOT / 'data/discoveries.json').read_text())[0], id='unknown', organization='Not stated in the abstract reviewed')]
            try:
                generator.ROOT = root
                generator.write_profile_pages(records, {'models': [], 'families': []})
            finally:
                generator.ROOT = original_root
            canonical = (root / 'profiles/org-massachusetts-institute-of-technology.html').read_text()
            self.assertIn('alias-a', canonical)
            self.assertIn('alias-b', canonical)
            self.assertIn('org-massachusetts-institute-of-technology.html', (root / 'profiles/org-mit.html').read_text())
            unknown = (root / 'profiles/org-affiliation-not-reported.html').read_text()
            self.assertNotIn('"@type": "Organization"', unknown)
            directory = (root / 'profiles/index.html').read_text()
            self.assertIn('1 organizations and', directory)
            self.assertIn('Unknown affiliation', directory)

    def test_review_preflight_checks_only_changed_review_or_sourcecheck_fields(self):
        before = [{'id':'old','verification_status':'verified'}, {'id':'pending','verification_status':'needs verification'}]
        self.assertEqual(validate_review_patch(before, copy.deepcopy(before)), [])
        edited = copy.deepcopy(before)
        edited[0]['summary'] = 'Changed wording; historical unknown scope stays unknown'
        self.assertEqual(validate_review_patch(before, edited), [])
        edited[1]['verification_status'] = 'verified'
        with self.assertRaisesRegex(ValueError, 'actual review day'):
            validate_review_patch(before, edited)
        edited[1]['source_review'] = {'date':'2026-11-18','scope':'Abstract and publication metadata; no full text'}
        self.assertEqual(validate_review_patch(before, edited), ['pending'])
        edited[1]['source_review']['date'] = '2999-01-01'
        with self.assertRaisesRegex(ValueError, 'future'):
            validate_review_patch(before, edited)

    def test_field_year_denominators_and_common_task_missingness(self):
        page = (ROOT / 'methodology.html').read_text()
        helper = re.search(r'<script id="coverage-metrics">(.*?)</script>', page, re.S)[1]
        self.node(helper + r'''
const assert=require('node:assert/strict');
const rows=coverageByFieldYear([{field:'biology',publication_date:'2026-01-01',source_type:'paper',verification_status:'verified',source_review:{date:'2026-11-18',scope:'Abstract'}},{field:'biology',publication_date:'2026-02-01',source_type:'blog',verification_status:'needs verification'},{field:'physics',publication_date:'2025-01-01',source_type:'other',verification_status:'verified'}]);
assert.equal(rows.reduce((n,r)=>n+r.total,0),3);assert.equal(rows[0].total,2);assert.equal(rows[0].pending,1);assert.equal(rows[0].reviewed,1);
for(const r of rows)assert.equal(Object.values(r.sources).reduce((a,b)=>a+b,0),r.total);
assert.deepEqual(coverageByFieldYear([]),[]);
const {comparisonFacts}=require('./assets/model-progress-facts.js');
const facts=comparisonFacts({benchmarks:{a:{score:0}}},{benchmarks:{b:{score:10}}},[{id:'a'},{id:'b'}]);
assert.equal(facts.availableA,1);assert.equal(facts.availableB,1);assert.equal(facts.common,0);assert.equal(facts.delta,null);
''')
