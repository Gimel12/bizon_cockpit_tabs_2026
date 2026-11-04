# BIZON Cockpit tabs

Nine custom tabs across seven signed packages for the hardened BIZON OS 6.1 image: an AI assistant using local models or Claude with optional computer control, GPU status/control, authenticated VNC, Docker images, notebooks, tutorials, signed updates, drive health/load testing, and Linux software RAID management. [BIZON AI](AI_AGENT.md) documents provider setup, per-request Cockpit authority, private history, limits, and image sealing. OS drives are explicitly protected from all performance tests. Drive reports retain temperature and error history with model/serial identification. See [Storage Lab](STORAGE.md) for safeguards, reports and validation.

## Shared workspace design

All ten custom page entrypoints use the same BIZON workspace styling: readable type, outlined icons, floating panels and one compact Light/Dark selector in the Cockpit toolbar. Dark is the default. The choice is saved in the browser and synchronized across open tabs; it does not change OS or account settings. The surrounding Cockpit navigation adopts the same palette while retaining native navigation and administration controls. The nine BIZON tabs use Cockpit's native **Apps** section, above the original **System** and **Tools** sections, including immediately after login.

Shared tokens, appearance control, icons and shell styling live in `cockpit_support/theme/`. Page-specific layout overrides consume those tokens. With `jsdom@26` available in `NODE_PATH`, run `node test_theme.cjs`, `node test_workspace_ui.cjs`, `node test_gpu_docker_ui.cjs`, `node test_storage_ui.cjs` and `node test_vnc_ui.cjs` for UI regressions. Run `python3 -m unittest test_navigation test_updater` to verify native navigation and signed-release validation.

## Customer updates

Open **Update Tabs → Check for updates**. Enable **Administrative access** in Cockpit, then choose **Install update** and confirm. The updater accepts only signed releases from this repository; the public verification key is installed with the OS. The previous installed release is retained for **Restore previous version**. Reloading Cockpit applies the new tabs without restarting the workstation or its workloads.

A network error, missing release, invalid signature, modified download, unsafe archive, or failed validation leaves the active tabs unchanged. Application code remains owned by root. This updater does not update the OS, drivers, BIZON API runtime, or the updater trust key.

## Maintainer workflow

1. Make and review changes, then run `python3 test_storage.py`, `python3 test_updater.py`, `python3 -m unittest test_agent_backend test_ai_executor`, `node test_ai_ui.cjs` (with `jsdom` in `NODE_PATH`) and `node test_vnc_socket.cjs`. Test on a hardened BIZON workstation using `acceptance.py` (administrator; prompts for the existing account password) and `test_container_actions.py` (uses temporary containers and a prepared test image).
2. Build signed assets with `python3 build_release.py --version vX.Y.Z --sequence N --key /secure/offline/private-key.pem --out /path/to/assets`. Use a strictly increasing integer sequence. Keep the private signing key outside this repository and every customer image.
3. Publish a GitHub release at the matching tag with `manifest.json`, `manifest.json.sig`, and `tabs.tar.gz`. Mark the intended stable release as latest. Never replace signed assets for an existing release; publish a new version.
4. Test an actual **Check → Install → Reload** from the preceding version. Also test rollback and reinstalling the latest release.

First-time provisioning on the hardened OS only: review this checkout, download the three signed release assets, and run `sudo ./deploy.sh /path/to/assets`. Existing legacy images need the OS security migration first; copying tabs alone does not harden their API, SSH, or privileged helpers.

## Login appearance and image provisioning

The blue login wallpaper and dark sign-in panel live in `cockpit_support/branding/`. The reviewed installer `install_cockpit_branding.py` registers these assets through Cockpit 314's supported XDG data search path for both web-service instance types. `deploy.sh` installs this integration after activating a signed release. It preserves Cockpit's packaged login code, authentication and TLS, and backs up any replaced configuration. Existing web-service instances keep their current settings until they end; no sessions are restarted by the installer.

On a previously provisioned image with a verified release containing these assets, run `sudo python3 -I install_cockpit_branding.py` once. Future signed tab updates switch the artwork automatically. Rolling back to a release without branding uses the last installed fallback artwork. `sudo python3 -I install_cockpit_branding.py --remove` restores the backed-up systemd configuration. The wallpaper uses the built-in image generation tool; it contains no credentials or customer information.

**Existing customer images need that one-time administrator integration for the new login appearance.** A tab-only update delivers the new navigation immediately but cannot register the login web service's environment. See [LOG_REMEDIATION.md](LOG_REMEDIATION.md) for the separately applied local-mail and HighPoint permission fixes; these belong to image provisioning, not signed tab updates.

## Remote desktop

Open **VNC Remote Desktop → Connect to desktop**. A connection card shows startup progress and offers Cancel. Failed or stalled connections return a clear Retry action after at most 45 seconds. The connected toolbar provides Full screen and Disconnect; the display automatically fits the available space. Disconnecting ends this separate virtual desktop and its applications, so save your work first.

For UI regression checks, install `jsdom@26` in a temporary test directory and run `NODE_PATH=/path/to/node_modules node test_vnc_ui.cjs` and `node test_vnc_socket.cjs`. The lifecycle suite covers manual startup, split responses, authentication, errors, timeout, cancellation, reconnection and cleanup.

## Validation boundaries

The VNC **Full screen** button fills the display and hides Cockpit navigation. Use **Exit full screen** or Escape to return; move to the upper-right corner to see the floating controls. The normal view also fits the available browser height without a page scrollbar.

VNC starts a separate virtual desktop via the authenticated Cockpit channel, uses per-session credentials and loopback listeners, and cleans up on disconnect. Notebook launches use a private-network HTTPS listener and a per-notebook token. A first-use self-signed certificate must be verified by the customer. Only BIZON-managed notebooks belonging to the current user are affected by **Stop All**.

AI answers require a configured provider or local model. Computer control runs with the selected account or explicit per-request administrator authority; user mode is not a sandbox. See [AI setup, validation, and clone cleanup](AI_AGENT.md). HighPoint and IPMI-positive tests require representative hardware. Automated tests and one test workstation do not guarantee every hardware/browser combination.
