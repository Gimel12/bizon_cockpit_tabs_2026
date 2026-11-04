#!/usr/bin/python3
"""Start VNC on loopback with a fresh per-session password; no public proxy."""
import argparse, json, os, pathlib, secrets, socket, subprocess, time, signal
def terminate(signum, frame): raise KeyboardInterrupt
signal.signal(signal.SIGTERM, terminate)
signal.signal(signal.SIGHUP, terminate)
p=argparse.ArgumentParser();p.add_argument('--port',default='6080');p.parse_args()
state=pathlib.Path.home()/'.local/state/bizon/vnc';state.mkdir(parents=True,exist_ok=True,mode=0o700);state.chmod(0o700)
port=None
for display in range(10,30):
    if pathlib.Path('/tmp/.X%d-lock'%display).exists(): continue
    with socket.socket() as sock:
        try: sock.bind(('127.0.0.1',5900+display));port=5900+display;break
        except OSError: pass
if port is None: raise SystemExit('No free VNC display')
password=secrets.token_urlsafe(8)[:8]
password_file=state/('passwd-%d'%display)
password_file.write_bytes(subprocess.check_output(['/usr/bin/vncpasswd','-f'],input=(password+'\n').encode()))
password_file.chmod(0o600)
try:
    result=subprocess.run(['/usr/bin/vncserver',':'+str(display),'-xstartup','/usr/local/libexec/bizon-vnc-session','-geometry','1920x1080','-depth','24','-localhost','yes','-SecurityTypes','VncAuth','-PasswordFile',str(password_file)],capture_output=True,text=True)
    if result.returncode:
        raise SystemExit(result.stderr)
    print(json.dumps({'port':port,'password':password}),flush=True)
    pid=int(pathlib.Path('/tmp/.X%d-lock'%display).read_text().strip())
    while True:
        time.sleep(2)
        try:os.kill(pid,0)
        except ProcessLookupError:break
except (KeyboardInterrupt,BrokenPipeError): pass
finally:
    subprocess.run(['/usr/bin/vncserver','-kill',':'+str(display)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    password_file.unlink(missing_ok=True)
