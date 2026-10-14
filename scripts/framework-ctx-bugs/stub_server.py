#!/usr/bin/env python3
"""Loopback-only synthetic llama-swap/llama-server stand-in, never a model runner."""
import argparse
import hashlib
import json
import math
import random
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gen_prompts as gp

BUILDS = {'nathanw': dict(name='stub-fork', sha='stubfork', build_info='b10814-9e21f2e53'),
          'upstream': dict(name='stub-upstream', sha='stubupstream', build_info='b11514-de7fa0a3c')}
INITIAL_MODEL = 'qwen3-coder-next-upstream'


def render(messages):
    return ''.join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + '<|im_start|>assistant\n'


def token_count(text, model='qwen'):
    # Intentionally different model tokenizers; plateau widths exercise exact fitting.
    return math.ceil(len(text) / (3 if model.startswith('qwen') else 3.4))


def clean_runbook():
    rng = random.Random(91)
    sections = []
    for i in range(1, 13):
        # Synthetic unique prose tokens resist the compression detector; no repeated sentences.
        prose = ' '.join('check' + ''.join(rng.choices('abcdefghijklmnop', k=9)) for _ in range(160))
        sections.append(f'{i}. Migration stage {i}\n{prose}.')
    return '\n\n'.join(sections) + '\n-- END OF RUNBOOK --'


RUNBOOK = clean_runbook()


def identify(messages):
    text = messages[-1]['content']
    if len(messages) > 2:
        return 'S5'
    if text.startswith('OPS LOG'):
        return 'S3'  # F uses the same template; distinguish its records below.
    if 'eight constraints' in text:
        return 'S2'
    if '12 numbered sections' in text:
        return 'S4'
    return 'S1'


def clean_answer(prompt, messages):
    if prompt == 'S1':
        return '391,12,708'
    if prompt == 'S2':
        return json.dumps(dict(title='Restart safely', steps=['Check status', 'Notify operators',
            'Stop service', 'Start service', 'Verify health'], risk='low')) + '\nEND'
    if prompt == 'S4':
        return RUNBOOK
    if prompt == 'S5':
        return 'The rollback gateway is cedar-582.\nref: TCK-4471'
    log = messages[-1]['content'].split('END LOG')[0]
    values = [re.search(r'id=' + r['id'] + r' \|[^\n]*value=([^\s|]+)', log)[1] for r in gp.NEEDLES]
    count = len(re.findall(r'host=host-03 \| severity=critical', log))
    expected = values + ['NOT IN LOG', 'NOT IN LOG']
    if gp.QUESTIONS[-1] in messages[-1]['content'].split('QUESTIONS\n')[-1]:
        expected.append(count)
    return '[LOG-QA]' + json.dumps(expected)


class StubServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address=('127.0.0.1', 0), *, clean=False, delay_request=None, delay_seconds=10,
                 kernel_log_error=False):
        super().__init__(address, Handler)
        self.clean = clean
        self.delay_request, self.delay_seconds = delay_request, delay_seconds
        self.entry = INITIAL_MODEL
        self.instance = 0
        self.requests = []
        self.loads = []
        self.mutex = threading.Lock()
        self.delayed = threading.Event()
        self.release_delay = threading.Event()
        self.kernel_log_error = kernel_log_error
        self.kernel_windows = []
        self.kernel_events = []

    @property
    def url(self):
        return f'http://127.0.0.1:{self.server_port}'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200):
        body = json.dumps(data).encode()
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        s = self.server
        if self.path.startswith('/upstream/') and self.path.endswith('/health'):
            with s.mutex:
                s.entry = self.path.split('/')[2]
                s.loads.append(s.entry)
                s.instance += 1
            self.reply(dict(status='ok'))
        elif self.path == '/health':
            self.reply(dict(status='ok', ctx_bugs_stub=True, builds=BUILDS,
                            server_instance=s.instance))
        elif self.path.startswith('/kernel-logs?'):
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            since, until = float(query['since'][0]), float(query['until'][0])
            s.kernel_windows.append((since, until))
            if s.kernel_log_error:
                self.reply(dict(error='sudo -n journalctl: simulated kernel log permission failure'))
            else:
                self.reply(dict(text='\n'.join(line for epoch, line in s.kernel_events if since <= epoch <= until)))
        elif self.path == '/props':
            match = re.search(r'-ctx(32k|64k|96k|131k)(?:-[a-z0-9]+)?$', s.entry)
            size = {'32k': 32768, '64k': 65536, '96k': 98304, '131k': 131072}.get(match[1] if match else '', 131072)
            build = 'nathanw' if '-nathanw-' in s.entry else 'upstream'
            self.reply(dict(model_alias=s.entry, default_generation_settings=dict(n_ctx=size),
                            total_slots=1, build_info=BUILDS[build]['build_info']))
        elif self.path == '/logs':
            self.reply(dict(entry=s.entry, loads=s.loads, requests=len(s.requests)))
        else:
            self.reply(dict(error='unknown path'), 404)

    def do_POST(self):
        s = self.server
        payload = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        if self.path == '/apply-template':
            self.reply(dict(prompt=render(payload['messages'])))
        elif self.path == '/tokenize':
            self.reply(dict(tokens=list(range(token_count(payload['content'], s.entry)))))
        elif self.path == '/v1/chat/completions':
            with s.mutex:
                s.requests.append(payload)
                number = len(s.requests)
            if number == s.delay_request:
                s.delayed.set()
                s.release_delay.wait(s.delay_seconds)
            prompt = identify(payload['messages'])
            answer = clean_answer(prompt, payload['messages'])
            reasoning, finish, canned = 'Checked the supplied inputs.', 'stop', 'clean'
            model = payload['model']
            greedy = payload['temperature'] == 0
            is_s3 = prompt == 'S3' and payload['messages'][-1]['content'].count('\nid=') == 200
            if not s.clean:
                if model.startswith('laguna') and '-nathanw-' in model:
                    canned = 'token-14-flood'
                elif model == 'qwen3.8-flash-next-q4-nathanw-ctx32k':
                    if prompt == 'S1' and greedy:
                        reasoning = ('a' * 50 + ' b' * 12) * 3
                        canned = 'loop'
                    elif prompt == 'S2' and greedy:
                        phrase = 'one two three four five six seven eight'
                        reasoning = '\n'.join(f'{i} {phrase} {hashlib.sha256(str(i).encode()).hexdigest()}' for i in range(4))
                        canned = 'repetition'
                    elif prompt == 'S4' and greedy:
                        finish, canned = 'length', 'runaway'
                    elif prompt == 'S5' and not greedy and payload['seed'] == 2:
                        answer = '<think>' + answer
                        canned = 'template-leak'
                    elif is_s3 and not greedy and payload['seed'] == 1:
                        values = json.loads(answer[len('[LOG-QA]'):])
                        values[5] = 'invented-password'
                        answer = '[LOG-QA]' + json.dumps(values)
                        canned = 'absent-fact'
            visible = token_count(reasoning + answer, model)
            # Deliberately synthetic accounting: isolate hidden-token detection
            # while leaving the clean visible answer unchanged for comparisons.
            completion = max(476, visible * 20) if canned == 'token-14-flood' else visible
            self.reply(dict(id=f'stub-{number}', ctx_bugs_canned=canned, model=model,
                choices=[dict(message=dict(role='assistant', content=answer, reasoning_content=reasoning), finish_reason=finish)],
                usage=dict(prompt_tokens=token_count(render(payload['messages']), model), completion_tokens=completion),
                timings=dict(prompt_per_second=600, predicted_per_second=25)))
        else:
            self.reply(dict(error='unknown path'), 404)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--clean', action='store_true')
    parser.add_argument('--delay-request', type=int)
    parser.add_argument('--delay-seconds', type=float, default=10)
    parser.add_argument('--kernel-log-error', action='store_true', help='simulate a failed kernel journal command')
    args = parser.parse_args()
    server = StubServer(('127.0.0.1', args.port), clean=args.clean,
                        delay_request=args.delay_request, delay_seconds=args.delay_seconds,
                        kernel_log_error=args.kernel_log_error)
    print(server.url, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
