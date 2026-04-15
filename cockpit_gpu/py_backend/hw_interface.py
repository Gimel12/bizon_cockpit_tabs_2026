import argparse
import os
import json
mode = "prod"

def set_pl(gpu, power_limit,mode):
    # Replace with correct command

    cmd = f"sudo nvidia-smi -i {gpu} -pl {power_limit}"
    # cmd = f"echo root | sudo -S nvidia-smi -i {gpu} -pl {power_limit}"
    r = cmd
    if mode != "dev":
        r = os.popen(cmd).read()
    return r


if __name__ == "__main__":
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--power', default="")
    cmdline.add_argument('--gpu_clock', default="")
    cmdline.add_argument('--gpu_id', default="")
    flags, unk_args = cmdline.parse_known_args()
    result = {
        "success": False,
    }
    if flags.gpu_id == "":
        print(json.dumps(result))
        exit(0)
    
    if flags.power != "":
        r = set_pl(int(flags.gpu_id),int(flags.power),mode)
        result["output"] = r
        if r.lower().find("error") == -1:
            result["output"] = r
            result["success"] = True
        
        print(json.dumps(result))
