#!/usr/bin/env python3
"""Installer and shell integration checks; never start a CPU/RAM workload."""
import base64
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import install_cpu_ram_test as installer


MENU = r'''# Existing workstation settings
export KEEP_THIS_SETTING="unchanged"
alias bizonhelp='
echo Bizonhelp_4.1
echo -e cpu-test ----------"\033[31;1mStress test for your CPU\033[0m"
echo -e gpu-test ----------"\033[31;1mTest GPUs\033[0m"
echo -e ipmipassreset -----"\033[31;1mReset password to 'Bizon123'\033[0m"
echo -e anydesk-restore ---"\033[31;1mRestore new Anydesk ID\033[0m"
echo'
alias cpu-test='s-tui'
alias anydesk-restore='
sudo rm -f /etc/anydesk/service.conf
sudo reboot
'
alias unrelated='printf preserved'
# End of existing workstation settings

'''
STOCK = '''# Skeleton configuration
case $- in
    *i*) ;;
      *) return;;
esac
alias ll='ls -alF'
'''


class ShellTests(unittest.TestCase):
    def test_menu_update_preserves_old_cpu_test_and_other_settings(self):
        result = installer.rewrite_bashrc(MENU.encode()).decode()
        self.assertIn("alias cpu-test='s-tui'", result)
        self.assertIn('export KEEP_THIS_SETTING="unchanged"', result)
        self.assertIn("alias unrelated='printf preserved'", result)
        self.assertIn("Reset password to 'Bizon123'", result)
        self.assertNotIn('anydesk-restore', result)
        self.assertNotIn('sudo reboot', result)
        for name, command in installer.ALIASES.items():
            self.assertEqual(result.count("alias " + name + "='" + command + "'"), 1)
            self.assertEqual(result.count('echo -e ' + name + ' '), 1)
        self.assertEqual(installer.rewrite_bashrc(result.encode()).decode(), result)
        installer.check_shell(result.encode())

    def test_stock_configuration_receives_aliases_and_guarded_help(self):
        result = installer.rewrite_bashrc(STOCK.encode())
        self.assertTrue(result.startswith(STOCK.encode()))
        self.assertIn(b'if ! type bizonhelp >/dev/null 2>&1; then', result)
        installer.check_shell(result)
        self.assertEqual(installer.rewrite_bashrc(result), result)

    def test_existing_help_is_not_overridden_and_fallback_runs_for_new_users(self):
        for original, marker in ((MENU, 'Bizonhelp_4.1'), ('# new user\n', 'BIZON CPU/RAM test commands')):
            result = installer.rewrite_bashrc(original.encode())
            with tempfile.TemporaryDirectory() as directory:
                rc = Path(directory) / 'bashrc'
                rc.write_bytes(result)
                probe = Path(directory) / 'probe.sh'
                probe.write_text('shopt -s expand_aliases\nsource "$1"\nbizonhelp\n')
                check = subprocess.run(['/bin/bash', '--noprofile', '--norc', str(probe), str(rc)],
                                       capture_output=True, text=True,
                                       env={'PATH': '/usr/bin:/bin', 'BASH_ENV': '/dev/null'})
            self.assertEqual(check.returncode, 0, check.stderr)
            self.assertIn(marker, check.stdout)
            self.assertIn('cpu-ram-status', check.stdout)

    def test_existing_custom_help_function_is_preserved(self):
        original = b'function bizonhelp { printf "%s\\n" "Custom help"; }\n'
        result = installer.rewrite_bashrc(original)
        self.assertTrue(result.startswith(original))
        installer.check_shell(result)

    def test_refuses_conflicting_alias_unknown_menu_and_modified_anydesk_command(self):
        for original in (
                MENU + "alias cpu-ram-test='something else'\n",
                MENU.replace("echo'\n", "not-the-menu-end\n"),
                MENU.replace('sudo reboot', 'echo custom-action'),
                MENU + installer.BEGIN + '\n'):
            with self.assertRaises(installer.InstallError):
                installer.rewrite_bashrc(original.encode())

    def test_retains_anydesk_entries_when_executable_still_exists(self):
        result = installer.rewrite_bashrc(MENU.encode(), retire_anydesk=False)
        self.assertIn(b'alias anydesk-restore=', result)
        self.assertIn(b'echo -e anydesk-restore ', result)

    def test_syntax_validation_does_not_execute_commands_or_bash_env(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'unexpected'
            environment = Path(directory) / 'environment'
            environment.write_text('touch ' + str(marker) + '\n')
            with patch.dict(os.environ, {'BASH_ENV': str(environment)}):
                installer.check_shell(('touch ' + str(marker) + '\n').encode())
            self.assertFalse(marker.exists())

    def test_launcher_preserves_arguments_without_shell_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            recorder = root / 'recorder.sh'
            recorder.write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
            recorder.chmod(0o755)
            wrapper = root / 'wrapper.sh'
            # Substitute only the fixed interpreter for a harmless recorder;
            # exercise the exact production shell argument forwarding.
            wrapper.write_bytes(installer.WRAPPER.replace(b'/usr/bin/python3', str(recorder).encode(), 1))
            marker = root / 'must-not-exist'
            dangerous = '$(touch ' + str(marker) + ')'
            result = subprocess.run(['/bin/sh', str(wrapper), 'start', '--duration', '30m', dangerous],
                                    capture_output=True, text=True, check=True)
            self.assertEqual(result.stdout.splitlines(), ['-I', str(installer.RUNNER), 'start', '--duration', '30m', dangerous])
            self.assertFalse(marker.exists())


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / 'image'
        self.root.mkdir()
        self.backup = self.base / 'private-backup'
        self.source = self.base / 'runner.py'
        self.source.write_text('"""Test fixture only; never run a workload."""\n')
        self.enterContext(patch.object(installer, 'ROOT_UID', os.getuid()))
        self.enterContext(patch.object(installer, 'ROOT_GID', os.getgid()))
        self.enterContext(patch.object(installer.os, 'geteuid', return_value=0))
        self.chown = self.enterContext(patch.object(installer.os, 'chown'))
        self.fchown = self.enterContext(patch.object(installer.os, 'fchown'))
        for path, content in ((installer.BASHRC, MENU), (installer.SKEL, STOCK)):
            destination = self.at(path)
            destination.parent.mkdir(parents=True)
            destination.write_text(content)
            destination.chmod(0o640)
        for choices in installer.DEPENDENCIES.values():
            path = self.at(Path(choices[0]))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('fixture dependency\n')
            path.chmod(0o755)

    def at(self, path):
        return installer.at(self.root, path)

    def install(self):
        return installer.install(self.root, self.source, self.backup)

    def test_installs_root_files_private_reports_preserves_shell_owners_and_backups(self):
        original_shell = installer.snapshot(self.at(installer.BASHRC))
        result = self.install()
        self.assertFalse(result['workload_started'])
        self.assertEqual(len(result['changed']), 4)
        self.assertEqual(self.at(installer.RUNNER).read_bytes(), self.source.read_bytes())
        self.assertEqual(self.at(installer.LAUNCHER).read_bytes(), installer.WRAPPER)
        self.assertEqual(stat.S_IMODE(self.at(installer.RUNNER).stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(self.at(installer.REPORTS).stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.at(installer.BASHRC).stat().st_mode), 0o640)
        backup_file = self.backup / 'cpu-ram-install-backup.json'
        self.assertEqual(stat.S_IMODE(backup_file.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.backup.stat().st_mode), 0o700)
        saved = json.loads(backup_file.read_text())
        self.assertEqual(saved['originals'][str(installer.BASHRC)], original_shell)
        self.assertIsNone(saved['originals'][str(installer.RUNNER)])
        self.fchown.assert_any_call(unittest.mock.ANY, original_shell['uid'], original_shell['gid'])

    def test_reinstall_is_idempotent_and_source_upgrade_keeps_first_backup(self):
        self.install()
        backup_file = self.backup / 'cpu-ram-install-backup.json'
        original_backup = backup_file.read_bytes()
        self.assertEqual(self.install()['changed'], [])
        self.source.write_text('# new runner revision\n')
        self.assertEqual(self.install()['changed'], [str(installer.RUNNER)])
        self.assertEqual(backup_file.read_bytes(), original_backup)

    def test_missing_dependency_or_invalid_source_prevents_changes(self):
        self.at(Path('/usr/bin/stress-ng')).unlink()
        with self.assertRaises(installer.InstallError):
            self.install()
        self.assertFalse(self.at(installer.RUNNER).exists())
        self.assertFalse(self.backup.exists())

    def test_symlinked_shell_configuration_is_rejected(self):
        path = self.at(installer.BASHRC)
        original = path.read_bytes()
        path.unlink()
        outside = self.base / 'outside'
        outside.write_bytes(original)
        path.symlink_to(outside)
        with self.assertRaises(installer.InstallError):
            self.install()
        self.assertEqual(outside.read_bytes(), original)

    def test_failure_rolls_back_existing_shell_files_and_new_runner(self):
        write = installer.write_atomic
        failed = False

        def fail_once(path, value):
            nonlocal failed
            if path == self.at(installer.SKEL) and not failed:
                failed = True
                raise OSError('injected failure')
            return write(path, value)

        with patch.object(installer, 'write_atomic', side_effect=fail_once):
            with self.assertRaises(OSError):
                self.install()
        self.assertFalse(self.at(installer.RUNNER).exists())
        self.assertFalse(self.at(installer.LAUNCHER).exists())
        self.assertEqual(self.at(installer.BASHRC).read_text(), MENU)
        self.assertEqual(self.at(installer.SKEL).read_text(), STOCK)


if __name__ == '__main__':
    unittest.main()
