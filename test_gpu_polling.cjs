const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
class Deferred extends Promise{always(fn){return this.finally(fn);}}
let passed=0;function check(name,fn){fn();passed++;console.log('PASS '+name);}
async function flush(){for(let i=0;i<10;i++)await Promise.resolve();}
(async()=>{
 const dom=new JSDOM(fs.readFileSync('cockpit_gpu/index.html','utf8'),{runScripts:'outside-only'}),w=dom.window,requests=[],timers=new Map();let id=0,samples=0,renders=0;
 Object.defineProperty(w.document,'visibilityState',{value:'visible',configurable:true});
 w.setTimeout=(fn,ms)=>{timers.set(++id,{fn,ms});return id;};w.clearTimeout=id=>timers.delete(id);
 w.cockpit=new w.EventTarget();w.cockpit.hidden=true;
 w.cockpit.spawn=()=>{let resolve,reject;const p=new Deferred((a,b)=>{resolve=a;reject=b;});const r={resolve,reject,closed:false};p.close=()=>{r.closed=true;reject(new Error('closed'));};requests.push(r);return p;};
 w.eval(fs.readFileSync('cockpit_gpu/assets/js/custom.js','utf8'));
 w.render_gpus=()=>renders++;w.collect_rt_sample=()=>samples++;
 w.initialize_gpu_monitor();
 check('hidden tab does not start a GPU probe',()=>assert.equal(requests.length,0));
 w.cockpit.hidden=false;w.cockpit.dispatchEvent(new w.Event('visibilitychange'));
 check('visible tab starts one GPU query',()=>assert.equal(requests.length,1));
 w.load_gpus();w.load_gpus();
 check('slow queries cannot overlap',()=>assert.equal(requests.length,1));
 requests[0].resolve('[{"name":"fixture"}]');await flush();
 check('success renders once and schedules the next query after completion',()=>{assert.equal(renders,1);assert.equal(samples,1);assert.equal(requests.length,1);assert([...timers.values()].some(x=>x.ms===1000));});
 w.cockpit.hidden=true;w.cockpit.dispatchEvent(new w.Event('visibilitychange'));
 check('hiding clears the scheduled poll',()=>assert.equal(timers.size,0));
 w.cockpit.hidden=false;w.cockpit.dispatchEvent(new w.Event('visibilitychange'));w.cockpit.hidden=true;w.cockpit.dispatchEvent(new w.Event('visibilitychange'));await flush();
 check('hiding cancels an active read-only query without restarting it',()=>{assert(requests[1].closed);assert.equal(timers.size,0);assert.equal(renders,1);});
 w.cockpit.hidden=false;w.cockpit.dispatchEvent(new w.Event('visibilitychange'));const deadline=[...timers.values()].find(x=>x.ms===8000);deadline.fn();await flush();
 check('query timeout uses a bounded retry delay',()=>{assert(requests[2].closed);assert([...timers.values()].some(x=>x.ms===5000));});
 w.dispatchEvent(new w.Event('beforeunload'));
 check('unload removes pending work',()=>assert.equal(timers.size,0));dom.window.close();
 for(const path of ['cockpit_support/support.html','cockpit_gpu/index.html','cockpit_containers/active_containers.html','cockpit_vnc/index.html']){
  const document=new JSDOM(fs.readFileSync(path,'utf8')).window.document,scripts=[...document.querySelectorAll('script[src]')];
  check(path+' has no parser-blocking external script',()=>assert(scripts.every(s=>s.defer||s.type==='module')));
  const names=scripts.map(s=>s.getAttribute('src'));
  const depends=(a,b)=>{if(names.includes(b))assert(names.indexOf(a)<names.indexOf(b));};
  depends('../base1/cockpit.js','updates.js');depends('../base1/cockpit.js','secure-vnc.js');depends('js/jquery.js','assets/js/active_container.js');depends('node_modules/chart.js/dist/chart.umd.js','assets/js/custom.js');
 }
 console.log(passed+'/'+passed+' GPU polling and script-order checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
