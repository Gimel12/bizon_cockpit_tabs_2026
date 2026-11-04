"""One read-only GPU snapshot; no daemon, sampling loop or persistent metric log."""
import fcntl
import json
import os
from pathlib import Path
import stat
import sys


class ProbeError(Exception):
    pass


def acquire_lock(runtime=None):
    """All sessions for this Unix account share one lock, held by the real NVML worker."""
    uid = os.getuid()
    runtime = Path('/run/user') / str(uid) if runtime is None else Path(runtime)
    directory = os.open(runtime, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(directory)
        if info.st_uid != uid or info.st_mode & 0o022:
            raise ProbeError('The private GPU runtime directory is unavailable.')
        fd = os.open('bizon-gpu-monitor.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=directory)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != uid or info.st_mode & 0o077 or info.st_nlink != 1:
                raise ProbeError('The GPU monitor lock is not private.')
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise ProbeError('Another GPU snapshot is still running. Readings are temporarily unavailable.') from error
            os.set_inheritable(fd, True)
            return fd
        except BaseException:
            os.close(fd)
            raise
    finally:
        os.close(directory)


def snapshot(nvml):
    nvml.nvmlInit()
    try:
        count = nvml.nvmlDeviceGetCount()
        if not 0 <= count <= 64:
            raise ProbeError('The GPU driver returned an invalid device count.')
        gpus = []
        for index in range(count):
            handle = nvml.nvmlDeviceGetHandleByIndex(index)
            memory = nvml.nvmlDeviceGetMemoryInfo(handle)
            utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
            name = nvml.nvmlDeviceGetName(handle)
            name = name.decode('utf-8', 'replace') if isinstance(name, bytes) else str(name)
            try:
                fan = nvml.nvmlDeviceGetFanSpeed(handle)
            except nvml.NVMLError:
                fan = 0
            try:
                low, high = nvml.nvmlDeviceGetPowerManagementLimitConstraints(handle)
                power_limits = {'power_limit': nvml.nvmlDeviceGetPowerManagementLimit(handle) // 1000,
                                'power_min': low // 1000, 'power_max': high // 1000}
            except nvml.NVMLError:
                power_limits = {'power_limit': None, 'power_min': None, 'power_max': None}
            gpus.append({
                'id': index, 'name': name, **power_limits,
                'temperature': nvml.nvmlDeviceGetTemperature(handle, nvml.NVML_TEMPERATURE_GPU),
                'gpu_utilization': utilization.gpu, 'memory_utilization': utilization.memory,
                'power_usage': nvml.nvmlDeviceGetPowerUsage(handle) // 1000,
                'memory_total': memory.total // 1024 // 1024,
                'memory_used': memory.used // 1024 // 1024,
                'memory_free': memory.free // 1024 // 1024,
                'memory_pct': round(memory.used / memory.total * 100, 2) if memory.total else 0,
                'fan': fan,
            })
        return gpus
    finally:
        nvml.nvmlShutdown()


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    try:
        if not args:
            fd = acquire_lock()
            try:
                # Exec, rather than capture_output/communicate: no unbounded wait after SIGKILL.
                # The inherited lock stays held even if the worker is stuck inside the driver.
                os.execv('/usr/bin/timeout', [
                    '/usr/bin/timeout', '--signal=TERM', '--kill-after=1s', '4s',
                    sys.executable, '-I', str(Path(__file__).resolve()), '--probe', str(fd),
                ])
            finally:
                os.close(fd)
        elif len(args) == 2 and args[0] == '--probe':
            fd = int(args[1])
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ProbeError('A private inherited GPU lock is required.')
            # The real worker owns the same open-file description as its watchdog.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            import pynvml
            print(json.dumps(snapshot(pynvml), allow_nan=False))
        else:
            raise ProbeError('Invalid GPU snapshot request.')
        return 0
    except (ProbeError, OSError, ValueError, ImportError) as error:
        print(str(error) if isinstance(error, ProbeError) else 'GPU readings are unavailable.', file=sys.stderr)
        return 1
    except Exception:
        # Driver errors go to stderr and a failed exit, never mixed with successful JSON.
        print('The GPU driver could not provide a snapshot.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
