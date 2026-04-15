import os
import time
import subprocess
import argparse

if __name__ == "__main__":
        
    os.system("docker ps -q | xargs docker stop")
    time.sleep(.5)
    os.system("docker container prune -f")
