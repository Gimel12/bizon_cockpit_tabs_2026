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
check('new users get the reference light appearance',()=>assert.equal(t.w.document.documentElement.dataset.bzTheme,'light'));
check('theme switch is named and exposes selected state',()=>{
 const group=t.w.document.querySelector('.bz-theme-switch');assert.equal(group.getAttribute('role'),'group');assert.equal(group.getAttribute('aria-label'),'Appearance');
 const btns=t.buttons();assert.equal(btns.length,2);assert.deepEqual(btns.map(b=>b.getAttribute('aria-label')),['Light mode','Dark mode']);assert.deepEqual(btns.map(b=>b.getAttribute('aria-pressed')),['true','false']);
 assert(btns.every(b=>b.type==='button'),'controls must not submit forms');
});
let last;
t.w.addEventListener('bizon-theme-change',e=>last=e.detail.theme);
t.click('dark');
check('dark button applies, persists, and broadcasts the choice',()=>{assert.equal(t.w.document.documentElement.dataset.bzTheme,'dark');assert.equal(t.w.localStorage.getItem(KEY),'dark');assert.equal(t.w.BizonTheme.getTheme(),'dark');assert.equal(last,'dark');assert.deepEqual(t.buttons().map(b=>b.getAttribute('aria-pressed')),['false','true']);});
const restored=setup({stored:t.w.localStorage.getItem(KEY)});
check('next tab or reload restores the stored theme',()=>assert.equal(restored.w.document.documentElement.dataset.bzTheme,'dark'));
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:KEY,newValue:'light'}));
check('theme changes from another tab synchronize the current page',()=>{assert.equal(t.w.document.documentElement.dataset.bzTheme,'light');assert.equal(last,'light');assert.deepEqual(t.buttons().map(b=>b.getAttribute('aria-pressed')),['true','false']);});
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:'unrelated.preference',newValue:'dark'}));
check('unrelated storage events leave appearance unchanged',()=>assert.equal(t.w.BizonTheme.getTheme(),'light'));
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:KEY,newValue:'dark'}));
t.w.dispatchEvent(new t.w.StorageEvent('storage',{key:KEY,newValue:null}));
check('removing the theme preference returns to light',()=>assert.equal(t.w.BizonTheme.getTheme(),'light'));
t.w.eval(source);t.w.document.dispatchEvent(new t.w.Event('DOMContentLoaded'));
check('duplicate initialization never duplicates the header or selectors',()=>{assert.equal(t.w.document.querySelectorAll('.bz-topbar').length,1);assert.equal(t.buttons().length,2);assert.equal(t.w.document.querySelector('body').firstElementChild.className,'bz-topbar');});
const blocked=setup({blocked:true});
blocked.click('dark');
check('blocked localStorage does not prevent switching themes',()=>{assert.equal(blocked.w.document.documentElement.dataset.bzTheme,'dark');assert.deepEqual(blocked.buttons().map(b=>b.getAttribute('aria-pressed')),['false','true']);});
blocked.click('light');
check('localStorage fallback supports switching back',()=>assert.equal(blocked.w.BizonTheme.getTheme(),'light'));
const invalid=setup({stored:'unexpected'});
check('unrecognized saved preferences safely fall back to light',()=>assert.equal(invalid.w.BizonTheme.getTheme(),'light'));
check('both appearances define every shared semantic palette token',()=>{
 const styleDom=new JSDOM('<style>'+css+'</style>');
 const rules=[...styleDom.window.document.styleSheets[0].cssRules];
 const keys=['--bz-bg','--bz-surface','--bz-surface-alt','--bz-text','--bz-muted','--bz-border','--bz-primary','--bz-on-primary','--bz-selected','--bz-shadow','--bz-success','--bz-danger','--bz-warning','--bz-canvas-glow','--bz-panel-inset'];
 for(const appearance of ['light','dark']){
  const rule=rules.find(r=>r.selectorText?.includes('[data-bz-theme="'+appearance+'"]'));
  assert(rule,'missing appearance palette '+appearance);
  assert.equal(rule.style.getPropertyValue('color-scheme'),appearance);
  for(const key of keys)assert(rule.style.getPropertyValue(key),'missing '+appearance+' '+key);
 }
 styleDom.window.close();
});
check('shared theme resources and shell stylesheet exist',()=>{
 for(const file of ['shell.css','bizon-logo.svg'])assert(fs.statSync(path.join(root,'cockpit_support/theme',file)).size>0);
});
for(const instance of [t,restored,blocked,invalid])instance.dom.window.close();
console.log(`${passed}/${passed} shared theme checks passed`);
