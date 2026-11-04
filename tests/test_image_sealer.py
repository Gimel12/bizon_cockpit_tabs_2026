"""Read-only/local-fixture tests. Never install, seal, stop a service or touch real disks."""
import importlib.util
import json
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
        result = self.shell('require_root(){ :; }; expand_cpu_ram_paths(){ :; }; preflight(){ echo READ_ONLY_CHECK; }; seal(){ echo UNEXPECTED_SEAL; }; main --dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('READ_ONLY_CHECK', result.stdout)
        self.assertNotIn('UNEXPECTED_SEAL', result.stdout)
        self.assertIn('/etc/netplan/90-NM-c223fe1d-54d3-4d35-a795-21ba8a1bc0d7.yaml', result.stdout)
        self.assertIn('Remove: /var/mail/bizon', result.stdout)
        self.assertNotIn('Remove: /home/bizon/Documents', result.stdout)
        self.assertNotIn('Remove: /home/bizon/models', result.stdout)
        self.assertNotIn('Remove: /home/bizon/anaconda3', result.stdout)

    def test_refused_preflight_never_reaches_destructive_actions(self):
        result = self.shell('require_root(){ :; }; expand_cpu_ram_paths(){ :; }; preflight(){ echo ACTIVE_WORK; return 1; }; seal(){ echo UNEXPECTED_SEAL; }; main --seal-and-poweroff')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('ACTIVE_WORK', result.stdout)
        self.assertNotIn('UNEXPECTED_SEAL', result.stdout)

    def test_source_does_not_clean_anything(self):
        result = self.shell('printf "SOURCE_ONLY\\n"')
        self.assertEqual(result.stdout, 'SOURCE_ONLY\n')

    def test_random_seed_writer_stops_before_identity_removal_and_poweroff(self):
        # Exercise the real seal orchestration with every system command replaced.
        # Keep even the built-in printf redirect inside the disposable directory.
        for stop_fails in [False, True]:
            with self.subTest(stop_fails=stop_fails), tempfile.TemporaryDirectory() as temporary:
                source = SHELL.read_text().replace('/usr/bin/', 'test_')
                source = source.replace('if [[ ${BASH_SOURCE[0]} == "$0" ]]; then main "$@"; fi', '')
                source = source.replace('/etc/machine-id', temporary + '/machine-id')
                source = source.replace('/var/lib/dbus/machine-id', temporary + '/dbus-machine-id')
                stubs = '''
preflight(){ echo CHECK; }
remove_path(){ echo "REMOVE $1"; }
truncate_log(){ echo "TRUNCATE $1"; }
test_systemctl(){
  echo "SYSTEMCTL $*"
  if [[ $1 == cat ]]; then return 1; fi
  if [[ $* == 'stop systemd-random-seed.service' ]]; then return SEED_STATUS; fi
}
test_install(){ :; }; test_touch(){ :; }; test_chmod(){ :; }; test_ln(){ :; }
test_journalctl(){ :; }; test_sleep(){ :; }; test_sync(){ :; }
FACTORY_PATHS=(factory); IDENTITY_PATHS=(/var/lib/systemd/random-seed)
ROTATED_LOGS=(rotation); LOG_PATHS=(log)
seal
'''.replace('SEED_STATUS', '1' if stop_fails else '0')
                # Main is removed from the local copy; only the stubbed seal runs.
                result = subprocess.run(['/bin/bash', '-c', source + '\n' + stubs], capture_output=True, text=True)
                lines = result.stdout.splitlines()
                self.assertIn('SYSTEMCTL stop systemd-random-seed.service', lines)
                if stop_fails:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(any(line.startswith('REMOVE ') for line in lines))
                    self.assertNotIn('SYSTEMCTL poweroff', lines)
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    stopped = lines.index('SYSTEMCTL stop systemd-random-seed.service')
                    removed = lines.index('REMOVE /var/lib/systemd/random-seed')
                    self.assertLess(stopped, removed)
                    self.assertLess(removed, lines.index('SYSTEMCTL poweroff'))

    def test_desktop_credentials_reset_is_exact_and_preserves_other_dbus_data(self):
        result = self.shell('printf "%s\\n" "${FACTORY_PATHS[@]}"')
        paths = set(result.stdout.splitlines())
        for account in ['/home/bizon', '/root']:
            for suffix in ['/.Xauthority', '/.ICEauthority', '/.dbus/session-bus']:
                self.assertIn(account + suffix, paths)
            self.assertNotIn(account + '/.dbus', paths)
            self.assertNotIn(account, paths)

    def test_exact_factory_allowlist_preserves_unreviewed_paths(self):
        result = self.shell('printf "%s\\n" "${FACTORY_PATHS[@]}"')
        paths = result.stdout.splitlines()
        self.assertEqual(len(paths), len(set(paths)))
        self.assertTrue(all(path.startswith('/') and not any(c in path for c in '*?[') for path in paths))
        self.assertNotIn('/var/lib/bizon-storage', paths)
        self.assertNotIn('/var/lib/bizon-cpu-ram-test', paths)
        self.assertNotIn('/var/lib/bizon-cpu-ram-test/runs', paths)
        self.assertIn('/var/backups/bizon-cpu-ram-install-20261104', paths)
        self.assertNotIn('/etc/netplan', paths)
        self.assertIn('/var/lib/bizon-storage/jobs/ce1253d2b4694b7a85f8c8a078236228', paths)

    def test_home_reset_preserves_model_plugin_binary_and_application_settings_paths(self):
        result = self.shell('printf "%s\\n" "${FACTORY_PATHS[@]}"')
        removed = [Path(p) for p in result.stdout.splitlines()]
        protected = [
            '/home/bizon/.cache/huggingface', '/home/bizon/.cache/vllm',
            '/home/bizon/.local/share/claude/versions', '/home/bizon/.claude/plugins',
            '/home/bizon/.opencode/bin', '/home/bizon/.config/opencode',
            '/home/bizon/models', '/home/bizon/.ollama/models', '/home/bizon/anaconda3',
            '/home/bizon/Documents', '/home/bizon/gpu-burn', '/home/bizon/cuda-samples',
            '/home/bizon/.config/LM Studio/config.json', '/home/bizon/.config/LM Studio/settings.json',
            '/home/bizon/.config/LM Studio/model-catalog.json', '/home/bizon/.docker/config.json',
            '/home/bizon/.config/Docker Desktop/settings.json', '/home/bizon/.config/Docker Desktop/settings-store.json',
        ]
        for text in protected:
            path = Path(text)
            self.assertFalse(any(candidate == path or candidate in path.parents for candidate in removed), text)
        for text in ['/home/bizon/.cache/google-chrome', '/home/bizon/.local/share/main.py/QtWebEngine', '/root/.python_history', '/home/bizon/.config/Code', '/home/bizon/.gitconfig', '/home/bizon/.claude/.credentials.json', '/home/bizon/.claude/settings.local.json', '/home/bizon/.claude/history.jsonl', '/home/bizon/.config/LM Studio/Local Storage', '/home/bizon/.config/Docker Desktop/Cookies']:
            self.assertIn(Path(text), removed)

    def test_session_globs_select_only_targeted_artifacts_and_do_not_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            matches = ['.bash_history-factory.tmp', '.docker/.token_seed', '.docker/.token_seed_old', '.vscode-server/.server.token', '.vscode-server/.server.pid', '.vscode-server/.server.log', '.windsurf-server/.server.token', '.windsurf-server/.server.pid', '.windsurf-server/.server.log']
            preserve = ['.bash_history.keep', '.bash_history-factory.txt', '.docker/config.json', '.vscode-server/extensions/keep', '.vscode-server/.server.json', '.windsurf-server/bin/keep', '.cache/huggingface/model']
            for name in matches + preserve:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('fixture')
            result = subprocess.run(['/bin/bash', '-c', 'source "$1"; FACTORY_PATHS=(); shopt -s nullglob; expand_private_session_files "$2"; printf "%s\\n" "${FACTORY_PATHS[@]}"', 'test', str(SHELL), str(root)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(set(result.stdout.splitlines()), {str(root / name) for name in matches})
            self.assertTrue(all((root / name).read_text() == 'fixture' for name in matches + preserve))

    def test_active_developer_and_embedded_browser_sessions_block_reset(self):
        for args, comm in [
            (['/home/bizon/.local/share/claude/versions/2.1.112'], '2.1.112'),
            (['node', '/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js'], 'node'),
            (['/home/bizon/.opencode/bin/opencode'], 'opencode'),
            (['/home/bizon/.vscode-server/bin/version/node', 'server-main.js'], 'node'),
            (['/home/bizon/.windsurf-server/bin/version/node', 'server-main.js'], 'node'),
            (['/usr/share/code/code'], 'code'), (['QtWebEngineProcess'], 'QtWebEngineProc'),
        ]:
            self.assertIsNotNone(preflight.process_category(args, comm), args)

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

    def test_cpu_ram_controller_and_surviving_stress_workers_block_sealing(self):
        examples = [
            (['python3', '/usr/local/libexec/bizon-cpu-ram-test', '_run'], 'python3'),
            (['python3', '/usr/local/libexec/bizon-cpu-ram-test.py', '_run'], 'python3'),
            (['python3', '/checkout/provision/bizon_cpu_ram_test.py', '_run'], 'python3'),
            (['/usr/bin/stress-ng', '--cpu', '2'], 'stress-ng'),
            (['/usr/bin/stress-ng', '--vm', '1'], 'stress-ng-vm'),
            (['/usr/bin/stress-ng', '--cpu', '2'], 'stress-ng-cpu'),
        ]
        for args, name in examples:
            self.assertEqual(preflight.process_category(args, name), 'CPU/RAM hardware test')
        self.assertIsNone(preflight.process_category(['python3', '/tmp/report.py', '/tmp/bizon-cpu-ram-test-report.html'], 'python3'))

    def test_active_cpu_ram_units_and_stopping_workloads_block_sealing(self):
        for unit in ['bizon-cpu-ram-test.service', 'bizon-cpu-ram-load.service']:
            for state in ['active running', 'activating start', 'deactivating stop-sigterm']:
                with patch.object(preflight, 'command', return_value=f'{unit} loaded {state} CPU RAM test') as command:
                    self.assertTrue(preflight.active_unit_checks())
                argv = command.call_args.args[0]
                self.assertIn(unit, argv)
                self.assertIn('--state=active,activating,deactivating', argv)
        with patch.object(preflight, 'command', return_value=''):
            self.assertFalse(preflight.active_unit_checks())
        with patch.object(preflight, 'command', side_effect=preflight.CheckError('Systemd unavailable')):
            with self.assertRaises(preflight.CheckError):
                preflight.active_unit_checks()

    def test_cpu_ram_lock_blocks_even_before_the_unit_starts(self):
        self.assertIn('/run/lock/bizon-cpu-ram-test.lock', preflight.STATE_LOCK_PATHS)
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / 'test.lock'; lock.touch()
            locks = Path(temporary) / 'locks'
            info = lock.stat()
            locks.write_text(f'1: FLOCK ADVISORY WRITE 1234 {os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino} 0 EOF\n')
            self.assertTrue(preflight.locked_state_checks([lock], locks))
            locks.write_text('')
            self.assertFalse(preflight.locked_state_checks([lock], locks))
            self.assertTrue(lock.exists())

    def cpu_ram_fixture(self, temporary, **updates):
        root = Path(temporary).resolve() / 'cpu-ram'; root.mkdir()
        run_id = '20261104T164501Z-a12b34cd'
        run = root / 'runs' / run_id; run.mkdir(parents=True)
        data = {'run_id': run_id, 'phase': 'completed', 'factory_test': True}
        data.update(updates)
        (run / 'summary.json').write_text(json.dumps(data))
        (run / 'report.txt').write_text('factory report')
        (root / 'latest.json').write_text(json.dumps({'run_id': run_id}))
        return root, run

    def test_cpu_ram_selection_is_read_only_and_selects_only_explicit_factory_paths(self):
        for phase in ['completed', 'stopped', 'failed', 'incomplete']:
            with tempfile.TemporaryDirectory() as temporary:
                root, run = self.cpu_ram_fixture(temporary, phase=phase)
                before = {str(p): (p.read_bytes(), p.stat().st_mode) for p in root.rglob('*') if p.is_file()}
                self.assertEqual(preflight.cpu_ram_factory_paths(root, os.getuid()), [root / 'latest.json', run])
                self.assertEqual(before, {str(p): (p.read_bytes(), p.stat().st_mode) for p in root.rglob('*') if p.is_file()})
                self.assertTrue(root.is_dir())
                self.assertTrue((root / 'runs').is_dir())

    def test_cpu_ram_customer_unmarked_and_active_runs_are_never_selected(self):
        for updates in [
            {'factory_test': False}, {'factory_test': 'true'}, {'factory_test': 1},
            {'phase': 'queued'}, {'phase': 'running'}, {'phase': 'unknown'}, {'phase': []},
            {'run_id': '../elsewhere'},
        ]:
            with tempfile.TemporaryDirectory() as temporary:
                root, run = self.cpu_ram_fixture(temporary, **updates)
                with self.assertRaises(preflight.CheckError, msg=str(updates)):
                    preflight.cpu_ram_factory_paths(root, os.getuid())
                self.assertEqual((run / 'report.txt').read_text(), 'factory report')
        with tempfile.TemporaryDirectory() as temporary:
            root, run = self.cpu_ram_fixture(temporary)
            data = json.loads((run / 'summary.json').read_text()); del data['factory_test']
            (run / 'summary.json').write_text(json.dumps(data))
            with self.assertRaises(preflight.CheckError):
                preflight.cpu_ram_factory_paths(root, os.getuid())

    def test_cpu_ram_unknown_artifacts_and_partial_metadata_require_review(self):
        for scenario in ['root-file', 'run-file', 'nested-directory', 'bad-id', 'no-summary', 'malformed', 'array']:
            with tempfile.TemporaryDirectory() as temporary:
                root, run = self.cpu_ram_fixture(temporary)
                if scenario == 'root-file': (root / 'customer.txt').write_text('keep')
                elif scenario == 'run-file': (run / '.summary.json.interrupted').write_text('keep')
                elif scenario == 'nested-directory': (run / 'attachments').mkdir()
                elif scenario == 'bad-id': run.rename(run.with_name('customer-run'))
                elif scenario == 'no-summary': (run / 'summary.json').unlink()
                elif scenario == 'malformed': (run / 'summary.json').write_text('{')
                elif scenario == 'array': (run / 'summary.json').write_text('[]')
                with self.assertRaises(preflight.CheckError, msg=scenario):
                    preflight.cpu_ram_factory_paths(root, os.getuid())

    def test_cpu_ram_latest_pointer_cannot_expand_cleanup_to_other_paths(self):
        for metadata in [{'run_id': '../../customer'}, {'run_id': []}, {'run_id': 'missing'}, {}, {'run_id': '20261104T164501Z-a12b34cd', 'extra': True}]:
            with tempfile.TemporaryDirectory() as temporary:
                root, run = self.cpu_ram_fixture(temporary)
                (root / 'latest.json').write_text(json.dumps(metadata))
                with self.assertRaises(preflight.CheckError, msg=str(metadata)):
                    preflight.cpu_ram_factory_paths(root, os.getuid())
                self.assertTrue(run.exists())

    def test_cpu_ram_links_permissions_and_unexpected_owners_are_rejected(self):
        for scenario in ['file-symlink', 'run-symlink', 'hardlink', 'writable-file', 'writable-run', 'owner']:
            with tempfile.TemporaryDirectory() as temporary:
                root, run = self.cpu_ram_fixture(temporary)
                report = run / 'report.txt'
                if scenario == 'file-symlink':
                    outside = root.parent / 'customer.txt'; outside.write_text('keep')
                    report.unlink(); report.symlink_to(outside)
                elif scenario == 'run-symlink':
                    outside = root.parent / 'customer'; run.rename(outside); run.symlink_to(outside, target_is_directory=True)
                elif scenario == 'hardlink': os.link(report, root.parent / 'customer.txt')
                elif scenario == 'writable-file': report.chmod(0o666)
                elif scenario == 'writable-run': run.chmod(0o777)
                owner = os.getuid() + 1 if scenario == 'owner' else os.getuid()
                with self.assertRaises(preflight.CheckError, msg=scenario):
                    preflight.cpu_ram_factory_paths(root, owner)

    def test_cpu_ram_empty_install_needs_no_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve() / 'cpu-ram'
            self.assertEqual(preflight.cpu_ram_factory_paths(root, os.getuid()), [])
            root.mkdir(); (root / 'runs').mkdir()
            self.assertEqual(preflight.cpu_ram_factory_paths(root, os.getuid()), [])

    def test_cpu_ram_report_change_between_preview_and_final_lock_blocks_sealing(self):
        first = preflight.CPU_RAM_ROOT / 'runs/20261104T164501Z-a12b34cd'
        second = preflight.CPU_RAM_ROOT / 'runs/20261104T164600Z-12ab34cd'
        latest = preflight.CPU_RAM_ROOT / 'latest.json'
        with patch.object(preflight, 'cpu_ram_factory_paths', return_value=[latest, first]):
            self.assertFalse(preflight.cpu_ram_selection_checks([str(latest), str(first), '/unrelated/path']))
            self.assertTrue(preflight.cpu_ram_selection_checks([str(preflight.CPU_RAM_ROOT)]))
            self.assertTrue(preflight.cpu_ram_selection_checks([]))
        with patch.object(preflight, 'cpu_ram_factory_paths', return_value=[latest, first, second]):
            self.assertTrue(preflight.cpu_ram_selection_checks([str(latest), str(first)]))

    def test_cpu_ram_selector_refusal_cannot_be_lost_in_shell_expansion(self):
        with tempfile.TemporaryDirectory() as temporary:
            helper = Path(temporary) / 'helper.py'
            helper.write_text('import sys\nprint("CPU_REPORTS_REQUIRE_REVIEW", file=sys.stderr)\nraise SystemExit(1)\n')
            result = subprocess.run(['/bin/bash', '-c', 'source "$1"; SEAL_TEST_HELPER=$2; helper_path(){ printf "%s\\n" "$SEAL_TEST_HELPER"; }; require_root(){ :; }; preflight(){ echo UNEXPECTED; }; seal(){ echo UNEXPECTED; }; main --dry-run', 'test', str(SHELL), str(helper)], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('UNEXPECTED', result.stdout)
            self.assertIn('CPU_REPORTS_REQUIRE_REVIEW', result.stderr)

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
