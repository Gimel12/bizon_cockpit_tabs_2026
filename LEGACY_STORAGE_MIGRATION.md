# Retiring the legacy storage desktop tools

The old NVMe GUI and its `manual_run.sh` can write directly to a block device.
The old RAID GUI does not use the protected Cockpit backend. They must not remain
alternate entrypoints in the customer image.

`retire_legacy_storage.py` is a one-time **OS provisioning migration**, separate
from the signed Cockpit tab archive. It does not change the tabs or release a new
version. It does not enumerate, mount, format, benchmark or change any drive.

## What changes

- Replace the complete `/usr/local/share/dlbt_os/bza/nvme_stress_test` directory,
  including its Git history and bytecode, with safe `app.py` and `manual_run.sh`
  launchers for `https://localhost:9090/cockpit_support/drives`.
- Replace the complete `/usr/local/share/dlbt_os/bza/raid/raid_gui_bizonOS`
  directory with safe `main.py` and `raid_functions.py` launchers for
  `https://localhost:9090/cockpit_support/raid`. Importing `raid_functions` has no
  action and no longer exposes the legacy storage operations.
- Change `/usr/local/bin/bizon-nvme-gui` and `/usr/local/bin/bizon-raid` to use
  those launchers with the system Python interpreter. They no longer activate
  Conda or depend on Qt.
- Update only the `nvme-stress` and `raid-manager` alias definitions in
  `/home/bizon/.bashrc`. Preserve its other bytes and its ownership/permissions.
  Unknown or duplicate alias definitions cause a refusal before source changes.

Both Cockpit routes must exist in the installed, root-owned manifest before the
migration runs. A regular desktop user gets a browser opened at the fixed HTTPS
URL. An administrator, an SSH session, or a headless session gets the URL printed
only; the launcher never starts a browser as root. Arguments are not forwarded
to a shell, URL or storage command. Cockpit provides its normal sign-in and
administrator controls. A self-signed Cockpit certificate still requires the
existing browser trust step; no certificate check is bypassed.

## Apply after reviewing the change

Backups contain the **entire original application source trees and `.bashrc`**,
which can include private configuration. Prefer a private administrator-owned
directory on external storage. Its parent must already exist. The migration
creates the final directory with mode `0700` and a `0600` JSON backup, or requires
those protections on an existing directory. It rejects links/special files in
the old application trees and never writes into the signed tab directories.

From a reviewed copy of this repository on the workstation:

```sh
sudo /usr/bin/python3 -I ./retire_legacy_storage.py \
  --backup-dir /mnt/private-export/bizon-legacy-storage-20261104
```

If external storage is not available, use this temporary root-only staging
location, then export its contents and remove the staging directory **before
capturing the customer image**:

```sh
sudo /usr/bin/python3 -I ./retire_legacy_storage.py \
  --backup-dir /var/backups/bizon-legacy-storage-20261104
```

For an offline mounted image, add `--root /mnt/bizon-image`. The backup path is a
path on the provisioning computer, not a path relative to that image. Installed
Cockpit links must resolve within the selected mounted filesystem. This migration
does not repair absolute links in an offline image automatically.

The command prints changed paths, backup location and backup SHA-256. Repeating
with the same backup is safe. It refuses to overwrite changes made afterward.
Keep the backup digest and output with the private manufacturing record.

## Verify and recover

Open a new regular desktop terminal and run `nvme-stress` and `raid-manager`.
Each should open the corresponding Cockpit tab. The existing shell's old aliases
also remain safe because their Python entrypoint paths have become launchers.
Over SSH, execute `bizon-nvme-gui` and `bizon-raid` to verify the printed URLs;
`localhost` here means the workstation, not the maintenance computer. No test
needs to start a storage workload.

The migration rolls back completed target replacements if a later write fails.
A power loss can leave a private `.bizon-storage-migration-*` staging directory
beside an old application folder. The restore command below can also recover a
missing target from the valid private backup. Inspect and remove any interrupted
staging directories before imaging; they can contain old application source.
Keep the external backup until the final restore test is accepted.

Rollback **restores the unsafe legacy applications** and is only for deliberate
maintenance, not a shipping configuration:

```sh
sudo /usr/bin/python3 -I ./retire_legacy_storage.py \
  --backup-dir /mnt/private-export/bizon-legacy-storage-20261104 --restore
```

Rollback preserves original contents, owners and permission bits, but does not
preserve original inode numbers or timestamps. It refuses if a target has been
edited since migration. Do not automatically rerun old application installers
or restore their Git checkouts: those can reintroduce the unsafe entrypoints.

## Focused validation

```sh
python3 -m unittest -v test_legacy_storage_migration
```

These tests use temporary directory fixtures and mocked browser launches. They
exercise complete source retirement, alias preservation, private backups,
round-trip restore, idempotence, interrupted writes, modified-file refusal,
path/link rejection, relocated offline images and root/headless/SSH behavior.
They never access block devices or run a benchmark/RAID operation.
