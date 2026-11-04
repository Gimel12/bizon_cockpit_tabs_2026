#!/usr/bin/python3 -I
"""Install signed BIZON Cockpit releases; never execute downloaded installers."""
import argparse, base64, fcntl, hashlib, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time
from pathlib import Path, PurePosixPath
from urllib.request import Request, urlopen
from urllib.error import HTTPError
TABS = tuple('cockpit_'+s for s in ('bizon_ai','containers','gpu','jupyter','support','tutorials','vnc'))
CONFIG = Path('/etc/bizon-tabs')
STORE = Path('/usr/local/share/bizon-tabs')
MAX_ARCHIVE = 100*1024*1024
RELEASE_DOWNLOAD = 'https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/download/'
class UpdateError(Exception): pass

def emit(message, **fields):
    print(json.dumps(dict(message=message, **fields)), flush=True)

def fetch(url, limit):
    if not url.startswith('https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/'):
        raise UpdateError('Release URL is outside the official repository')
    start=time.monotonic()
    try:
        with urlopen(Request(url,headers={'User-Agent':'BIZON-Tabs-Updater/1','Cache-Control':'no-cache'}),timeout=20) as r:
            if not r.url.startswith(('https://github.com/','https://release-assets.githubusercontent.com/','https://objects.githubusercontent.com/')):
                raise UpdateError('Unexpected download destination')
            chunks=[]; total=0
            while True:
                chunk=r.read(min(65536,limit+1-total))
                if not chunk:break
                total+=len(chunk)
                if total>limit or time.monotonic()-start>120:raise UpdateError('Download exceeds size or time limit')
                chunks.append(chunk)
            return b''.join(chunks)
    except HTTPError as e:
        if e.code==404:raise UpdateError('No signed BIZON release is published yet. Installed tabs were not changed.') from e
        raise UpdateError('Release server returned HTTP '+str(e.code)) from e

def metadata(raw, signature, key):
    with tempfile.TemporaryDirectory(prefix='bizon-verify-') as tmp:
        p=Path(tmp);(p/'manifest').write_bytes(raw);(p/'sig').write_bytes(signature)
        result=subprocess.run(['/usr/bin/openssl','dgst','-sha256','-verify',str(key),'-signature',str(p/'sig'),str(p/'manifest')],capture_output=True)
        if result.returncode:raise UpdateError('Release signature is invalid; no changes were made')
    try:m=json.loads(raw)
    except ValueError as e:raise UpdateError('Invalid release manifest') from e
    if m.get('schema')!=1 or m.get('product')!='bizon-cockpit-tabs':raise UpdateError('Wrong release product or schema')
    if type(m.get('sequence')) is not int or m['sequence']<1:raise UpdateError('Invalid release sequence')
    if not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]{0,63}',m.get('version','')):raise UpdateError('Invalid version')
    if not re.fullmatch('[a-f0-9]{64}',m.get('sha256','')):raise UpdateError('Invalid archive digest')
    if type(m.get('size')) is not int or not 0<m['size']<=MAX_ARCHIVE:raise UpdateError('Invalid archive size')
    if sorted(m.get('tabs',[]))!=sorted(TABS):raise UpdateError('Release does not contain the required tabs')
    if not m.get('url','').startswith('https://github.com/Gimel12/bizon_cockpit_tabs_2026/releases/download/'):
        raise UpdateError('Invalid archive URL')
    return m

def release_metadata(url, key):
    raw=fetch(url,65536)
    # The latest alias can move between requests or have differently cached
    # assets. Use only a restricted version hint to locate this manifest's
    # signature; no manifest data is trusted until metadata verifies its bytes.
    try:hint=json.loads(raw)
    except ValueError as e:raise UpdateError('Invalid release manifest') from e
    version=hint.get('version') if isinstance(hint,dict) else None
    if not isinstance(version,str) or not re.fullmatch(r'[0-9A-Za-z][0-9A-Za-z._-]{0,63}',version):
        raise UpdateError('Invalid release version hint')
    signature=fetch(RELEASE_DOWNLOAD+version+'/manifest.json.sig',2048)
    return metadata(raw,signature,key)

def unpack(blob,m,dest):
    if len(blob)!=m['size'] or hashlib.sha256(blob).hexdigest()!=m['sha256']:raise UpdateError('Release checksum mismatch')
    import io
    with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as archive:
        seen=set(); total=0; members=archive.getmembers()
        if len(members)>20000:raise UpdateError('Too many archive entries')
        for item in members:
            name=PurePosixPath(item.name)
            if name.is_absolute() or '..' in name.parts or not name.parts or name.parts[0] not in TABS:
                raise UpdateError('Unsafe archive path')
            if str(name) in seen:raise UpdateError('Duplicate archive path')
            seen.add(str(name));total+=item.size
            if not (item.isfile() or item.isdir()) or item.mode & 0o7000 or total>250*1024*1024:
                raise UpdateError('Unsupported archive entry or size')
            if any(x in ('.git','__pycache__') for x in name.parts):raise UpdateError('Development files in release')
        for item in members:
            p=dest/str(PurePosixPath(item.name))
            if item.isdir():p.mkdir(parents=True,exist_ok=True);p.chmod(0o755)
            else:
                p.parent.mkdir(parents=True,exist_ok=True)
                with archive.extractfile(item) as src,p.open('wb') as out:shutil.copyfileobj(src,out)
                p.chmod(0o755 if item.mode & 0o111 else 0o644)
    for tab in TABS:
        p=dest/tab
        try:manifest=json.loads((p/'manifest.json').read_text())
        except (OSError,ValueError) as e:raise UpdateError('Missing or invalid tab manifest: '+tab) from e
        for tool in manifest.get('tools',{}).values():
            page=PurePosixPath(tool.get('path',''))
            if page.is_absolute() or '..' in page.parts or not (p/str(page)).is_file():raise UpdateError('Missing tab entry page: '+tab)
    # Syntax-check owned Python/JSON/HTML entry points without importing or executing release code.
    for p in dest.rglob('*.py'):
        try:compile(p.read_bytes(),str(p),'exec')
        except (SyntaxError,ValueError) as e:raise UpdateError('Invalid Python in release: '+str(p.relative_to(dest))) from e
    (dest/'release.json').write_text(json.dumps(m,indent=2)+'\n')
    (dest/'release.json').chmod(0o644)
    dest.chmod(0o755)
    for folder in dest.rglob('*'):
        if folder.is_dir():folder.chmod(0o755)

def read_current(store=STORE):
    try:return json.loads((store/'current/release.json').read_text())
    except FileNotFoundError:return {'version':'6.1-security-20261104','sequence':0}

def atomic_link(target,path):
    temp=path.with_name(path.name+'.new')
    temp.unlink(missing_ok=True);temp.symlink_to(target);os.replace(temp,path)

def install(blob,m,store=STORE):
    store.mkdir(parents=True,exist_ok=True,mode=0o755)
    store.chmod(0o755)
    (store/'releases').mkdir(exist_ok=True)
    (store/'releases').chmod(0o755)
    current=read_current(store)
    highest=int((store/'highest-sequence').read_text()) if (store/'highest-sequence').exists() else current['sequence']
    target=store/'releases'/str(m['sequence'])
    reactivate = m['sequence']==highest and m['sequence']>current['sequence'] and target.is_dir()
    if m['sequence']<=highest and not reactivate:raise UpdateError('Release is not newer than the installed release history')
    if reactivate and json.loads((target/'release.json').read_text())!=m:raise UpdateError('Stored release metadata mismatch')
    if target.exists() and not reactivate:raise UpdateError('Release directory already exists')
    staging=Path(tempfile.mkdtemp(prefix='.stage-',dir=store))
    try:
        unpack(blob,m,staging)
        if not reactivate:os.rename(staging,target)
        old=os.readlink(store/'current') if (store/'current').is_symlink() else None
        if old:atomic_link(old,store/'previous')
        # Commit the anti-rollback floor first. A crash can skip a release, never replay it.
        h=store/'highest-sequence.new';h.write_text(str(m['sequence'])+'\n');h.chmod(0o644);os.replace(h,store/'highest-sequence')
        atomic_link('releases/'+str(m['sequence']),store/'current')
    finally:
        if staging.exists():shutil.rmtree(staging)
    return m

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--action',choices=('version','check','update','rollback'),default='version');a=parser.parse_args()
    if a.action=='version':emit('Installed release',**read_current());return
    if a.action in ('update','rollback') and os.geteuid()!=0:raise UpdateError('Administrator access is required to change installed tabs')
    lock=None
    if a.action in ('update','rollback'):
        lock=open('/run/lock/bizon-tabs-update.lock','a')
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise UpdateError('Another tab update is running')
    if a.action=='rollback':
        prev=STORE/'previous'
        if not prev.is_symlink():raise UpdateError('No previous release is available')
        target=os.readlink(prev)
        if not (STORE/target/'release.json').is_file():raise UpdateError('Previous release is missing')
        old=os.readlink(STORE/'current');atomic_link(target,STORE/'current');atomic_link(old,prev)
        emit('Previous release restored. Reload Cockpit.',success=True,**read_current());return
    cfg=json.loads((CONFIG/'source.json').read_text());url=cfg['manifest_url']
    emit('Checking the official BIZON release channel…')
    m=release_metadata(url,CONFIG/'release-public.pem')
    current=read_current()
    if m['sequence']<current['sequence']:raise UpdateError('Published release is older than the installed release; no changes made')
    available=m['sequence']>current['sequence']
    if a.action=='check' or not available:
        emit('Update available' if available else 'Installed tabs match the latest published release',local=current['version'],remote=m['version'],update_available=available);return
    emit('Downloading and verifying release '+m['version']+'…')
    blob=fetch(m['url'],MAX_ARCHIVE)
    install(blob,m)
    emit('Update installed. Reload Cockpit to use the new tabs.',success=True,**m)
if __name__=='__main__':
    try:main()
    except Exception as e:
        emit(str(e),success=False);sys.exit(1)
