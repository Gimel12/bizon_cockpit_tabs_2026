#!/usr/bin/python3
import hashlib,importlib.util,io,json,os,subprocess,tarfile,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('updater',Path(__file__).with_name('bizon-tabs-update.py'));u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
class UpdaterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
 def blob(self,extra=None):
  out=io.BytesIO()
  with tarfile.open(fileobj=out,mode='w:gz') as t:
   for name in u.TABS:
    for suffix,data in [('manifest.json',b'{"tools":{"main":{"path":"index.html"}}}'),('index.html',b'<h1>Test</h1>')]:
     x=tarfile.TarInfo(name+'/'+suffix);x.size=len(data);x.mode=0o644;t.addfile(x,io.BytesIO(data))
   if extra:
    x,data=extra;t.addfile(x,io.BytesIO(data))
  return out.getvalue()
 def meta(self,blob,seq=1):return dict(schema=1,product='bizon-cockpit-tabs',sequence=seq,version='test-'+str(seq),tabs=list(u.TABS),size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),url='https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/download/test/tabs.tar.gz')
 def test_install_and_atomic_upgrade(self):
  b=self.blob();u.install(b,self.meta(b),self.root);u.install(b,self.meta(b,2),self.root)
  self.assertEqual(u.read_current(self.root)['sequence'],2);self.assertEqual(os.readlink(self.root/'previous'),'releases/1')
 def test_restore_latest_after_rollback(self):
  b=self.blob();u.install(b,self.meta(b),self.root);m=self.meta(b,2);u.install(b,m,self.root)
  u.atomic_link('releases/1',self.root/'current');u.install(b,m,self.root)
  self.assertEqual(u.read_current(self.root)['sequence'],2)
 def test_replay_rejected(self):
  b=self.blob();m=self.meta(b);u.install(b,m,self.root)
  with self.assertRaises(u.UpdateError):u.install(b,m,self.root)
 def test_tamper_preserves_installed_release(self):
  b=self.blob();u.install(b,self.meta(b),self.root)
  with self.assertRaises(u.UpdateError):u.install(b+b'x',self.meta(b,2),self.root)
  self.assertEqual(u.read_current(self.root)['sequence'],1)
 def test_path_traversal(self):
  x=tarfile.TarInfo('cockpit_gpu/../../outside');x.size=1;b=self.blob((x,b'x'))
  with self.assertRaises(u.UpdateError):u.install(b,self.meta(b),self.root)
  self.assertFalse((self.root/'current').exists())
 def test_symlink_rejected(self):
  x=tarfile.TarInfo('cockpit_gpu/evil');x.type=tarfile.SYMTYPE;x.linkname='/etc';b=self.blob((x,b''))
  with self.assertRaises(u.UpdateError):u.install(b,self.meta(b),self.root)
 def test_duplicate_rejected(self):
  x=tarfile.TarInfo('cockpit_gpu/index.html');x.size=1;b=self.blob((x,b'x'))
  with self.assertRaises(u.UpdateError):u.install(b,self.meta(b),self.root)
 def test_invalid_python_rejected(self):
  x=tarfile.TarInfo('cockpit_gpu/bad.py');data=b'if !!!!!';x.size=len(data);b=self.blob((x,data))
  with self.assertRaises(u.UpdateError):u.install(b,self.meta(b),self.root)
 def test_signature_and_tampered_signature(self):
  key=self.root/'key';pub=self.root/'pub';raw=self.root/'manifest';sig=self.root/'sig'
  subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(key)],check=True,capture_output=True)
  subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],check=True,capture_output=True)
  b=self.blob();raw.write_text(json.dumps(self.meta(b)));subprocess.run(['openssl','dgst','-sha256','-sign',str(key),'-out',str(sig),str(raw)],check=True,capture_output=True)
  self.assertEqual(u.metadata(raw.read_bytes(),sig.read_bytes(),pub)['sequence'],1)
  with self.assertRaises(u.UpdateError):u.metadata(raw.read_bytes()+b' ',sig.read_bytes(),pub)
 def test_foreign_download_rejected(self):
  with self.assertRaises(u.UpdateError):u.fetch('https://example.org/arbitrary',10)
if __name__=='__main__':unittest.main(verbosity=2)
