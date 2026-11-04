# BIZON Cockpit tabs

Nine custom tabs across seven signed packages for the hardened BIZON OS 6.1 image: AI diagnostics, GPU status/control, authenticated VNC, Docker images, notebooks, tutorials, signed updates, drive health/load testing, and Linux software RAID management. OS drives are explicitly protected from all performance tests. Drive reports retain temperature and error history with model/serial identification. See [Storage Lab](STORAGE.md) for safeguards, reports and validation.

## Shared workspace design

All ten custom page entrypoints use the same BIZON workspace styling: readable type, outlined icons, floating panels and a shared Light/Dark appearance selector. Light is the default. The choice is saved in the browser and synchronized across open tabs; it does not change OS or account settings. The surrounding Cockpit navigation adopts the same palette while retaining native navigation and administration controls.

Shared tokens, header, icons and shell styling live in `cockpit_support/theme/`. Page-specific layout overrides consume those tokens. With `jsdom@26` available in `NODE_PATH`, run `node test_theme.cjs`, `node test_workspace_ui.cjs`, `node test_gpu_docker_ui.cjs`, `node test_storage_ui.cjs` and `node test_vnc_ui.cjs` for UI regressions.

## Customer updates

Open **Update Tabs → Check for updates**. Enable **Administrative access** in Cockpit, then choose **Install update** and confirm. The updater accepts only signed releases from this repository; the public verification key is installed with the OS. The previous installed release is retained for **Restore previous version**. Reloading Cockpit applies the new tabs without restarting the workstation or its workloads.

A network error, missing release, invalid signature, modified download, unsafe archive, or failed validation leaves the active tabs unchanged. Application code remains owned by root. This updater does not update the OS, drivers, BIZON API runtime, or the updater trust key.

## Maintainer workflow

1. Make and review changes, then run `python3 test_storage.py`, `python3 test_updater.py` and `node test_vnc_socket.cjs`. Test on a hardened BIZON workstation using `acceptance.py` (administrator; prompts for the existing account password) and `test_container_actions.py` (uses temporary containers and a prepared test image).
2. Build signed assets with `python3 build_release.py --version vX.Y.Z --sequence N --key /secure/offline/private-key.pem --out /path/to/assets`. Use a strictly increasing integer sequence. Keep the private signing key outside this repository and every customer image.
3. Publish a GitHub release at the matching tag with `manifest.json`, `manifest.json.sig`, and `tabs.tar.gz`. Mark the intended stable release as latest. Never replace signed assets for an existing release; publish a new version.
4. Test an actual **Check → Install → Reload** from the preceding version. Also test rollback and reinstalling the latest release.

First-time provisioning on the hardened OS only: review this checkout, download the three signed release assets, and run `sudo ./deploy.sh /path/to/assets`. Existing legacy images need the OS security migration first; copying tabs alone does not harden their API, SSH, or privileged helpers.

## Remote desktop

Open **VNC Remote Desktop → Connect to desktop**. A connection card shows startup progress and offers Cancel. Failed or stalled connections return a clear Retry action after at most 45 seconds. The connected toolbar provides Full screen and Disconnect; the display automatically fits the available space. Disconnecting ends this separate virtual desktop and its applications, so save your work first.

For UI regression checks, install `jsdom@26` in a temporary test directory and run `NODE_PATH=/path/to/node_modules node test_vnc_ui.cjs` and `node test_vnc_socket.cjs`. The lifecycle suite covers manual startup, split responses, authentication, errors, timeout, cancellation, reconnection and cleanup.

## Validation boundaries

The VNC **Full screen** button fills the display and hides Cockpit navigation. Use **Exit full screen** or Escape to return; move to the upper-right corner to see the floating controls. The normal view also fits the available browser height without a page scrollbar.

VNC starts a separate virtual desktop via the authenticated Cockpit channel, uses per-session credentials and loopback listeners, and cleans up on disconnect. Notebook launches use a private-network HTTPS listener and a per-notebook token. A first-use self-signed certificate must be verified by the customer. Only BIZON-managed notebooks belonging to the current user are affected by **Stop All**.

AI answers require a configured provider or local model. HighPoint and IPMI-positive tests require representative hardware. Automated tests and one test workstation do not guarantee every hardware/browser combination.
