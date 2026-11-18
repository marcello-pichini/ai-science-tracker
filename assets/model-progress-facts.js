/* Descriptive comparisons only: no significance or causal-performance inference. */
function comparisonFacts(a,b,benchmarks) {
  const common=benchmarks.flatMap(k=>{
    const av=a?.benchmarks[k.id]?.score,bv=b?.benchmarks[k.id]?.score;
    return av==null||bv==null?[]:[{name:k.name,delta:bv-av}];
  });
  const intervals=[a?.eci_low,a?.eci_high,b?.eci_low,b?.eci_high];
  return {
    delta:a?.eci==null||b?.eci==null?null:b.eci-a.eci,
    signedDays:a?.date&&b?.date?Math.round((Date.parse(b.date+'T00:00:00Z')-Date.parse(a.date+'T00:00:00Z'))/864e5):null,
    common:common.length,total:benchmarks.length,
    availableA:benchmarks.filter(k=>a?.benchmarks[k.id]?.score!=null).length,
    availableB:benchmarks.filter(k=>b?.benchmarks[k.id]?.score!=null).length,
    higher:common.filter(k=>k.delta>1e-9).length,
    lower:common.filter(k=>k.delta< -1e-9).length,
    unchanged:common.filter(k=>Math.abs(k.delta)<=1e-9).length,
    intervalsOverlap:intervals.some(v=>v==null)?null:Math.max(a.eci_low,b.eci_low)<=Math.min(a.eci_high,b.eci_high),
    sameModel:!!a&&a.id===b?.id,
    differentLabs:!!a&&!!b&&a.lab!==b.lab,
    differentDateBases:!!a&&!!b&&a.date_basis!==b.date_basis
  };
}
/* Exact source IDs only; unknown URL values leave the default selection intact. */
function linkedComparison(params,models,start) {
  const model=models.find(m=>m.id===params.get('model'));
  if(!model)return null;
  let baseline=params.has('baseline')?models.find(m=>m.id===params.get('baseline')):null;
  if(!params.has('baseline')){
    const peers=models.filter(m=>m.lab===model.lab&&m.id!==model.id);
    baseline=peers.find(m=>m.eci!=null&&m.date&&model.date&&m.date<=model.date)||peers.find(m=>m.eci!=null)||peers[0];
  }
  const lab=params.get('lab')==='All labs'||baseline&&baseline.lab!==model.lab?'All labs':model.lab;
  const period=['recent','all'].includes(params.get('period'))?params.get('period'):[model,baseline].some(m=>m?.date&&m.date<start)?'all':'recent';
  return {model:model.id,baseline:baseline?.id||'',lab,period};
}
if(typeof module!=='undefined')module.exports={comparisonFacts,linkedComparison};
