#!/usr/bin/python3 -I
"""Factory-sealing support. Default checks are read-only; --remove/--truncate require explicit root use."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys


class CheckError(Exception):
    pass


CPU_RAM_ROOT = Path('/var/lib/bizon-cpu-ram-test')
CPU_RAM_RUN_ID = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}')
CPU_RAM_REPORT_FILES = {
    'summary.json', 'report.txt', 'stress-ng.log', 'ras-before.txt',
    'ras-after.txt', 'kernel-events.log', 'telemetry.jsonl',
}
STATE_LOCK_PATHS = (
    '/var/lib/dpkg/lock', '/var/lib/dpkg/lock-frontend', '/var/lib/apt/lists/lock',
    '/var/cache/apt/archives/lock', '/run/lock/bizon-tabs-update.lock',
    '/var/lib/bizon-storage/operation.lock', '/run/lock/bizon-cpu-ram-test.lock',
    '/home/bizon/.local/share/bizon-ai-agent/active.lock',
    '/root/.local/share/bizon-ai-agent/active.lock',
)


def command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CheckError('Could not complete a required readiness check: ' + Path(args[0]).name) from error
    if result.returncode:
        raise CheckError('Could not complete a required readiness check: ' + Path(args[0]).name)
    return result.stdout


def process_category(argv, comm):
    names = {Path(arg).name for arg in argv}
    if any('/cockpit_bizon_ai/agent/' in arg and arg.endswith(('/backend.py', '/executor.py')) for arg in argv):
        return 'BIZON AI request or computer-control session'
    if any('/storage/' in arg and arg.endswith('/backend.py') for arg in argv) or 'bizon-vnc-session' in names:
        return 'BIZON storage or VNC session'
    if 'bizon-tabs-update' in names or 'bizon-tabs-update.py' in names or 'update_tabs.py' in names:
        return 'Cockpit tab update'
    if names & {'bizon-cpu-ram-test', 'bizon-cpu-ram-test.py', 'bizon_cpu_ram_test.py'} or comm == 'stress-ng' or comm.startswith('stress-ng-'):
        return 'CPU/RAM hardware test'
    # Ubuntu keeps this watcher idle until shutdown. Actual workers, locks and units still block.
    if comm == 'unattended-upgr' and argv == ['/usr/bin/python3', '/usr/share/unattended-upgrades/unattended-upgrade-shutdown', '--wait-for-signal']:
        return None
    if comm in {'apt', 'apt-get', 'dpkg', 'unattended-upgr', 'do-release-upgr', 'snap'}:
        return 'software installation or update'
    if comm in {'firefox', 'chrome', 'chromium', 'chromium-browse', 'brave', 'vivaldi-bin', 'QtWebEngineProc', 'lm-studio', 'LM Studio', 'docker-desktop', 'Docker Desktop'}:
        return 'browser using a factory profile'
    if comm in {'claude', 'opencode', 'code', 'code-insiders', 'windsurf', 'cursor', 'devin'} or any(
        '/.local/share/claude/versions/' in arg or '/@anthropic-ai/claude-code/' in arg
        or '/.vscode-server/' in arg or '/.windsurf-server/' in arg for arg in argv
    ):
        return 'developer editor or AI CLI session'
    if comm in {'jupyter', 'jupyter-lab', 'jupyter-noteboo', 'fio', 'nvme-stress-test', 'gpu_burn'}:
        return 'notebook or hardware workload'
    return None


def ancestors(proc=Path('/proc')):
    result = set()
    pid = os.getpid()
    while pid and pid not in result:
        result.add(pid)
        try:
            status = (proc / str(pid) / 'status').read_text()
            pid = int(re.search(r'^PPid:\s+(\d+)', status, re.M)[1])
        except (OSError, TypeError, ValueError):
            break
    return result


def process_checks(proc=Path('/proc')):
    issues = set()
    # A sealer launched through an AI executor is still active AI work; do not exempt ancestors.
    excluded = {os.getpid()}
    for path in proc.iterdir():
        if not path.name.isdigit() or int(path.name) in excluded:
            continue
        try:
            argv = (path / 'cmdline').read_bytes().decode('utf-8', 'replace').strip('\0').split('\0')
            category = process_category(argv, (path / 'comm').read_text().strip())
            if category:
                issues.add('Close or finish the active ' + category + '.')
        except FileNotFoundError:
            pass  # Process exited during the snapshot.
        except PermissionError as error:
            raise CheckError('Cannot inspect all running processes.') from error
    return sorted(issues)


def interactive_shell(argv):
    if not argv or argv[0].startswith('-'):
        return True
    skip = False
    for index, arg in enumerate(argv[1:], 1):
        if skip:
            skip = False; continue
        if arg in {'-o', '-O', '+o', '+O', '--rcfile', '--init-file'}:
            skip = True; continue
        if arg == '--':
            return index + 1 >= len(argv)
        if arg.startswith('--'):
            continue
        if arg.startswith('-'):
            if 'i' in arg[1:]:
                return True
            if 'c' in arg[1:]:
                return index + 1 >= len(argv)
            continue
        if not arg.startswith('+'):
            return False  # An explicit script, before any script arguments.
    return True  # Flag-only shells can read an interactive terminal.


def invocation_checks(proc=Path('/proc')):
    for pid in ancestors(proc):
        try:
            comm = (proc / str(pid) / 'comm').read_text().strip()
            argv = (proc / str(pid) / 'cmdline').read_bytes().decode('utf-8', 'replace').strip('\0').split('\0')
        except FileNotFoundError:
            continue
        if comm in {'bash', 'zsh', 'sh', 'dash', 'fish', 'ksh'}:
            if interactive_shell(argv):
                return ['Use a noninteractive, dedicated SSH command; an interactive parent shell can rewrite factory history.']
    return []


def fd_mount(fd):
    try:
        text = Path('/proc/self/fdinfo/' + str(fd)).read_text()
        return re.search(r'^mnt_id:\s+(\d+)$', text, re.M)[1]
    except (OSError, TypeError) as error:
        raise CheckError('Could not confirm cleanup filesystem boundaries.') from error


def clean_path(text, truncate=False):
    """Pin every parent with O_NOFOLLOW. Never follow symlinks or descend into mounted filesystems."""
    path = Path(text)
    if not path.is_absolute() or '..' in path.parts or len(path.parts) < 3:
        raise CheckError('Unsafe cleanup path.')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:-1]:
            try:
                child = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                return
            os.close(fd); fd = child
        name = path.name
        if truncate:
            try:
                target = os.open(name, os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=fd)
            except FileNotFoundError:
                return
            try:
                if not stat.S_ISREG(os.fstat(target).st_mode) or fd_mount(target) != fd_mount(fd):
                    raise CheckError('Refusing non-regular or mounted log: ' + text)
                os.ftruncate(target, 0)
            finally:
                os.close(target)
        else:
            remove_entry(fd, name, fd_mount(fd))
    finally:
        os.close(fd)


def remove_entry(parent, name, mount):
    try:
        info = os.stat(name, dir_fd=parent, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(info.st_mode):
        os.unlink(name, dir_fd=parent)
        return
    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        if fd_mount(child) != mount:
            raise CheckError('Refusing cleanup across a mount boundary.')
        with os.scandir(child) as entries:
            for entry in entries:
                remove_entry(child, entry.name, mount)
    finally:
        os.close(child)
    os.rmdir(name, dir_fd=parent)


def path_checks(paths, mounts):
    issues = []
    for text in paths:
        path = Path(text)
        if not path.is_absolute() or '..' in path.parts or path == Path('/'):
            issues.append('Invalid cleanup path.'); continue
        if any(parent.is_symlink() for parent in path.parents):
            issues.append('Cleanup path has a symlink parent: ' + text)
        if any(mount == path or path in mount.parents for mount in mounts):
            issues.append('Unmount the filesystem within cleanup path: ' + text)
    return issues


def mount_paths():
    values = []
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        raw = line.split()[4]
        values.append(Path(re.sub(r'\\([0-7]{3})', lambda match: chr(int(match[1], 8)), raw)))
    return values


def session_checks():
    issues = []
    parent_pids = ancestors()
    for line in command(['/usr/bin/loginctl', 'list-sessions', '--no-legend', '--no-pager']).splitlines():
        session = line.split()[0]
        details = command(['/usr/bin/loginctl', 'show-session', session, '-p', 'User', '-p', 'Name', '-p', 'Leader', '-p', 'Type', '-p', 'Service', '-p', 'Class'])
        data = dict(item.split('=', 1) for item in details.splitlines() if '=' in item)
        if data.get('Class') == 'greeter' or data.get('Name') == 'gdm':
            continue
        if int(data.get('Leader') or 0) in parent_pids:
            continue
        if int(data.get('User') or 0) >= 1000 or data.get('User') == '0':
            issues.append('Log out the other ' + ('Cockpit' if data.get('Service') == 'cockpit' else 'desktop/SSH') + ' session before sealing.')
    return sorted(set(issues))


def locked_state_checks(paths=None, locks=Path('/proc/locks')):
    paths = [Path(p) for p in STATE_LOCK_PATHS] if paths is None else paths
    identities = set()
    for path in paths:
        try:
            info = path.stat(); identities.add((os.major(info.st_dev), os.minor(info.st_dev), info.st_ino))
        except FileNotFoundError:
            pass
    for line in locks.read_text().splitlines():
        for token in line.split():
            match = re.fullmatch(r'([0-9a-f]+):([0-9a-f]+):(\d+)', token)
            if match and (int(match[1], 16), int(match[2], 16), int(match[3])) in identities:
                return ['An AI/storage/CPU-RAM/update lock is held; finish that operation before sealing.']
    return []


def cpu_ram_factory_paths(root=CPU_RAM_ROOT, owner=0):
    """Return only validated, completed factory-run paths. Never alter a report or status."""
    def trusted(path, directory=False):
        info = path.lstat()
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if (not expected_type(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022
                or (not directory and info.st_nlink != 1)):
            raise CheckError('CPU/RAM reports contain an unsafe file or directory; review them before sealing.')
        return info

    def json_object(path):
        trusted(path)
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC), 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != owner or info.st_mode & 0o022 or info.st_nlink != 1:
                raise CheckError('CPU/RAM report metadata changed while being checked.')
            data = stream.read(1024 * 1024 + 1)
        if len(data) > 1024 * 1024:
            raise CheckError('CPU/RAM report metadata is too large; review it before sealing.')
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError) as error:
            raise CheckError('CPU/RAM report metadata is invalid; review it before sealing.') from error
        if not isinstance(result, dict):
            raise CheckError('CPU/RAM report metadata must be an object; review it before sealing.')
        return result

    try:
        root.lstat()
    except FileNotFoundError:
        return []
    if any(parent.is_symlink() for parent in root.parents):
        raise CheckError('CPU/RAM reports have a symlink parent; review them before sealing.')
    trusted(root, directory=True)
    if any(path.name not in {'runs', 'latest.json'} for path in root.iterdir()):
        raise CheckError('Unrecognized CPU/RAM report artifacts need review/export before sealing.')
    runs = root / 'runs'
    selected = []
    if runs.exists() or runs.is_symlink():
        trusted(runs, directory=True)
        for run in sorted(runs.iterdir()):
            if not CPU_RAM_RUN_ID.fullmatch(run.name):
                raise CheckError('Unrecognized CPU/RAM run identifier; review/export it before sealing.')
            trusted(run, directory=True)
            for artifact in run.iterdir():
                if artifact.name not in CPU_RAM_REPORT_FILES:
                    raise CheckError('Unrecognized CPU/RAM report artifacts need review/export before sealing.')
                trusted(artifact)
            try:
                summary = json_object(run / 'summary.json')
            except FileNotFoundError as error:
                raise CheckError('A CPU/RAM run has no summary; reconcile it before sealing.') from error
            if summary.get('run_id') != run.name:
                raise CheckError('CPU/RAM run metadata does not match its directory; reconcile it before sealing.')
            if not isinstance(summary.get('phase'), str) or summary['phase'] not in {'completed', 'stopped', 'failed', 'incomplete'}:
                raise CheckError('A CPU/RAM record still reports active or unknown work; reconcile it before sealing.')
            if summary.get('factory_test') is not True:
                raise CheckError('Customer or unmarked CPU/RAM reports need review/export; they are not on the factory cleanup list.')
            selected.append(run)
    latest = root / 'latest.json'
    if latest.exists() or latest.is_symlink():
        metadata = json_object(latest)
        if (set(metadata) != {'run_id'} or not isinstance(metadata['run_id'], str)
                or metadata['run_id'] not in {run.name for run in selected}):
            raise CheckError('The latest CPU/RAM pointer does not identify a reviewed factory run; reconcile it before sealing.')
        selected.insert(0, latest)
    return selected


def cpu_ram_selection_checks(paths):
    selected = set(cpu_ram_factory_paths())
    planned = {Path(path) for path in paths if Path(path) == CPU_RAM_ROOT or CPU_RAM_ROOT in Path(path).parents}
    if selected != planned:
        return ['CPU/RAM factory reports changed after the cleanup preview; rerun the preview before sealing.']
    return []


def state_checks():
    issues = []
    for path in Path('/var/lib/bizon-storage/jobs').glob('*/state.json'):
        try:
            if json.loads(path.read_text()).get('status') in {'running', 'queued'}:
                issues.append('A storage record still reports active work; reconcile it before sealing.')
        except (OSError, ValueError):
            issues.append('A storage record cannot be checked; resolve it before sealing.')
    # Do not discard additional factory/customer runs added after this manifest was reviewed.
    known = 'ce1253d2b4694b7a85f8c8a078236228'
    if any(path.is_dir() and path.name != known for path in Path('/var/lib/bizon-storage/jobs').glob('*')):
        issues.append('Additional drive-test records need review/export and an explicit cleanup-list update.')
    if any(Path('/var/lib/bizon-storage/plans').glob('*.json')):
        issues.append('Pending RAID plans need review before sealing.')
    for path in Path('/sys/block').glob('md*/md/sync_action'):
        if path.read_text().strip() not in {'idle', 'frozen'}:
            issues.append('Wait for RAID synchronization or checking to finish.')
    if any(path.name != 'flush' for path in Path('/var/spool/dma').glob('*')):
        issues.append('Local mail is queued; resolve delivery before clearing factory mail.')
    return sorted(set(issues))


def active_unit_checks():
    units = command([
        '/usr/bin/systemctl', 'list-units', '--state=active,activating,deactivating',
        '--no-legend', '--no-pager', 'bizon-agent-*', 'bizon-storage-*',
        'bizon-cpu-ram-test.service', 'bizon-cpu-ram-load.service',
        'bizon-security-upgrade.service', 'apt-daily-upgrade.service',
    ])
    return ['An AI/storage/CPU-RAM/software update unit is still active.'] if units.strip() else []


def readiness(paths):
    issues = path_checks(paths, mount_paths())
    issues += cpu_ram_selection_checks(paths)
    helper = Path('/usr/local/libexec/bizon-firstboot')
    try:
        info = helper.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or not os.access(helper, os.X_OK):
            issues.append('The installed first-boot helper is not a trusted root executable.')
    except FileNotFoundError:
        issues.append('The first-boot helper is missing.')
    if command(['/usr/bin/systemctl', 'is-enabled', 'bizon-firstboot.service']).strip() != 'enabled':
        issues.append('The first-boot identity service is not enabled.')
    if command(['/usr/bin/systemctl', 'show', 'ssh.service', '-p', 'KillMode', '--value']).strip() != 'process':
        issues.append('SSH must use KillMode=process so sealing can stop the listener without terminating its invocation.')
    issues += active_unit_checks() + process_checks() + invocation_checks() + session_checks() + locked_state_checks() + state_checks()
    if Path('/run/docker.sock').exists():
        if command(['/usr/bin/docker', 'ps', '-q']).strip():
            issues.append('Stop running Docker containers, including notebooks, before sealing.')
    # Other installed identities are preserved, not silently erased.
    for directory in ['/home/bizon/.ssh', '/root/.ssh']:
        if any(p.name not in {'known_hosts', 'known_hosts.old'} for p in Path(directory).glob('*')):
            issues.append('Additional SSH files need review before cloning: ' + directory)
    return sorted(set(issues))


def main(argv=None):
    paths = (sys.argv[1:] if argv is None else argv)
    action = paths[0] if paths else ''
    if paths[:1] == ['--']:
        paths = paths[1:]
    if os.geteuid() != 0 or sys.platform != 'linux':
        print('Readiness checks require administrator access on the target Linux workstation.', file=sys.stderr)
        return 1
    try:
        if action == '--factory-cpu-ram-paths':
            if len(paths) != 1:
                raise CheckError('Factory report selection takes no additional arguments.')
            for path in cpu_ram_factory_paths():
                print(path)
            return 0
        if action in {'--remove', '--truncate'}:
            if len(paths) != 2:
                raise CheckError('Cleanup requires exactly one explicit path.')
            clean_path(paths[1], truncate=action == '--truncate')
            return 0
        issues = readiness(paths)
    except (CheckError, OSError, ValueError) as error:
        print('BLOCKED: ' + (str(error) if isinstance(error, CheckError) else 'A required readiness check failed.'), file=sys.stderr)
        return 1
    for issue in issues:
        print('BLOCKED: ' + issue, file=sys.stderr)
    if not issues:
        print('Read-only readiness checks passed. This does not certify a restored clone.')
    return bool(issues)


if __name__ == '__main__':
    sys.exit(main())
