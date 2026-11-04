"""Linux-only watchdog fixtures: harmless sleeping snapshots, never GPU faults."""
import importlib.util
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import unittest

BACKEND = Path(__file__).resolve().parents[1] / 'cockpit_gpu/py_backend/gpu_backend.py'
spec = importlib.util.spec_from_file_location('gpu_backend_watchdog_test', BACKEND)
backend = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backend)
WORKER = '''
import importlib.util, os, signal, sys, time, types
spec = importlib.util.spec_from_file_location('gpu_backend_test_worker', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.modules['pynvml'] = types.ModuleType('pynvml')
def harmless_snapshot(unused):
    if sys.argv[2] == 'ignore-term':
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print('READY', flush=True)
    time.sleep(60)
    return []
m.snapshot = harmless_snapshot
sys.exit(m.main(['--probe', sys.argv[3]]))
'''


@unittest.skipUnless(sys.platform == 'linux' and Path('/usr/bin/timeout').exists(), 'Requires Linux and GNU timeout')
class GPUWatchdogLinuxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        version = subprocess.run(['/usr/bin/timeout', '--version'], capture_output=True, text=True, timeout=3)
        if version.returncode or 'GNU coreutils' not in version.stdout:
            raise unittest.SkipTest('Requires GNU coreutils timeout')

    def exercise_watchdog(self, mode, expected_code, minimum_seconds):
        with tempfile.TemporaryDirectory(prefix='bizon-gpu-watchdog-fixture-') as runtime:
            descriptor = backend.acquire_lock(runtime)
            started = time.monotonic()
            worker = None
            try:
                worker = subprocess.Popen([
                    '/usr/bin/timeout', '--signal=TERM', '--kill-after=1s', '4s',
                    sys.executable, '-I', '-c', WORKER, str(BACKEND), mode, str(descriptor),
                ], pass_fds=(descriptor,), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
                # Only the actual watchdog/worker retain the shared open-file description.
                os.close(descriptor); descriptor = None
                with selectors.DefaultSelector() as selector:
                    selector.register(worker.stdout, selectors.EVENT_READ)
                    self.assertTrue(selector.select(timeout=3), 'The harmless probe did not become ready')
                self.assertEqual(worker.stdout.readline().strip(), 'READY')
                with self.assertRaises(backend.ProbeError):
                    backend.acquire_lock(runtime)
                stdout, stderr = worker.communicate(timeout=7)
                elapsed = time.monotonic() - started
                self.assertEqual(worker.returncode, expected_code, stderr)
                self.assertGreaterEqual(elapsed, minimum_seconds)
                self.assertLess(elapsed, 7.5)
                self.assertEqual(stdout, '')
                self.assertEqual(stderr, '')
                # No stuck lock survives a normally interruptible simulated driver call.
                descriptor = backend.acquire_lock(runtime)
            finally:
                if descriptor is not None:
                    os.close(descriptor)
                if worker is not None:
                    # Also covers assertion failures before the regular timeout fires.
                    try:
                        os.killpg(worker.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    worker.communicate(timeout=3)

    def test_stalled_probe_terminates_at_deadline_and_releases_worker_lock(self):
        self.exercise_watchdog('normal-term', 124, 3.7)

    def test_term_ignoring_probe_is_killed_after_grace_and_releases_worker_lock(self):
        self.exercise_watchdog('ignore-term', -signal.SIGKILL, 4.7)


if __name__ == '__main__':
    unittest.main()
