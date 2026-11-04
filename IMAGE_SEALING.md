# Factory image sealing

This is a reviewed cleanup manifest for the factory workstation inspected on November 4, 2026. Installing these tools does not clean files or power off. Do not run the sealer on a customer's working installation.

## Install and preview

From a reviewed checkout on the workstation:

```sh
python3 -I install_image_sealer.py --dry-run
sudo python3 -I install_image_sealer.py --install
sudo /usr/local/sbin/bizon-seal-image --dry-run
```

The installer validates syntax, preserves the original tools once in `/var/backups/bizon-sealer-before-factory-cleanup`, and installs the shell and support helper as root-owned mode 0750. A small first-boot drop-in removes the NetworkManager secret again before networking starts, in case it was rewritten during source shutdown. It keeps the existing first-boot identity service and does not invoke the sealer. The backup itself is on the final cleanup list.

The sealer's `--dry-run` prints only paths and planned actions, performs read-only checks, and reports blockers. It does not create locks, clean files, stop services or power off. It requires root so a successful preview can inspect all relevant processes, sessions and state. A failed readiness probe blocks sealing instead of assuming the machine is idle.

## Before the final action

1. Complete the application/hardware acceptance checks and export the report, required drive-test and CPU/RAM reports, and maintenance backups **off this machine**. The known factory drive test, explicitly marked factory CPU/RAM runs and maintenance directories are deliberately removed.
2. Stop AI requests, storage and CPU/RAM tests, notebooks, Docker containers and updates. Log out of Cockpit and the desktop, close browsers, and close other SSH sessions. Use a dedicated **noninteractive remote command** to invoke the sealer. Interactive parent shells are refused because they can rewrite shell history on exit. The GDM greeter may remain.
3. Review the preview's exact list. New drive-test records, unmarked/customer CPU/RAM reports, pending RAID plans and extra SSH identities require a separate review. The script does not delete arbitrary home-directory files, Documents, models, Anaconda environments, installed programs or Docker images. Review any new factory artifacts that were created after this manifest.
4. Keep a rollback image and Rescuezilla USB ready. Run the final command only when the next boot will be Rescuezilla, not the installed OS.

```sh
ssh -t -o ControlMaster=no -o ControlPath=none bizon@WORKSTATION \
  'sudo /usr/local/sbin/bizon-seal-image --seal-and-poweroff'
```

The exact flag is mandatory. With no flag, an unrecognized flag, or combined flags, the script exits without action. Preflight failures occur before cleanup. Once sealing starts it stops management activation sockets and the SSH listener, rechecks readiness, stops idle management/logging services, marks first boot, removes the listed factory data and identities, clears the five named classic logs and their rotations, rotates the journal, waits two seconds, vacuums archived journals older than one second, syncs and powers off. SSH must use the observed `KillMode=process`, which preserves the accepted connection while stopping the listener. The invocation must not share a multiplexed SSH connection. It does not force-stop a detected active job or logged-in graphical session. Avoid starting any new work during this maintenance window.

If any step fails, **do not capture the image**. Some services may already be stopped or some files removed. Resolve the failure and rerun, or restore the factory backup. A subsequent installed-OS boot will regenerate the identities once the first-boot marker exists; reseal afterward before imaging.

## What is reset

- Existing SSH host keys, Cockpit certificates, local API token, machine ID and system random seed are removed. The existing first-boot service regenerates management identities before their listeners start.
- Factory AI conversations/provider configuration, browser profiles/keyrings, shell/Python history, recent-file history and temporary notebook/VNC credentials are removed for the explicitly listed accounts.
- The **one observed factory Wi-Fi Netplan profile** is removed. Other profiles are untouched. `/var/lib/NetworkManager/secret_key` is removed so NetworkManager creates a new secret on its next start. No network configuration reload is attempted mid-seal.
- Listed maintenance backups, staging folders, factory drive-test results and local factory mail are removed. The DMA local-delivery configuration stays installed.

The customer-baseline reset also removes the reviewed factory developer accounts/history, VS Code's reviewed empty/default user profile, remote-editor session data and tokens, Git identity, Docker build activity, and selected browser/Qt caches. Temporary shell histories and remote-editor token/PID/log files use narrowly scoped patterns only. LM Studio and Docker Desktop keep their application configuration while their reviewed browser storage/cache is reset. Active editor, AI CLI and embedded-browser processes block sealing.

The whole `.cache` directory is never removed. Hugging Face/model caches, installed Claude/OpenCode binaries, Claude plugins, OpenCode local-model configuration, model weights, benchmark code, documents and wallpaper are preserved. The list is intentionally explicit; review new personal data before updating the factory image rather than broadening it to a whole-home deletion.

The cleanup helper pins parent directories with no-follow file descriptors and refuses to descend into another mount, rather than trusting a pathname check made earlier. Its default mode is read-only; the shell invokes its explicit root-only `--remove`/`--truncate` modes only during final sealing.

### CPU/RAM factory reports

Use the CPU/RAM runner's explicit `--factory-test` option for disposable factory validation runs, and export their reports before sealing. The sealer adds individual paths under `/var/lib/bizon-cpu-ram-test/runs/` only when each run has a valid identifier, matching summary, terminal phase, and `factory_test: true`. It accepts only the runner's known report files with trusted ownership and permissions. It also clears `latest.json` when that pointer identifies a selected factory run. The report root and empty `runs` directory remain installed; the next customer test creates its own history.

An active controller, workload unit, stress-ng process or held test lock blocks sealing. Queued/running records, missing or malformed summaries, unexpected files, and ordinary customer/unmarked reports also block it; they are not automatically deleted or relabeled as factory data. Resolve and export those records explicitly before retrying. Failed, stopped and incomplete **terminal** factory runs can be cleaned, but their terminal state does not mean the hardware passed.

The exact CPU/RAM selection is checked again during final readiness checks. If reports changed since selection, sealing stops before cleanup. The runner and sealer coordinate through the image-sealing lock so a new managed test cannot start during cleanup. The reviewed installer backup `/var/backups/bizon-cpu-ram-install-20261104` is also removed; other backup paths are preserved and require separate review.

## Required restored-image validation

Restore onto a spare drive/machine, then check first boot completes, SSH/Cockpit/API identities differ from the source and from a second clone, machine ID differs, and the factory Wi-Fi connection/history/provider keys are absent. Test Ethernet DHCP and customer Wi-Fi setup on the actual hardware: removal of a factory profile does not guarantee every network card will be configured correctly. Re-run application acceptance checks, including VNC, notebooks, updates, and storage OS-drive protection. Perform the deferred physical HighPoint/IPMI checks where applicable.

The factory username/password and hostname are not changed. Assign a unique hostname during per-machine provisioning if desired. Filesystem UUIDs used by root/EFI remain those of the cloned filesystems; do not attach two copies with identical UUIDs while validating boot selection.

Deletion is logical cleanup, not forensic erasure of free space or filesystem journals. Raw sector-by-sector imaging may retain deleted data; use a separately approved sanitization process if that threat is in scope. Current sealing/shutdown journal entries may remain. The allowlist does not certify unrelated credentials, custom files, model caches or additional accounts. Inspect changes made after this manifest before publishing a new image.

## Local checks

```sh
python3 -m unittest discover -s tests -p 'test_image_sealer.py' -v
```

These tests use mocked orchestration and disposable local fixtures. They never install the tools, stop a real service, perform sealing, or touch a disk/RAID device. A real restore test remains required.
