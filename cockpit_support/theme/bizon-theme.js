/* One preference for every BIZON tab; no request, credential or service changes. */
(() => {
    'use strict';
    const KEY='bizon.workspace.theme';
    const source=document.currentScript.src;
    let selected='light';
    try { if(localStorage.getItem(KEY)==='dark') selected='dark'; } catch (_) {}
    const icons={sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',moon:'<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>',cpu:'<rect x="5" y="5" width="14" height="14" rx="3"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/>',monitor:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',drive:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 14h18m-5 3h2"/>',book:'<path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1v15"/>',layers:'<path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',refresh:'<path d="M20 7v5h-5M4 17v-5h5M5.5 7a7.5 7.5 0 0 1 12-2L20 8M4 16l2.5 3a7.5 7.5 0 0 0 12-2"/>',chat:'<path d="M21 11a8 8 0 0 1-8 8H6l-4 3V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4Z"/><path d="M7 8h10M7 12h7"/>'};
    function icon(name) {return '<svg class="bz-icon" aria-hidden="true" viewBox="0 0 24 24">'+(icons[name]||icons.cpu)+'</svg>';}
    function hostTheme(){
        try {
            if(window.parent===window)return;
            const doc=window.parent.document;
            doc.documentElement.dataset.bzTheme=selected;
            if(!doc.getElementById('bizon-shell-theme')){
                const link=doc.createElement('link');link.id='bizon-shell-theme';link.rel='stylesheet';link.href=new URL('shell.css',source).href;doc.head.appendChild(link);
            }
            const mapping={'cockpit_bizon_ai':'chat','cockpit_gpu':'cpu','cockpit_vnc':'monitor','cockpit_containers':'layers','cockpit_jupyter':'book','cockpit_tutorials':'book','cockpit_support/drives':'drive','cockpit_support/raid':'layers','cockpit_support/support':'refresh'};
            doc.querySelectorAll('#host-apps a').forEach(a=>{
                if(a.querySelector('.bz-nav-icon'))return;
                const path=a.getAttribute('href')||'';
                const name=Object.keys(mapping).find(k=>path.includes(k));if(!name)return;
                const wrap=doc.createElement('span');wrap.className='bz-nav-icon';wrap.innerHTML=icon(mapping[name]);a.prepend(wrap);
            });
        } catch(_) { /* Standalone / cross-origin embedding keeps the page-local theme. */ }
    }
    function apply(value){
        selected=value==='dark'?'dark':'light';
        document.documentElement.dataset.bzTheme=selected;
        document.querySelectorAll('.bz-theme-switch button').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.theme===selected)));
        hostTheme();
        window.dispatchEvent(new CustomEvent('bizon-theme-change',{detail:{theme:selected}}));
    }
    function set(value){try {localStorage.setItem(KEY,value);}catch(_){} apply(value);}
    window.BizonTheme={getTheme:()=>selected,setTheme:set,icon};
    document.documentElement.dataset.bzTheme=selected;
    function mount(){
        if(document.querySelector('.bz-topbar'))return;
        const header=document.createElement('header');header.className='bz-topbar';
        header.innerHTML='<div class="bz-identity"><span class="bz-logo"><img alt="BIZON" src="'+new URL('bizon-logo.svg',source).href+'"></span><div class="bz-product">Workstation<span>Your tools, together</span></div></div><div class="bz-theme-switch" role="group" aria-label="Appearance"><button type="button" data-theme="light" aria-label="Light mode">'+icon('sun')+'Light</button><button type="button" data-theme="dark" aria-label="Dark mode">'+icon('moon')+'Dark</button></div>';
        header.querySelectorAll('button').forEach(b=>b.addEventListener('click',()=>set(b.dataset.theme)));
        document.body.prepend(header);apply(selected);
    }
    window.addEventListener('storage',e=>{if(e.key===KEY)apply(e.newValue);});
    if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',mount,{once:true});else mount();
})();
