
## Installing the jupyter interface tab
* Install the necessary libraries (If it's the first time)
  `sudo apt-get update`
  `sudo apt-get install python3-pip`
  `conda install pip`
  `pip3 install docker`  
  
## Requirements for VNC tab
```
  sudo apt-get update
  sudo apt install xfce4 xfce4-goodies xorg dbus-x11 x11-xserver-utils
  sudo apt install tigervnc-standalone-server tigervnc-common
```
### Configure the VNC server

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

## Configuration of Cockpit

* Add the docker permission group (if it's not created already)
  `sudo groupadd docker`
  `sudo usermod -a -G docker $MY_USER` # change $NY_USER with the actual user
  Log out and back in.

* Copy the dlbt folder to /usr/local/share/dlbt_os
  `sudo mkdir /usr/local/share/dlbt_os`
  `chmod 777 - R /usr/local/share/dlbt_os`
  `git clone https://github.com/technopremium/cockpit_support.git`
  `sudo cp -r cockpit_support /usr/local/share/dlbt_os`

* Create the cockpit custom tab
  `mkdir -p ~/.local/share/cockpit`   (If it's the first tab)
  `cd /usr/local/share/dlbt_os/cockpit_support`
  `ln -snf $PWD ~/.local/share/cockpit/cockpit_support`

* Hit reinstall tabs in the Support tab
  `ln -snf /usr/local/share/dlbt_os/cockpit_containers ~/.local/share/cockpit/cockpit_containers`
  `ln -snf /usr/local/share/dlbt_os/cockpit_jupyter ~/.local/share/cockpit/cockpit_jupyter`
  `ln -snf /usr/local/share/dlbt_os/cockpit_vnc ~/.local/share/cockpit/cockpit_vnc`
  
* Check if the tab was correctly added
  `cockpit-bridge --packages`
