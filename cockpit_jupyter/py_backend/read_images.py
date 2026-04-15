import docker
import json

client = docker.from_env()

ims = []
images = client.images.list()
for im in images:    
    image = {
        "id": im.short_id[im.short_id.find(":")+1:],                
        "title": im.tags[0],
        "repository": im.tags[0],
        "created": im.attrs["Created"],
        "size": im.attrs["Size"] 
    }

    # print(list(c.ports.values())[0][0]["HostPort"])
    # print(c.attrs["HostConfig"]["PortBindings"])
    ims.append(image)

d = json.dumps(ims)
print(d)