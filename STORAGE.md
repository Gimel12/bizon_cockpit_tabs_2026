# BIZON Storage Lab

Two Cockpit tools ship inside the existing signed `cockpit_support` package: **Drive Health & Tests** and **RAID Manager**. This preserves compatibility with the deployed seven-package updater; no new listening service, password database or public API is introduced.

## Drive tests and reports

- Discover NVMe, SATA/SAS and Linux software RAID devices. SMART details include identity, firmware, temperature, wear, power-on hours, media errors and the full vendor record when available. Unsupported SMART is explicitly unknown, never healthy.
- Run simultaneous sequential-read, random-read, sequential-write or 70/30 mixed workloads. Duration is bounded to one hour, queue depth to 64 and selection to 16 devices. fio bypasses the filesystem cache for test I/O.
- Raw-device tests are always read-only, with fio's additional `--readonly` guard and a held read-only device descriptor. Write workloads use a newly allocated, private temporary file on a mounted ext4/XFS/Btrfs data volume under `/mnt`, `/media` or `/srv`. At least 10% and 2 GiB free space must remain. System filesystems are excluded from write tests.
- Jobs run in transient systemd services, so leaving the page does not silently terminate a test. Stop requests end fio and preserve partial results. A stopped, failed or interrupted run is not reported as a passing test. A forced kill/reboot can leave a temporary file; the interrupted report names its directory for administrator inspection.
- Live graphs show fio's cumulative average throughput, not a promised hardware rating. Results include IOPS and mean/P99 completion latency. SMART is captured before and after, with periodic temperature samples.
- HTML reports are standalone and escape customer/device text. Complete JSON includes measurements, configuration, identity and health records. Reports remain root-owned in `/var/lib/bizon-storage/jobs`; download through the authenticated tab. Export wanted reports before image sealing; do not ship factory/customer test history in a cloned image.

## Software RAID

RAID 0, 1, 5, 6 and 10 are supported with minimum/even-member checks. Creation accepts blank, unmounted whole drives only. Existing signatures, partitions, swap, read-only devices and storage holders prevent selection. This tool does not offer a blanket erase action to make a disk eligible.

Every create/delete requires a short-lived server-side plan and typed confirmation. Device identities, disk sequence and availability are rechecked before execution. Operations are serialized against active storage tests. Array deletion requires an unmounted, idle array with unchanged membership; it stops the array and clears member RAID superblocks without running a general filesystem wipe. Changes are recorded under `/var/lib/bizon-storage/raid-*.json`.

New data arrays are recorded by UUID in `/etc/mdadm/mdadm.conf`, preserving unrelated configuration and retaining backups. Formatting/mounting uses Cockpit's existing **Storage** page; this avoids inventing a second filesystem/mount workflow. Consistency checking requests the kernel's `check` action, not `repair`. Inspect mismatch counts and member health. RAID is not a backup. Hardware RAID controllers and reshape/member replacement workflows are outside this release.

## Installation and validation

Current hardened BIZON systems receive both tools using **Update Tabs → Check for updates → Install update**. The existing public verification key, archive verification, anti-replay checks and rollback remain unchanged. Systems lacking dependencies can use **Install missing storage tools**, which installs `fio`, `smartmontools` and `mdadm` from configured Ubuntu repositories on Ubuntu 24.04. It does not perform a distribution upgrade. Legacy unhardened images still need the documented baseline migration.

Run `python3 test_storage.py`, `python3 test_updater.py` and `node test_vnc_socket.cjs`. `test_storage_integration.py` is a root-only lab test with private, disposable loop-backed fixtures; review it before running. It tests real fio and mdadm operations, not production disks. Never interpret virtual-disk performance as physical drive performance.

References: [fio documentation](https://fio.readthedocs.io/en/latest/fio_doc.html), [Linux MD documentation](https://www.kernel.org/doc/html/latest/admin-guide/md.html), [Cockpit privileged process channels](https://cockpit-project.org/guide/latest/cockpit-spawn.html). Design references: [original drive tester](https://github.com/Gimel12/nvme_stress_test) and [original RAID app](https://github.com/Gimel12/raid_managment_software_2025). The older Flask servers are not installed or exposed by these tabs.
