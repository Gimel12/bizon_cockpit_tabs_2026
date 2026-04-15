import json
import os
import time
import sys
import argparse
# 20.04 update
version_name = ""
version_id = ""

__version__ = "1.0.0"
upd_cmd = ""

_update_dirs = {
    "containers":{
        "dev":{
            "version_name": "/usr/local/share/dlbt_os/test_upd/vs_lightcp_ct.txt",
            "version_id": "1OsH_AS6e1vrHFLElQVgdW7EOedkCvQE7",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/test_upd/cockpit_containers;
                        mkdir /usr/local/share/dlbt_os/test_upd/cockpit_containers
                        7z x -o/usr/local/share/dlbt_os/test_upd/cockpit_containers $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/test_upd/cockpit_containers/ ~/.local/share/cockpit/cockpit_containers_test;
                        rm /usr/local/share/dlbt_os/test_upd/vs_lightcp_ct.txt;
                        rm $FILENAME; rm dwnld.status"""
        },
        "production":{
            "version_name": "/usr/local/share/dlbt_os/vs_cockpit_ct.txt",
            "version_id": "17ZHbf9rEHH36aoubIf9SUd7yrjDOJ5b1",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/cockpit_containers;
                        mkdir /usr/local/share/dlbt_os/cockpit_containers;
                        7z x -o/usr/local/share/dlbt_os/cockpit_containers $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/cockpit_containers/ ~/.local/share/cockpit/cockpit_containers;
                        rm /usr/local/share/dlbt_os/vs_cockpit_ct.txt;
                        rm $FILENAME;rm dwnld.status"""
        }
    },
    "jupyter":{
        "dev":{
            "version_name": "/usr/local/share/dlbt_os/test_upd/vs_lightcp_jp.txt",
            "version_id": "1fNvT6ZRUaznD-ktaasvBaWxAQWgYst_Y",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/test_upd/cockpit_jupyter;
                        mkdir /usr/local/share/dlbt_os/test_upd/cockpit_jupyter;
                        7z x -o/usr/local/share/dlbt_os/test_upd/cockpit_jupyter $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/test_upd/cockpit_jupyter/ ~/.local/share/cockpit/cockpit_jupyter_test;
                        rm /usr/local/share/dlbt_os/test_upd/vs_lightcp_jp.txt;
                        rm $FILENAME; rm dwnld.status"""
        },
        "production":{
            "version_name": "/usr/local/share/dlbt_os/vs_cockpit_jp.txt",
            "version_id": "1fW67SBI-0ElAwKLy9Thr9wX2C98z9mvh",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/cockpit_jupyter;
                        mkdir /usr/local/share/dlbt_os/cockpit_jupyter;
                        7z x -o/usr/local/share/dlbt_os/cockpit_jupyter $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/cockpit_jupyter/ ~/.local/share/cockpit/cockpit_jupyter;
                        rm /usr/local/share/dlbt_os/vs_cockpit_jp.txt;
                        rm $FILENAME; rm dwnld.status"""
        }
    },

    "support":{
        "dev":{
            "version_name": "/usr/local/share/dlbt_os/test_upd/vs_lightcp_sp.txt",
            "version_id": "1nMf_qFnq8hGlcTNqJkvHX0wMf4XKW4xY",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/test_upd/cockpit_support;
                        mkdir /usr/local/share/dlbt_os/test_upd/cockpit_support;
                        7z x -o/usr/local/share/dlbt_os/test_upd/cockpit_support $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/test_upd/cockpit_support/ ~/.local/share/cockpit/cockpit_support_test;
                        rm /usr/local/share/dlbt_os/test_upd/vs_lightcp_sp.txt;
                        rm $FILENAME; rm dwnld.status"""
        },
        "production":{
            "version_name": "/usr/local/share/dlbt_os/vs_cockpit_sp.txt",
            "version_id": "1FJJDEPojb27-loucNrhQGpvRMnNkX6Q8",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/cockpit_support;
                        mkdir /usr/local/share/dlbt_os/cockpit_support;
                        7z x -o/usr/local/share/dlbt_os/cockpit_support $FILENAME;
                        ln -snf /usr/local/share/dlbt_os/cockpit_support/ ~/.local/share/cockpit/cockpit_support;
                        rm /usr/local/share/dlbt_os/vs_cockpit_sp.txt;
                        rm $FILENAME; rm dwnld.status"""
        }
    },

    "vnc":{
        "dev":{
            "version_name": "/usr/local/share/dlbt_os/test_upd/vs_lightcp_vnc.txt",
            "version_id": "1cTdgeDMPXLu4-w7YDghlPtEmqWmFV3BF",
            "upd_cmd": """rm -r /usr/local/share/dlbt_os/test_upd/cockpit_vnc;
                        mkdir /usr/local/share/dlbt_os/test_upd/cockpit_vnc;
                        7z x -o/usr/local/share/dlbt_os/test_upd/cockpit_vnc $FILENAME;                        
                        ln -snf /usr/local/share/dlbt_os/test_upd/cockpit_vnc/ ~/.local/share/cockpit/cockpit_vnc_test;
                        sh /usr/local/share/dlbt_os/cockpit_vnc/setup.bash;
                        rm /usr/local/share/dlbt_os/test_upd/vs_lightcp_vnc.txt;
                        rm $FILENAME; rm dwnld.status"""
        },
        "production":{
            "version_name": "/usr/local/share/dlbt_os/vs_cockpit_vnc.txt",
            "version_id": "1DK1PVAStgy6CHpAMioq8ZNSngK9ZztkX",
            "upd_cmd": """rm -rf /usr/local/share/dlbt_os/cockpit_vnc;
                        mkdir /usr/local/share/dlbt_os/cockpit_vnc;
                        7z x -o/usr/local/share/dlbt_os/cockpit_vnc $FILENAME;
                        sh /usr/local/share/dlbt_os/cockpit_vnc/setup.bash;
                        ln -snf /usr/local/share/dlbt_os/cockpit_vnc/ ~/.local/share/cockpit/cockpit_vnc;
                        rm /usr/local/share/dlbt_os/vs_cockpit_vnc.txt;
                        rm $FILENAME; rm dwnld.status"""
        }
    }
}

def get_download_cmd(filename, fileid):
    return f"""wget --load-cookies /tmp/cookies.txt "https://docs.google.com/uc?export=download&confirm=$(wget --quiet --save-cookies /tmp/cookies.txt --keep-session-cookies --no-check-certificate 'https://docs.google.com/uc?export=download&id={fileid}' -O- | sed -rn 's/.*confirm=([0-9A-Za-z_]+).*/\1\n/p')&id={fileid}" -O {filename} && rm -rf /tmp/cookies.txt && echo 'progressing...' >> dwnld.status"""

def check_version():

    cmd = get_download_cmd(version_name, version_id)
    os.popen(cmd)
    time.sleep(15)

    no_connection_count = 0
    while not os.path.exists(version_name):
        time.sleep(2)
        no_connection_count += 2
        if no_connection_count > 20:
            sys.exit(1)

    with open(version_name, 'r') as f:        
        lines = f.readlines()
        # print(lines)
        last_v = lines[0]
        version, name, fid = last_v.split()
        # msg = "Update your bizon system. The latest version is " + version + name
        # os.popen(
        #     'zenity --info --title="System  [v1.0.1]" --text="'+msg+'" --width=350')        

        if version == __version__:
            print("Matched versions..")            
            f.close()
            os.popen("rm " + version_name)
            os.popen("rm dwnld.status")
            return
          
        os.popen("rm dwnld.status")
        dcmd = get_download_cmd(name, fid)
        os.popen(dcmd)
        time.sleep(2)
        # wait for the file to get downloaded
        while not os.path.exists('dwnld.status'):
            time.sleep(2)            
        
        print("Downloaded files...")
        # os.popen(upd_cmd)
        
        # PWD_placeholder = "$PASSWD511"
        # # ## Run the update
        s = upd_cmd.replace("$FILENAME",name)
        r = os.popen(s).read()
        # print("Downloaded update script commands... :\n\n")
        # print(s)
        
        # print(r)

def check_version_all(mode="production"):
    global version_name, version_id, upd_cmd
    for tab in _update_dirs:
        version_name = _update_dirs[tab][mode]["version_name"]
        version_id = _update_dirs[tab][mode]["version_id"]
        upd_cmd = _update_dirs[tab][mode]["upd_cmd"]
        check_version()


if __name__ == "__main__":
    cmdline = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    cmdline.add_argument('--tabname', default="")
    cmdline.add_argument('--mode', default="production")

    flags, unk_args = cmdline.parse_known_args()  
    if flags.tabname == "":
        x = 1/0    
    elif flags.tabname == "all":
        check_version_all(flags.mode)
    else:
        version_name = _update_dirs[flags.tabname][flags.mode]["version_name"]
        version_id = _update_dirs[flags.tabname][flags.mode]["version_id"]
        upd_cmd = _update_dirs[flags.tabname][flags.mode]["upd_cmd"]        
        check_version()
    