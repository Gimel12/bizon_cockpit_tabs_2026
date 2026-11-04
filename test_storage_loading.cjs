/* Run with jsdom@26 in NODE_PATH. No real storage operations are performed. */
const {JSDOM}=require('jsdom'),fs=require('node:fs'),assert=require('node:assert/strict');
let count=0;
const check=(name,fn)=>{fn();count++;console.log('PASS '+name);};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
function setup(){
 const dom=new JSDOM(fs.readFileSync('cockpit_support/raid.html','utf8'),{runScripts:'outside-only',url:'https://fixture.test/raid'}),w=dom.window,timers=new Map(),pollers=[],requests=[];
 w.eval(fs.readFileSync('tests/storage-ui-fixture.js','utf8'));
 let timerId=0;
 w.setTimeout=(fn,ms)=>{timers.set(++timerId,{fn,ms});return timerId;};w.clearTimeout=id=>timers.delete(id);w.setInterval=fn=>pollers.push(fn);
 w.cockpit.spawn=args=>{
  const p={action:args[3],closed:0,stream(fn){this.onData=fn;return this;},then(fn){this.onDone=fn;return this;},catch(fn){this.onError=fn;return this;},close(){this.closed++;},resolve(data){this.onData(JSON.stringify({ok:true,data}));this.onDone();},reject(error){this.onError(error);}};
  requests.push(p);return p;
 };
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};
 w.eval(fs.readFileSync('cockpit_support/storage/storage.js','utf8')+'\nwindow.loadingTest={api};');
 return{dom,w,d:w.document,timers,pollers,requests};
}
(async()=>{
 for(const page of ['drives','raid'])check(page+' paints static loading content before scripts finish',()=>{
  const dom=new JSDOM(fs.readFileSync('cockpit_support/'+page+'.html','utf8')),d=dom.window.document;
  assert(d.querySelector('#storage-loading').textContent.includes('Opening your storage workspace'));
  const core=d.querySelector('script[src="../base1/cockpit.js"]'),logic=d.querySelector('script[src="storage/storage.js"]');
  assert(core.defer&&logic.defer);assert(core.compareDocumentPosition(logic)&dom.window.Node.DOCUMENT_POSITION_FOLLOWING);dom.window.close();
 });
 const t=setup();
 check('initial inventory shows busy state and disables changes',()=>{assert.equal(t.d.querySelector('.drive-panel').getAttribute('aria-busy'),'true');assert(t.d.querySelector('#refresh').disabled);assert(t.d.querySelector('#create').disabled);assert.equal(t.requests[0].action,'inventory');});
 check('inventory deadline is bounded at sixty seconds',()=>assert([...t.timers.values()].some(x=>x.ms===60000)));
 [...t.timers.values()].find(x=>x.ms===60000).fn();await flush();
 check('stalled inventory closes only its read channel and offers retry',()=>{assert.equal(t.requests[0].closed,1);assert(!t.d.querySelector('#load-retry').classList.contains('hidden'));assert(!t.d.querySelector('#refresh').disabled);assert.match(t.d.querySelector('#load-help').textContent,/too long/);assert(t.d.querySelector('#create').disabled);});
 const total=t.requests.length;await t.pollers[0]();
 check('failed inventory does not start background polling',()=>assert.equal(t.requests.length,total));
 t.requests[0].resolve(t.w.fixtureInventory);await flush();
 check('late timed-out response cannot reactivate the page',()=>{assert.equal(t.d.querySelectorAll('.drive-card').length,0);assert(t.d.querySelector('#storage-loading').classList.contains('failed'));});
 t.d.querySelector('#load-retry').click();
 check('retry starts a fresh inventory request',()=>assert.equal(t.requests.filter(x=>x.action==='inventory').length,2));
 t.requests.at(-1).resolve(t.w.fixtureInventory);await flush();
 check('drive inventory renders before history finishes',()=>{assert.equal(t.d.querySelectorAll('.drive-card').length,6);assert(t.d.querySelector('#storage-loading').classList.contains('hidden'));assert.equal(t.requests.at(-1).action,'jobs');assert(t.d.querySelector('#refresh').disabled);assert.match(t.d.querySelector('#connection').textContent,/Loading recent tests/);});
 t.requests.at(-1).reject(new Error('History unavailable'));await flush();
 check('history failure keeps the rendered inventory and explains the error',()=>{assert.equal(t.d.querySelectorAll('.drive-card').length,6);assert.match(t.d.querySelector('#notice').textContent,/history could not be loaded/);assert(t.d.querySelector('.pick[data-path="/dev/nvme0n1"]').disabled);assert(!t.d.querySelector('#refresh').disabled);assert(!t.d.querySelector('#connection').textContent.includes('Loading recent tests'));});
 t.w.cockpit.hidden=true;const beforeHidden=t.requests.length;await t.pollers[0]();
 check('hidden Cockpit tabs skip polling',()=>assert.equal(t.requests.length,beforeHidden));
 t.w.cockpit.hidden=false;Object.defineProperty(t.d,'hidden',{value:false,configurable:true});const poll=t.pollers[0]();const beforeOverlap=t.requests.length;await t.pollers[0]();
 check('slow background polling never overlaps another poll',()=>assert.equal(t.requests.length,beforeOverlap));
 t.requests.at(-1).resolve([]);await flush();t.requests.at(-1).resolve([]);await poll;
 const noWriteTimer=t.timers.size;const mutation=t.w.loadingTest.api('raid-apply',{token:'fixture-only'});
 check('storage-changing actions are never given read-only cancellation deadlines',()=>assert.equal(t.timers.size,noWriteTimer));t.requests.at(-1).resolve({message:'fixture'});await mutation;
 t.d.querySelector('#refresh').click();t.requests.at(-1).reject({problem:'access-denied'});await flush();
 check('administrative access failure is actionable and can be retried',()=>{assert.match(t.d.querySelector('#load-help').textContent,/administrative access/);assert(!t.d.querySelector('#load-retry').classList.contains('hidden'));});
 t.d.querySelector('#load-retry').click();t.requests.at(-1).resolve({devices:[]});await flush();
 check('incomplete inventory fails safely without enabling changes',()=>{assert.match(t.d.querySelector('#load-help').textContent,/incomplete/);assert(t.d.querySelector('#create').disabled);});
 t.dom.window.close();console.log(count+' storage loading checks passed');
})().catch(e=>{console.error(e);process.exit(1);});
