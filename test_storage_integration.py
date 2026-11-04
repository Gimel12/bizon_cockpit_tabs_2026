#!/usr/bin/python3
"""Root integration test. Destructive commands are restricted to private loop-backed fixtures."""
import hashlib,importlib.util,json,os,subprocess,time,uuid
from pathlib import Path
spec=importlib.util.spec_from_file_location('s','/var/lib/bizon-storage-validation/backend.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
config_path=Path('/etc/mdadm/mdadm.conf');config_before=config_path.read_text()
s.setup();lab=s.STATE/'lab';lab.mkdir(mode=0o700,exist_ok=True);out=Path('/home/bizon/storage-lab-20261104');checks=[];loops=[];arrays=[];mount=Path('/mnt/bizon-storage-validation');jobs=[]
def passed(x):checks.append(x);print('PASS',x,flush=True)
def waitjob(jid,timeout=70):
 for _ in range(timeout):
  d=s.read_job(jid)
  if d['status'] not in ['queued','running']:return d
  time.sleep(1)
 raise AssertionError('Job timeout')
def waitsync(path,timeout=120):
 for _ in range(timeout):
  _,a=s.array_by_path(path)
  if a['sync_action'] in ['idle',None]:return a
  time.sleep(1)
 raise AssertionError('Sync timeout')
def expect(fn):
 try:fn()
 except s.StorageError:return
 raise AssertionError('Unsafe action was not rejected')
def apply(req):
 p=s.raid_plan(req);return s.raid_apply({'token':p['token'],'confirmation':p['confirmation']})
try:
 inventory=s.inventory();system=next(d for d in inventory['devices'] if '/' in d['mountpoints']);assert not system['available'];passed('Real OS drive is protected; SMART inventory loads')
 expect(lambda:s.raid_plan({'action':'create','devices':[system['path'],system['path']],'level':'1','name':'bad'}));passed('Duplicate physical drive selection rejected')
 for i in range(4):
  image=lab/('fixture-'+str(i)+'.img');fd=os.open(image,os.O_CREAT|os.O_EXCL|os.O_RDWR,0o600);os.ftruncate(fd,4*1024**3);os.close(fd)
  loop=s.run(['/usr/sbin/losetup','--find','--show','--direct-io=on',str(image)]).stdout.strip();loops.append(loop)
 assert all(s.find(p)['type']=='loop' for p in loops);passed('Four private loop devices created and recognized')
 before={p:hashlib.sha256(open(p,'rb').read(1024*1024)).hexdigest() for p in loops[:2]}
 job=s.start_test({'devices':loops[:2],'profile':'seq-read','duration':10,'depth':4,'size_gib':1,'customer':'Validation fixture','reference':'Read-only pair'});jobs.append(job['id'])
 expect(lambda:s.raid_plan({'action':'create','devices':loops[:2],'level':'1','name':'bizon_validation'}));passed('RAID changes blocked during active test')
 result=waitjob(job['id']);assert result['status']=='completed',result;assert len(result['results'])==2;assert any(x['bandwidth'] for x in result['samples']),result
 assert all(hashlib.sha256(open(p,'rb').read(1024*1024)).hexdigest()==before[p] for p in loops[:2]);passed('Concurrent read-only tests completed with live samples and unchanged fixture data')
 (out/'sample-client-report.html').write_text(s.report(result));(out/'sample-result.json').write_text(json.dumps(result,indent=2));passed('HTML client report and complete JSON generated')
 job=s.start_test({'devices':loops[:1],'profile':'random-read','duration':60,'depth':4});jobs.append(job['id']);time.sleep(3);s.dispatch('stop',{'id':job['id']});assert waitjob(job['id'])['status']=='cancelled';passed('Cancellation stops worker and reports incomplete result')
 for level,count in [('1',2),('0',2),('5',3),('6',4),('10',4)]:
  r=apply({'action':'create','devices':loops[:count],'level':level,'name':'bizon_validation'});path=r['array']['path'];arrays.append(path);waitsync(path);passed('RAID '+level+' creation and initial synchronization')
  if level=='1':
   s.run(['/usr/sbin/mkfs.ext4','-q',path]);mount.mkdir(exist_ok=True);s.run(['/usr/bin/mount',path,str(mount)])
   expect(lambda:s.raid_plan({'action':'delete','path':path}));passed('Mounted array deletion rejected')
   keep=mount/'customer-data.txt';keep.write_text('BIZON preservation fixture\n')
   job=s.start_test({'devices':[path],'profile':'mixed','duration':10,'depth':4,'size_gib':1,'mounts':{path:str(mount)},'customer':'Validation fixture','reference':'Mixed load'});jobs.append(job['id']);result=waitjob(job['id']);assert result['status']=='completed',result
   assert keep.read_text()=='BIZON preservation fixture\n';assert not list(mount.glob('.bizon-test-*'));passed('Mixed read/write uses a temporary file, preserves existing data and cleans up')
   s.run(['/usr/bin/umount',str(mount)]);s.raid_check({'path':path});a=waitsync(path);assert int(a['mismatch_count'])==0;passed('RAID consistency check completes without mismatches')
  apply({'action':'delete','path':path});arrays.remove(path);assert not any(s.signatures(s.find(p)) for p in loops[:count]);passed('RAID '+level+' deletion clears only fixture member metadata')
 passed('All storage integration checks completed')
finally:
 for jid in jobs:
  try:
   if s.read_job(jid)['status'] in ['running','queued']:s.dispatch('stop',{'id':jid});waitjob(jid)
  except Exception:pass
 if os.path.ismount(mount):s.run(['/usr/bin/umount',str(mount)],check=False)
 for path in arrays:s.run(['/usr/sbin/mdadm','--stop',path],check=False)
 for loop in loops:s.run(['/usr/sbin/losetup','-d',loop],check=False)
 for image in lab.glob('fixture-*.img'):image.unlink()
 if mount.exists() and not os.path.ismount(mount):mount.rmdir()
 config_path.write_text(config_before)
 (out/'integration-result.json').write_text(json.dumps({'passed':checks,'count':len(checks),'fixture_devices':loops,'job_ids':jobs},indent=2))
