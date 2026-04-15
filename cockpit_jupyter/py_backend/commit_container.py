import os
import time
import subprocess
import argparse

if __name__ == "__main__":
    
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--image', default="")
    cmdline.add_argument('--name', default="")

    flags, unk_args = cmdline.parse_known_args()
    os.system("docker commit "+ flags.image + " " + flags.name)
