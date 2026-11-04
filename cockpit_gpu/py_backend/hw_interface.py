import argparse, json, subprocess
p=argparse.ArgumentParser()
p.add_argument('--gpu_id',type=int,required=True)
p.add_argument('--power',type=int,required=True)
a=p.parse_args()
if not 0 <= a.gpu_id < 32 or not 1 <= a.power <= 2000:
    p.error('Invalid GPU or power limit')
r=subprocess.run(['/usr/bin/nvidia-smi','-i',str(a.gpu_id),'-pl',str(a.power)],capture_output=True,text=True,timeout=15)
print(json.dumps({'success':r.returncode==0,'output':r.stdout+r.stderr}))
