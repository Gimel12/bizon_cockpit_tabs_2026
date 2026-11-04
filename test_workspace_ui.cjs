const {JSDOM}=require('jsdom');
const fs=require('fs'),assert=require('assert/strict');
const root=__dirname+'/';let count=0;
function ok(name,fn){fn();count++;console.log('PASS '+name)}
const dom=new JSDOM(fs.readFileSync(root+'cockpit_jupyter/index.html','utf8'),{runScripts:'outside-only'});
const w=dom.window;w.setInterval=()=>0;w.console.log=()=>{};w.Image=w.Image;
w.eval(fs.readFileSync(root+'cockpit_jupyter/js/jquery.js','utf8'));
const calls=[];w.cockpit={jump:p=>calls.push(p),spawn:a=>{calls.push(a);return {then(){return this},catch(){return this}}}};
w.eval(fs.readFileSync(root+'cockpit_jupyter/assets/js/navigation.js','utf8'));
w.eval(fs.readFileSync(root+'cockpit_jupyter/assets/js/custom.js','utf8'));
w.process_images('[]');w.writeAvailableMachines();
ok('No images shows a helpful empty state and disables launch',()=>{assert.match(w.document.getElementById('containers-grid').textContent,/No notebook images/);assert(w.document.getElementById('run_button').disabled)});
w.document.querySelector('.notebook-empty a').click();ok('Empty state navigates to Cockpit Docker Images',()=>assert.equal(calls.pop(),'/cockpit_containers/active_containers'));
w.check_container_info();ok('Missing selections do not invoke backend',()=>assert.equal(calls.length,0));
w.process_images(JSON.stringify([{title:'Notebook <img src=x>',repository:'pytorch',id:'sha256:test'}]));
ok('Image labels are text, not executable markup',()=>{assert.match(w.document.querySelector('.custom-container').textContent,/<img/);assert.equal(w.document.querySelectorAll('.custom-container img').length,1)});
w.document.querySelector('.custom-container').dispatchEvent(new w.KeyboardEvent('keydown',{key:'Enter',bubbles:true}));ok('Image keyboard selection is announced',()=>{assert.equal(w.document.querySelector('.custom-container').getAttribute('aria-pressed'),'true');assert(w.document.getElementById('run_button').disabled)});
w.document.querySelector('.custom-machine').dispatchEvent(new w.KeyboardEvent('keydown',{key:' ',bubbles:true}));ok('GPU keyboard selection enables launch with valid image',()=>assert.equal(w.document.getElementById('run_button').disabled,false));
w.document.getElementById('run_button').click();ok('Valid selected configuration reaches backend once',()=>assert.equal(calls.length,1));
w.showImageLoadError();ok('Image loading error stays visible and blocks launch',()=>{assert.match(w.document.querySelector('[role=alert]').textContent,/could not be loaded/);assert(w.document.getElementById('run_button').disabled)});
dom.window.close();
const active=new JSDOM(fs.readFileSync(root+'cockpit_jupyter/active_containers.html','utf8'),{runScripts:'outside-only'});active.window.setInterval=()=>0;active.window.eval(fs.readFileSync(root+'cockpit_jupyter/assets/js/active_container.js','utf8'));active.window.process_containers('[]');ok('Empty running list explains how to begin',()=>{assert.match(active.window.document.querySelector('table').textContent,/No notebooks are running/);assert(active.window.document.getElementById('stop-all').hidden)});active.window.close();
// AI lifecycle, authority, streaming and XSS checks live in test_ai_ui.cjs.
// These workspace checks cover the current keyboard-native starter prompts.
const ai=new JSDOM(fs.readFileSync(root+'cockpit_bizon_ai/index.html','utf8'),{runScripts:'outside-only'});
const a=ai.window,aiCalls=[];
a.cockpit={
 spawn(args){aiCalls.push(args);return {then(){return this},input(){return this},close(){}}},
 permission(){return {addEventListener(){},close(){}}}
};
a.eval(fs.readFileSync(root+'cockpit_bizon_ai/chat.js','utf8'));
a.document.dispatchEvent(new a.Event('DOMContentLoaded'));
const prompts=[...a.document.querySelectorAll('.suggestions button[data-prompt]')];
ok('AI starter prompts use native buttons and fixed outline icons',()=>{
 assert.equal(prompts.length,3);
 assert(prompts.every(button=>button.querySelector('svg')));
 assert.equal(a.document.querySelectorAll('.suggestions script,.suggestions img').length,0);
});
const promptText=prompts[0].dataset.prompt;
prompts[0].focus();prompts[0].click();
ok('AI starter prompt fills and focuses the composer without running commands',()=>{
 assert.equal(a.document.getElementById('chat-input').value,promptText);
 assert.equal(a.document.activeElement,a.document.getElementById('chat-input'));
 assert(!aiCalls.some(args=>args.at(-1)==='chat'||args.at(-1).endsWith('executor.py')));
});
a.dispatchEvent(new a.Event('beforeunload'));ai.window.close();
console.log(count+' checks passed');
