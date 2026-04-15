## Installing noVnc
`cp noVnc /usr/local/share/dlbt_os/py_backend/`
`cp start_vnc.py /usr/local/share/dlbt_os/py_backend/`

## Commands to run it
vncserver -geometry 1280x720 -depth 24 -SecurityTypes=none

## Command to connect over the browser

/usr/local/share/dlbt_os/py_backend/noVNC/utils/launch.sh --vnc localhost:5901

* In the location of the noVNC repo
./utils/launch.sh --vnc localhost:5901

bizon root