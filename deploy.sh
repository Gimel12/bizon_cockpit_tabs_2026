#!/usr/bin/env bash
# deploy.sh — Install Bizon Cockpit tabs from GitHub
#
# First-time install:
#   curl -fsSL https://raw.githubusercontent.com/Gimel12/bizon_cockpit_tabs_2026/main/deploy.sh | sudo bash
#   — or —
#   sudo bash deploy.sh
#
# After install, users can update from the "Update Tabs" cockpit page.
set -euo pipefail

REPO_URL="https://github.com/Gimel12/bizon_cockpit_tabs_2026.git"
REPO_DIR="/opt/bizon-cockpit-tabs"
INSTALL_DIR="/usr/local/share/dlbt_os"
BRANCH="main"

# Detect the main non-root user (fallback to bizon)
MAIN_USER="${SUDO_USER:-bizon}"
MAIN_HOME="$(eval echo ~${MAIN_USER})"
COCKPIT_USER_DIR="${MAIN_HOME}/.local/share/cockpit"

echo "=== Bizon Cockpit Tabs Deploy ==="
echo "User: ${MAIN_USER} | Home: ${MAIN_HOME}"
echo ""

# 1. Clone or pull the repo
if [ ! -d "${REPO_DIR}/.git" ]; then
    echo "📥 Cloning repository..."
    rm -rf "${REPO_DIR}"
    git clone "${REPO_URL}" "${REPO_DIR}"
    cd "${REPO_DIR}" && git checkout "${BRANCH}"
    echo "✓ Cloned to ${REPO_DIR}"
else
    echo "🔄 Pulling latest changes..."
    cd "${REPO_DIR}"
    git fetch origin "${BRANCH}"
    git checkout "${BRANCH}"
    git reset --hard "origin/${BRANCH}"
    echo "✓ Updated to latest"
fi

echo ""
COMMIT=$(cd "${REPO_DIR}" && git log -1 --oneline --no-decorate)
echo "📌 Version: ${COMMIT}"
echo ""

# 2. Deploy cockpit_* directories
mkdir -p "${INSTALL_DIR}"
mkdir -p "${COCKPIT_USER_DIR}"

DEPLOYED=0
for tab_dir in "${REPO_DIR}"/cockpit_*/; do
    [ -d "${tab_dir}" ] || continue
    tab_name="$(basename "${tab_dir}")"

    # Remove old and copy new
    rm -rf "${INSTALL_DIR}/${tab_name}"
    cp -r "${tab_dir}" "${INSTALL_DIR}/${tab_name}"

    # Create user-level symlink for Cockpit discovery
    ln -sfn "${INSTALL_DIR}/${tab_name}" "${COCKPIT_USER_DIR}/${tab_name}"

    echo "  ✓ ${tab_name}"
    DEPLOYED=$((DEPLOYED + 1))
done

echo ""
echo "✓ Deployed ${DEPLOYED} tab(s)"

# 3. Fix ownership
chown -R "${MAIN_USER}:${MAIN_USER}" "${COCKPIT_USER_DIR}"

# 4. Restart Cockpit
echo ""
echo "🔄 Restarting Cockpit..."
systemctl restart cockpit 2>/dev/null || true
echo "✓ Cockpit restarted"

echo ""
echo "=== Deploy complete! ==="
echo "Open https://$(hostname):9090 to access the web UI."
