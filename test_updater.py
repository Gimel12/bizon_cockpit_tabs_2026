#!/usr/bin/python3
import hashlib,importlib.util,io,json,os,subprocess,tarfile,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('updater',Path(__file__).with_name('bizon-tabs-update.py'));u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
class UpdaterTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.addCleanup(self.tmp.cleanup)
 def blob(self,extra=None,manifests=None):
  out=io.BytesIO()
  with tarfile.open(fileobj=out,mode='w:gz') as t:
   for name in u.TABS:
    manifest=(manifests or {}).get(name,{'tools':{'main':{'path':'index.html'}}})
    for suffix,data in [('manifest.json',json.dumps(manifest).encode()),('index.html',b'<h1>Test</h1>')]:
     x=tarfile.TarInfo(name+'/'+suffix);x.size=len(data);x.mode=0o644;t.addfile(x,io.BytesIO(data))
   if extra:
    x,data=extra;t.addfile(x,io.BytesIO(data))
  return out.getvalue()
 def meta(self,blob,seq=1):return dict(schema=1,product='bizon-cockpit-tabs',sequence=seq,version='test-'+str(seq),tabs=list(u.TABS),size=len(blob),sha256=hashlib.sha256(blob).hexdigest(),url='https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/download/test/tabs.tar.gz')
 def signed(self,raw):
  key=self.root/'key';pub=self.root/'pub'
  if not key.exists():
   subprocess.run(['openssl','genpkey','-algorithm','RSA','-pkeyopt','rsa_keygen_bits:2048','-out',str(key)],check=True,capture_output=True)
   subprocess.run(['openssl','pkey','-in',str(key),'-pubout','-out',str(pub)],check=True,capture_output=True)
  signature=subprocess.run(['openssl','dgst','-sha256','-sign',str(key)],input=raw,check=True,capture_output=True).stdout
  return pub,signature
 def test_install_and_atomic_upgrade(self):
  b=self.blob();u.install(b,self.meta(b),self.root);u.install(b,self.meta(b,2),self.root)
  self.assertEqual(u.read_current(self.root)['sequence'],2);self.assertEqual(os.readlink(self.root/'previous'),'releases/1')
 def test_native_navigation_sections_are_validated_and_installed(self):
  for section in ('dashboard','menu','tools'):
   with self.subTest(section=section):
    b=self.blob(manifests={name:{section:{'main':{'path':'index.html'}}} for name in u.TABS})
    target=self.root/section;u.install(b,self.meta(b),target)
    self.assertEqual(u.read_current(target)['sequence'],1)
 def test_upgrade_from_tools_to_dashboard_keeps_previous_release(self):
  old=self.blob();u.install(old,self.meta(old),self.root)
  new=self.blob(manifests={name:{'dashboard':{'main':{'path':'index.html'}}} for name in u.TABS})
  u.install(new,self.meta(new,2),self.root)
  self.assertEqual(u.read_current(self.root)['sequence'],2)
  previous=json.loads((self.root/'previous'/u.TABS[0]/'manifest.json').read_text())
  current=json.loads((self.root/'current'/u.TABS[0]/'manifest.json').read_text())
  self.assertIn('tools',previous);self.assertIn('dashboard',current)
 def test_invalid_page_in_any_navigation_section_preserves_release(self):
  old=self.blob();u.install(old,self.meta(old),self.root)
  for section in ('dashboard','menu','tools'):
   for entry in ({'path':'missing.html'},{'path':'../cockpit_gpu/index.html'},{'path':'/etc/passwd'},{'path':''},{'path':[]},{},None):
    with self.subTest(section=section,entry=entry):
     # A valid entry in another section must not hide an invalid entry.
     manifest={'tools':{'valid':{'path':'index.html'}},section:{'invalid':entry}}
     b=self.blob(manifests={u.TABS[0]:manifest})
     with self.assertRaises(u.UpdateError):u.install(b,self.meta(b,2),self.root)
     self.assertEqual(u.read_current(self.root)['sequence'],1)
 def test_missing_or_invalid_navigation_is_rejected(self):
  manifests=[{},[],None,{'dashboard':[]},{'menu':None},{'tools':'invalid'},{'dashboard':{}}]
  for manifest in manifests:
   with self.subTest(manifest=manifest):
    b=self.blob(manifests={u.TABS[0]:manifest})
    with self.assertRaises(u.UpdateError):u.install(b,self.meta(b),self.root)
    self.assertFalse((self.root/'current').exists())
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
 def test_latest_alias_moving_between_requests_uses_matching_signature(self):
  latest='https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/latest/download/manifest.json'
  first=json.dumps(self.meta(self.blob(),1)).encode();second=json.dumps(self.meta(self.blob(),2)).encode()
  pub,first_sig=self.signed(first);_,second_sig=self.signed(second)
  calls=[]
  def moving_server(url,limit):
   calls.append((url,limit))
   if url==latest:return first
   # The latest alias moved to release 2 after its manifest was downloaded.
   if url==latest+'.sig':return second_sig
   if url==u.RELEASE_DOWNLOAD+'test-1/manifest.json.sig':return first_sig
   raise AssertionError('Unexpected release request: '+url)
  with patch.object(u,'fetch',side_effect=moving_server):
   self.assertEqual(u.release_metadata(latest,pub)['sequence'],1)
  self.assertEqual(calls,[(latest,65536),(u.RELEASE_DOWNLOAD+'test-1/manifest.json.sig',2048)])
 def test_unsafe_or_malformed_version_hint_never_fetches_signature(self):
  versions=[None,[],1,'','../v1','v1/other','https://evil.example','v1?other','v1#other','v1%2fother','v1\n','a'*65]
  for version in versions:
   with self.subTest(version=version),patch.object(u,'fetch',return_value=json.dumps({'version':version}).encode()) as fetch:
    with self.assertRaises(u.UpdateError):u.release_metadata('latest',self.root/'unused-key')
    self.assertEqual(fetch.call_count,1)
  for raw in (b'not json',b'[]',b'null'):
   with self.subTest(raw=raw),patch.object(u,'fetch',return_value=raw) as fetch:
    with self.assertRaises(u.UpdateError):u.release_metadata('latest',self.root/'unused-key')
    self.assertEqual(fetch.call_count,1)
 def test_safe_version_hint_does_not_make_tampered_manifest_trusted(self):
  original=json.dumps(self.meta(self.blob())).encode();pub,signature=self.signed(original)
  tampered=json.loads(original);tampered['sequence']=999
  with patch.object(u,'fetch',side_effect=[json.dumps(tampered).encode(),signature]):
   with self.assertRaisesRegex(u.UpdateError,'signature is invalid'):u.release_metadata('latest',pub)
  self.assertFalse((self.root/'current').exists())
if __name__=='__main__':unittest.main(verbosity=2)
