#!/usr/bin/env python3
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backend', Path(__file__).parent / 'cockpit_bizon_ai/agent/backend.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
p = b.provider


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = b.Profile(Path(self.temp.name) / 'profile')
        self.events = []
        self.cancel = p.Cancellation()
        self.request = {'message': 'Check the GPU', 'provider': 'ollama', 'model': 'test-model', 'mode': 'agent'}

    def run_chat(self, responses, results=None, request=None):
        calls = []
        responses = iter(responses)
        def adapter(*args):
            calls.append(args[:5] + (copy.deepcopy(args[5]),) + args[6:])
            response = next(responses)
            args[-1](response.get('content', ''))
            return response
        with patch.object(p, 'chat', side_effect=adapter):
            b.chat(self.profile, request or self.request, self.events.append,
                   results or (lambda request_id, cancel: {'output': 'ok', 'exit_code': 0}), self.cancel)
        return calls

    def tool(self, name='run_command', args=None, identifier='native1'):
        return {'content': '', 'tool_calls': [{'id': identifier, 'name': name, 'arguments': args or {'command': 'nvidia-smi'}}]}

    def test_multiple_native_tool_turns_feed_results_and_persist_only_plain_history(self):
        seen = []
        def result(request_id, cancel):
            seen.append(request_id)
            return {'output': 'temperature 32 C', 'exit_code': 0}
        calls = self.run_chat([self.tool(), self.tool('read_file', {'path': '/etc/os-release'}, 'native2'), {'content': 'GPU healthy', 'tool_calls': []}], result)
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0], seen[1])
        self.assertEqual(calls[1][5][-1]['role'], 'tool')
        self.assertIn('temperature 32 C', calls[1][5][-1]['content'])
        history = self.profile.conversation(self.events[0]['id'])
        self.assertEqual([x['role'] for x in history['messages']], ['user', 'assistant'])
        self.assertEqual(len(history['messages'][-1]['actions']), 2)
        self.assertNotIn('tool_calls', json.dumps(history))
        self.assertEqual(self.events[-1]['type'], 'done')

    def test_failed_tool_result_is_returned_to_model_and_recorded(self):
        calls = self.run_chat([self.tool(), {'content': 'Command failed', 'tool_calls': []}],
                              lambda *_: {'output': '', 'exit_code': 1, 'error': 'not available'})
        self.assertTrue(calls[-1][5][-1]['is_error'])
        self.assertIn('not available', calls[-1][5][-1]['content'])

    def test_chat_mode_never_dispatches_unsolicited_tool_calls(self):
        req = dict(self.request, mode='chat')
        with self.assertRaisesRegex(b.Error, 'control is off'):
            self.run_chat([self.tool()], request=req)
        self.assertFalse(any(x['type'] == 'tool_request' for x in self.events))

    def test_unknown_tools_and_invalid_arguments_never_reach_executor(self):
        invalid = [self.tool('remove_disk'), self.tool(args={'command': 'x', 'sudoPassword': 'bad'}),
                   self.tool(args={'command': 'x', 'timeout_seconds': 999}), self.tool('read_file', {'path': '../x', 'limit': True})]
        for response in invalid:
            self.events.clear()
            with self.subTest(response=response), self.assertRaises(b.Error):
                self.run_chat([response])
            self.assertFalse(any(x['type'] == 'tool_request' for x in self.events))

    def test_limits_total_tool_calls_without_executing_extra(self):
        responses = [self.tool(identifier='id' + str(x)) for x in range(17)]
        with self.assertRaisesRegex(b.Error, 'limit reached'):
            self.run_chat(responses)
        self.assertEqual(sum(x['type'] == 'tool_request' for x in self.events), 16)

    def test_provider_switch_restores_only_user_assistant_messages_without_orphan_tools(self):
        self.run_chat([self.tool(), {'content': 'Done', 'tool_calls': []}])
        cid = self.events[0]['id']
        req = dict(self.request, provider='openai_local', conversation_id=cid, message='Explain that')
        calls = self.run_chat([{'content': 'Explanation', 'tool_calls': []}], request=req)
        self.assertTrue(all(x['role'] in ('user', 'assistant') for x in calls[0][5]))
        self.assertFalse(any('tool_calls' in x for x in calls[0][5]))

    def test_api_key_never_returned_or_sent_in_model_context_and_outputs_are_redacted(self):
        key = 'sk-ant-test-' + 'z' * 80
        self.profile.write(self.profile.root / 'config.json', dict(b.DEFAULTS, claude_api_key=key))
        with patch.object(p, 'models', return_value=[]):
            output = b.action(self.profile, 'status', {})
        self.assertNotIn(key, json.dumps(output))
        self.assertTrue(output['claude_configured'])
        req = dict(self.request, message='Please protect ' + key)
        calls = self.run_chat([self.tool(), {'content': 'Echo ' + key, 'tool_calls': []}],
                              lambda *_: {'output': 'password=hidden\n' + key, 'exit_code': 0}, req)
        self.assertNotIn(key, json.dumps(calls[-1][5]))
        self.assertNotIn(key, json.dumps(self.events))
        self.assertNotIn(key, next(self.profile.history.glob('*.json')).read_text())
        self.assertNotIn('hidden', next(self.profile.history.glob('*.json')).read_text())

    def test_profile_files_private_and_lock_blocks_concurrent_planner_and_config_changes(self):
        self.profile.write(self.profile.root / 'config.json', b.DEFAULTS)
        self.assertEqual(stat.S_IMODE(self.profile.root.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.profile.root / 'config.json').stat().st_mode), 0o600)
        with self.profile.lock():
            with self.assertRaisesRegex(b.Error, 'Another BIZON AI'):
                self.run_chat([{'content': 'no', 'tool_calls': []}])
            with self.assertRaises(b.Error):
                b.configure(self.profile, {'provider': 'claude'})

    def test_config_retains_key_when_omitted_and_delete_is_explicit(self):
        with patch.object(p, 'models', return_value=[]):
            b.configure(self.profile, {'claude_api_key': 'private-credential', 'provider': 'claude'})
            b.configure(self.profile, {'provider': 'ollama'})
            self.assertEqual(self.profile.config()['claude_api_key'], 'private-credential')
            b.configure(self.profile, {'delete_claude_key': True})
            self.assertNotIn('claude_api_key', self.profile.config())

    def rename_fixture(self):
        self.run_chat([self.tool(), {'content': 'GPU checked', 'tool_calls': []}])
        conversation_id = self.events[0]['id']
        return conversation_id, self.profile.history / (conversation_id + '.json')

    def test_history_rename_trims_title_preserves_messages_actions_and_private_mode(self):
        conversation_id, path = self.rename_fixture()
        before = json.loads(path.read_text())
        with patch.object(b.time, 'time', return_value=before['updated_at'] + 5):
            result = b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': '  GPU health check  '})
        after = json.loads(path.read_text())
        self.assertEqual(result, {'ok': True, 'id': conversation_id, 'title': 'GPU health check', 'updated_at': before['updated_at'] + 5})
        self.assertEqual(after['messages'], before['messages'])
        self.assertEqual(after['id'], before['id'])
        self.assertEqual(after['title'], 'GPU health check')
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        maximum = 'x' * 80
        self.assertEqual(b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': ' ' + maximum + ' '})['title'], maximum)

    def test_history_rename_invalid_titles_do_not_modify_conversation(self):
        conversation_id, path = self.rename_fixture()
        before = path.read_bytes()
        for title in ('', ' \n\t ', 'x' * 81, 'unsafe\0title', None, 1, []):
            with self.subTest(title=title), self.assertRaises(b.Error):
                b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': title})
            self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(b.Error):
            b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'valid', 'messages': []})
        self.assertEqual(path.read_bytes(), before)

    def test_history_rename_missing_traversal_symlink_and_mismatched_ids_rejected(self):
        conversation_id, path = self.rename_fixture()
        original = path.read_bytes()
        missing = '11111111-1111-4111-8111-111111111111'
        for selected in (missing, '../' + conversation_id, None):
            with self.subTest(selected=selected), self.assertRaises(b.Error):
                b.action(self.profile, 'history_rename', {'id': selected, 'title': 'New name'})
        self.assertFalse((self.profile.history / (missing + '.json')).exists())
        self.assertEqual(path.read_bytes(), original)
        changed = json.loads(original)
        changed['id'] = missing
        path.write_text(json.dumps(changed))
        with self.assertRaisesRegex(b.Error, 'does not match'):
            b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'New name'})
        self.assertFalse((self.profile.history / (missing + '.json')).exists())
        external = self.profile.root / 'external.json'
        external.write_bytes(original)
        path.unlink()
        path.symlink_to(external)
        with self.assertRaises(b.Error):
            b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'New name'})
        self.assertEqual(external.read_bytes(), original)

    def test_history_rename_rejects_a_conversation_owned_by_another_account(self):
        conversation_id, path = self.rename_fixture()
        before = path.read_bytes()
        original_lstat = Path.lstat
        def ownership(candidate, *args, **kwargs):
            info = original_lstat(candidate, *args, **kwargs)
            if candidate == path:
                values = list(info)
                values[4] = os.getuid() + 1
                return os.stat_result(values)
            return info
        with patch.object(Path, 'lstat', ownership), self.assertRaisesRegex(b.Error, 'permissions'):
            b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'New name'})
        self.assertEqual(path.read_bytes(), before)

    def test_history_rename_requires_profile_lock(self):
        conversation_id, path = self.rename_fixture()
        before = path.read_bytes()
        with self.profile.lock(), self.assertRaisesRegex(b.Error, 'Another BIZON AI'):
            b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'New name'})
        self.assertEqual(path.read_bytes(), before)

    def test_history_rename_redacts_current_key_from_title_and_returned_data(self):
        conversation_id, path = self.rename_fixture()
        key = 'private-title-canary'
        self.profile.write(self.profile.root / 'config.json', dict(b.DEFAULTS, claude_api_key=key))
        result = b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'Notes ' + key})
        self.assertEqual(result['title'], 'Notes [redacted]')
        self.assertNotIn(key, json.dumps(result))
        self.assertNotIn(key, path.read_text())
        self.profile.write(self.profile.root / 'config.json', dict(b.DEFAULTS, claude_api_key='canary'))
        result = b.action(self.profile, 'history_rename', {'id': conversation_id, 'title': 'canary ' * 11})
        self.assertLessEqual(len(result['title']), 80)

    def test_symlink_profile_and_history_ids_rejected(self):
        root = Path(self.temp.name) / 'link'
        root.symlink_to(self.profile.root)
        with self.assertRaises(b.Error):
            b.Profile(root)
        for cid in ('../../config', 'notuuid', None):
            with self.assertRaises(b.Error):
                b.action(self.profile, 'history_read', {'id': cid})

    def test_context_bounded_and_attachments_validated(self):
        self.assertEqual(b.context([{'role': 'user', 'content': 'x' * 100}], 10), [])
        for attachment in ([{'name': 'x', 'media_type': 'image/png', 'data': '!'}],
                           [{'name': 'x', 'text': 'x' * 32769}], [{'name': 'x', 'text': 'a'}] * 5):
            with self.assertRaises(b.Error):
                b.attachments({'attachments': attachment}, b.Redactor())

    def test_cancel_in_tool_wait_releases_lock_and_saves_stopped_history(self):
        def stop(*_):
            self.cancel.cancel()
            self.cancel.check()
        with self.assertRaises(p.Cancelled):
            self.run_chat([self.tool()], stop)
        with self.profile.lock():
            pass
        self.assertIn('Request stopped', next(self.profile.history.glob('*.json')).read_text())

    def test_stale_tool_results_rejected_and_eof_cancels(self):
        cancel = p.Cancellation()
        pump = b.InputPump(io.BytesIO(b''), cancel)
        self.assertTrue(cancel.event.wait(1))
        pump = object.__new__(b.InputPump)
        pump.events = queue.Queue()
        pump.events.put({'type': 'tool_result', 'id': 'old', 'result': {}})
        with self.assertRaisesRegex(b.Error, 'stale'):
            pump.result('new', p.Cancellation())

    def test_split_streamed_secrets_not_emitted(self):
        key = 'sk-ant-secret-' + 'x' * 100
        output = []
        stream = b.TextStream(output.append, b.Redactor([key]))
        text = 'Normal words ' * 250 + key + '\nThe end.'
        for start in range(0, len(text), 11):
            stream.feed(text[start:start + 11])
        stream.finish()
        combined = ''.join(x['text'] for x in output)
        self.assertNotIn(key, combined)
        self.assertIn('[redacted]', combined)
        self.assertTrue(combined.endswith('The end.'))

    def test_private_key_stream_and_unterminated_key_never_leak_body(self):
        for footer in ('-----END PRIVATE KEY-----\n', ''):
            events = []
            stream = b.TextStream(events.append, b.Redactor())
            for part in ('Before\n-----BE', 'GIN PRIVATE KEY-----\n', 'TOP_SECRET_KEY_BODY\n', footer):
                stream.feed(part)
            stream.finish()
            self.assertNotIn('TOP_SECRET_KEY_BODY', json.dumps(events))
            self.assertIn('[redacted private key]', json.dumps(events))

    def test_existing_private_data_permissions_are_tightened(self):
        path = self.profile.root / 'config.json'
        path.write_text('{}')
        path.chmod(0o644)
        self.profile.config()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_process_eof_and_sigterm_cancel_blocked_provider_and_release_lock(self):
        source = Path(b.__file__).resolve()
        for mode in ('eof', 'sigterm'):
            code = ("import importlib.util,time,sys; "
                    + "s=importlib.util.spec_from_file_location('backend'," + repr(str(source)) + "); "
                    + "b=importlib.util.module_from_spec(s);s.loader.exec_module(b); "
                    + "profile=b.Profile(" + repr(str(self.profile.root)) + ");b.Profile=lambda:profile; "
                    + "b.provider.chat=lambda *a:time.sleep(30);sys.argv=['backend','chat'];sys.exit(b.main())")
            process = subprocess.Popen([sys.executable, '-I', '-c', code], stdin=subprocess.PIPE,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                process.stdin.write(json.dumps(self.request) + '\n')
                process.stdin.flush()
                first = json.loads(process.stdout.readline())
                self.assertEqual(first['type'], 'conversation')
                self.assertEqual(json.loads(process.stdout.readline())['type'], 'status')
                start = time.monotonic()
                if mode == 'eof':
                    process.stdin.close()
                else:
                    process.terminate()
                process.wait(timeout=3)
                self.assertLess(time.monotonic() - start, 3)
                self.assertEqual(process.returncode, 1)
                self.assertIn('Request stopped', process.stdout.read())
                self.assertEqual(process.stderr.read(), '')
                with self.profile.lock():
                    pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                for stream in (process.stdin, process.stdout, process.stderr):
                    if not stream.closed:
                        stream.close()


class ProviderTests(unittest.TestCase):
    def stream(self, events):
        return io.BytesIO((''.join('data: ' + json.dumps(x) + '\n\n' for x in events)).encode())

    def adapter(self, provider, stream, messages=None):
        text, captured = [], []
        def request(url, body=None, key=None, cancel=None, timeout=5):
            captured.append((url, body, key))
            return stream
        with patch.object(p, 'request', side_effect=request):
            result = p.chat(provider, 'http://127.0.0.1:11434', 'secret-key', 'test', 'system', messages or [{'role': 'user', 'content': 'hi'}], b.TOOLS, p.Cancellation(), text.append)
        return result, text, captured

    def test_ollama_native_stream_and_tools(self):
        stream = io.BytesIO((json.dumps({'message': {'content': 'Checking', 'thinking': 'private'}}) + '\n' +
                             json.dumps({'message': {'tool_calls': [{'function': {'name': 'run_command', 'arguments': {'command': 'pwd'}}}]}, 'done': True}) + '\n').encode())
        result, text, req = self.adapter('ollama', stream)
        self.assertEqual(text, ['Checking'])
        self.assertEqual(result['tool_calls'][0]['arguments'], {'command': 'pwd'})
        self.assertFalse(req[0][1]['think'])
        self.assertIsNone(req[0][2])
        self.assertNotIn('secret-key', json.dumps(req[0][1]))

    def test_claude_split_tool_json_and_private_thinking_ignored(self):
        events = [
          {'type': 'content_block_delta', 'index': 0, 'delta': {'type': 'thinking_delta', 'thinking': 'do not show'}},
          {'type': 'content_block_delta', 'index': 1, 'delta': {'type': 'text_delta', 'text': 'Check it'}},
          {'type': 'content_block_start', 'index': 2, 'content_block': {'type': 'tool_use', 'id': 'tool_1', 'name': 'read_file', 'input': {}}},
          {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': '{"pa'}},
          {'type': 'content_block_delta', 'index': 2, 'delta': {'type': 'input_json_delta', 'partial_json': 'th":"/etc/os-release"}'}},
          {'type': 'message_stop'}]
        result, text, req = self.adapter('claude', self.stream(events))
        self.assertEqual(text, ['Check it'])
        self.assertEqual(result['tool_calls'], [{'id': 'tool_1', 'name': 'read_file', 'arguments': {'path': '/etc/os-release'}}])
        self.assertEqual(req[0][0], 'https://api.anthropic.com/v1/messages')
        self.assertNotIn('secret-key', json.dumps(req[0][1]))
        self.assertEqual(req[0][2], 'secret-key')

    def test_openai_split_native_tool_arguments(self):
        events = [
          {'choices': [{'delta': {'tool_calls': [{'index': 0, 'id': 'tool1', 'function': {'name': 'run_command', 'arguments': '{"command":'}}]}, 'finish_reason': None}]},
          {'choices': [{'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': '"pwd"}'}}]}, 'finish_reason': 'tool_calls'}]}]
        result, _, _ = self.adapter('openai_local', self.stream(events))
        self.assertEqual(result['tool_calls'][0]['arguments']['command'], 'pwd')

    def test_provider_specific_tool_history_is_valid_and_consecutive_claude_results_group(self):
        messages = [{'role': 'assistant', 'content': '', 'tool_calls': [
          {'id': 'a', 'name': 'read_file', 'arguments': {'path': '/tmp/a'}}, {'id': 'b', 'name': 'read_file', 'arguments': {'path': '/tmp/b'}}]},
          {'role': 'tool', 'tool_call_id': 'a', 'name': 'read_file', 'content': 'A'},
          {'role': 'tool', 'tool_call_id': 'b', 'name': 'read_file', 'content': 'B', 'is_error': True}]
        claude = p.native_messages('claude', messages)
        self.assertEqual(len(claude), 2)
        self.assertEqual(len(claude[1]['content']), 2)
        self.assertTrue(claude[1]['content'][1]['is_error'])
        self.assertEqual(p.native_messages('openai_local', messages)[2]['tool_call_id'], 'b')
        self.assertEqual(p.native_messages('ollama', messages)[2]['tool_name'], 'read_file')

    def test_local_url_rejects_external_auth_ambiguous_and_redirect_destinations(self):
        for url in ('http://169.254.169.254:80', 'http://example.com:80', 'http://127.0.0.1.evil:80',
                    'http://user:pass@127.0.0.1:80', 'file:///tmp/x', 'http://127.0.0.1:80/admin', 'http://127.0.0.1:80?x=1'):
            with self.subTest(url=url), self.assertRaises(p.Error if hasattr(p, 'Error') else p.ProviderError):
                p.local_url(url)
        self.assertEqual(p.local_url('http://localhost:11434/'), 'http://127.0.0.1:11434')
        self.assertEqual(p.endpoint('http://[::1]:8000/v1', '/v1/models'), 'http://[::1]:8000/v1/models')
        with self.assertRaises(p.ProviderError):
            p.NoRedirect().redirect_request(None, None, 302, '', {}, 'http://example.com')

    def test_incomplete_and_error_streams_fail_without_untrusted_server_body(self):
        with self.assertRaisesRegex(p.ProviderError, 'before.*completed'):
            self.adapter('claude', self.stream([{'type': 'ping'}]))
        with self.assertRaisesRegex(p.ProviderError, 'inference error') as exc:
            self.adapter('claude', self.stream([{'type': 'error', 'error': {'message': 'secret-server-body'}}]))
        self.assertNotIn('secret-server-body', str(exc.exception))

    def test_models_normalized_and_discovery_timeout_bounded(self):
        captured = []
        def request(*args, **kwargs):
            captured.append(kwargs)
            return io.BytesIO(b'{"models":[{"name":"qwen:27b"}]}')
        with patch.object(p, 'request', side_effect=request):
            self.assertEqual(p.models('ollama', 'http://127.0.0.1:11434'), [{'id': 'qwen:27b', 'name': 'qwen:27b'}])
        self.assertEqual(captured[0]['timeout'], 5)
        self.assertIsNone(captured[0]['key'])

    def test_malformed_json_types_are_clean_errors(self):
        for value in ([], None, 'bad'):
            with self.assertRaises(p.ProviderError):
                p.read_json(io.BytesIO(json.dumps(value).encode()))
            with self.assertRaises(p.ProviderError):
                self.adapter('claude', self.stream([value]))
        with self.assertRaises(p.ProviderError):
            self.adapter('ollama', io.BytesIO(b'{"message":[]}\n'))

    def test_cancellation_prevents_provider_read(self):
        cancel = p.Cancellation()
        cancel.cancel()
        with self.assertRaises(p.Cancelled):
            list(p.lines(io.BytesIO(b'test\n'), cancel))


if __name__ == '__main__':
    unittest.main(verbosity=2)
