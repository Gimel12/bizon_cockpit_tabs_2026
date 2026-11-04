"""Bounded standard-library adapters. Only native provider tool calls are accepted.

Protocol references:
https://docs.ollama.com/capabilities/tool-calling
https://docs.ollama.com/api/chat
https://platform.claude.com/docs/en/build-with-claude/streaming
"""
import ipaddress
import json
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

MAX_RESPONSE = 4 * 1024 * 1024
MAX_LINE = 512 * 1024


class ProviderError(RuntimeError):
    pass


class Cancelled(ProviderError):
    pass


class Cancellation:
    def __init__(self):
        self.event = threading.Event()
        self.response = None
        self.lock = threading.Lock()

    def check(self):
        if self.event.is_set():
            raise Cancelled('Request stopped')

    def attach(self, response):
        with self.lock:
            self.response = response
        if self.event.is_set():
            self.cancel()
        self.check()

    def cancel(self):
        self.event.set()
        with self.lock:
            response = self.response
        if response is not None:
            # Interrupt a blocked streamed read without waiting for its timeout.
            try:
                response.fp.raw._sock.shutdown(socket.SHUT_RDWR)
            except (AttributeError, OSError):
                pass

    def detach(self):
        with self.lock:
            self.response = None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError('Provider redirects are not allowed')


def local_url(value):
    if not isinstance(value, str) or len(value) > 512:
        raise ProviderError('Invalid local server address')
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ProviderError('Use an HTTP or HTTPS loopback server without credentials or query parameters')
    host = parsed.hostname
    if host == 'localhost':
        host = '127.0.0.1'
    try:
        address = ipaddress.ip_address(host or '')
        port = parsed.port
    except ValueError as exc:
        raise ProviderError('Local server must use a loopback address') from exc
    if not address.is_loopback or not port or parsed.path.rstrip('/') not in ('', '/v1'):
        raise ProviderError('Local server must use a loopback address, explicit port, and optional /v1 path')
    hostname = '[' + host + ']' if address.version == 6 else host
    return f'{parsed.scheme}://{hostname}:{port}' + parsed.path.rstrip('/')


def endpoint(base, path):
    base = local_url(base)
    if base.endswith('/v1'):
        base = base[:-3]
    return base + path


def request(url, body=None, key=None, cancel=None, timeout=5):
    headers = {'Accept': 'application/json', 'User-Agent': 'BIZON-Agent/1'}
    if body is not None:
        headers['Content-Type'] = 'application/json'
    if key:
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers)
    if cancel:
        cancel.check()
    try:
        response = opener.open(req, timeout=timeout)
    except urllib.error.HTTPError as exc:
        # Provider response bodies may echo credentials or private request data.
        raise ProviderError(f'Provider returned HTTP {exc.code}') from None
    except (urllib.error.URLError, OSError, ValueError):
        if cancel:
            cancel.check()
        raise ProviderError('Cannot reach provider; check its address and running service') from None
    if cancel:
        try:
            cancel.attach(response)
        except Cancelled:
            response.close()
            raise
    return response


def read_json(response):
    try:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ProviderError('Provider response exceeds the size limit')
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ProviderError('Provider returned an invalid JSON object')
        return value
    except (ValueError, UnicodeError):
        raise ProviderError('Provider returned invalid JSON') from None


def models(provider, base, key='', cancel=None):
    if provider == 'claude':
        if not key:
            return []
        url = 'https://api.anthropic.com/v1/models?limit=100'
    elif provider in ('ollama', 'openai_local'):
        url = endpoint(base, '/api/tags' if provider == 'ollama' else '/v1/models')
    else:
        raise ProviderError('Unknown AI provider')
    token = cancel or Cancellation()
    timed_out = threading.Event()
    def expire():
        timed_out.set()
        token.cancel()
    timer = threading.Timer(5, expire)
    timer.daemon = True
    timer.start()
    try:
        with request(url, key=key if provider == 'claude' else None, cancel=token, timeout=5) as response:
            data = read_json(response)
        token.check()
    except (OSError, ProviderError):
        if timed_out.is_set():
            raise ProviderError('Model discovery timed out') from None
        raise
    finally:
        timer.cancel()
        token.detach()
    result = []
    items = data.get('models' if provider == 'ollama' else 'data', [])
    if not isinstance(items, list):
        raise ProviderError('Provider returned an invalid model list')
    for model in items[:100]:
        if not isinstance(model, dict):
            raise ProviderError('Provider returned an invalid model entry')
        name = model.get('name') if provider == 'ollama' else model.get('id')
        if isinstance(name, str) and 0 < len(name) <= 200:
            result.append({'id': name, 'name': str(model.get('display_name') or name)[:200]})
    return result


def lines(response, cancel):
    total = 0
    start = time.monotonic()
    while True:
        cancel.check()
        if time.monotonic() - start > 180:
            raise ProviderError('Provider response timed out')
        line = response.readline(MAX_LINE + 1)
        if not line:
            break
        total += len(line)
        if len(line) > MAX_LINE or total > MAX_RESPONSE:
            raise ProviderError('Provider response exceeds the size limit')
        try:
            yield line.decode('utf-8').rstrip('\r\n')
        except UnicodeError:
            raise ProviderError('Provider returned invalid text') from None


def sse(response, cancel):
    data = []
    for line in lines(response, cancel):
        if not line:
            if data:
                value = '\n'.join(data)
                data = []
                if value == '[DONE]':
                    return
                try:
                    yield json.loads(value)
                except ValueError:
                    raise ProviderError('Provider returned invalid streaming data') from None
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    if data:
        value = '\n'.join(data)
        if value != '[DONE]':
            try:
                yield json.loads(value)
            except ValueError:
                raise ProviderError('Provider returned incomplete streaming data') from None


def native_messages(provider, messages):
    result = []
    for msg in messages:
        role, content = msg['role'], msg.get('content', '')
        images = msg.get('images', [])
        calls = msg.get('tool_calls', [])
        if provider == 'claude':
            if role == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': msg['tool_call_id'], 'content': content,
                         'is_error': bool(msg.get('is_error'))}
                if result and result[-1]['role'] == 'user' and isinstance(result[-1]['content'], list) and result[-1]['content'][0].get('type') == 'tool_result':
                    result[-1]['content'].append(block)
                else:
                    result.append({'role': 'user', 'content': [block]})
            else:
                blocks = [{'type': 'text', 'text': content}] if content else []
                blocks += [{'type': 'image', 'source': {'type': 'base64', 'media_type': x['media_type'], 'data': x['data']}} for x in images]
                blocks += [{'type': 'tool_use', 'id': x['id'], 'name': x['name'], 'input': x['arguments']} for x in calls]
                result.append({'role': role, 'content': blocks or [{'type': 'text', 'text': '(no text)'}]})
        elif provider == 'ollama':
            item = {'role': role, 'content': content}
            if images:
                item['images'] = [x['data'] for x in images]
            if calls:
                item['tool_calls'] = [{'function': {'name': x['name'], 'arguments': x['arguments']}} for x in calls]
            if role == 'tool':
                item['tool_name'] = msg['name']
            result.append(item)
        else:
            item = {'role': role, 'content': content}
            if images:
                item['content'] = [{'type': 'text', 'text': content}] + [{'type': 'image_url', 'image_url': {'url': 'data:' + x['media_type'] + ';base64,' + x['data']}} for x in images]
            if calls:
                item['tool_calls'] = [{'id': x['id'], 'type': 'function', 'function': {'name': x['name'], 'arguments': json.dumps(x['arguments'])}} for x in calls]
            if role == 'tool':
                item['tool_call_id'] = msg['tool_call_id']
            result.append(item)
    return result


def chat(provider, base, key, model, system, messages, tools, cancel, on_text):
    native = native_messages(provider, messages)
    if provider == 'claude':
        url = 'https://api.anthropic.com/v1/messages'
        body = {'model': model, 'max_tokens': 4096, 'system': system, 'messages': native, 'stream': True}
        if tools:
            body['tools'] = [{'name': x['name'], 'description': x['description'], 'input_schema': x['parameters']} for x in tools]
    else:
        url = endpoint(base, '/api/chat' if provider == 'ollama' else '/v1/chat/completions')
        body = {'model': model, 'messages': [{'role': 'system', 'content': system}] + native, 'stream': True}
        if provider == 'ollama':
            body.update({'think': False, 'options': {'num_ctx': 32768, 'num_predict': 4096}, 'keep_alive': '5m'})
        else:
            body['max_tokens'] = 4096
        if tools:
            body['tools'] = [{'type': 'function', 'function': x} for x in tools]
    text, calls, finished = [], {}, False
    try:
        with request(url, body, key if provider == 'claude' else None, cancel, timeout=30) as response:
            if provider == 'ollama':
                events = (json.loads(line) for line in lines(response, cancel) if line)
            else:
                events = sse(response, cancel)
            for event in events:
                cancel.check()
                if not isinstance(event, dict):
                    raise ProviderError('Provider returned an invalid streaming event')
                if event.get('error') or event.get('type') == 'error':
                    raise ProviderError('Provider reported an inference error')
                delta = ''
                if provider == 'ollama':
                    message = event.get('message', {})
                    delta = message.get('content', '')
                    for call in message.get('tool_calls', []):
                        fn = call.get('function', {})
                        index = fn.get('index', len(calls))
                        if index in calls:
                            # Some servers repeat the final complete native tool call.
                            if calls[index]['name'] == fn.get('name') and calls[index]['arguments'] == fn.get('arguments'):
                                continue
                            raise ProviderError('Provider repeated an inconsistent tool call')
                        calls[index] = {'id': 'call_' + uuid.uuid4().hex, 'name': fn.get('name'), 'arguments': fn.get('arguments', {})}
                    finished = bool(event.get('done'))
                elif provider == 'claude':
                    kind = event.get('type')
                    index = event.get('index', 0)
                    if kind == 'content_block_start' and event.get('content_block', {}).get('type') == 'tool_use':
                        block = event['content_block']
                        calls[index] = {'id': block['id'], 'name': block['name'], 'arguments': block.get('input', {}), '_partial': ''}
                    elif kind == 'content_block_delta':
                        change = event.get('delta', {})
                        if change.get('type') == 'text_delta':
                            delta = change.get('text', '')
                        elif change.get('type') == 'input_json_delta' and index in calls:
                            calls[index]['_partial'] += change.get('partial_json', '')
                    finished = kind == 'message_stop'
                else:
                    choices = event.get('choices', [])
                    if not choices:
                        continue
                    choice = choices[0]
                    change = choice.get('delta', {})
                    delta = change.get('content') or ''
                    for call in change.get('tool_calls', []):
                        index = call.get('index', 0)
                        item = calls.setdefault(index, {'id': '', 'name': '', '_partial': ''})
                        item['id'] += call.get('id', '')
                        item['name'] += call.get('function', {}).get('name', '')
                        item['_partial'] += call.get('function', {}).get('arguments', '')
                    finished = choice.get('finish_reason') is not None
                if delta:
                    if not isinstance(delta, str):
                        raise ProviderError('Provider returned invalid answer text')
                    text.append(delta)
                    if sum(map(len, text)) > 128 * 1024:
                        raise ProviderError('Answer exceeds the size limit')
                    on_text(delta)
                if len(calls) > 16:
                    raise ProviderError('Provider requested too many tools')
                if finished:
                    break
        cancel.check()
        if not finished:
            raise ProviderError('Provider stream ended before the response completed')
        result = []
        for call in calls.values():
            partial = call.pop('_partial', '')
            if partial:
                call['arguments'] = json.loads(partial)
            call.setdefault('arguments', {})
            call['id'] = call.get('id') or 'call_' + uuid.uuid4().hex
            if not isinstance(call['arguments'], dict):
                raise ProviderError('Tool arguments must be an object')
            result.append(call)
        return {'content': ''.join(text), 'tool_calls': result}
    except (ValueError, KeyError, TypeError, AttributeError, OSError):
        cancel.check()
        raise ProviderError('Provider returned an invalid or interrupted response') from None
    finally:
        cancel.detach()
