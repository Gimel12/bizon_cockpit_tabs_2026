#!/bin/bash
# Reviewed factory-image cleanup. Never run this on a customer installation.
set -euo pipefail
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
umask 077

FACTORY_PATHS=(
  /etc/netplan/90-NM-c223fe1d-54d3-4d35-a795-21ba8a1bc0d7.yaml
  /var/lib/NetworkManager/secret_key
  /var/backups/bizon-ai-20261104
  /var/backups/bizon-driver-20261104
  /var/backups/bizon-log-remediation-20261104
  /var/backups/bizon-packages-20261104
  /var/backups/bizon-seal-image.pre-ai-agent-20261104
  /var/backups/bizon-storage-protection-20261104
  /var/backups/bizon-storage-validation-20261104
  /var/backups/bizon-legacy-storage-20261104
  /var/backups/bizon-sealer-before-factory-cleanup
  /var/lib/bizon-storage/jobs/ce1253d2b4694b7a85f8c8a078236228
  /var/lib/bizon-storage-validation
  /var/mail/bizon
  /home/bizon/storage-protection-validation.log
  /home/bizon/security-package-review-20261104
  /home/bizon/bizon-ai-update-progress.log
  /home/bizon/bizon-base-update-progress.log
  /home/bizon/storage-ui-verification.json
  /home/bizon/storage-lab-20261104
  /home/bizon/driver-update-20261104
  /home/bizon/storage-protection-20261104
  /home/bizon/bizon-ai-update-20261104
  /home/bizon/vnc-v617-assets
  /home/bizon/theme-v618-assets
  /home/bizon/test_container_actions.py
  /home/bizon/acceptance.py
  /home/bizon/bizon-retire-legacy-storage.py
  /home/bizon/legacy-storage-backup.json
  /home/bizon/.local/state/bizon/vnc
  /home/bizon/.local/state/bizon/notebooks
  /home/bizon/.local/share/bizon-ai-agent
  /root/.local/share/bizon-ai-agent
  /root/.bash_history
  /home/bizon/.bash_history
  /home/bizon/.zsh_history
  /home/bizon/.python_history
  /home/bizon/.local/share/recently-used.xbel
  /home/bizon/snap/firefox/common/.mozilla/firefox
  /home/bizon/.mozilla/firefox
  /home/bizon/.config/google-chrome
  /home/bizon/.config/chromium
  /home/bizon/.local/share/keyrings
  /home/bizon/.ssh/known_hosts
  /home/bizon/.ssh/known_hosts.old
  /home/bizon/.cache/google-chrome
  /home/bizon/.cache/chromium
  /home/bizon/snap/firefox/common/.cache/mozilla
  /home/bizon/.local/share/main.py/QtWebEngine
  /home/bizon/.local/share/-c/QtWebEngine
  /home/bizon/.cache/main.py
  /home/bizon/.cache/-c
  /home/bizon/.cache/bizon-qml-smoke.py
  /home/bizon/.local/share/data/file__0.localstorage
  /home/bizon/.bizon_app_cache
  /home/bizon/.vnc
  /home/bizon/.local/share/Trash
  /home/bizon/.cache/thumbnails
  /home/bizon/.cache/tracker3
  /home/bizon/.local/share/gvfs-metadata
  /home/bizon/.local/share/org.gnome.TextEditor/recently-used.xbel
  /home/bizon/.local/share/org.gnome.TextEditor/session.gvariant
  /home/bizon/.history
  /home/bizon/.lesshst
  /home/bizon/.viminfo
  /home/bizon/.wget-hsts
  /home/bizon/.xsession-errors
  /home/bizon/.xsession-errors.old
  /root/.history
  /root/.zsh_history
  /root/.python_history
  /root/.lesshst
  /root/.viminfo
  /root/.wget-hsts
  /root/.xsession-errors
  /root/.xsession-errors.old
  /root/.local/share/recently-used.xbel
  /root/.local/share/org.gnome.TextEditor/recently-used.xbel
  /root/.local/share/org.gnome.TextEditor/session.gvariant
  /home/bizon/.claude.json
  /home/bizon/.claude/.credentials.json
  /home/bizon/.claude/backups
  /home/bizon/.claude/cache
  /home/bizon/.claude/downloads
  /home/bizon/.claude/file-history
  /home/bizon/.claude/history.jsonl
  /home/bizon/.claude/mcp-needs-auth-cache.json
  /home/bizon/.claude/paste-cache
  /home/bizon/.claude/projects
  /home/bizon/.claude/session-env
  /home/bizon/.claude/sessions
  /home/bizon/.claude/settings.json
  /home/bizon/.claude/settings.local.json
  /home/bizon/.claude/shell-snapshots
  /home/bizon/.cache/claude-cli-nodejs
  /home/bizon/.local/state/claude
  /home/bizon/.codeium/windsurf
  /home/bizon/.local/share/opencode
  /home/bizon/.local/state/opencode/prompt-history.jsonl
  /home/bizon/.config/Code
  /home/bizon/.vscode-server/data
  /home/bizon/.windsurf-server/data
  /home/bizon/.local/share/devin/cli
  /home/bizon/.cache/devin
  /home/bizon/.ollama/history
  /home/bizon/.gitconfig
  /home/bizon/.docker/buildx/activity
  /home/bizon/.docker/buildx/refs
  "/home/bizon/.config/LM Studio/.org.chromium.Chromium.NfxiSz"
  "/home/bizon/.config/LM Studio/Cache"
  "/home/bizon/.config/LM Studio/Code Cache"
  "/home/bizon/.config/LM Studio/Crashpad"
  "/home/bizon/.config/LM Studio/DawnCache"
  "/home/bizon/.config/LM Studio/DawnGraphiteCache"
  "/home/bizon/.config/LM Studio/DawnWebGPUCache"
  "/home/bizon/.config/LM Studio/GPUCache"
  "/home/bizon/.config/LM Studio/Local Storage"
  "/home/bizon/.config/LM Studio/Network Persistent State"
  "/home/bizon/.config/LM Studio/Preferences"
  "/home/bizon/.config/LM Studio/Session Storage"
  "/home/bizon/.config/LM Studio/Shared Dictionary"
  "/home/bizon/.config/LM Studio/SingletonCookie"
  "/home/bizon/.config/LM Studio/SingletonLock"
  "/home/bizon/.config/LM Studio/SingletonSocket"
  "/home/bizon/.config/LM Studio/Trust Tokens"
  "/home/bizon/.config/LM Studio/Trust Tokens-journal"
  "/home/bizon/.config/LM Studio/blob_storage"
  "/home/bizon/.config/LM Studio/logs"
  "/home/bizon/.config/Docker Desktop/Network Persistent State"
  "/home/bizon/.config/Docker Desktop/Cookies"
  "/home/bizon/.config/Docker Desktop/Cookies-journal"
  "/home/bizon/.config/Docker Desktop/TransportSecurity"
)
IDENTITY_PATHS=(/var/lib/bizon-api/local-token /var/lib/systemd/random-seed /etc/machine-id /var/lib/dbus/machine-id)
LOG_PATHS=(/var/log/auth.log /var/log/syslog /var/log/wtmp /var/log/btmp /var/log/lastlog)

usage() {
  echo 'Usage: bizon-seal-image --dry-run | --seal-and-poweroff'
  echo 'Factory image only. Export evidence, close Cockpit/browsers, log out other sessions, and stop work first.'
  echo 'The explicit --seal-and-poweroff action deletes listed factory data and shuts down.'
}

require_root() {
  [[ $EUID == 0 ]] || { echo 'Run the reviewed factory sealer as administrator.' >&2; return 1; }
}

helper_path() {
  local directory
  directory=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
  if [[ -f "$directory/seal_preflight.py" ]]; then
    printf '%s\n' "$directory/seal_preflight.py"
  else
    printf '%s\n' /usr/local/libexec/bizon-seal-preflight
  fi
}

expand_private_session_files() {
  # Only these filename families are variable; never expand an entire account/cache directory.
  local account
  for account in "$@"; do
    FACTORY_PATHS+=("$account"/.bash_history-*.tmp "$account"/.docker/.token_seed*)
    FACTORY_PATHS+=("$account"/.vscode-server/.*.token "$account"/.vscode-server/.*.pid "$account"/.vscode-server/.*.log)
    FACTORY_PATHS+=("$account"/.windsurf-server/.*.token "$account"/.windsurf-server/.*.pid "$account"/.windsurf-server/.*.log)
  done
}

expand_paths() {
  # Exact system identity/log families and narrowly scoped session artifacts.
  shopt -s nullglob
  expand_private_session_files /home/bizon /root
  IDENTITY_PATHS+=(/etc/ssh/ssh_host_* /etc/cockpit/ws-certs.d/*.cert /etc/cockpit/ws-certs.d/*.key)
  local path
  ROTATED_LOGS=()
  for path in "${LOG_PATHS[@]}"; do
    ROTATED_LOGS+=("$path".[0-9]* "$path".gz)
  done
  shopt -u nullglob
}

preflight() {
  /usr/bin/python3 -I "$(helper_path)" -- "${FACTORY_PATHS[@]}" "${IDENTITY_PATHS[@]}" "${LOG_PATHS[@]}" "${ROTATED_LOGS[@]}"
}

print_plan() {
  local path
  echo 'PREVIEW: no files, services, identities or power state are changed.'
  echo 'Require no active work, browsers, desktop/Cockpit or other login sessions.'
  echo 'Stop SSH/Cockpit activation sockets and the SSH listener; recheck; stop idle API/Cockpit and rsyslog.'
  echo 'Set /var/lib/bizon-image/needs-firstboot before removing identities.'
  for path in "${FACTORY_PATHS[@]}" "${IDENTITY_PATHS[@]}" "${ROTATED_LOGS[@]}"; do printf 'Remove: %s\n' "$path"; done
  for path in "${LOG_PATHS[@]}"; do printf 'Truncate existing regular log: %s\n' "$path"; done
  echo 'Create uninitialized /etc/machine-id and restore /var/lib/dbus/machine-id symlink.'
  echo 'Rotate journal, wait 2 seconds, vacuum archives older than 1 second, sync, power off.'
  echo 'Keep OS, models, Anaconda, Docker images, Documents and all unlisted files.'
  echo 'Fresh sealing/shutdown logs may remain. This is not secure erasure of disk free space.'
}

remove_path() { /usr/bin/python3 -I "$(helper_path)" --remove "$1"; }

truncate_log() {
  /usr/bin/python3 -I "$(helper_path)" --truncate "$1"
}

seal() {
  # Preflight requires KillMode=process: stop only sshd's listener, not this accepted connection.
  /usr/bin/systemctl stop cockpit.socket ssh.socket ssh.service
  preflight
  /usr/bin/systemctl stop bizon-api.service cockpit.service
  if /usr/bin/systemctl cat rsyslog.service >/dev/null 2>&1; then /usr/bin/systemctl stop rsyslog.service; fi
  /usr/bin/install -d -m700 /var/lib/bizon-image
  /usr/bin/touch /var/lib/bizon-image/needs-firstboot
  local path
  for path in "${FACTORY_PATHS[@]}" "${IDENTITY_PATHS[@]}" "${ROTATED_LOGS[@]}"; do remove_path "$path"; done
  printf 'uninitialized\n' > /etc/machine-id
  /usr/bin/chmod 444 /etc/machine-id
  /usr/bin/ln -s /etc/machine-id /var/lib/dbus/machine-id
  for path in "${LOG_PATHS[@]}"; do truncate_log "$path"; done
  /usr/bin/journalctl --rotate
  /usr/bin/sleep 2
  /usr/bin/journalctl --vacuum-time=1s
  /usr/bin/sync
  /usr/bin/systemctl poweroff
}

main() {
  if [[ $# != 1 || ( "$1" != --dry-run && "$1" != --seal-and-poweroff ) ]]; then usage; return 2; fi
  require_root
  expand_paths
  if [[ $1 == --dry-run ]]; then print_plan; preflight; return; fi
  # An explicit action is still refused if any preflight check fails; no changes yet.
  preflight
  exec 9>/run/lock/bizon-image-seal.lock
  /usr/bin/flock -n 9 || { echo 'Another image-sealing operation is running.' >&2; return 1; }
  trap 'echo "Sealing did not finish. Do not capture this image; resolve the error and rerun or restore the factory backup." >&2' ERR
  seal
}

if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi
