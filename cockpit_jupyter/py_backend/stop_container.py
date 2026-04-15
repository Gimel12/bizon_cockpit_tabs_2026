import os
import time
import subprocess
import argparse

if __name__ == "__main__":
    
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--image', default="")

    flags, unk_args = cmdline.parse_known_args()
    os.system("docker stop "+ flags.image)
    time.sleep(.5)
    os.system("docker rm "+ flags.image)
