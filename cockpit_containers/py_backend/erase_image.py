#!/usr/bin/python3
import argparse,re,subprocess
p=argparse.ArgumentParser();p.add_argument('--image_id',required=True);a=p.parse_args()
if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/@-]{0,255}',a.image_id):p.error('Invalid image reference')
raise SystemExit(subprocess.run(['/usr/bin/docker','image','rm',a.image_id]).returncode)
