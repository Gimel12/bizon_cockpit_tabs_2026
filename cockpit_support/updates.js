'use strict';
const helper='/usr/local/libexec/bizon-tabs-update';
const el=id=>document.getElementById(id);
let pending='update',available=false,busy=false,needsReload=false,versionGeneration=0;
const MAX_LOG=24000,READ_TIMEOUT=30000;
function status(state,title,detail){
  el('status-panel').dataset.state=state;
  el('status').textContent=title;
  el('status-detail').textContent=detail;
  el('progress').hidden=state!=='busy';
}
function controls(){
  el('check').disabled=busy||needsReload;
  el('update').disabled=busy||!available||needsReload;
  el('rollback').disabled=busy||needsReload;
  el('reload').hidden=!needsReload;
  el('confirm-action').disabled=busy;
  el('update').classList.toggle('primary',available);
  el('check').classList.toggle('primary',!available);
}
function version(){
  const generation=++versionGeneration;
  let timedOut=false;
  const request=cockpit.spawn(['/usr/bin/python3','-I',helper,'--action=version'],{err:'message'});
  const timer=setTimeout(()=>{timedOut=true;if(generation===versionGeneration)el('version').textContent='Unavailable';request.close();},10000);
  request.then(out=>{
    if(generation!==versionGeneration||timedOut)return;
    const info=JSON.parse(out);
    el('version').textContent=typeof info.version==='string'?info.version:'Unavailable';
  }).catch(()=>{if(generation===versionGeneration)el('version').textContent='Unavailable';}).always(()=>clearTimeout(timer));
}
function run(action){
  if(busy||needsReload)return;
  busy=true;available=false;controls();
  let buffer='',failure='',changed=false,timedOut=false,timer;
  const checking=action==='check';
  status('busy',checking?'Checking for updates…':action==='rollback'?'Restoring the previous release…':'Installing your update…',checking?'Contacting the official BIZON release channel.':'Keep this tab open while the verified release is applied.');
  el('log').textContent='';
  function log(message){el('log').textContent=(el('log').textContent+message+'\n').slice(-MAX_LOG);}
  function line(text){
    if(!text.trim())return;
    try{
      const info=JSON.parse(text);
      if(typeof info.message==='string')log(info.message);
      if(info.success===false)failure=info.message||'The release could not be applied.';
      if(typeof info.update_available==='boolean')available=info.update_available;
      if(typeof info.remote==='string')el('latest-version').textContent=info.remote;
      if(typeof info.local==='string')el('version').textContent=info.local;
      if(info.success===true){changed=true;if(typeof info.version==='string')el('version').textContent=info.version;}
    }catch{log(text);}
  }
  const options={err:'message'};if(!checking)options.superuser='require';
  const request=cockpit.spawn(['/usr/bin/python3','-I',helper,'--action='+action],options);
  if(checking)timer=setTimeout(()=>{timedOut=true;request.close();},READ_TIMEOUT);
  request.stream(data=>{
    buffer+=data;
    let pos;while((pos=buffer.indexOf('\n'))>=0){line(buffer.slice(0,pos));buffer=buffer.slice(pos+1);}
    // Keep malformed or unexpectedly verbose output from growing the page indefinitely.
    if(buffer.length>MAX_LOG){log(buffer.slice(0,MAX_LOG));buffer='';}
  }).then(()=>{
    line(buffer);buffer='';
    if(failure)throw new Error(failure);
    if(timedOut)throw new Error('The update check took too long. Check your internet connection and try again.');
    if(changed){
      needsReload=true;available=false;
      status('success',action==='rollback'?'Previous release restored':'Update installed','Reload tabs when you’re ready to use this release. Save any work in remote desktop sessions first.');
    }else if(available){
      status('available','A new release is ready','Choose Install update to download and verify it.');
    }else{
      status('success','Your tabs are up to date','You’re using the latest published BIZON release.');
    }
  }).catch(err=>{
    line(buffer);buffer='';available=false;
    const message=timedOut?'The update check took too long. Check your internet connection and try again.':failure||(err.problem==='access-denied'?'Enable administrative access in Cockpit, then try again.':err.message)||'Could not complete the request. Please try again.';
    status('error','Couldn’t complete the request',message);
    el('update-details').open=true;
  }).always(()=>{clearTimeout(timer);busy=false;controls();version();});
}
el('check').addEventListener('click',()=>run('check'));
for(const action of ['update','rollback'])el(action).addEventListener('click',()=>{
  if(busy||needsReload||(action==='update'&&!available))return;
  pending=action;
  el('confirm-title').textContent=action==='update'?'Install official update?':'Restore previous version?';
  el('confirm-copy').textContent=action==='update'?'The verified BIZON release will replace your installed tabs. You can reload Cockpit when the update finishes.':'The previous installed release will become active. You can reload Cockpit when the restore finishes.';
  el('confirm').showModal();
});
el('cancel').addEventListener('click',()=>el('confirm').close());
el('confirm-action').addEventListener('click',()=>{el('confirm').close();run(pending);});
el('reload').addEventListener('click',()=>window.top.location.reload());
version();
