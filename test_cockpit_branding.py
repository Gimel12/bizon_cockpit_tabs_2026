#!/usr/bin/env python3
"""Filesystem-level tests for the one-time login branding bootstrap."""
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

import install_cockpit_branding as branding


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        for name, value in (('ROOT_UID', os.getuid()), ('ROOT_GID', os.getgid())):
            self.enterContext(patch.object(branding, name, value))
        self.enterContext(patch.object(branding.os, 'geteuid', return_value=0))
        for name in ('chown', 'fchown', 'lchown'):
            self.enterContext(patch.object(branding.os, name))
        self.systemctl = self.enterContext(patch.object(branding.subprocess, 'run'))
        self.store = self.at(branding.STORE)
        self.release = self.make_release('1', b'body.login-pf { color: blue; }', b'first')
        (self.store / 'current').symlink_to('releases/1')

    def at(self, path):
        return self.root / path.relative_to('/')

    def make_release(self, version, css=None, image=None):
        release = self.store / 'releases' / version
        release.mkdir(parents=True)
        (release / 'release.json').write_text(json.dumps({
            'schema': 1, 'product': 'bizon-cockpit-tabs', 'sequence': int(version)}))
        if css is not None:
            assets = release / 'cockpit_support/branding'
            assets.mkdir(parents=True)
            (assets / 'branding.css').write_bytes(css)
            (assets / 'bizon-login.png').write_bytes(b'\x89PNG\r\n\x1a\n' + image)
        return release

    def install(self):
        return branding.install_branding(self.root, reload_systemd=False)

    def served(self, name):
        # Cockpit 314 resolves these directory roots once, then opens files in
        # order for each request. ENOENT (including a broken link) falls through.
        roots = [(self.at(branding.BASE) / part / 'cockpit/static').resolve()
                 for part in ('live', 'fallback')]
        for root in roots:
            try:
                return (root / name).read_bytes()
            except FileNotFoundError:
                pass
        raise FileNotFoundError(name)

    def test_installs_both_instances_without_touching_vendor_files_or_sessions(self):
        vendor = self.at(Path('/usr/share/cockpit/branding/ubuntu/branding.css'))
        vendor.parent.mkdir(parents=True)
        vendor.write_text('original vendor file')
        result = self.install()
        self.assertFalse(result['restart_performed'])
        self.systemctl.assert_not_called()
        self.assertEqual(vendor.read_text(), 'original vendor file')
        for path in branding._dropins(self.root).values():
            self.assertEqual(path.read_bytes(), branding.DROPIN)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertIn(b'live:/usr/local/share/bizon-cockpit-branding/fallback:', branding.DROPIN)
        self.assertEqual(self.served('branding.css'), b'body.login-pf { color: blue; }')

    def test_upgrade_follows_current_link_without_reinstalling_or_resolving_roots_again(self):
        self.install()
        root = (self.at(branding.BASE) / 'live/cockpit/static').resolve()
        self.make_release('2', b'new theme', b'second')
        (self.store / 'current').unlink()
        (self.store / 'current').symlink_to('releases/2')
        self.assertEqual((root / 'branding.css').read_bytes(), b'new theme')
        self.assertEqual(self.served('bizon-login.png'), b'\x89PNG\r\n\x1a\nsecond')

    def test_expected_absolute_links_migrate_to_relative_idempotently(self):
        self.install()
        live = self.at(branding.BASE) / 'live/cockpit/static'
        backup = self.at(branding.STATE).read_bytes()
        for name in branding.ASSETS:
            link = live / name
            link.unlink()
            link.symlink_to(self.store / 'current/cockpit_support/branding' / name)
        self.install()
        inodes = {}
        for name in branding.ASSETS:
            link = live / name
            self.assertFalse(Path(os.readlink(link)).is_absolute())
            self.assertEqual(link.resolve(), self.release / 'cockpit_support/branding' / name)
            inodes[name] = link.lstat().st_ino
        self.install()
        self.assertEqual(self.at(branding.STATE).read_bytes(), backup)
        self.assertEqual({name: (live / name).lstat().st_ino for name in branding.ASSETS}, inodes)
        self.systemctl.assert_not_called()

    def test_offline_links_survive_relocation_and_keep_following_updates(self):
        self.install()
        destination = tempfile.TemporaryDirectory()
        self.addCleanup(destination.cleanup)
        relocated = Path(destination.name).resolve() / 'relocated-image'
        self.root.rename(relocated)
        self.root = relocated
        self.store = self.at(branding.STORE)
        live = self.at(branding.BASE) / 'live/cockpit/static'
        # Read the live links directly: a fallback could hide a broken link.
        self.assertEqual((live / 'branding.css').read_bytes(), b'body.login-pf { color: blue; }')
        self.assertEqual((live / 'bizon-login.png').read_bytes(), b'\x89PNG\r\n\x1a\nfirst')
        self.install()
        self.make_release('2', b'new relocated theme', b'relocated second')
        (self.store / 'current').unlink()
        (self.store / 'current').symlink_to('releases/2')
        self.assertEqual((live / 'branding.css').read_bytes(), b'new relocated theme')
        self.assertEqual((live / 'bizon-login.png').read_bytes(), b'\x89PNG\r\n\x1a\nrelocated second')
        self.systemctl.assert_not_called()

    def test_rollback_to_release_without_branding_uses_persistent_fallback(self):
        self.install()
        self.make_release('2')
        (self.store / 'current').unlink()
        (self.store / 'current').symlink_to('releases/2')
        self.assertEqual(self.served('branding.css'), b'body.login-pf { color: blue; }')
        self.assertEqual(self.served('bizon-login.png'), b'\x89PNG\r\n\x1a\nfirst')

    def test_reinstall_preserves_backup_and_remove_restores_exact_original(self):
        paths = branding._dropins(self.root)
        path = paths[branding.SERVICES[0]]
        path.parent.mkdir(parents=True)
        old = b'[Service]\nEnvironment="ORIGINAL_SETTING=yes"\n'
        path.write_bytes(old)
        path.chmod(0o640)
        self.install()
        backup = self.at(branding.STATE).read_bytes()
        self.install()
        self.assertEqual(self.at(branding.STATE).read_bytes(), backup)
        branding.remove_branding(self.root, reload_systemd=False)
        self.assertEqual(path.read_bytes(), old)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
        self.assertFalse(paths[branding.SERVICES[1]].exists())
        self.assertFalse(self.at(branding.STATE).exists())
        self.assertFalse(branding.remove_branding(self.root, reload_systemd=False)['removed'])

    def test_admin_edit_is_never_silently_overwritten_by_reinstall_or_remove(self):
        self.install()
        path = next(iter(branding._dropins(self.root).values()))
        path.write_text('a later local administrator change')
        with self.assertRaisesRegex(branding.BrandingError, 'changed since backup'):
            self.install()
        with self.assertRaisesRegex(branding.BrandingError, 'changed since backup'):
            branding.remove_branding(self.root, reload_systemd=False)
        self.assertEqual(path.read_text(), 'a later local administrator change')

    def test_invalid_asset_prevents_any_configuration_change(self):
        (self.release / 'cockpit_support/branding/bizon-login.png').write_bytes(b'not a png')
        with self.assertRaisesRegex(branding.BrandingError, 'PNG'):
            self.install()
        self.assertFalse(self.at(branding.STATE).exists())
        self.assertFalse(self.at(branding.BASE).exists())

    def test_input_assets_must_be_regular_non_writable_files(self):
        asset = self.release / 'cockpit_support/branding/branding.css'
        asset.chmod(0o666)
        with self.assertRaises(branding.BrandingError):
            self.install()
        asset.unlink()
        target = self.root / 'external.css'
        target.write_text('unsafe')
        asset.symlink_to(target)
        with self.assertRaises(branding.BrandingError):
            self.install()
        self.assertFalse(self.at(branding.STATE).exists())

    def test_current_must_resolve_to_signed_release_store(self):
        (self.store / 'current').unlink()
        (self.store / 'current').symlink_to(self.root)
        with self.assertRaisesRegex(branding.BrandingError, 'within the signed release store'):
            self.install()

    def test_existing_output_symlink_cannot_redirect_writes(self):
        live = self.at(branding.BASE) / 'live/cockpit/static'
        live.mkdir(parents=True)
        victim = self.root / 'unrelated'
        victim.write_text('keep')
        (live / 'branding.css').symlink_to(victim)
        with self.assertRaisesRegex(branding.BrandingError, 'Unexpected existing branding asset'):
            self.install()
        self.assertEqual(victim.read_text(), 'keep')
        self.assertFalse(self.at(branding.STATE).exists())

    def test_existing_parent_symlink_cannot_redirect_install(self):
        target = self.root / 'elsewhere'
        target.mkdir()
        self.at(branding.BASE).parent.mkdir(parents=True, exist_ok=True)
        self.at(branding.BASE).symlink_to(target)
        with self.assertRaises(branding.BrandingError):
            self.install()
        self.assertEqual(list(target.iterdir()), [])

    def test_unprivileged_use_is_rejected(self):
        with patch.object(branding.os, 'geteuid', return_value=1000):
            with self.assertRaisesRegex(branding.BrandingError, 'administrator'):
                self.install()
        self.assertFalse(self.at(branding.STATE).exists())

    def test_offline_root_never_runs_host_systemctl_even_if_requested(self):
        with self.assertRaisesRegex(branding.BrandingError, 'reload_systemd=False'):
            branding.install_branding(self.root)
        self.systemctl.assert_not_called()
        self.assertFalse(self.at(branding.STATE).exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
