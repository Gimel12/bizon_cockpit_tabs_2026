const view = document.getElementById('desktop-view');
const button = document.getElementById('fullscreen');
const notice = document.getElementById('notice');
// Cockpit hosts this page in a same-origin iframe. Request fullscreen on that
// frame in the shell document: the browser can then hide the shell completely
// without depending on fullscreen delegation into the nested document.
let hostFrame = null;
try { hostFrame = window.frameElement; } catch (_) { /* separate-origin embed */ }
const hostDocument = hostFrame?.ownerDocument;
function activeDocument() {
    if (document.fullscreenElement) return document;
    if (hostDocument?.fullscreenElement === hostFrame) return hostDocument;
    return null;
}
function syncFullscreen() {
    const active = Boolean(activeDocument());
    document.body.classList.toggle('fullscreen', active);
    button.textContent = active ? 'Exit full screen' : 'Full screen';
    button.setAttribute('aria-pressed', String(active));
    button.title = active ? 'Exit full screen (Esc)' : 'Use your entire display. Press Esc to exit.';
}
let fullscreenPending = false;
button.addEventListener('click', async () => {
    if (fullscreenPending) return;
    fullscreenPending = true;
    try {
        const active = activeDocument();
        if (active) await active.exitFullscreen();
        else if (hostFrame?.requestFullscreen) await hostFrame.requestFullscreen();
        else if (document.fullscreenEnabled && view.requestFullscreen) await view.requestFullscreen();
        else throw new Error('Fullscreen is not supported in this browser.');
        notice.hidden = true;
        notice.textContent = '';
    } catch (error) {
        console.warn('Fullscreen request failed:', error.name, error.message);
        notice.textContent = 'Your browser could not enter full screen. Allow fullscreen for this page and try again.';
        notice.hidden = false;
    } finally {
        fullscreenPending = false;
        syncFullscreen();
    }
});
document.addEventListener('fullscreenchange', syncFullscreen);
hostDocument?.addEventListener('fullscreenchange', syncFullscreen);
syncFullscreen();

window.addEventListener('desktop-ended', () => {
    const active=activeDocument();
    if(active) active.exitFullscreen().catch(()=>{});
});
