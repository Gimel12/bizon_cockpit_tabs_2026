* Update the tab
  `sudo rm -r /usr/local/share/dlbt_os/jupyter_docker`
  `sudo cp -r jupyter_docker /usr/local/share/dlbt_os`
  `sudo rm -r /usr/local/share/dlbt_os/py_backend/`
  `sudo cp -r py_backend/ /usr/local/share/dlbt_os/`
  `cd /usr/local/share/dlbt_os/jupyter_docker`
  `ln -snf $PWD ~/.local/share/cockpit/jupyter_docker`
