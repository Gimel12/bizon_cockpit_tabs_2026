"""Independent CPU/RAM runner regressions; only disposable SQLite fixtures, no workload or services."""
import argparse
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('cpu_ram_runner', BASE / 'provision/bizon_cpu_ram_test.py')
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
GiB, MiB = 1024**3, 1024**2


def snapshot():
    return {
        'issues': [], 'boot_id': 'boot-a', 'recorder': 'invocation-a', 'database': [1, 100],
        'tables': {name: {'rows': 2, 'last': 2} for name in runner.TABLES},
        'edac': {'mc0/ce_count': 3, 'mc0/ue_count': 0},
        'trace': {'mce/mce_record': True, 'ras/mc_event': True, 'ras/extlog_mem_event': True, 'ras/aer_event': True},
        'loss': {'cpu0:overrun': 1, 'cpu0:commit overrun': 0, 'cpu0:dropped events': 0},
        'mce_available': True, 'ecc_available': True,
    }


def state():
    return {'new_events': {}, 'edac_delta': {}, 'kernel_events': [], 'safety_stop': '',
            'stop_requested': False, 'monitoring_gaps': [],
            'coverage': {'mce_available': True, 'ecc_available': True}}


class DurationTests(unittest.TestCase):
    def test_units_and_inclusive_limits(self):
        for text, expected in [('10', 10), ('10s', 10), ('30m', 1800), ('1h', 3600), ('7d', 604800), ('604800s', 604800)]:
            self.assertEqual(runner.duration(text), expected)

    def test_invalid_or_unbounded_durations_are_rejected(self):
        for text in ['', '0', '9s', '604801s', '8d', '-1h', '1.5h', '1e5', 'inf', 'NaN', '1h; poweroff', '1h\n', ' 1h']:
            with self.subTest(text=text), self.assertRaises(argparse.ArgumentTypeError):
                runner.duration(text)


class MemoryTests(unittest.TestCase):
    def test_available_memory_and_os_reserve_bound_target(self):
        plan = runner.memory_plan(64 * GiB, 60 * GiB)
        self.assertLessEqual(plan['bytes'], 60 * GiB - plan['reserve_bytes'])
        self.assertLessEqual(plan['bytes'], 64 * GiB * 85 // 100)
        self.assertEqual(plan['bytes'] % MiB, 0)
        self.assertGreaterEqual(plan['reserve_bytes'], 2 * GiB)
        self.assertLess(plan['limit_bytes'], 60 * GiB)

    def test_explicit_small_allocation_and_minimum_boundary(self):
        self.assertEqual(runner.memory_plan(64 * GiB, 50 * GiB, override_mib=256)['bytes'], 256 * MiB)
        self.assertEqual(runner.memory_plan(4 * GiB, 3 * GiB, override_mib=512)['bytes'], 512 * MiB)

    def test_unavailable_or_oversized_memory_is_refused(self):
        for total, available, override in [(64 * GiB, 2 * GiB, None), (64 * GiB, 60 * GiB, 255), (64 * GiB, 60 * GiB, 0), (64 * GiB, 60 * GiB, -1), (64 * GiB, 60 * GiB, 1000000), (4 * GiB, 2 * GiB, None)]:
            with self.subTest(total=total, available=available, override=override), self.assertRaises(ValueError):
                runner.memory_plan(total, available, override_mib=override)

    def test_recheck_rejects_target_when_other_work_consumes_the_reserve(self):
        plan = runner.memory_plan(64 * GiB, 60 * GiB)
        with self.assertRaises(ValueError):
            runner.memory_plan(64 * GiB, 40 * GiB, override_mib=plan['bytes'] // MiB)


class CoverageTests(unittest.TestCase):
    def test_unchanged_existing_counters_and_normal_growth_are_not_gaps(self):
        before = snapshot(); after = copy.deepcopy(before)
        self.assertEqual(runner.snapshot_gaps(before, after), [])
        after['tables']['mc_event'] = {'rows': 3, 'last': 3}
        after['edac']['mc0/ce_count'] += 1
        self.assertEqual(runner.snapshot_gaps(before, after), [])

    def test_identity_changes_and_current_probe_failures_are_gaps(self):
        for key, changed, expected in [('boot_id', 'boot-b', 'rebooted'), ('recorder', 'invocation-b', 'restarted'), ('database', [1, 200], 'replaced')]:
            before = snapshot(); after = copy.deepcopy(before); after[key] = changed
            self.assertTrue(any(expected in x for x in runner.snapshot_gaps(before, after)))
        before = snapshot(); after = copy.deepcopy(before); after['issues'] = ['database locked']
        self.assertIn('database locked', runner.snapshot_gaps(before, after))

    def test_counter_rollback_source_disappearance_and_trace_disable_cannot_be_clean(self):
        for key in ['rows', 'last']:
            before = snapshot(); after = copy.deepcopy(before); after['tables']['mc_event'][key] = 1
            self.assertTrue(any('reset' in x for x in runner.snapshot_gaps(before, after)))
        for group, member in [('tables', 'mc_event'), ('edac', 'mc0/ce_count'), ('loss', 'cpu0:overrun'), ('trace', 'ras/mc_event')]:
            before = snapshot(); after = copy.deepcopy(before); del after[group][member]
            self.assertTrue(any('sources changed' in x for x in runner.snapshot_gaps(before, after)))
        before = snapshot(); after = copy.deepcopy(before); after['edac']['mc0/ce_count'] = 0
        self.assertTrue(any('EDAC counter reset' in x for x in runner.snapshot_gaps(before, after)))
        before = snapshot(); after = copy.deepcopy(before); after['trace']['ras/mc_event'] = False
        self.assertTrue(any('disabled' in x for x in runner.snapshot_gaps(before, after)))

    def test_loss_counter_increase_or_reset_is_a_gap(self):
        for value in [0, 2]:
            before = snapshot(); after = copy.deepcopy(before); after['loss']['cpu0:overrun'] = value
            self.assertTrue(any('lost or trace counters reset' in x for x in runner.snapshot_gaps(before, after)))


class ResultTests(unittest.TestCase):
    def test_completed_result_discloses_unavailable_ecc(self):
        value = state(); value['coverage']['ecc_available'] = False
        phase, message = runner.determine_result(value, 0, True)
        self.assertEqual(phase, 'completed'); self.assertIn('ECC verification unavailable', message)

    def test_hardware_events_and_safety_stops_override_success_or_user_stop(self):
        for key, entry in [('new_events', {'mc_event': 1}), ('edac_delta', {'mc0/ce_count': 1}), ('kernel_events', [{'message': '[Hardware Error]'}]), ('safety_stop', 'Temperature limit')]:
            value = state(); value[key] = entry; value['stop_requested'] = True
            self.assertEqual(runner.determine_result(value, 0, True)[0], 'failed')

    def test_stopped_failed_or_incomplete_workload_never_completes(self):
        value = state(); value['stop_requested'] = True
        self.assertEqual(runner.determine_result(value, 0, True)[0], 'stopped')
        for code, finished in [(1, True), (-9, True), (None, False), (0, False)]:
            self.assertEqual(runner.determine_result(state(), code, finished)[0], 'incomplete')

    def test_stressor_failure_is_distinct_from_missing_resources_or_unsupported_workload(self):
        phase, message = runner.determine_result(state(), 2, False)
        self.assertEqual(phase, 'failed'); self.assertIn('WORKLOAD FAILED', message)
        for code in [1, 3, 4, 5, 6, 7]:
            self.assertEqual(runner.determine_result(state(), code, False)[0], 'incomplete')

    def test_telemetry_gap_prevents_clean_completion(self):
        value = state(); value['monitoring_gaps'] = ['RAS events dropped']
        self.assertEqual(runner.determine_result(value, 0, True)[0], 'incomplete')

    def test_missing_mce_support_cannot_complete_even_without_a_recorded_gap(self):
        value = state(); value['coverage']['mce_available'] = False
        self.assertEqual(runner.determine_result(value, 0, True)[0], 'incomplete')

    def test_plain_status_reports_lost_monitor_after_reboot_as_incomplete(self):
        with patch.object(runner, 'latest', return_value=(Path('/fixture'), {'phase': 'running'})), patch.object(runner, 'show') as show, patch.object(runner, 'unit_info', return_value={'ActiveState': 'inactive'}):
            self.assertEqual(runner.watch(False), 2)
        self.assertEqual(show.call_args.args[0]['phase'], 'incomplete')
        self.assertIn('INCOMPLETE', show.call_args.args[0]['result'])


class WorkloadTests(unittest.TestCase):
    def test_success_summary_requires_all_requested_workers_and_no_skips_or_failures(self):
        log = 'stress-ng: info: skipped: 0\nstress-ng: info: passed: 3: cpu (2) vm (1)\nstress-ng: info: failed: 0\nstress-ng: info: successful run completed in 30.00 secs'
        self.assertTrue(runner.workload_summary(log, 2))
        for changed in [log.replace('cpu (2)', 'cpu (1)'), log.replace('vm (1)', 'vm (0)'), log.replace('skipped: 0', 'skipped: 1'), log.replace('failed: 0', 'failed: 1'), log.replace('successful run completed', 'unsuccessful run completed'), '', 'successful run completed']:
            self.assertFalse(runner.workload_summary(changed, 2), changed)

    def test_workload_has_one_memory_worker_explicit_size_verification_and_runtime(self):
        config = {'cpu_workers': 24, 'memory': {'bytes': 512 * MiB}, 'duration_seconds': 60}
        args = runner.workload_argv(config)
        self.assertEqual(args[0], '/usr/bin/stress-ng')
        self.assertEqual(args[args.index('--vm') + 1], '1')
        self.assertEqual(args[args.index('--vm-bytes') + 1], str(512 * MiB))
        self.assertEqual(args[args.index('--cpu') + 1], '24')
        self.assertEqual(args[args.index('--timeout') + 1], '60s')
        for flag in ['--verify', '--abort', '--oomable', '--vm-keep']:
            self.assertIn(flag, args)
        self.assertNotIn('--all', args); self.assertNotIn('--maximize', args)

    def test_load_cgroup_bounds_memory_swap_runtime_and_scope(self):
        config = {'cpu_workers': 2, 'memory': {'bytes': 512 * MiB, 'limit_bytes': 1024 * MiB}, 'duration_seconds': 60}
        with patch.object(runner, 'checked') as check:
            runner.launch_load(config, Path('/fixture/report with spaces'))
        args = check.call_args.args[0]
        self.assertIn('--property=MemoryMax=' + str(1024 * MiB), args)
        self.assertIn('--property=MemorySwapMax=0', args)
        self.assertIn('--property=RuntimeMaxSec=90', args)
        self.assertIn('--property=User=nobody', args)
        self.assertIn('--property=NoNewPrivileges=yes', args)
        self.assertIn('--property=WorkingDirectory=/tmp', args)
        self.assertIn('--property=BindsTo=' + runner.UNIT, args)
        self.assertEqual(args[args.index('--') + 1:], runner.workload_argv(config))


class RasDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ras.db'
        self.real_connect = sqlite3.connect
        self.connections = []
        with self.fixture_connect() as db:
            db.executescript('CREATE TABLE mc_event(id INTEGER PRIMARY KEY, err_count INTEGER, err_type TEXT); CREATE TABLE mce_record(id INTEGER PRIMARY KEY, status INTEGER); CREATE TABLE extlog_event(id INTEGER PRIMARY KEY, error_count INTEGER, cper_data BLOB); CREATE TABLE aer_event(id INTEGER PRIMARY KEY, err_type TEXT);')
            db.executescript("INSERT INTO mc_event VALUES(1,7,'Corrected'),(2,9,'Corrected'); INSERT INTO mce_record VALUES(1,123),(2,456); INSERT INTO extlog_event VALUES(1,2,X'0102'),(2,3,X'0405'); INSERT INTO aer_event VALUES(1,'Corrected'),(2,'Corrected');")

    def fixture_connect(self):
        connection = self.real_connect(self.path)
        self.connections.append(connection)
        self.addCleanup(connection.close)
        return connection

    def events(self, before, after):
        with patch.object(runner.sqlite3, 'connect', side_effect=lambda *args, **kwargs: self.fixture_connect()) as connect:
            result = runner.ras_new_events(before, after)
        if before['database'] == after['database']:
            self.assertIn('mode=ro', connect.call_args.args[0]); self.assertEqual(connect.call_args.kwargs.get('timeout'), 2)
        else:
            connect.assert_not_called()
        return result

    def test_preexisting_database_errors_are_not_counted_as_new(self):
        before = snapshot()
        self.assertEqual(self.events(before, copy.deepcopy(before)), ({}, []))

    def test_new_ids_are_counted_by_event_multiplicity_and_upper_snapshot_bound(self):
        with self.fixture_connect() as db:
            db.executescript("INSERT INTO mc_event VALUES(3,4,'Corrected'),(4,0,'Unknown'),(5,99,'Corrected'); INSERT INTO mce_record VALUES(3,-1); INSERT INTO extlog_event VALUES(3,6,X'CAFE'); INSERT INTO aer_event VALUES(3,'Fatal');")
        before = snapshot(); after = copy.deepcopy(before)
        after['tables']['mc_event'] = {'rows': 4, 'last': 4}
        for name in ['mce_record', 'extlog_event', 'aer_event']:
            after['tables'][name] = {'rows': 3, 'last': 3}
        counts, details = self.events(before, after)
        self.assertEqual(counts, {'mc_event': 5, 'mce_record': 1, 'extlog_event': 6, 'aer_event': 1})
        self.assertFalse(any(row['record']['id'] == 5 for row in details))
        self.assertEqual(next(row['record']['cper_data'] for row in details if row['source'] == 'extlog_event'), 'cafe')

    def test_replaced_database_and_missing_sources_are_not_mixed_into_counts(self):
        before = snapshot(); after = copy.deepcopy(before); after['database'] = [1, 999]
        self.assertEqual(self.events(before, after), ({}, []))
        self.assertTrue(runner.snapshot_gaps(before, after))
        after = copy.deepcopy(before); del after['tables']['mc_event']
        self.assertEqual(self.events(before, after), ({}, []))
        self.assertTrue(runner.snapshot_gaps(before, after))

    def test_all_events_counted_even_when_detail_rows_are_capped(self):
        with self.fixture_connect() as db:
            db.executemany('INSERT INTO mc_event VALUES(?,?,?)', [(i, 2, 'Corrected') for i in range(3, 154)])
        before = snapshot(); after = copy.deepcopy(before)
        after['tables']['mc_event'] = {'rows': 153, 'last': 153}
        counts, details = self.events(before, after)
        self.assertEqual(counts['mc_event'], 302)
        self.assertEqual(len(details), 100)

    def test_database_failure_propagates_instead_of_returning_no_errors(self):
        with patch.object(runner.sqlite3, 'connect', side_effect=sqlite3.OperationalError('locked')):
            with self.assertRaises(sqlite3.OperationalError):
                runner.ras_new_events(snapshot(), snapshot())

    def test_event_poll_explicitly_closes_its_readonly_connection(self):
        self.events(snapshot(), snapshot())
        with self.assertRaises(sqlite3.ProgrammingError):
            self.connections[-1].execute('SELECT 1')


class KernelEventTests(unittest.TestCase):
    def test_benign_capability_boot_messages_do_not_count_as_faults(self):
        for line in ['mce: CPU supports 10 MCE banks', 'EDAC MC: Ver: 3.0.0', 'RAS: Correctable Errors collector initialized.', 'mce: [Hardware Error]: Machine check events logged']:
            self.assertEqual(bool(runner.HARDWARE_RE.search(line)), '[Hardware Error]' in line)

    def test_actual_fault_messages_are_recognized(self):
        for line in ['EDAC MC0: 1 CE on DIMM_A1', 'EDAC MC0: 1 UE on DIMM_A1', 'Memory failure: page recovery failed', 'Out of memory: Killed process 123 (stress-ng)', 'CPU0: critical temperature reached']:
            self.assertIsNotNone(runner.HARDWARE_RE.search(line), line)

    def test_same_sensor_labels_on_different_cpu_devices_do_not_hide_hot_socket(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for index, milli_c in enumerate([100000, 40000]):
                sensor = root / ('hwmon' + str(index)); sensor.mkdir()
                (sensor / 'name').write_text('coretemp\n')
                (sensor / 'temp1_label').write_text('Core 0\n')
                (sensor / 'temp1_input').write_text(str(milli_c))
            original_path = Path
            with patch.object(runner, 'Path', side_effect=lambda value: root if value == '/sys/class/hwmon' else original_path(value)):
                readings = runner.temperatures()
            self.assertEqual(sorted(readings.values()), [40, 100])


class BoundedCommandTests(unittest.TestCase):
    def test_stdout_stderr_exit_status_and_invalid_utf8_are_preserved(self):
        result = runner.command([sys.executable, '-c', "import sys; sys.stdout.buffer.write(b'hello\\xff'); sys.stderr.write('diagnostic'); sys.exit(7)"])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout, 'hello\ufffd')
        self.assertEqual(result.stderr, 'diagnostic')

    def test_both_streams_are_drained_without_pipe_deadlock(self):
        result = runner.command([sys.executable, '-c', "import sys; sys.stdout.write('o'*262144); sys.stdout.flush(); sys.stderr.write('e'*262144); sys.stderr.flush()"], timeout=5)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 262144)
        self.assertEqual(len(result.stderr), 262144)

    def test_each_output_stream_is_bounded_and_child_reaped(self):
        original = subprocess.Popen
        for stream in ['stdout', 'stderr']:
            children = []
            def create(*args, **kwargs):
                child = original(*args, **kwargs); children.append(child); return child
            with patch.object(runner.subprocess, 'Popen', side_effect=create), self.assertRaisesRegex(RuntimeError, 'output limit'):
                runner.command([sys.executable, '-c', f"import sys,time; sys.{stream}.write('x'*(2*1024*1024+1)); sys.{stream}.flush(); time.sleep(30)"], timeout=5)
            self.assertEqual(len(children), 1)
            self.assertIsNotNone(children[0].poll())

    def test_timeout_is_bounded_and_child_reaped(self):
        original = subprocess.Popen; children = []
        def create(*args, **kwargs):
            child = original(*args, **kwargs); children.append(child); return child
        began = time.monotonic()
        with patch.object(runner.subprocess, 'Popen', side_effect=create), self.assertRaises(subprocess.TimeoutExpired):
            runner.command([sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.1)
        self.assertLess(time.monotonic() - began, 3)
        self.assertIsNotNone(children[0].poll())

    def test_ras_diagnostic_uses_summary_not_all_historical_records(self):
        with patch.object(runner, 'command', return_value=subprocess.CompletedProcess([], 0, 'summary', '')) as command:
            runner.ras_text()
        args = [call.args[0] for call in command.call_args_list]
        self.assertTrue(any('--summary' in arg for arg in args))
        self.assertFalse(any('--errors' in arg for arg in args))


class StopTests(unittest.TestCase):
    def test_repeated_stop_on_finished_test_is_successful_without_commands(self):
        with patch.object(runner, 'lock', side_effect=lambda *_: contextlib.nullcontext()) as lock, patch.object(runner, 'unit_info', return_value={'ActiveState': 'inactive'}), patch.object(runner, 'command') as command:
            runner.stop_test(); runner.stop_test()
        command.assert_not_called()
        self.assertEqual(lock.call_count, 2)
        self.assertTrue(all(call.args == ('/run/lock/bizon-cpu-ram-control.lock',) for call in lock.call_args_list))

    def test_stopping_monitor_tolerates_load_already_gone_from_bindsto(self):
        with patch.object(runner, 'lock', return_value=contextlib.nullcontext()), patch.object(runner, 'unit_info', side_effect=[{'ActiveState': 'active'}, {'ActiveState': 'inactive'}]) as info, patch.object(runner, 'command', return_value=subprocess.CompletedProcess([], 0, '', '')) as command:
            runner.stop_test()
        self.assertEqual([call.args[0] for call in info.call_args_list], [runner.UNIT, runner.LOAD])
        command.assert_called_once_with(['/usr/bin/systemctl', 'stop', runner.UNIT], timeout=40)

    def test_load_disappearing_between_check_and_stop_is_not_a_failure(self):
        with patch.object(runner, 'lock', return_value=contextlib.nullcontext()), patch.object(runner, 'unit_info', side_effect=[{'ActiveState': 'inactive'}, {'ActiveState': 'active'}, {'ActiveState': 'inactive'}]), patch.object(runner, 'command', return_value=subprocess.CompletedProcess([], 5, '', 'Unit not loaded')) as command:
            runner.stop_test()
        command.assert_called_once_with(['/usr/bin/systemctl', 'stop', runner.LOAD], timeout=40)

    def test_real_stop_failure_is_reported_while_unit_remains_active(self):
        with patch.object(runner, 'lock', return_value=contextlib.nullcontext()), patch.object(runner, 'unit_info', return_value={'ActiveState': 'active'}), patch.object(runner, 'command', return_value=subprocess.CompletedProcess([], 1, '', 'Access denied')), self.assertRaisesRegex(RuntimeError, 'Could not stop .*Access denied'):
            runner.stop_test()

    def test_control_lock_failure_prevents_any_stop_command(self):
        with patch.object(runner, 'lock', side_effect=RuntimeError('already running')), patch.object(runner, 'unit_info') as info, patch.object(runner, 'command') as command, self.assertRaisesRegex(RuntimeError, 'already running'):
            runner.stop_test()
        info.assert_not_called(); command.assert_not_called()


class MonitorStateTests(unittest.TestCase):
    def test_seen_edac_error_remains_failed_after_counter_resets(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); run_id = '20261104T120000Z-01234567'
            directory = root / run_id; directory.mkdir()
            value = state()
            value.update(run_id=run_id, phase='queued', started_at='2026-11-04T12:00:00Z', elapsed_seconds=0,
                         cpu_model='fixture', event_details=[],
                         config={'cpu_workers': 1, 'duration_seconds': 10, 'memory_percent': 85,
                                 'memory': {'bytes': 512 * MiB}, 'max_temperature': 95})
            (directory / 'summary.json').write_text(json.dumps(value))
            (directory / 'stress-ng.log').write_text('skipped: 0\npassed: 2: cpu (1) vm (1)\nfailed: 0\nsuccessful run completed')
            before = snapshot(); increment = copy.deepcopy(before); reset = copy.deepcopy(before)
            increment['edac']['mc0/ce_count'] += 3; reset['edac']['mc0/ce_count'] = 0
            with contextlib.ExitStack() as stack:
                patches = {
                    'RUNS': root, 'STOP': False, 'secure_dir': lambda *_: None,
                    'lock': lambda *_, **__: contextlib.nullcontext(), 'ras_text': lambda: '',
                    'ras_snapshot': unittest.mock.Mock(side_effect=[before, increment, reset]),
                    'journal_start': lambda: 'cursor', 'journal_poll': lambda _: ('cursor', []),
                    'memory_info': lambda: {'MemTotal': 64 * GiB, 'MemAvailable': 60 * GiB},
                    'launch_load': lambda *_: None, 'cpu_ticks': lambda: (100, 20),
                    'ras_new_events': lambda *_: ({}, []), 'temperatures': lambda: {'cpu': 40},
                    'checked': lambda *_, **__: '',
                    'stop_unit': lambda *_, **__: None,
                    'command': lambda *_, **__: subprocess.CompletedProcess([], 0, '', ''),
                    'unit_info': unittest.mock.Mock(side_effect=[{'ActiveState': 'active', 'SubState': 'running'},
                        {'ActiveState': 'active', 'SubState': 'exited', 'Result': 'success', 'ExecMainCode': '1', 'ExecMainStatus': '0'}]),
                }
                for name, replacement in patches.items():
                    stack.enter_context(patch.object(runner, name, replacement))
                stack.enter_context(patch.object(runner.signal, 'signal'))
                stack.enter_context(patch.object(runner.time, 'sleep'))
                stack.enter_context(patch.object(runner.time, 'monotonic', side_effect=[0, 6, 12, 14]))
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                runner.monitor(run_id)
            final = json.loads((directory / 'summary.json').read_text())
            self.assertEqual(final['edac_delta']['mc0/ce_count'], 3)
            self.assertEqual(final['phase'], 'failed')
            self.assertTrue(any('EDAC counter reset' in gap for gap in final['monitoring_gaps']))


if __name__ == '__main__':
    unittest.main()
