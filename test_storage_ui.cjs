/* npm install --prefix /tmp/bizon-storage-ui-tests jsdom@26
 * NODE_PATH=/tmp/bizon-storage-ui-tests/node_modules node test_storage_ui.cjs */
const {JSDOM}=require('jsdom'),fs=require('node:fs'),assert=require('node:assert/strict');
let count=0;const ok=(condition,label)=>{assert.ok(condition,label);console.log('PASS '+label);count++;};
const wait=()=>new Promise(resolve=>setTimeout(resolve,15));
async function page(mode){
 const dom=new JSDOM(fs.readFileSync('cockpit_support/'+(mode==='raid'?'raid':'drives')+'.html','utf8'),{runScripts:'outside-only',url:'https://fixture.test/'+mode});
 const w=dom.window;w.HTMLDialogElement.prototype.showModal=function(){this.open=true;};w.HTMLDialogElement.prototype.close=function(){this.open=false;};w.HTMLElement.prototype.scrollIntoView=function(){};w.URL.createObjectURL=()=> 'blob:fixture';w.URL.revokeObjectURL=()=>{};
 w.eval(fs.readFileSync('tests/storage-ui-fixture.js','utf8'));w.eval(fs.readFileSync('cockpit_support/storage/storage.js','utf8')+'\nwindow.uiTest={loadJobs,reset:()=>{chosen.clear();renderDrives();}};');await wait();return dom;
}
(async()=>{
 let dom=await page('drives'),w=dom.window,d=w.document;
 w.cockpit.jump=path=>w.fixtureCalls.push({action:'jump',path});d.querySelector('.workspace-nav a[href="raid.html"]').click();ok(w.fixtureCalls.some(x=>x.action==='jump'&&x.path==='/cockpit_support/raid'),'Navigation switches the Cockpit component, not only its iframe');
 ok(d.querySelectorAll('.drive-card').length===6,'Drive cards render the inventory');
 ok(d.querySelector('[data-path="/dev/nvme0n1"].pick').disabled,'OS drive cannot be selected');
 ok(d.querySelector('#start').disabled,'No drive selection keeps Start disabled');
 d.querySelector('[data-path="/dev/nvme0n1"].detail').click();ok(d.querySelector('#details').open&&d.querySelector('#details-body').textContent.includes('OS / system'),'OS SMART details remain accessible');d.querySelector('#details-close').click();
 const pick=path=>{const p=d.querySelector('.pick[data-path="'+path+'"]');p.checked=true;p.dispatchEvent(new w.Event('change'));};
 pick('/dev/nvme1n1');ok(!d.querySelector('#start').disabled,'Data-drive selection enables test review');
 let r=d.querySelector('[name=profile][value=mixed]');r.checked=true;r.dispatchEvent(new w.Event('change'));
 ok(d.querySelector('.mount').value==='/mnt/projects','Write test targets its mounted data volume');
 d.querySelector('#start').click();await wait();ok(d.querySelector('#review').open&&d.querySelector('#review-body').textContent.includes('DEMO-DATA'),'Test review identifies exact model and serial');
 d.querySelector('#review-apply').click();await wait();ok(w.fixtureCalls.some(x=>x.action==='start'&&x.req.profile==='mixed'&&x.req.devices[0]==='/dev/nvme1n1'),'Confirmed test sends the selected workload and data drive');
 ok(d.querySelector('#results-title').textContent==='Test in progress','Running state is distinct from historical results');
 d.querySelector('#stop').click();await wait();ok(w.fixtureCalls.some(x=>x.action==='stop'),'Stop action reaches backend');
 w.fixtureJobs.length=0;await w.uiTest.loadJobs();ok(d.querySelector('#results-title').textContent==='Ready when you are','Empty results state clears the previous run');
 w.uiTest.reset();pick('/dev/sdb');r=d.querySelector('[name=profile][value=seq-write]');r.checked=true;r.dispatchEvent(new w.Event('change'));ok(d.querySelector('#start').disabled,'Write test without an eligible mount is blocked');
 d.querySelector('#drive-search').value='DEMO-004';d.querySelector('#drive-search').dispatchEvent(new w.Event('input'));ok(d.querySelectorAll('.drive-card').length===1&&d.querySelector('.drive-numbers').textContent.includes('—'),'Serial search and unknown health values display correctly');
 dom.window.close();
 dom=await page('raid');w=dom.window;d=w.document;
 const select=path=>{const p=d.querySelector('.pick[data-path="'+path+'"]');p.checked=true;p.dispatchEvent(new w.Event('change'));};
 select('/dev/sdb');ok(d.querySelector('#create').disabled,'One drive cannot create RAID 1');select('/dev/sdc');ok(!d.querySelector('#create').disabled,'Two blank drives enable RAID 1 review');
 r=d.querySelector('[name=level][value="10"]');r.checked=true;r.dispatchEvent(new w.Event('change'));select('/dev/sdd');ok(d.querySelector('#create').disabled,'Odd drive count blocks RAID 10');select('/dev/sde');ok(!d.querySelector('#create').disabled,'Four blank drives enable RAID 10');
 d.querySelector('#array-name').value='bad;command';d.querySelector('#array-name').dispatchEvent(new w.Event('input'));ok(d.querySelector('#create').disabled,'Invalid array name is blocked before review');
 d.querySelector('#array-name').value='projects';d.querySelector('#array-name').dispatchEvent(new w.Event('input'));d.querySelector('#create').click();await wait();ok(d.querySelector('#review-apply').disabled,'RAID review requires typed confirmation');
 d.querySelector('#confirmation').value='CREATE projects';d.querySelector('#confirmation').dispatchEvent(new w.Event('input'));ok(!d.querySelector('#review-apply').disabled,'Exact typed phrase enables the reviewed change');
 d.querySelector('#review-cancel').click();ok(!w.fixtureCalls.some(x=>x.action==='raid-apply'),'Cancelling a RAID review never applies it');
 d.querySelector('#create').click();await wait();d.querySelector('#confirmation').value='CREATE projects';d.querySelector('#confirmation').dispatchEvent(new w.Event('input'));d.querySelector('#review-apply').click();await wait();ok(w.fixtureCalls.some(x=>x.action==='raid-apply'&&x.req.confirmation==='CREATE projects'&&x.req.token==='b'.repeat(32)),'RAID apply sends only the reviewed token and exact confirmation');
 dom.window.close();console.log(count+' UI checks passed');
})().catch(e=>{console.error(e);process.exit(1);});
