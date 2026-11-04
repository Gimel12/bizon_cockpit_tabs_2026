#!/usr/bin/python3 -I
"""Retire legacy storage GUIs; this provisioning tool never operates on disks.

Original source trees, launchers and .bashrc are saved in a caller-selected,
private backup directory. This file is intentionally outside the signed tabs.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile


ROOT_UID = 0
ROOT_GID = 0
NVME = Path('/usr/local/share/dlbt_os/bza/nvme_stress_test')
RAID = Path('/usr/local/share/dlbt_os/bza/raid/raid_gui_bizonOS')
BASHRC = Path('/home/bizon/.bashrc')
LAUNCHERS = (Path('/usr/local/bin/bizon-nvme-gui'), Path('/usr/local/bin/bizon-raid'))
TARGETS = (NVME, RAID, BASHRC, *LAUNCHERS)
BACKUP_NAME = 'legacy-storage-backup.json'
MAX_BYTES = 16 * 1024 * 1024
URLS = {
    'drives': 'https://localhost:9090/cockpit_support/drives',
    'raid': 'https://localhost:9090/cockpit_support/raid',
}


class MigrationError(RuntimeError):
    pass


def at(root, absolute):
    return root / absolute.relative_to('/')


def require_root():
    if os.geteuid() != 0:
        raise MigrationError('Run this reviewed provisioning tool as administrator.')


def check_parents(path, root):
    """Do not follow symlinks in writable deployment/backup paths."""
    for parent in (path, *path.parents):
        if parent == root.parent or (parent != root and root not in parent.parents):
            break
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode):
            raise MigrationError('Expected a real directory: ' + str(parent))
        # A user's home owns .bashrc; only root may own code directories.
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        if parent != at(root, BASHRC.parent) and (
                info.st_uid not in (0, ROOT_UID) or (info.st_mode & 0o022 and not sticky_root)):
            raise MigrationError('Unsafe directory ownership or permissions: ' + str(parent))


def snapshot(path, *, user_file=False):
    """Bounded, non-following snapshot: reject special files and linked code."""
    entries = {}
    total = 0
    paths = [path]
    while paths:
        item = paths.pop()
        info = item.lstat()
        if not user_file and (info.st_uid != ROOT_UID or info.st_mode & 0o022):
            raise MigrationError('Unsafe code ownership or permissions: ' + str(item))
        entry = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
        if stat.S_ISDIR(info.st_mode):
            entry['kind'] = 'directory'
            paths.extend(sorted(item.iterdir(), reverse=True))
        elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
            total += info.st_size
            if total > MAX_BYTES:
                raise MigrationError('Legacy source exceeds the reviewed backup size limit.')
            entry.update(kind='file', data=base64.b64encode(item.read_bytes()).decode('ascii'))
        else:
            raise MigrationError('Refusing a symlink, hardlink or special file: ' + str(item))
        entries[str(item.relative_to(path))] = entry
    return entries


def encoded_file(data, mode=0o644, uid=None, gid=None):
    uid = ROOT_UID if uid is None else uid
    gid = ROOT_GID if gid is None else gid
    return {'kind': 'file', 'mode': mode, 'uid': uid, 'gid': gid,
            'data': base64.b64encode(data).decode('ascii')}


def python_launcher(kind):
    """Arguments never become a URL, shell command or disk operation."""
    label = 'Drive Health & Tests' if kind == 'drives' else 'RAID Manager'
    return ('''#!/usr/bin/python3 -I
"""Legacy storage entrypoint: open the protected Cockpit interface only."""
import os
import subprocess

URL = %r


def main():
    print(%r)
    print(URL, flush=True)
    # Never start a browser as root, through SSH, or without a desktop session.
    if (os.geteuid() == 0 or os.environ.get('SSH_CONNECTION')
            or os.environ.get('SSH_TTY')
            or not (os.environ.get('DISPLAY') or os.environ.get('WAYLAND_DISPLAY'))):
        print('Open this workstation-local address in your regular desktop browser.')
        return 0
    try:
        subprocess.Popen(['/usr/bin/xdg-open', URL], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         close_fds=True, start_new_session=True)
    except OSError:
        print('Could not open a browser automatically. Use the address above.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
''' % (URLS[kind], label + ' is now available in Cockpit.')).encode()


def wrapper(script):
    return ('#!/bin/sh\n# Retired legacy GUI; use authenticated Cockpit.\n'
            'exec /usr/bin/python3 -I ' + str(script) + '\n').encode()


def rewrite_aliases(data):
    text = data.decode('utf-8')
    for name, launcher in zip(('nvme-stress', 'raid-manager'), LAUNCHERS):
        # These aliases are single-quoted (possibly multiline). Refuse unknown
        # shell forms instead of guessing and damaging unrelated .bashrc code.
        starts = re.findall(r'^\s*alias\s+' + re.escape(name) + r'\s*=', text, re.M)
        pattern = r"^alias " + re.escape(name) + r"='[^']*'[ \t]*$"
        matches = list(re.finditer(pattern, text, re.M))
        if len(starts) != 1 or len(matches) != 1:
            raise MigrationError('Expected one single-quoted ' + name + ' alias in .bashrc.')
        text = re.sub(pattern, "alias " + name + "='" + str(launcher) + "'", text, count=1, flags=re.M)
    return text.encode('utf-8')


def replacements(originals):
    directory = {'kind': 'directory', 'mode': 0o755, 'uid': ROOT_UID, 'gid': ROOT_GID}
    nvme = {'.': directory.copy(), 'app.py': encoded_file(python_launcher('drives'), 0o755),
            'manual_run.sh': encoded_file(wrapper(NVME / 'app.py'), 0o755)}
    raid = {'.': directory.copy(), 'main.py': encoded_file(python_launcher('raid'), 0o755),
            'raid_functions.py': encoded_file(python_launcher('raid'), 0o644)}
    bash = originals[str(BASHRC)]['.'].copy()
    bash['data'] = base64.b64encode(rewrite_aliases(base64.b64decode(bash['data']))).decode('ascii')
    return {str(NVME): nvme, str(RAID): raid, str(BASHRC): {'.': bash},
            str(LAUNCHERS[0]): {'.': encoded_file(wrapper(NVME / 'app.py'), 0o755)},
            str(LAUNCHERS[1]): {'.': encoded_file(wrapper(RAID / 'main.py'), 0o755)}}


def verify_tabs(root):
    package = at(root, Path('/usr/local/share/dlbt_os/cockpit_support'))
    manifest_path = package / 'manifest.json'
    for path in (manifest_path, package / 'drives.html', package / 'raid.html'):
        resolved = path.resolve(strict=True)
        if resolved != root and root not in resolved.parents:
            raise MigrationError('Cockpit files resolve outside the selected filesystem root.')
        info = resolved.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
            raise MigrationError('Cockpit files must be installed and root-owned.')
    manifest = json.loads(manifest_path.read_text())
    for key, filename in (('drive-tests', 'drives.html'), ('raid-manager', 'raid.html')):
        if not any(manifest.get(group, {}).get(key, {}).get('path') == filename
                   for group in ('dashboard', 'tools', 'menu')):
            raise MigrationError('The protected Cockpit storage routes are not installed.')


def collect(root, allow_missing=False):
    result = {}
    for target in TARGETS:
        path = at(root, target)
        check_parents(path.parent, root)
        if allow_missing and not path.exists() and not path.is_symlink():
            result[str(target)] = None
        else:
            result[str(target)] = snapshot(path, user_file=target == BASHRC)
    return result


def write_private(path, value):
    with path.open('xb') as stream:
        os.fchmod(stream.fileno(), 0o600)
        os.fchown(stream.fileno(), ROOT_UID, ROOT_GID)
        stream.write(json.dumps(value, sort_keys=True).encode())
        stream.flush()
        os.fsync(stream.fileno())


def private_backup(directory):
    directory = Path(os.path.abspath(directory))
    if directory.is_symlink():
        raise MigrationError('Backup directory must not be a symlink.')
    check_parents(directory.parent, Path(directory.anchor))
    if not directory.exists():
        directory.mkdir(mode=0o700)
        os.chown(directory, ROOT_UID, ROOT_GID)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o077:
        raise MigrationError('Backup directory must be administrator-owned with mode 0700.')
    return directory


def validate_saved(value):
    if value.get('schema') != 1 or value.get('product') != 'bizon-legacy-storage-retirement':
        raise MigrationError('Not a legacy-storage migration backup.')
    for section in ('originals', 'installed'):
        if set(value.get(section, {})) != {str(path) for path in TARGETS}:
            raise MigrationError('Unexpected backup targets.')
        for target, entries in value[section].items():
            if '.' not in entries:
                raise MigrationError('Incomplete backup.')
            for name, entry in entries.items():
                relative = Path(name)
                if relative.is_absolute() or '..' in relative.parts or str(relative) != name:
                    raise MigrationError('Unsafe backup path.')
                if entry.get('kind') not in ('directory', 'file'):
                    raise MigrationError('Unsupported backup entry.')
                if entry.get('mode', -1) < 0 or entry['mode'] > 0o777:
                    raise MigrationError('Unsafe backup mode.')
                if entry['kind'] == 'file':
                    base64.b64decode(entry['data'], validate=True)
    if value['installed'] != replacements(value['originals']):
        raise MigrationError('Backup belongs to a different migration revision.')


def apply_snapshot(path, entries):
    """Stage beside a target, then rename. Interrupted staging remains private."""
    if entries is None:
        # Restore the pre-transaction absent state after a failed recovery.
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)
        return
    if entries['.']['kind'] == 'file':
        # In particular, do not stage .bashrc in a directory beneath a user's
        # writable home. Keep the parent open and operate on the file descriptor
        # so a renamed temporary path cannot redirect privileged writes.
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        name = '.bizon-storage-' + os.urandom(12).hex()
        try:
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=parent_fd)
            with os.fdopen(fd, 'wb') as stream:
                entry = entries['.']
                stream.write(base64.b64decode(entry['data'], validate=True))
                os.fchown(stream.fileno(), entry['uid'], entry['gid'])
                os.fchmod(stream.fileno(), entry['mode'])
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path.name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
        finally:
            try:
                os.unlink(name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
            os.close(parent_fd)
        return
    staging = Path(tempfile.mkdtemp(prefix='.bizon-storage-migration-', dir=path.parent))
    fresh, retired = staging / 'new', staging / 'old'
    moved = False
    safe_to_clean = False
    try:
        for name, entry in sorted(entries.items(), key=lambda item: (len(Path(item[0]).parts), item[0])):
            item = fresh if name == '.' else fresh / name
            if entry['kind'] == 'directory':
                item.mkdir(mode=0o700)
            else:
                item.write_bytes(base64.b64decode(entry['data'], validate=True))
            os.chown(item, entry['uid'], entry['gid'])
            item.chmod(entry['mode'])
        if path.exists() or path.is_symlink():
            os.replace(path, retired)
            moved = True
        os.replace(fresh, path)
        safe_to_clean = True
    except BaseException:
        if moved and not path.exists():
            os.replace(retired, path)
        safe_to_clean = True
        raise
    finally:
        # If restoring the original also failed, retain the private staging
        # copy for recovery; never delete the only nearby original on an error.
        if safe_to_clean or not moved:
            shutil.rmtree(staging)


def transition(root, before, after):
    completed = []
    try:
        for target in TARGETS:
            key = str(target)
            if before[key] == after[key]:
                continue
            path = at(root, target)
            check_parents(path.parent, root)
            actual = snapshot(path, user_file=target == BASHRC) if path.exists() or path.is_symlink() else None
            if actual != before[key]:
                raise MigrationError('Target changed while preparing migration: ' + key)
            completed.append(target)
            apply_snapshot(path, after[key])
    except BaseException:
        for target in reversed(completed):
            apply_snapshot(at(root, target), before[str(target)])
        raise


def migrate(root, backup_dir, restore=False):
    require_root()
    root = Path(root).resolve(strict=True)
    check_parents(root, root)
    # Never put old executable code underneath a replaced application tree.
    requested = Path(os.path.abspath(backup_dir))
    for target in TARGETS:
        destination = at(root, target)
        if requested == destination or destination in requested.parents:
            raise MigrationError('The backup must be outside all migration targets.')
    current = collect(root, allow_missing=restore)
    backup = private_backup(requested)
    filename = backup / BACKUP_NAME
    if filename.exists() or filename.is_symlink():
        info = filename.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o077:
            raise MigrationError('Unsafe backup file.')
        if info.st_size > MAX_BYTES * 4:
            raise MigrationError('Oversized backup file.')
        saved = json.loads(filename.read_text())
        validate_saved(saved)
        for key in current:
            if restore and current[key] is None:
                continue
            if current[key] not in (saved['originals'][key], saved['installed'][key]):
                raise MigrationError('A migrated file changed; refusing to overwrite it: ' + key)
    elif restore:
        raise MigrationError('The selected backup does not exist.')
    else:
        verify_tabs(root)
        installed = replacements(current)
        if installed == current:
            return {'status': 'already-retired', 'changed': []}
        saved = {'schema': 1, 'product': 'bizon-legacy-storage-retirement',
                 'originals': current, 'installed': installed}
        validate_saved(saved)
        write_private(filename, saved)
    if not restore:
        verify_tabs(root)
    desired = saved['originals' if restore else 'installed']
    transition(root, current, desired)
    return {'status': 'restored' if restore else 'retired', 'backup': str(filename),
            'changed': [key for key in current if current[key] != desired[key]],
            'backup_sha256': hashlib.sha256(filename.read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path('/'), help='Mounted OS root (default: /)')
    parser.add_argument('--backup-dir', type=Path, required=True,
                        help='Private existing-parent directory, preferably on external storage')
    parser.add_argument('--restore', action='store_true', help='Restore the selected originals (unsafe legacy apps)')
    args = parser.parse_args()
    try:
        print(json.dumps(migrate(args.root, args.backup_dir, args.restore), indent=2))
    except (MigrationError, OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, 'Storage migration refused: ' + str(exc) + '\n')


if __name__ == '__main__':
    main()
