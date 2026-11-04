'use strict';
const el=id=>document.getElementById(id), mode=document.body.dataset.mode;
const esc=x=>String(x??'Not reported').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const numeric=n=>n!==null&&n!==undefined&&n!==''&&Number.isFinite(Number(n));
const fmt=(n,d=1)=>numeric(n)?Number(n).toLocaleString(undefined,{maximumFractionDigits:d}):'—';
const capacity=n=>numeric(n)?(n>=1e12?fmt(n/1e12,2)+' TB':fmt(n/1e9,1)+' GB'):'Not reported';
const value=name=>document.querySelector('input[name="'+name+'"]:checked')?.value;
const helper='/usr/local/share/dlbt_os/cockpit_support/storage/backend.py';
const colors=['#82b8ff','#80dfc5','#c5a6ff','#f3c286'];
const workloads={
 'seq-read':{title:'Read speed',detail:'Reads large blocks to measure sequential throughput. No data is written.',short:'Read only'},
 'random-read':{title:'Everyday access',detail:'Reads small blocks from different locations to measure random access. No data is written.',short:'Read only'},
 'seq-write':{title:'Write speed',detail:'Writes large blocks to a new temporary file on each selected data volume. Existing files are preserved.',short:'Temporary-file writes'},
 'mixed':{title:'Mixed workload',detail:'Combines 70% reads and 30% writes in a new temporary file to simulate a busy data volume.',short:'70% reads · 30% writes'}
};
const layouts={
 '0':{title:'Maximum capacity',minimum:2,tolerance:'None',description:'No redundancy. One failed drive loses the entire array.'},
 '1':{title:'Mirror',minimum:2,tolerance:'All but one drive',description:'Each drive holds a copy. Usable space equals the smallest drive.'},
 '5':{title:'Balanced',minimum:3,tolerance:'1 drive',description:'One drive’s worth of space is reserved for parity.'},
 '6':{title:'Double protection',minimum:4,tolerance:'2 drives',description:'Two drives’ worth of space are reserved for parity.'},
 '10':{title:'Speed + protection',minimum:4,tolerance:'1 per mirrored pair',description:'Half the capacity stores mirrored copies. Requires an even number of drives.'}
};
const errorFields={media_errors:'Media errors',error_log_entries:'Error log entries',reallocated_sectors:'Reallocated sectors',pending_sectors:'Pending sectors',uncorrectable_sectors:'Uncorrectable sectors',crc_errors:'Interface CRC errors',scsi_read_errors:'Uncorrected read errors',scsi_write_errors:'Uncorrected write errors'};
let inventory=null,chosen=new Set(),current=null,reviewAction=null,busy=false,polling=false,driveFilter='all',historySignature='',activeSignature='',mountChoices={};
const driveIcon='<svg viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5" y="3" width="22" height="26" rx="4"/><circle cx="16" cy="14" r="6"/><circle cx="16" cy="14" r="1.4"/><path d="m16 14 7 6M9 25h8M22 25h1"/></svg>';
const emptyArt='<svg viewBox="0 0 180 105" fill="none" aria-hidden="true"><path d="M15 80h150M25 58h130M35 36h110" stroke="#294362" stroke-dasharray="3 5"/><rect x="62" y="12" width="56" height="78" rx="9" fill="#192b40" stroke="currentColor"/><circle cx="90" cy="43" r="17" stroke="currentColor"/><circle cx="90" cy="43" r="4" stroke="currentColor"/><path d="m90 43 20 19M74 78h18" stroke="currentColor"/><circle cx="145" cy="31" r="10" fill="#213b52" stroke="#73b6c5"/><path d="m141 31 3 3 5-6" stroke="#8fe0c8"/></svg>';
function notice(text,error=false){el('notice').textContent=text;el('notice').className=error?'error':'';}
function api(action,data={}){
 return new Promise((resolve,reject)=>{
  let output='';const p=cockpit.spawn(['/usr/bin/python3','-I',helper,action,JSON.stringify(data)],{superuser:'require',err:'message'});
  p.stream(s=>output+=s);p.then(()=>{try{const r=JSON.parse(output);if(!r.ok)throw Error(r.error);resolve(r.data);}catch(e){reject(e);}}).catch(e=>{
   try{reject(Error(JSON.parse(output).error));}catch{reject(Error(e.problem==='access-denied'?'Enable administrative access in Cockpit to use storage tools.':e.message||String(e)));}
  });
 });
}
async function action(fn){if(busy)return;busy=true;try{await fn();}catch(e){notice(e.message,true);}finally{busy=false;}}
function pill(text,tone='neutral'){return '<span class="pill '+tone+'"><i class="health-dot" aria-hidden="true"></i>'+esc(text)+'</span>';}
function healthLabel(h){return {passed:'Health check passed',warning:'Review health warnings',partial:'Limited health data',unavailable:'Health not available'}[h?.status]||'Health not available';}
function healthTone(h){return h?.status==='passed'?'good':h?.status==='warning'?'bad':h?.status==='partial'?'warn':'neutral';}
function healthExplanation(h){return {passed:'The drive reports a passing SMART health check.',warning:'The drive has reported health or error-history warnings. Review the counters and vendor details before relying on it.',partial:'The drive reports a passing health check, but some SMART commands or logs are unavailable.',unavailable:'This drive or controller did not provide a complete SMART health result. Missing data is not a passing result.'}[h?.status]||'No SMART health result was reported.';}
function usable(d){return mode==='raid'?d.available===true:d.test_allowed===true;}
function selectedDrives(){return inventory?.devices.filter(d=>chosen.has(d.path)&&usable(d))||[];}
function running(){return Boolean(current&&['queued','running'].includes(current.status));}
function drawMetrics(){
 const ds=inventory.devices,ready=ds.filter(usable).length;
 const items=[['Connected drives',ds.length,'detected','▤'],[mode==='raid'?'Ready for RAID':'Ready to test',ready,mode==='raid'?'blank & unused':'data drives','↗'],['Health warnings',ds.filter(d=>d.health?.status==='warning').length,'reported','◇'],['System drives',ds.filter(d=>d.is_os).length,'protected','⌑']];
 el('metrics').innerHTML=items.map(([label,n,hint,icon])=>'<div class="metric"><div class="metric-top">'+label+'<span class="metric-icon" aria-hidden="true">'+icon+'</span></div><strong>'+n+'</strong><small>'+hint+'</small></div>').join('');
}
function renderDrives(){
 if(!inventory)return;
 chosen=new Set([...chosen].filter(p=>inventory.devices.some(d=>d.path===p&&usable(d))));
 const query=el('drive-search').value.trim().toLowerCase();
 const ds=inventory.devices.filter(d=>(driveFilter==='all'||(driveFilter==='ready'?usable(d):['warning','partial'].includes(d.health?.status)))&&[d.model,d.name,d.path,d.serial].some(s=>String(s||'').toLowerCase().includes(query)));
 el('selection-hint').textContent=mode==='raid'?'Select blank, unused drives. Your OS and in-use drives stay protected.':'Select data drives to test. Your OS drive is protected; its health details remain available.';
 el('drives').innerHTML=ds.map(d=>{
  const allowed=usable(d),role=d.is_os?'OS / system drive · Tests disabled':!d.test_allowed?'Tests disabled · Protection unverified':d.type.startsWith('raid')?'Software RAID array':mode==='raid'&&!allowed?'In use · Not available for RAID':'Data drive';
  return '<article class="drive-card '+(chosen.has(d.path)?'selected ':'')+(d.is_os?'protected':'')+'"><div class="drive-card-top"><div class="drive-glyph">'+driveIcon+'</div><div class="drive-identity"><h3>'+esc(d.model||d.name)+'</h3><small>'+esc(d.path)+' · '+esc(d.transport||d.type)+'</small><small>Serial '+esc(d.serial)+'</small></div><input type="checkbox" class="pick" data-path="'+esc(d.path)+'" aria-label="Select '+esc(d.model||d.name)+' '+esc(d.path)+'" '+(chosen.has(d.path)?'checked ':'')+(!allowed?'disabled':'')+'></div><div class="drive-role '+(d.is_os?'protected-role':'')+'">'+(d.is_os?'◇ ':'')+esc(role)+'</div><div class="drive-numbers"><div><span>Capacity</span><strong>'+esc(capacity(d.size))+'</strong></div><div><span>Temperature</span><strong>'+fmt(d.health?.temperature)+' <small>°C</small></strong></div><div><span>Endurance used</span><strong>'+fmt(d.health?.percentage_used)+' <small>%</small></strong></div></div><div class="drive-card-bottom">'+pill(healthLabel(d.health),healthTone(d.health))+'<button class="detail text-button" data-path="'+esc(d.path)+'" aria-label="Health details for '+esc(d.model||d.name)+' '+esc(d.path)+'">Health details →</button></div></article>';
 }).join('');
 if(!ds.length)el('drives').innerHTML='<div class="empty-filter">No drives match this view. Try another filter or search.</div>';
 if(ds.length===1&&!usable(ds[0])&&driveFilter==='all'&&!query)el('drives').innerHTML+='<div class="drive-helper"><span class="section-icon" aria-hidden="true">+</span><h3>'+ (mode==='raid'?'Add data drives to build an array':'A data drive is your next step')+'</h3><p>'+(mode==='raid'?'Connect at least two blank data drives, then refresh. We’ll help you choose a layout and preview the capacity before creating anything.':'Connect a separate data drive, then refresh. You can inspect the system drive’s health now, but performance tests on it are disabled.')+'</p></div>';
 document.querySelectorAll('.pick').forEach(c=>c.onchange=()=>{c.checked?chosen.add(c.dataset.path):chosen.delete(c.dataset.path);c.closest('.drive-card').classList.toggle('selected',c.checked);selection();});
 document.querySelectorAll('.detail').forEach(b=>b.onclick=()=>details(b.dataset.path));
 document.querySelectorAll('.drive-card').forEach(card=>card.onclick=e=>{if(e.target.closest('button,input,a'))return;const checkbox=card.querySelector('.pick');if(!checkbox.disabled)checkbox.click();});
 el('drive-guidance').innerHTML='<p class="guidance"><span aria-hidden="true">ⓘ</span><span><strong>Health data comes from the drive.</strong> Some controllers do not expose temperatures, wear or every SMART counter.</span></p>';
 selection();
}
function selection(){
 if(!inventory)return;
 const ds=selectedDrives(),n=ds.length;el('selected-count').textContent=n+' selected';
 if(mode==='raid'){
  const level=value('level'),l=layouts[level],validCount=n>=l.minimum&&(level!=='10'||n%2===0),factor=level==='0'?n:level==='1'?1:level==='5'?n-1:level==='6'?n-2:n/2;
  const total=ds.reduce((s,d)=>s+d.size,0),usableBytes=validCount?Math.min(...ds.map(d=>d.size))*factor:null;
  const slots=Math.max(l.minimum,n),tiles=Array.from({length:slots},(_,i)=>'<div class="member-tile '+(i<n?'':'ghost')+'">'+driveIcon+(i<n?'Drive '+(i+1):'Add drive')+'</div>').join('');
  el('raid-estimate').innerHTML='<div class="capacity-hero"><span>Estimated usable capacity</span><strong>'+esc(usableBytes===null?'—':capacity(usableBytes))+'</strong><small>RAID '+level+' · '+esc(l.title)+'</small></div><div class="member-map" aria-label="'+n+' of '+slots+' drive slots selected">'+tiles+'</div><dl class="preview-facts"><div><dt>Selected drives</dt><dd>'+n+' / '+l.minimum+' minimum</dd></div><div><dt>Failure tolerance</dt><dd>'+esc(l.tolerance)+'</dd></div><div><dt>Raw capacity</dt><dd>'+esc(n?capacity(total):'Select drives')+'</dd></div><div><dt>Usable space</dt><dd>'+ (usableBytes!==null?fmt(100*usableBytes/total,0)+'% before formatting':'Awaiting selection')+'</dd></div></dl><p class="field-help">'+esc(l.description)+'</p>'+(level==='0'?'<p class="alert">RAID 0 provides no drive-failure protection.</p>':'')+(n?'<div class="preview-members">'+ds.map(d=>'<span>'+esc(d.model||d.name)+' · '+esc(d.path)+' · '+esc(d.serial)+'</span>').join('')+'</div>':'');
  const validName=/^[a-zA-Z][a-zA-Z0-9_-]{0,23}$/.test(el('array-name').value);
  el('create').disabled=!validCount||!validName||running();
  el('create-hint').textContent=running()?'Wait for the active drive test to finish.':!n?'Select '+l.minimum+' or more blank data drives above.':!validCount?(level==='10'&&n>=4?'RAID 10 needs an even number of drives.':'Select '+(l.minimum-n)+' more drive'+(l.minimum-n===1?'':'s')+' for this layout.'):!validName?'Enter an array name starting with a letter.':'Nothing changes until you review the drives and type the confirmation.';
  return;
 }
 const profile=value('profile'),writing=['seq-write','mixed'].includes(profile);
 document.querySelectorAll('.mount').forEach(m=>mountChoices[m.dataset.path]=m.value);
 el('profile-explainer').textContent=workloads[profile].detail;
 el('mounts').innerHTML=writing?ds.map(d=>{
  const mounts=d.mountpoints.filter(m=>/^\/(mnt|media|srv)\//.test(m));
  return '<label>Write-test volume · '+esc(d.name)+'<select class="mount" data-path="'+esc(d.path)+'">'+(mounts.map(m=>'<option value="'+esc(m)+'" '+(mountChoices[d.path]===m?'selected':'')+'>'+esc(m)+'</option>').join('')||'<option value="">No eligible mounted data volume</option>')+'</select></label>';
 }).join(''):'';
 const missingMount=writing&&[...document.querySelectorAll('.mount')].some(m=>!m.value);
 document.querySelectorAll('.mount').forEach(m=>m.onchange=()=>{mountChoices[m.dataset.path]=m.value;selection();});
 el('test-summary').innerHTML=n?'<span class="pill">'+n+' drive'+(n===1?'':'s')+'</span><span>'+esc(workloads[profile].title)+' · '+esc(el('duration').selectedOptions[0].textContent)+'</span>':'<span>Choose a data drive above to begin.</span>';
 el('start').disabled=!n||missingMount||running();
 el('start-hint').textContent=running()?'A test is already running. Stop it or wait for it to finish.':missingMount?'Mount a data filesystem under /mnt, /media or /srv in Cockpit Storage before running a write test.':n?'The next step shows the exact drives and settings. Selected drives run at the same time.':'You can explore test options while no data drive is selected.';
}
function details(path){
 const d=inventory.devices.find(x=>x.path===path),h=d.health||{};
 el('details-title').textContent=d.model||d.name;
 const grid=items=>'<dl class="details-grid">'+items.map(([k,v])=>'<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>').join('')+'</dl>';
 el('details-body').innerHTML=pill(healthLabel(h),healthTone(h))+'<p>'+esc(healthExplanation(h))+'</p>'+(d.is_os?'<div class="inspector-note protection">OS / system drive — all performance tests are disabled. You can still inspect its identity and health.</div>':!d.test_allowed?'<div class="inspector-note protection">'+esc(d.test_block_reason)+'</div>':'')+grid([['Device',d.path],['Serial number',d.serial],['Capacity',capacity(d.size)],['Interface',d.transport||d.type],['Firmware',h.firmware],['WWN',d.wwn]])+'<div class="inspector-section"><h3>Health &amp; lifetime readings</h3>'+grid([['Temperature',numeric(h.temperature)?fmt(h.temperature)+' °C':'Not reported'],['Endurance used',numeric(h.percentage_used)?fmt(h.percentage_used)+'%':'Not reported'],['Power-on hours',h.power_on_hours],['Unsafe shutdowns',h.unsafe_shutdowns],...Object.entries(errorFields).filter(([k])=>h[k]!=null).map(([k,label])=>[label,h[k]])])+'</div>'+((h.alerts||[]).length?'<div class="alert error">'+esc(h.alerts.join('; '))+'</div>':'')+'<div class="inspector-section"><h3>How this drive is being used</h3><p>'+esc(d.mountpoints.join(', ')||'No mounted volumes')+'</p><p>'+esc(d.reasons.join('; ')||'Blank and available for a new array')+'</p></div><details><summary>Advanced SMART details</summary><p>'+esc((h.messages||[]).join('; ')||'Complete vendor response below.')+'</p><pre>'+esc(JSON.stringify(h.raw||{},null,2))+'</pre></details>';
 el('details').showModal();
}
function review(title,body,confirmation,fn){
 reviewAction=fn;el('review-title').textContent=title;el('review-body').innerHTML=body;el('confirmation').value='';el('confirmation').placeholder=confirmation||'';el('confirmation-label').classList.toggle('hidden',!confirmation);el('review-apply').disabled=Boolean(confirmation);el('review-apply').textContent=confirmation?'Confirm storage change':'Start test';el('confirmation').oninput=()=>el('review-apply').disabled=el('confirmation').value!==confirmation;el('review').showModal();
}
function navigate(page,device){
 if(typeof cockpit.jump==='function')cockpit.jump('/cockpit_support/'+page+(device?'#/?device='+encodeURIComponent(device):''));
 else location.href=page+'.html'+(device?'?device='+encodeURIComponent(device):'');
}
function selectFromLocation(){
 const requested=new URLSearchParams(location.search).get('device')||new URLSearchParams(location.hash.split('?')[1]||'').get('device');
 if(requested){chosen.add(requested);if(inventory)renderDrives();}
}
function reviewDrives(ds){return '<div class="review-list">'+ds.map(d=>'<div class="review-drive"><strong>'+esc(d.model||d.name||d.path)+'</strong><small>'+esc(d.path)+' · Serial '+esc(d.serial||d.drive?.serial)+' · '+esc(capacity(d.size||d.drive?.size))+'</small></div>').join('')+'</div>';}
async function start(){
 const ds=selectedDrives();if(!ds.length||el('start').disabled)return;
 const profile=value('profile'),req={devices:ds.map(d=>d.path),profile,duration:Number(el('duration').value),depth:Number(el('depth').value),size_gib:Number(el('size').value),customer:el('customer').value,reference:el('reference').value,mounts:{}};
 document.querySelectorAll('.mount').forEach(m=>req.mounts[m.dataset.path]=m.value);
 review('Ready to test '+ds.length+' drive'+(ds.length===1?'?':'s?'),reviewDrives(ds)+'<dl class="preview-facts"><div><dt>Workload</dt><dd>'+esc(workloads[profile].title)+'</dd></div><div><dt>Duration per drive</dt><dd>'+req.duration+' seconds</dd></div><div><dt>Queue depth</dt><dd>'+req.depth+'</dd></div><div><dt>Test size</dt><dd>'+req.size_gib+' GiB</dd></div></dl><p>'+esc(workloads[profile].detail)+'</p><p>Selected drives run together. Other workloads may slow down. You can stop the test and keep partial results.</p>',null,async()=>{current=await api('start',req);notice('Test started. It will continue if you leave this tab.');await loadJobs();});
}
function chart(samples){
 const valid=samples.map(s=>({...s,bandwidth:(s.bandwidth||[]).filter(p=>p.every(Number.isFinite))})),points=valid.flatMap(s=>s.bandwidth),maxX=Math.max(1,...points.map(p=>p[0])),maxY=Math.max(1,...points.map(p=>p[1]));
 return '<svg class="chart" viewBox="0 0 560 180" role="img" aria-label="Cumulative average throughput over time in MiB per second"><path class="grid" d="M45 30H535M45 85H535M45 140H535"/><text x="12" y="19">'+fmt(maxY,0)+' MiB/s</text><text x="45" y="164">0 s</text><text x="490" y="164">'+fmt(maxX,0)+' s</text>'+valid.map((s,i)=>'<polyline stroke="'+colors[i%colors.length]+'" points="'+s.bandwidth.map(p=>(45+p[0]/maxX*490).toFixed(1)+','+(140-p[1]/maxY*110).toFixed(1)).join(' ')+'"/>').join('')+'</svg><div class="legend">'+valid.map((s,i)=>'<span><i style="background:'+colors[i%colors.length]+'"></i>'+esc(s.path)+'</span>').join('')+'</div>';
}
function statePill(status){return pill(({completed:'Completed',running:'Running',queued:'Preparing',cancelled:'Stopped',failed:'Test failed',interrupted:'Interrupted'})[status]||status,status==='completed'?'good':status==='failed'?'bad':['cancelled','interrupted'].includes(status)?'warn':'neutral');}
function renderActive(d){
 const wasRunning=running();current=d;const signature=JSON.stringify(d);if(signature===activeSignature)return;activeSignature=signature;
 if(el('results-title'))el('results-title').textContent=d?(['queued','running'].includes(d.status)?'Test in progress':'Last test result'):'Ready when you are';
 if(el('results-subtitle'))el('results-subtitle').textContent=d?new Date(d.created*1000).toLocaleString():'Live performance and health, in one place.';
 if(!d){el('active').innerHTML='<div class="empty-state">'+emptyArt+'<h3>A clear picture of performance.</h3><p>Start a test to see speed, response time, temperature and drive errors here.</p><ol class="empty-guide"><li><b>1</b>Select a data drive</li><li><b>2</b>Choose a workload and duration</li><li><b>3</b>Review results and export a client report</li></ol></div>';selection();return;}
 const active=['queued','running'].includes(d.status),rs=d.results||[],metrics=rs.flatMap(r=>r.metrics),read=metrics.reduce((s,j)=>s+(j.read?.mib_s||0),0),write=metrics.reduce((s,j)=>s+(j.write?.mib_s||0),0),progress=Math.min(100,Math.max(0,(d.elapsed||0)/d.config.duration*100));
 let content='<div class="run-head">'+statePill(d.status)+'<small>'+fmt(d.elapsed||0,0)+'s elapsed · '+d.config.duration+'s planned</small></div><div class="progress" role="progressbar" aria-label="Test duration" aria-valuenow="'+Math.round(progress)+'" aria-valuemin="0" aria-valuemax="100"><div style="width:'+progress+'%"></div></div><p class="run-meta">'+esc(workloads[d.config.profile]?.title||d.config.profile)+' · '+d.config.devices.length+' drive'+(d.config.devices.length===1?'':'s')+' · '+esc(d.config.reference||'No reference added')+'</p><div class="run-stats"><div class="result-number"><span>READ SPEED · TOTAL</span><strong>'+fmt(metrics.length?read:null,0)+'</strong><small>MiB/s</small></div><div class="result-number"><span>WRITE SPEED · TOTAL</span><strong>'+fmt(metrics.length?write:null,0)+'</strong><small>MiB/s</small></div></div>'+chart(d.samples||[])+'<p class="field-help">Cumulative average throughput. Results reflect this workload and test size.</p>';
 for(const t of d.config.devices){
  const path=t.path,h=d.health_samples?.at(-1)?.drives?.[path]||d.after?.[path]||d.before?.[path]||{},before=d.before?.[path]||{},temps=(d.temperature_samples||[]).map(x=>x.temperatures?.[path]).filter(Number.isFinite),metric=rs.find(r=>r.path===path)?.metrics?.[0];
  const increases=Object.entries(errorFields).filter(([k])=>numeric(h[k])&&numeric(before[k])&&h[k]>before[k]).map(([k,label])=>label+': +'+(h[k]-before[k]));
  content+='<div class="run-drive"><div class="run-drive-title"><span>'+esc(t.model||t.name||path)+'</span><small>'+esc(path)+'</small></div><div class="health-line">'+pill(healthLabel(h),healthTone(h))+'<span>Latest '+fmt(h.temperature)+' °C · Peak '+fmt(temps.length?Math.max(...temps):null)+' °C</span></div>'+(increases.length?'<p class="alert">'+esc(increases.join(' · '))+'</p>':'')+(metric?'<details><summary>Response time &amp; IOPS</summary><dl class="preview-facts"><div><dt>Read / write IOPS</dt><dd>'+fmt(metric.read?.iops,0)+' / '+fmt(metric.write?.iops,0)+'</dd></div><div><dt>P99 latency · read / write</dt><dd>'+fmt(metric.read?.latency_p99_ms,3)+' / '+fmt(metric.write?.latency_p99_ms,3)+' ms</dd></div></dl></details>':'')+'</div>';
 }
 const errors=[...(d.errors||[]),...(d.cleanup_warnings||[]),...(d.error?[d.error]:[])];
 if(errors.length)content+='<div class="alert error">'+esc(errors.join('; '))+'</div>';
 if(d.health_warnings?.length)content+='<div class="alert">Health warnings or increased error counters were recorded. Review the full report before accepting this drive.</div>';
 if(['cancelled','interrupted','failed'].includes(d.status))content+='<p class="field-help">This test is incomplete. Its recorded measurements are retained, but it is not a passing result.</p>';
 content+='<div class="toolbar result-actions">'+(active?'<button id="stop" class="danger">Stop test</button>':'<button id="active-report" class="primary">Download HTML report ↗</button>')+'</div>';
 el('active').innerHTML=content;
 if(el('stop'))el('stop').onclick=()=>action(async()=>{notice((await api('stop',{id:d.id})).message);});
 if(el('active-report'))el('active-report').onclick=()=>action(()=>exportReport(d.id));
 if(wasRunning!==running())selection();
}
function download(text,name,type){const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
async function exportReport(id){const r=await api('report',{id});download(r.html,'BIZON-storage-'+id.slice(0,8)+'.html','text/html');}
async function loadJobs(){
 const jobs=await api('jobs'),signature=JSON.stringify(jobs);
 if(signature!==historySignature){
  historySignature=signature;el('history-count').textContent=jobs.length+' test'+(jobs.length===1?'':'s');
  el('history').innerHTML=jobs.map(d=>'<div class="history-row"><span class="history-icon" aria-hidden="true">▤</span><div><strong>'+esc(d.config.reference||workloads[d.config.profile]?.title||d.config.profile)+'</strong><small>'+esc(new Date(d.created*1000).toLocaleString())+' · '+esc(d.config.devices.map(t=>t.model||t.path).join(', '))+'</small></div>'+statePill(d.status)+'<div class="toolbar"><button data-job="'+esc(d.id)+'" data-format="view">View result</button><button class="download-report" data-job="'+esc(d.id)+'" data-format="html">HTML report ↗</button><button class="quiet" data-job="'+esc(d.id)+'" data-format="json" aria-label="Download complete JSON record for '+esc(d.config.reference||d.id)+'">JSON</button></div></div>').join('')||'<div class="empty-filter">Your completed and stopped tests will appear here. Reports are saved even after you close this tab.</div>';
  document.querySelectorAll('[data-job]').forEach(b=>b.onclick=()=>action(async()=>{const id=b.dataset.job;if(b.dataset.format==='html')await exportReport(id);else{const r=await api('status',{id});if(b.dataset.format==='view'){renderActive(r);el('active').scrollIntoView({block:'nearest',behavior:'smooth'});}else download(JSON.stringify(r,null,2),'BIZON-storage-'+id.slice(0,8)+'.json','application/json');}}));
 }
 const active=jobs.find(d=>['running','queued'].includes(d.status)),selected=active||jobs.find(d=>d.id===current?.id)||jobs[0];
 renderActive(selected?await api('status',{id:selected.id}):null);
}
function renderArrays(){
 el('arrays').innerHTML=inventory.arrays.map(a=>{
  const device=inventory.devices.find(d=>d.path===a.path),protectedArray=!device?.test_allowed,busyArray=a.sync_action&&a.sync_action!=='idle',degraded=numeric(a.degraded)&&Number(a.degraded)>0,issues=degraded||(numeric(a.mismatch_count)&&Number(a.mismatch_count)>0),healthy=numeric(a.degraded)&&Number(a.degraded)===0&&['active','clean','readonly','read-auto'].includes(a.state);
  return '<article class="array-item"><div class="array-heading"><h3>'+esc(a.path)+'</h3>'+pill(issues?'Needs attention':busyArray?'Sync / check active':'Array '+(a.state||'status unknown'),issues?'bad':busyArray||!healthy?'neutral':'good')+'</div><div class="array-capacity">'+esc(capacity(a.size))+'</div><p>'+esc(a.level?.toUpperCase())+' · '+a.members.length+' members'+(protectedArray?' · System / protected':'')+'</p><div class="array-members">'+a.members.map(m=>'<span>'+esc(m.path)+' · '+esc(m.state)+'</span>').join('')+'</div>'+(busyArray?'<p>Activity: '+esc(a.sync_action)+' · '+esc(a.sync_completed||'Progress not reported')+'</p>':'')+'<p>Mismatched sectors: '+esc(a.mismatch_count)+'</p><div class="array-actions"><button data-array="'+esc(a.path)+'" data-action="test" '+(protectedArray||busyArray?'disabled':'')+'>Speed test</button><button data-array="'+esc(a.path)+'" data-action="check" '+(protectedArray||a.level==='raid0'||a.sync_action!=='idle'?'disabled':'')+'>Check integrity</button><button data-array="'+esc(a.path)+'" data-action="delete" class="danger" '+(protectedArray||a.mountpoints.length||busyArray?'disabled':'')+'>Delete</button></div></article>';
 }).join('')||'<div class="empty-state">'+emptyArt+'<h3>No arrays yet.</h3><p>Your arrays will appear here with their capacity, member drives and sync status.</p></div>';
 document.querySelectorAll('[data-array]').forEach(b=>b.onclick=()=>action(async()=>{
  if(b.dataset.action==='test'){navigate('drives',b.dataset.array);return;}
  if(b.dataset.action==='check'){review('Check array integrity?','<p>Reads redundant array data and may slow other workloads. This requests a consistency check, without automatic repair.</p>',null,async()=>{notice((await api('raid-check',{path:b.dataset.array})).message);await refresh();});el('review-apply').textContent='Start integrity check';return;}
  await plan({action:'delete',path:b.dataset.array});
 }));
}
async function plan(req){
 const p=await api('raid-plan',req),creating=p.config.action==='create',paths=creating?p.config.devices:p.config.members;
 const ds=paths.map(d=>({...d,model:inventory.devices.find(x=>x.path===d.path)?.model}));
 const body='<div class="alert '+(creating?'':'error')+'">'+esc(p.warning)+'</div>'+reviewDrives(ds)+(creating?'<dl class="preview-facts"><div><dt>Array name</dt><dd>'+esc(p.config.name)+'</dd></div><div><dt>Layout</dt><dd>RAID '+esc(p.config.level)+'</dd></div><div><dt>Estimated usable capacity</dt><dd>'+esc(capacity(p.capacity))+'</dd></div><div><dt>After creation</dt><dd>Format and mount in Cockpit Storage</dd></div></dl>':'<p>Array: <strong>'+esc(p.config.array.path)+'</strong>. Its data will become inaccessible.</p>')+'<p>Type <strong>'+esc(p.confirmation)+'</strong> to confirm these exact drives. This review expires in 5 minutes.</p>';
 review(creating?'Review your new array':'Delete this array?',body,p.confirmation,async()=>{notice('Applying the reviewed storage change…');const r=await api('raid-apply',{token:p.token,confirmation:el('confirmation').value});notice(r.message);chosen.clear();await refresh();});
}
async function refresh(){
 inventory=await api('inventory');drawMetrics();renderDrives();if(mode==='raid')renderArrays();
 el('connection').textContent=inventory.host+' · Updated '+new Date().toLocaleTimeString([],{hour:'2-digit',minute:'2-digit'});
 const missing=Object.entries(inventory.tools).filter(([,ok])=>!ok).map(([k])=>k);el('install-tools').classList.toggle('hidden',!missing.length);
 if(missing.length)notice('Storage tools are missing: '+missing.join(', ')+'. Install them to enable all features.',true);else if(el('notice').textContent.startsWith('Loading'))notice('');
 await loadJobs();
}
el('refresh').onclick=()=>action(refresh);el('install-tools').onclick=()=>action(async()=>{notice('Installing the required Ubuntu storage packages…');notice((await api('install-tools')).message);await refresh();});
el('details-close').onclick=()=>el('details').close();el('review-cancel').onclick=()=>el('review').close();el('review-apply').onclick=()=>action(async()=>{el('review').close();await reviewAction();});
el('drive-search').oninput=renderDrives;
 document.querySelectorAll('.workspace-nav nav a').forEach(a=>a.onclick=e=>{if(e.ctrlKey||e.metaKey||e.shiftKey||e.altKey)return;e.preventDefault();navigate(a.getAttribute('href').split('.')[0]);});
document.querySelectorAll('[data-filter]').forEach(b=>b.onclick=()=>{driveFilter=b.dataset.filter;document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));renderDrives();});
if(mode==='drives'){
 document.querySelectorAll('[name=profile]').forEach(r=>r.onchange=selection);el('duration').onchange=selection;el('start').onclick=()=>action(start);
 selectFromLocation();window.addEventListener('hashchange',selectFromLocation);
}else{
 document.querySelectorAll('[name=level]').forEach(r=>r.onchange=selection);el('array-name').oninput=selection;el('create').onclick=()=>action(()=>{if(!el('create').disabled)return plan({action:'create',devices:selectedDrives().map(d=>d.path),level:value('level'),name:el('array-name').value});});
}
action(refresh);
setInterval(async()=>{if(polling||busy||document.hidden||cockpit.hidden||el('review').open||el('details').open)return;polling=true;try{await loadJobs();if(mode==='raid'&&inventory){const arrays=await api('arrays');if(JSON.stringify(arrays)!==JSON.stringify(inventory.arrays)){inventory.arrays=arrays;renderArrays();}}}catch(e){notice(e.message,true);}finally{polling=false;}},3000);
