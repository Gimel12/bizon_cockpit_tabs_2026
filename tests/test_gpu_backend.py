"""GPU snapshot safety tests. No actual GPU or power-setting calls."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

PATH = Path(__file__).resolve().parents[1] / 'cockpit_gpu/py_backend/gpu_backend.py'
spec = importlib.util.spec_from_file_location('gpu_backend', PATH)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)


class DriverError(Exception):
    pass


class FakeDriver:
    NVMLError = DriverError
    NVML_TEMPERATURE_GPU = 0

    def __init__(self):
        self.calls = []

    def nvmlInit(self): self.calls.append('init')
    def nvmlShutdown(self): self.calls.append('shutdown')
    def nvmlDeviceGetCount(self): return 1
    def nvmlDeviceGetHandleByIndex(self, index): return index
    def nvmlDeviceGetMemoryInfo(self, handle): return types.SimpleNamespace(total=4096 * 1024**2, used=1024**3, free=3072 * 1024**2)
    def nvmlDeviceGetUtilizationRates(self, handle):
        self.calls.append('utilization')
        return types.SimpleNamespace(gpu=12, memory=7)
    def nvmlDeviceGetName(self, handle): return b'Fixture GPU'
    def nvmlDeviceGetFanSpeed(self, handle):
        self.calls.append('fan')
        return 30
    def nvmlDeviceGetPowerManagementLimitConstraints(self, handle): return (50_000, 200_000)
    def nvmlDeviceGetPowerManagementLimit(self, handle): return 150_000
    def nvmlDeviceGetTemperature(self, handle, sensor): return 40
    def nvmlDeviceGetPowerUsage(self, handle): return 25_000


class GPUBackendTests(unittest.TestCase):
    def test_snapshot_is_one_read_only_pass_and_preserves_fields(self):
        driver = FakeDriver()
        result = backend.snapshot(driver)
        self.assertEqual(result[0]['name'], 'Fixture GPU')
        self.assertEqual(result[0]['memory_pct'], 25)
        self.assertEqual(result[0]['power_limit'], 150)
        self.assertEqual(result[0]['power_min'], 50)
        self.assertEqual(result[0]['power_max'], 200)
        self.assertEqual(driver.calls, ['init', 'utilization', 'fan', 'shutdown'])
        json.dumps(result, allow_nan=False)

    def test_driver_error_still_closes_nvml(self):
        driver = FakeDriver()
        with patch.object(driver, 'nvmlDeviceGetMemoryInfo', side_effect=DriverError('fixture')):
            with self.assertRaises(DriverError): backend.snapshot(driver)
        self.assertEqual(driver.calls[-1], 'shutdown')

    def test_unsupported_controls_keep_readings_available(self):
        driver = FakeDriver()
        with patch.object(driver, 'nvmlDeviceGetFanSpeed', side_effect=DriverError), patch.object(driver, 'nvmlDeviceGetPowerManagementLimitConstraints', side_effect=DriverError):
            result = backend.snapshot(driver)[0]
        self.assertEqual(result['temperature'], 40)
        self.assertIsNone(result['power_limit'])

    def test_second_session_cannot_enter_driver_until_lock_released(self):
        with tempfile.TemporaryDirectory() as root:
            fd = backend.acquire_lock(root)
            try:
                self.assertTrue(os.get_inheritable(fd))
                with self.assertRaises(backend.ProbeError): backend.acquire_lock(root)
                self.assertEqual((Path(root) / 'bizon-gpu-monitor.lock').stat().st_mode & 0o777, 0o600)
            finally: os.close(fd)
            fd = backend.acquire_lock(root); os.close(fd)

    def test_real_child_retains_lock_after_supervisor_descriptor_closes(self):
        with tempfile.TemporaryDirectory() as root:
            fd = backend.acquire_lock(root)
            child = subprocess.Popen([sys.executable, '-I', '-c', 'import sys; print("ready", flush=True); sys.stdin.read()'], pass_fds=(fd,), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(child.stdout.readline().strip(), 'ready')
                os.close(fd); fd = None
                with self.assertRaises(backend.ProbeError): backend.acquire_lock(root)
            finally:
                if fd is not None: os.close(fd)
                child.communicate(timeout=5)
            fd = backend.acquire_lock(root); os.close(fd)

    def test_runtime_symlinks_and_unsafe_lock_files_are_refused(self):
        for scenario in ['symlink', 'hardlink', 'permissions']:
            with tempfile.TemporaryDirectory() as root:
                lock = Path(root) / 'bizon-gpu-monitor.lock'
                target = Path(root) / 'target'; target.write_text('preserve')
                if scenario == 'symlink': lock.symlink_to(target)
                elif scenario == 'hardlink': os.link(target, lock)
                else: lock.write_text(''); lock.chmod(0o666)
                with self.assertRaises((OSError, backend.ProbeError)): backend.acquire_lock(root)
                self.assertEqual(target.read_text(), 'preserve')

    def test_default_execs_bounded_watchdog_with_inherited_worker_lock(self):
        with tempfile.TemporaryDirectory() as root:
            fd = backend.acquire_lock(root)
            observed = []
            def execute(program, argv):
                observed.append((program, argv, os.get_inheritable(fd)))
                raise OSError('fixture: exec refused')
            with patch.object(backend, 'acquire_lock', return_value=fd), patch.object(backend.os, 'execv', side_effect=execute), contextlib.redirect_stderr(io.StringIO()):
                result = backend.main([])
            self.assertEqual(result, 1)
            self.assertEqual(len(observed), 1)
            program, argv, inherited = observed[0]
            self.assertEqual(program, '/usr/bin/timeout')
            self.assertEqual(argv[1:4], ['--signal=TERM', '--kill-after=1s', '4s'])
            self.assertIn('-I', argv)
            self.assertEqual(argv[-2:], ['--probe', str(fd)])
            self.assertTrue(inherited)
            with self.assertRaises(OSError): os.fstat(fd)

    def test_worker_requires_real_inherited_descriptor_before_loading_nvml(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(backend.main(['--probe', '999999']), 1)
            self.assertEqual(backend.main(['--probe', 'invalid']), 1)
        self.assertNotIn('pynvml', sys.modules)


if __name__ == '__main__':
    unittest.main()
