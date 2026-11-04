#!/usr/bin/env python3
"""Live local-model acceptance; writes only inside a temporary directory.

Run as root on the test workstation with --agent-dir pointing at reviewed code.
Claude is never called. Model-proposed tools are restricted by this test harness.
"""
import argparse,json,os,pwd,queue,subprocess,tempfile,threading,time,uuid
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--agent-dir',type=Path,required=True);a=p.parse_args()
user=pwd.getpwnam('bizon');results=[]
class Channel:
 def __init__(self,script,args=(),admin=False,home=None):
  cmd=['/usr/bin/python3','-I',str(a.agent_dir/script),*args]
  if not admin:cmd=['runuser','-u','bizon','--','env','HOME='+str(home),*cmd]
  self.p=subprocess.Popen(cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,cwd=home)
  self.q=queue.Queue()
  def read():
   for line in self.p.stdout:
    try:self.q.put(json.loads(line))
    except ValueError:self.q.put({'type':'invalid','message':line[:200]})
   self.q.put({'type':'closed'})
  threading.Thread(target=read,daemon=True).start()
 def send(self,data):self.p.stdin.write(json.dumps(data)+'\n');self.p.stdin.flush()
 def recv(self,timeout=120):return self.q.get(timeout=timeout)
 def close(self):
  if not self.p.stdin.closed:self.p.stdin.close()
  try:self.p.wait(timeout=8)
  except subprocess.TimeoutExpired:self.p.terminate();self.p.wait(timeout=5)
  self.p.stdout.close();self.p.stderr.close()
def run_case(name,prompt,mode,admin,home,path=None):
 started=time.monotonic();planner=None;executor=None;calls=[];answer='';errors=[]
 try:
  run_id=str(uuid.uuid4());nonce=uuid.uuid4().hex+uuid.uuid4().hex
  if mode=='agent':
   executor=Channel('executor.py',admin=admin,home=home)
   executor.send({'type':'init','run_id':run_id,'nonce':nonce,'ttl_seconds':180,'mode':'administrator' if admin else 'user'})
   assert executor.recv()['type']=='ready'
  planner=Channel('backend.py',('chat',),home=home)
  planner.send({'message':prompt,'provider':'ollama','model':'qwen3.8:27b','mode':mode})
  while time.monotonic()-started<240:
   event=planner.recv()
   if event['type']=='tool_request':
    assert executor is not None,'Chat tried to execute a tool'
    args=event['arguments'];tool=event['name'];calls.append({'name':tool,'arguments':args})
    permitted=(admin and tool=='run_command' and args.get('command','').strip()=='id -u') or (not admin and path is not None and tool in ('read_file','write_file') and args.get('path')==str(path))
    if not permitted:raise AssertionError('Model proposed an unexpected tool; nothing executed: '+json.dumps(calls[-1]))
    executor.send({'type':'execute','run_id':run_id,'nonce':nonce,'id':event['id'],'name':tool,'arguments':args})
    while True:
     result=executor.recv()
     if result['type'] in ('error','closed'):raise AssertionError(result)
     if result['type']=='tool_done':break
    assert result['result']['exit_code']==0,result
    if admin:assert result['result']['output'].strip()=='0',result
    planner.send({'type':'tool_result','id':event['id'],'result':result['result']})
   elif event['type']=='done':answer=event['content'];break
   elif event['type'] in ('error','invalid','closed'):raise AssertionError(event)
  else:raise AssertionError('Live test deadline exceeded')
  if path is not None:
   assert path.read_text().strip()=='BIZON_AGENT_OK'
   assert {'read_file','write_file'}<={x['name'] for x in calls}
  if admin:assert calls and '0' in answer
  if mode=='chat':assert 'CHAT_OK' in answer and not calls
  results.append({'test':name,'passed':True,'tools':calls,'answer':answer,'seconds':round(time.monotonic()-started,2)})
 except Exception as e:results.append({'test':name,'passed':False,'error':str(e),'seconds':round(time.monotonic()-started,2)})
 finally:
  if planner:planner.close()
  if executor:executor.close()
 print(json.dumps(results[-1]),flush=True)
with tempfile.TemporaryDirectory(prefix='bizon-agent-acceptance-') as folder:
 home=Path(folder);os.chown(home,user.pw_uid,user.pw_gid);path=home/'result.txt'
 run_case('Local chat executes no tools','Reply with exactly CHAT_OK and nothing else.','chat',False,home)
 run_case('Local model writes and reads a disposable file',f'Use the write_file tool to create {path} containing exactly BIZON_AGENT_OK. Then use read_file to read that same file and report the text. Do not use shell commands or touch any other file.','agent',False,home,path)
 run_case('Administrator command returns root UID','Use run_command to execute exactly id -u. Report the numeric UID from its output. Do not run anything else or change any files.','agent',True,home)
print(json.dumps({'passed':sum(x['passed'] for x in results),'total':len(results),'results':results},indent=2))
raise SystemExit(0 if all(x['passed'] for x in results) else 1)
