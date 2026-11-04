#!/usr/bin/python3
"""On-machine read-only/API and temporary VNC acceptance tests; prompts for password."""
import getpass,http.client,json,os,re,select,socket,struct,subprocess,time
from pathlib import Path
password=getpass.getpass('Existing BIZON password: ');results=[]
def check(name,ok,detail=''):
 results.append(dict(test=name,passed=bool(ok),detail=detail));print(('PASS ' if ok else 'FAIL ')+name,flush=True)
def req(path,body=None,headers=None):
 c=http.client.HTTPConnection('127.0.0.1',4000,timeout=45);c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json',**(headers or {})});r=c.getresponse();data=r.read();c.close();return r.status,json.loads(data)
for endpoint in ['ssh-uname','system-info','detailed-specs','gpu-status','gpu-processes','processes','disk-usage','network-stats','system-health']:
 try:
  status,data=req('/api/'+endpoint,{'username':'bizon','password':password});check('API '+endpoint,status==200 and isinstance(data,(dict,list)) and bool(data),str(status))
 except Exception as e:check('API '+endpoint,False,str(e))
for endpoint in ['run-command','run-sudo-command','set-gpu-power-limit','set-fan-speed','reboot','shutdown']:
 try:
  status,data=req('/api/'+endpoint,{});check('API protected action rejects missing credentials: '+endpoint,status in (400,401),str(status))
 except Exception as e:check(endpoint,False,str(e))
for tab in sorted(Path('/usr/local/share/dlbt_os').glob('cockpit_*')):
 if not tab.is_dir():continue
 try:
  m=json.loads((tab/'manifest.json').read_text());paths=[v['path'] for v in m['tools'].values()];check('Tab entry points '+tab.name,all((tab/p).is_file() for p in paths))
  missing=[]
  for html in tab.glob('*.html'):
   for src in re.findall(r'<script[^>]+src=[\"\']([^\"\']+)',html.read_text()):
    if not src.startswith(('https:','http:','../base1/')) and not (html.parent/src).is_file():missing.append(src)
  check('Local script assets '+tab.name,not missing,', '.join(missing))
 except Exception as e:check('Tab '+tab.name,False,str(e))
for tab,script,python in [('cockpit_gpu','gpu_backend.py','/home/bizon/anaconda3/bin/python3'),('cockpit_containers','read_images.py','/usr/bin/python3'),('cockpit_jupyter','read_containers.py','/usr/bin/python3'),('cockpit_jupyter','read_images.py','/usr/bin/python3')]:
 try:
  r=subprocess.run(['runuser','-u','bizon','--',python,'/usr/local/share/dlbt_os/'+tab+'/py_backend/'+script],capture_output=True,text=True,timeout=30)
  data=json.loads(r.stdout);check('Backend '+tab+'/'+script,r.returncode==0 and isinstance(data,(dict,list)))
 except Exception as e:check('Backend '+script,False,str(e))
# Test the RFB protocol with generated credentials, without logging any secrets.
def exact(s,n):
 b=b''
 while len(b)<n:
  x=s.recv(n-len(b))
  if not x:raise RuntimeError('RFB closed unexpectedly')
  b+=x
 return b
def auth(port,pw):
 s=socket.create_connection(('127.0.0.1',port),timeout=10);s.settimeout(10)
 assert exact(s,12)==b'RFB 003.008\n';s.sendall(b'RFB 003.008\n');types=exact(s,exact(s,1)[0]);assert 2 in types and 1 not in types;s.sendall(b'\x02');challenge=exact(s,16)
 key=bytes(int(f'{v:08b}'[::-1],2) for v in pw.encode()[:8].ljust(8,b'\x00'))
 r=subprocess.run(['/usr/bin/openssl','enc','-des-ecb','-provider','legacy','-K',key.hex(),'-nopad'],input=challenge,capture_output=True,check=True)
 s.sendall(r.stdout);status=struct.unpack('!I',exact(s,4))[0]
 return s,status
for cycle in range(1,4):
 proc=None;config=None
 try:
  before=set(Path('/home/bizon/.local/state/bizon/vnc').glob('passwd-*'))
  proc=subprocess.Popen(['runuser','-u','bizon','--','/usr/bin/python3','-I','/usr/local/share/dlbt_os/cockpit_vnc/py_backend/start_vnc.py'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
  if not select.select([proc.stdout],[],[],35)[0]:raise RuntimeError('VNC startup timeout')
  config=json.loads(proc.stdout.readline());port=config['port']
  s,status=auth(port,'wrongpw!');s.close();check('VNC wrong password rejected cycle '+str(cycle),status!=0)
  s,status=auth(port,config['password']);check('VNC authentication cycle '+str(cycle),status==0)
  s.sendall(b'\x01');info=exact(s,24);width,height=struct.unpack('!HH',info[:4]);name=exact(s,struct.unpack('!I',info[20:])[0]);check('VNC framebuffer cycle '+str(cycle),width>0 and height>0)
  s.sendall(struct.pack('!BBHHHH',3,0,0,0,64,64));check('VNC screen update cycle '+str(cycle),exact(s,1)==b'\x00');s.close()
 except Exception as e:check('VNC cycle '+str(cycle),False,str(e))
 finally:
  if proc:
   proc.terminate()
   try:proc.communicate(timeout=15)
   except subprocess.TimeoutExpired:proc.kill();proc.communicate();check('VNC cleanup timed out',False)
  if config:
   with socket.socket() as s:s.settimeout(1);closed=s.connect_ex(('127.0.0.1',config['port']))!=0
   after=set(Path('/home/bizon/.local/state/bizon/vnc').glob('passwd-*'));check('VNC listener and credential cleanup cycle '+str(cycle),closed and after==before)
check('No failed services',not subprocess.check_output(['systemctl','--failed','--no-legend','--plain'],text=True).strip())
Path('/var/log/bizon-acceptance.json').write_text(json.dumps(results,indent=2));print(str(sum(x['passed'] for x in results))+'/'+str(len(results))+' passed')
raise SystemExit(0 if all(x['passed'] for x in results) else 1)
