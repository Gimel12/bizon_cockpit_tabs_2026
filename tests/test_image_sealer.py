"""Read-only/local-fixture tests. Never install, seal, stop a service or touch real disks."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
SHELL = BASE / 'provision/bizon-seal-image.sh'
spec = importlib.util.spec_from_file_location('seal_preflight', BASE / 'provision/seal_preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class ImageSealerTests(unittest.TestCase):
    def shell(self, code):
        return subprocess.run(['/bin/bash', '-c', 'source "$1"; ' + code, 'test', str(SHELL)], capture_output=True, text=True)

    def test_shell_syntax(self):
        subprocess.run(['/bin/bash', '-n', str(SHELL)], check=True)

    def test_missing_or_mixed_flags_never_reach_preflight(self):
        for invocation in ['main', 'main --seal', 'main --dry-run --seal-and-poweroff']:
            result = self.shell('preflight(){ echo UNEXPECTED; }; seal(){ echo UNEXPECTED; }; ' + invocation)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('UNEXPECTED', result.stdout)

    def test_dry_run_prints_exact_cleanup_plan_without_sealing(self):
        result = self.shell('require_root(){ :; }; preflight(){ echo READ_ONLY_CHECK; }; seal(){ echo UNEXPECTED_SEAL; }; main --dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('READ_ONLY_CHECK', result.stdout)
        self.assertNotIn('UNEXPECTED_SEAL', result.stdout)
        self.assertIn('/etc/netplan/90-NM-c223fe1d-54d3-4d35-a795-21ba8a1bc0d7.yaml', result.stdout)
        self.assertIn('Remove: /var/mail/bizon', result.stdout)
        self.assertNotIn('Remove: /home/bizon/Documents', result.stdout)
        self.assertNotIn('Remove: /home/bizon/models', result.stdout)
        self.assertNotIn('Remove: /home/bizon/anaconda3', result.stdout)

    def test_refused_preflight_never_reaches_destructive_actions(self):
        result = self.shell('require_root(){ :; }; preflight(){ echo ACTIVE_WORK; return 1; }; seal(){ echo UNEXPECTED_SEAL; }; main --seal-and-poweroff')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ACTIVE_WORK', result.stdout)
        self.assertNotIn('UNEXPECTED_SEAL', result.stdout)

    def test_source_does_not_clean_anything(self):
        result = self.shell('printf "SOURCE_ONLY\\n"')
        self.assertEqual(result.stdout, 'SOURCE_ONLY\n')

    def test_exact_factory_allowlist_preserves_unreviewed_paths(self):
        result = self.shell('printf "%s\\n" "${FACTORY_PATHS[@]}"')
        paths = result.stdout.splitlines()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(path.startswith('/') and not any(c in path for c in '*?[') for path in paths))
        self.assertNotIn('/var/lib/bizon-storage', paths)
        self.assertNotIn('/etc/netplan', paths)
        self.assertIn('/var/lib/bizon-storage/jobs/ce1253d2b4694b7a85f8c8a078236228', paths)

    def test_process_matching_rejects_jobs_but_not_model_server_or_own_probe(self):
        examples = [
            (['python3', '/usr/local/share/dlbt_os/cockpit_bizon_ai/agent/backend.py', 'chat'], 'python3'),
            (['python3', '/opt/release/cockpit_bizon_ai/agent/executor.py'], 'python3'),
            (['python3', '/opt/release/cockpit_support/storage/backend.py', 'worker'], 'python3'),
            (['python3', '/usr/local/libexec/bizon-tabs-update', 'install'], 'python3'),
            (['/usr/bin/firefox'], 'firefox'), (['/usr/bin/apt-get'], 'apt-get'),
        ]
        for args, name in examples:
            self.assertIsNotNone(preflight.process_category(args, name))
        self.assertIsNone(preflight.process_category(['ollama', 'serve'], 'ollama'))
        self.assertIsNone(preflight.process_category(['python3', '/usr/local/libexec/bizon-seal-preflight'], 'python3'))

    def test_interactive_parent_shell_flags_cannot_rewrite_history_after_sealing(self):
        for args in [['bash'], ['-bash'], ['bash', '-i'], ['bash', '-il'], ['bash', '-lic', 'command'], ['bash', '--login'], ['bash', '-O', 'extglob'], ['bash', '--norc', '-s']]:
            self.assertTrue(preflight.interactive_shell(args), args)
        for args in [['bash', '-c', 'sudo sealer'], ['bash', '-lc', 'sudo sealer'], ['bash', '/usr/local/sbin/bizon-seal-image', '--seal-and-poweroff'], ['bash', '--norc', '--', '/path/script']]:
            self.assertFalse(preflight.interactive_shell(args), args)

    def test_only_exact_idle_unattended_shutdown_watcher_is_excluded(self):
        watcher = ['/usr/bin/python3', '/usr/share/unattended-upgrades/unattended-upgrade-shutdown', '--wait-for-signal']
        self.assertIsNone(preflight.process_category(watcher, 'unattended-upgr'))
        for args in [watcher[:-1], watcher + ['--debug'], ['/usr/bin/python3', '/usr/bin/unattended-upgrade'], ['/usr/bin/python3', '/tmp/unattended-upgrade-shutdown', '--wait-for-signal']]:
            self.assertEqual(preflight.process_category(args, 'unattended-upgr'), 'software installation or update')
        self.assertEqual(preflight.process_category(['/usr/bin/apt-get', 'upgrade'], 'apt-get'), 'software installation or update')

    def test_mount_and_symlink_parent_are_rejected_without_modification(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            actual = root / 'actual'; actual.mkdir()
            linked = root / 'linked'; linked.symlink_to(actual, target_is_directory=True)
            file = actual / 'preserve'; file.write_text('do not remove')
            # Resolve the platform /var -> /private/var link for this fixture only.
            actual = actual.resolve(); linked = root.resolve() / 'linked'
            self.assertTrue(preflight.path_checks([str(linked / 'preserve')], []))
            self.assertTrue(preflight.path_checks([str(actual)], [actual / 'mounted']))
            self.assertFalse(preflight.path_checks([str(actual)], []))
            self.assertEqual(file.read_text(), 'do not remove')

    def test_read_only_helper_does_not_hide_probe_failure(self):
        with patch.object(preflight.os, 'geteuid', return_value=0), patch.object(preflight.sys, 'platform', 'linux'), patch.object(preflight, 'readiness', side_effect=preflight.CheckError('Unable to inspect jobs')):
            self.assertEqual(preflight.main(['--']), 1)

    def test_cleanup_unlinks_nested_symlink_without_reading_or_removing_its_target(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(preflight, 'fd_mount', return_value='fixture'):
            root = Path(temporary).resolve()
            target = root / 'factory'; target.mkdir()
            outside = root / 'preserved'; outside.mkdir()
            (outside / 'customer.txt').write_text('keep')
            (target / 'linked').symlink_to(outside, target_is_directory=True)
            (target / 'factory.txt').write_text('remove')
            preflight.clean_path(str(target))
            self.assertFalse(target.exists())
            self.assertEqual((outside / 'customer.txt').read_text(), 'keep')

    def test_cleanup_refuses_parent_symlink_even_without_earlier_preflight(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(preflight, 'fd_mount', return_value='fixture'):
            root = Path(temporary).resolve()
            outside = root / 'preserved'; outside.mkdir()
            (outside / 'customer.txt').write_text('keep')
            (root / 'linked').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(OSError):
                preflight.clean_path(str(root / 'linked/customer.txt'))
            self.assertEqual((outside / 'customer.txt').read_text(), 'keep')

    def test_cleanup_refuses_new_mount_boundary_before_removing_contents(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            target = root / 'factory'; target.mkdir()
            (target / 'customer.txt').write_text('keep')
            parent_inode = root.stat().st_ino
            with patch.object(preflight, 'fd_mount', side_effect=lambda fd: 'original' if os.fstat(fd).st_ino == parent_inode else 'new-mount'):
                with self.assertRaises(preflight.CheckError):
                    preflight.clean_path(str(target))
            self.assertEqual((target / 'customer.txt').read_text(), 'keep')

    def test_log_truncation_preserves_mode_and_refuses_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(preflight, 'fd_mount', return_value='fixture'):
            root = Path(temporary).resolve()
            log = root / 'factory.log'; log.write_text('factory'); log.chmod(0o640)
            linked = root / 'linked.log'; linked.symlink_to(log)
            with self.assertRaises(OSError):
                preflight.clean_path(str(linked), truncate=True)
            self.assertEqual(log.read_text(), 'factory')
            preflight.clean_path(str(log), truncate=True)
            self.assertEqual(log.read_bytes(), b'')
            self.assertEqual(log.stat().st_mode & 0o777, 0o640)

    def test_installer_defaults_to_preview(self):
        result = subprocess.run([os.sys.executable, '-I', str(BASE / 'install_image_sealer.py')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('No changes made', result.stdout)
        self.assertNotIn('Installed factory-sealing tools', result.stdout)


if __name__ == '__main__':
    unittest.main()
