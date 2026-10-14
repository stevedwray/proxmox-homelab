"""Private, stdlib-only reader for local VS Code Copilot session storage."""
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from scan_openwebui import detect_text, markdown, month, text_content


def load_session(path):
    """Replay VS Code's installed ObjectMutationLog protocol (kinds 0–3).

    Verified against the local workbench.desktop.main.js implementation:
    0 snapshot, 1 set, 2 truncate/append array, 3 unset. A partially written
    last journal line is ignored and reported; other errors are not hidden.
    """
    path = Path(path)
    if path.suffix != '.jsonl':
        with path.open() as source:
            return json.load(source), False
    state, partial = None, False
    with path.open() as source:
        for line in source:
            if not line.strip():
                continue
            try:
                op = json.loads(line)
            except json.JSONDecodeError:
                if not line.endswith('\n') and source.read() == '':
                    partial = True
                    break
                raise
            if not isinstance(op, dict):
                raise ValueError('journal operation is not an object')
            kind = op.get('kind')
            if kind == 0:
                state = op['v']
                continue
            if kind not in (1, 2, 3) or state is None:
                raise ValueError('unknown journal operation or missing snapshot')
            keys = op.get('k')
            if not isinstance(keys, list):
                raise ValueError('journal operation path is not an array')
            if not keys:
                continue
            parent = state
            for key in keys[:-1]:
                parent = parent[key]
            key = keys[-1]
            if kind == 1:
                parent[key] = op['v']
            elif kind == 3:
                if isinstance(parent, dict):
                    parent.pop(key, None)
                else:
                    parent[key] = None
            else:
                values = parent.get(key) if isinstance(parent, dict) else parent[key]
                values = values or []
                if not isinstance(values, list):
                    raise ValueError('journal append target is not an array')
                if 'i' in op:
                    index = op['i']
                    if not isinstance(index, int) or index < 0:
                        raise ValueError('invalid journal truncation index')
                    values = values[:index] + [None]*max(0, index-len(values))
                values.extend(op.get('v') or [])
                parent[key] = values
    if not isinstance(state, dict):
        raise ValueError('session snapshot is not an object')
    return state, partial


FLAG_FIELDS = ('toolCalling', 'supportsToolCalling', 'thinking', 'enableThinking',
               'supportsThinking', 'reasoning', 'reasoningEffort', 'reasoningFormat')
SECRET_FIELDS = {'apikey', 'api_key', 'authorization', 'access_token', 'password', 'secret', 'token'}


def secret_values(value):
    found = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in SECRET_FIELDS and isinstance(child, str) and child:
                found.add(child)
            else:
                found.update(secret_values(child))
    elif isinstance(value, list):
        for child in value:
            found.update(secret_values(child))
    return found


def redact(text, secrets):
    for secret in sorted(secrets, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = re.sub(r'(?i)(authorization\s*[:=]\s*[\"\']?\s*bearer\s+)[^\s\"\'<>]+', r'\1[REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{16,}\b', '[REDACTED]', text)
    text = re.sub(r'(?i)([\"\']?(?:api[_-]?key|access_token)[\"\']?\s*[:=]\s*[\"\'])([^\"\'\n]+)', r'\1[REDACTED]', text)
    return text


def private_json(path, value, lines=False):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as target:
        if lines:
            for row in value:
                target.write(json.dumps(row, ensure_ascii=False, sort_keys=True)+'\n')
        else:
            json.dump(value, target, ensure_ascii=False, sort_keys=True, indent=2)
            target.write('\n')


def config_models(path):
    """Return only allowed client fields; credentials stay in memory for redaction."""
    with Path(path).open() as source:
        data = json.load(source)
    secrets = secret_values(data)
    providers = data if isinstance(data, list) else data.get('providers', [])
    rows = []
    for provider in providers:
        if not isinstance(provider, dict):
            raise ValueError('unsupported client provider')
        for model in provider.get('models', []):
            if not isinstance(model, dict):
                raise ValueError('unsupported configured model')
            url = model.get('url', provider.get('url'))
            if not isinstance(url, str):
                continue
            parts = urlsplit(url)
            framework = ('framework' in (parts.hostname or '').lower()
                         or 'framework' in str(provider.get('name', '')).lower()
                         or 'framework' in str(model.get('name', '')).lower())
            if not framework:
                continue
            host = parts.hostname or ''
            if ':' in host:
                host = '['+host+']'
            if parts.port:
                host += ':'+str(parts.port)
            clean_url = urlunsplit((parts.scheme, host, parts.path, '', ''))
            flags = {key: model[key] for key in FLAG_FIELDS if key in model and isinstance(model[key], (str, int, float, bool, type(None)))}
            options = model.get('modelOptions', {})
            if isinstance(options, dict):
                for key in FLAG_FIELDS:
                    if key in options and isinstance(options[key], (str, int, float, bool, type(None))):
                        flags['modelOptions.'+key] = options[key]
            row = dict(model_id=redact(str(model.get('id', 'unknown')), secrets),
                       url=redact(clean_url, secrets), maxInputTokens=model.get('maxInputTokens'),
                       maxOutputTokens=model.get('maxOutputTokens'), flags=flags)
            # Enforce an allowlist, including types, rather than copying config.
            for key in ('maxInputTokens', 'maxOutputTokens'):
                if not isinstance(row[key], int):
                    row[key] = None
            row['flags'] = {key: redact(value, secrets) if isinstance(value, str) else value for key, value in flags.items()}
            rows.append(row)
    return rows, secrets


def saved_text(value):
    """VS Code MarkdownString, text fragments and thinking deltas."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(saved_text(item) for item in value)
    if isinstance(value, dict):
        return saved_text(value.get('value', value.get('text', '')))
    return ''


def response_parts(request):
    response = request.get('response', [])
    if isinstance(response, str):
        return response, '', []
    if not isinstance(response, list):
        raise ValueError('unsupported response parts')
    answer, thinking, tools = [], [], []
    for part in response:
        if isinstance(part, str):
            answer.append(part)
        elif isinstance(part, dict):
            kind = part.get('kind')
            if kind == 'thinking':
                value = part.get('value', part.get('content', ''))
                thinking.append(saved_text(value))
            elif kind in ('toolInvocationSerialized', 'toolInvocation'):
                tools.append(part)
            elif kind == 'markdownContent':
                answer.append(saved_text(part.get('content')))
            elif kind is None and isinstance(part.get('value'), str):
                answer.append(part['value'])
    return '\n'.join(answer), '\n'.join(thinking), tools


def tool_arguments(part):
    for field in ('arguments', 'parameters', 'input'):
        if field in part:
            value = part[field]
            if isinstance(value, str):
                try:
                    return json.loads(value), True, False
                except ValueError:
                    return None, True, True
            return value, True, False
    specific = part.get('toolSpecificData', {})
    if isinstance(specific, dict) and specific.get('kind') == 'terminal':
        command = specific.get('commandLine')
        if isinstance(command, dict) and isinstance(command.get('original'), str):
            return dict(command=command['original']), True, False
    return None, False, False


def content_tool_checks(text):
    """Check explicit leaked tool-call envelopes, not arbitrary prose/code JSON."""
    flags, locations = set(), []
    starts = list(re.finditer(r'<tool_call>', text))
    for start in starts:
        end = text.find('</tool_call>', start.end())
        locations.append(start.start())
        flags.add('tool-call-in-content')
        try:
            if end < 0:
                raise ValueError('unclosed tool envelope')
            payload = json.loads(text[start.end():end])
            if not isinstance(payload, dict):
                raise ValueError('tool payload is not an object')
            function = payload.get('function', payload)
            if not isinstance(function, dict) or not isinstance(function.get('name'), str):
                raise ValueError('missing tool name')
            if isinstance(function.get('arguments'), str):
                json.loads(function['arguments'])
        except ValueError:
            flags.add('tool-malformed')
    return flags, min(locations, default=0)


def model_for(request):
    value = request.get('modelId')
    if isinstance(value, str) and value:
        return value, 'request.modelId'
    return 'unknown', 'not recorded per request'


def session_paths(root):
    paths = []
    workspace = root/'workspaceStorage'
    if workspace.is_dir():
        paths += list(workspace.glob('*/chatSessions/*.json')) + list(workspace.glob('*/chatSessions/*.jsonl'))
    empty = root/'globalStorage'/'emptyWindowChatSessions'
    if empty.is_dir():
        paths += list(empty.glob('*.json')) + list(empty.glob('*.jsonl'))
    # A journal supersedes the same session's old JSON snapshot, not another session.
    chosen = {}
    for path in paths:
        key = (path.parent, path.stem)
        if key not in chosen or path.suffix == '.jsonl':
            chosen[key] = path
    return sorted(chosen.values())


def cutoff(request):
    result = request.get('result') or {}
    error = result.get('errorDetails') or {} if isinstance(result, dict) else {}
    return bool(request.get('isCanceled') is True or request.get('finish_reason') == 'length'
                or (isinstance(error, dict) and error.get('responseIsIncomplete') is True))


def scan_copilot(root, output, progress=100):
    root, output = Path(root).resolve(), Path(output).resolve()
    if not root.is_dir():
        raise ValueError('VS Code User directory missing')
    paths = session_paths(root)
    if not paths:
        raise ValueError('no local Copilot session files')
    limits, secrets = config_models(root/'chatLanguageModels.json')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    if output.stat().st_mode & 0o077:
        raise ValueError('output directory must be private')
    by_model, by_month, flag_counts = {}, {}, Counter()
    unreadable, hits = [], []
    sessions = responses = requests_count = partials = unknown_tools = tools_count = 0
    tool_repeat_hits = 0
    for file_index, path in enumerate(paths, 1):
        if progress and file_index % progress == 0:
            print(f'COPILOT-PROGRESS: {file_index}/{len(paths)} files; {responses} responses; {len(hits)} candidates', file=sys.stderr, flush=True)
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            unreadable.append(dict(source_hash=hashlib.sha256(str(path).encode()).hexdigest(), reason='source symlink'))
            continue
        try:
            data, partial = load_session(path)
            requests = data.get('requests', [])
            if not isinstance(requests, list) or not all(isinstance(item, dict) for item in requests):
                raise ValueError('unsupported request list')
            decoded = [response_parts(item) for item in requests]
        except (ValueError, KeyError, TypeError, IndexError, OSError):
            unreadable.append(dict(source_hash=hashlib.sha256(str(path).encode()).hexdigest(), reason='unreadable session/schema'))
            continue
        sessions += 1
        partials += partial
        requests_count += len(requests)
        relative = path.relative_to(root)
        workspace_key = relative.parts[1] if relative.parts[0] == 'workspaceStorage' else 'empty-window'
        workspace_hash = hashlib.sha256(workspace_key.encode()).hexdigest()
        source_hash = hashlib.sha256(str(relative).encode()).hexdigest()
        history_chars = 0
        previous_tool, streak = None, 0
        for index, (request, decoded_response) in enumerate(zip(requests, decoded)):
            answer, thinking, tools = decoded_response
            history_chars += len(text_content(request.get('message', {}).get('text') if isinstance(request.get('message'), dict) else request.get('message')))
            prompt_tokens = math.ceil(history_chars/3.5)
            model, model_source = model_for(request)
            model = redact(model, secrets)
            stamp = request.get('responseTimestamp', request.get('timestamp', data.get('creationDate')))
            has_response = bool(answer or thinking or tools or request.get('result'))
            if not has_response:
                continue
            responses += 1
            flags, details, excerpts = set(), {}, []
            for channel, text in (('answer', answer), ('reasoning', thinking)):
                found, checks, offset, excerpt = detect_text(text)
                # Keep compression-only reasoning informational as ctx-bugs does.
                if channel == 'reasoning' and checks == ['zlib'] and 'loop' not in found:
                    found = [flag for flag in found if flag != 'repetition']
                    found.append('dense-reasoning')
                flags.update(found)
                if found:
                    details[channel] = dict(flags=found, repetition_checks=checks)
                    if any(flag != 'dense-reasoning' for flag in found):
                        excerpts.append((channel, offset, excerpt))
            if re.search(r'^\s*(?:analysis|reasoning)\s*:', answer, re.I):
                flags.add('template-leak')
                details['reasoning-in-content'] = 'explicit analysis/reasoning label (heuristic)'
                excerpts.append(('answer', 0, answer[:400]))
            raw_flags, offset = content_tool_checks(answer)
            flags.update(raw_flags)
            if raw_flags:
                excerpts.append(('answer', offset, answer[max(0, offset-80):offset+320]))
            if cutoff(request):
                flags.add('cut-off')
            for part in tools:
                tools_count += 1
                arguments, available, malformed = tool_arguments(part)
                if malformed:
                    flags.add('tool-malformed')
                if not available or malformed:
                    unknown_tools += 1
                    previous_tool, streak = None, 0
                    continue
                name = part.get('toolId', part.get('name', 'unknown'))
                signature = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False))
                streak = streak+1 if signature == previous_tool else 1
                previous_tool = signature
                if streak >= 3:
                    flags.add('tool-repeat')
                    details['tool-repeat'] = dict(tool_name=redact(str(name), secrets), consecutive=streak,
                                                  arguments_sha256=hashlib.sha256(signature[1].encode()).hexdigest())
                    message = part.get('invocationMessage', '')
                    message = message.get('value', '') if isinstance(message, dict) else message
                    excerpts.append(('tool', 0, str(message)[:400]))
            if not tools:
                previous_tool, streak = None, 0
            # Dense reasoning alone is not a replay candidate.
            candidate_flags = flags - {'dense-reasoning'}
            for table, key in ((by_model, model), (by_month, month(stamp))):
                group = table.setdefault(key, Counter())
                group['responses'] += 1
                group['candidates'] += bool(candidate_flags)
            flag_counts.update(flags)
            tool_repeat_hits += 'tool-repeat' in flags
            if candidate_flags:
                channel, offset, excerpt = excerpts[0] if excerpts else ('answer', max(0,len(answer)-400), answer[-400:])
                hits.append(dict(source_hash=source_hash, session_id=redact(str(data.get('sessionId',path.stem)), secrets),
                    workspace_hash=workspace_hash, request_index=index, request_count=len(requests),
                    model_id=model, model_id_source=model_source, timestamp=stamp,
                    estimated_history_tokens=prompt_tokens, recorded_prompt_tokens=request.get('promptTokens'),
                    completion_tokens=request.get('completionTokens'), partial_journal=partial,
                    flags=sorted(flags), details=details, excerpt_channel=channel, excerpt_offset=offset,
                    excerpt=redact(excerpt,secrets)[:400]))
            history_chars += len(answer)  # Never feed reasoning into history estimates.
    findings=[]
    for model in limits:
        name=model['model_id'].lower()
        reasoning = any(token in name for token in ('qwen3.8-flash','qwen38-flash','glm-5.3','glm5')) or any(
            value not in (None, False, 0, '', 'off', 'false', 'disabled', 'none') for key,value in model['flags'].items() if 'thinking' in key.lower() or 'reasoning' in key.lower())
        limit=model['maxOutputTokens']
        if reasoning and isinstance(limit,int) and 0 < limit < 16384:
            findings.append(dict(kind='FND-client-limits',model_id=model['model_id'],maxOutputTokens=limit,
                                 basis='Below 16384-token ctx-bug-test reasoning budget; candidate budget pressure, not proof of a loop cause'))
    counts=dict(files=len(paths),sessions=sessions,requests=requests_count,responses=responses,candidates=len(hits),
                unreadable_files=len(unreadable),partial_journals=partials,tools=tools_count,
                tools_without_arguments=unknown_tools,tool_repeat_responses=tool_repeat_hits,
                by_model=by_model,by_month=by_month,flags=flag_counts)
    private_json(output/'hits.jsonl', hits, lines=True)
    private_json(output/'client-limits.json',dict(models=limits,findings=findings))
    private_json(output/'summary.json',counts)
    private_json(output/'unreadable.jsonl',unreadable,lines=True)
    lines=['# Local Copilot scan','',f'Files: {len(paths)}. Readable sessions: {sessions}. Responses: {responses}. Candidates: {len(hits)}.',
           f'Unreadable files: {len(unreadable)}. Partial journals: {partials}.',
           f'Tool invocations: {tools_count}; without parseable stored arguments: {unknown_tools}.', '',
           'Mechanical candidates, not confirmed engine bugs. Dense reasoning alone is informational.',
           'Tool-repeat requires identical recorded arguments, not matching display messages. Missing arguments limit coverage.',
           'Cut-off includes recorded cancellation/incomplete errors; user cancellations are not themselves bugs.',
           'History sizes are chars/3.5 of saved user/answer text only; system prompts and tool schemas are not reconstructed.', '']
    for title,table in (('By model',by_model),('By month (UTC)',by_month)):
        lines += [f'## {title}','','| Group | Responses | Candidates |','| --- | ---: | ---: |']
        lines += [f"| {markdown(key)} | {value['responses']} | {value['candidates']} |" for key,value in sorted(table.items())]
        lines += ['']
    lines += ['## Flags','','| Flag | Responses |','| --- | ---: |']
    lines += [f'| {flag} | {count} |' for flag,count in sorted(flag_counts.items())]
    descriptor=os.open(output/'summary.md',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as target:target.write('\n'.join(lines)+'\n')
    return counts
