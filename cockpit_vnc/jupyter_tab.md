
## Installing the jupyter interface tab
* `cp noVNC /usr/local/share/dlbt_os/py_backend/`
* `sudo chmod --recursive 777 /usr/local/share/dlbt_os/py_backend/`

* Copy the dlbt folder to /usr/local/share/dlbt_os
  `sudo mkdir /usr/local/share/dlbt_os`
  `sudo cp -r jupyter_docker /usr/local/share/dlbt_os`

* Create the cockpit custom tab
  `mkdir -p ~/.local/share/cockpit`
  `cd /usr/local/share/dlbt_os/jupyter_docker`
  `ln -snf $PWD ~/.local/share/cockpit/jupyter_docker`

* Check if the tab was correctly added
  `cockpit-bridge --packages`

* Python backend for the jupyter tab
  `sudo cp -r py_backend /usr/local/share/dlbt_os`

* Replace the folder
  `sudo rm -r /usr/local/share/dlbt_os/jupyter_docker`
  `sudo cp -r jupyter_docker /usr/local/share/dlbt_os`
  `cd /usr/local/share/dlbt_os/jupyter_docker`
  `ln -snf $PWD ~/.local/share/cockpit/jupyter_docker`
