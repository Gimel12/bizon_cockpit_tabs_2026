import os
import time
import subprocess
import argparse

if __name__ == "__main__":
    
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--name', default="")
    cmdline.add_argument('--image', default="")
    cmdline.add_argument('--gpus', default="1")
    cmdline.add_argument('--port', default="")
    cmdline.add_argument('--volume', default="x")
    cmdline.add_argument('--mode', default="production")
    cmdline.add_argument('--extra', default="")
    flags, unk_args = cmdline.parse_known_args()
    devs = "0"
    amount_gpus = int(flags.gpus)
    for i in range(1,amount_gpus):
        devs += "," + str(i)
    # print(flags.name)
    # -e NVIDIA_VISIBLE_DEVICES=0
    # command
    # docker run --gpus device=0,1 -t -p 8840:8888 --name lolita c8515d0efd jupyter notebook --port=8888 --ip=0.0.0.0 --allow-root --no-browser
    v_option = ""
    if flags.volume != "x":
        v_option = "-v " + flags.volume

    cmd = "docker run -t --gpus " + "'" + '"' +"device=" + devs  + '"' + "'" + " -p "+ flags.port+":8888 " + v_option + " --name "+ flags.name + " --shm-size=1g --ulimit memlock=-1  --ulimit stack=67108864 " + flags.extra + " " + flags.image + " jupyter notebook --port=8888 --ip=0.0.0.0 --allow-root --no-browser"
    print(cmd)
    os.system(cmd) 
    # if flags.mode == "production":
    #     cmd = "docker run -t --gpus " + "'" + '"' +"device=" + devs  + '"' + "'" + " -p "+ flags.port+":8888 " + v_option + " --name "+ flags.name + " " + flags.extra + " " + flags.image + " jupyter notebook --port=8888 --ip=0.0.0.0 --allow-root --no-browser"
    #     print(cmd)
    #     os.system(cmd)    
    # else:
    #     cmd = "docker run -t " + " -p "+ flags.port+":8888 " + v_option + " --name "+ flags.name + " " + flags.extra + " " + flags.image + " jupyter notebook --port=8888 --ip=0.0.0.0 --allow-root --no-browser";
    #     print(cmd)
    #     os.system("docker run -t " + " -p "+ flags.port+":8888 " + v_option + " --name "+ flags.name + " " + flags.extra + " " + flags.image + " jupyter notebook --port=8888 --ip=0.0.0.0 --allow-root --no-browser")
        
    # p = subprocess.Popen(["docker", "run", "-t" ,"-p=8888:8888", "--name", flags.name, flags.image, "jupyter", "notebook", "--port=8888", "--ip=0.0.0.0","--allow-root"],
    #                      cwd="/",
    #                      stdout=subprocess.PIPE,
    #                      stderr=subprocess.STDOUT)

    

    # s = a.splitlines()[-1]
    # print(s)
    while True:
        time.sleep(2)    
        # print("dlss")
    