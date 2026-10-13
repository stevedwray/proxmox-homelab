#!/usr/bin/env python3
"""Checkpointed Framework context bug hunt. Standard-library only."""
import argparse
import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

import detectors
import framework_lock
import gen_prompts as gp
from resp_client import RespRedis

MODELS = ('qwen3.8-flash-next-q4', 'laguna-s-2.1')
BUILDS = ('nathanw', 'upstream')
SIZES = (32768, 65536, 98304, 131072)
SUFFIXES = dict(zip(SIZES, ('32k', '64k', '96k', '131k')))
BUDGET, MARGIN = 16384, 2048
DEFAULT_MODEL = 'glm-5.3-flash-upstream'
PROMPT_DIR = Path(__file__).parent / 'prompts'
# D3: Qwen values are the operator's published thinking-mode recipe.
# Laguna temperature/top_p: Poolside's "Recommended sampling", pinned card:
# https://huggingface.co/poolside/Laguna-S-2.1-FP8/blob/2bea609ec5cc284a99471d3eba1e33fa9cede712/README.md
# top_k/min_p: the base checkpoint's shipped generation_config (linked by its card):
# https://huggingface.co/poolside/Laguna-S-2.1/blob/179ee67/generation_config.json
# Do not substitute the checkpoint's 1.0/1.0 defaults for the published recommendation.
SAMPLING = {
    MODELS[0]: dict(temperature=.6, top_p=.95, top_k=20, min_p=0),
    MODELS[1]: dict(temperature=.7, top_p=.95, top_k=20, min_p=0),
}
SAMPLING_SOURCES = {
    MODELS[0]: 'docs/ctx-bug-test/plan.md D3',
    MODELS[1]: [
        'https://huggingface.co/poolside/Laguna-S-2.1-FP8/blob/2bea609ec5cc284a99471d3eba1e33fa9cede712/README.md',
        'https://huggingface.co/poolside/Laguna-S-2.1/blob/179ee67/generation_config.json'],
}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('wb') as output:
        output.write(gp.json_bytes(value))
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


def append_jsonl(path, value):
    with Path(path).open('a', encoding='utf-8') as output:
        output.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')
        output.flush()
        os.fsync(output.fileno())


def read_results(path):
    """Discard only an incomplete final append; corrupted complete records are fatal."""
    if not path.exists():
        return []
    data = path.read_bytes()
    complete = data.rsplit(b'\n', 1)[0] + b'\n' if b'\n' in data else b''
    if not data.endswith(b'\n'):
        path.write_bytes(complete)
    return [json.loads(line) for line in complete.splitlines() if line]


class Client:
    def __init__(self, base_url, swap_url=None, timeout=1800, api_key=None):
        self.base = base_url.rstrip('/')
        self.swap = (swap_url or base_url).rstrip('/')
        self.timeout, self.api_key = timeout, api_key
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for url in (self.base, self.swap):
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('base URLs must be HTTP(S) without embedded credentials')

    def call(self, path, payload=None, swap=False):
        headers = {'Content-Type': 'application/json'}
        if not swap and self.api_key:
            headers['Authorization'] = 'Bearer ' + self.api_key
        request = urllib.request.Request((self.swap if swap else self.base) + path,
            data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.load(response)

    def load(self, entry):
        return self.call('/upstream/' + urllib.parse.quote(entry, safe='') + '/health', swap=True)

    def tokenize(self, text, special=False):
        result = self.call('/tokenize', dict(content=text, add_special=False, parse_special=special))
        if not isinstance(result.get('tokens'), list):
            raise ValueError('/tokenize did not return a tokens list')
        return len(result['tokens'])

    def prompt_tokens(self, fixture):
        # Counting raw messages misses the template/BOS/generation prefix. Render first.
        rendered = self.call('/apply-template', dict(messages=fixture['messages'], add_generation_prompt=True))
        if not isinstance(rendered.get('prompt'), str):
            raise ValueError('/apply-template did not return a prompt string')
        return self.tokenize(rendered['prompt'], special=True)


def entry_id(model, build, size, candidate=False):
    return f'{model}-{build}' + ('-candidate' if candidate else '') + f'-ctx{SUFFIXES[size]}'


def fit_check(count, size):
    if count + BUDGET + MARGIN > size:
        raise ValueError(f'prompt {count} + answer {BUDGET} + margin {MARGIN} exceeds context {size}')


def make_fill(client, size, template):
    """Maximize complete records, then fit inert padding to the exact token target.

    Every candidate relocates the same needles and recomputes the count. Fail
    closed if this tokenizer cannot reach the exact target with the padding.
    """
    target = size - BUDGET - MARGIN
    seed = template['seed']
    low, high = 20, 200
    if client.prompt_tokens(gp.qa_prompt(low, seed)) > target:
        raise ValueError('F minimum log cannot fit')
    while client.prompt_tokens(gp.qa_prompt(high, seed)) <= target:
        low, high = high, high * 2
        if high > 100000:
            raise ValueError('F record search did not converge')
    while high - low > 1:
        middle = (low + high) // 2
        if client.prompt_tokens(gp.qa_prompt(middle, seed)) <= target:
            low = middle
        else:
            high = middle
    base = gp.qa_prompt(low, seed)
    base_count = client.prompt_tokens(base)
    if base_count == target:
        return base, target
    # Leave room for the padding label itself, even when a record ended one
    # token below the target. Regenerate so positions/count remain accurate.
    low -= 1
    base_count = client.prompt_tokens(gp.qa_prompt(low, seed))
    # Short inert audit padding contains no IDs, host names, facts or answers.
    prefix = '\nAudit padding:'
    left, right = 0, max(256, (target - base_count) * 16)
    def candidate(length):
        pad = prefix + (' x' * ((length + 1) // 2))[:length]
        return gp.qa_prompt(low, seed, pad)
    while client.prompt_tokens(candidate(right)) < target:
        right *= 2
        if right > 65536:
            raise ValueError('F padding search did not converge')
    while left <= right:
        middle = (left + right) // 2
        fixture = candidate(middle)
        count = client.prompt_tokens(fixture)
        if count == target:
            fixture['padding_chars'] = middle
            return fixture, count
        if count < target:
            left = middle + 1
        else:
            right = middle - 1
    # BPE boundaries can make token count locally nonmonotonic.
    for length in range(max(0, right - 64), left + 65):
        fixture = candidate(length)
        if client.prompt_tokens(fixture) == target:
            fixture['padding_chars'] = length
            return fixture, target
    raise ValueError('cannot land F on exact tokenizer target; cell refused')


def check_props(props, entry, size, expected):
    settings = props.get('default_generation_settings', {})
    actual_ctx = props.get('n_ctx', settings.get('n_ctx'))
    alias = props.get('model_alias', props.get('alias'))
    if alias != entry or actual_ctx != size or props.get('build_info') != expected:
        raise ValueError(f'/props mismatch: expected {entry}, n_ctx={size}, build_info={expected!r}; got {props!r}')
    slots = props.get('total_slots', props.get('n_slots'))
    if slots is not None and slots != 1:
        raise ValueError(f'expected one parallel slot, got {slots}')


def command(argv):
    result = subprocess.run(argv, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f'{argv[0]} failed: {result.stderr.strip()}')
    return result.stdout


def server_pid(entry):
    found = []
    for path in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            argv = path.read_bytes().split(b'\0')
            if argv and b'llama-server' in argv[0] and b'--alias' in argv:
                index = argv.index(b'--alias')
                if argv[index+1].decode() == entry:
                    found.append(int(path.parent.name))
        except (OSError, UnicodeError, IndexError):
            continue
    if len(found) != 1:
        raise RuntimeError(f'cannot identify exactly one llama-server PID for {entry}: {found}')
    pid = found[0]
    return [pid, Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]]


def runs(short=False, greedy_only=False, extra_seeds=None):
    if extra_seeds:
        return [(p, f'seed{s}', s, False) for p in ('S1', 'S2', 'S3', 'S4', 'S5', 'F') for s in extra_seeds]
    out = []
    for prompt in ('S1', 'S2', 'S3', 'S4', 'S5', 'F'):
        out.append((prompt, 'greedy', 1, True))
        if not short and not greedy_only:
            out.extend((prompt, f'seed{s}', s, False) for s in ((1,) if prompt == 'F' else (1, 2, 3)))
    return out


def add_divergences(records):
    """Rebuild comparisons on resume, independent of execution order."""
    greedy = {(r['model'], r['build'], r['size'], r['prompt']): r for r in records
              if r['run'] == 'greedy' and not r.get('error')}
    for r in records:
        r['flags'] = [f for f in r['flags'] if f not in ('ctx-divergence', 'build-divergence')]
        for flag in ('ctx-divergence', 'build-divergence'):
            r['details'].pop(flag, None)
        if r['run'] != 'greedy' or r.get('error'):
            continue
        baselines = []
        if r['prompt'] != 'F' and r['size'] != 32768:
            baselines.append(('ctx-divergence', greedy.get((r['model'], r['build'], 32768, r['prompt']))))
        if r['build'] == 'upstream':
            baselines.append(('build-divergence', greedy.get((r['model'], 'nathanw', r['size'], r['prompt']))))
        for flag, baseline in baselines:
            if baseline:
                index = detectors.first_difference(r['answer'], baseline['answer'])
                if index is not None:
                    r['flags'].append(flag)
                    r['details'][flag] = dict(first_differing_character=index, baseline=baseline['key'])
        r['flags'].sort()


def findings(records):
    """Attribute reproducible flags at the same prompt, model and size."""
    out = []
    groups = {}
    for r in records:
        groups.setdefault((r['model'], r['size'], r['prompt']), {}).setdefault(r['build'], []).append(r)
    info_flags = {'build-divergence'}
    for (model, size, prompt), builds in groups.items():
        for build, own in builds.items():
            other = builds.get('upstream' if build == 'nathanw' else 'nathanw', [])
            for flag in sorted({f for r in own for f in r['flags']} - info_flags):
                greedy_flag = any(r['run'] == 'greedy' and flag in r['flags'] for r in own)
                sampled = [r for r in own if r['run'].startswith('seed') and r['seed'] in (1, 2, 3)]
                opposite = [r for r in other if r['run'].startswith('seed') and r['seed'] in (1, 2, 3)]
                reproducible = greedy_flag or sum(flag in r['flags'] for r in sampled) >= 2
                classified = False
                if reproducible and len(opposite) == 3 and not any(flag in r['flags'] for r in opposite):
                    out.append(dict(kind='build bug', model=model, build=build, size=size, prompt=prompt, flag=flag))
                    classified = True
                baseline = [r for r in records if r['model'] == model and r['build'] == build
                            and r['size'] == 32768 and r['prompt'] == prompt]
                if prompt != 'F' and (flag == 'ctx-divergence' or
                    (size > 32768 and baseline and not any(flag in r['flags'] for r in baseline))):
                    out.append(dict(kind='context-size bug', model=model, build=build, size=size, prompt=prompt, flag=flag))
                    classified = True
                if not classified:
                    repeats = [r for r in own if r['seed'] > 3]
                    reproduced = len(repeats) >= 3 and sum(flag in r['flags'] for r in repeats) >= 2
                    out.append(dict(kind='reproduced; compare original paired cells' if reproduced else 'needs three more seeds',
                                    model=model, build=build, size=size, prompt=prompt, flag=flag))
    return out


def report(directory, records, manifest):
    add_divergences(records)
    lines = ['# Context bug test', '', f"Status: {manifest.get('status', 'running')}. Dry run: {manifest['dry_run']}.", '',
             '| Cell | Prompt / run | Flags | Prompt tokens | Generated tokens | Prompt tok/s | Gen tok/s | Wall seconds |',
             '| --- | --- | --- | ---: | ---: | ---: | ---: | ---: |']
    for r in records:
        timing = r.get('response', {}).get('timings', {})
        lines.append(f"| {r['cell']} | {r['prompt']}/{r['run']} | {', '.join(r['flags']) or 'clean'} | "
                     f"{r['prompt_tokens']} | {r.get('generated_tokens', 0)} | {timing.get('prompt_per_second', '—')} | "
                     f"{timing.get('predicted_per_second', '—')} | {r['wall_seconds']:.3f} |")
    lines.extend(['', '## Divergences', '', '| Request | Flag | First differing character |', '| --- | --- | ---: |'])
    for r in records:
        for flag in ('ctx-divergence', 'build-divergence'):
            if flag in r['flags']:
                lines.append(f"| {r['key']} | {flag} | {r['details'][flag]['first_differing_character']} |")
    conclusions = findings(records)
    lines.extend(['', '## Candidate findings', '', 'Build divergence is information only. Unpaired/incomplete comparisons do not establish build bugs.', ''])
    for finding in conclusions:
        lines.append('- ' + json.dumps(finding, sort_keys=True))
    fill = [r for r in records if r['prompt'] == 'F' and r['run'] == 'greedy']
    lines.extend(['', '## Fill accuracy', '', '| Model | Build | Context | Correct / 8 |', '| --- | --- | ---: | ---: |'])
    for r in fill:
        bad = {f.split(':', 1)[1] for f in r['flags'] if f.startswith(('wrong:q', 'hallucination:q'))}
        lines.append(f"| {r['model']} | {r['build']} | {r['size']} | {8-len(bad)}/8 |")
    lines.extend(['', 'F accuracy falling on both builds is fill degradation, not a context-size bug.',
                  'Raw responses, settings and hashes are in results.jsonl, raw/, prompts/ and run.json.', ''])
    (directory / 'report.md').write_text('\n'.join(lines))
    write_json(directory / 'findings.json', conclusions)


class Run:
    def __init__(self, args):
        self.args = args
        self.directory = Path(args.run_dir) if args.run_dir else Path(args.results_root) / dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        self.directory.mkdir(parents=True, exist_ok=True)
        for name in ('raw', 'logs', 'prompts'):
            (self.directory / name).mkdir(exist_ok=True)
        self.client = Client(args.base_url, args.swap_url, args.timeout,
                             Path(args.api_key_file).read_text().strip() if args.api_key_file and not args.dry_run else None)
        self.manifest_path = self.directory / 'run.json'
        self.results_path = self.directory / 'results.jsonl'
        self.records, self.done = [], set()
        self.manifest = {}

    def log(self, message):
        line = f'{now()} {message}'
        print(line, flush=True)
        with (self.directory / 'run.log').open('a') as output:
            output.write(line + '\n')

    def save(self):
        write_json(self.manifest_path, self.manifest)
        old = {r['key']: (list(r['flags']), dict(r['details'])) for r in self.records}
        report(self.directory, self.records, self.manifest)
        changed = [r for r in self.records if old[r['key']] != (r['flags'], r['details'])]
        if changed:
            # Comparisons can become known only when the other cell finishes.
            # Persist them in BOTH the checkpoint and raw records, not just the report.
            temporary = self.results_path.with_suffix('.jsonl.tmp')
            with temporary.open('w') as output:
                for record in self.records:
                    output.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n')
                output.flush()
                os.fsync(output.fileno())
            temporary.replace(self.results_path)
            for record in changed:
                write_json(self.directory / 'raw' / record['cell'] / f"{record['prompt']}-{record['run']}.json", record)
        write_json(self.directory / 'progress.json', dict(status=self.manifest['status'],
                   completed=len(self.records), updated=now(), run_dir=str(self.directory)))

    def prepare(self):
        if self.args.dry_run:
            for url in (self.client.base, self.client.swap):
                if urllib.parse.urlsplit(url).hostname not in ('127.0.0.1', '::1', 'localhost'):
                    raise ValueError('dry run requires loopback stand-in URLs')
            health = self.client.call('/health')
            if health.get('ctx_bugs_stub') is not True:
                raise ValueError('dry run refuses a server without the stand-in marker')
            builds = health['builds']
        else:
            if not self.args.builds_json:
                raise ValueError('live runs require --builds-json expectations recorded in phase 1; do not infer /props build_info from compiler version text')
            builds = json.loads(Path(self.args.builds_json).read_text())
            for label in self.args.builds:
                backend = 'fork' if label == 'nathanw' else 'upstream'
                link = 'candidate' if self.args.candidate else 'current'
                info = json.loads((Path(self.args.builds_root) / backend / link / 'build.json').read_text())
                if any(builds[label][key] != info[key] for key in ('name', 'sha')):
                    raise ValueError(f'{backend}/{link} does not match approved build expectations')
        if self.args.builds_json:
            builds = json.loads(Path(self.args.builds_json).read_text())
        hashes = json.loads((PROMPT_DIR / 'manifest.json').read_text())
        self.fixtures = {}
        for name, item in hashes['prompts'].items():
            data = (PROMPT_DIR / item['file']).read_bytes()
            if gp.sha(data) != item['sha256']:
                raise ValueError(f'prompt hash mismatch: {name}')
            self.fixtures[name] = json.loads(data)
        identity = dict(dry_run=self.args.dry_run, base_url=self.client.base, swap_url=self.client.swap,
                        builds=builds, prompt_manifest=hashes, sampling=SAMPLING,
                        models=self.args.models, sizes=self.args.sizes, builds_selected=self.args.builds,
                        greedy_only=self.args.greedy_only, extra_seeds=self.args.extra_seeds,
                        candidate=self.args.candidate,
                        script_hashes={p.name: gp.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py')
                                       if not p.name.startswith('test_') and p.name != 'stub_server.py'},
                        answer_budget=BUDGET, margin=MARGIN, cache_prompt=False)
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text())
            if self.manifest['identity'] != identity:
                raise ValueError('resume settings/builds/prompt hashes differ from run.json')
        else:
            self.manifest = dict(identity=identity, dry_run=self.args.dry_run,
                started=now(), job_id='ctx-bugs-' + self.directory.name, status='running',
                sampling_sources=SAMPLING_SOURCES, cells={}, fill_prompts={},
                harness_sha256=gp.sha(Path(__file__).read_bytes()))
            try:
                self.manifest['restore_model'] = self.client.call('/props')['model_alias']
            except (OSError, ValueError):
                self.manifest['restore_model'] = DEFAULT_MODEL
                self.manifest['restore_model_note'] = 'nothing answered on :8080'
            if not isinstance(self.manifest['restore_model'], str) or not self.manifest['restore_model']:
                raise ValueError('/props model_alias must be a non-empty string')
        self.manifest.update(status='running', resumed=now())
        for name, item in hashes['prompts'].items():
            (self.directory / 'prompts' / item['file']).write_bytes((PROMPT_DIR / item['file']).read_bytes())
        (self.directory / 'dmesg.txt').touch(exist_ok=True)
        self.save()

    @contextlib.contextmanager
    def lock(self):
        # This local lock also prevents simultaneous writers to the checkpoint.
        with (self.directory / '.lock').open('a') as local:
            fcntl.flock(local, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if self.args.dry_run:
                yield
                return
            cfg = json.loads(Path(self.args.redis_config).read_text())['publish']
            client = RespRedis(host=cfg['host'], port=cfg.get('port', 6379), db=cfg.get('db', 1),
                               password=Path(cfg['password_file']).read_text().strip(), timeout=10)
            if not framework_lock.acquire(client, self.manifest['job_id'], 'ctx-bugs', 'ctx-bugs',
                    on_wait=lambda holder: self.log(f'Waiting for Framework lock: {holder}')):
                raise RuntimeError('could not acquire Framework lock')
            with framework_lock.held(client, self.manifest['job_id']):
                self.redis_client = client
                yield

    def check_lock(self):
        if not self.args.dry_run and not framework_lock.renew(self.redis_client, self.manifest['job_id']):
            raise RuntimeError('Framework run lock lost; stopping')

    def preflight_cell(self, model, build, size):
        entry = entry_id(model, build, size, self.args.candidate)
        self.check_lock()
        self.client.load(entry)
        props = self.client.call('/props')
        check_props(props, entry, size, self.manifest['identity']['builds'][build]['build_info'])
        counts = {}
        fixtures = {k: self.fixtures[k] for k in ('S1', 'S2', 'S3', 'S4', 'S5')}
        for name, fixture in fixtures.items():
            counts[name] = self.client.prompt_tokens(fixture)
            fit_check(counts[name], size)
        fill_key = f'{model}-ctx{SUFFIXES[size]}'
        fill_path = self.directory / 'prompts' / f'{fill_key}-F.json'
        if fill_key in self.manifest['fill_prompts']:
            meta = self.manifest['fill_prompts'][fill_key]
            data = fill_path.read_bytes()
            if gp.sha(data) != meta['sha256']:
                raise ValueError('saved F hash mismatch')
            fill = json.loads(data)
            count = self.client.prompt_tokens(fill)
            if count != meta['token_count']:
                raise ValueError('build tokenizers differ for saved F; cell refused')
        else:
            fill, count = make_fill(self.client, size, self.fixtures['F-template'])
            data = gp.json_bytes(fill)
            fill_path.write_bytes(data)
            self.manifest['fill_prompts'][fill_key] = dict(file=str(fill_path.relative_to(self.directory)),
                sha256=gp.sha(data), token_count=count, needles=fill['needles'], expected=fill['expected'])
        if count != size - BUDGET - MARGIN:
            raise ValueError('saved F is not at the exact target')
        fixtures['F'], counts['F'] = fill, count
        fit_check(count, size)
        cell = self.manifest['cells'].setdefault(entry, {})
        cell.update(props=props, prompt_tokens=counts, fill_key=fill_key)
        self.save()
        return entry, fixtures, counts

    def server_identity(self, entry):
        if self.args.dry_run:
            return self.client.call('/health').get('server_instance')
        return server_pid(entry)

    def kernel_window(self, since, until):
        if self.args.dry_run:
            query = urllib.parse.urlencode(dict(since=since, until=until))
            result = self.client.call('/kernel-logs?' + query)
            if result.get('error'):
                raise RuntimeError(result['error'])
            return result['text']
        return command(['sudo', '-n', 'journalctl', '-k', '--since', f'@{since:.6f}',
                        '--until', f'@{until:.6f}', '--no-pager', '-o', 'short-iso'])

    def cell_logs(self, cell_start):
        try:
            if self.args.dry_run:
                return json.dumps(self.client.call('/logs', swap=True), indent=2)
            return command(['sudo', '-n', 'journalctl', '-u', 'llama-swap.service',
                            '--since', cell_start, '--no-pager'])
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            return f'ERROR capturing llama-swap system journal: {type(exc).__name__}: {exc}'

    def request(self, model, build, size, entry, fixture, count, prompt, run, seed, greedy, short):
        self.check_lock()
        settings = dict(SAMPLING[model], seed=seed, temperature=0 if greedy else SAMPLING[model]['temperature'],
                        max_tokens=2048 if short else BUDGET, cache_prompt=False, stream=False)
        payload = dict(settings, model=entry, messages=fixture['messages'])
        key = f'{entry}/{prompt}/{run}'
        evidence_errors = []
        pid = after_pid = None
        try:
            pid = self.server_identity(entry)
        except (OSError, ValueError, RuntimeError) as exc:
            evidence_errors.append(f'before server identity: {type(exc).__name__}: {exc}')
        since = time.time()
        started = time.monotonic()
        response, error = {}, None
        try:
            response = self.client.call('/v1/chat/completions', payload)
            if not response.get('choices') or not isinstance(response['choices'][0].get('message'), dict):
                raise ValueError('invalid completion response')
        except (OSError, ValueError) as exc:
            error = f'{type(exc).__name__}: {exc}'
        until = time.time()
        elapsed = time.monotonic() - started
        healthy = True
        try:
            self.client.call('/health')
        except (OSError, ValueError) as exc:
            healthy = False
            evidence_errors.append(f'after health: {type(exc).__name__}: {exc}')
        try:
            after_pid = self.server_identity(entry)
        except (OSError, ValueError, RuntimeError) as exc:
            evidence_errors.append(f'after server identity: {type(exc).__name__}: {exc}')
        window = ''
        try:
            window = self.kernel_window(since, until)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            evidence_errors.append(f'kernel window capture: {type(exc).__name__}: {exc}')
        evidence_error = '; '.join(evidence_errors) or None
        choice = response.get('choices', [{}])[0]
        message = choice.get('message', {})
        visible = (message.get('reasoning_content') or '') + (message.get('content') or '')
        visible_count = None
        if not error and healthy:
            try:
                visible_count = self.client.tokenize(visible)
            except (OSError, ValueError) as exc:
                error = f'visible token count failed: {exc}'
        grade = detectors.detect(prompt, response, fixture, visible_count, error=error, healthy=healthy,
                                 restarted=pid is not None and after_pid is not None and after_pid != pid,
                                 dmesg_window=window)
        record = dict(key=key, cell=entry, model=model, build=build, size=size, prompt=prompt, run=run, seed=seed,
                      settings=settings, prompt_sha256=gp.sha(gp.json_bytes(fixture)), prompt_tokens=count,
                      server_prompt_tokens=response.get('usage', {}).get('prompt_tokens'),
                      generated_tokens=response.get('usage', {}).get('completion_tokens', 0),
                      response=response, error=error, evidence_error=evidence_error,
                      kernel_window=dict(since=since, until=until),
                      wall_seconds=elapsed, recorded=now(), server_before=pid, server_after=after_pid, **grade)
        with (self.directory / 'dmesg.txt').open('a') as output:
            output.write(f'\n## {key} kernel window @{since:.6f} to @{until:.6f}\n{window}\n')
        return record

    def checkpoint(self, record):
        write_json(self.directory / 'raw' / record['cell'] / f"{record['prompt']}-{record['run']}.json", record)
        append_jsonl(self.results_path, record)
        self.records.append(record)
        self.done.add(record['key'])
        self.save()
        self.log(f"{record['key']}: {', '.join(record['flags']) or 'clean'}")

    def matrix(self):
        # Size before build makes paired F reuse immediate; S1 always runs first.
        for model in self.args.models:
            for size in self.args.sizes:
                for build in self.args.builds:
                    entry = entry_id(model, build, size, self.args.candidate)
                    existing = self.manifest['cells'].get(entry, {})
                    short = existing.get('short', self.args.candidate)
                    pending = [r for r in runs(short, self.args.greedy_only, self.args.extra_seeds)
                               if f'{entry}/{r[0]}/{r[1]}' not in self.done]
                    if not pending:
                        continue
                    self.log(f'Loading and checking {entry}')
                    cell_start = now()
                    try:
                        entry, fixtures, counts = self.preflight_cell(model, build, size)
                        self.manifest['cells'][entry]['short'] = short
                        # The normal S1 greedy is a probe only if it triggers short form.
                        # Save that probe separately, then run all six short requests at 2048.
                        probe_key = f'{entry}/S1/greedy'
                        if model == MODELS[1] and build == 'nathanw' and not short and probe_key not in self.done:
                            probe = self.request(model, build, size, entry, fixtures['S1'], counts['S1'],
                                                 'S1', 'greedy', 1, True, False)
                            short = 'hidden-tokens' in probe['flags']
                            self.manifest['cells'][entry]['short'] = short
                            if short:
                                write_json(self.directory / 'raw' / entry / 'S1-probe.json', probe)
                                self.manifest['cells'][entry]['probe'] = probe
                                self.save()
                            else:
                                self.checkpoint(probe)
                        for prompt, run, seed, greedy in runs(short, self.args.greedy_only, self.args.extra_seeds):
                            if f'{entry}/{prompt}/{run}' in self.done:
                                continue
                            record = self.request(model, build, size, entry, fixtures[prompt], counts[prompt],
                                                  prompt, run, seed, greedy, short)
                            self.checkpoint(record)
                    finally:
                        logs = self.cell_logs(cell_start)
                        with (self.directory / 'logs' / f'{entry}.log').open('a') as output:
                            output.write(f'\n## Invocation {cell_start}\n{logs}\n')

    def execute(self):
        # Claim the run directory before reading or modifying any checkpoint.
        with (self.directory / '.checkpoint-lock').open('a') as guard:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.records = read_results(self.results_path)
            self.done = {r['key'] for r in self.records}
            if len(self.records) != len(self.done):
                raise ValueError('duplicate checkpoint request keys')
            self.prepare()
            return self.execute_locked()

    def execute_locked(self):
        with self.lock():
            try:
                self.matrix()
                self.manifest['status'] = 'complete'
            except KeyboardInterrupt:
                self.manifest['status'] = 'interrupted'
                self.log('Interrupted request remains pending; resume with --run-dir')
            except Exception as exc:
                self.manifest.update(status='failed', failure=f'{type(exc).__name__}: {exc}')
                self.log(self.manifest['failure'])
            finally:
                try:
                    self.check_lock()
                    restore_model = self.manifest.get('restore_model', DEFAULT_MODEL)
                    if re.search(r'-ctx(?:32k|64k|96k|131k)$', restore_model):
                        restore_model = DEFAULT_MODEL
                    self.client.load(restore_model)
                    self.manifest['restored_model'] = restore_model
                    self.manifest['restored_default'] = True
                except Exception as exc:
                    self.manifest.update(restored_default=False, restore_error=str(exc), status='failed')
                self.save()
        return 0 if self.manifest['status'] == 'complete' else (130 if self.manifest['status'] == 'interrupted' else 1)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='loopback marked stand-in only; no Redis or host commands')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--swap-url', help='default :8099 live; same as base URL in dry run')
    parser.add_argument('--api-key-file', default=None, help='live defaults to /etc/llamacpp/api-key')
    parser.add_argument('--results-root', default='/storage/artifacts/framework-ctx-bugs')
    parser.add_argument('--run-dir', help='explicit existing directory resumes, or creates a new run')
    parser.add_argument('--timeout', type=float, default=1800)
    parser.add_argument('--models', nargs='+', choices=MODELS, default=list(MODELS))
    parser.add_argument('--builds', nargs='+', choices=BUILDS, default=list(BUILDS))
    parser.add_argument('--sizes', nargs='+', type=int, choices=SIZES, default=list(SIZES))
    parser.add_argument('--greedy-only', action='store_true', help='pilot: combine with --sizes 131072')
    parser.add_argument('--extra-seeds', nargs=3, type=int, help='reproduction: three additional seeds, e.g. 4 5 6')
    parser.add_argument('--builds-root', default='/storage/llama-builds')
    parser.add_argument('--builds-json', help='explicit {nathanw,upstream: {name,sha,build_info}} expectations')
    parser.add_argument('--candidate', action='store_true', help='D1: one Laguna/nathanw candidate short-form cell; specify its size')
    parser.add_argument('--redis-config', default='/etc/llama-builds/backends.json')
    args = parser.parse_args(argv)
    if not args.dry_run:
        args.swap_url = args.swap_url or 'http://127.0.0.1:8099'
        args.api_key_file = args.api_key_file or '/etc/llamacpp/api-key'
    if args.extra_seeds and (len(set(args.extra_seeds)) != 3 or any(s <= 3 for s in args.extra_seeds)):
        parser.error('reproduction needs three distinct seeds greater than 3')
    if args.candidate and (args.models != [MODELS[1]] or args.builds != ['nathanw'] or len(args.sizes) != 1):
        parser.error('--candidate requires --models laguna-s-2.1 --builds nathanw and exactly one --sizes value')
    return args


def main(argv=None):
    def interrupt(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupt)
    signal.signal(signal.SIGINT, interrupt)
    try:
        return Run(parse_args(argv)).execute()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f'ctx-bugs: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
