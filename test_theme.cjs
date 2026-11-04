/* Shared theme regression tests. Run with jsdom@26 in NODE_PATH. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const {JSDOM}=require('jsdom');
const root=__dirname;
const themePath=path.join(root,'cockpit_support/theme/bizon-theme.js');
const source=fs.readFileSync(themePath,'utf8');
const css=fs.readFileSync(path.join(root,'cockpit_support/theme/bizon-theme.css'),'utf8');
const KEY='bizon.workspace.theme';
const pages=[
 'cockpit_bizon_ai/index.html','cockpit_gpu/index.html',
 'cockpit_jupyter/index.html','cockpit_jupyter/active_containers.html',
 'cockpit_containers/active_containers.html','cockpit_vnc/index.html',
 'cockpit_support/drives.html','cockpit_support/raid.html',
 'cockpit_support/support.html','cockpit_tutorials/index.html'
];
let passed=0;
function check(name,fn){fn();passed++;console.log('PASS '+name);}
function setup({stored,blocked=false}={}){
 const dom=new JSDOM('<!doctype html><html><head></head><body><main id="content">Workspace</main></body></html>',{url:'https://workstation.test/cockpit/cockpit_support/drives.html',runScripts:'outside-only'});
 const w=dom.window;
 if(stored!==undefined)w.localStorage.setItem(KEY,stored);
 if(blocked)Object.defineProperty(w,'localStorage',{get(){throw new w.DOMException('Storage unavailable','SecurityError');}});
 const script=w.document.createElement('script');script.src='https://workstation.test/cockpit/cockpit_support/theme/bizon-theme.js';
 Object.defineProperty(w.document,'currentScript',{configurable:true,get:()=>script});
 w.eval(source);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));
 const buttons=()=>[...w.document.querySelectorAll('.bz-theme-switch button')];
 const click=value=>w.document.querySelector('[data-theme="'+value+'"]').click();
 return{dom,w,buttons,click};
}
check('shared theme is valid JavaScript',()=>new vm.Script(source,{filename:themePath}));
for(const page of pages){
 check(page+' loads shared theme assets once',()=>{
  const dom=new JSDOM(fs.readFileSync(path.join(root,page),'utf8'));
  const doc=dom.window.document;
  const styles=[...doc.querySelectorAll('link[rel="stylesheet"]')].filter(x=>x.getAttribute('href').endsWith('theme/bizon-theme.css'));
  const scripts=[...doc.querySelectorAll('script[src]')].filter(x=>x.getAttribute('src').endsWith('theme/bizon-theme.js'));
  assert.equal(styles.length,1,'one shared stylesheet required');assert.equal(scripts.length,1,'one shared script required');
  for(const el of [...styles,...scripts])assert(fs.existsSync(path.resolve(root,path.dirname(page),el.getAttribute('src')||el.getAttribute('href'))),'shared asset path must resolve');
  dom.window.close();
 });
}
check('inline scripts across the ten entrypoints have valid syntax',()=>{
 for(const page of pages){
  const dom=new JSDOM(fs.readFileSync(path.join(root,page),'utf8'));
  for(const script of dom.window.document.querySelectorAll('script:not([src])')){
   if(script.type==='application/json' || script.type==='application/ld+json')continue;
   new vm.Script(script.textContent,{filename:page+' inline script'});
  }
  dom.window.close();
 }
});
const t=setup();
check('new users default to dark',()=>assert.equal(t.w.document.documentElement.dataset.bzTheme,'dark'));
check('standalone view has only a compact named appearance control',()=>{
 const group=t.w.document.querySelector('.bz-theme-switch');assert.equal(group.getAttribute('role'),'group');assert.equal(group.getAttribute('aria-label'),'Appearance');
 assert(group.classList.contains('bz-theme-floating'));
 assert.equal(t.w.document.querySelectorAll('.bz-topbar,.bz-identity,.bz-product').length,0);
 const btns=t.buttons();assert.equal(btns.length,2);assert.deepEqual(btns.map(b=>b.getAttribute('aria-label')),['Light mode','Dark mode']);assert.deepEqual(btns.map(b=>b.getAttribute('aria-pressed')),['false','true']);
 assert(btns.every(b=>b.type==='button'));
});
let last,events=0;
t.w.addEventListener('bizon-theme-change',e=>{last=e.detail.theme;events++;});
t.click('light');
check('light selection applies, persists and notifies once',()=>{assert.equal(t.w.document.documentElement.dataset.bzTheme,'light');assert.equal(t.w.localStorage.getItem(KEY),'light');assert.equal(t.w.BizonTheme.getTheme(),'light');assert.equal(last,'light');assert.equal(events,1);});
t.click('light');
check('reselecting current theme does not trigger chart redraw events',()=>assert.equal(events,1));
const restored=setup({stored:t.w.localStorage.getItem(KEY)});
check('explicit saved light preference is preserved',()=>assert.equal(restored.w.document.documentElement.dataset.bzTheme,'light'));
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:KEY,newValue:'dark'}));
check('other browser tab theme changes synchronize',()=>{assert.equal(t.w.BizonTheme.getTheme(),'dark');assert.equal(last,'dark');assert.deepEqual(t.buttons().map(b=>b.getAttribute('aria-pressed')),['false','true']);});
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:'unrelated.preference',newValue:'light'}));
check('unrelated storage events do not change theme',()=>assert.equal(t.w.BizonTheme.getTheme(),'dark'));
t.click('light');t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:KEY,newValue:null}));
check('removing preference returns to dark',()=>assert.equal(t.w.BizonTheme.getTheme(),'dark'));
t.w.eval(source);t.w.document.dispatchEvent(new t.w.Event('DOMContentLoaded'));
check('duplicate initialization creates no extra controls',()=>{assert.equal(t.w.document.querySelectorAll('#bizon-appearance-control').length,1);assert.equal(t.buttons().length,2);});
const blocked=setup({blocked:true});blocked.click('light');
check('blocked storage still supports selection',()=>assert.equal(blocked.w.BizonTheme.getTheme(),'light'));
blocked.click('dark');
check('blocked storage supports switching back',()=>assert.equal(blocked.w.BizonTheme.getTheme(),'dark'));
const invalid=setup({stored:'unexpected'});
check('invalid saved preference defaults to dark',()=>assert.equal(invalid.w.BizonTheme.getTheme(),'dark'));
const shell=new JSDOM('<!doctype html><html><head></head><body><div id="host-apps"><a href="/cockpit_vnc">Remote Desktop</a></div><header class="pf-v5-c-masthead"><div class="pf-v5-c-toolbar__content-section"><div id="admin">Administrative access</div><div class="pf-v5-c-toolbar__item" id="help-item"><button id="toggle-docs">Help</button></div></div></header><iframe></iframe><iframe></iframe></body></html>',{url:'https://workstation.test/',runScripts:'outside-only'});
let storageListeners=0;const addListener=shell.window.addEventListener.bind(shell.window);shell.window.addEventListener=(name,...args)=>{if(name==='storage')storageListeners++;addListener(name,...args);};
function loadFrame(frame) {
 const w=frame.contentWindow;
 const script=w.document.createElement('script');script.src='https://workstation.test/cockpit/cockpit_support/theme/bizon-theme.js';
 Object.defineProperty(w.document,'currentScript',{configurable:true,get:()=>script});
 w.eval(source);w.document.dispatchEvent(new w.Event('DOMContentLoaded'));return w;
}
const frames=[...shell.window.document.querySelectorAll('iframe')];const one=loadFrame(frames[0]),two=loadFrame(frames[1]);
check('two iframe pages share one masthead selector beside Help',()=>{const doc=shell.window.document;assert.equal(doc.querySelectorAll('#bizon-appearance-control').length,1);assert.equal(doc.querySelector('#bizon-appearance-control').nextElementSibling.id,'help-item');assert.equal(doc.querySelectorAll('#bizon-shell-theme').length,1);assert.equal(one.document.querySelectorAll('.bz-theme-switch').length,0);assert.equal(two.document.querySelectorAll('.bz-theme-switch').length,0);});
let oneEvents=0,twoEvents=0;one.addEventListener('bizon-theme-change',()=>oneEvents++);two.addEventListener('bizon-theme-change',()=>twoEvents++);
shell.window.document.querySelector('[data-theme="light"]').click();
check('masthead choice immediately updates every open BIZON frame',()=>{assert.equal(one.BizonTheme.getTheme(),'light');assert.equal(two.BizonTheme.getTheme(),'light');assert.equal(shell.window.document.documentElement.dataset.bzTheme,'light');assert.equal(oneEvents,1);assert.equal(twoEvents,1);});
one.BizonTheme.setTheme('dark');
check('theme API from one frame immediately updates sibling and shell',()=>{assert.equal(two.BizonTheme.getTheme(),'dark');assert.equal(shell.window.document.documentElement.dataset.bzTheme,'dark');});
one.eval(source);two.eval(source);
check('duplicate loads retain one storage listener for the entire shell',()=>assert.equal(storageListeners,1));
check('theme applies do not mutate navigation links or add icons',()=>{assert.equal(shell.window.document.querySelector('#host-apps').innerHTML,'<a href="/cockpit_vnc">Remote Desktop</a>');});
check('theme implementation has no observer or polling loops',()=>{assert(!/MutationObserver|setInterval|setTimeout/.test(source));});
const next=shell.window.document.createElement('iframe');shell.window.document.body.append(next);const three=loadFrame(next);
check('newly opened frames inherit the current shell choice',()=>assert.equal(three.BizonTheme.getTheme(),'dark'));
shell.window.close();
check('both appearances define every shared semantic palette token',()=>{
 const styleDom=new JSDOM('<style>'+css+'</style>');
 const rules=[...styleDom.window.document.styleSheets[0].cssRules];
 const keys=['--bz-bg','--bz-surface','--bz-surface-alt','--bz-text','--bz-muted','--bz-border','--bz-primary','--bz-on-primary','--bz-selected','--bz-shadow','--bz-success','--bz-danger','--bz-warning','--bz-canvas-glow','--bz-panel-inset','--bz-radius'];
 for(const appearance of ['light','dark']){
  const rule=rules.find(r=>r.selectorText?.includes('[data-bz-theme="'+appearance+'"]'));
  assert(rule,'missing appearance palette '+appearance);
  assert.equal(rule.style.getPropertyValue('color-scheme'),appearance);
  for(const key of keys)assert(rule.style.getPropertyValue(key),'missing '+appearance+' '+key);
 }
 styleDom.window.close();
});
check('AI and notebook dependencies defer parsing while keeping dependency order',()=>{
 for(const page of ['cockpit_bizon_ai/index.html','cockpit_jupyter/index.html','cockpit_jupyter/active_containers.html']){
  const dom=new JSDOM(fs.readFileSync(path.join(root,page),'utf8'));
  const scripts=[...dom.window.document.querySelectorAll('script[src]')];
  assert(scripts.every(script=>script.defer),'external scripts should not block page parsing');
  assert(scripts.every(script=>!script.async),'dependencies must execute in document order');
  assert.equal(scripts[0].getAttribute('src'),'../base1/cockpit.js');
  const urls=scripts.map(script=>script.getAttribute('src'));
  const application=page.startsWith('cockpit_bizon_ai')?'chat.js':page.includes('active_containers')?'assets/js/active_container.js':'assets/js/custom.js';
  assert(urls.indexOf(application)>urls.indexOf('../cockpit_support/theme/bizon-theme.js'));
  if(page.startsWith('cockpit_jupyter'))assert(urls.indexOf('js/jquery.js')<urls.indexOf(application));
  const csp=JSON.parse(fs.readFileSync(path.join(root,page.split('/')[0],'manifest.json'),'utf8'))['content-security-policy'];
  for(const inline of dom.window.document.querySelectorAll('script:not([src])')){
   const hash=require('node:crypto').createHash('sha256').update(inline.textContent).digest('base64');
   assert(csp.includes('sha256-'+hash),'inline compatibility script retains authorized CSP hash');
  }
  dom.window.close();
 }
});
check('all custom navigation entries have CSS-only outline icon masks',()=>{
 const shellCss=fs.readFileSync(path.join(root,'cockpit_support/theme/shell.css'),'utf8');
 for(const entry of ['cockpit_bizon_ai','cockpit_gpu','cockpit_vnc','cockpit_containers','cockpit_jupyter','cockpit_tutorials','cockpit_support/drives','cockpit_support/raid','cockpit_support/support']){
  assert(shellCss.includes('a[href*="'+entry+'"]::before{-webkit-mask:'));
 }
 const masks=[...shellCss.matchAll(/data:image\/svg\+xml,([^"\)]+)/g)];
 assert.equal(masks.length,18);
 for(const mask of masks){const svg=decodeURIComponent(mask[1]);assert(svg.startsWith('<svg '));assert(svg.endsWith('</svg>'));}
});
check('shared theme resources and shell stylesheet exist',()=>{
 for(const file of ['shell.css','bizon-logo.svg'])assert(fs.statSync(path.join(root,'cockpit_support/theme',file)).size>0);
});
for(const instance of [t,restored,blocked,invalid])instance.dom.window.close();
console.log(`${passed}/${passed} shared theme checks passed`);
