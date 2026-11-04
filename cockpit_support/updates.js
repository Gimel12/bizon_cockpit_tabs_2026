'use strict';
const helper='/usr/local/libexec/bizon-tabs-update';
const el=id=>document.getElementById(id);
let pending='update',available=false;
function version(){cockpit.spawn(['/usr/bin/python3','-I',helper,'--action=version'],{err:'message'}).then(out=>{const info=JSON.parse(out);el('version').textContent=info.version;}).catch(()=>{el('version').textContent='Version information unavailable';});}
function run(action){
  let buffer='',failure='',changed=false;
  el('status').className='';el('status').textContent=action==='check'?'Checking for updates…':'Applying release…';el('log').textContent='';
  ['check','update','rollback'].forEach(id=>el(id).disabled=true);
  function line(text){if(!text.trim())return;try{const info=JSON.parse(text);el('log').textContent+=info.message+'\n';if(info.success===false)failure=info.message;if(typeof info.update_available==='boolean')available=info.update_available;if(info.success===true)changed=true;}catch{el('log').textContent+=text+'\n';}}
  const options={err:'message'};if(action!=='check')options.superuser='require';
  cockpit.spawn(['/usr/bin/python3','-I',helper,'--action='+action],options).stream(data=>{buffer+=data;let pos;while((pos=buffer.indexOf('\n'))>=0){line(buffer.slice(0,pos));buffer=buffer.slice(pos+1);}}).then(()=>{
    line(buffer);el('status').className='success';el('status').textContent=changed?'Release applied. Reloading tabs…':available?'An update is available.':'Your tabs are up to date.';
    if(changed)setTimeout(()=>window.top.location.reload(),1500);
  }).catch(err=>{line(buffer);el('status').className='error';el('status').textContent=failure||(err.problem==='access-denied'?'Enable administrative access in Cockpit, then try again.':err.message)||'Could not complete the request';}).always(()=>{el('check').disabled=false;el('rollback').disabled=false;el('update').disabled=!available;version();});
}
el('check').addEventListener('click',()=>run('check'));
for(const action of ['update','rollback'])el(action).addEventListener('click',()=>{pending=action;el('confirm-title').textContent=action==='update'?'Install official update?':'Restore previous version?';el('confirm-copy').textContent=action==='update'?'The verified BIZON release will replace the installed tabs. Cockpit will reload when it finishes.':'The previous installed release will become active. Cockpit will reload when it finishes.';el('confirm').showModal();});
el('cancel').addEventListener('click',()=>el('confirm').close());
el('confirm-action').addEventListener('click',()=>{el('confirm').close();run(pending);});
version();
