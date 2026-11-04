const fs=require('node:fs');
const assert=require('node:assert/strict');
const {JSDOM}=require('jsdom');
let passed=0;
const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
class Deferred extends Promise{always(fn){return this.finally(fn);}}
async function flush(){for(let i=0;i<12;i++)await Promise.resolve();}
function setup(){
 const dom=new JSDOM(fs.readFileSync('cockpit_support/support.html','utf8'),{runScripts:'outside-only',url:'https://workstation.test/cockpit_support/support.html'}),w=dom.window;
 let counter=0;const requests=[],timers=new Map();
 w.setTimeout=(fn,ms)=>{timers.set(++counter,{fn,ms});return counter;};w.clearTimeout=id=>timers.delete(id);
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.cockpit={spawn(args,options){let resolve,reject;const p=new Deferred((a,b)=>{resolve=a;reject=b;});const request={args,options,p,resolve,reject,closed:false};p.stream=fn=>{request.stream=fn;return p;};p.close=()=>{request.closed=true;reject(Object.assign(new Error('closed'),{problem:'cancelled'}));};requests.push(request);return p;}};
 w.eval(fs.readFileSync('cockpit_support/updates.js','utf8'));
 const el=id=>w.document.getElementById(id),click=id=>el(id).click();
 const last=action=>requests.filter(r=>r.args.at(-1)==='--action='+action).at(-1);
 const versions=async()=>{for(const r of requests.filter(r=>r.args.at(-1)==='--action=version'))r.resolve('{"version":"v1.0.0"}');await flush();};
 return {dom,w,el,click,last,versions,requests,timers};
}
(async()=>{
 const t=setup();await t.versions();
 check('initial load reads only installed version',()=>{assert.equal(t.requests.length,1);assert.equal(t.el('version').textContent,'v1.0.0');assert(t.el('update').disabled);});
 t.click('check');let r=t.last('check');
 check('check prevents overlapping requests',()=>{assert(t.el('check').disabled);assert(t.el('rollback').disabled);t.click('check');assert.equal(t.requests.filter(x=>x.args.at(-1)==='--action=check').length,1);});
 r.stream('{"message":"Found release","remote":"v1.1.0","local":"v1.0.0",');r.stream('"update_available":true}\n');r.resolve();await flush();
 check('split response enables update and displays both versions',()=>{assert.equal(t.el('latest-version').textContent,'v1.1.0');assert(!t.el('update').disabled);assert.match(t.el('status').textContent,/new release/);});
 await t.versions();t.click('update');
 check('install requires explicit review',()=>{assert(t.el('confirm').open);assert(!t.last('update'));});
 t.click('cancel');check('cancel review makes no changes',()=>{assert(!t.el('confirm').open);assert(!t.last('update'));});
 t.click('update');t.click('confirm-action');r=t.last('update');
 check('install keeps required administrative access',()=>assert.equal(r.options.superuser,'require'));
 r.stream('{"message":"Update installed","success":true,"version":"v1.1.0"}\n');r.resolve();await flush();
 check('success offers reload without replacing the shell automatically',()=>{assert(!t.el('reload').hidden);assert.equal(t.el('status').textContent,'Update installed');assert([...t.timers.values()].every(x=>x.ms!==1500));assert(t.el('check').disabled);});
 await t.versions();t.dom.window.close();
 const e=setup();await e.versions();e.click('check');r=e.last('check');r.stream('{"message":"Signature invalid","success":false}\n');r.resolve();await flush();
 check('backend failure cannot be reported as successful',()=>{assert.equal(e.el('status-panel').dataset.state,'error');assert.equal(e.el('status-detail').textContent,'Signature invalid');assert(e.el('update').disabled);assert(e.el('update-details').open);});
 await e.versions();e.click('check');r=e.last('check');const deadline=[...e.timers.values()].find(x=>x.ms===30000);deadline.fn();await flush();
 check('stalled check times out and permits retry',()=>{assert(r.closed);assert.equal(e.el('status-panel').dataset.state,'error');assert.match(e.el('status-detail').textContent,/took too long/);assert(!e.el('check').disabled);});
 await e.versions();e.click('check');r=e.last('check');r.stream('x'.repeat(48000));r.reject(new Error('Network error'));await flush();
 check('diagnostic output is bounded and rendered as text',()=>{assert(e.el('log').textContent.length<=24000);assert.equal(e.el('log').children.length,0);});
 await e.versions();e.click('rollback');e.click('confirm-action');r=e.last('rollback');r.reject(Object.assign(new Error('Denied'),{problem:'access-denied'}));await flush();
 check('administrator failure gives actionable instructions',()=>assert.match(e.el('status-detail').textContent,/Enable administrative access/));
 await e.versions();e.click('check');r=e.last('check');r.stream('{"message":"Current","remote":"v1.0.0","update_available":false}\n');r.resolve();await flush();
 check('up-to-date result restores idle controls',()=>{assert.equal(e.el('status').textContent,'Your tabs are up to date');assert(!e.el('check').disabled);assert(e.el('update').disabled);});
 await e.versions();e.dom.window.close();
 console.log(passed+'/'+passed+' updater UI checks passed');
})().catch(err=>{console.error(err);process.exitCode=1;});
