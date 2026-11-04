#!/usr/bin/python3
import json,subprocess
ids=subprocess.check_output(['/usr/bin/docker','image','ls','-q','--no-trunc'],text=True).split()
images=[]
if ids:
    data=json.loads(subprocess.check_output(['/usr/bin/docker','image','inspect',*dict.fromkeys(ids)],text=True))
    for image in data:
        ident=image['Id'].split(':')[-1][:12]
        tag=(image.get('RepoTags') or [ident])[0]
        images.append(dict(id=ident,title=tag,repository=tag,created=image['Created'],size=image['Size']))
print(json.dumps(images))
