#!/usr/bin/python3
import argparse,getpass,json,pathlib,re,shutil,subprocess

def managed(ident):
 if not re.fullmatch('[a-f0-9]{12,64}',ident):raise ValueError('Invalid container ID')
 c=json.loads(subprocess.check_output(['/usr/bin/docker','inspect',ident],text=True))[0]
 labels=c['Config'].get('Labels') or {}
 if labels.get('com.bizon.notebook')!='true' or labels.get('com.bizon.owner')!=getpass.getuser():raise ValueError('This is not your BIZON notebook')
 return c

def stop(ident):
 c=managed(ident);subprocess.run(['/usr/bin/docker','stop','-t','5',ident],check=True,capture_output=True)
 state=pathlib.Path.home()/'.local/state/bizon/notebooks'/c['Name'].lstrip('/')
 if state.is_dir():shutil.rmtree(state)

def main(action):
 p=argparse.ArgumentParser();p.add_argument('--image',default='');p.add_argument('--name',default='');a=p.parse_args()
 try:
  if action=='stop':stop(a.image)
  elif action=='save':
   managed(a.image)
   if not re.fullmatch(r'[a-z0-9][a-z0-9._/-]*(?::[A-Za-z0-9_][A-Za-z0-9_.-]{0,127})?',a.name):raise ValueError('Use a valid lowercase image name')
   subprocess.run(['/usr/bin/docker','commit',a.image,a.name],check=True,capture_output=True)
  elif action=='stop-all':
   ids=subprocess.check_output(['/usr/bin/docker','ps','-q','--filter','label=com.bizon.notebook=true','--filter','label=com.bizon.owner='+getpass.getuser()],text=True).split()
   for ident in ids:stop(ident)
  print(json.dumps({'success':True}))
 except (ValueError,subprocess.SubprocessError) as exc:p.exit(1,str(exc)+'\n')
