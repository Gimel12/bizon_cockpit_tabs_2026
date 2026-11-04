#!/usr/bin/python3
import json,subprocess,uuid
from pathlib import Path
results=[];prefix='bizon-accept-'+uuid.uuid4().hex[:8];created=[];saved=prefix+':saved';base='/usr/local/share/dlbt_os/cockpit_jupyter/py_backend/'
def call(args,**kw):return subprocess.run(args,capture_output=True,text=True,**kw)
def check(name,ok):results.append({'test':name,'passed':bool(ok)});print(('PASS ' if ok else 'FAIL ')+name,flush=True)
def action(script,*args):return call(['runuser','-u','bizon','--','/usr/bin/python3',base+script,*args])
existing=call(['docker','ps','-q','--filter','label=com.bizon.notebook=true','--filter','label=com.bizon.owner=bizon']).stdout.strip()
if existing:raise SystemExit('Close existing BIZON notebooks before this isolated action test')
try:
 for suffix,managed in [('owned',True),('other',False)]:
  args=['docker','run','-d','--rm','--name',prefix+'-'+suffix]
  if managed:args+=['--label','com.bizon.notebook=true','--label','com.bizon.owner=bizon']
  r=call(args+['bizon-security-notebook-test:20261104','sleep','120'],check=True);created.append(r.stdout.strip())
 own,other=created
 for script,args in [('stop_container.py',['--image=bad;id']),('commit_container.py',['--image='+own,'--name=bad;id'])]:check('Reject injection '+script,action(script,*args).returncode!=0)
 check('Reject stop of unmanaged container',action('stop_container.py','--image='+other).returncode!=0)
 call(['docker','exec',own,'python','-c',"open('/tmp/bizon-validation-marker','w').write('preserved')"],check=True)
 check('Save notebook image',action('commit_container.py','--image='+own,'--name='+saved).returncode==0)
 r=call(['docker','run','--rm',saved,'cat','/tmp/bizon-validation-marker']);check('Saved image retains notebook changes',r.returncode==0 and r.stdout=='preserved')
 check('Stop all managed notebooks',action('stop_all_containers.py').returncode==0)
 check('Stop all preserves unmanaged container',call(['docker','inspect',other]).returncode==0)
 check('Managed container stopped',call(['docker','inspect',own]).returncode!=0)
 r=call(['runuser','-u','bizon','--','/usr/bin/python3','/usr/local/share/dlbt_os/cockpit_containers/py_backend/erase_image.py','--image_id='+saved]);check('Delete saved test image',r.returncode==0)
finally:
 for ident in created:call(['docker','rm','-f',ident])
 call(['docker','image','rm',saved])
Path('/var/log/bizon-container-actions.json').write_text(json.dumps(results,indent=2))
raise SystemExit(0 if all(r['passed'] for r in results) else 1)
