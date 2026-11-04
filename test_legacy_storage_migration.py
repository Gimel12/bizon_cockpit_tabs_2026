#!/usr/bin/env python3
"""Migration checks use temporary files and mocked browser launches, never disks."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import types
import unittest
from unittest.mock import patch

import retire_legacy_storage as migration


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'image'
        self.root.mkdir()
        self.backup = self.base / 'export'
        self.enterContext(patch.object(migration, 'ROOT_UID', os.getuid()))
        self.enterContext(patch.object(migration, 'ROOT_GID', os.getgid()))
        self.enterContext(patch.object(migration.os, 'geteuid', return_value=0))
        self.enterContext(patch.object(migration.os, 'chown'))
        self.enterContext(patch.object(migration.os, 'fchown'))
        for path in migration.TARGETS:
            target = self.at(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            if path in (migration.NVME, migration.RAID):
                target.mkdir()
                (target / '.git').mkdir()
                (target / '.git' / 'old-source').write_text('historical unsafe source')
                (target / '__pycache__').mkdir()
                (target / '__pycache__' / 'old.pyc').write_bytes(b'old bytecode')
                (target / 'original.py').write_text('original source')
            else:
                target.write_text('#!/bin/sh\necho old\n')
                target.chmod(0o755)
        self.original_bashrc = (
            '# keep this header\nexport USER_SETTING="unchanged"\n'
            "alias nvme-stress='\ncd /legacy/nvme\npython3 app.py\n'\n"
            '# keep this middle comment\n'
            "alias raid-manager='\ncd /legacy/raid\npython3 main.py\n'\n"
            "alias unrelated='echo preserved'\n# keep this footer\n")
        self.at(migration.BASHRC).write_text(self.original_bashrc)
        self.at(migration.BASHRC).chmod(0o640)
        package = self.at(Path('/usr/local/share/dlbt_os/cockpit_support'))
        package.mkdir()
        (package / 'manifest.json').write_text(json.dumps({'dashboard': {
            'drive-tests': {'path': 'drives.html'}, 'raid-manager': {'path': 'raid.html'}}}))
        (package / 'drives.html').write_text('protected drives')
        (package / 'raid.html').write_text('protected RAID')
        self.originals = migration.collect(self.root)

    def at(self, path):
        return migration.at(self.root, path)

    def install(self):
        return migration.migrate(self.root, self.backup)

    def test_replaces_entire_old_trees_and_only_known_aliases(self):
        result = self.install()
        self.assertEqual(result['status'], 'retired')
        self.assertEqual(len(result['changed']), 5)
        self.assertEqual({p.name for p in self.at(migration.NVME).iterdir()}, {'app.py', 'manual_run.sh'})
        self.assertEqual({p.name for p in self.at(migration.RAID).iterdir()}, {'main.py', 'raid_functions.py'})
        bashrc = self.at(migration.BASHRC).read_text()
        for preserved in ('# keep this header', 'export USER_SETTING="unchanged"',
                          '# keep this middle comment', "alias unrelated='echo preserved'", '# keep this footer'):
            self.assertIn(preserved, bashrc)
        self.assertIn("alias nvme-stress='/usr/local/bin/bizon-nvme-gui'", bashrc)
        self.assertIn("alias raid-manager='/usr/local/bin/bizon-raid'", bashrc)
        expected = self.original_bashrc.replace(
            "alias nvme-stress='\ncd /legacy/nvme\npython3 app.py\n'",
            "alias nvme-stress='/usr/local/bin/bizon-nvme-gui'").replace(
            "alias raid-manager='\ncd /legacy/raid\npython3 main.py\n'",
            "alias raid-manager='/usr/local/bin/bizon-raid'")
        self.assertEqual(bashrc, expected)
        self.assertEqual(stat.S_IMODE(self.at(migration.BASHRC).stat().st_mode), 0o640)
        self.assertNotIn('anaconda', self.at(migration.LAUNCHERS[0]).read_text())
        self.assertNotIn('dd ', self.at(migration.NVME / 'manual_run.sh').read_text())

    def test_backup_is_private_and_roundtrip_restores_all_original_bytes_and_modes(self):
        self.install()
        backup_file = self.backup / migration.BACKUP_NAME
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(backup_file.stat().st_mode), 0o600)
        saved = json.loads(backup_file.read_text())
        self.assertEqual(saved['originals'], self.originals)
        migration.migrate(self.root, self.backup, restore=True)
        self.assertEqual(migration.collect(self.root), self.originals)

    def test_repeated_install_and_restore_are_idempotent(self):
        self.install()
        saved = (self.backup / migration.BACKUP_NAME).read_bytes()
        self.assertEqual(self.install()['changed'], [])
        self.assertEqual((self.backup / migration.BACKUP_NAME).read_bytes(), saved)
        migration.migrate(self.root, self.backup, restore=True)
        self.assertEqual(migration.migrate(self.root, self.backup, restore=True)['changed'], [])

    def test_no_changes_when_routes_missing_or_changed(self):
        self.at(Path('/usr/local/share/dlbt_os/cockpit_support/manifest.json')).write_text('{}')
        with self.assertRaises(migration.MigrationError):
            self.install()
        self.assertEqual(migration.collect(self.root), self.originals)
        self.assertFalse((self.backup / migration.BACKUP_NAME).exists())

    def test_refuses_ambiguous_aliases_without_touching_sources(self):
        path = self.at(migration.BASHRC)
        path.write_text(self.original_bashrc + "alias nvme-stress='another command'\n")
        before = migration.collect(self.root)
        with self.assertRaises(migration.MigrationError):
            self.install()
        self.assertEqual(migration.collect(self.root), before)

    def test_restore_refuses_user_edits_made_after_migration(self):
        self.install()
        path = self.at(migration.BASHRC)
        path.write_text(path.read_text() + '# later customer preference\n')
        with self.assertRaises(migration.MigrationError):
            migration.migrate(self.root, self.backup, restore=True)
        self.assertIn('# later customer preference', path.read_text())

    def test_mid_transaction_failure_rolls_back_all_completed_targets(self):
        actual = migration.apply_snapshot
        calls = 0

        def fail_once(path, entries):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError('injected write failure')
            return actual(path, entries)

        with patch.object(migration, 'apply_snapshot', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.install()
        self.assertEqual(migration.collect(self.root), self.originals)
        self.assertTrue((self.backup / migration.BACKUP_NAME).is_file())

    def test_rejects_symlink_and_hardlink_sources(self):
        path = self.at(migration.NVME) / 'link'
        path.symlink_to('/etc/passwd')
        with self.assertRaises(migration.MigrationError):
            self.install()
        path.unlink()
        os.link(self.at(migration.NVME) / 'original.py', path)
        with self.assertRaises(migration.MigrationError):
            self.install()

    def test_refuses_backup_inside_retired_tree(self):
        with self.assertRaises(migration.MigrationError):
            migration.migrate(self.root, self.at(migration.NVME) / 'backup')

    def test_refuses_world_readable_backup_and_tampered_restore_paths(self):
        self.backup.mkdir(mode=0o755)
        with self.assertRaises(migration.MigrationError):
            self.install()
        self.backup.chmod(0o700)
        self.install()
        filename = self.backup / migration.BACKUP_NAME
        value = json.loads(filename.read_text())
        value['originals'][str(migration.NVME)]['../escape'] = value['originals'][str(migration.NVME)]['original.py']
        filename.write_text(json.dumps(value))
        with self.assertRaises(migration.MigrationError):
            migration.migrate(self.root, self.backup, restore=True)
        self.assertFalse((self.at(migration.NVME).parent / 'escape').exists())

    def test_relocated_offline_image_can_restore_from_external_backup(self):
        self.install()
        moved = self.base / 'relocated-image'
        self.root.rename(moved)
        self.root = moved
        migration.migrate(self.root, self.backup, restore=True)
        self.assertEqual(migration.collect(self.root), self.originals)

    def test_directory_activation_failure_restores_original_before_returning(self):
        actual_replace = os.replace
        failed = False

        def fail_activation(source, destination, **kwargs):
            nonlocal failed
            if not failed and Path(source).name == 'new' and destination == self.at(migration.NVME):
                failed = True
                raise OSError('interrupted directory activation')
            return actual_replace(source, destination, **kwargs)

        with patch.object(migration.os, 'replace', side_effect=fail_activation):
            with self.assertRaises(OSError):
                self.install()
        self.assertTrue(failed)
        self.assertEqual(migration.collect(self.root), self.originals)

    def test_valid_backup_can_recover_missing_targets_after_interruption(self):
        self.install()
        self.at(migration.NVME).rename(self.base / 'interrupted-original')
        self.at(migration.BASHRC).unlink()
        with self.assertRaises(FileNotFoundError):
            self.install()
        migration.migrate(self.root, self.backup, restore=True)
        self.assertEqual(migration.collect(self.root), self.originals)

    def test_missing_target_recovery_still_requires_valid_private_backup(self):
        self.at(migration.NVME).rename(self.base / 'interrupted-original')
        with self.assertRaises(migration.MigrationError):
            migration.migrate(self.root, self.backup, restore=True)
        self.assertFalse(self.at(migration.NVME).exists())


class LauncherTests(unittest.TestCase):
    def run_launcher(self, kind='drives', uid=1000, env=None):
        module = types.ModuleType('retired_launcher')
        exec(compile(migration.python_launcher(kind), 'launcher.py', 'exec'), module.__dict__)
        with patch.dict(os.environ, env or {}, clear=True), patch('os.geteuid', return_value=uid), \
                patch('subprocess.Popen') as popen, contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(module.main(), 0)
        return popen, output.getvalue()

    def test_regular_desktop_launches_only_fixed_https_cockpit_route(self):
        for kind in ('drives', 'raid'):
            popen, output = self.run_launcher(kind, env={'DISPLAY': ':0'})
            self.assertEqual(popen.call_args.args[0], ['/usr/bin/xdg-open', migration.URLS[kind]])
            self.assertNotIn('shell', popen.call_args.kwargs)
            self.assertIn(migration.URLS[kind], output)

    def test_root_headless_and_ssh_never_start_browser(self):
        for uid, env in ((0, {'DISPLAY': ':0'}), (1000, {}),
                         (1000, {'DISPLAY': ':0', 'SSH_CONNECTION': 'client server'}),
                         (1000, {'WAYLAND_DISPLAY': 'wayland-0', 'SSH_TTY': '/dev/pts/2'})):
            popen, output = self.run_launcher(uid=uid, env=env)
            popen.assert_not_called()
            self.assertIn(migration.URLS['drives'], output)

    def test_import_does_not_launch_browser_and_old_raid_functions_are_absent(self):
        namespace = {'__name__': 'raid_functions'}
        with patch('subprocess.Popen') as popen:
            exec(compile(migration.python_launcher('raid'), 'raid_functions.py', 'exec'), namespace)
        popen.assert_not_called()
        self.assertNotIn('create_raid', namespace)
        self.assertNotIn('delete_raid', namespace)


if __name__ == '__main__':
    unittest.main()
