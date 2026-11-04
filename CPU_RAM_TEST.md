# CPU and RAM test from the terminal

Use this test when checking workstation stability before shipment. Save work
first: the test deliberately puts the CPU and RAM under sustained load. Keep the
machine ventilated. It does not benchmark or write directly to storage drives.

Open a new terminal after installation, then use:

| Command | Purpose |
|---|---|
| `cpu-ram-test` | Start the default one-hour CPU and RAM test |
| `cpu-ram-test --duration 30m` | Run for thirty minutes |
| `cpu-ram-status` | Watch the current test |
| `cpu-ram-stop` | Stop the test |
| `cpu-ram-report` | Show the latest saved report |
| `bizonhelp` | Show the workstation command menu |

The default memory setting is `--memory-percent 85`, targeting 85% of total RAM.
The runner caps this at currently available memory minus a reserve of at least
2 GiB or 10% of total RAM, whichever is larger, and refuses when too little RAM
is available. `--cpu-workers` and `--memory-mib` are also
available for deliberately small validation runs. Do not treat a small smoke
test as a full hardware stability test.

The original `cpu-test` command still opens **s-tui**. The new commands use the
normal administrator prompt; no password is stored and no passwordless sudo
rule is installed. Commands passed to the runner remain separate arguments.

`start` displays live progress. **Ctrl+C during start stops that test**;
Ctrl+C in `status --watch` only leaves the monitor. Use `start --detach` to start
without attaching the terminal. The systemd-managed test continues if the SSH
connection closes; reconnect and use the status or stop command.

For scripts or an existing shell without the aliases, use the full command:

```sh
sudo /usr/local/bin/bizon-cpu-ram-test start --duration 30m
sudo /usr/local/bin/bizon-cpu-ram-test status --watch
sudo /usr/local/bin/bizon-cpu-ram-test stop
sudo /usr/local/bin/bizon-cpu-ram-test report
```

Reports are stored under `/var/lib/bizon-cpu-ram-test/runs/` with administrator-only
access. The latest-run pointer is `latest.json`; `report` prints the text report
path. Export factory test reports before sealing the customer image.

## What the test checks

The runner uses all logical CPU threads plus one large RAM worker, with
`stress-ng --verify --abort`. The memory worker keeps its allocation and cycles
through memory test methods. CPU methods also cycle. The unprivileged workload
runs separately from the monitor with a memory ceiling, no swap allowance, and
a time limit. Stopping the monitor also stops its workload.

Progress updates every five seconds: CPU utilization, available RAM, peak CPU
temperature, new RAS/kernel events, and monitoring gaps. The default temperature
stop is **95 °C**; `--max-temperature` accepts 70–105 °C for a technician who has
checked the processor's limits. A critically low RAM reserve or a new hardware
error also stops the test. Unsupported temperature sensors are shown as unavailable.

RAS monitoring records a baseline before applying load. It checks the
`rasdaemon` database, EDAC corrected/uncorrected counters, the kernel journal,
and the recorder's own trace instance. Existing errors remain intact and are
not counted as new errors. Recorder restarts, counter resets, missing records,
and lost trace events make the monitoring result incomplete. A test never clears
hardware counters, injects hardware errors, or changes CPU frequency settings.

Each run saves `report.txt`, `summary.json`, `stress-ng.log`, `telemetry.jsonl`,
`kernel-events.log`, and before/after `ras-mc-ctl` summaries. EDAC increments
and RAS events may describe the same error and must not be added together.

Read the result literally:

- **Errors detected:** a new hardware/runtime event, counter increment, or safety stop needs review.
- **Incomplete / stopped:** the workload or monitoring did not finish successfully.
- **Completed, ECC unavailable:** the load finished and no new errors were observed,
  but the board/kernel does not expose ECC counters. This is not an ECC pass.
- **Completed, no new errors observed:** available checks completed without new errors.
  It is still not a guarantee of fault-free hardware.

The OS reserve and firmware-reserved memory cannot be fully tested while Ubuntu
is running. Full physical-memory coverage requires an offline memory test.
On the development workstation (Core Ultra 9 285K), firmware reports no memory
error correction and EDAC controllers are absent; MCE recording is available.

Implementation references: [stress-ng documentation](https://colinianking.github.io/stress-ng/)
and [rasdaemon documentation](https://github.com/mchehab/rasdaemon). The runner was
validated against Ubuntu 24.04's installed stress-ng 0.17.06 and rasdaemon 0.8.0.

## Provisioning

The core runner is `provision/bizon_cpu_ram_test.py`. The standalone installer
copies it to `/usr/local/libexec/bizon-cpu-ram-test.py`, installs the command
launcher, and updates `/home/bizon/.bashrc` and `/etc/skel/.bashrc`. New user
accounts receive the same aliases and a small help menu if they do not already
have `bizonhelp`. Existing unrelated shell settings and `cpu-test` are preserved.

The obsolete `anydesk-restore` alias and its help line are retired only when the
AnyDesk command is absent and the alias matches the old delete-config/reboot
implementation. Unknown conflicting aliases cause the installer to stop for
review. The installer never sources user shell configuration as administrator.

Required installed commands: `python3`, `stress-ng`, `rasdaemon`, `ras-mc-ctl`,
`journalctl`, `systemctl`, and `systemd-run`. Missing dependencies cause a refusal; the installer does not
install packages, start workloads, enable services, or reboot the machine.

From a reviewed checkout:

```sh
sudo /usr/bin/python3 -I ./install_cpu_ram_test.py \
  --backup-dir /var/backups/bizon-cpu-ram-install-20261104
```

The backup is private and contains original shell configuration. Export it off
the master and remove the local copy before capturing customer media. Repeating
the installation is safe and preserves that first backup. A later write failure
restores earlier changed files. The installer also accepts `--root` for a mounted
image and `--source` for an explicitly reviewed runner source.

Manufacturing validation runs should include `start --factory-test` so the
report is marked as factory data for the image preparation workflow. This flag
does not change load limits or turn a brief test into hardware certification.

Validate the installer without stressing hardware:

```sh
python3 -m unittest -v test_cpu_ram_install
```

These tests use temporary filesystem fixtures, parse shell configuration without
executing it, and exercise aliases/help with harmless fixture menus. The core
runner has separate workload and safety tests.
