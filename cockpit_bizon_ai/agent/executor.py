#!/usr/bin/python3 -I
"""Per-run Cockpit executor. Account/admin authority, not a security sandbox."""
import codecs
import json
import os
from pathlib import Path
import pwd
import queue
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid

MAX_LINE = 512 * 1024
MAX_OUTPUT = 128 * 1024
MAX_FILE = 256 * 1024
ID = re.compile(r'[A-Za-z0-9_-]{1,128}')


class ProtocolError(Exception):
    pass


def exact_keys(value, required, optional=()):
    if not isinstance(value, dict) or not set(required) <= set(value) or set(value) - set(required) - set(optional):
        raise ProtocolError('Invalid request fields')


def memory_limit():
    try:
        physical = os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
    except (ValueError, OSError):
        physical = 8 * 1024**3
    return max(512 * 1024**2, min(8 * 1024**3, physical // 4))


class Executor:
    def __init__(self):
        self.inbox = queue.Queue(maxsize=8)
        self.cancel = threading.Event()
        self.reason = 'Run cancelled'
        self.nonce = None
        self.run_id = None
        self.expires = float('inf')
        self.ids = set()
        self.counter = 0
        self.instance = uuid.uuid4().hex[:12]
        self.active = None
        self.active_cleaned = False
        self.unit = None
        self.user_manager = os.geteuid() != 0
        runtime = Path('/run/user') / str(os.geteuid())
        self.systemd = bool(shutil.which('systemd-run') and Path('/run/systemd/system').exists()
                            and (not self.user_manager or (runtime / 'bus').exists()))

    def redact(self, value):
        if isinstance(value, str):
            return value.replace(self.nonce, '[redacted]') if self.nonce else value
        if isinstance(value, dict):
            return {k: self.redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v) for v in value]
        return value

    def emit(self, event):
        try:
            sys.stdout.write(json.dumps(self.redact(event), ensure_ascii=True) + '\n')
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            self.stop('Control channel closed')

    def stop(self, reason='Run cancelled'):
        self.reason = reason
        self.cancel.set()

    def reader(self):
        # A daemon blocked in BufferedReader.readline can retain its stream lock
        # during interpreter shutdown and abort Python. Raw fd reads have no
        # buffered-stream lock; SIGTERM can exit even while stdin remains open.
        buffered = b''
        try:
            while True:
                chunk = os.read(sys.stdin.fileno(), 65536)
                if not chunk:
                    self.stop('Control channel closed')
                    return
                buffered += chunk
                while b'\n' in buffered:
                    line, buffered = buffered.split(b'\n', 1)
                    if len(line) + 1 > MAX_LINE:
                        self.stop('Request exceeds size limit')
                        return
                    try:
                        self.inbox.put_nowait(line)
                    except queue.Full:
                        self.stop('Too many pending requests')
                        return
                if len(buffered) >= MAX_LINE:
                    self.stop('Request exceeds size limit')
                    return
        except OSError:
            self.stop('Control channel closed')

    def decode(self, line):
        try:
            value = json.loads(line)
        except (ValueError, UnicodeError):
            raise ProtocolError('Invalid JSON request') from None
        return value

    def init(self, value):
        exact_keys(value, ('type', 'run_id', 'nonce', 'ttl_seconds', 'mode'))
        if value['type'] != 'init':
            raise ProtocolError('Initialize this run before executing tools')
        try:
            run_id = str(uuid.UUID(value['run_id']))
        except (ValueError, TypeError, AttributeError):
            raise ProtocolError('Invalid run identifier') from None
        if value['run_id'] != run_id:
            raise ProtocolError('Invalid run identifier')
        nonce = value['nonce']
        if not isinstance(nonce, str) or not re.fullmatch('[a-f0-9]{64}', nonce):
            raise ProtocolError('Invalid run authorization')
        ttl = value['ttl_seconds']
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise ProtocolError('Run lifetime must be 1–3600 seconds')
        mode = value['mode']
        if mode not in ('user', 'administrator') or (mode == 'administrator') != (os.geteuid() == 0):
            raise ProtocolError('Requested authority does not match this Cockpit channel')
        self.run_id, self.nonce = run_id, nonce
        self.expires = time.monotonic() + ttl
        self.emit({'type': 'ready', 'run_id': run_id})

    def request(self, value):
        exact_keys(value, ('type', 'run_id', 'nonce', 'id', 'name', 'arguments'))
        if value['type'] != 'execute' or value['run_id'] != self.run_id or value['nonce'] != self.nonce:
            raise ProtocolError('Request does not belong to this authorized run')
        ident = value['id']
        if not isinstance(ident, str) or not ID.fullmatch(ident) or ident == self.nonce:
            raise ProtocolError('Invalid tool request identifier')
        if ident in self.ids:
            raise ProtocolError('Tool request identifier was already used')
        self.ids.add(ident)
        if len(self.ids) > 64:
            raise ProtocolError('Run tool limit reached')
        return value

    def check(self):
        if time.monotonic() >= self.expires:
            self.stop('Run authorization expired')
        return not self.cancel.is_set()

    def pending_while_running(self):
        while not self.inbox.empty():
            value = self.request(self.decode(self.inbox.get_nowait()))
            self.emit({'type': 'tool_done', 'id': value['id'], 'result': {
                'output': '', 'exit_code': 1, 'error': 'Another tool is running; wait for its result.'}})

    def environment(self):
        user = pwd.getpwuid(os.geteuid())
        env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
               'HOME': user.pw_dir, 'USER': user.pw_name, 'LOGNAME': user.pw_name,
               'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'SHELL': '/bin/bash'}
        if self.user_manager:
            env['XDG_RUNTIME_DIR'] = '/run/user/' + str(os.geteuid())
            env['DBUS_SESSION_BUS_ADDRESS'] = 'unix:path=' + env['XDG_RUNTIME_DIR'] + '/bus'
        return env

    def terminate(self):
        proc = self.active
        if not proc or self.active_cleaned:
            return
        self.active_cleaned = True
        if self.unit:
            args = ['systemctl'] + (['--user'] if self.user_manager else [])
            try:
                subprocess.run(args + ['stop', self.unit], env=self.environment(),
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=4)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    subprocess.run(args + ['kill', '--signal=KILL', '--kill-whom=all', self.unit],
                                   env=self.environment(), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=2)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        if proc:
            # Also clean up descendants that outlive a completed shell.
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass

    def command(self, ident, args):
        exact_keys(args, ('command',), ('cwd', 'timeout_seconds'))
        command = args['command']
        if not isinstance(command, str) or not command.strip() or len(command.encode()) > 16384 or '\0' in command:
            raise ValueError('Command must contain 1–16384 bytes of shell text')
        timeout = args.get('timeout_seconds', 120)
        if type(timeout) not in (int, float) or not 1 <= timeout <= 600:
            raise ValueError('Command timeout must be 1–600 seconds')
        cwd = self.path(args.get('cwd', os.getcwd()))
        if not cwd.is_dir():
            raise ValueError('Working directory does not exist')
        env = self.environment()
        # The systemd user manager may carry a broader login environment than
        # this process. Clear it again inside the unit before running the shell.
        argv = ['/usr/bin/env', '-i'] + [k + '=' + v for k, v in env.items()] + ['/bin/bash', '-c', command]
        self.counter += 1
        if self.systemd:
            self.unit = 'bizon-agent-' + self.run_id.replace('-', '') + '-' + self.instance + '-' + str(self.counter) + '.service'
            argv = ['systemd-run'] + (['--user'] if self.user_manager else []) + [
                '--quiet', '--wait', '--pipe', '--collect', '--service-type=exec', '--unit=' + self.unit,
                '--working-directory=' + str(cwd), '--property=KillMode=control-group',
                '--property=TimeoutStopSec=2', '--property=RuntimeMaxSec=' + str(timeout + 1),
                '--property=MemoryMax=' + str(memory_limit()), '--property=MemorySwapMax=0',
                '--property=TasksMax=128', '--property=LimitCORE=0', '--property=LimitNOFILE=1024',
                '--property=UMask=0077'] + ['--setenv=' + k + '=' + v for k, v in env.items()] + ['--'] + argv
        else:
            # No Python preexec_fn: the stdin reader is already a running thread.
            # The fixed wrapper receives model-authored shell text only as $2.
            # Virtual-memory limits are best effort on non-Linux test hosts.
            argv = ['/bin/bash', '-c',
                    'ulimit -c 0; ulimit -n 1024; ulimit -v "$1" 2>/dev/null || :; '
                    'exec /bin/bash -c "$2"',
                    'bizon-resource-limits', str(memory_limit() // 1024), command]
        self.active = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       start_new_session=True)
        self.active_cleaned = False
        started = time.monotonic()
        deadline = min(self.expires, started + timeout)
        decoder = codecs.getincrementaldecoder('utf-8')('replace')
        collected = bytearray()
        stream_pending = ''
        error = None
        exit_code = None
        selector = selectors.DefaultSelector()
        selector.register(self.active.stdout, selectors.EVENT_READ)
        try:
            while selector.get_map():
                self.pending_while_running()
                if not self.check():
                    error, exit_code = self.reason, 130
                    break
                if time.monotonic() >= deadline:
                    error, exit_code = 'Command exceeded its time limit', 124
                    break
                for key, _ in selector.select(timeout=0.05):
                    chunk = os.read(key.fileobj.fileno(), 16384)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        break
                    remaining = MAX_OUTPUT - len(collected)
                    collected.extend(chunk[:remaining])
                    stream_pending += decoder.decode(chunk[:remaining])
                    # Hold a nonce-sized tail so split chunks cannot leak it.
                    stream_pending = self.redact(stream_pending)
                    if len(stream_pending) > 64:
                        self.emit({'type': 'output', 'id': ident, 'text': stream_pending[:-64]})
                        stream_pending = stream_pending[-64:]
                    if len(chunk) > remaining:
                        error, exit_code = 'Command output exceeded 128 KiB', 125
                        break
                if error:
                    break
                # A background child may retain stdout after the shell exits.
                if self.active.poll() is not None and selector.get_map():
                    self.terminate()
            while exit_code is None:
                self.pending_while_running()
                if not self.check():
                    error, exit_code = self.reason, 130
                elif time.monotonic() >= deadline:
                    error, exit_code = 'Command exceeded its time limit', 124
                else:
                    exit_code = self.active.poll()
                    if exit_code is None:
                        time.sleep(0.05)
            stream_pending += decoder.decode(b'', final=True)
            if stream_pending:
                self.emit({'type': 'output', 'id': ident, 'text': stream_pending})
        finally:
            selector.close()
            self.terminate()
            self.active.stdout.close()
            self.active = None
            self.unit = None
        result = {'output': collected.decode('utf-8', errors='replace'), 'exit_code': exit_code,
                  'duration_seconds': round(time.monotonic() - started, 3)}
        if error:
            result['error'] = error
        elif exit_code:
            result['error'] = 'Command exited with status ' + str(exit_code)
        return result

    def path(self, value):
        if not isinstance(value, str) or not value or len(value) > 4096 or '\0' in value:
            raise ValueError('Invalid file path')
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError('Use an absolute file path')
        try:
            return path.resolve()
        except RuntimeError:
            raise ValueError('File path cannot be resolved') from None

    def read_file(self, args):
        exact_keys(args, ('path',), ('limit',))
        path = self.path(args['path'])
        limit = args.get('limit', 65536)
        if type(limit) is not int or not 1 <= limit <= MAX_FILE:
            raise ValueError('Read limit must be 1–262144 bytes')
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0))
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise ValueError('read_file accepts regular files only')
            content = os.read(fd, limit + 1)
        finally:
            os.close(fd)
        return {'output': content[:limit].decode('utf-8', errors='replace'), 'exit_code': 0,
                'truncated': len(content) > limit}

    def write_file(self, args):
        exact_keys(args, ('path', 'content'), ('append',))
        path = self.path(args['path'])
        content = args['content']
        append = args.get('append', False)
        if not isinstance(content, str) or len(content.encode()) > MAX_FILE or type(append) is not bool:
            raise ValueError('Write content must be at most 262144 bytes; append must be boolean')
        if path.exists() and not path.is_file():
            raise ValueError('write_file accepts regular files only')
        data = content.encode('utf-8')
        if append:
            fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0), 0o600)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError('write_file accepts regular files only')
                with os.fdopen(fd, 'ab', closefd=False) as target:
                    target.write(data)
                    target.flush()
                    os.fsync(fd)
            finally:
                os.close(fd)
        else:
            previous = path.stat() if path.exists() else None
            fd, temporary = tempfile.mkstemp(prefix='.bizon-agent-', dir=path.parent)
            try:
                with os.fdopen(fd, 'wb') as target:
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                    if previous:
                        # Preserve owner/mode but never introduce setuid bits.
                        if os.geteuid() == 0:
                            os.fchown(target.fileno(), previous.st_uid, previous.st_gid)
                        os.fchmod(target.fileno(), stat.S_IMODE(previous.st_mode) & 0o777)
                os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {'output': 'Wrote ' + str(len(data)) + ' bytes to ' + str(path), 'exit_code': 0}

    def execute(self, value):
        ident = value['id']
        self.emit({'type': 'tool_start', 'id': ident})
        try:
            if value['name'] == 'run_command':
                result = self.command(ident, value['arguments'])
            elif value['name'] == 'read_file':
                result = self.read_file(value['arguments'])
            elif value['name'] == 'write_file':
                result = self.write_file(value['arguments'])
            else:
                raise ValueError('Unknown executor tool')
        except (ValueError, OSError) as exc:
            result = {'output': '', 'exit_code': 1, 'error': str(exc)[:500]}
        self.emit({'type': 'tool_done', 'id': ident, 'result': result})

    def run(self):
        threading.Thread(target=self.reader, daemon=True).start()
        init_deadline = time.monotonic() + 30
        try:
            while self.check():
                if self.run_id is None and time.monotonic() > init_deadline:
                    raise ProtocolError('Run initialization timed out')
                try:
                    line = self.inbox.get(timeout=0.05)
                except queue.Empty:
                    continue
                value = self.decode(line)
                if self.run_id is None:
                    self.init(value)
                else:
                    self.execute(self.request(value))
        except ProtocolError as exc:
            self.stop(str(exc))
        finally:
            self.terminate()
            if self.reason != 'Control channel closed':
                self.emit({'type': 'error', 'message': self.reason})


def main():
    if len(sys.argv) != 1:
        print(json.dumps({'type': 'error', 'message': 'Executor does not accept command-line arguments'}), flush=True)
        return 1
    runner = Executor()
    signal.signal(signal.SIGTERM, lambda *_: runner.stop())
    signal.signal(signal.SIGINT, lambda *_: runner.stop())
    signal.signal(signal.SIGHUP, lambda *_: runner.stop('Control channel closed'))
    runner.run()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
