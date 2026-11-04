#!/usr/bin/python3 -I
"""Administrator bootstrap for the hardened BIZON OS image; accepts a signed release directory."""
import argparse,importlib.util,json,os,shutil
from pathlib import Path
base=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('release_directory',type=Path);a=p.parse_args()
if os.geteuid()!=0:p.error('Run this reviewed installer as administrator')
for required in ['/usr/local/libexec/bizon-vnc-session','/usr/local/libexec/bizon-diagnostics','/var/lib/bizon-api/local-token']:
 if not Path(required).exists():p.error('Install the hardened BIZON OS baseline first: missing '+required)
spec=importlib.util.spec_from_file_location('updater',base/'bizon-tabs-update.py');u=importlib.util.module_from_spec(spec);spec.loader.exec_module(u)
m=u.metadata((a.release_directory/'manifest.json').read_bytes(),(a.release_directory/'manifest.json.sig').read_bytes(),base/'release-public.pem');blob=(a.release_directory/'tabs.tar.gz').read_bytes()
# Validate all release content before changing system paths.
import tempfile
with tempfile.TemporaryDirectory() as tmp:u.unpack(blob,m,Path(tmp))
cfg=Path('/etc/bizon-tabs');cfg.mkdir(exist_ok=True,mode=0o755);cfg.chmod(0o755)
if (cfg/'release-public.pem').exists() and (cfg/'release-public.pem').read_bytes()!=(base/'release-public.pem').read_bytes():p.error('Existing signing key differs; explicit key rotation is required')
for source,dest,mode in [('release-public.pem',cfg/'release-public.pem',0o644),('bizon-tabs-update.py',Path('/usr/local/libexec/bizon-tabs-update'),0o755)]:
 shutil.copyfile(base/source,dest);dest.chmod(mode);os.chown(dest,0,0)
(cfg/'source.json').write_text(json.dumps({'manifest_url':'https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/latest/download/manifest.json'})+'\n');(cfg/'source.json').chmod(0o644)
store=u.STORE;original=store/'releases/0';original.mkdir(parents=True,exist_ok=True)
for path in [store,store/'releases',original]:path.chmod(0o755)
if not (store/'current').exists():
 (original/'release.json').write_text(json.dumps({'sequence':0,'version':'6.1-security-baseline'})+'\n');(original/'release.json').chmod(0o644)
 u.atomic_link('releases/0',store/'current')
for tab in u.TABS:
 path=Path('/usr/local/share/dlbt_os')/tab
 if not path.is_symlink():
  if path.exists():os.rename(path,original/tab)
  path.symlink_to(store/'current'/tab)
if u.read_current()['sequence']<m['sequence']:u.install(blob,m)
wrapper=Path('/opt/bizon-cockpit-tabs/update_tabs.py');shutil.copyfile(base/'update_tabs.py',wrapper);wrapper.chmod(0o755);os.chown(wrapper,0,0)
print('Verified BIZON release and updater installed. Reload Cockpit.')
