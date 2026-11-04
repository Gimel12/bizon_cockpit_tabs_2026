/* One compact control and one preference for all BIZON pages in a Cockpit shell. */
(() => {
    'use strict';
    if (window.BizonTheme?.version === 2) return;
    const KEY = 'bizon.workspace.theme';
    const CONTROL = 'bizon-appearance-control';
    const CONTROLLER = '__bizonAppearanceV2';
    const source = document.currentScript.src;
    const normalize = value => value === 'light' ? 'light' : 'dark';
    const stored = () => { try { return normalize(localStorage.getItem(KEY)); } catch (_) { return 'dark'; } };
    const icons={sun:'<circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5"/>',moon:'<path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z"/>',cpu:'<rect x="5" y="5" width="14" height="14" rx="3"/><rect x="9" y="9" width="6" height="6" rx="1"/><path d="M9 2v3m6-3v3M9 19v3m6-3v3M2 9h3m-3 6h3m14-6h3m-3 6h3"/>',monitor:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',drive:'<rect x="3" y="4" width="18" height="16" rx="3"/><path d="M3 14h18m-5 3h2"/>',book:'<path d="M12 5c-3-2-6-2-10-1v15c4-1 7-1 10 1 3-2 6-2 10-1V4c-4-1-7-1-10 1v15"/>',layers:'<path d="m12 3 10 5-10 5L2 8Zm-10 9 10 5 10-5M2 16l10 5 10-5"/>',refresh:'<path d="M20 7v5h-5M4 17v-5h5M5.5 7a7.5 7.5 0 0 1 12-2L20 8M4 16l2.5 3a7.5 7.5 0 0 0 12-2"/>',chat:'<path d="M21 11a8 8 0 0 1-8 8H6l-4 3V7a4 4 0 0 1 4-4h11a4 4 0 0 1 4 4Z"/><path d="M7 8h10M7 12h7"/>'};
    function icon(name) {return '<svg class="bz-icon" aria-hidden="true" viewBox="0 0 24 24">'+(icons[name]||icons.cpu)+'</svg>';}
    function applyLocal(value) {
        const theme = normalize(value);
        const changed = document.documentElement.dataset.bzTheme !== theme;
        document.documentElement.dataset.bzTheme = theme;
        document.querySelectorAll('#' + CONTROL + ' button').forEach(button => {
            button.setAttribute('aria-pressed', String(button.dataset.theme === theme));
        });
        if (changed) window.dispatchEvent(new CustomEvent('bizon-theme-change', {detail: {theme}}));
    }
    function findToolbar(doc) {
        return doc.querySelector('#toggle-docs')?.closest('.pf-v5-c-toolbar__item')?.parentElement ||
            doc.querySelector('#toggle-docs')?.closest('.pf-v6-c-toolbar__item')?.parentElement ||
            doc.querySelector('.pf-v5-c-masthead .pf-v5-c-toolbar__content-section') ||
            doc.querySelector('.pf-v6-c-masthead .pf-v6-c-toolbar__content-section') ||
            doc.querySelector('.pf-v5-c-masthead [role="toolbar"]') ||
            doc.querySelector('.pf-v6-c-masthead [role="toolbar"]');
    }
    let owner = window;
    try {
        if (window.parent !== window && findToolbar(window.parent.document)) owner = window.parent;
    } catch (_) { /* Cross-origin embeddings retain a compact page-local control. */ }
    function createController(target) {
        const doc = target.document;
        let selected = stored();
        function sync(value) {
            selected = normalize(value);
            const local = target.BizonTheme;
            if (local?.version === 2) local.applyTheme(selected);
            else doc.documentElement.dataset.bzTheme = selected;
            // Only BIZON iframe documents are changed. Built-in Cockpit pages keep their own theme.
            for (const frame of doc.querySelectorAll('iframe')) {
                try {
                    if (frame.contentWindow.BizonTheme?.version === 2) frame.contentWindow.BizonTheme.applyTheme(selected);
                } catch (_) { /* Ignore unrelated cross-origin frames. */ }
            }
            doc.querySelectorAll('#' + CONTROL + ' button').forEach(button => {
                button.setAttribute('aria-pressed', String(button.dataset.theme === selected));
            });
        }
        function set(value) {
            const theme = normalize(value);
            try { target.localStorage.setItem(KEY, theme); } catch (_) {}
            sync(theme);
        }
        function mount() {
            if (doc.getElementById(CONTROL)) return;
            const toolbar = target !== window ? findToolbar(doc) : null;
            if (target !== window && !toolbar) return;
            const group = doc.createElement('div');
            group.id = CONTROL;
            group.className = 'bz-theme-switch' + (toolbar ? ' bz-theme-masthead' : ' bz-theme-floating');
            group.setAttribute('role', 'group');
            group.setAttribute('aria-label', 'Appearance');
            group.innerHTML = '<button type="button" data-theme="light" aria-label="Light mode" title="Light mode">' + icon('sun') + '<span>Light</span></button><button type="button" data-theme="dark" aria-label="Dark mode" title="Dark mode">' + icon('moon') + '<span>Dark</span></button>';
            group.addEventListener('click', event => {
                const button = event.target.closest('button[data-theme]');
                if (button && group.contains(button)) set(button.dataset.theme);
            });
            if (toolbar) {
                const help = doc.querySelector('#toggle-docs')?.closest('.pf-v5-c-toolbar__item, .pf-v6-c-toolbar__item');
                toolbar.insertBefore(group, help?.parentElement === toolbar ? help : null);
            }
            else doc.body.append(group);
            sync(selected);
        }
        target.addEventListener('storage', event => {
            if (event.key === KEY || event.key === null) sync(event.newValue);
        });
        return {getTheme: () => selected, setTheme: set, mount};
    }
    if (!owner[CONTROLLER]) owner[CONTROLLER] = createController(owner);
    const controller = owner[CONTROLLER];
    window.BizonTheme = {version: 2, getTheme: () => normalize(document.documentElement.dataset.bzTheme), setTheme: value => controller.setTheme(value), applyTheme: applyLocal, icon};
    applyLocal(controller.getTheme());
    function mount() {
        // This module never edits navigation links or listens to document mutations.
        if (owner !== window) {
            const doc = owner.document;
            if (!doc.getElementById('bizon-shell-theme')) {
                const link = doc.createElement('link');
                link.id = 'bizon-shell-theme';link.rel = 'stylesheet';link.href = new URL('shell.css', source).href;
                doc.head.append(link);
            }
        }
        controller.mount();
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount, {once: true});
    else mount();
})();
