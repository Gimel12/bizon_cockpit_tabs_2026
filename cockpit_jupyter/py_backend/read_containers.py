import docker
import json

client = docker.from_env()

containers = []
conts = client.containers.list()

for c in conts:
    port = "8000"
    ports = c.ports    
    for k,v in ports.items():
        if v is not None and "HostPort" in v[0]:
            port = v[0]["HostPort"]
    cn = {
        "id": c.short_id,
        "date": c.attrs['Created'],        
        "status": c.status,
        "name": c.name,
        "image": c.image.tags[0],
        "port":port        
    }

    # print(list(c.ports.values())[0][0]["HostPort"])
    # print(c.attrs["HostConfig"]["PortBindings"])
    containers.append(cn)

# print(json.dumps(containers))
d = json.dumps(containers)
print(d)