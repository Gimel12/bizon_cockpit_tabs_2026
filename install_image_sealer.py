#!/usr/bin/python3 -I
"""Install the reviewed factory-sealing tools; installation never performs sealing."""
import argparse
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile

BASE = Path(__file__).resolve().parent
SOURCES = [
    (BASE / 'provision/bizon-seal-image.sh', Path('/usr/local/sbin/bizon-seal-image'), 0o750),
    (BASE / 'provision/seal_preflight.py', Path('/usr/local/libexec/bizon-seal-preflight'), 0o750),
    (BASE / 'provision/bizon-firstboot-seal.conf', Path('/etc/systemd/system/bizon-firstboot.service.d/seal.conf'), 0o644),
]
BACKUP = Path('/var/backups/bizon-sealer-before-factory-cleanup')


def trusted_parent(path):
    for parent in [path.parent, *path.parent.parents]:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Unsafe installation directory: ' + str(parent))


def atomic_file(destination, data, mode):
    fd, temporary = tempfile.mkstemp(prefix='.' + destination.name + '.', dir=destination.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), 0, 0)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--install', action='store_true', help='Install tools only; do not clean or power off')
    group.add_argument('--dry-run', action='store_true', help='Show installation plan without writes (default)')
    args = parser.parse_args(argv)
    for source, _, _ in SOURCES:
        if source.is_symlink() or not source.is_file():
            parser.error('Missing or linked source: ' + str(source))
    subprocess.run(['/bin/bash', '-n', str(SOURCES[0][0])], check=True)
    compile(SOURCES[1][0].read_bytes(), str(SOURCES[1][0]), 'exec')
    if not args.install:
        for source, destination, mode in SOURCES:
            print(f'Install {source.name} -> {destination} as root:root {mode:04o}')
        print('Preserve existing tools once in ' + str(BACKUP))
        print('No changes made. Installation will not run the sealer.')
        return 0
    if os.geteuid() != 0 or sys.platform != 'linux':
        parser.error('Installation requires administrator access on the target Linux workstation')
    firstboot = Path('/usr/local/libexec/bizon-firstboot')
    if not firstboot.is_file() or firstboot.is_symlink():
        parser.error('Install the existing BIZON first-boot identity baseline first')
    trusted_parent(BACKUP)
    dropins = SOURCES[2][1].parent
    trusted_parent(dropins)
    if dropins.is_symlink() or (dropins.exists() and not dropins.is_dir()):
        parser.error('Unsafe first-boot drop-in directory')
    if dropins.exists():
        trusted_parent(SOURCES[2][1])
    # All remaining checks precede installation writes.
    for _, destination, _ in SOURCES[:2]:
        trusted_parent(destination)
    for _, destination, _ in SOURCES:
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            parser.error('Refusing linked or non-regular target: ' + str(destination))
    if BACKUP.exists():
        info = BACKUP.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            parser.error('Unsafe existing backup directory')
    else:
        BACKUP.mkdir(mode=0o700)
    dropins.mkdir(mode=0o755, exist_ok=True)
    trusted_parent(SOURCES[2][1])
    # Preserve the original version on repeated provisioning runs.
    for _, destination, _ in SOURCES:
        saved = BACKUP / destination.name
        if saved.is_symlink():
            parser.error('Refusing linked backup file')
        if destination.exists() and not saved.exists():
            atomic_file(saved, destination.read_bytes(), 0o600)
    # Install the drop-in/helper before the shell so the old shell remains usable throughout.
    for source, destination, mode in reversed(SOURCES):
        atomic_file(destination, source.read_bytes(), mode)
    subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    print('Installed factory-sealing tools. Nothing was cleaned and the workstation remains running.')
    print('Next review: sudo /usr/local/sbin/bizon-seal-image --dry-run')
    return 0


if __name__ == '__main__':
    sys.exit(main())
