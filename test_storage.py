#!/usr/bin/env python3
"""Storage invariants: no real device I/O in this unit suite."""
import importlib.util,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('storage',Path(__file__).parent/'cockpit_support/storage/backend.py');s=importlib.util.module_from_spec(spec);spec.loader.exec_module(s)
class StorageTests(unittest.TestCase):
 def disk(self,**kw):
  return dict(path='/dev/test',kname='test',type='disk',size=100*1024**3,serial='ONE',wwn='x',ro=False,mountpoints=[],**kw)
 def test_identity_rejects_path_injection(self):
  for value in ['../etc/passwd','x;reboot','/dev/sda',None,'a'*33]:
   with self.assertRaises(s.StorageError):s.ident(value)
 def test_duplicate_selection(self):
  with self.assertRaises(s.StorageError):s.selected(['/dev/a','/dev/a'])
 def test_absent_selection(self):
  with patch.object(s,'tree',return_value=[]):
   with self.assertRaises(s.StorageError):s.selected(['/dev/sda'])
 def test_partition_cannot_be_selected(self):
  with patch.object(s,'tree',return_value=[dict(path='/dev/sda1',type='part')]):
   with self.assertRaises(s.StorageError):s.find('/dev/sda1')
 def test_mounted_child_protects_whole_disk(self):
  d=self.disk(children=[dict(mountpoints=['/'],children=[])])
  with patch.object(s,'holders',return_value=[]),patch.object(s,'signatures',return_value=[]):
   reasons=s.available(d);self.assertIn('Mounted or active swap',reasons);self.assertGreaterEqual(len(reasons),2)
 def test_signatures_and_holders_protect(self):
  with patch.object(s,'holders',return_value=['md0']),patch.object(s,'signatures',return_value=[{}]):self.assertEqual(len(s.available(self.disk())),2)
 def test_write_rejects_system_mount(self):
  d=self.disk(fstype='ext4');d['mountpoints']=['/']
  with patch.object(s,'selected',return_value=[d]),patch.object(s,'fingerprint',return_value={}),patch.object(s,'require_testable'),patch.object(s.Path,'exists',return_value=True):
   with self.assertRaises(s.StorageError):s.validate_test({'devices':['/dev/test'],'profile':'mixed','mounts':{'/dev/test':'/'}})
 def test_bounded_workloads(self):
  with patch.object(s,'selected',return_value=[self.disk()]):
   for req in [{'duration':0},{'duration':3601},{'duration':True},{'depth':256},{'size_gib':200},{'profile':'write;reboot'}]:
    with self.assertRaises(s.StorageError):s.validate_test({'devices':['/dev/test'],**req})
 def test_fio_partial_records(self):
  self.assertEqual(s.json_records('{"jobs":[]}\n{"jobs":[1]}\n{"jo'),{'jobs':[1]})
 def test_metrics_units(self):
  r=s.metrics({'jobs':[{'read':{'bw_bytes':1048576,'iops':3,'clat_ns':{'mean':1000000,'percentile':{'99.000000':2000000}}}}]})[0]['read'];self.assertEqual(r['mib_s'],1);self.assertEqual(r['latency_mean_ms'],1);self.assertEqual(r['latency_p99_ms'],2)
 def test_unknown_smart_not_pass(self):
  from types import SimpleNamespace
  with patch.object(s,'run',return_value=SimpleNamespace(returncode=2,stdout='{}',stderr='')),patch.object(s.Path,'exists',return_value=True):self.assertEqual(s.smart('/dev/no')['status'],'unavailable')
 def test_smart_media_warning(self):
  from types import SimpleNamespace
  raw={'smart_status':{'passed':True},'nvme_smart_health_information_log':{'media_errors':1}}
  with patch.object(s,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(raw),stderr='')),patch.object(s.Path,'exists',return_value=True):self.assertEqual(s.smart('/dev/no')['status'],'warning')
 def test_smart_failed_health_and_partial_log(self):
  from types import SimpleNamespace
  for raw,code,expected in [({'smart_status':{'passed':False}},8,'warning'),({'smart_status':{'passed':True}},4,'partial')]:
   with patch.object(s,'run',return_value=SimpleNamespace(returncode=code,stdout=json.dumps(raw),stderr='')),patch.object(s.Path,'exists',return_value=True):self.assertEqual(s.smart('/dev/no')['status'],expected)
 def test_report_escapes_customer_and_drive(self):
  d={'status':'cancelled','config':{'devices':[{'path':'<script>x</script>','drive':{'size':100,'serial':'<img>'}}],'customer':'<script>alert(1)</script>','reference':'x','profile':'seq-read','duration':30,'depth':1}}
  report=s.report(d);self.assertNotIn('<script>',report);self.assertIn('&lt;script&gt;',report);self.assertIn('cancelled',report)
 def test_plan_expired_and_confirmation(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(s,'STATE',Path(tmp)),patch.object(s,'check_idle'),patch.object(s,'boot_id',return_value='b'):
   (Path(tmp)/'plans').mkdir();token='a'*32;p=Path(tmp)/'plans'/(token+'.json')
   for created,confirmation in [(0,'CREATE data'),(s.time.time(),'WRONG')]:
    s.save(p,{'boot_id':'b','created':created,'confirmation':'CREATE data'})
    with self.assertRaises(s.StorageError):s.raid_apply({'token':token,'confirmation':confirmation})
 def test_changed_drive_rejected_before_mdadm(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(s,'STATE',Path(tmp)),patch.object(s,'check_idle'),patch.object(s,'boot_id',return_value='b'),patch.object(s,'selected',return_value=[self.disk()]),patch.object(s,'run') as command:
   (Path(tmp)/'plans').mkdir();token='a'*32
   s.save(Path(tmp)/'plans'/(token+'.json'),{'token':token,'boot_id':'b','created':s.time.time(),'confirmation':'CREATE data','config':{'action':'create','name':'data','level':'1','devices':[{'path':'/dev/test','serial':'OTHER'}]}})
   with self.assertRaises(s.StorageError):s.raid_apply({'token':token,'confirmation':'CREATE data'})
   command.assert_not_called()
 def test_mounted_array_rejected(self):
  d=self.disk();d['mountpoints']=['/mnt/data']
  with patch.object(s,'array_by_path',return_value=(d,{'sync_action':'idle'})):
   with self.assertRaises(s.StorageError):s.validate_array_change('/dev/md0')
 def test_backend_has_no_shell_execution(self):
  text=Path(s.__file__).read_text();self.assertNotIn('shell=True',text);self.assertNotIn('wipefs\',\'-a',text)
class SystemProtectionTests(unittest.TestCase):
 def node(self,path,key,children=None,**extra):
  return dict(path=path,**{'maj:min':key},children=children or [],**extra)
 def test_os_disk_and_other_partition_protected_data_disk_allowed(self):
  nodes=[self.node('/dev/nvme0n1','259:0',[self.node('/dev/nvme0n1p1','259:1'),self.node('/dev/nvme0n1p2','259:2')]),self.node('/dev/sdb','8:16')]
  protected,error=s.system_guard(nodes,{'/':'259:1'})
  self.assertIsNone(error);self.assertTrue(protected['/dev/nvme0n1']);self.assertTrue(protected['/dev/nvme0n1p2']);self.assertFalse(protected['/dev/sdb'])
 def test_raid_lvm_crypto_all_parents_protected(self):
  root=self.node('/dev/dm-1','253:1')
  md=self.node('/dev/md0','9:0',[self.node('/dev/dm-0','253:0',[root])])
  nodes=[self.node('/dev/sda','8:0',[md]),self.node('/dev/sdb','8:16',[md]),self.node('/dev/sdc','8:32')]
  protected,error=s.system_guard(nodes,{'/':'253:1'})
  self.assertIsNone(error)
  for p in ['/dev/sda','/dev/sdb','/dev/md0','/dev/dm-0']:self.assertTrue(protected[p],p)
  self.assertFalse(protected['/dev/sdc'])
 def test_separate_boot_home_and_swap_protected(self):
  nodes=[self.node('/dev/'+str(i),'8:'+str(i)) for i in range(5)]
  protected,error=s.system_guard(nodes,{'/':'8:0','/boot/efi':'8:1','/home':'8:2','swap: /dev/3':'8:3'})
  self.assertIsNone(error)
  for i in range(4):self.assertTrue(protected['/dev/'+str(i)])
  self.assertFalse(protected['/dev/4'])
 def test_nested_system_filesystem_protected(self):
  nodes=[self.node('/dev/a','8:0'),self.node('/dev/b','8:1',mountpoints=['/var/lib']),self.node('/dev/c','8:2',mountpoints=['/mnt/data'])]
  protected,error=s.system_guard(nodes,{'/':'8:0'});self.assertIsNone(error);self.assertTrue(protected['/dev/b']);self.assertFalse(protected['/dev/c'])
 def test_shared_filesystem_uuid_protected(self):
  nodes=[self.node('/dev/a','8:0',uuid='fs'),self.node('/dev/b','8:1',uuid='fs')]
  protected,error=s.system_guard(nodes,{'/':'8:0'});self.assertTrue(protected['/dev/b'])
 def test_unknown_system_storage_fails_closed(self):
  for sources in [{},{'/':'0:31'},{'/':'8:0','/var':'0:9'}]:
   protected,error=s.system_guard([self.node('/dev/a','8:0')],sources);self.assertIsNotNone(error)
   with patch.object(s,'system_guard',return_value=(protected,error)):
    with self.assertRaises(s.StorageError):s.require_testable([{'path':'/dev/a'}])
 def test_all_four_profiles_block_os_before_fio(self):
  with patch.object(s,'selected',return_value=[{'path':'/dev/os'}]),patch.object(s,'system_guard',return_value=({'/dev/os':['/']},None)),patch.object(s.Path,'exists',return_value=True):
   for profile in s.PROFILES:
    with self.assertRaisesRegex(s.StorageError,'OS / system'):s.validate_test({'devices':['/dev/os'],'profile':profile})
 def test_missing_device_in_protection_snapshot_rejected(self):
  with patch.object(s,'system_guard',return_value=({},None)):
   with self.assertRaisesRegex(s.StorageError,'topology changed'):s.require_testable([{'path':'/dev/missing'}])
 def test_non_os_read_accepted(self):
  d=StorageTests().disk()
  with patch.object(s,'selected',return_value=[d]),patch.object(s,'system_guard',return_value=({'/dev/test':[]},None)),patch.object(s.Path,'exists',return_value=True),patch.object(s,'fingerprint',return_value={}):
   self.assertEqual(s.validate_test({'devices':['/dev/test']})['devices'][0]['path'],'/dev/test')
 def test_worker_rechecks_before_opening_device(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(s,'STATE',Path(tmp)),patch.object(s,'find',return_value={'path':'/dev/os'}),patch.object(s,'system_guard',return_value=({'/dev/os':['/']},None)),patch.object(s.os,'open') as opening,patch.object(s.subprocess,'Popen') as launch:
   jid='b'*32;p=Path(tmp)/'jobs'/jid;p.mkdir(parents=True)
   s.save(p/'state.json',{'config':{'devices':[{'path':'/dev/os'}]}})
   s.worker(jid);d=json.loads((p/'state.json').read_text());self.assertEqual(d['status'],'failed');self.assertIn('OS / system',d['error']);opening.assert_not_called();launch.assert_not_called()
 def test_periodic_snapshots_and_report_show_transient_errors(self):
  path='/dev/data';d={'status':'completed','config':{'devices':[{'path':path,'model':'Sample <drive>','name':'data','transport':'nvme','drive':{'size':10**12,'serial':'SERIAL-123','wwn':'WWN-456'}}],'customer':'Customer','reference':'REF','profile':'mixed','duration':30,'depth':4},'before':{path:{'temperature':30,'media_errors':0,'pending_sectors':0,'status':'passed'}},'after':{path:{'temperature':35,'media_errors':0,'status':'passed'}}}
  s.record_health(d,d['before'],0,'before');s.record_health(d,{path:{'temperature':52,'media_errors':2,'status':'warning','alerts':['Transient error'],'raw':{'secret':'raw not duplicated'}}},10,'during');s.record_health(d,d['after'],30,'after')
  self.assertNotIn('raw',d['health_samples'][1]['drives'][path]);r=s.report(d)
  for value in ['SERIAL-123','WWN-456','Sample &lt;drive&gt;','52 °C','Transient error','Review required','Recorded temperature and error timeline','Not comparable']:self.assertIn(value,r)
  self.assertEqual(s.error_changes({'media_errors':0},{'media_errors':2}),{'media_errors':2})

if __name__=='__main__':unittest.main(verbosity=2)
