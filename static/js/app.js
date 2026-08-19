/* ==========================================================================
   FiBand — front-end logic
   All chart series come from window.FIBAND_DATA (JSON emitted in
   templates/base.html before this file).
   ========================================================================== */
'use strict';

// ---- Mobile hamburger nav: toggles the collapsed page menu below 640px. ----
(function(){
  const btn = document.getElementById('navToggle');
  const nav = document.getElementById('pageNav');
  if(!btn || !nav) return;
  function close(){ nav.classList.remove('open'); btn.classList.remove('open'); btn.setAttribute('aria-expanded','false'); }
  btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = nav.classList.toggle('open');
    btn.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  document.addEventListener('click', (e) => {
    if(nav.classList.contains('open') && !nav.contains(e.target) && e.target !== btn) close();
  });
  nav.addEventListener('click', (e) => { if(e.target.tagName === 'A') close(); });
})();

const D = window.FIBAND_DATA || {};

const hrLabels    = D.hrLabels    || [];
const hrVals      = D.hrVals      || [];
const stepLabels  = D.stepLabels  || [];
const stepVals    = D.stepVals    || [];
const stepDayLabels = D.stepDayLabels || [];
const stepDayVals   = D.stepDayVals   || [];
const bpLabels    = D.bpLabels    || [];
const bpSys       = D.bpSys       || [];
const bpDia       = D.bpDia       || [];
const spo2Labels  = D.spo2Labels  || [];
const spo2Vals    = D.spo2Vals    || [];
const stressLabels= D.stressLabels|| [];
const stressVals  = D.stressVals  || [];
const hrvLabels   = D.hrvLabels   || [];
const hrvVals     = D.hrvVals     || [];
const longRange   = !!D.longRange;

// ---- "Statistical data" view: rolling-median filter (±2 sample window) that
// replaces isolated sensor spikes/dips with the local median, leaving the
// shape of the series intact. Used by the "Raw / statistical data" toggle.
function _median(a){ if(!a.length) return NaN; const s=a.slice().sort((x,y)=>x-y), n=s.length;
  return n%2 ? s[(n-1)/2] : (s[n/2-1]+s[n/2])/2; }
function rollingMedian(vals, w=2){
  if(vals.length < 2*w+1) return vals.slice();
  return vals.map((_,i)=>{
    const lo=Math.max(0,i-w), hi=Math.min(vals.length-1,i+w);
    return Math.round(_median(vals.slice(lo,hi+1)));
  });
}
const hrValsStat     = rollingMedian(hrVals);
const spo2ValsStat   = rollingMedian(spo2Vals);
const stressValsStat = rollingMedian(stressVals);
const hrvValsStat    = rollingMedian(hrvVals);

const baseOpts = { responsive:true,
  interaction:{ mode:'index', intersect:false },
  plugins:{
    legend:{ display:false },
    tooltip:{ backgroundColor:'#1d2023', titleColor:'#f6f6f3', bodyColor:'#f6f6f3',
      borderColor:'#33363a', borderWidth:1, cornerRadius:10, padding:10,
      titleFont:{family:'JetBrains Mono', size:11, weight:'600'},
      bodyFont:{family:'JetBrains Mono', size:11}, boxPadding:4, displayColors:true, boxWidth:8, boxHeight:8 }
  },
  font:{family:'JetBrains Mono'},
  scales:{ x:{ ticks:{color:'#9a9c98', font:{family:'JetBrains Mono', size:10}, maxTicksLimit:10}, grid:{display:false}, border:{color:'#26292c'} },
           y:{ ticks:{color:'#9a9c98', font:{family:'JetBrains Mono', size:10}}, grid:{color:'#1d2023'}, border:{display:false}, beginAtZero:false } } };

function noData(id){
  const c = document.getElementById(id);
  if(!c) return;
  const ctx = c.getContext('2d');
  ctx.fillStyle = '#9a9c98'; ctx.font = '500 12px -apple-system,sans-serif'; ctx.textAlign='center';
  ctx.fillText('No data in this period', c.width/2, c.height/2);
}

function lineChart(id, labels, datasets, zero=false){
  if(!document.getElementById(id)) return null;   // canvas exists only on the charts page
  if(!labels.length){ noData(id); return null; }
  datasets = datasets.map(d => ({ tension:.3, pointHoverRadius:4, pointHoverBackgroundColor:'#0c0e10',
    pointHoverBorderWidth:2, pointBackgroundColor:'#0c0e10', ...d }));
  return new Chart(document.getElementById(id), { type:'line', data:{labels, datasets},
    options:{ ...baseOpts, plugins:{ ...baseOpts.plugins, legend:{display:datasets.length>1, position:'top', align:'end',
        labels:{color:'#f6f6f3', font:{family:'JetBrains Mono', size:11}, boxWidth:8, boxHeight:8, usePointStyle:true} } },
      scales:{ ...baseOpts.scales, y:{ ...baseOpts.scales.y, beginAtZero:zero } } } });
}

// Continuous-sample charts registered for the "Raw / statistical data" toggle.
const _statCharts = [];
function registerStat(chart, raw, stat){ if(chart) _statCharts.push({chart, raw, stat}); }
function setStatMode(on){
  document.querySelectorAll('#dataModeToggle .rbtn').forEach(b =>
    b.classList.toggle('on', (b.dataset.mode==='stat')===on));
  _statCharts.forEach(({chart, raw, stat})=>{ chart.data.datasets[0].data = on?stat:raw; chart.update(); });
  try{ localStorage.setItem('fiband_datamode', on?'stat':'real'); }catch(e){}
}

const hrChart = lineChart('hrChart', hrLabels, [{ label:'bpm', data:hrVals, borderColor:'#ff8a5c',
    backgroundColor:'rgba(255,138,92,.10)', fill:true, pointRadius:0, borderWidth:2 }]);
registerStat(hrChart, hrVals, hrValsStat);

// Multi-day period: one bar per day with the daily step total.
// Otherwise the individual sensor slots (intra-day view) as before.
if(document.getElementById('stepChart')){
  if(stepDayVals.length > 1){
    new Chart(document.getElementById('stepChart'), { type:'bar',
      data:{ labels:stepDayLabels, datasets:[{ label:'steps/day', data:stepDayVals, backgroundColor:'#2dd4bf', borderRadius:5, maxBarThickness:36 }]},
      options:{ ...baseOpts, scales:{ ...baseOpts.scales, y:{ ...baseOpts.scales.y, beginAtZero:true } } } });
  } else if(stepLabels.length){
    new Chart(document.getElementById('stepChart'), { type:'bar',
      data:{ labels:stepLabels, datasets:[{ label:'steps', data:stepVals, backgroundColor:'#2dd4bf', borderRadius:5, maxBarThickness:24 }]},
      options:{ ...baseOpts, scales:{ ...baseOpts.scales, y:{ ...baseOpts.scales.y, beginAtZero:true } } } });
  } else noData('stepChart');
}

lineChart('bpChart', bpLabels, [
  { label:'systolic', data:bpSys, borderColor:'#2dd4bf', backgroundColor:'transparent', fill:false, pointRadius:2, borderWidth:2 },
  { label:'diastolic', data:bpDia, borderColor:'#9a9c98', backgroundColor:'transparent', fill:false, pointRadius:2, borderWidth:2, borderDash:[4,3] }
]);
const spo2Chart = lineChart('spo2Chart', spo2Labels, [{ label:'SpO2 %', data:spo2Vals, borderColor:'#2dd4bf',
    backgroundColor:'rgba(45,212,191,.10)', fill:true, pointRadius:2, borderWidth:2 }]);
registerStat(spo2Chart, spo2Vals, spo2ValsStat);
const stressChart = lineChart('stressChart', stressLabels, [{ label:'stress', data:stressVals, borderColor:'#ff8a5c',
    backgroundColor:'rgba(255,138,92,.10)', fill:true, pointRadius:0, borderWidth:2 }]);
registerStat(stressChart, stressVals, stressValsStat);
const hrvChart = lineChart('hrvChart', hrvLabels, [{ label:'HRV ms', data:hrvVals, borderColor:'#c9f26c',
    backgroundColor:'rgba(201,242,108,.10)', fill:true, pointRadius:0, borderWidth:2 }]);
registerStat(hrvChart, hrvVals, hrvValsStat);

// Apply the saved mode (default: raw data).
try{ if(localStorage.getItem('fiband_datamode')==='stat') setStatMode(true); }catch(e){}

async function sync(mode){
  const btns = document.querySelectorAll('button'); btns.forEach(b=>b.disabled=true);
  const s = document.getElementById('status');
  s.textContent = 'Connecting to the band and measuring... (can take a few minutes)';
  try{
    const r = await fetch('/action/sync?mode='+mode, {method:'POST'});
    const j = await r.json();
    if(j.ok){
      let msg = '✓ Synced. ';
      if(j.battery) msg += 'Battery '+j.battery.level+'%. ';
      if(j.measurements && j.measurements.length) msg += j.measurements.map(m=>
          m.metric==='blood_pressure' ? ('blood pressure '+m.value+'/'+m.value2) : (m.metric+' '+m.value)).join(', ')+'. ';
      const span = (j.days_synced!=null) ? (j.days_synced===0 ? 'today only' : ('last '+(j.days_synced+1)+' days')) : '';
      msg += 'History'+(span?' ('+span+')':'')+': '+j.hr_points+' heart-rate points, '+j.step_points+' step slots, '
           + (j.stress_points||0)+' stress, '+(j.hrv_points||0)+' HRV.';
      if(j.errors && j.errors.length) msg += '\nNotes: '+j.errors.join(' | ');
      s.textContent = msg + '\nRefreshing charts...';
      setTimeout(()=>location.reload(), 1200);
    } else {
      s.textContent = '✗ Error: '+((j.errors||['unknown']).join(' | '));
    }
  }catch(e){ s.textContent = '✗ Network error: '+e; }
  finally{ btns.forEach(b=>b.disabled=false); }
}

async function aiAnalyze(){
  const btns = document.querySelectorAll('button'); btns.forEach(b=>b.disabled=true);
  const s = document.getElementById('aistatus');
  s.textContent = 'Analysis in progress with the AI model... (can take a few seconds)';
  try{
    const r = await fetch('/action/ai_prompt', {method:'POST'});
    const j = await r.json();
    if(j.ok){
      s.textContent = '✓ Analysis complete · '+j.days+' days'
        + (j.tokens_out ? ' · '+j.tokens_out+' tokens generated' : '')+' · saved to the database (#'+j.id+').';
      const meta = document.getElementById('aimeta');
      meta.textContent = 'Last report · just now · '+j.model;
      meta.style.display = '';
      document.getElementById('aireport').innerHTML = j.short;
      const full = document.getElementById('aifull'); full.innerHTML = j.full; full.style.display = 'none';
      const diet = document.getElementById('aidiet'); diet.innerHTML = j.diet || ''; diet.style.display = 'none';
      const bx = document.getElementById('aibtns'); bx.style.display = '';
      bx.querySelectorAll('button').forEach(b => b.textContent = 'View ' + b.dataset.label);
      bx.querySelector('[data-label="dietary and supplement advice"]').style.display =
        (j.diet && j.diet.trim()) ? '' : 'none';
    } else {
      s.textContent = '✗ Error: '+((j.errors||['unknown']).join(' | '));
    }
  }catch(e){ s.textContent = '✗ Network error: '+e; }
  finally{ btns.forEach(b=>b.disabled=false); }
}

function toggleBox(boxId, btn){
  const f = document.getElementById(boxId);
  const hidden = (f.style.display === 'none');
  f.style.display = hidden ? '' : 'none';
  btn.textContent = (hidden ? 'Hide ' : 'View ') + btn.dataset.label;
}

// Diary: enable "Save" only when the note has changed from the saved one.
function noteChanged(ta){
  const box = ta.closest('.noteday');
  box.querySelector('.savebtn').disabled = (ta.value === box.dataset.saved);
  box.querySelector('.notesaved').textContent = '';
}
async function saveNote(date){
  const box = document.querySelector('.noteday[data-date="'+date+'"]');
  if(!box) return;
  const ta = box.querySelector('textarea');
  const btn = box.querySelector('.savebtn');
  const stat = box.querySelector('.notesaved');
  btn.disabled = true; stat.textContent = 'Saving…';
  try{
    const r = await fetch('/action/save_note', {method:'POST',
      body: new URLSearchParams({date: date, note: ta.value})});
    const j = await r.json();
    if(j.ok){
      box.dataset.saved = j.note;
      ta.value = j.note;                       // reflects the server-side cap (2000 chars)
      box.querySelector('.note-dot').style.display = j.has ? '' : 'none';
      stat.textContent = '✓ Saved';
      btn.disabled = true;
      setTimeout(()=>{ if(stat.textContent==='✓ Saved') stat.textContent=''; }, 2500);
    } else {
      stat.textContent = '✗ '+((j.errors||['error']).join(' '));
      btn.disabled = false;
    }
  }catch(e){ stat.textContent = '✗ Network error'; btn.disabled = false; }
}
