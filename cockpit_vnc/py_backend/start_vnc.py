import os
import sys
import time
import socket
import argparse
import subprocess
import glob

# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def display_in_use(display_num):
    """Check if an X display number is already in use (file or abstract socket)."""
    # Check file-based socket
    if os.path.exists("/tmp/.X11-unix/X{}".format(display_num)):
        return True
    # Check abstract socket (used by Xorg / GDM)
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect("\0/tmp/.X11-unix/X{}".format(display_num))
        s.close()
        return True
    except (ConnectionRefusedError, OSError):
        pass
    # Check lock file
    if os.path.exists("/tmp/.X{}-lock".format(display_num)):
        return True
    return False


def find_free_display(start=10, end=30):
    """Return the first free X display number in [start, end)."""
    for n in range(start, end):
        if not display_in_use(n):
            return n
    return None


def kill_existing_vnc_servers():
    """Kill any VNC servers we may have started previously."""
    for n in range(1, 30):
        pid_file = os.path.expanduser(
            "~/.vnc/{hostname}:{n}.pid".format(
                hostname=socket.gethostname(), n=n
            )
        )
        if os.path.exists(pid_file):
            os.system("vncserver -kill :{} >/dev/null 2>&1".format(n))
    time.sleep(1)
    # Clean up any stale lock/socket files that belong to dead processes
    for lock in glob.glob("/tmp/.X*-lock"):
        try:
            with open(lock) as f:
                pid = int(f.read().strip())
            # If process is dead, remove the lock
            if not os.path.exists("/proc/{}".format(pid)):
                os.remove(lock)
        except (OSError, ValueError):
            pass
    for sock in glob.glob("/tmp/.X11-unix/X*"):
        try:
            display_num = int(sock.rsplit("X", 1)[1])
            lock = "/tmp/.X{}-lock".format(display_num)
            if not os.path.exists(lock):
                os.remove(sock)
        except (OSError, ValueError, IndexError):
            pass


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

if __name__ == "__main__":

    cmdline = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    cmdline.add_argument("--port", default="6080")
    flags, _ = cmdline.parse_known_args()

    print("Cleaning up old VNC sessions...")
    kill_existing_vnc_servers()

    display = find_free_display()
    if display is None:
        print("ERROR: Could not find a free X display (tried :10 – :29)")
        sys.exit(1)

    vnc_port = 5900 + display  # e.g. display :10 → port 5910
    print("Using display :{} (VNC port {})".format(display, vnc_port))

    # Start VNC server on the chosen display
    rc = os.system(
        "vncserver :{d} -geometry 1920x1080 -depth 24 -SecurityTypes=none".format(
            d=display
        )
    )
    if rc != 0:
        print("ERROR: vncserver failed to start (exit code {})".format(rc))
        sys.exit(1)

    time.sleep(3)

    # Verify VNC is actually listening
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(("127.0.0.1", vnc_port))
        s.close()
        print("VNC server confirmed listening on port {}".format(vnc_port))
    except Exception as e:
        print("WARNING: VNC port {} not responding: {}".format(vnc_port, e))

    print("Press Ctrl-C to stop")

    # Start noVNC / websockify proxy
    os.system(
        "/usr/local/share/dlbt_os/cockpit_vnc/noVNC/utils/launch.sh "
        "--vnc localhost:{vnc} --listen {ws}".format(
            vnc=vnc_port, ws=flags.port
        )
    )

while True:
    time.sleep(2)
