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
  with patch.object(s,'selected',return_value=[d]),patch.object(s,'fingerprint',return_value={}),patch.object(s.Path,'exists',return_value=True):
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
if __name__=='__main__':unittest.main(verbosity=2)
