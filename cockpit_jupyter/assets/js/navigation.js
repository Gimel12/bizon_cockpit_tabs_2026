/* Keep notebook links inside Cockpit's navigation, including the shell URL.
 * The regular href still works for standalone previews and modified clicks. */
document.addEventListener('click', function(event) {
    if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest('a[data-cockpit-route]');
    if (!link || typeof window.cockpit?.jump !== 'function') return;
    event.preventDefault();
    window.cockpit.jump(link.dataset.cockpitRoute);
});
