import json
import argparse

# FIXME: Add to a json
path = "/usr/local/share/dlbt_os/gen/nvidia-log.txt"

def read_lines():
    with open(path,'r') as f:
        ls = f.readlines()
        d = []
        for l in ls:
            d.append(json.loads(l))
    return d

def read_file():
    d = read_lines()
    return json.dumps(d)

def fix_filter(s):
    if s[0] == "'" or s[0]=='"':
        return s[1:-1]
    return s

def read_next_logs(num,last_timestamp,sample_size):
    last_timestamp = fix_filter(last_timestamp)
    lines = read_lines()
    sample_size = min(sample_size, len(lines))
    
    idx = -1
    out = []
    response = {
        "filter": last_timestamp,
        "end": True,
    }
    if last_timestamp != "NIL":
        for i,l in enumerate(lines):
            if l["timestamp"] == last_timestamp:
                idx = i
                break
    # print(idx)
    # If it is too old or non-existent:

    if idx == -1:
        out = lines[-sample_size:-sample_size+num]
        response["end"] = False
    elif idx < len(lines)-1:
        out = lines[idx+1:idx+1+num]
        response["end"] = idx+1+num >= len(lines)
    response["values"] = out
    
    return json.dumps(response)        

if __name__ == "__main__":
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--last_log', default="NIL")
    cmdline.add_argument('--batch_size', default="5")
    cmdline.add_argument('--sampling_size', default="100")
    flags, unk_args = cmdline.parse_known_args()
    out = read_next_logs(int(flags.batch_size),flags.last_log,int(flags.sampling_size))
    print(out)
