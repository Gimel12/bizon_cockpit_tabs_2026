# Bizon Cockpit Tabs

Custom Cockpit web UI tabs for Bizon workstations.

## Tabs

| Tab | Directory | Description |
|-----|-----------|-------------|
| Bizon AI | `cockpit_bizon_ai/` | AI chat assistant with Claude & Ollama |
| GPU Monitor | `cockpit_gpu/` | Real-time GPU monitoring, power control, and history |
| VNC Remote Desktop | `cockpit_vnc/` | Launch and connect to a VNC remote desktop session |
| Docker Images | `cockpit_containers/` | Manage Docker images |
| My Notebooks | `cockpit_jupyter/` | Create and manage Jupyter notebook containers |
| Video Tutorials | `cockpit_tutorials/` | Embedded Notion page with video tutorials |
| Update Tabs | `cockpit_support/` | Check for updates and update all tabs from GitHub |

## Requirements

- Ubuntu 24.04+
- Cockpit (`apt install cockpit`)
- Python 3, git
- Docker
- NVIDIA drivers + `nvidia-smi` (for GPU Monitor)

## First-Time Install (on a new machine)

```bash
# One-liner:
curl -fsSL https://raw.githubusercontent.com/Gimel12/bizon_cockpit_tabs_2026/main/deploy.sh | sudo bash

# Or manually:
sudo git clone https://github.com/Gimel12/bizon_cockpit_tabs_2026.git /opt/bizon-cockpit-tabs
cd /opt/bizon-cockpit-tabs
sudo bash deploy.sh
```

This will:
1. Clone the repo to `/opt/bizon-cockpit-tabs`
2. Copy all `cockpit_*` tabs to `/usr/local/share/dlbt_os/`
3. Create symlinks in `~/.local/share/cockpit/`
4. Restart Cockpit

## Updating (for end users)

After the initial install, users can update directly from the Cockpit web UI:

1. Open Cockpit → **Update Tabs** (last item in sidebar)
2. Click **Update All Web-UI**
3. Confirm → the system pulls the latest from GitHub and redeploys all tabs
4. Page auto-refreshes when done

Users can also click **Check for Updates** to see if new versions are available.

## Development Workflow

1. Make changes to any `cockpit_*` directory
2. Commit and push to `main`
3. Users click "Update All Web-UI" on their machines — done!

```bash
git add -A
git commit -m "Add new feature X"
git push origin main
```

## Architecture

```
/opt/bizon-cockpit-tabs/         ← Git repo (clone of this repo)
  ├── cockpit_*/                 ← Source tab directories
  ├── update_tabs.py             ← Backend script called by Update Tabs page
  ├── deploy.sh                  ← Initial install / deploy script
  └── README.md

/usr/local/share/dlbt_os/        ← Deployed tabs (copied from repo)
  └── cockpit_*/

~/.local/share/cockpit/          ← Symlinks for Cockpit discovery
  └── cockpit_* → /usr/local/share/dlbt_os/cockpit_*
```

## Tab Order in Sidebar

Controlled by `order` field in each `manifest.json`:

1. Bizon AI (10)
2. GPU Monitor (30)
3. VNC Remote Desktop (40)
4. Docker Images (50)
5. My Notebooks (60)
6. Video Tutorials (70)
7. Update Tabs (100)
