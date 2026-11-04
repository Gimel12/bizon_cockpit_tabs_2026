#!/usr/bin/python3
"""Root-only validation with a private RAM-backed loop; never benchmarks the OS disk."""
import importlib.util,json,os,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('s','/var/lib/bizon-storage-validation/backend.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
s.setup();out=Path('/home/bizon/storage-protection-20261104');out.mkdir(exist_ok=True)
checks=[];jobs=[];loop=None;mounted=False;ram=False;lab=s.STATE/'lab';mount=Path('/mnt/bizon-protection-validation')
def passed(x):checks.append(x);print('PASS',x,flush=True)
def wait(jid):
 for _ in range(100):
  result=s.read_job(jid)
  if result['status'] not in ['queued','running']:return result
  time.sleep(1)
 raise AssertionError('Worker timeout')
try:
 inv=s.inventory();osdrives=[d for d in inv['devices'] if d['is_os']]
 assert osdrives and all(not d['test_allowed'] for d in osdrives)
 (out/'inventory.json').write_text(json.dumps(inv,indent=2));passed('OS disk labelled and excluded; SMART details still available')
 for disk in osdrives:
  for profile in s.PROFILES:
   try:s.start_test({'devices':[disk['path']],'profile':profile,'duration':10})
   except s.StorageError as e:assert 'OS / system' in str(e),str(e)
   else:raise AssertionError('OS workload accepted')
 passed('Backend rejects all four read/write profiles on every OS device')
 lab.mkdir(mode=0o700,exist_ok=True);assert not list(lab.iterdir()) and not os.path.ismount(lab)
 s.run(['/usr/bin/mount','-t','tmpfs','-o','size=6G,mode=0700','bizon-validation-ram',str(lab)]);ram=True
 image=lab/'protection-fixture.img';fd=os.open(image,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600);os.ftruncate(fd,4*1024**3);os.close(fd)
 loop=s.run(['/usr/sbin/losetup','--find','--show',str(image)]).stdout.strip()
 s.run(['/usr/sbin/mkfs.ext4','-q',loop]);s.run(['/usr/bin/udevadm','trigger','--action=change','/sys/class/block/'+Path(loop).name]);s.run(['/usr/bin/udevadm','settle']);mount.mkdir(exist_ok=False);s.run(['/usr/bin/mount',loop,str(mount)]);mounted=True
 keep=mount/'customer-data.txt';keep.write_text('Preserve customer data\n')
 passed('Disposable data volume is RAM-backed, not a physical OS-drive benchmark')
 for profile in ['seq-read','seq-write','mixed']:
  job=s.start_test({'devices':[loop],'profile':profile,'duration':10,'depth':4,'size_gib':1,'mounts':{loop:str(mount)},'customer':'VALIDATION FIXTURE — NOT CUSTOMER HARDWARE','reference':'RAM fixture '+profile});jobs.append(job['id']);result=wait(job['id'])
  assert result['status']=='completed',result
  assert result['health_samples'][0]['phase']=='before' and result['health_samples'][-1]['phase']=='after'
  assert any(x['phase']=='during' for x in result['health_samples'])
  assert all(x['drives'][loop].get('temperature') is None for x in result['health_samples'])
  assert keep.read_text()=='Preserve customer data\n' and not list(mount.glob('.bizon-test-*'))
  (out/(profile+'.json')).write_text(json.dumps(result,indent=2));(out/(profile+'.html')).write_text(s.report(result))
  passed(profile+': completed, preserved files, cleaned up, recorded unavailable SMART honestly')
 job=s.start_test({'devices':[loop],'profile':'random-read','duration':60,'depth':1,'customer':'VALIDATION FIXTURE','reference':'Cancellation'});jobs.append(job['id']);time.sleep(3);s.dispatch('stop',{'id':job['id']});result=wait(job['id'])
 assert result['status']=='cancelled' and result['health_samples'][-1]['phase']=='after' and not result['errors'];passed('Cancellation records final health and remains incomplete')
finally:
 for jid in jobs:
  if s.read_job(jid)['status'] in ['queued','running']:s.dispatch('stop',{'id':jid});wait(jid)
 if mounted:s.run(['/usr/bin/umount',str(mount)])
 if loop:s.run(['/usr/sbin/losetup','-d',loop])
 if ram:s.run(['/usr/bin/umount',str(lab)])
 if mount.exists():mount.rmdir()
 (out/'results.json').write_text(json.dumps({'checks':checks,'job_ids':jobs},indent=2))
print(json.dumps({'passed':len(checks)}))
