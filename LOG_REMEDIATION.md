# Local alert and log cleanup — 2026-11-04

This is a host provisioning change, not a Cockpit tab update. It was applied to the Ubuntu 24.04 image at `192.168.1.148`. It does not restart the desktop, change storage protection, modify the NVIDIA driver, or erase journal records.

## What changed

- Removed execute bits from `/etc/udev/rules.d/60-persistent-storage-hptblock.rules` (`0755` → `0644`), preserving its contents. Udev had warned on every rule reload.
- Replaced the masked, unconfigured `postfix` package with Ubuntu's `dma` package. Postfix's remaining `sendmail` binary had failed when sudo and mdadm submitted local alerts because `/etc/postfix/main.cf` was absent.
- Kept local alert delivery: `root` aliases to `bizon`, with messages stored in `/var/mail/bizon`. No SMTP server or external account was introduced.
- Set DMA's smarthost to `127.0.0.1`. Local recipients are delivered normally; non-local recipients cannot use direct Internet delivery. With no local SMTP listener, non-local attempts fail/defer visibly rather than reaching an external relay. Administrators must explicitly configure external delivery if they need it later.

DMA does not listen for SMTP connections. See the [Ubuntu 24.04 DMA manual](https://manpages.ubuntu.com/manpages/noble/man8/dma.8.html).

## Reproduce on this image baseline

Run the following as an administrator after inspecting the machine's mail configuration. Existing customer mail or external aliases must be preserved and reviewed, not overwritten.

1. Count files in `/var/spool/postfix/{active,incoming,deferred,maildrop,hold,corrupt}`. Continue only if all counts are zero. Back up `/etc/postfix`, `/etc/aliases`, `/etc/mailname`, `/var/spool/postfix`, and existing Postfix unit overrides into a root-only directory. Download the installed Postfix `.deb` for rollback. On this image the backup is `/var/backups/bizon-log-remediation-20261104`, mode `0700`; Postfix was `3.8.6-1ubuntu0.1`.
2. Inspect `apt-get -s install dma`: the reviewed transaction removed only Postfix and installed only DMA. Do not use `autoremove` as part of this fix.
3. Preseed and replace the packages:

   ```sh
   printf '%s\n' 'dma dma/mailname string localhost' 'dma dma/relayhost string 127.0.0.1' | debconf-set-selections
   DEBIAN_FRONTEND=noninteractive apt-get -y --no-install-recommends install dma
   DEBIAN_FRONTEND=noninteractive apt-get -y purge postfix
   ```

4. Install `/etc/dma/dma.conf` with owner `root:mail` and mode `0640`:

   ```text
   # BIZON: local system alerts only. No SMTP listener.
   # Keep non-local recipients on loopback; never use direct external delivery.
   SMARTHOST 127.0.0.1
   PORT 25
   MAILNAME localhost
   ALIASES /etc/aliases
   SPOOLDIR /var/spool/dma
   ```

5. Preserve `/etc/aliases`; if no root alias exists, append `root: bizon`. Retain `postmaster: root`. This baseline had no other active aliases. Keep the file owned by root, mode `0644`.
6. Remove only the HighPoint rule's execute bits:

   ```sh
   chmod a-x /etc/udev/rules.d/60-persistent-storage-hptblock.rules
   ```

No udev device trigger or service restart is needed for the permission correction.

## Verification

- Submit a clearly labelled local test with `/usr/sbin/sendmail -D -oi -t`, addressed only to `root`, then verify its unique marker in `/var/mail/bizon`. Do not send external test mail.
- On this package the new mailbox is owned by `bizon:mail`, mode `0620`: the owner can read/write and the mail group can write. Do not loosen its permissions to make a test pass.
- Submit to a unique nonexistent local user: DMA must return a nonzero status and record the rejection in the journal. This proves delivery failures remain visible.
- Check `ss -ltnp` for absence of ports 25, 465 and 587, `apt-get check`, and `systemctl --failed`.
- Confirm `/usr/sbin/sendmail` belongs to DMA and that no new `fatal: open /etc/postfix/main.cf` entries appear after replacement.
- Keep the factory test message and protected rollback backup out of customer images during the existing image-sealing process; do not erase logs during troubleshooting.

The live checks passed. DMA is `0.13-1build3`; no dependency packages were added beyond DMA. The first validation script expected mailbox mode `0660`, while DMA correctly created the stricter `0620`; the assertion was corrected without changing permissions.

## Other logs reviewed

- The earlier storage worker OOM occurred in `/var/lib/bizon-storage-validation/backend.py` against disposable loop-backed fixtures. The prior storage validation report documents the corrected memory policy and direct backing I/O, followed by 21 passing integration checks. Current workers retain `MemoryHigh=15%` and `MemoryMax=25%`; no new limit change was warranted.
- VNC GNOME session errors coincide with earlier acceptance-test desktop teardown. No VNC process, listener, or credential file remained after the completed tests.
- OpenIPMI is correctly skipped by the hardware condition on this board, not failed.
- NVIDIA's repeating HDMI pixel-clock warning concerns the attached MSI monitor's advertised range. No NVIDIA Xid, GPU reset, thermal fault, or physical-disk I/O error was found in the current boot. ACPI firmware warnings, optional UDisks module probes and Bluetooth feature warnings were retained for visibility rather than suppressed.

Host-specific evidence is stored outside the repository in `login-refresh-20261104/` alongside the image maintenance reports. These checks do not replace physical controller/IPMI testing or validation after cloning.
