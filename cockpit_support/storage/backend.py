#!/usr/bin/python3 -I
"""BIZON storage operations over Cockpit's privileged process channel. No HTTP listener."""
import datetime, concurrent.futures, contextlib, fcntl, hashlib, html, json, os, re, shutil, signal, socket, stat, subprocess, sys, time, uuid
from pathlib import Path

STATE = Path('/var/lib/bizon-storage')
PROFILES = {'seq-read': ('read','1M'), 'random-read': ('randread','4k'), 'seq-write': ('write','1M'), 'mixed': ('randrw','4k')}
LEVELS = {'0':2,'1':2,'5':3,'6':4,'10':4}
TOOLS = {'fio':'/usr/bin/fio','smartctl':'/usr/sbin/smartctl','mdadm':'/usr/sbin/mdadm'}
class StorageError(Exception): pass

def run(args, timeout=30, check=True):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout, env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'}, stdin=subprocess.DEVNULL)
    if check and p.returncode: raise StorageError((p.stderr or p.stdout or 'Command failed')[-2500:].strip())
    return p

def save(path, data):
    tmp=path.with_suffix('.new');tmp.write_text(json.dumps(data,indent=2));tmp.chmod(0o600);os.replace(tmp,path)

def setup():
    if os.geteuid()!=0: raise StorageError('Enable administrative access in Cockpit to use storage tools.')
    STATE.mkdir(mode=0o700,exist_ok=True)
    if STATE.is_symlink() or STATE.stat().st_uid!=0 or STATE.stat().st_mode & 0o022: raise StorageError('Unsafe storage state directory')
    for n in ['jobs','plans']: (STATE/n).mkdir(mode=0o700,exist_ok=True)

@contextlib.contextmanager
def lock():
    with (STATE/'operation.lock').open('a') as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise StorageError('Another storage operation is active. Stop it or wait for completion.')
        yield

def ident(value):
    if not isinstance(value,str) or not re.fullmatch('[a-f0-9]{32}',value): raise StorageError('Invalid operation identifier')
    return value

def boot_id(): return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
def walk(nodes):
    for d in nodes:
        yield d
        yield from walk(d.get('children',[]))

def tree():
    return json.loads(run(['/usr/bin/lsblk','-J','-b','-o','NAME,KNAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,UUID,FSTYPE,MOUNTPOINTS,RO,TRAN,MAJ:MIN']).stdout)['blockdevices']

# Protect the complete block graph, including every member of a system RAID/LVM
# stack and other partitions sharing a system disk. Never infer this from names.
def system_sources():
    sources={}
    for target in ['/', '/boot', '/boot/efi', '/usr', '/var', '/etc', '/opt', '/home']:
        if os.path.exists(target):
            dev=os.stat(target).st_dev
            sources[target]=f'{os.major(dev)}:{os.minor(dev)}'
    for line in Path('/proc/swaps').read_text().splitlines()[1:]:
        name=line.split()[0].replace('\\040',' ')
        st=os.stat(name);dev=st.st_rdev if stat.S_ISBLK(st.st_mode) else st.st_dev
        sources['swap: '+name]=f'{os.major(dev)}:{os.minor(dev)}'
    return sources

def system_guard(nodes=None, sources=None):
    nodes=tree() if nodes is None else nodes
    sources=system_sources() if sources is None else sources
    graph={};paths={};uuids={}
    def visit(items,parent=None):
        for d in items:
            key=d.get('maj:min')
            if not key: continue
            graph.setdefault(key,set());paths[d['path']]=key
            if parent: graph[key].add(parent);graph[parent].add(key)
            if d.get('uuid'):
                other=uuids.setdefault(d['uuid'],key)
                graph[key].add(other);graph[other].add(key)
            visit(d.get('children',[]),key)
    visit(nodes)
    sources=dict(sources)
    for d in walk(nodes):
        for mount in d.get('mountpoints',[]) or []:
            if mount=='[SWAP]' or (mount and any(mount==base or mount.startswith(base+'/') for base in ['/boot','/usr','/var','/etc','/opt','/home'])):
                sources[mount if mount!='[SWAP]' else 'swap: '+d['path']]=d.get('maj:min')
    # A virtual, remote or unrecognised system filesystem must not silently
    # disable protection. Inventory still works; all workload starts fail closed.
    unresolved=[role for role,key in sources.items() if key not in graph]
    if '/' not in sources: unresolved.append('/')
    reason=('System storage could not be fully identified ('+', '.join(unresolved)+'). Tests are disabled.') if unresolved else None
    roles={}
    for role,key in sources.items():
        pending=[key];seen=set()
        while pending:
            current=pending.pop()
            if current in seen: continue
            seen.add(current);roles.setdefault(current,set()).add(role)
            pending.extend(graph.get(current,()))
    return {path:sorted(roles.get(key,())) for path,key in paths.items()},reason

def require_testable(devices, nodes=None):
    protected,reason=system_guard(nodes)
    if reason: raise StorageError(reason)
    for d in devices:
        if d['path'] not in protected: raise StorageError('Drive topology changed; refresh and try again.')
        if protected.get(d['path']):
            raise StorageError(d['path']+': OS / system drive protected. Read and write tests are disabled; SMART inspection remains available.')

ERROR_FIELDS = {
    'media_errors':'Media / data integrity errors', 'error_log_entries':'NVMe error log entries',
    'reallocated_sectors':'Reallocated sectors', 'pending_sectors':'Pending sectors',
    'uncorrectable_sectors':'Uncorrectable sectors', 'crc_errors':'Interface CRC errors',
    'scsi_read_errors':'SCSI uncorrected read errors', 'scsi_write_errors':'SCSI uncorrected write errors',
}

def record_health(data, health, elapsed, phase):
    snapshot={path:{k:v for k,v in h.items() if k!='raw'} for path,h in health.items()}
    data.setdefault('health_samples',[]).append({'elapsed':round(elapsed,1),'phase':phase,'drives':snapshot})
    data.setdefault('temperature_samples',[]).append({'elapsed':round(elapsed,1),'temperatures':{path:h.get('temperature') for path,h in health.items()}})

def error_changes(before, after):
    return {k:after[k]-before[k] for k in ERROR_FIELDS if type(before.get(k)) in (int,float) and type(after.get(k)) in (int,float)}

def laboratory(d):
    if d['type']!='loop' or d.get('ro'): return False
    try:
        file=Path((Path('/sys/class/block')/d['kname']/'loop/backing_file').read_text().strip())
        return file.resolve().parent==STATE/'lab' and file.stat().st_uid==0 and not file.stat().st_mode & 0o022
    except OSError: return False

def supported(d): return d['type']=='disk' or d['type'].startswith('raid') or laboratory(d)
def mounts(d): return sorted({p for n in walk([d]) for p in n.get('mountpoints',[]) if p})
def holders(d): return [p.name for p in (Path('/sys/class/block')/d['kname']/'holders').iterdir()]
def signatures(d): return json.loads(run(['/usr/sbin/wipefs','--json','--no-act',d['path']]).stdout).get('signatures',[])
def fingerprint(d):
    result={k:d.get(k) for k in ['path','maj:min','size','serial','wwn','type']}
    diskseq=Path('/sys/class/block')/d['kname']/'diskseq'
    if diskseq.exists():result['diskseq']=diskseq.read_text().strip()
    return result

def find(path, nodes=None):
    for d in walk(tree() if nodes is None else nodes):
        if d['path']==path and supported(d): return d
    raise StorageError('Drive is unavailable; refresh the list.')

def available(d):
    reasons=[]
    if d.get('ro'): reasons.append('Read-only device')
    if mounts(d): reasons.append('Mounted or active swap')
    if d.get('children'): reasons.append('Contains partitions or another storage layer')
    if holders(d): reasons.append('Used by an array, encryption or volume manager')
    if signatures(d): reasons.append('Existing filesystem, partition table or RAID metadata')
    if d['type']!='disk' and not laboratory(d): reasons.append('Not an unused whole drive')
    return reasons

def smart(path):
    if not Path(TOOLS['smartctl']).exists(): return {'status':'unavailable','messages':['Install smartmontools to read drive health.']}
    try:p=run([TOOLS['smartctl'],'-a','-j',path],check=False,timeout=10)
    except (OSError,subprocess.TimeoutExpired) as e:return {'status':'unavailable','messages':[str(e)]}
    try: data=json.loads(p.stdout)
    except ValueError: return {'status':'unavailable','messages':[p.stderr.strip() or 'No SMART data returned']}
    nv=data.get('nvme_smart_health_information_log',{});attrs=data.get('ata_smart_attributes',{}).get('table',[])
    counters={str(a['id']):a.get('raw',{}).get('value') for a in attrs}
    alerts=[]
    if data.get('smart_status',{}).get('passed') is False: alerts.append('SMART health check failed')
    if nv.get('critical_warning',0): alerts.append('NVMe critical warning')
    for name,value in [('media_errors',nv.get('media_errors')),('reallocated_sectors',counters.get('5')),('pending_sectors',counters.get('197')),('uncorrectable_sectors',counters.get('198'))]:
        if value: alerts.append(name+': '+str(value))
    # smartctl exit bits 0-2 mean unavailable/incomplete commands, not a healthy disk.
    if p.returncode & 0xF8: alerts.append('SMART reports health/error/self-test history flags; inspect details')
    status='unavailable'
    if alerts:status='warning'
    elif data.get('smart_status',{}).get('passed') is True and not p.returncode & 3:
        status='partial' if p.returncode & 4 else 'passed'
    return {'status':status,'alerts':alerts,'temperature':data.get('temperature',{}).get('current',nv.get('temperature')),'power_on_hours':data.get('power_on_time',{}).get('hours',nv.get('power_on_hours')),'percentage_used':nv.get('percentage_used'),'media_errors':nv.get('media_errors'),'error_log_entries':nv.get('num_err_log_entries'),'unsafe_shutdowns':nv.get('unsafe_shutdowns'),'reallocated_sectors':counters.get('5'),'pending_sectors':counters.get('197'),'uncorrectable_sectors':counters.get('198'),'crc_errors':counters.get('199'),'scsi_read_errors':data.get('scsi_error_counter_log',{}).get('read',{}).get('total_uncorrected_errors'),'scsi_write_errors':data.get('scsi_error_counter_log',{}).get('write',{}).get('total_uncorrected_errors'),'firmware':data.get('firmware_version'),'messages':[m.get('string','') for m in data.get('smartctl',{}).get('messages',[])],'raw':data}

def array_info(d):
    base=Path('/sys/class/block')/d['kname']/'md'
    def read(n):
        try: return (base/n).read_text().strip()
        except OSError: return None
    members=[]
    for dev in sorted(base.glob('dev-*')):
        try:
            name=(dev/'block').resolve().name
            members.append({'path':'/dev/'+name,'state':(dev/'state').read_text().strip()})
        except OSError: pass
    return {'path':d['path'],'name':d['kname'],'uuid':read('uuid'),'level':read('level'),'state':read('array_state'),'degraded':read('degraded'),'sync_action':read('sync_action'),'sync_completed':read('sync_completed'),'mismatch_count':read('mismatch_cnt'),'members':members,'mountpoints':mounts(d),'size':d['size']}

def inventory(include_smart=True):
    nodes=tree();found={d['path']:d for d in walk(nodes) if supported(d)}
    protected,protection_error=system_guard(nodes)
    health={}
    if include_smart:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            health=dict(zip(found,pool.map(smart,found)))
    devices=[];arrays=[]
    for path,d in found.items():
        item={**fingerprint(d),'name':d['kname'],'model':d.get('model'),'transport':d.get('tran'),'mountpoints':mounts(d),'reasons':available(d),'health':health.get(path)}
        item.update(is_os=bool(protected.get(path)),system_roles=protected.get(path,[]),test_allowed=not (protected.get(path) or protection_error),test_block_reason=protection_error or ('OS / system drive: read and write tests disabled' if protected.get(path) else None))
        item['available']=not item['reasons'] and item['test_allowed'];devices.append(item)
        if d['type'].startswith('raid'): arrays.append(array_info(d))
    return {'devices':devices,'arrays':arrays,'tools':{k:Path(v).exists() for k,v in TOOLS.items()},'host':socket.gethostname(),'time':time.time()}

def selected(paths):
    if not isinstance(paths,list) or not 1<=len(paths)<=16 or any(not isinstance(x,str) for x in paths) or len(set(paths))!=len(paths): raise StorageError('Select between 1 and 16 different drives.')
    nodes=tree();return [find(p,nodes) for p in paths]

def validate_test(req):
    ds=selected(req.get('devices'));profile=req.get('profile','seq-read')
    if profile not in PROFILES: raise StorageError('Unknown workload')
    duration=req.get('duration',60);depth=req.get('depth',16);size=req.get('size_gib',1)
    if type(duration)!=int or not 10<=duration<=3600: raise StorageError('Duration must be 10–3600 seconds.')
    if depth not in [1,4,16,32,64]: raise StorageError('Invalid queue depth')
    if type(size)!=int or not 1<=size<=64: raise StorageError('Test file size must be 1–64 GiB.')
    if not Path(TOOLS['fio']).exists(): raise StorageError('fio is not installed. Install the storage tools first.')
    require_testable(ds)
    write=profile in ['seq-write','mixed'];targets=[]
    for d in ds:
        target={'drive':fingerprint(d),'model':d.get('model'),'name':d.get('kname'),'transport':d.get('tran'),'path':d['path']}
        if write:
            m=req.get('mounts',{}).get(d['path'])
            # Use only a filesystem directly on the selected drive/array or its partitions.
            parts=list(walk([d]));mountdev=next((n for n in parts if m and m in n.get('mountpoints',[]) and n.get('fstype') in ['ext4','xfs','btrfs']),None)
            if not mountdev or not m.startswith(('/mnt/','/media/','/srv/')): raise StorageError('Write tests need a mounted data filesystem under /mnt, /media or /srv. System filesystems are protected.')
            if str(Path(m).resolve())!=m or os.stat(m).st_dev!=os.stat(mountdev['path']).st_rdev: raise StorageError('Mount identity changed or is not a direct local filesystem.')
            free=shutil.disk_usage(m).free;requested=size*1024**3
            if free-requested<max(2*1024**3,shutil.disk_usage(m).total//10): raise StorageError('Insufficient free space: keep at least 10% and 2 GiB free.')
            target.update(mount=m,mount_device=mountdev['path'],mount_id=os.stat(m).st_dev)
        targets.append(target)
    if write and len({t['mount_id'] for t in targets})!=len(targets): raise StorageError('Select each filesystem only once.')
    return {'devices':targets,'profile':profile,'duration':duration,'depth':depth,'size_gib':size,'customer':str(req.get('customer',''))[:160],'reference':str(req.get('reference',''))[:160]}

def job_path(jid): return STATE/'jobs'/ident(jid)
def read_job(jid):
    p=job_path(jid);data=json.loads((p/'state.json').read_text())
    if data['status'] in ['queued','running']:
        unit='bizon-storage-'+jid+'.service'
        active=run(['/usr/bin/systemctl','is-active',unit],check=False).stdout.strip()
        if data.get('boot_id')!=boot_id() or active not in ['active','activating']:
            if time.time()-data['created']>10:
                data.update(status='interrupted',error='Worker stopped or the machine restarted; this is not a passing test.',finished=time.time())
                leftovers=[str(Path(t['mount'])/('.bizon-test-'+jid)) for t in data['config']['devices'] if 'mount' in t]
                if leftovers:data['cleanup_warnings']=['Interrupted write test: inspect temporary directories before removal: '+', '.join(leftovers)]
                save(p/'state.json',data)
    return data

def check_idle():
    for p in (STATE/'jobs').glob('*/state.json'):
        data=read_job(p.parent.name)
        if data['status'] in ['queued','running']: raise StorageError('A storage test is already active. Stop it or wait before changing storage.')

def start_test(req):
    with lock():
        check_idle();config=validate_test(req);jid=uuid.uuid4().hex;p=job_path(jid);p.mkdir(mode=0o700)
        data={'id':jid,'status':'queued','created':time.time(),'boot_id':boot_id(),'host':socket.gethostname(),'config':config,'samples':[],'results':[]}
        save(p/'state.json',data)
        try:
            run(['/usr/bin/systemd-run','--quiet','--collect','--unit=bizon-storage-'+jid,'--property=Type=exec','--property=KillMode=mixed','--property=TimeoutStopSec=20','--property=RuntimeMaxSec='+str(config['duration']+180),'--property=UMask=0077','--property=Nice=5','--property=MemoryHigh=15%','--property=MemoryMax=25%','/usr/bin/python3','-I',str(Path(__file__).resolve()),'worker',jid])
        except Exception:
            data['status']='failed';save(p/'state.json',data);raise
        return data

def json_records(text):
    decoder=json.JSONDecoder();last={};offset=0
    while offset<len(text):
        while offset<len(text) and text[offset].isspace():offset+=1
        try:obj,end=decoder.raw_decode(text,offset)
        except ValueError:break
        last=obj;offset=end
    return last

def fio_record(path):
    if not path.exists():return {}
    with path.open('rb') as f:
        f.seek(0,2);size=f.tell();f.seek(max(0,size-262144));text=f.read().decode('utf-8',errors='replace')
    if size>262144:
        start=text.find('\n{')
        if start<0:return {}
        text=text[start+1:]
    return json_records(text)

def health_many(paths):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:return dict(zip(paths,pool.map(smart,paths)))

def metrics(raw):
    out=[]
    for j in raw.get('jobs',[]):
        r={'name':j.get('jobname'),'error':j.get('error',0)}
        for mode in ['read','write']:
            v=j.get(mode,{});lat=v.get('clat_ns',{})
            r[mode]={'mib_s':v.get('bw_bytes',v.get('bw',0)*1024)/1024**2,'iops':v.get('iops',0),'bytes':v.get('io_bytes',0),'latency_mean_ms':lat.get('mean',0)/1e6,'latency_p99_ms':lat.get('percentile',{}).get('99.000000',0)/1e6}
        out.append(r)
    return out

def worker(jid):
    p=job_path(jid);data=json.loads((p/'state.json').read_text());config=data['config'];children=[];files=[];fds=[];cancelled=False
    def stop(sig,frame):
        nonlocal cancelled
        cancelled=True
        for proc,_,_ in children:
            if proc.poll() is None: proc.send_signal(signal.SIGINT)
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:
        require_testable([find(x['path']) for x in config['devices']])
        data.update(status='running',started=time.time());data['before']=health_many([x['path'] for x in config['devices']]);record_health(data,data['before'],0,'before');save(p/'state.json',data)
        rw,bs=PROFILES[config['profile']]
        for i,t in enumerate(config['devices']):
            if cancelled: break
            d=find(t['path']);require_testable([d])
            if fingerprint(d)!=t['drive']: raise StorageError('Drive identity changed before test launch.')
            rawfd=os.open(t['path'],os.O_RDONLY|os.O_CLOEXEC);fds.append(rawfd)
            filename='/proc/self/fd/'+str(rawfd);size=min(d['size']//2,config['size_gib']*1024**3)//4096*4096
            if 'mount' in t:
                # New private directory; never reuse or delete an existing user file.
                validate_test({'devices':[t['path']],'profile':config['profile'],'duration':config['duration'],'depth':config['depth'],'size_gib':config['size_gib'],'mounts':{t['path']:t['mount']}})
                folder=Path(t['mount'])/('.bizon-test-'+jid)
                folder.mkdir(mode=0o700);dirfd=os.open(folder,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);fds.append(dirfd);files.append((folder,dirfd));filename='/proc/self/fd/'+str(dirfd)+'/test.bin';size=config['size_gib']*1024**3
                fd=os.open('test.bin',os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600,dir_fd=dirfd)
                try:os.posix_fallocate(fd,0,size)
                finally:os.close(fd)
            out=p/(str(i)+'.json');log=(p/(str(i)+'.log')).open('w')
            cmd=[TOOLS['fio'],'--name='+str(i),'--filename='+filename,'--rw='+rw,'--bs='+bs,'--ioengine=libaio','--direct=1','--iodepth='+str(config['depth']),'--size='+str(size),'--time_based=1','--runtime='+str(config['duration']),'--ramp_time=2','--randrepeat=0','--group_reporting=1','--output-format=json','--status-interval=2','--output='+str(out),'--write_bw_log='+str(p/str(i)),'--log_avg_msec=1000','--rwmixread=70']
            if 'mount' not in t: cmd.append('--readonly')
            proc=subprocess.Popen(cmd,stdout=log,stderr=log,pass_fds=tuple(fds),env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin','LC_ALL':'C'});children.append((proc,out,log))
        while any(proc.poll() is None for proc,_,_ in children):
            elapsed=round(time.time()-data['started'],1)
            samples=data.get('samples') or [{'path':t['path'],'bandwidth':[]} for t in config['devices']]
            live=[]
            for i,(proc,out,log) in enumerate(children):
                raw=fio_record(out)
                mm=metrics(raw)
                if mm:
                    samples[i]['bandwidth'].append([elapsed,sum(m['read']['mib_s']+m['write']['mib_s'] for m in mm)])
                    live.append({'path':config['devices'][i]['path'],'metrics':mm})
            if not data.get('temperature_samples') or elapsed-data['temperature_samples'][-1]['elapsed']>=10:
                hs=health_many([x['path'] for x in config['devices']]);record_health(data,hs,elapsed,'during')
            data['samples']=samples;data['results']=live;data['elapsed']=elapsed
            save(p/'state.json',data);time.sleep(1)
        errors=[];data['results']=[]
        for i,(proc,out,log) in enumerate(children):
            log.close()
            try:
                raw=fio_record(out);result=metrics(raw)
                if not result:raise ValueError('No complete fio record')
                if (proc.returncode and not cancelled) or any(j['error'] for j in result): errors.append('fio reported an I/O error on '+config['devices'][i]['path'])
                data['results'].append({'path':config['devices'][i]['path'],'metrics':result})
            except (OSError,ValueError): errors.append('Incomplete fio results for '+config['devices'][i]['path'])
        data['after']=health_many([x['path'] for x in config['devices']]);record_health(data,data['after'],time.time()-data['started'],'after')
        data['status']='cancelled' if cancelled else ('failed' if errors else 'completed');data['errors']=errors
        data['health_warnings']=sorted({path for sample in data.get('health_samples',[]) for path,h in sample['drives'].items() if h.get('status')=='warning' or any(v>0 for v in error_changes(data['before'].get(path,{}),h).values())})
    except Exception as e:
        data.update(status='cancelled' if cancelled else 'failed',error=str(e))
    finally:
        for proc,_,log in children:
            if proc.poll() is None:
                proc.send_signal(signal.SIGINT)
                try: proc.wait(timeout=8)
                except subprocess.TimeoutExpired: proc.kill();proc.wait()
            if not log.closed:log.close()
        if data.get('before') and not data.get('after'):
            try:
                data['after']=health_many([x['path'] for x in config['devices']])
                record_health(data,data['after'],time.time()-data['started'],'after')
            except Exception as e:
                data.setdefault('cleanup_warnings',[]).append('Final SMART snapshot unavailable: '+str(e))
        data['health_warnings']=sorted({path for sample in data.get('health_samples',[]) for path,h in sample['drives'].items() if h.get('status')=='warning' or any(v>0 for v in error_changes(data.get('before',{}).get(path,{}),h).values())})
        for folder,dirfd in files:
            try: os.unlink('test.bin',dir_fd=dirfd);folder.rmdir()
            except OSError as e: data.setdefault('cleanup_warnings',[]).append(str(e))
        for fd in fds:os.close(fd)
        data['finished']=time.time();save(p/'state.json',data)

def array_by_path(path):
    d=find(path)
    if not d['type'].startswith('raid'): raise StorageError('Select a Linux software RAID array.')
    return d,array_info(d)

def validate_array_change(path):
    d,a=array_by_path(path)
    if mounts(d) or holders(d) or d.get('children'): raise StorageError('Array is mounted, used as swap, partitioned or used by another storage layer. Unmount it in Storage first.')
    if a['sync_action'] not in [None,'idle']: raise StorageError('Wait for the array sync/check to finish first.')
    return d,a

def raid_plan(req):
    with lock():
        check_idle();action=req.get('action')
        if action=='create':
            ds=selected(req.get('devices'));level=str(req.get('level'));name=req.get('name','')
            if level not in LEVELS or len(ds)<LEVELS[level] or (level=='10' and len(ds)%2): raise StorageError('Insufficient or invalid drive count for this RAID level.')
            if not re.fullmatch('[a-zA-Z][a-zA-Z0-9_-]{0,23}',name): raise StorageError('Array name must start with a letter and contain at most 24 letters, numbers, hyphens or underscores.')
            if Path('/dev/md/'+name).exists(): raise StorageError('That array name already exists.')
            for d in ds:
                reasons=available(d)
                if reasons: raise StorageError(d['path']+': '+', '.join(reasons))
            config={'action':action,'name':name,'level':level,'devices':[fingerprint(d) for d in ds]}
            text='CREATE '+name
            capacity=min(d['size'] for d in ds)*({'0':len(ds),'1':1,'5':len(ds)-1,'6':len(ds)-2,'10':len(ds)//2}[level])
            detail={'capacity':capacity,'warning':'Creates RAID metadata on all selected drives. Only blank, unused whole drives are accepted. Format and mount the new array using Cockpit Storage afterwards. RAID is not a backup.'}
        elif action=='delete':
            d,a=validate_array_change(req.get('path'));config={'action':action,'array':a,'drive':fingerprint(d),'members':[fingerprint(n) for n in walk(tree()) if n['path'] in [m['path'] for m in a['members']]]};text='DELETE '+a['name'];detail={'warning':'Permanently removes RAID metadata from the listed members. All data on this array becomes inaccessible. The array must be unmounted first.'}
        else: raise StorageError('Unknown RAID action')
        token=uuid.uuid4().hex;plan={'token':token,'created':time.time(),'boot_id':boot_id(),'config':config,'confirmation':text,**detail};save(STATE/'plans'/(token+'.json'),plan);return plan

def persist_array(a,remove=False):
    # Data arrays auto-assemble by UUID; retain all unrelated system configuration.
    p=Path('/etc/mdadm/mdadm.conf');text=p.read_text() if p.exists() else ''
    marker='# BIZON-STORAGE '+a['uuid']
    lines=text.splitlines();new=[];skip=False
    for line in lines:
        if skip: skip=False;continue
        if line==marker:skip=True;continue
        new.append(line)
    if not remove:new.extend([marker,'ARRAY '+a['path']+' UUID='+a['uuid']])
    backup=STATE/('mdadm.conf.'+str(time.time_ns())+'.bak');backup.write_text(text);backup.chmod(0o600)
    tmp=p.with_name('mdadm.conf.bizon-new');tmp.write_text('\n'.join(new)+'\n');tmp.chmod(0o644);os.replace(tmp,p)

def raid_apply(req):
    with lock():
        check_idle();path=STATE/'plans'/(ident(req.get('token'))+'.json');plan=json.loads(path.read_text())
        if plan['boot_id']!=boot_id() or time.time()-plan['created']>300: raise StorageError('Plan expired; review the drives again.')
        if req.get('confirmation')!=plan['confirmation']: raise StorageError('Typed confirmation does not match.')
        path.unlink();config=plan['config'];audit={'time':time.time(),'plan':plan,'status':'started'};ap=STATE/('raid-'+plan['token']+'.json');save(ap,audit)
        try:
            if config['action']=='create':
                ds=selected([d['path'] for d in config['devices']])
                for d,expected in zip(ds,config['devices']):
                    if fingerprint(d)!=expected or available(d): raise StorageError('Drive identity or availability changed; review again.')
                name=config['name'];device='/dev/md/'+name
                if Path(device).exists(): raise StorageError('Array name is now in use.')
                run([TOOLS['mdadm'],'--create',device,'--metadata=1.2','--level='+config['level'],'--raid-devices='+str(len(ds)),'--name='+name,'--run',*[d['path'] for d in ds]],timeout=90)
                run(['/usr/bin/udevadm','settle'],timeout=20)
                d=find(str(Path(device).resolve()));a=array_info(d);persist_array(a)
                result={'message':'Array created. Initial synchronization may still be running. Use Cockpit Storage to format and mount it.','array':a}
            else:
                d,a=validate_array_change(config['array']['path'])
                if fingerprint(d)!=config['drive'] or a['uuid']!=config['array']['uuid'] or a['members']!=config['array']['members']: raise StorageError('Array identity or membership changed; review again.')
                current_members=[fingerprint(n) for n in walk(tree()) if n['path'] in [m['path'] for m in a['members']]]
                if current_members!=config['members']:raise StorageError('Array member identity changed; review again.')
                # Capture exact members, stop first, then clear only RAID superblocks. Never wipe filesystems.
                run([TOOLS['mdadm'],'--stop',d['path']]);failures=[]
                for member in a['members']:
                    r=run([TOOLS['mdadm'],'--zero-superblock',member['path']],check=False)
                    if r.returncode: failures.append(member['path']+': '+r.stderr.strip())
                persist_array(a,remove=True)
                if failures: raise StorageError('Array stopped, but metadata cleanup was incomplete: '+'; '.join(failures))
                result={'message':'Array stopped and RAID metadata removed.'}
            audit.update(status='completed',result=result);save(ap,audit);return result
        except Exception as e:
            audit.update(status='failed',error=str(e));save(ap,audit);raise

def raid_check(req):
    with lock():
        check_idle();d,a=array_by_path(req.get('path'));require_testable([d])
        if a['level']=='raid0': raise StorageError('RAID 0 has no redundant data to check. Use a read test.')
        if a['sync_action']!='idle': raise StorageError('A sync/check is already running.')
        (Path('/sys/class/block')/d['kname']/'md/sync_action').write_text('check')
        return {'message':'Consistency check started. Check progress and mismatch count in the array card. No automatic repair requested.'}

def report(data):
    esc=lambda x:html.escape(str(x if x is not None else 'Not reported'))
    def number(v,suffix=''):
        return esc(round(v,2))+suffix if type(v) in (int,float) else 'Not reported'
    def date(v):
        return datetime.datetime.fromtimestamp(v,datetime.timezone.utc).strftime('%d %b %Y · %H:%M:%S UTC') if isinstance(v,(int,float)) else 'Not recorded'
    def table(headers,rows):
        return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+esc(v)+'</th>' for v in headers)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+str(v)+'</td>' for v in row)+'</tr>' for row in rows)+'</tbody></table></div>'
    def details(items):
        return '<dl>'+''.join('<div><dt>'+esc(k)+'</dt><dd>'+esc(v)+'</dd></div>' for k,v in items)+'</dl>'
    config=data['config'];sections=[];warnings=[]
    for drive_number,t in enumerate(config['devices'],1):
        path=t['path'];before=data.get('before',{}).get(path,{}) or {};after=data.get('after',{}).get(path,{}) or {};h=after or before
        readings=[(s.get('elapsed',0),s['drives'][path]) for s in data.get('health_samples',[]) if path in s.get('drives',{})]
        temps=[(s.get('elapsed',0),s.get('temperatures',{}).get(path)) for s in data.get('temperature_samples',[]) if type(s.get('temperatures',{}).get(path)) in (int,float)]
        if not temps:
            temps=[(0,before.get('temperature')),(data.get('elapsed',config['duration']),after.get('temperature'))]
            temps=[(x,y) for x,y in temps if type(y) in (int,float)]
        alerts=sorted({a for _,r in readings+[(0,before),(0,after)] for a in r.get('alerts',[])})
        increases={k:max([0]+[r.get(k,0)-before[k] for _,r in readings+[(0,after)] if type(r.get(k)) in (int,float)]) for k in ERROR_FIELDS if type(before.get(k)) in (int,float)}
        if alerts or any(v>0 for v in increases.values()):warnings.append(path)
        sections.append('<section><div class="eyebrow">DRIVE '+str(drive_number)+'</div><h2>'+esc(t.get('model') or t.get('name') or path)+'</h2>'+details([
            ('Device / name',path+' / '+str(t.get('name') or path.rsplit('/',1)[-1])),('Serial number',t['drive'].get('serial')),('Capacity',str(round(t['drive'].get('size',0)/1e9,2))+' GB'),('Interface',t.get('transport') or h.get('raw',{}).get('device',{}).get('protocol') or t['drive'].get('type')),('WWN',t['drive'].get('wwn')),('Firmware',h.get('firmware'))]))
        sections.append('<h3>Health at a glance</h3>'+details([('SMART before',before.get('status')),('SMART after',after.get('status')),('Temperature before',number(before.get('temperature'),' °C')),('Temperature after',number(after.get('temperature'),' °C')),('Peak recorded',number(max([y for _,y in temps]),' °C') if temps else 'Not reported'),('Power-on hours',h.get('power_on_hours')),('Endurance used',number(h.get('percentage_used'),'%')),('Unsafe shutdowns',h.get('unsafe_shutdowns'))]))
        if alerts:sections.append('<p class="warning">'+esc('; '.join(alerts))+'</p>')
        if h.get('status') not in ['passed','warning']:sections.append('<p class="note">SMART data is partial or unavailable. This report does not certify drive health.</p>')
        sections.append('<h3>Measured performance</h3>')
        result=next((r for r in data.get('results',[]) if r['path']==path),{})
        rows=[]
        for j in result.get('metrics',[]):
            for mode in ['read','write']:
                v=j.get(mode,{})
                rows.append([esc(mode.title())]+[number(v.get(k)) for k in ['mib_s','iops','latency_mean_ms','latency_p99_ms']]+[esc(j.get('error'))])
        sections.append(table(['Workload','MiB/s','IOPS','Mean latency (ms)','P99 latency (ms)','I/O error code'],rows) if rows else '<p>No completed performance measurement was recorded.</p>')
        sections.append('<h3>Temperature during the test</h3>')
        if temps:
            xmax=max(1,max(x for x,_ in temps));low=min(y for _,y in temps)-2;high=max(y for _,y in temps)+2
            points=' '.join(f'{48+x/xmax*690:.1f},{145-(y-low)/(high-low)*115:.1f}' for x,y in temps)
            sections.append('<svg viewBox="0 0 800 180" role="img" aria-label="Recorded drive temperature in degrees Celsius"><path d="M48 25V145H750" fill="none" stroke="#b9c8d9"/><text x="2" y="30">'+number(high)+' °C</text><text x="2" y="148">'+number(low)+' °C</text><text x="48" y="170">0 s</text><text x="680" y="170">'+number(xmax)+' s</text><polyline fill="none" stroke="#087cbe" stroke-width="3" points="'+points+'"/></svg>')
        else:sections.append('<p>Temperature was not reported by this device or controller.</p>')
        sections.append('<p class="note">Snapshots are captured before, about every 10 seconds during, and after the workload. Short temperature spikes between samples may not be captured.</p><h3>Errors before and after</h3>')
        rows=[]
        for key,label in ERROR_FIELDS.items():
            a=before.get(key);b=after.get(key);delta=error_changes(before,after).get(key)
            if a is None and b is None and not any(r.get(key) is not None for _,r in readings): continue
            change=('+' if delta and delta>0 else '')+str(delta) if delta is not None else 'Not comparable'
            if delta is not None and delta<0:change+=' (counter reset / changed)'
            rows.append([esc(label),number(a),number(b),esc(change),number(increases.get(key))])
        sections.append(table(['Counter','Before','After','Change','Largest recorded increase'],rows) if rows else '<p>No supported error counters were reported by this device or controller.</p>')
        sections.append('<p class="note">Counters are lifetime totals; increases during this test are shown separately. Error log entries can include command errors, not only media failures. Missing counters are not treated as zero.</p>')
        rows=[]
        for elapsed,r in readings:
            changes=error_changes(before,r)
            raised=[ERROR_FIELDS[k]+': +'+str(v) for k,v in changes.items() if v>0]
            rows.append([number(elapsed,' s'),number(r.get('temperature'),' °C'),esc(r.get('status')),esc('; '.join(raised+r.get('alerts',[])) or 'No increase in comparable counters')])
        if rows:sections.append('<details><summary>Recorded temperature and error timeline ('+str(len(rows))+' snapshots)</summary>'+table(['Elapsed','Temperature','SMART status','Changes / alerts'],rows)+'</details>')
        else:sections.append('<p class="note">This older test record has no periodic error-counter history; only its available before/after readings are shown.</p>')
        sections.append('<details><summary>Technical SMART records</summary><pre>'+esc(json.dumps({'before':before,'after':after,'snapshots':readings},indent=2))+'</pre></details></section>')
    status=data.get('status','unknown');issues=list(data.get('errors',[]))+list(data.get('cleanup_warnings',[]))
    if data.get('error'):issues.append(data['error'])
    needs_review=bool(warnings or data.get('health_warnings') or issues)
    verdict='Review required' if needs_review else ('Workload completed' if status=='completed' else 'Test incomplete')
    css='''body{margin:0;background:#edf2f7;color:#172d44;font:15px/1.6 system-ui,sans-serif}main{max-width:1060px;margin:auto;padding:40px 24px}header{background:#102c48;color:white;padding:34px;border-radius:20px}h1{font-size:36px;line-height:1.15;margin:10px 0}h2{font-size:26px;margin:4px 0 20px}h3{margin-top:28px}.eyebrow{font-size:12px;letter-spacing:.16em;font-weight:700;color:#087cbe}header .eyebrow{color:#91d3ff}.verdict{display:inline-block;padding:8px 14px;border-radius:8px;background:#e4f5ee;color:#126446;font-weight:700}.warning{background:#fff1d4;color:#75500b;border-radius:8px;padding:14px}.note{font-size:13px;color:#54697d}section{background:white;border:1px solid #d9e3ed;border-radius:16px;padding:28px;margin:24px 0}dl{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px;margin:24px 0}dt{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:#61788c}dd{margin:3px 0;font-weight:600;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;font-size:13px}th{text-align:left;background:#f0f5fa}th,td{padding:11px;border-bottom:1px solid #e1e8ee;vertical-align:top}.scroll{overflow:auto}svg{width:100%;max-height:220px}svg text{font:12px system-ui;fill:#54697d}details{margin-top:18px}summary{cursor:pointer;font-weight:600;color:#087cbe}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:11px}footer{font-size:12px;color:#61788c}@media(max-width:640px){main{padding:16px}header,section{padding:20px}h1{font-size:28px}dl{grid-template-columns:repeat(2,minmax(0,1fr))}}@media print{body{background:white}main{padding:0}header{color:#172d44;background:white;border-bottom:3px solid #087cbe;border-radius:0}section{break-inside:auto}h2,h3{break-after:avoid}.scroll{overflow:visible}tr{break-inside:avoid}details{display:none}footer{margin-top:20px}}'''
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>BIZON · Storage validation report</title><style>'+css+'</style></head><body><main><header><div class="eyebrow">BIZON / STORAGE LAB</div><h1>Storage validation report</h1><p>'+esc(config.get('customer') or 'Customer not specified')+' · '+esc(config.get('reference') or 'Reference not specified')+'</p><span class="verdict '+('warning' if needs_review or status!='completed' else '')+'">'+esc(verdict)+'</span></header>'+details([('Run status',status),('Workstation',data.get('host')),('Started',date(data.get('started') or data.get('created'))),('Finished',date(data.get('finished'))),('Test profile',config['profile']),('Configured duration',str(config['duration'])+' seconds'),('Queue depth',config['depth']),('Test region / file',str(config.get('size_gib',1))+' GiB'),('Drives tested',len(config['devices']))])+('<p class="warning">'+esc('; '.join(issues))+'</p>' if issues else '')+'<p class="note">“Workload completed” means the I/O workload finished without reported errors. It does not certify drive health or future reliability. Review SMART status and counter changes below. Read tests use the selected region; write tests use a temporary file, not the entire drive.</p>'+''.join(sections)+'<details><summary>Complete machine-readable run record</summary><pre>'+esc(json.dumps(data,indent=2))+'</pre></details><footer>Report ID '+esc(data.get('id'))+' · Generated '+date(time.time())+' · All times UTC. Performance reflects this workload, test size and system conditions.</footer></main></body></html>'

def dispatch(action,req):
    if action=='install-tools':
        with lock():
            check_idle()
            if all(Path(p).exists() for p in TOOLS.values()):return {'message':'All storage tools are already installed.'}
            os_release=Path('/etc/os-release').read_text()
            if 'VERSION_ID="24.04"' not in os_release:raise StorageError('Automatic tool setup is supported on Ubuntu 24.04 only.')
            run(['/usr/bin/apt-get','update'],timeout=180)
            run(['/usr/bin/env','DEBIAN_FRONTEND=noninteractive','/usr/bin/apt-get','install','-y','--no-upgrade','--no-install-recommends','fio','smartmontools','mdadm'],timeout=300)
            return {'message':'Storage tools installed. Refresh to read drive information.'}
    if action=='arrays': return [array_info(d) for d in {n['path']:n for n in walk(tree()) if n['type'].startswith('raid')}.values()]
    if action=='inventory': return inventory()
    if action=='start': return start_test(req)
    if action=='jobs': return [ {k:v for k,v in read_job(p.name).items() if k not in ['before','after','samples','health_samples','temperature_samples']} for p in sorted((STATE/'jobs').iterdir(),key=lambda p:p.stat().st_mtime,reverse=True)[:50] if p.is_dir()]
    if action=='status': return read_job(req['id'])
    if action=='stop':
        jid=ident(req['id']);data=read_job(jid)
        if data['status'] in ['running','queued']:run(['/usr/bin/systemctl','kill','--kill-whom=main','--signal=SIGTERM','bizon-storage-'+jid+'.service'])
        return {'message':'Stop requested. Results and cleanup status will appear when the worker exits.'}
    if action=='report':return {'html':report(read_job(req['id']))}
    if action=='raid-plan':return raid_plan(req)
    if action=='raid-apply':return raid_apply(req)
    if action=='raid-check':return raid_check(req)
    raise StorageError('Unknown storage action')

if __name__=='__main__':
    try:
        setup()
        if len(sys.argv)!=3: raise StorageError('Expected action and JSON request')
        if sys.argv[1]=='worker':worker(ident(sys.argv[2]))
        else: print(json.dumps({'ok':True,'data':dispatch(sys.argv[1],json.loads(sys.argv[2]))}))
    except Exception as e:
        print(json.dumps({'ok':False,'error':str(e)}));sys.exit(1)
