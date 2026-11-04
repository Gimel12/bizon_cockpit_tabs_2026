#!/usr/bin/python3 -I
"""Install the BIZON CPU/RAM terminal runner without starting a workload."""
import argparse
import ast
import base64
import json
import os
from pathlib import Path
import re
import stat
import subprocess


ROOT_UID = 0
ROOT_GID = 0
RUNNER = Path('/usr/local/libexec/bizon-cpu-ram-test.py')
LAUNCHER = Path('/usr/local/bin/bizon-cpu-ram-test')
BASHRC = Path('/home/bizon/.bashrc')
SKEL = Path('/etc/skel/.bashrc')
REPORTS = Path('/var/lib/bizon-cpu-ram-test/runs')
SOURCE = Path(__file__).resolve().parent / 'provision/bizon_cpu_ram_test.py'
TARGETS = (RUNNER, LAUNCHER, BASHRC, SKEL)
BEGIN = '# BEGIN BIZON CPU/RAM TERMINAL TEST'
END = '# END BIZON CPU/RAM TERMINAL TEST'
ALIASES = {
    'cpu-ram-test': 'sudo /usr/local/bin/bizon-cpu-ram-test start',
    'cpu-ram-status': 'sudo /usr/local/bin/bizon-cpu-ram-test status --watch',
    'cpu-ram-stop': 'sudo /usr/local/bin/bizon-cpu-ram-test stop',
    'cpu-ram-report': 'sudo /usr/local/bin/bizon-cpu-ram-test report',
}
HELP = {
    'cpu-ram-test': 'Start a 1-hour CPU/RAM test (85% RAM target)',
    'cpu-ram-status': 'Watch CPU/RAM test progress',
    'cpu-ram-stop': 'Stop the CPU/RAM test',
    'cpu-ram-report': 'Show the latest CPU/RAM report',
}
WRAPPER = (b'#!/bin/sh\n# BIZON CPU/RAM test: preserve argument boundaries.\n'
           b'exec /usr/bin/python3 -I /usr/local/libexec/bizon-cpu-ram-test.py "$@"\n')
DEPENDENCIES = {
    'python3': ('/usr/bin/python3',),
    'stress-ng': ('/usr/bin/stress-ng',),
    'rasdaemon': ('/usr/sbin/rasdaemon', '/usr/bin/rasdaemon'),
    'ras-mc-ctl': ('/usr/sbin/ras-mc-ctl',),
    'journalctl': ('/usr/bin/journalctl',),
    'systemctl': ('/usr/bin/systemctl', '/bin/systemctl'),
    'systemd-run': ('/usr/bin/systemd-run', '/bin/systemd-run'),
}


class InstallError(RuntimeError):
    pass


def at(root, path):
    return root / path.relative_to('/')


def parent_check(path, root):
    for parent in (path, *path.parents):
        if parent != root and root not in parent.parents:
            break
        if not parent.exists() and not parent.is_symlink():
            continue
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise InstallError('Expected a real directory: ' + str(parent))
        allowed_home = parent == at(root, BASHRC.parent)
        sticky = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if not allowed_home and (info.st_uid not in (0, ROOT_UID) or (info.st_mode & 0o022 and not sticky)):
            raise InstallError('Unsafe parent directory: ' + str(parent))


def snapshot(path, required=False):
    if not path.exists() and not path.is_symlink():
        if required:
            raise InstallError('Required shell configuration is missing: ' + str(path))
        return None
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 2 * 1024 * 1024:
        raise InstallError('Expected a small regular file without links: ' + str(path))
    return {'data': base64.b64encode(path.read_bytes()).decode(),
            'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}


def record(data, mode=0o755):
    return {'data': base64.b64encode(data).decode(), 'mode': mode, 'uid': ROOT_UID, 'gid': ROOT_GID}


def write_atomic(path, value):
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    temp_name = '.bizon-cpu-ram-' + os.urandom(12).hex()
    try:
        fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                     0o600, dir_fd=descriptor)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(base64.b64decode(value['data'], validate=True))
            os.fchown(stream.fileno(), value['uid'], value['gid'])
            os.fchmod(stream.fileno(), value['mode'])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path.name, src_dir_fd=descriptor, dst_dir_fd=descriptor)
    finally:
        try:
            os.unlink(temp_name, dir_fd=descriptor)
        except FileNotFoundError:
            pass
        os.close(descriptor)


def rewrite_bashrc(data, retire_anydesk=True):
    text = data.decode('utf-8')
    begin_count, end_count = text.count(BEGIN), text.count(END)
    if begin_count != end_count or begin_count > 1:
        raise InstallError('Ambiguous CPU/RAM shell integration markers.')
    pattern = re.escape(BEGIN) + r'\n.*?^' + re.escape(END) + r'\n?'
    unowned = re.sub(pattern, '', text, flags=re.M | re.S) if begin_count else text
    for name in ALIASES:
        if re.search(r'^\s*(?:alias\s+' + re.escape(name) + r'\s*=|(?:function\s+)?'
                     + re.escape(name) + r'\s*\()', unowned, re.M):
            raise InstallError('Existing unmanaged command: ' + name)
    if retire_anydesk:
        matches = list(re.finditer(r"^alias anydesk-restore='([^']*)'\n?", text, re.M))
        if re.search(r'^\s*alias\s+anydesk-restore\s*=', text, re.M) and not matches:
            raise InstallError('Unrecognized anydesk-restore alias; review before replacement.')
        for match in matches:
            lines = [line.strip() for line in match[1].splitlines() if line.strip()]
            if lines != ['sudo rm -f /etc/anydesk/service.conf', 'sudo reboot']:
                raise InstallError('Unexpected anydesk-restore alias; review it before replacement.')
        if len(matches) > 1:
            raise InstallError('Duplicate anydesk-restore aliases.')
        text = re.sub(r"^alias anydesk-restore='[^']*'\n?", '', text, flags=re.M)
    starts = list(re.finditer(r"^alias bizonhelp='\n", text, re.M))
    if len(starts) > 1:
        raise InstallError('Duplicate bizonhelp definitions.')
    if starts:
        start = starts[0].end()
        end = re.search(r"^echo'[ \t]*(?:\n|$)", text[start:], re.M)
        if not end:
            raise InstallError('Unrecognized bizonhelp menu; no files changed.')
        stop = start + end.start()
        lines = text[start:stop].splitlines(keepends=True)
        prefixes = tuple('echo -e ' + name + ' ' for name in HELP)
        lines = [line for line in lines if not line.startswith(prefixes)
                 and not (retire_anydesk and line.startswith('echo -e anydesk-restore '))]
        anchors = [i for i, line in enumerate(lines) if line.startswith('echo -e cpu-test ')]
        if len(anchors) != 1:
            raise InstallError('Expected the existing cpu-test help entry.')
        additions = ['echo -e ' + name + ' ----"\\033[31;1m' + label + '\\033[0m"\n'
                     for name, label in HELP.items()]
        lines[anchors[0] + 1:anchors[0] + 1] = additions
        text = text[:start] + ''.join(lines) + text[stop:]
    block = BEGIN + '\n' + ''.join("alias " + name + "='" + command + "'\n"
                                   for name, command in ALIASES.items())
    block += 'if ! type bizonhelp >/dev/null 2>&1; then\n    function bizonhelp {\n'
    block += "        printf '%s\\n' 'BIZON CPU/RAM test commands'\n"
    block += ''.join("        printf '%s\\n' '" + name + ' — ' + label + "'\n" for name, label in HELP.items())
    block += '    }\nfi\n' + END + '\n'
    if begin_count:
        text = re.sub(pattern, lambda unused: block, text, flags=re.M | re.S)
    else:
        text += ('' if text.endswith('\n') else '\n') + '\n' + block
    return text.encode('utf-8')


def check_shell(data):
    # Parse only: never source customer .bashrc or execute its commands as root.
    result = subprocess.run(['/bin/bash', '-n'], input=data, capture_output=True, check=False,
                            env={'PATH': '/usr/bin:/bin', 'LANG': 'C', 'BASH_ENV': '/dev/null'})
    if result.returncode:
        raise InstallError('Updated shell configuration did not pass bash syntax validation.')


def install(root, source, backup_dir):
    if os.geteuid() != 0:
        raise InstallError('Run this reviewed installer as administrator.')
    root = Path(root).resolve(strict=True)
    for name, locations in DEPENDENCIES.items():
        if not any(at(root, Path(location)).is_file() and os.access(at(root, Path(location)), os.X_OK)
                   for location in locations):
            raise InstallError('Install the required Ubuntu dependency first: ' + name)
    source = Path(source)
    source_data = source.read_bytes()
    if len(source_data) > 2 * 1024 * 1024:
        raise InstallError('Runner source is unexpectedly large.')
    ast.parse(source_data, filename=str(source))
    originals = {}
    for path in TARGETS:
        parent_check(at(root, path).parent, root)
        originals[str(path)] = snapshot(at(root, path), path in (BASHRC, SKEL))
    anydesk_present = any(at(root, Path(prefix) / command).exists()
                          for prefix in ('/usr/bin', '/usr/local/bin', '/usr/sbin', '/usr/local/sbin', '/home/bizon/.local/bin')
                          for command in ('anydesk', 'anydesk-restore'))
    desired = {str(RUNNER): record(source_data), str(LAUNCHER): record(WRAPPER)}
    for path in (BASHRC, SKEL):
        entry = originals[str(path)].copy()
        updated = rewrite_bashrc(base64.b64decode(entry['data']), retire_anydesk=not anydesk_present)
        check_shell(updated)
        entry['data'] = base64.b64encode(updated).decode()
        desired[str(path)] = entry
    backup = Path(os.path.abspath(backup_dir))
    for path in TARGETS:
        if backup == at(root, path) or at(root, path) in backup.parents:
            raise InstallError('Backup directory overlaps an installation target.')
    parent_check(backup, Path(backup.anchor))
    if not backup.exists():
        backup.mkdir(mode=0o700)
        os.chown(backup, ROOT_UID, ROOT_GID)
    info = backup.lstat()
    if info.st_uid != ROOT_UID or info.st_mode & 0o077:
        raise InstallError('Backup directory must be administrator-owned with mode 0700.')
    state = backup / 'cpu-ram-install-backup.json'
    if state.exists() or state.is_symlink():
        entry = snapshot(state, True)
        if entry['uid'] != ROOT_UID or entry['mode'] & 0o077:
            raise InstallError('Unsafe installer backup.')
        saved = json.loads(base64.b64decode(entry['data']))
        if saved.get('schema') != 1 or set(saved.get('originals', {})) != {str(p) for p in TARGETS}:
            raise InstallError('Unrecognized installer backup.')
    else:
        write_atomic(state, record(json.dumps({'schema': 1, 'originals': originals}).encode(), 0o600))
    for directory in (at(root, RUNNER.parent), at(root, LAUNCHER.parent), at(root, REPORTS)):
        parent_check(directory, root)
        directory.mkdir(parents=True, exist_ok=True)
        if directory == at(root, REPORTS):
            os.chown(directory.parent, ROOT_UID, ROOT_GID)
            directory.parent.chmod(0o700)
            os.chown(directory, ROOT_UID, ROOT_GID)
            directory.chmod(0o700)
    completed = []
    try:
        for path in TARGETS:
            key = str(path)
            if originals[key] == desired[key]:
                continue
            target = at(root, path)
            if snapshot(target) != originals[key]:
                raise InstallError('File changed while preparing installation: ' + key)
            completed.append(path)
            write_atomic(target, desired[key])
    except BaseException:
        for path in reversed(completed):
            previous = originals[str(path)]
            if previous is None:
                at(root, path).unlink(missing_ok=True)
            else:
                write_atomic(at(root, path), previous)
        raise
    return {'changed': [str(path) for path in completed], 'backup': str(state),
            'reports': str(REPORTS), 'workload_started': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'))
    parser.add_argument('--source', type=Path, default=SOURCE)
    parser.add_argument('--backup-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(install(args.root, args.source, args.backup_dir), indent=2))
    except (InstallError, OSError, ValueError, SyntaxError) as exc:
        parser.exit(1, 'CPU/RAM installation refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
