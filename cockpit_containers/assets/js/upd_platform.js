document.addEventListener('DOMContentLoaded', function() {
  ['update','update-tab-btn','update-webui-btn'].forEach(function(id) {
    const button=document.getElementById(id);
    if (button) button.addEventListener('click',function(event) {
      event.preventDefault(); window.alert('Install an administrator-reviewed BIZON release to update this application.');
    });
  });
});
