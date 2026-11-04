#!/usr/bin/python3 -I
"""Bounded CPU/RAM burn-in with independent workload and RAS coverage results."""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import re
import selectors
import signal
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path('/var/lib/bizon-cpu-ram-test')
RUNS = ROOT / 'runs'
UNIT = 'bizon-cpu-ram-test.service'
LOAD = 'bizon-cpu-ram-load.service'
SCRIPT = '/usr/local/libexec/bizon-cpu-ram-test.py'
TABLES = {'mc_event': 'err_count', 'mce_record': None, 'extlog_event': 'error_count', 'aer_event': None}
RUN_RE = re.compile(r'[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\Z')
TERMINAL = {'completed', 'stopped', 'failed', 'incomplete'}
STOP = False
HARDWARE_RE = re.compile(r'\[Hardware Error\]|Machine check events logged|Machine Check Exception|'
                         r'EDAC.*(?:[0-9]+\s+(?:CE|UE)|(?:corrected|uncorrected|fatal)\s+error)|'
                         r'mce:.*(?:error|failure)|Memory failure:|hardware memory corruption|'
                         r'Out of memory:|oom-kill:|Killed process .*stress-ng|critical temperature', re.I)


def command(argv, timeout=12):
    # Bound external-tool output even when the machine is flooding its error log.
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        streams = {proc.stdout: bytearray(), proc.stderr: bytearray()}
        try:
            with selectors.DefaultSelector() as selector:
                for stream in streams:
                    selector.register(stream, selectors.EVENT_READ)
                deadline = time.monotonic() + timeout
                while selector.get_map():
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(argv, timeout)
                    for key, _ in selector.select(min(0.2, max(0, deadline - time.monotonic()))):
                        data = key.fileobj.read1(65536)
                        if not data:
                            selector.unregister(key.fileobj)
                        else:
                            streams[key.fileobj].extend(data)
                            if len(streams[key.fileobj]) > 2 * 1024**2:
                                raise RuntimeError(Path(argv[0]).name + ' exceeded the safe output limit; monitoring is incomplete')
                proc.wait(timeout=max(0.1, deadline - time.monotonic()))
            return subprocess.CompletedProcess(argv, proc.returncode,
                streams[proc.stdout].decode('utf-8', 'replace'), streams[proc.stderr].decode('utf-8', 'replace'))
        except BaseException:
            proc.kill()
            proc.wait()
            raise


def checked(argv, timeout=12):
    result = command(argv, timeout)
    if result.returncode:
        raise RuntimeError(f'{Path(argv[0]).name}: {(result.stderr or result.stdout).strip()[:500]}')
    return result.stdout


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds')


def duration(value):
    match = re.fullmatch(r'(\d+)(s|m|h|d)?', value)
    if not match:
        raise argparse.ArgumentTypeError('Use a duration such as 30m, 1h or 8h.')
    seconds = int(match[1]) * {'s': 1, 'm': 60, 'h': 3600, 'd': 86400, None: 1}[match[2]]
    if not 10 <= seconds <= 604800:
        raise argparse.ArgumentTypeError('Duration must be between 10 seconds and 7 days.')
    return seconds


def secure_dir(path):
    if not path.exists():
        secure_dir(path.parent)
        path.mkdir(mode=0o700)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise RuntimeError(f'Unsafe directory: {path}')


def write_json(path, value):
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


@contextlib.contextmanager
def lock(path, shared=False):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Unsafe lock file')
        try:
            fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another test or image-sealing operation is already running.') from None
        yield
    finally:
        os.close(fd)


def memory_info():
    return {m[1]: int(m[2]) * 1024 for line in Path('/proc/meminfo').read_text().splitlines()
            if (m := re.match(r'(\w+):\s+(\d+) kB', line))}


def memory_plan(total, available, percent=85, override_mib=None):
    reserve = max(2 * 1024**3, total // 10)
    safe = min(total * percent // 100, available - reserve)
    amount = override_mib * 1024**2 if override_mib is not None else safe
    amount = amount // (1024**2) * 1024**2
    if amount < 256 * 1024**2 or amount > safe:
        raise ValueError('Not enough free RAM for this allocation plus the OS reserve. Close workloads or use a smaller --memory-mib value (minimum 256).')
    return {'bytes': amount, 'reserve_bytes': reserve, 'limit_bytes': amount + min(1024**3, reserve // 2)}


def unit_info(name):
    text = checked(['/usr/bin/systemctl', 'show', name, '--no-pager',
                    '--property=ActiveState,SubState,MainPID,InvocationID,Result,ExecMainCode,ExecMainStatus,MemoryCurrent,MemoryPeak,CPUUsageNSec'])
    return dict(line.split('=', 1) for line in text.splitlines() if '=' in line)


def stop_unit(unit, timeout=40):
    if unit_info(unit).get('ActiveState') in {'active', 'activating', 'deactivating'}:
        result = command(['/usr/bin/systemctl', 'stop', unit], timeout=timeout)
        if result.returncode and unit_info(unit).get('ActiveState') not in {'inactive', 'failed'}:
            raise RuntimeError('Could not stop ' + unit + ': ' + result.stderr.strip())


def ras_snapshot():
    snap = {'issues': [], 'tables': {}, 'edac': {}, 'trace': {}, 'loss': {}}
    snap['boot_id'] = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    service = unit_info('rasdaemon.service')
    snap['recorder'] = service.get('InvocationID')
    if service.get('ActiveState') != 'active':
        snap['issues'].append('RAS recorder is not active')
    database = Path('/var/lib/rasdaemon/ras-mc_event.db')
    try:
        info = database.stat()
        snap['database'] = [info.st_dev, info.st_ino]
        with contextlib.closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=2)) as db:
            for table, counter in TABLES.items():
                exists = db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?', (table,)).fetchone()
                if not exists:
                    continue
                cols = {row[1] for row in db.execute(f'PRAGMA table_info({table})')}
                if 'id' not in cols or (counter and counter not in cols):
                    snap['issues'].append(f'Unsupported RAS schema: {table}')
                    continue
                count, last = db.execute(f'SELECT COUNT(*), COALESCE(MAX(id),0) FROM {table}').fetchone()
                snap['tables'][table] = {'rows': count, 'last': last}
    except (OSError, sqlite3.Error) as error:
        snap['issues'].append(f'RAS database unavailable: {error}')
    for directory in sorted(Path('/sys/devices/system/edac/mc').glob('mc[0-9]*')):
        for kind in ('ce_count', 'ue_count'):
            path = directory / kind
            try:
                snap['edac'][str(path)] = int(path.read_text())
            except (OSError, ValueError):
                snap['issues'].append(f'Cannot read EDAC counter {path.name}')
    trace = next((Path(p) for p in ('/sys/kernel/tracing/instances/rasdaemon',
                                   '/sys/kernel/debug/tracing/instances/rasdaemon') if Path(p).is_dir()), None)
    if trace is None:
        snap['issues'].append('RAS trace instance unavailable')
    else:
        try:
            if (trace / 'tracing_on').read_text().strip() != '1':
                snap['issues'].append('RAS tracing is off')
            for event in ('mce/mce_record', 'ras/mc_event', 'ras/extlog_mem_event', 'ras/aer_event'):
                path = trace / 'events' / event / 'enable'
                snap['trace'][event] = path.exists() and path.read_text().strip() == '1'
            for path in trace.glob('per_cpu/cpu*/stats'):
                for line in path.read_text().splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        if key.strip() in {'overrun', 'commit overrun', 'dropped events'}:
                            snap['loss'][path.parent.name + ':' + key.strip()] = int(value.strip())
        except (OSError, ValueError) as error:
            snap['issues'].append(f'RAS trace health unavailable: {error}')
    snap['mce_available'] = bool(snap['trace'].get('mce/mce_record') and 'mce_record' in snap['tables'])
    snap['ecc_available'] = bool(snap['edac'] and snap['trace'].get('ras/mc_event') and 'mc_event' in snap['tables'])
    if not snap['mce_available']:
        snap['issues'].append('MCE recording is unavailable on this hardware/kernel')
    if not snap['loss']:
        snap['issues'].append('RAS trace loss counters unavailable')
    return snap


def snapshot_gaps(before, after):
    gaps = list(after['issues'])
    for key, label in (('boot_id', 'Host rebooted'), ('recorder', 'RAS recorder restarted'),
                       ('database', 'RAS database replaced')):
        if before.get(key) != after.get(key):
            gaps.append(label)
    for key in ('tables', 'edac', 'trace', 'loss'):
        if before[key].keys() != after[key].keys():
            gaps.append(f'RAS {key} sources changed')
    for table in before['tables'].keys() & after['tables'].keys():
        if any(after['tables'][table][k] < before['tables'][table][k] for k in ('rows', 'last')):
            gaps.append(f'RAS database counters reset: {table}')
    for key, value in before['edac'].items():
        if key in after['edac'] and after['edac'][key] < value:
            gaps.append('EDAC counter reset: ' + key)
    for key, value in before['loss'].items():
        if key in after['loss'] and after['loss'][key] != value:
            gaps.append('RAS events lost or trace counters reset: ' + key)
    for key, enabled in before['trace'].items():
        if enabled and not after['trace'].get(key):
            gaps.append('RAS trace event disabled: ' + key)
    return gaps


def ras_new_events(before, after):
    counts = {}
    details = []
    if before.get('database') != after.get('database'):
        return counts, details
    with contextlib.closing(sqlite3.connect('file:/var/lib/rasdaemon/ras-mc_event.db?mode=ro', uri=True, timeout=2)) as db:
        db.row_factory = sqlite3.Row
        for table, counter in TABLES.items():
            if table not in before['tables'] or table not in after['tables']:
                continue
            lo, hi = before['tables'][table]['last'], after['tables'][table]['last']
            if hi <= lo:
                continue
            expr = f'SUM(CASE WHEN {counter}>0 THEN {counter} ELSE 1 END)' if counter else 'COUNT(*)'
            counts[table] = db.execute(f'SELECT COALESCE({expr},0) FROM {table} WHERE id>? AND id<=?', (lo, hi)).fetchone()[0]
            for row in db.execute(f'SELECT * FROM {table} WHERE id>? AND id<=? ORDER BY id LIMIT 100', (lo, hi)):
                details.append({'source': table, 'record': {k: (v.hex() if isinstance(v, bytes) else v) for k, v in dict(row).items()}})
    return counts, details


def journal_start():
    out = checked(['/usr/bin/journalctl', '-k', '-n', '1', '-o', 'json', '--no-pager'])
    records = [json.loads(x) for x in out.splitlines() if x.startswith('{')]
    if not records or '__CURSOR' not in records[-1]:
        raise RuntimeError('No kernel journal cursor available')
    return records[-1]['__CURSOR']


def journal_poll(cursor):
    out = checked(['/usr/bin/journalctl', '-k', '--after-cursor=' + cursor, '-o', 'json', '--no-pager'])
    events = []
    for line in out.splitlines():
        record = json.loads(line)
        cursor = record['__CURSOR']
        message = record.get('MESSAGE', '')
        if isinstance(message, str) and HARDWARE_RE.search(message):
            events.append({'time_us': record.get('__REALTIME_TIMESTAMP'), 'message': message})
    return cursor, events


def temperatures():
    values = {}
    for device in Path('/sys/class/hwmon').glob('hwmon*'):
        try:
            name = (device / 'name').read_text().strip()
            if name not in {'coretemp', 'k10temp', 'zenpower', 'acpitz'}:
                continue
            for path in device.glob('temp*_input'):
                labelpath = path.with_name(path.name.replace('_input', '_label'))
                label = labelpath.read_text().strip() if labelpath.exists() else path.stem
                value = int(path.read_text()) / 1000
                if 0 < value < 150:
                    values[device.name + ':' + name + ':' + label] = value
        except (OSError, ValueError):
            continue
    return values


def cpu_ticks():
    nums = [int(x) for x in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    return sum(nums), nums[3] + nums[4]


def workload_argv(config):
    # Exactly one VM worker: Ubuntu 24.04's --vm-bytes is PER worker.
    return ['/usr/bin/stress-ng', '--cpu', str(config['cpu_workers']), '--cpu-method', 'all',
            '--cpu-load', '100', '--vm', '1', '--vm-bytes', str(config['memory']['bytes']),
            '--vm-keep', '--vm-method', 'all', '--verify', '--abort', '--oomable',
            '--timeout', str(config['duration_seconds']) + 's', '--metrics-brief']


def launch_load(config, directory):
    argv = ['/usr/bin/systemd-run', '--quiet', '--unit=' + LOAD, '--property=Type=exec',
            '--property=RemainAfterExit=yes', '--property=User=nobody', '--property=Group=nogroup',
            '--property=NoNewPrivileges=yes', '--property=PrivateTmp=yes', '--property=WorkingDirectory=/tmp',
            '--property=ProtectSystem=strict', '--property=ProtectHome=yes',
            '--property=MemoryAccounting=yes', '--property=CPUAccounting=yes',
            '--property=MemoryMax=' + str(config['memory']['limit_bytes']), '--property=MemorySwapMax=0',
            '--property=OOMPolicy=stop', '--property=TasksMax=4096', '--property=TimeoutStopSec=10',
            '--property=RuntimeMaxSec=' + str(config['duration_seconds'] + 30),
            '--property=BindsTo=' + UNIT, '--property=After=' + UNIT,
            '--property=StandardOutput=append:' + str(directory / 'stress-ng.log'),
            '--property=StandardError=inherit', '--'] + workload_argv(config)
    checked(argv)


def determine_result(state, exit_status, finished):
    if state['new_events'] or any(state['edac_delta'].values()) or state['kernel_events'] or state['safety_stop']:
        return 'failed', 'ERRORS DETECTED — inspect the report before approving this hardware'
    if state['stop_requested']:
        return 'stopped', 'STOPPED — test did not complete'
    if exit_status == 2:
        return 'failed', 'WORKLOAD FAILED — a stressor reported failure; review stress-ng.log'
    if exit_status != 0 or not finished:
        return 'incomplete', 'INCOMPLETE — workload failed, was interrupted or could not finish'
    if state['monitoring_gaps']:
        return 'incomplete', 'INCOMPLETE — hardware monitoring had gaps'
    if not state['coverage']['mce_available']:
        return 'incomplete', 'INCOMPLETE — MCE recording was unavailable'
    if not state['coverage']['ecc_available']:
        return 'completed', 'COMPLETED — no new errors observed; ECC verification unavailable'
    return 'completed', 'COMPLETED — no new errors observed in available CPU/RAM monitoring'


def workload_summary(log, cpu_workers):
    """Require both requested stressors to report success, not merely exit zero."""
    match = re.search(r'passed:\s+\d+:\s+cpu\s+\((\d+)\)\s+vm\s+\((\d+)\)', log)
    failed = re.search(r'failed:\s+(\d+)', log)
    skipped = re.search(r'skipped:\s+(\d+)', log)
    return bool(match and int(match[1]) == cpu_workers and int(match[2]) == 1
                and failed and int(failed[1]) == 0 and skipped and int(skipped[1]) == 0
                and re.search(r'\bsuccessful run completed\b', log))


def report_text(state, directory):
    config = state['config']
    lines = ['BIZON CPU + RAM test', '=' * 60, state.get('result', state['phase'].upper()), '',
             'Run: ' + state['run_id'], 'Started: ' + state['started_at'],
             'CPU: ' + state['cpu_model'],
             f"CPU workers: {config['cpu_workers']} | RAM target: {config['memory']['bytes']/1024**3:.2f} GiB",
             f"Elapsed: {state['elapsed_seconds']:.0f}s / {config['duration_seconds']}s",
             'Workload exit code: ' + str(state.get('exit_status', 'running')),
             'MCE recording: ' + ('available' if state['coverage']['mce_available'] else 'UNAVAILABLE'),
             'ECC/EDAC reporting: ' + ('available' if state['coverage']['ecc_available'] else 'UNAVAILABLE — no supported memory-controller counters'),
             'Firmware memory correction: ' + state.get('memory_correction', 'not reported'),
             'New RAS events: ' + json.dumps(state['new_events']),
             'New EDAC counter increments (may overlap RAS): ' + json.dumps(state['edac_delta']),
             f"Kernel hardware/runtime events: {len(state['kernel_events'])}",
             'Peak observed CPU temperature: ' + (str(state.get('peak_temperature_c')) + ' °C' if state.get('peak_temperature_c') is not None else 'unavailable'),
             'Load service result: ' + state.get('load_result', 'running'), '', 'Monitoring gaps:']
    lines.extend('- ' + x for x in state['monitoring_gaps'])
    if not state['monitoring_gaps']:
        lines.append('None detected')
    if state['safety_stop']:
        lines.extend(['', 'Safety stop: ' + state['safety_stop']])
    lines.extend(['', 'Kernel events:'] + [x['message'] for x in state['kernel_events']])
    lines.extend(['', 'RAS event detail (up to 200 records):', json.dumps(state['event_details'], indent=2), '',
                  'Limitations: this is an online workload test, not a guarantee of fault-free hardware.',
                  'The OS reserve, firmware-reserved RAM and unsupported ECC telemetry are not verified.',
                  'Existing RAS records were preserved; only events after the baseline are counted.',
                  'Review stress-ng.log and ras-before/after.txt for details.', 'Report directory: ' + str(directory)])
    return '\n'.join(lines) + '\n'


def ras_text():
    chunks = []
    for flag in ('--status', '--error-count', '--summary'):
        try:
            result = command(['/usr/sbin/ras-mc-ctl', flag])
            chunks.append(flag + f' (exit {result.returncode})\n' + result.stdout + result.stderr)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
            chunks.append(str(error))
    return '\n'.join(chunks)


def monitor(run_id):
    global STOP
    directory = RUNS / run_id
    secure_dir(directory)
    state = json.loads((directory / 'summary.json').read_text())
    config = state['config']
    started = time.monotonic()
    previous = baseline = None
    cursor = None
    exit_status, finished = None, False
    def stop_handler(*_):
        global STOP
        STOP = True
    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    with lock('/run/lock/bizon-image-seal.lock', shared=True), lock('/run/lock/bizon-cpu-ram-test.lock'):
        try:
            baseline = previous = ras_snapshot()
            state['coverage'] = {k: baseline[k] for k in ('mce_available', 'ecc_available')}
            state['monitoring_gaps'].extend(baseline['issues'])
            state['baseline'] = baseline
            (directory / 'ras-before.txt').write_text(ras_text())
            try:
                cursor = journal_start()
            except Exception as error:
                state['monitoring_gaps'].append('Kernel journal unavailable: ' + str(error))
            # Recheck free RAM immediately before launch; another workload may have started.
            mem = memory_info()
            memory_plan(mem['MemTotal'], mem['MemAvailable'], config['memory_percent'], config['memory']['bytes'] // 1024**2)
            launch_load(config, directory)
            state['phase'] = 'running'
            ticks = cpu_ticks()
            last_poll = 0.0
            while True:
                now = time.monotonic()
                state['elapsed_seconds'] = now - started
                state['stop_requested'] = STOP
                info = unit_info(LOAD)
                ended = info.get('SubState') in {'exited', 'dead', 'failed'} or info.get('ActiveState') in {'failed', 'inactive'}
                if STOP or state['elapsed_seconds'] > config['duration_seconds'] + 45:
                    stop_unit(LOAD, timeout=20)
                    info = unit_info(LOAD)
                    ended = True
                    if not STOP:
                        state['monitoring_gaps'].append('Workload exceeded its time limit')
                if now - last_poll >= 5 or ended:
                    # Small drain delay lets rasdaemon commit the final trace records.
                    if ended:
                        time.sleep(2)
                    current = ras_snapshot()
                    state['monitoring_gaps'].extend(snapshot_gaps(previous, current))
                    try:
                        counts, details = ras_new_events(previous, current)
                        for key, value in counts.items():
                            state['new_events'][key] = state['new_events'].get(key, 0) + value
                        state['event_details'] = (state['event_details'] + details)[:200]
                    except (OSError, sqlite3.Error) as error:
                        state['monitoring_gaps'].append('Could not read new RAS events: ' + str(error))
                    for key, value in current['edac'].items():
                        if key in baseline['edac']:
                            state['edac_delta'][key] = max(state['edac_delta'].get(key, 0), value - baseline['edac'][key])
                    state['last_snapshot'] = current
                    previous = current
                    if cursor:
                        try:
                            cursor, events = journal_poll(cursor)
                            state['kernel_events'] = (state['kernel_events'] + events)[:200]
                            with (directory / 'kernel-events.log').open('a') as stream:
                                for event in events:
                                    stream.write(json.dumps(event) + '\n')
                        except Exception as error:
                            state['monitoring_gaps'].append('Kernel journal read failed: ' + str(error))
                            stop_unit(LOAD, timeout=20)
                    temps = temperatures()
                    peak = max(temps.values(), default=None)
                    if peak is not None:
                        state['peak_temperature_c'] = max(peak, state.get('peak_temperature_c') or 0)
                    mem = memory_info()
                    new_ticks = cpu_ticks()
                    delta = new_ticks[0] - ticks[0]
                    cpu = 100 * (1 - (new_ticks[1] - ticks[1]) / delta) if delta else 0
                    ticks = new_ticks
                    state['live'] = {'time': utc(), 'cpu_percent': round(cpu, 1),
                                     'available_gib': round(mem['MemAvailable'] / 1024**3, 2),
                                     'temperatures_c': temps, 'load_memory_bytes': info.get('MemoryCurrent'),
                                     'load_peak_bytes': info.get('MemoryPeak')}
                    with (directory / 'telemetry.jsonl').open('a') as stream:
                        stream.write(json.dumps(state['live']) + '\n')
                    if peak is not None and peak >= config['max_temperature']:
                        state['safety_stop'] = f"CPU temperature reached {peak:g} °C (limit {config['max_temperature']} °C)"
                    if mem['MemAvailable'] < max(512 * 1024**2, mem['MemTotal'] // 50):
                        state['safety_stop'] = 'The OS is running short of available RAM'
                    state['monitoring_gaps'] = list(dict.fromkeys(state['monitoring_gaps']))
                    write_json(directory / 'summary.json', state)
                    last_poll = now
                if ended:
                    exit_status = int(info.get('ExecMainStatus') or -1)
                    finished = (info.get('Result') == 'success' and info.get('ExecMainCode') == '1'
                                and state['elapsed_seconds'] >= config['duration_seconds'] - 1)
                    state['load_result'] = info.get('Result', 'unknown')
                    break
                if state['safety_stop'] or state['new_events'] or any(state['edac_delta'].values()) or state['kernel_events']:
                    stop_unit(LOAD, timeout=20)
                    # Next poll captures final workload status and remaining events.
                time.sleep(1)
        except Exception as error:
            state['monitoring_gaps'].append('Test interrupted: ' + str(error))
        finally:
            try:
                stop_unit(LOAD, timeout=20)
            except Exception as error:
                state['monitoring_gaps'].append('Workload cleanup failed: ' + str(error))
            state['elapsed_seconds'] = time.monotonic() - started
            state['stop_requested'] = STOP
            state['exit_status'] = exit_status
            state['finished_at'] = utc()
            if exit_status == 0 and finished and not STOP:
                try:
                    with (directory / 'stress-ng.log').open() as stream:
                        output = stream.read(2 * 1024**2)
                    if not workload_summary(output, config['cpu_workers']):
                        state['monitoring_gaps'].append('stress-ng did not confirm all requested CPU and RAM workers passed')
                except (OSError, UnicodeError) as error:
                    state['monitoring_gaps'].append('stress-ng result log unavailable: ' + str(error))
            state['phase'], state['result'] = determine_result(state, exit_status, finished)
            state['monitoring_gaps'] = list(dict.fromkeys(state['monitoring_gaps']))
            (directory / 'ras-after.txt').write_text(ras_text())
            write_json(directory / 'summary.json', state)
            (directory / 'report.txt').write_text(report_text(state, directory))
            print(state['result'], flush=True)


def latest():
    pointer = ROOT / 'latest.json'
    if not pointer.exists():
        raise RuntimeError('No CPU + RAM test has been run yet.')
    run_id = json.loads(pointer.read_text())['run_id']
    if not RUN_RE.fullmatch(run_id):
        raise RuntimeError('Invalid report identifier')
    directory = RUNS / run_id
    return directory, json.loads((directory / 'summary.json').read_text())


def show(state, directory):
    live = state.get('live', {})
    print(f"\nBIZON CPU + RAM | {state['phase'].upper()} | {state['elapsed_seconds']:.0f}/{state['config']['duration_seconds']} seconds", flush=True)
    print(f"CPU: {live.get('cpu_percent', '—')}% | RAM available: {live.get('available_gib', '—')} GiB | Peak CPU: {state.get('peak_temperature_c', '—')} °C", flush=True)
    print('New RAS events: ' + str(sum(state['new_events'].values())) +
          f" | EDAC increments: {sum(state['edac_delta'].values())} | Kernel events: {len(state['kernel_events'])} | Monitoring gaps: {len(state['monitoring_gaps'])}", flush=True)
    print('ECC: ' + ('available' if state['coverage']['ecc_available'] else 'not available on this board/kernel'), flush=True)
    if state['phase'] in TERMINAL:
        print(state['result'] + '\nReport: ' + str(directory / 'report.txt'), flush=True)


def stop_test():
    # The load unit can disappear as soon as BindsTo stops it. Stopping an
    # already-finished test is successful; serialize with new start requests.
    with lock('/run/lock/bizon-cpu-ram-control.lock'):
        for unit in (UNIT, LOAD):
            stop_unit(unit)


def watch(follow, stop_on_interrupt=False):
    try:
        while True:
            directory, state = latest()
            if state['phase'] not in TERMINAL:
                info = unit_info(UNIT)
                if info.get('ActiveState') not in {'active', 'activating', 'deactivating'}:
                    state = dict(state, phase='incomplete', result='INCOMPLETE — the monitor stopped or the host rebooted; this run did not finish')
                    show(state, directory)
                    return 2
            show(state, directory)
            if state['phase'] in TERMINAL or not follow:
                if state['phase'] in TERMINAL:
                    return 0 if state['phase'] == 'completed' else 2
                return 0
            time.sleep(5)
    except KeyboardInterrupt:
        if stop_on_interrupt:
            stop_test()
            return watch(False)
        print('\nMonitor closed. The test continues; use cpu-ram-stop to stop it.')
        return 0


def start(args):
    secure_dir(RUNS)
    with lock('/run/lock/bizon-cpu-ram-control.lock'), lock('/run/lock/bizon-image-seal.lock', shared=True), lock('/run/lock/bizon-cpu-ram-test.lock'):
        if unit_info(UNIT).get('ActiveState') in {'active', 'activating', 'deactivating'}:
            raise RuntimeError('A CPU + RAM test is already running; use cpu-ram-status.')
        if unit_info(LOAD).get('SubState') not in {'dead', 'failed', 'exited'}:
            raise RuntimeError('A CPU + RAM workload is already running.')
        for unit in (LOAD, UNIT):
            command(['/usr/bin/systemctl', 'stop', unit])
            command(['/usr/bin/systemctl', 'reset-failed', unit])
        checked(['/usr/bin/systemctl', 'start', 'rasdaemon.service'])
        mem = memory_info()
        plan = memory_plan(mem['MemTotal'], mem['MemAvailable'], args.memory_percent, args.memory_mib)
        run_id = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex[:8]
        directory = RUNS / run_id
        directory.mkdir(mode=0o700)
        config = {'duration_seconds': args.duration, 'cpu_workers': args.cpu_workers,
                  'memory_percent': args.memory_percent, 'memory': plan, 'max_temperature': args.max_temperature}
        cpu_model = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), 'unknown')
        correction = 'not reported'
        try:
            data = command(['/usr/sbin/dmidecode', '-t', '16']).stdout
            correction = next((line.split(':', 1)[1].strip() for line in data.splitlines() if 'Error Correction Type:' in line), correction)
        except (OSError, subprocess.TimeoutExpired):
            pass
        state = {'run_id': run_id, 'phase': 'queued', 'factory_test': args.factory_test,
                 'started_at': utc(), 'elapsed_seconds': 0, 'config': config, 'cpu_model': cpu_model,
                 'memory_total_bytes': mem['MemTotal'], 'memory_correction': correction,
                 'coverage': {'mce_available': False, 'ecc_available': False}, 'monitoring_gaps': [],
                 'new_events': {}, 'edac_delta': {}, 'kernel_events': [], 'event_details': [],
                 'safety_stop': '', 'stop_requested': False}
        write_json(directory / 'summary.json', state)
        write_json(ROOT / 'latest.json', {'run_id': run_id})
        for name in ('stress-ng.log', 'kernel-events.log', 'telemetry.jsonl'):
            (directory / name).touch(mode=0o600)
        argv = ['/usr/bin/systemd-run', '--quiet', '--unit=' + UNIT, '--property=Type=exec',
                '--property=OOMScoreAdjust=-500', '--property=TimeoutStopSec=35',
                '--property=RuntimeMaxSec=' + str(args.duration + 120),
                '--', '/usr/bin/python3', '-I', SCRIPT, '_worker', run_id]
        # Pass the start lock to systemd only after the launch call returns; the worker
        # retries briefly so concurrent starts cannot take the interval before it runs.
        checked(argv)
    print(f"Started {args.cpu_workers} CPU workers + {plan['bytes']/1024**3:.2f} GiB RAM for {args.duration}s.")
    print('The test reserves RAM for Ubuntu. Closing SSH does not stop the test.')
    if args.detach:
        print('Use cpu-ram-status, cpu-ram-stop and cpu-ram-report.')
        return 0
    print('Ctrl+C here stops this test. Reports are saved automatically.')
    time.sleep(1)
    return watch(True, stop_on_interrupt=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    run = sub.add_parser('start', help='Start a CPU + RAM test (default: one hour, all CPU threads)')
    run.add_argument('--duration', type=duration, default=3600)
    run.add_argument('--memory-percent', type=int, choices=range(10, 91), default=85, metavar='10..90')
    run.add_argument('--memory-mib', type=int, help='Smaller explicit RAM allocation for a quick check; minimum256 MiB')
    run.add_argument('--cpu-workers', type=int, default=os.cpu_count() or 1)
    run.add_argument('--max-temperature', type=int, choices=range(70, 106), default=95, metavar='70..105', help='Stop at this CPU temperature in °C (default95)')
    run.add_argument('--detach', action='store_true')
    run.add_argument('--factory-test', action='store_true', help='Mark factory-validation records as removable during final image sealing')
    status = sub.add_parser('status', help='Display the latest run')
    status.add_argument('--watch', action='store_true')
    sub.add_parser('stop', help='Stop this tool’s test and save a partial report')
    sub.add_parser('report', help='Print the latest saved report')
    worker = sub.add_parser('_worker', help=argparse.SUPPRESS)
    worker.add_argument('run_id')
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error('Use sudo (the cpu-ram-* aliases include it).')
    os.umask(0o077)
    if args.action == 'start':
        if not 1 <= args.cpu_workers <= (os.cpu_count() or 1):
            parser.error('--cpu-workers must be between1 and the number of logical CPUs')
        return start(args)
    if args.action == 'status':
        return watch(args.watch)
    if args.action == 'stop':
        stop_test()
        if (ROOT / 'latest.json').exists():
            watch(False)
        else:
            print('No CPU + RAM test is active.')
        return 0
    if args.action == 'report':
        directory, state = latest()
        if state['phase'] not in TERMINAL:
            return watch(False)
        print((directory / 'report.txt').read_text())
        return 0 if state['phase'] == 'completed' else 2
    if not RUN_RE.fullmatch(args.run_id):
        parser.error('Invalid run identifier')
    # The starter holds the lock through systemd-run, so wait for that short handoff.
    for attempt in range(20):
        try:
            monitor(args.run_id)
            return 0
        except RuntimeError as error:
            if 'already running' not in str(error) or attempt == 19:
                raise
            time.sleep(0.1)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as error:
        print('BIZON CPU + RAM: ' + str(error), file=sys.stderr)
        sys.exit(2)
