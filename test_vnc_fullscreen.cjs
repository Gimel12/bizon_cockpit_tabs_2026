const fs=require('node:fs'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const source=fs.readFileSync('cockpit_vnc/fullscreen.js','utf8');let passed=0;
const check=(name,fn)=>{fn();passed++;console.log('PASS '+name);};
async function flush(){for(let i=0;i<8;i++)await Promise.resolve();}
function setup(embedded=true){
 const dom=new JSDOM('<body><main id="desktop-view"></main><button id="fullscreen">Full screen</button><div id="notice" hidden></div></body>',{runScripts:'outside-only'}),w=dom.window,doc=w.document;
 const hostDoc=new w.EventTarget();hostDoc.fullscreenElement=null;
 const calls={host:0,view:0,hostExit:0,viewExit:0};let rejectHost=false,rejectView=false;
 const host={ownerDocument:hostDoc,async requestFullscreen(){calls.host++;if(rejectHost)throw new Error('not granted');hostDoc.fullscreenElement=host;hostDoc.dispatchEvent(new w.Event('fullscreenchange'));}};
 hostDoc.exitFullscreen=async()=>{calls.hostExit++;hostDoc.fullscreenElement=null;hostDoc.dispatchEvent(new w.Event('fullscreenchange'));};
 Object.defineProperty(w,'frameElement',{get:()=>embedded?host:null});
 Object.defineProperty(doc,'fullscreenEnabled',{value:true});
 Object.defineProperty(doc,'fullscreenElement',{value:null,writable:true});
 doc.getElementById('desktop-view').requestFullscreen=async()=>{calls.view++;if(rejectView)throw new Error('not granted');doc.fullscreenElement=doc.getElementById('desktop-view');doc.dispatchEvent(new w.Event('fullscreenchange'));};
 doc.exitFullscreen=async()=>{calls.viewExit++;doc.fullscreenElement=null;doc.dispatchEvent(new w.Event('fullscreenchange'));};
 w.console.warn=()=>{};w.eval(source);
 return{w,doc,dom,calls,host,hostDoc,el:id=>doc.getElementById(id),rejectHost(v){rejectHost=v;},rejectView(v){rejectView=v;},click(){doc.getElementById('fullscreen').click();}};
}
(async()=>{
 let t=setup();t.click();await flush();
 check('Cockpit frame fullscreen is preferred even when child fullscreen is enabled',()=>{assert.equal(t.calls.host,1);assert.equal(t.calls.view,0);assert(t.doc.body.classList.contains('fullscreen'));assert.equal(t.el('fullscreen').getAttribute('aria-pressed'),'true');});
 t.click();await flush();
 check('exit uses the active shell document and restores state',()=>{assert.equal(t.calls.hostExit,1);assert(!t.doc.body.classList.contains('fullscreen'));assert.equal(t.el('fullscreen').textContent,'Full screen');});
 t.rejectHost(true);t.click();await flush();
 check('denied request leaves a clear message without false fullscreen state',()=>{assert(!t.el('notice').hidden);assert(!t.doc.body.classList.contains('fullscreen'));assert.equal(t.calls.view,0);});
 t.rejectHost(false);t.click();await flush();
 check('successful retry removes stale error notice',()=>{assert(t.el('notice').hidden);assert.equal(t.el('notice').textContent,'');assert(t.doc.body.classList.contains('fullscreen'));});
 t.w.dispatchEvent(new t.w.Event('desktop-ended'));await flush();
 check('ending desktop exits shell fullscreen',()=>{assert.equal(t.calls.hostExit,2);assert(!t.doc.body.classList.contains('fullscreen'));});t.dom.window.close();
 t=setup(false);t.click();await flush();
 check('standalone page requests fullscreen on its desktop view',()=>{assert.equal(t.calls.view,1);assert.equal(t.calls.host,0);assert(t.doc.body.classList.contains('fullscreen'));});
 t.click();await flush();check('standalone exit uses own document',()=>assert.equal(t.calls.viewExit,1));
 t.rejectView(true);t.click();await flush();check('standalone rejection also restores usable controls',()=>{assert(!t.el('notice').hidden);assert.equal(t.el('fullscreen').getAttribute('aria-pressed'),'false');});
 t.dom.window.close();console.log(passed+'/'+passed+' VNC fullscreen checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
