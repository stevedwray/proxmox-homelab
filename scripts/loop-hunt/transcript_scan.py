"""Read-only adapters for the repository's saved benchmark/agent transcripts."""
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import tempfile

from scan_openwebui import bucket, detect_text, markdown, month, text_content

SETTING_KEYS = {'max_tokens', 'max_completion_tokens', 'max_gen_toks', 'n_predict',
                'temperature', 'top_p', 'top_k', 'min_p', 'seed', 'stop',
                'reasoning_effort', 'cache_prompt', 'stream', 'num_concurrent'}
RESPONSE_KEYS = ('response', 'model_output', 'model_response', 'initial_response')


def read_json(path):
    with Path(path).open() as source:
        return json.load(source)


def dictionary(value):
    return value if isinstance(value, dict) else {}


def parameters(value):
    if isinstance(value, str):
        value = dict(part.split('=', 1) for part in value.split(',') if '=' in part)
    return {key: val for key, val in dictionary(value).items() if key in SETTING_KEYS}


def metadata(path, root, kind):
    """Nearest recorded run metadata, never current live server identity."""
    run = {}
    for folder in (path.parent, *path.parent.parents):
        candidate = folder/'run.json'
        if candidate.is_file():
            if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                raise ValueError('run metadata escapes approved root')
            run = dictionary(read_json(candidate))
            break
        if folder == root:
            break
    if kind == 'cse':
        # CSE's producer uses meta.json (and a later manifest.json), not
        # eval-runner's run.json. These contain recorded run dates/requests.
        for name in ('meta.json', 'manifest.json'):
            candidate = path.parent/name
            if candidate.is_file():
                if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                    raise ValueError('CSE metadata escapes approved root')
                run = {**dictionary(read_json(candidate)), **run}
    result = {}
    if kind == 'lm-eval':
        stamp = path.stem.rsplit('_', 1)[-1]
        choices = list(path.parent.glob('results_*.json'))
        exact = path.parent/('results_'+stamp+'.json')
        if exact in choices:
            if exact.is_symlink() or not exact.resolve().is_relative_to(root):
                raise ValueError('result metadata escapes approved root')
            result = dictionary(read_json(exact))
        elif len(choices) == 1:
            if choices[0].is_symlink() or not choices[0].resolve().is_relative_to(root):
                raise ValueError('result metadata escapes approved root')
            result = dictionary(read_json(choices[0]))
    elif kind == 'cse' and (path.parent/'result.json').is_file():
        result_path = path.parent/'result.json'
        if result_path.is_symlink() or not result_path.resolve().is_relative_to(root):
            raise ValueError('result metadata escapes approved root')
        result = dictionary(read_json(result_path))
    return run, result


def identity(run, result, row):
    server = dictionary(run.get('server'))
    props = dictionary(server.get('props'))
    served = dictionary(result.get('served_model'))
    config = dictionary(result.get('config'))
    args = config.get('model_args', {})
    if isinstance(args, str):
        args = dict(part.split('=', 1) for part in args.split(',') if '=' in part)
    args = dictionary(args)
    candidates = [('run.server.model_id', server.get('model_id')),
                  ('result.served_model', served.get('alias') or served.get('id') or served.get('path')),
                  ('response.model', row.get('model_id') or row.get('model')),
                  ('recorded model arguments', args.get('model') or args.get('pretrained')),
                  ('recorded requested model', run.get('model_id') or run.get('model') or run.get('backend_model') or result.get('backend_model'))]
    model, provenance = 'unknown', 'not recorded'
    for label, value in candidates:
        if isinstance(value, str) and value:
            model, provenance = value, label
            break
    return dict(model_id=model, model_id_source=provenance,
                model_alias=props.get('model_alias') or served.get('alias'),
                build_info=props.get('build_info') or served.get('build'),
                identity_changed=served.get('changed_during_run'))


def settings_for(run, result, row):
    config = dictionary(result.get('config'))
    sources = {'run': parameters(run), 'result.gen_kwargs': parameters(config.get('gen_kwargs')),
               'run.settings': parameters(run.get('settings')), 'response': parameters(row)}
    for key in ('settings', 'params', 'parameters', 'gen_kwargs'):
        sources['response.'+key] = parameters(row.get(key))
    return {label: values for label, values in sources.items() if values}


def strings(value):
    """lm_eval generations are nested lists; keep all generations, once."""
    if isinstance(value, (str, dict)):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif value is not None:
        raise ValueError('unsupported generation value')


def channels(value):
    if isinstance(value, str):
        if value.lstrip().startswith('<think>'):
            final = '</think>' in value and bool(value.split('</think>', 1)[1].strip())
            return value if final else '', '' if final else value, final, {}, None
        return value, '', bool(value.strip()), {}, None
    if value is not None and (not isinstance(value, dict) or not any(key in value for key in
            ('choices', 'message', 'content', 'text', 'reasoning_content', 'reasoning'))):
        raise ValueError('unsupported structured response')
    data = dictionary(value)
    choices = data.get('choices')
    choice = dictionary(choices[0]) if isinstance(choices, list) and choices else data
    message = dictionary(choice.get('message')) or choice
    answer = text_content(message.get('content', message.get('text', '')))
    reasoning = text_content(message.get('reasoning_content', message.get('reasoning', '')))
    return answer, reasoning, bool(answer.strip()), dictionary(data.get('usage')), choice.get('finish_reason')


def prompt_chars(value):
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(prompt_chars(item) for item in value)
    if isinstance(value, dict):
        return len(text_content(value.get('content', value.get('text', ''))))
    return 0


def response_record(path, root, kind, index, value, row, run, result, prompt=None):
    answer, reasoning, final, usage, finish = channels(value)
    settings = settings_for(run, result, row)
    cap = None
    for values in settings.values():
        for key in ('max_gen_toks', 'n_predict', 'max_tokens', 'max_completion_tokens'):
            if key in values:
                try:
                    candidate = int(values[key])
                    if candidate > 0:
                        cap = candidate
                except (ValueError, TypeError):
                    pass
    row_usage = dictionary(row.get('usage'))
    completion = usage.get('completion_tokens', row_usage.get('completion_tokens', row.get('generated_tokens')))
    finish = finish or row.get('finish_reason')
    capped = finish == 'length' or (cap is not None and isinstance(completion, (int, float)) and completion >= cap)
    recorded_prompt = usage.get('prompt_tokens', row_usage.get('prompt_tokens'))
    return dict(source=kind, source_file=str(path.relative_to(root)), response_index=str(index),
                **identity(run, result, row), run_id=run.get('run', run.get('run_id', path.parent.name)),
                timestamp=row.get('timestamp', run.get('created_utc', run.get('started_at',
                           result.get('started_at', result.get('date'))))),
                estimated_prompt_tokens=math.ceil(prompt_chars(prompt)/3.5) if prompt is not None else None,
                recorded_prompt_tokens=recorded_prompt, settings=settings, token_cap=cap,
                completion_tokens=completion, finish_reason=finish,
                cap_evidence_available=finish is not None or (cap is not None and completion is not None),
                cap_exhausted=bool(capped and not final), answer=answer, reasoning=reasoning)


def lm_eval_records(path, root):
    run, result = metadata(path, root, 'lm-eval')
    with path.open() as source:
        for line_number, line in enumerate(source, 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not any(key in row for key in ('resps', 'filtered_resps')):
                raise ValueError('unsupported lm_eval sample')
            # Raw generations take precedence, even when empty. Never scan a
            # parsed/extracted duplicate as a second independent generation.
            raw = row['resps'] if 'resps' in row else row['filtered_resps']
            for generation, value in enumerate(strings(raw)):
                yield response_record(path, root, 'lm-eval', f'{line_number}:{generation}', value,
                                      row, run, result, row.get('arguments', row.get('prompt')))


def cse_records(path, root):
    run, result = metadata(path, root, 'cse')
    data = read_json(path)
    if not isinstance(data, list):
        raise ValueError('unsupported CyberSecEval response container')
    for index, row in enumerate(data):
        if not isinstance(row, dict):
            raise ValueError('unsupported CyberSecEval row')
        prompt = next((row[key] for key in ('test_case_prompt', 'prompt', 'mutated_prompt', 'question') if key in row), None)
        if any(key in row for key in RESPONSE_KEYS):
            key = next(key for key in RESPONSE_KEYS if key in row)
            yield response_record(path, root, 'cse', index, row[key], row, run, result, prompt)
        elif 'operation_log' in row:
            parts = re.split(r'(>>> (?:USER|AI): )', row['operation_log'])
            history = ''
            for i in range(1, len(parts), 2):
                body = parts[i+1] if i+1 < len(parts) else ''
                if parts[i] == '>>> AI: ':
                    yield response_record(path, root, 'cse', f'{index}:operation:{i}', body, row, run, result, history)
                history += body
        elif 'dialogue_history' in row:
            parts = re.split(r'(?:/n)?(Attacker|Victim): ', row['dialogue_history'])
            history = ''
            for i in range(1, len(parts), 2):
                body = parts[i+1] if i+1 < len(parts) else ''
                # Do not attribute the victim's words to the attacker model.
                turn = dict(row, model=row.get(parts[i].lower()+'_model', 'unknown'))
                record = response_record(path, root, 'cse', f'{index}:{parts[i]}:{i}', body, turn, run, result, history)
                record.update(model_id=turn['model'], model_id_source='recorded dialogue speaker model',
                              model_alias=None, build_info=None)
                yield record
                history += body
        else:
            raise ValueError('unsupported CyberSecEval response fields')


def cse_usage_summary(root):
    """Count authoritative finish reasons; never positionally join model calls.

    The producer records no response IDs and includes judge/retry calls.
    These counts therefore have a different denominator from responses.json.
    """
    by_model, by_month, reasons = {}, {}, Counter()
    files = calls = length = missing = 0
    for path in sorted(root.rglob('usage.jsonl')):
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError('usage metadata escapes approved root')
        files += 1
        run, result = metadata(path, root, 'cse')
        stamp = run.get('started_at', result.get('started_at'))
        with path.open() as source:
            for line in source:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError('unsupported CSE usage row')
                calls += 1
                reason = row.get('finish_reason')
                exhausted = reason == 'length'
                length += exhausted
                missing += reason is None
                reasons[str(reason) if reason is not None else 'not recorded'] += 1
                model = row.get('model') if isinstance(row.get('model'), str) else 'unknown'
                for table, key in ((by_model, model), (by_month, month(row.get('timestamp', stamp)))):
                    counts = table.setdefault(key, Counter())
                    counts['calls'] += 1
                    counts['cap_exhausted'] += exhausted
    return dict(files=files, calls=calls, cap_exhausted=length, missing_finish_reason=missing,
                by_model=by_model, by_month=by_month, finish_reasons=reasons)


_UNREAD = object()

def deep_research_records(path, root, data=_UNREAD):
    if data is _UNREAD:
        data = read_json(path)
    if not isinstance(data, dict) or not isinstance(data.get('ui_events'), list):
        raise ValueError('unsupported deep-research session (expected ui_events)')
    run = dict(data, run=data.get('session_id', path.stem), created_utc=data.get('timestamp'))
    events = data['ui_events']
    history, pending = 0, {}
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError('unsupported deep-research event')
        text = text_content(dictionary(event.get('data')).get('text'))
        kind, source = event.get('type'), event.get('source', 'unknown')
        if kind == 'reasoning':
            old = pending.get(source)
            if old:
                yield old
            record = response_record(path, root, 'deep-research', index,
                                     dict(content='', reasoning_content=text), event, run, {}, None)
            record['estimated_prompt_tokens'] = math.ceil(history/3.5)
            record['prompt_estimate_basis'] = 'UI event prefix; actual agent request history not recorded'
            record['agent_source'] = source
            pending[source] = record
        elif kind == 'text' and source != 'User':
            record = response_record(path, root, 'deep-research', index, text, event, run, {}, None)
            record['estimated_prompt_tokens'] = math.ceil(history/3.5)
            record['prompt_estimate_basis'] = 'UI event prefix; actual agent request history not recorded'
            record['agent_source'] = source
            if source in pending:
                record['reasoning'] = pending.pop(source)['reasoning']
            yield record
        history += len(text)
    yield from pending.values()


ADAPTERS = {'lm-eval': ('samples_*.jsonl', lm_eval_records),
            'cse': ('responses.json', cse_records),
            'deep-research': ('session_*.json', deep_research_records)}


def scan_transcripts(root, output, kind):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError('transcript root does not exist')
    pattern, adapter = ADAPTERS[kind]
    paths = sorted(path for path in root.rglob(pattern) if not path.is_relative_to(output))
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.stat().st_mode & 0o077 or any((output/name).exists() for name in ('hits.jsonl', 'summary.md', 'unreadable.jsonl', 'usage-summary.json')):
        raise ValueError('output must be private and reports must not exist')
    tables = {'By model': {}, 'By month (UTC)': {}, 'By estimated prompt size': {}}
    usage_summary = cse_usage_summary(root) if kind == 'cse' else None
    unreadable = []
    flags_count = Counter()
    total = flagged = degeneration = capped = missing_caps = unknown_models = 0
    published = []
    fd, temporary = tempfile.mkstemp(prefix='.hits-', dir=output)
    try:
        with os.fdopen(fd, 'w') as hits:
            for path in paths:
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('transcript symlink escapes approved root')
                if kind == 'deep-research':
                    try:
                        data = read_json(path)
                    except json.JSONDecodeError:
                        unreadable.append(dict(source_file=str(path.relative_to(root)), exception_class='JSONDecodeError'))
                        continue
                    records = deep_research_records(path, root, data)
                else:
                    records = adapter(path, root)
                for record in records:
                    total += 1
                    flags, details, excerpts = set(), {}, []
                    for channel in ('answer', 'reasoning'):
                        found, checks, offset, excerpt = detect_text(record[channel])
                        flags.update(found)
                        if found:
                            details[channel] = dict(flags=found, repetition_checks=checks)
                            excerpts.append((channel, offset, excerpt))
                    if record['cap_exhausted']:
                        flags.add('cap-exhausted')
                    cap_only = bool(flags) and flags == {'cap-exhausted'}
                    noncap = bool(flags - {'cap-exhausted'})
                    flagged += bool(flags)
                    degeneration += noncap
                    capped += record['cap_exhausted']
                    missing_caps += not record['cap_evidence_available']
                    unknown_models += record['model_id'] == 'unknown'
                    for title, key in (('By model', record['model_id']), ('By month (UTC)', month(record['timestamp'])),
                                       ('By estimated prompt size', bucket(record['estimated_prompt_tokens']))):
                        counts = tables[title].setdefault(key, Counter())
                        counts['responses'] += 1
                        counts['degeneration'] += noncap
                        counts['cap_exhausted'] += record['cap_exhausted']
                    if not flags:
                        continue
                    flags_count.update(flags)
                    if excerpts:
                        channel, offset, excerpt = excerpts[0]
                    else:
                        channel = 'reasoning' if record['reasoning'] else 'answer'
                        offset = max(0, len(record[channel])-400)
                        excerpt = record[channel][offset:offset+400]
                    item = {key: value for key, value in record.items() if key not in ('answer', 'reasoning')}
                    item.update(flags=sorted(flags), details=details, cap_only=cap_only,
                                excerpt_channel=channel, excerpt_offset=offset, excerpt=excerpt)
                    hits.write(json.dumps(item, ensure_ascii=False, sort_keys=True)+'\n')
            hits.flush()
            os.fsync(hits.fileno())
        lines = ['# Transcript loop scan', '', f'Source: {kind}. Files: {len(paths)}. Responses: {total}.',
                 f'Flagged responses: {flagged}. Degeneration candidates: {degeneration}. Cap-exhausted (separate): {capped}.',
                 'Coverage: saved transcript files only.' if paths else 'Coverage: no saved transcript files; no responses evaluated. This is not evidence that loops did not occur.',
                 f'Unknown model identity: {unknown_models}. Responses without cap evidence: {missing_caps}.',
                 f'Unreadable session files (invalid JSON at scan time): {len(unreadable)}. Their responses are not evaluated.', '',
                 'Mechanical flags are candidates, not confirmed semantic loops. Cap exhaustion alone is not looping.',
                 'Only recorded identities/settings are used. Missing token/finish metadata cannot establish cap exhaustion.',
                 'Prompt sizes use available prompt text, chars/3.5; deep-research estimates use the UI prefix, not reconstructed per-agent requests.', '']
        for title, table in tables.items():
            lines += [f'## {title}', '', '| Group | Responses | Degeneration candidates | Cap-exhausted |', '| --- | ---: | ---: | ---: |']
            lines += [f"| {markdown(key)} | {counts['responses']} | {counts['degeneration']} | {counts['cap_exhausted']} |"
                      for key, counts in sorted(table.items())]
            lines += ['']
        lines += ['## Flags', '', '| Flag | Responses |', '| --- | ---: |']
        lines += [f'| {flag} | {count} |' for flag, count in sorted(flags_count.items())]
        if usage_summary is not None:
            lines += ['', '## CSE usage finish reasons', '',
                      f"Usage files: {usage_summary['files']}. Logged calls: {usage_summary['calls']}. "
                      f"Cap-exhausted calls (finish_reason=length): {usage_summary['cap_exhausted']}. "
                      f"Missing finish_reason: {usage_summary['missing_finish_reason']}.", '',
                      'Usage includes model/judge/retry calls and has no response ID. No positional join to transcripts is made; length calls may have a partial final answer.', '']
            for title, table in (('By recorded request model', usage_summary['by_model']),
                                 ('By usage month (UTC)', usage_summary['by_month'])):
                lines += [f'### {title}', '', '| Group | Logged calls | Cap-exhausted calls |', '| --- | ---: | ---: |']
                lines += [f"| {markdown(key)} | {counts['calls']} | {counts['cap_exhausted']} |" for key, counts in sorted(table.items())]
                lines += ['']
            lines += ['| finish_reason | Calls |', '| --- | ---: |']
            lines += [f'| {markdown(key)} | {count} |' for key, count in sorted(usage_summary['finish_reasons'].items())]
        lines += ['', 'hits.jsonl contains bounded excerpts and recorded settings. Keep it on the source host; return only counts and explicitly approved excerpts.', '']
        os.link(temporary, output/'hits.jsonl')
        published.append(output/'hits.jsonl')
        descriptor = os.open(output/'summary.md', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        published.append(output/'summary.md')
        with os.fdopen(descriptor, 'w') as summary:
            summary.write('\n'.join(lines))
        if unreadable:
            descriptor = os.open(output/'unreadable.jsonl', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            published.append(output/'unreadable.jsonl')
            with os.fdopen(descriptor, 'w') as audit:
                for item in unreadable:
                    audit.write(json.dumps(item, sort_keys=True)+'\n')
        if usage_summary is not None:
            descriptor = os.open(output/'usage-summary.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            published.append(output/'usage-summary.json')
            with os.fdopen(descriptor, 'w') as audit:
                json.dump(usage_summary, audit, sort_keys=True, indent=2)
                audit.write('\n')
    except BaseException:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        Path(temporary).unlink(missing_ok=True)
    return dict(files=len(paths), responses=total, hits=flagged, degeneration=degeneration, cap_exhausted=capped,
                unreadable_files=len(unreadable), usage_cap_exhausted=usage_summary['cap_exhausted'] if usage_summary else None)
