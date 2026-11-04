const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('cockpit_vnc/noVNC/core/util/browser.js','utf8');
const start=source.indexOf('async function _checkWebCodecsH264DecodeSupport()');
const end=source.indexOf('// Advertise H.264',start);
let passed=0;
function check(name,fn){fn();passed++;console.log('PASS '+name);}
async function tick(){for(let i=0;i<10;i++)await Promise.resolve();}
function setup(mode){
 let options,decoderCount=0,closed=0,framesClosed=0,lateConfig,lateFlush,timerId=0;const timers=new Map();
 class VideoDecoder{
  static isConfigSupported(){
   if(mode==='config-reject')return Promise.reject(new Error('unsupported'));
   if(mode==='config-stall')return new Promise(resolve=>{lateConfig=resolve;});
   return Promise.resolve({supported:mode!=='unsupported'});
  }
  constructor(o){options=o;this.state='unconfigured';decoderCount++;}
  configure(){if(mode==='configure-throw')throw new Error('failed');this.state='configured';}
  decode(){}
  flush(){
   if(mode==='flush-reject')return Promise.reject(new Error('failed'));
   if(mode==='flush-stall')return new Promise((resolve,reject)=>{lateFlush={resolve,reject};});
   if(mode!=='no-frame')options.output({close(){framesClosed++;}});
   if(mode==='decode-error')options.error(new Error('decoder error'));
   return Promise.resolve();
  }
  close(){assert.notEqual(this.state,'closed');this.state='closed';closed++;}
 }
 class EncodedVideoChunk{}
 const window=mode==='missing'?{}:{VideoDecoder,EncodedVideoChunk};
 const context=vm.createContext({window,VideoDecoder,EncodedVideoChunk,Uint8Array,Base64:{decode:()=>[]},setTimeout(fn,ms){assert.equal(ms,1200);timers.set(++timerId,fn);return timerId;},clearTimeout(id){timers.delete(id);}});
 const run=vm.runInContext(source.slice(start,end)+'\n_checkWebCodecsH264DecodeSupport',context);
 return {run,timers,get closed(){return closed;},get decoderCount(){return decoderCount;},get framesClosed(){return framesClosed;},timeout(){[...timers.values()][0]();},lateConfig(){lateConfig({supported:true});},lateFlush(){options.output({close(){framesClosed++;}});lateFlush.reject(new Error('late close'));}};
}
(async()=>{
 for(const mode of ['missing','unsupported','config-reject','configure-throw','flush-reject','no-frame','decode-error','success']){
  const t=setup(mode),result=await t.run();
  check(mode+' resolves safely and releases resources',()=>{assert.equal(result,mode==='success');assert.equal(t.closed,t.decoderCount);assert.equal(t.timers.size,0);if(mode==='success')assert.equal(t.framesClosed,1);});
 }
 let t=setup('config-stall'),p=t.run();await tick();t.timeout();assert.equal(await p,false);t.lateConfig();await tick();
 check('stalled capability check times out without allocating a late decoder',()=>{assert.equal(t.decoderCount,0);assert.equal(t.timers.size,0);});
 t=setup('flush-stall');p=t.run();await tick();t.timeout();assert.equal(await p,false);t.lateFlush();await tick();
 check('stalled flush closes its decoder and releases a late frame',()=>{assert.equal(t.decoderCount,1);assert.equal(t.closed,1);assert.equal(t.framesClosed,1);assert.equal(t.timers.size,0);});
 check('optional codec probing does not block module evaluation',()=>{assert(!/supportsWebCodecsH264Decode\s*=\s*await/.test(source));assert(source.includes('_checkWebCodecsH264DecodeSupport().then'));});
 const html=fs.readFileSync('cockpit_vnc/index.html','utf8');
 check('theme precedes VNC module and Connect waits for handlers',()=>{assert(html.indexOf('bizon-theme.js')<html.indexOf('secure-vnc.js'));assert(/<button id="connect"[^>]+disabled/.test(html));});
 console.log(`${passed}/${passed} VNC codec startup checks passed`);
})().catch(error=>{console.error(error);process.exitCode=1;});
