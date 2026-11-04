#!/usr/bin/env python3
"""Build deterministic tab assets. The signing key stays on the maintainer computer."""
import argparse,gzip,hashlib,io,json,subprocess,tarfile
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--version',required=True);p.add_argument('--sequence',type=int,required=True);p.add_argument('--key',required=True);p.add_argument('--out',required=True);a=p.parse_args()
base=Path(__file__).parent;out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
tabs=sorted(x.name for x in base.glob('cockpit_*') if x.is_dir())
archive=out/'tabs.tar.gz'
with archive.open('wb') as raw,gzip.GzipFile(fileobj=raw,mode='wb',mtime=0) as gz,tarfile.open(fileobj=gz,mode='w') as t:
 for name in tabs:
  for path in sorted((base/name).rglob('*')):
   if not path.is_file() or any(x in ('__pycache__','.git','.DS_Store') for x in path.parts) or path.suffix in ('.pyc','.zip','.7z'):continue
   if path.is_symlink():raise SystemExit('Symlink not allowed: '+str(path))
   item=tarfile.TarInfo(str(path.relative_to(base)));data=path.read_bytes();item.size=len(data);item.mode=0o755 if path.stat().st_mode&0o111 else 0o644;item.mtime=0;t.addfile(item,io.BytesIO(data))
data=archive.read_bytes();manifest=dict(schema=1,product='bizon-cockpit-tabs',sequence=a.sequence,version=a.version,tabs=tabs,size=len(data),sha256=hashlib.sha256(data).hexdigest(),url=f'https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/download/{a.version}/tabs.tar.gz')
f=out/'manifest.json';f.write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
subprocess.run(['openssl','dgst','-sha256','-sign',a.key,'-out',str(f)+'.sig',str(f)],check=True)
print(json.dumps(manifest,indent=2))
