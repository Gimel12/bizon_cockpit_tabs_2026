# Installing the VNC tab for cockpit

## Install the VNC Server on the PC

```
sudo apt-get update
sudo apt install xfce4 xfce4-goodies xorg dbus-x11 x11-xserver-utils
sudo apt install tigervnc-standalone-server tigervnc-common

```

## Configure the VNC server

* Run `vncserver` and set a password, choose not to set a view-only password
* Create a backup file for the config file ~/.vnc/xstartup
    `sudo cp ~/.vnc/xstartup ~/.vnc/xstartup.original`

* Replace the content and copy the following  into the ~/.vnc/xstartup file 
```
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4

gnome-session -session=gnome-classic
gnome-panel

```

## Copy the custom cockpit tab files

* `git clone https://github.com/technopremium/cockpit_vnc.git`

* Setup the files
`sudo cp -r cockpit_vnc /usr/local/share/dlbt_os`
`sudo chmod 777 /usr/local/share/dlbt_os/cockpit_vnc`
`sudo cp -r cockpit_vnc/start_vnc.py /usr/local/share/dlbt_os/py_backend`
`sudo chmod +x /usr/local/share/dlbt_os/py_backend/start_vnc.py`

* Create the cockpit custom tab  
  `cd /usr/local/share/dlbt_os/cockpit_vnc`
  `ln -snf $PWD ~/.local/share/cockpit/cockpit_vnc`