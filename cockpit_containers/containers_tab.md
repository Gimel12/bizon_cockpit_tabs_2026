
## Installing the jupyter interface tab
* Install the necessary libraries (If it's the first time)
  `sudo apt-get update`
  `sudo apt-get install python3-pip`
  `conda install pip`
  `pip3 install docker`  
  `pip3 install pyinstaller`

* Add the docker permission group (if it's not created already)
  `sudo groupadd docker`
  `sudo usermod -a -G docker $MY_USER` # change $NY_USER with the actual user
  Log out and back in.

* Copy the dlbt folder to /usr/local/share/dlbt_os
  `sudo mkdir /usr/local/share/dlbt_os`
  `chmod 777 - R /usr/local/share/dlbt_os`
  `git clone https://github.com/technopremium/cockpit_containers.git`
  `sudo cp -r cockpit_containers /usr/local/share/dlbt_os`

* Create the cockpit custom tab
  `mkdir -p ~/.local/share/cockpit`   (If it's the first tab)
  `cd /usr/local/share/dlbt_os/cockpit_containers`
  `ln -snf $PWD ~/.local/share/cockpit/cockpit_containers`
  
* Check if the tab was correctly added
  `cockpit-bridge --packages`

* Python backend for the containers tab
  `sudo cp -r py_backend /usr/local/share/dlbt_os`

* Update the tab
  `sudo rm -r /usr/local/share/dlbt_os/cockpit_containers`  
  `git clone https://github.com/technopremium/cockpit_containers.git /usr/local/share/dlbt_os/`