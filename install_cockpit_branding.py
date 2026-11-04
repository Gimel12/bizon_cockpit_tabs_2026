#!/usr/bin/python3 -I
"""Install local login branding after the signed tabs release has been activated.

Cockpit 314 searches explicit XDG_DATA_DIRS/cockpit/static before OS branding.
Use real search directories with relative per-file links: resolving a directory
symlink would pin a running web service to one release. Relative links also
survive moving an offline image's filesystem root. Missing files fall through to
root-owned fallback copies, including when rolling back to an older release.

Sources (Cockpit 314): src/ws/cockpitbranding.c, lines 27-89;
src/common/cockpitwebresponse.c, lines 1161-1256.
This bootstrap never changes packaged login HTML/JS, authentication, or TLS.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile

ROOT_UID = 0
ROOT_GID = 0
ASSETS = ('branding.css', 'bizon-login.png')
SERVICES = ('cockpit-wsinstance-http.service', 'cockpit-wsinstance-https@.service')
BASE = Path('/usr/local/share/bizon-cockpit-branding')
STORE = Path('/usr/local/share/bizon-tabs')
STATE = Path('/var/lib/bizon-cockpit-branding/install-state.json')
DROPIN_NAME = '50-bizon-login-branding.conf'
DROPIN = (
    '# Managed by BIZON install_cockpit_branding.py; original content is backed up.\n'
    '[Service]\n'
    'Environment="XDG_DATA_DIRS=/usr/local/share/bizon-cockpit-branding/live:'
    '/usr/local/share/bizon-cockpit-branding/fallback:/usr/local/share:/usr/share"\n'
).encode()


class BrandingError(RuntimeError):
    pass


def _require_root():
    if os.geteuid() != 0:
        raise BrandingError('Run this reviewed bootstrap as administrator')


def _path(root, absolute):
    return root / absolute.relative_to('/')


def _secure(path, kind='file'):
    info = path.lstat()
    expected = stat.S_ISDIR if kind == 'directory' else stat.S_ISREG
    if not expected(info.st_mode) or info.st_uid != ROOT_UID or info.st_mode & 0o022:
        raise BrandingError('Expected a root-owned, non-writable ' + kind + ': ' + str(path))
    return info


def _parents(path, root):
    for parent in reversed((path, *path.parents)):
        if parent == root or root in parent.parents:
            if parent.exists() or parent.is_symlink():
                _secure(parent, 'directory')


def _mkdir(path, root, mode=0o755):
    _parents(path, root)
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(mode=mode if directory == path else 0o755)
        os.chown(directory, ROOT_UID, ROOT_GID)
    _secure(path, 'directory')
    path.chmod(mode)


def _write(path, data, mode=0o644, gid=ROOT_GID):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            os.fchown(stream.fileno(), ROOT_UID, gid)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def _dropins(root):
    return {service: _path(root, Path('/etc/systemd/system')) / (service + '.d') / DROPIN_NAME
            for service in SERVICES}


def _state(root):
    path = _path(root, STATE)
    if not path.exists() and not path.is_symlink():
        return None
    _secure(path)
    value = json.loads(path.read_text())
    if value.get('schema') != 1 or set(value.get('originals', {})) != set(SERVICES):
        raise BrandingError('Invalid Cockpit branding backup state')
    return value


def _snapshot(path):
    if not path.exists() and not path.is_symlink():
        return None
    info = _secure(path)
    data = path.read_bytes()
    if len(data) > 65536:
        raise BrandingError('Existing Cockpit branding drop-in is unexpectedly large')
    return {'data': base64.b64encode(data).decode(), 'mode': stat.S_IMODE(info.st_mode), 'gid': info.st_gid}


def _check_managed(dropins, state):
    """Do not silently replace administrator changes made after installation."""
    for service, path in dropins.items():
        if path.exists() or path.is_symlink():
            _secure(path)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            original = state['originals'][service]
            original_digest = hashlib.sha256(base64.b64decode(original['data'])).hexdigest() if original else None
            if digest not in (state['installed_sha256'], original_digest):
                raise BrandingError('Cockpit branding drop-in changed since backup: ' + str(path))


def _assets(root):
    store = _path(root, STORE)
    _parents(store, root)
    current = store / 'current'
    if not current.is_symlink() or current.lstat().st_uid != ROOT_UID:
        raise BrandingError('The signed tabs current release link is missing or not root-owned')
    release = current.resolve(strict=True)
    releases = store / 'releases'
    _secure(releases, 'directory')
    if release.parent != releases:
        raise BrandingError('The current tabs release must be within the signed release store')
    _parents(release / 'cockpit_support' / 'branding', root)
    _secure(release / 'release.json')
    metadata = json.loads((release / 'release.json').read_text())
    if metadata.get('product') != 'bizon-cockpit-tabs' or metadata.get('schema') != 1:
        raise BrandingError('Activate a verified BIZON tabs release before installing branding')
    data = {}
    for name in ASSETS:
        source = release / 'cockpit_support' / 'branding' / name
        _secure(source)
        data[name] = source.read_bytes()
        if not data[name] or len(data[name]) > 10 * 1024 * 1024:
            raise BrandingError('Invalid branding asset size: ' + name)
    if not data['bizon-login.png'].startswith(b'\x89PNG\r\n\x1a\n'):
        raise BrandingError('Login wallpaper must be a PNG image')
    return data


def install_branding(root=Path('/'), reload_systemd=True):
    """Idempotently install from the root-owned release activated by the updater.

    ``root`` is a filesystem staging root for tests/image builds, never a source
    of release assets. No process is stopped or restarted. Existing instances
    keep their old environment until they naturally exit or are later restarted.
    """
    _require_root()
    root = Path(root).resolve()
    if reload_systemd and root != Path('/'):
        raise BrandingError('Use reload_systemd=False when preparing an offline filesystem')
    data = _assets(root)  # Validate everything before changing configuration.
    dropins = _dropins(root)
    state_path = _path(root, STATE)
    for path in (*dropins.values(), state_path):
        _parents(path.parent, root)
    state = _state(root)
    if state is None:
        state = {'schema': 1, 'installed_sha256': hashlib.sha256(DROPIN).hexdigest(),
                 'originals': {service: _snapshot(path) for service, path in dropins.items()}}
    else:
        _check_managed(dropins, state)
    live = _path(root, BASE) / 'live/cockpit/static'
    fallback = _path(root, BASE) / 'fallback/cockpit/static'
    link_targets = {}
    for directory in (live, fallback):
        _parents(directory, root)
    for name in ASSETS:
        link = live / name
        target = _path(root, STORE) / 'current/cockpit_support/branding' / name
        link_targets[name] = os.path.relpath(target, live)
        if link.exists() or link.is_symlink():
            # Previous bootstraps wrote absolute targets. Only that exact
            # trusted target may migrate; do not accept arbitrary symlinks.
            if (not link.is_symlink() or link.lstat().st_uid != ROOT_UID or
                    os.readlink(link) not in (str(target), link_targets[name])):
                raise BrandingError('Unexpected existing branding asset: ' + str(link))
        backup = fallback / name
        if backup.exists() or backup.is_symlink():
            _secure(backup)
    _mkdir(state_path.parent, root, 0o700)
    # The original drop-ins are safely recorded before replacing either one.
    _write(state_path, (json.dumps(state, indent=2) + '\n').encode(), 0o600)
    for directory in (live, fallback):
        _mkdir(directory, root)
    for name in ASSETS:
        _write(fallback / name, data[name])
        link = live / name
        if not link.is_symlink() or os.readlink(link) != link_targets[name]:
            # Atomically replace a validated legacy link without creating a
            # moment when the web service must fall back to older artwork.
            with tempfile.TemporaryDirectory(prefix='.bizon-link-', dir=live) as staging:
                pending = Path(staging) / name
                pending.symlink_to(link_targets[name])
                os.lchown(pending, ROOT_UID, ROOT_GID)
                os.replace(pending, link)
    for path in dropins.values():
        _mkdir(path.parent, root)
        _write(path, DROPIN)
    state['installed_sha256'] = hashlib.sha256(DROPIN).hexdigest()
    _write(state_path, (json.dumps(state, indent=2) + '\n').encode(), 0o600)
    if reload_systemd:
        subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    return {'installed': True, 'restart_performed': False,
            'message': 'Branding installed. New web-service instances use it; existing sessions were not restarted.'}


def remove_branding(root=Path('/'), reload_systemd=True):
    """Restore original drop-ins, leaving cached artwork harmlessly on disk."""
    _require_root()
    root = Path(root).resolve()
    if reload_systemd and root != Path('/'):
        raise BrandingError('Use reload_systemd=False when preparing an offline filesystem')
    state = _state(root)
    if state is None:
        return {'removed': False, 'restart_performed': False}
    dropins = _dropins(root)
    for path in dropins.values():
        _parents(path.parent, root)
    _check_managed(dropins, state)
    for service, path in dropins.items():
        original = state['originals'][service]
        if original is None:
            path.unlink(missing_ok=True)
        else:
            _write(path, base64.b64decode(original['data'], validate=True), original['mode'], original['gid'])
    _path(root, STATE).unlink()
    if reload_systemd:
        subprocess.run(['/usr/bin/systemctl', 'daemon-reload'], check=True)
    return {'removed': True, 'restart_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--remove', action='store_true', help='Restore backed-up systemd configuration')
    args = parser.parse_args()
    try:
        print(json.dumps(remove_branding() if args.remove else install_branding()))
    except (BrandingError, OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
