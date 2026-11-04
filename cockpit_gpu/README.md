### Prerequisites
pip install pynvml
pip install json


## Manual Installation 
1. Clone the repo
  `cd /usr/local/share/dlbt_os/`
  `git clone https://github.com/technopremium/cockpit_gpu.git`

2. Link the custom tab
  `cd /usr/local/share/dlbt_os/cockpit_gpu`
  `ln -snf $PWD ~/.local/share/cockpit/cockpit_gpu`
  
* [Optional]Check if the tab was correctly added
  `cockpit-bridge --packages`

3. Install the dependencies for the javascript tab
```
npm install chart.js
```
4. Restart the system for loading the script

Background logging was removed on November 4, 2026. Dashboard samples are session-only.
