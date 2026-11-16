const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date = value => new Date(value+'T00:00:00Z');
const format = value => value ? date(value).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'}) : 'Date unavailable';
const num = value => value==null?'Not available':Number(value).toLocaleString('en-GB',{maximumFractionDigits:2});
const signed = value => (value>0?'+':'')+num(value);
const interval = m => m?.eci_low==null&&m?.eci_high==null?'Interval unavailable':(m?.eci_low==null?'Lower bound unavailable':num(m.eci_low))+'–'+(m?.eci_high==null?'Upper bound unavailable':num(m.eci_high));
let start,end;
const state={lab:'OpenAI',baseline:'GPT-6 Sol',model:'GPT-6.1 Sol',period:'recent',query:'',onlyECI:false};
const presets=[
  ['Sol 6 → 6.1','GPT-6 Sol','GPT-6.1 Sol','A version update'],
  ['Astra / Sol 6.1','GPT-6 Astra','GPT-6.1 Sol','Different variants'],
  ['Luna / Sol 6','GPT-6 Luna','GPT-6 Sol','Same source date'],
  ['Fable 5.1 → 5.2','Claude Fable 5.1','Claude Fable 5.2','Another model line'],
  ['Flash 3.7 → 3.8','Gemini 3.7 Flash','Gemini 3.8 Flash','Task-level trade-offs']
];
let D,models=[],lookup,cadenceStats=[],selectedCadence='OpenAI',selectedDay=null;
const scoped=()=>models.filter(m=>state.lab==='All labs'||m.lab===state.lab);
const options=(rows,chosen)=>'<option value="">Choose a model</option>'+rows.map(m=>`<option value="${esc(m.id)}"${m.id===chosen?' selected':''}>${esc(m.name)}${m.eci==null?' · no ECI':''}</option>`).join('');
function preserveFocus(action){const id=document.activeElement.id;action();if(id)document.getElementById(id)?.focus({preventScroll:true});}
function selectLab(lab){
  state.lab=lab;state.query='';$('model-search').value='';
  const rows=scoped(),scored=rows.filter(m=>m.eci!=null);
  state.model=(scored[0]||rows[0])?.id||'';state.baseline=(scored[1]||rows[1])?.id||'';
  if(lab==='OpenAI'){state.baseline='GPT-6 Sol';state.model='GPT-6.1 Sol';}
  preserveFocus(render);if(lab!=='All labs')showCadence(lab);
}
function render(){
  $('lab-tabs').innerHTML=['All labs',...D.labs].map((lab,i)=>{const rows=models.filter(m=>lab==='All labs'||m.lab===lab);return `<button type="button" id="lab-${i}" data-lab="${lab}" aria-pressed="${state.lab===lab}">${lab}<span>${rows.length} entries / ${rows.filter(m=>m.eci!=null).length} ECI</span></button>`;}).join('');
  $('lab-select').innerHTML=['All labs',...D.labs].map(lab=>{const n=models.filter(m=>lab==='All labs'||m.lab===lab).length;return `<option value="${lab}"${state.lab===lab?' selected':''}>${lab} · ${n} entries</option>`;}).join('');
  $('comparison-presets').innerHTML='<span>Try a comparison</span>'+presets.map((p,i)=>lookup.has(p[1])&&lookup.has(p[2])?`<button id="preset-${i}" type="button" data-preset="${i}" aria-pressed="${state.baseline===p[1]&&state.model===p[2]}">${p[0]}<small>${p[3]}</small></button>`:'').join('');
  const rows=scoped(),scored=rows.filter(m=>m.eci!=null),dates=rows.map(m=>m.date).filter(Boolean).sort();
  $('selection-coverage').textContent=`${state.lab}: ${rows.length} imported entries; ${scored.length} with ECI (${num(scored.length/Math.max(1,rows.length)*100)}% coverage). Recorded years: ${dates[0]?.slice(0,4)||'unknown'}–${dates.at(-1)?.slice(0,4)||'unknown'}.`;
  renderComparison();draw();renderInventory();shareSelection();
}
function shareSelection(){
  const url=new URL(location.href);
  for(const key of ['model','baseline','lab','period'])url.searchParams.set(key,state[key]);
  history.replaceState(null,'',url);
}
function applyPreset(index){
  const p=presets[index],a=lookup.get(p[1]),b=lookup.get(p[2]);
  state.lab=a.lab===b.lab?a.lab:'All labs';state.baseline=a.id;state.model=b.id;
  state.query='';$('model-search').value='';
  state.period=a.date<start||b.date<start?'all':'recent';$('plot-period').value=state.period;
  preserveFocus(render);if(state.lab!=='All labs')showCadence(state.lab);
}
function renderReadout(a,b){
  if(!a||!b){$('comparison-readout').innerHTML='<h3>What this comparison tells you</h3><p>Choose a baseline and a comparison model to see capability, date and benchmark differences.</p>';return;}
  const f=comparisonFacts(a,b,D.benchmarks),lines=[];
  let headline='Choose two models to read the comparison.';
  if(f.delta==null)headline='An ECI comparison is unavailable for at least one selected model.';
  else if(f.sameModel)headline='The same source model is selected twice; the difference is zero by construction.';
  else if(f.delta===0)headline='The point estimates are equal; this does not establish identical capabilities.';
  else headline=`The comparison model has an ECI estimate ${num(Math.abs(f.delta))} points ${f.delta>0?'higher':f.delta<0?'lower':'different'} than the baseline${f.delta===0?' (no point-estimate change)':''}.`;
  if(f.intervalsOverlap===true)lines.push('The 90% credible intervals overlap. This alone neither proves equality nor establishes a reliable ranking.');
  else if(f.intervalsOverlap===false)lines.push('The displayed 90% credible intervals do not overlap. We have not calculated a joint probability or significance test for their difference.');
  else lines.push('An uncertainty interval is unavailable for at least one selected model.');
  if(f.signedDays!=null)lines.push(f.signedDays===0?'Both models share a recorded date; this is not a measured generational interval.':`The comparison model’s recorded date is ${Math.abs(f.signedDays)} days ${f.signedDays>0?'later':'earlier'} than the baseline’s date.`);
  if(f.differentDateBases)lines.push('The two dates use different definitions (benchmark release versus catalog publication); their spacing is not a verified launch interval.');
  if(f.differentLabs)lines.push('This is a cross-lab comparison, not a documented generational lineage.');
  const summary=f.common?`${f.common} of ${f.total} displayed benchmarks have scores for both models: ${f.higher} higher, ${f.lower} lower and ${f.unchanged} unchanged for the comparison model.`:'None of the four displayed benchmarks has scores for both models.';
  $('comparison-readout').innerHTML=`<h3>What this comparison tells you</h3><p class="readout-headline">${esc(headline)}</p><div class="readout-grid"><div><h4>Capability estimate and dates</h4><ul>${lines.map(s=>`<li>${esc(s)}</li>`).join('')}</ul></div><div><h4>Task-level evidence</h4><p>${esc(summary)}</p><p>These counts cover only the displayed tasks. Scores use each model’s best observed configuration; they do not establish superiority under the same inference budget.</p><p><a href="#benchmark-heading">Inspect the benchmark changes</a> · <a href="#inventory-heading">Find another model</a></p></div></div>`;
}
function renderComparison(){
  const a=lookup.get(state.baseline),b=lookup.get(state.model),rows=scoped();
  const delta=a?.eci!=null&&b?.eci!=null?b.eci-a.eci:null;
  const gap=a?.date&&b?.date?Math.round(Math.abs(date(b.date)-date(a.date))/864e5):null;
  $('comparison').innerHTML=`<p class="descr">Choose explicit models, including different variants.</p><div class="comparison-selectors"><label class="date-picker">Baseline<select id="baseline-model">${options(rows,state.baseline)}</select></label><label class="date-picker">Comparison model<select id="comparison-model">${options(rows,state.model)}</select></label></div><h3>${esc(a?.name||'Choose a baseline')}<span class="pair-arrow" aria-hidden="true">↓</span>${esc(b?.name||'Choose a comparison')}</h3><div class="pair-stats"><div><strong>${delta==null?'—':signed(delta)}</strong><span>ECI points, comparison − baseline</span></div><div><strong>${gap==null?'—':gap}</strong><span>days between source dates</span></div></div><div class="eci-range"><span>${num(a?.eci)} ECI</span><span>${num(b?.eci)} ECI</span></div><div class="pair-dates"><time>${format(a?.date)}</time><time>${format(b?.date)}</time></div><p class="descr">Read the interpretation below for uncertainty, date order and task-level trade-offs.</p>`;
  $('pair-lab').textContent=b?.lab||state.lab;
  $('model-history').innerHTML=[a,b].filter(Boolean).map((m,i)=>`<article class="model-detail${i?' current-model':''}"><h3>${esc(m.name)}</h3><p class="model-meta">${esc(m.lab)} · ${format(m.date)} · ${esc(m.access||'Access not stated')}</p><dl><div><dt>ECI / 90% credible interval</dt><dd>${num(m.eci)}${m.eci_low!=null&&m.eci_high!=null?' / '+num(m.eci_low)+'–'+num(m.eci_high):' / interval unavailable'}</dd></div><div><dt>Date basis / model domain</dt><dd>${esc(m.date_basis)} / ${esc(m.domain||'Domain not in source snapshot')}</dd></div><div><dt>Parameters / training compute</dt><dd>${m.parameters==null?'Not in import':num(m.parameters)} / ${m.compute_flop==null?'Not in import':m.compute_flop.toExponential(2)+' FLOP'}</dd></div></dl><details class="source-details"><summary>${m.variants.length} evaluation configurations</summary><ul>${m.variants.map(v=>`<li>${esc(v)}</li>`).join('')||'<li>No configuration IDs in source</li>'}</ul></details>${m.catalog_releases.length?`<details class="source-details"><summary>${m.catalog_releases.length} original catalog labels</summary><ul>${m.catalog_releases.map(r=>`<li>${esc(r.name)} · ${format(r.date)}</li>`).join('')}</ul></details>`:''}<p class="source-links"><a href="${esc(D.source_url)}">Epoch data export (ZIP)</a>${m.catalog_link&&/^https:\/\//.test(m.catalog_link)?`<a href="${esc(m.catalog_link)}">Catalog source</a>`:''}</p>${m.lab_inferred?'<p class="descr">Lab attributed by model-family name; source organization is empty.</p>':''}</article>`).join('');
  $('benchmark-chart').innerHTML=D.benchmarks.map(k=>{
    const av=a?.benchmarks[k.id],bv=b?.benchmarks[k.id],x=v=>12+v*2.16,change=av&&bv?bv.score-av.score:null;
    return `<div class="benchmark-row"><div><b>${esc(k.name)}</b><small>${esc(k.domain)} · ${av?num(av.score)+'%':'Not available'} → ${bv?num(bv.score)+'%':'Not available'}</small><details class="config-details source-details"><summary>Evaluation settings</summary><p>Baseline: ${av?esc(av.variant):'Not available'}<br>Comparison: ${bv?esc(bv.variant):'Not available'}</p></details></div><svg class="benchmark-track" viewBox="0 0 240 36" role="img" aria-label="${esc(k.name)}: ${av?num(av.score)+'%':'not available'} to ${bv?num(bv.score)+'%':'not available'}"><line class="track-base" x1="12" x2="228" y1="16" y2="16"/>${[0,25,50,75,100].map(v=>`<line class="track-tick" x1="${x(v)}" x2="${x(v)}" y1="12" y2="20"/>`).join('')}${change==null?'':`<line class="track-change${change<0?' negative':''}" x1="${x(av.score)}" x2="${x(bv.score)}" y1="16" y2="16"/>`}${av?`<circle class="track-before" cx="${x(av.score)}" cy="16" r="5"/>`:''}${bv?`<circle class="track-after" cx="${x(bv.score)}" cy="16" r="5"/>`:''}<text x="12" y="34">0</text><text x="228" y="34" text-anchor="end">100%</text></svg><strong class="benchmark-delta${change!=null&&change<0?' decline':''}">${change==null?'Unavailable':signed(change)+' pp'}</strong></div>`;
  }).join('');
  $('benchmarks').innerHTML=`<thead><tr><th>Benchmark</th><th>${esc(a?.name||'Baseline')}</th><th>${esc(b?.name||'Comparison')}</th><th>Change</th></tr></thead><tbody>${D.benchmarks.map(k=>{const av=a?.benchmarks[k.id]?.score,bv=b?.benchmarks[k.id]?.score;return `<tr><th>${esc(k.name)}</th><td>${av==null?'Not available':num(av)+'%'}</td><td>${bv==null?'Not available':num(bv)+'%'}</td><td>${av==null||bv==null?'—':signed(bv-av)+' pp'}</td></tr>`;}).join('')}</tbody>`;
  renderReadout(a,b);
}
function fitPlotLabels(svg,width){
  svg.querySelectorAll('.selected-model-label').forEach(label=>{
    const bounds=label.getBBox(),x=Number(label.getAttribute('x'));
    if(bounds.x<4)label.setAttribute('x',x+4-bounds.x);
    else if(bounds.x+bounds.width>width-4)label.setAttribute('x',x+width-4-bounds.x-bounds.width);
  });
}
function draw(){
  if(!D)return;
  const all=scoped().filter(m=>m.eci!=null&&m.date),points=all.filter(m=>state.period==='all'||m.date>=start).sort((a,b)=>a.date.localeCompare(b.date)||a.id.localeCompare(b.id));
  const W=Math.max(260,Math.round($('progress-chart').clientWidth)),H=350,pad={l:38,r:18,t:32,b:38};
  if(!points.length){$('progress-chart').innerHTML='<p class="vuoto">No ECI scores in this period. Use Full history or select another lab.</p>';$('plot-caption').textContent='No scored observations in this view.';return;}
  const first=state.period==='recent'?date(start):date(points[0].date),last=date(end),span=Math.max(864e5,last-first);
  const lo=Math.floor(Math.min(...points.map(m=>m.eci_low??m.eci))/10)*10,hi=Math.ceil(Math.max(...points.map(m=>m.eci_high??m.eci))/10)*10;
  const x=d=>pad.l+(date(d)-first)/span*(W-pad.l-pad.r),y=v=>H-pad.b-(v-lo)/Math.max(1,hi-lo)*(H-pad.t-pad.b);
  let svg=Array.from({length:5},(_,i)=>lo+(hi-lo)*i/4).map(v=>`<line class="griglia" x1="${pad.l}" x2="${W-pad.r}" y1="${y(v)}" y2="${y(v)}"/><text class="ax" x="${pad.l-8}" y="${y(v)+4}" text-anchor="end">${num(v)}</text>`).join('');
  svg+=Array.from({length:W<420?3:5},(_,i)=>{const n=W<420?2:4,t=new Date(+first+span*i/n);return `<text class="ax" x="${pad.l+(W-pad.l-pad.r)*i/n}" y="${H-10}" text-anchor="${i===0?'start':i===n?'end':'middle'}">${t.toLocaleDateString('en-GB',{month:'short',year:'2-digit',timeZone:'UTC'})}</text>`;}).join('');
  const a=lookup.get(state.baseline),b=lookup.get(state.model);
  if(a?.eci!=null&&b?.eci!=null&&points.includes(a)&&points.includes(b))svg+=`<path class="comparison-connector" d="M${x(a.date)},${y(a.eci)} L${x(b.date)},${y(b.eci)}"/>`;
  svg+=points.map((m,i)=>{const active=m.id===state.model,base=m.id===state.baseline;return `<g id="point-${models.indexOf(m)}" class="model-point${active?' selected-point':''}${base?' baseline-point':''}" role="button" tabindex="${active||(!points.some(p=>p.id===state.model)&&i===0)?0:-1}" data-model="${models.indexOf(m)}" aria-label="${esc(m.name)}, ${esc(m.lab)}, ${format(m.date)}, ECI ${num(m.eci)}, 90% credible interval: ${esc(interval(m))}"><title>${esc(m.name)} · ${esc(m.lab)}\n${format(m.date)} · ECI ${num(m.eci)}\n90% credible interval ${interval(m)}</title>${m.eci_low!=null&&m.eci_high!=null?`<line class="uncertainty" x1="${x(m.date)}" x2="${x(m.date)}" y1="${y(m.eci_low)}" y2="${y(m.eci_high)}"/>`:''}<circle class="hit" cx="${x(m.date)}" cy="${y(m.eci)}" r="10"/><circle class="mark" cx="${x(m.date)}" cy="${y(m.eci)}" r="${active||base?6:3}"/></g>`;}).join('');
  svg+=[a,b].filter(m=>m&&points.includes(m)).map((m,i)=>`<text class="selected-model-label" x="${Math.min(W-pad.r-4,Math.max(pad.l+4,x(m.date)))}" y="${Math.max(18,Math.min(H-pad.b-8,y(m.eci)+(i?-18:24)))}" text-anchor="${x(m.date)>W/2?'end':'start'}">${esc(m.name)} · ${num(m.eci)}</text>`).join('');
  $('progress-chart').innerHTML=`<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="${points.length} ECI observations for ${esc(state.lab)}; arrow keys navigate, Enter selects a model; vertical bars show 90% credible intervals.">${svg}</svg><p class="chart-legend">Hollow: baseline · Filled: comparison · Vertical lines: 90% credible intervals. Arrow keys move between models; Enter selects.</p>`;
  fitPlotLabels($('progress-chart').querySelector('svg'),W);
  $('plot-caption').textContent=`${points.length} of ${all.length} dated ECI observations in view. Cropped ECI axis: ${num(lo)}–${num(hi)}.`;
  $('pair-overview').innerHTML='';
  $('plot-data').innerHTML='<tr><th>Exact model</th><th>Date</th><th>ECI</th><th>90% interval</th></tr>'+points.map(m=>`<tr><td>${esc(m.name)}</td><td>${format(m.date)}</td><td>${num(m.eci)}</td><td>${interval(m)}</td></tr>`).join('');
}
function renderInventory(){
  const q=state.query.toLowerCase(),rows=scoped().filter(m=>(!state.onlyECI||m.eci!=null)&&(!q||(m.name+' '+m.lab+' '+m.variants.join(' ')).toLowerCase().includes(q)));
  $('inventory-count').textContent=`${rows.length} of ${scoped().length} source entries shown · ${rows.filter(m=>m.eci!=null).length} with ECI`;
  $('model-inventory').innerHTML='<thead><tr><th>Exact model / version</th><th>Lab</th><th>Recorded date</th><th>ECI / 90% interval</th><th>Access</th><th>Evaluation configs</th></tr></thead><tbody>'+rows.map(m=>`<tr${m.id===state.model?' class="inventory-selected"':''}><th scope="row"><button type="button" class="model-link" id="row-${models.indexOf(m)}" data-model="${models.indexOf(m)}">${esc(m.name)}</button>${m.lab_inferred?'<small>Lab inferred from family name</small>':''}</th><td>${esc(m.lab)}</td><td>${format(m.date)}<small>${esc(m.date_basis)}</small></td><td>${num(m.eci)}${m.eci!=null?'<small>'+interval(m)+'</small>':''}</td><td>${esc(m.access||'Not stated')}</td><td>${m.variants.length}</td></tr>`).join('')+'</tbody>';
}
function computeCadence(){
  cadenceStats=D.labs.map(lab=>{const rows=models.filter(m=>m.lab===lab&&m.date&&m.date>=start&&m.date<=end),dates=[...new Set(rows.map(m=>m.date))].sort();const gaps=dates.slice(1).map((d,i)=>(date(d)-date(dates[i]))/864e5).sort((a,b)=>a-b),mid=Math.floor(gaps.length/2);return {lab,rows,dates,gaps,median:gaps.length?(gaps.length%2?gaps[mid]:(gaps[mid-1]+gaps[mid])/2):null};});
}
function showCadence(lab,day=null){
  selectedCadence=lab;selectedDay=day;const x=d=>10+(date(d)-date(start))/(date(end)-date(start))*240;
  $('cadence').innerHTML=`<h3>Recorded dates across eight labs</h3><p class="descr">Each dot is one source date; larger dots contain more entries. Arrow keys move between dates; Enter inspects.</p><div class="cadence-axis"><span>Lab / entries</span><div><span>${format(start)}</span><span>${format(end)}</span></div><span>Median gap</span></div>`+cadenceStats.map((s,labIndex)=>`<div class="cadence-row${s.lab===lab?' active':''}"><button type="button" id="cadence-lab-${labIndex}" data-cadence="${s.lab}" aria-pressed="${s.lab===lab}"><b>${s.lab}</b><small>${s.dates.length} dates · ${s.rows.length} entries</small></button><svg viewBox="0 0 260 36" role="group" aria-label="${s.lab}, ${s.dates.length} dates"><line class="track-base" x1="10" x2="250" y1="18" y2="18"/>${s.dates.map((d,i)=>{const rows=s.rows.filter(m=>m.date===d);return `<g id="cadence-date-${labIndex}-${i}" role="button" tabindex="${i===s.dates.length-1?0:-1}" data-cadence="${s.lab}" data-date="${d}" aria-label="${s.lab}, ${format(d)}, ${rows.length} entries"><title>${format(d)} · ${rows.map(m=>esc(m.name)).join(', ')}</title><circle class="hit" cx="${x(d)}" cy="18" r="8"/><circle class="cadence-dot" cx="${x(d)}" cy="18" r="${Math.min(5,2+Math.log2(rows.length))}"/></g>`;}).join('')}</svg><span class="cadence-median">${s.median==null?'N/A':num(s.median)+' d'}</span></div>`).join('');
  const s=cadenceStats.find(s=>s.lab===lab);
  $('release-title').textContent=lab+(day?' · '+format(day):' · Latest 5 dates');
  $('cadence-summary').innerHTML=`<label class="date-picker">Inspect a recorded date<select id="date-picker"><option value="">Latest 5 dates</option>${s.dates.slice().reverse().map(d=>`<option value="${d}"${d===day?' selected':''}>${format(d)}</option>`).join('')}</select></label><dl class="cadence-stats"><div><dt>Median gap</dt><dd>${s.median==null?'N/A':num(s.median)+' d'}</dd></div><div><dt>Shortest / longest</dt><dd>${s.gaps.length?s.gaps[0]+' / '+s.gaps.at(-1)+' d':'N/A'}</dd></div><div><dt>Entries / dates</dt><dd>${s.rows.length} / ${s.dates.length}</dd></div><div><dt>Observed gaps</dt><dd>${s.gaps.length}</dd></div></dl><p class="descr">These are observed source gaps. Missing releases and overlapping labels can change the summary; it is not a generation-speed ranking.</p>`;
  $('release-list').innerHTML=(day?[day]:s.dates.slice(-5).reverse()).map(d=>`<div class="release-date"><time>${format(d)}</time><span>${s.rows.filter(m=>m.date===d).map(m=>`<button class="model-link" data-model="${models.indexOf(m)}">${esc(m.name)}</button>`).join(', ')}</span></div>`).join('')||'<p>No recorded dates in this window.</p>';
}
function chooseModel(index){
  const m=models[index],params=new URLSearchParams({model:m.id,baseline:state.baseline===m.id?'':state.baseline,lab:state.lab,period:m.date&&m.date<start?'all':state.period});
  Object.assign(state,linkedComparison(params,models,start));$('plot-period').value=state.period;
  preserveFocus(render);
}
document.addEventListener('click',e=>{const b=e.target.closest('[data-preset],[data-lab],[data-model],[data-cadence]');if(!b)return;if(b.dataset.preset!==undefined)applyPreset(Number(b.dataset.preset));else if(b.dataset.lab)selectLab(b.dataset.lab);else if(b.dataset.model!==undefined)chooseModel(Number(b.dataset.model));else preserveFocus(()=>showCadence(b.dataset.cadence,b.dataset.cadence===selectedCadence&&b.dataset.date===selectedDay?null:b.dataset.date));});
document.addEventListener('keydown',e=>{
  const b=e.target.closest('svg [data-model],svg [data-date]');if(!b)return;
  if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();const nodes=[...b.parentNode.querySelectorAll('[data-model],[data-date]')],n=nodes[Math.max(0,Math.min(nodes.length-1,nodes.indexOf(b)+(e.key==='ArrowRight'?1:-1)))];b.tabIndex=-1;n.tabIndex=0;n.focus();}
  else if(['Enter',' '].includes(e.key)){e.preventDefault();if(b.dataset.model!==undefined)chooseModel(Number(b.dataset.model));else{showCadence(b.dataset.cadence,b.dataset.date);$('release-title').focus();}}
});
document.addEventListener('change',e=>{
  if(e.target.id==='lab-select'){selectLab(e.target.value);}
  else if(e.target.id==='baseline-model'||e.target.id==='comparison-model'){state[e.target.id==='baseline-model'?'baseline':'model']=e.target.value;const m=lookup.get(e.target.value);if(m?.date&&m.date<start){state.period='all';$('plot-period').value='all';}preserveFocus(render);}
  else if(e.target.id==='plot-period'){state.period=e.target.value;draw();shareSelection();}
  else if(e.target.id==='only-eci'){state.onlyECI=e.target.checked;renderInventory();}
  else if(e.target.id==='date-picker'){const day=e.target.value;preserveFocus(()=>showCadence(selectedCadence,day||null));}
});
$('model-search').addEventListener('input',e=>{state.query=e.target.value;renderInventory();});
$('theme').onclick=()=>{const dark=document.documentElement.dataset.theme==='dark'||(!document.documentElement.dataset.theme&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.dataset.theme=dark?'light':'dark';};
window.addEventListener('resize',draw);
fetch('data/model-progress.json').then(r=>{if(!r.ok)throw Error('Model export unavailable');return r.json();}).then(data=>{
  D=data;end=D.fetched_on;const windowStart=date(end);windowStart.setUTCFullYear(windowStart.getUTCFullYear()-1);start=windowStart.toISOString().slice(0,10);$('import-date').textContent=format(end);$('cadence-period').textContent=format(end);models=D.models;lookup=new Map(models.map(m=>[m.id,m]));
  $('coverage').textContent=`${models.length} source entries · ${models.filter(m=>m.eci!=null).length} with ECI · ${D.labs.length} labs · ${D.fetched_on}`;
  $('source-coverage').textContent=`${models.filter(m=>m.lab_inferred).length} lab assignments rely on family names because source organizations are empty; they are marked in the inventory.`;
  Object.assign(state,linkedComparison(new URLSearchParams(location.search),models,start)||{});$('plot-period').value=state.period;
  render();computeCadence();showCadence(state.lab==='All labs'?(lookup.get(state.model)?.lab||'OpenAI'):state.lab);
}).catch(error=>{$('coverage').textContent='Model data could not load.';$('comparison').innerHTML='<p>Reload the page to retry. Source import or rendering failed.</p>';console.error(error);});

$('clear-model-search').onclick=()=>{state.query='';state.onlyECI=false;$('model-search').value='';$('only-eci').checked=false;renderInventory();};
