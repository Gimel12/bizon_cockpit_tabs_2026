#!/usr/bin/env python3
"""
update_tabs.py — Pull latest cockpit tabs from GitHub and deploy them.

Usage:
    python3 update_tabs.py --action=update      # git pull + deploy all tabs
    python3 update_tabs.py --action=check        # check if updates are available
    python3 update_tabs.py --action=version      # show current version info

This script is called by the Update Tabs cockpit page via cockpit.spawn().
Output is streamed back to the browser.
"""

import subprocess
import sys
import os
import json
import argparse
import shutil

REPO_URL = "https://github.com/Gimel12/bizon_cockpit_tabs_2026.git"
REPO_DIR = "/opt/bizon-cockpit-tabs"
INSTALL_DIR = "/usr/local/share/dlbt_os"
COCKPIT_USER_DIR = os.path.expanduser("~/.local/share/cockpit")
BRANCH = "main"


def run(cmd, cwd=None):
    """Run a shell command and return output."""
    result = subprocess.run(
        cmd, shell=True, cwd=cwd,
        capture_output=True, text=True, timeout=120
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def emit(msg):
    """Print a message and flush — cockpit.spawn streams stdout."""
    print(msg, flush=True)


def ensure_repo():
    """Clone the repo if it doesn't exist, or verify it's valid."""
    if not os.path.isdir(REPO_DIR):
        emit(f"📥 Cloning repository for the first time...")
        code, out, err = run(f"git clone {REPO_URL} {REPO_DIR}")
        if code != 0:
            emit(f"❌ Clone failed: {err}")
            sys.exit(1)
        emit("✓ Repository cloned successfully.")
    elif not os.path.isdir(os.path.join(REPO_DIR, ".git")):
        emit("⚠️ Repo directory exists but is not a git repo. Re-cloning...")
        shutil.rmtree(REPO_DIR)
        code, out, err = run(f"git clone {REPO_URL} {REPO_DIR}")
        if code != 0:
            emit(f"❌ Clone failed: {err}")
            sys.exit(1)
        emit("✓ Repository cloned successfully.")


def check_for_updates():
    """Check if there are new commits on remote."""
    ensure_repo()

    # Fetch latest
    run(f"git fetch origin {BRANCH}", cwd=REPO_DIR)

    # Compare local vs remote
    code, local_hash, _ = run(f"git rev-parse HEAD", cwd=REPO_DIR)
    code2, remote_hash, _ = run(f"git rev-parse origin/{BRANCH}", cwd=REPO_DIR)

    if local_hash == remote_hash:
        emit("✅ All tabs are up to date.")
        emit(f"Current version: {local_hash[:8]}")
        return False
    else:
        # Count commits behind
        code3, count, _ = run(f"git rev-list HEAD..origin/{BRANCH} --count", cwd=REPO_DIR)
        emit(f"🔔 Update available! {count} new commit(s).")
        emit(f"Local:  {local_hash[:8]}")
        emit(f"Remote: {remote_hash[:8]}")

        # Show what changed
        code4, log, _ = run(
            f"git log HEAD..origin/{BRANCH} --oneline --no-decorate",
            cwd=REPO_DIR
        )
        if log:
            emit(f"\nChanges:\n{log}")
        return True


def deploy_tabs():
    """Copy cockpit_* dirs from repo to install location + symlink."""
    os.makedirs(INSTALL_DIR, exist_ok=True)
    os.makedirs(COCKPIT_USER_DIR, exist_ok=True)

    deployed = 0
    for item in sorted(os.listdir(REPO_DIR)):
        src = os.path.join(REPO_DIR, item)
        if not os.path.isdir(src) or not item.startswith("cockpit_"):
            continue

        dst = os.path.join(INSTALL_DIR, item)
        symlink = os.path.join(COCKPIT_USER_DIR, item)

        # Remove old and copy new
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)

        # Create symlink
        if os.path.islink(symlink):
            os.unlink(symlink)
        elif os.path.exists(symlink):
            shutil.rmtree(symlink)
        os.symlink(dst, symlink)

        emit(f"  ✓ {item}")
        deployed += 1

    emit(f"\n✓ Deployed {deployed} tab(s).")
    return deployed


def do_update():
    """Full update: pull + deploy + restart cockpit."""
    ensure_repo()

    emit("🔄 Pulling latest changes from GitHub...")
    # Reset any local changes and pull
    run(f"git checkout {BRANCH}", cwd=REPO_DIR)
    run("git reset --hard HEAD", cwd=REPO_DIR)
    code, out, err = run(f"git pull origin {BRANCH}", cwd=REPO_DIR)

    if code != 0:
        emit(f"❌ Pull failed: {err}")
        sys.exit(1)

    if "Already up to date" in out:
        emit("ℹ️ Already up to date. Re-deploying anyway...")
    else:
        emit("✓ Pulled latest changes.")

    # Show current commit
    _, commit, _ = run("git log -1 --oneline --no-decorate", cwd=REPO_DIR)
    emit(f"📌 Version: {commit}")

    emit("\n📦 Deploying tabs...")
    deploy_tabs()

    emit("\n🔄 Restarting Cockpit...")
    code, _, err = run("systemctl restart cockpit")
    if code != 0:
        emit(f"⚠️ Could not restart Cockpit: {err}")
        emit("Please restart manually: sudo systemctl restart cockpit")
    else:
        emit("✓ Cockpit restarted.")

    emit("\n✅ Update complete! Refresh the page to see changes.")


def show_version():
    """Show the current installed version."""
    ensure_repo()
    _, commit, _ = run("git log -1 --format='%h %s (%ci)'", cwd=REPO_DIR)
    _, branch, _ = run("git branch --show-current", cwd=REPO_DIR)
    emit(f"Branch: {branch}")
    emit(f"Version: {commit}")

    # List installed tabs
    tabs = sorted([d for d in os.listdir(INSTALL_DIR) if d.startswith("cockpit_")])
    emit(f"\nInstalled tabs ({len(tabs)}):")
    for t in tabs:
        emit(f"  • {t}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--action", default="update", choices=["update", "check", "version"])
    args = parser.parse_args()

    if args.action == "update":
        do_update()
    elif args.action == "check":
        check_for_updates()
    elif args.action == "version":
        show_version()
