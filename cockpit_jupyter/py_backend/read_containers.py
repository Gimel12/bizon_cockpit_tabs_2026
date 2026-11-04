#!/usr/bin/python3
import json,subprocess,pathlib,getpass
ids=subprocess.check_output(['/usr/bin/docker','ps','-q','--filter','label=com.bizon.notebook=true','--filter','label=com.bizon.owner='+getpass.getuser()],text=True).split()
containers=[]
if ids:
 for c in json.loads(subprocess.check_output(['/usr/bin/docker','inspect',*ids],text=True)):
  ports=c['NetworkSettings'].get('Ports',{}).get('8888/tcp') or []
  name=c['Name'].lstrip('/');url=None
  try:
   token=json.loads((pathlib.Path.home()/'.local/state/bizon/notebooks'/name/'notebook.json').read_text())['IdentityProvider']['token']
   if ports:url='https://'+ports[0]['HostIp']+':'+ports[0]['HostPort']+'/lab?token='+token
  except (OSError,ValueError,KeyError):pass
  containers.append(dict(id=c['Id'][:12],date=c['Created'],status=c['State']['Status'],name=name,image=c['Config']['Image'],port=ports[0]['HostPort'] if ports else '',url=url))
print(json.dumps(containers))
