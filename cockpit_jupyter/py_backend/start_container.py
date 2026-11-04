#!/usr/bin/python3
"""Launch a token-authenticated TLS notebook using validated argv, never a shell."""
import argparse, json, os, pathlib, re, secrets, shlex, socket, subprocess, ipaddress, getpass, time, ssl, http.client, shutil

def build_args(a, state):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',a.name): raise ValueError('Invalid container name')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}',a.image): raise ValueError('Invalid image name')
    if not 8800 <= int(a.port) <= 8888: raise ValueError('Notebook ports must be 8800–8888')
    if not 0 <= int(a.gpus) <= 32: raise ValueError('Invalid GPU count')
    args=['/usr/bin/docker','run','--rm','-d','--label','com.bizon.notebook=true','--label','com.bizon.owner='+getpass.getuser(),'-p',getattr(a,'bind_address','127.0.0.1')+':'+str(int(a.port))+':8888','--name',a.name,'--shm-size=1g','--ulimit','memlock=-1','--ulimit','stack=67108864']
    if int(a.gpus): args+=['--gpus','"device='+','.join(str(i) for i in range(int(a.gpus)))+'"']
    if a.volume != 'x':
        parts=a.volume.split(':')
        if len(parts) not in (2,3) or (len(parts)==3 and parts[2] not in ('ro','rw')): raise ValueError('Use source:destination[:ro|rw] for volumes')
        source=pathlib.Path(parts[0]).expanduser().resolve()
        roots=[pathlib.Path.home(),pathlib.Path('/mnt'),pathlib.Path('/media')]
        if not any(source == root or root in source.parents for root in roots): raise ValueError('Volumes must be inside your home, /mnt or /media')
        if not parts[1].startswith('/') or parts[1] in ('/','/proc','/sys','/dev','/bizon-config'): raise ValueError('Invalid container mount destination')
        args+=['-v',str(source)+':'+':'.join(parts[1:])]
    extra=shlex.split(a.extra)
    while extra:
        option=extra.pop(0)
        if '=' in option: option,value=option.split('=',1)
        elif extra: value=extra.pop(0)
        else: raise ValueError('Missing extra option value')
        if option not in ('--cpus','--memory','--shm-size') or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?[bkmgBKMG]?',value):
            raise ValueError('Extra options support --cpus, --memory and --shm-size only')
        args += [option,value]
    args += ['-v',str(state)+':/bizon-config:ro',a.image,'jupyter','notebook','--config=/bizon-config/notebook.json','--port=8888','--ip=0.0.0.0','--allow-root','--no-browser']
    return args

def main():
    p=argparse.ArgumentParser()
    for name,default in [('name',''),('image',''),('gpus','1'),('port',''),('volume','x'),('mode','production'),('extra','')]: p.add_argument('--'+name,default=default)
    a=p.parse_args()
    routes=json.loads(subprocess.check_output(['/usr/sbin/ip','-j','-4','route','get','1.1.1.1'],text=True))
    a.bind_address=routes[0].get('prefsrc','')
    private=[ipaddress.ip_network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')]
    if not a.bind_address or not any(ipaddress.ip_address(a.bind_address) in net for net in private):
        p.error('A private management-network address is required for notebooks')
    state=pathlib.Path.home()/'.local/state/bizon/notebooks'/a.name
    try: args=build_args(a,state)
    except ValueError as exc: p.error(str(exc))
    if subprocess.run(['/usr/bin/docker','container','inspect',a.name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0:
        p.error('A container with this name already exists')
    state.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(state,0o700)
    cert=state/'cert.pem';key=state/'key.pem'
    subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:3072','-sha256','-nodes','-days','365','-subj','/CN=BIZON notebook','-addext','subjectAltName=IP:'+a.bind_address,'-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    token=secrets.token_hex(32)
    config={'NotebookApp':{'token':token,'certfile':'/bizon-config/cert.pem','keyfile':'/bizon-config/key.pem'},'ServerApp':{'token':token,'certfile':'/bizon-config/cert.pem','keyfile':'/bizon-config/key.pem'},'IdentityProvider':{'token':token}}
    (state/'notebook.json').write_text(json.dumps(config));(state/'notebook.json').chmod(0o600)
    result=subprocess.run(args,capture_output=True,text=True)
    if result.returncode:
        shutil.rmtree(state)
        raise SystemExit(result.stderr.strip())
    context=ssl.create_default_context(cafile=str(cert))
    for attempt in range(60):
        try:
            conn=http.client.HTTPSConnection(a.bind_address,int(a.port),context=context,timeout=1)
            conn.request('GET','/api/sessions',headers={'Authorization':'token '+token})
            response=conn.getresponse();response.read();conn.close()
            if response.status==200:break
        except (OSError,ValueError):pass
        time.sleep(.5)
    else:
        subprocess.run(['/usr/bin/docker','stop','-t','3',a.name],capture_output=True)
        shutil.rmtree(state)
        raise SystemExit('Notebook did not become ready; check that the image includes Jupyter Notebook')
    print(json.dumps({'success':True,'name':a.name}),flush=True)
if __name__=='__main__': main()
