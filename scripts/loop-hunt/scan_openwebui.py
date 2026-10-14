#!/usr/bin/env python3
"""Scan an Open WebUI snapshot; print no chats or excerpts to stdout."""
import argparse
from collections import Counter
import contextlib
import datetime as dt
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import tempfile

from snapshot_sqlite import read_only


def load_detectors():
    here = Path(__file__).resolve().parent
    path = here / 'detectors.py'  # The plan copies this alongside the scanner.
    if not path.exists():
        path = here.parent / 'framework-ctx-bugs' / 'detectors.py'
    spec = importlib.util.spec_from_file_location('loop_hunt_detectors', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


detectors = load_detectors()
MARKERS = ('〈|', '<|im_end|>', '<|im_start|>', '<think>', '</think>')


def text_content(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return '\n'.join(item['text'] for item in value
                         if isinstance(item, dict) and isinstance(item.get('text'), str))
    return ''


def detect_text(text):
    flags, positions = [], []
    if detectors.loop(text):
        flags.append('loop')
        match = re.search(r'(.{50,}?)\1\1', text[-2000:], re.S)
        positions.append(max(0, len(text)-2000) + match.start())
    checks = detectors.repetition(text)
    if checks:
        flags.append('repetition')
        tokens = list(re.finditer(r"\b[\w'-]+\b", text))
        seen = Counter()
        for i in range(len(tokens)-7):
            shingle = tuple(token.group().lower() for token in tokens[i:i+8])
            seen[shingle] += 1
            if seen[shingle] == 4:
                positions.append(tokens[i].start())
                break
        else:
            positions.append(max(0, len(text)-400))
    for marker in MARKERS:
        offset = text.find(marker)
        if offset >= 0:
            flags.append('template-leak')
            if marker == '〈|':
                flags.append('hidden-token-string')
            positions.append(offset)
    offset = max(0, min(positions, default=0)-100)
    return sorted(set(flags)), checks, offset, text[offset:offset+400]


def month(value):
    try:
        if isinstance(value, (int, float)):
            return dt.datetime.fromtimestamp(value / 1000 if value > 100_000_000_000 else value,
                                             dt.timezone.utc).strftime('%Y-%m')
        if isinstance(value, str):
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            return parsed.replace(tzinfo=parsed.tzinfo or dt.timezone.utc).astimezone(dt.timezone.utc).strftime('%Y-%m')
    except (ValueError, OverflowError, OSError):
        pass
    return 'unknown'


def bucket(count):
    if count is None:
        return 'unknown (broken history link)'
    for limit, label in ((32768, '<32k'), (65536, '32k–64k'), (98304, '64k–96k'),
                         (131072, '96k–131k'), (262144, '131k–262k')):
        if count < limit:
            return label
    return '>=262k'


def messages(chat):
    history = chat.get('history')
    if isinstance(history, dict) and isinstance(history.get('messages'), dict) and history['messages']:
        raw = history['messages']
        if not all(isinstance(message, dict) for message in raw.values()):
            raise ValueError('unsupported history message structure')
        # All branches, once each. The flat list often duplicates the active path.
        return list(raw.items()), True
    flat = chat.get('messages', [])
    if not isinstance(flat, list) or not all(isinstance(message, dict) for message in flat):
        raise ValueError('unsupported flat message structure')
    return [(str(i), message) for i, message in enumerate(flat)], False


def history_chars(items, key, graph):
    if not graph:
        index = next(i for i, (name, _) in enumerate(items) if name == key)
        return sum(len(text_content(message.get('content'))) for _, message in items[:index+1])
    by_id, seen, count = dict(items), set(), 0
    while key is not None:
        if key in seen or key not in by_id:
            return None
        seen.add(key)
        message = by_id[key]
        count += len(text_content(message.get('content')))
        key = message.get('parentId')
    return count


def stored_parameters(chat, message):
    # Preserve provenance instead of guessing effective sampling defaults.
    result = {}
    for label, source in (('chat', chat), ('message', message)):
        for field in ('params', 'parameters'):
            if field in source:
                result.setdefault(label, {})[field] = source[field]
    return result


def model_id(chat, message):
    value = message.get('model') or chat.get('model')
    if not value and isinstance(chat.get('models'), list) and len(chat['models']) == 1:
        value = chat['models'][0]
    if isinstance(value, dict):
        value = value.get('id')
    return value if isinstance(value, str) and value else 'unknown'


def markdown(value):
    return str(value).replace('\n', ' ').replace('\r', ' ').replace('|', '\\|').replace('`', "'")


def scan(database, output):
    database, output = Path(database), Path(output)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if output.stat().st_mode & 0o077:
        raise ValueError('output directory must have mode 0700')
    if any((output / name).exists() for name in ('hits.jsonl', 'summary.md')):
        raise FileExistsError('scan outputs already exist; use a new output directory')
    by_model, by_month, by_bucket = {}, {}, {}
    flag_counts = Counter()
    total_chats = total_messages = total_hits = broken_histories = 0
    fd, name = tempfile.mkstemp(prefix='.hits-', dir=output)
    temporary = Path(name)
    published = []
    try:
        with os.fdopen(fd, 'w') as hits, contextlib.closing(read_only(database)) as connection:
            columns = {row[1] for row in connection.execute('PRAGMA table_info(chat)')}
            if not {'id', 'chat'} <= columns:
                raise ValueError('unsupported Open WebUI chat table (requires id and chat)')
            date_column = 'created_at' if 'created_at' in columns else 'NULL'
            for chat_id, serialized, created_at in connection.execute(f'SELECT id, chat, {date_column} FROM chat ORDER BY id'):
                total_chats += 1
                try:
                    chat = json.loads(serialized)
                except (TypeError, ValueError):
                    raise ValueError('invalid chat JSON; scan incomplete') from None
                if not isinstance(chat, dict):
                    raise ValueError('unsupported chat JSON structure')
                items, graph = messages(chat)
                for index, (key, message) in enumerate(items):
                    if message.get('role') != 'assistant':
                        continue
                    total_messages += 1
                    length = history_chars(items, key, graph)
                    tokens = math.ceil(length / 3.5) if length is not None else None
                    broken_histories += length is None
                    timestamp = message.get('timestamp', message.get('created_at', created_at))
                    model = model_id(chat, message)
                    flags, details, excerpts = set(), {}, []
                    for channel in ('content', 'reasoning_content'):
                        text = text_content(message.get(channel))
                        found, checks, offset, excerpt = detect_text(text)
                        flags.update(found)
                        if found:
                            details[channel] = dict(flags=found, repetition_checks=checks)
                            excerpts.append((channel, offset, excerpt))
                    for table, group in ((by_model, model), (by_month, month(timestamp)), (by_bucket, bucket(tokens))):
                        counter = table.setdefault(group, Counter())
                        counter['assistant_messages'] += 1
                        counter['hits'] += bool(flags)
                    if not flags:
                        continue
                    total_hits += 1
                    flag_counts.update(flags)
                    channel, offset, excerpt = excerpts[0]
                    item = dict(chat_id=chat_id, message_index=index, message_id=message.get('id', key),
                                model_id=model, timestamp=timestamp, estimated_history_tokens=tokens,
                                flags=sorted(flags), details=details, request_parameters=stored_parameters(chat, message),
                                excerpt=excerpt, excerpt_offset=offset, excerpt_channel=channel)
                    hits.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + '\n')
            hits.flush()
            os.fsync(hits.fileno())
        lines = ['# Open WebUI loop scan', '', f'Chats: {total_chats}. Assistant messages: {total_messages}. Flagged messages: {total_hits}.', '',
                 'Mechanical detector candidates, not confirmed semantic loops. History estimates use chars/3.5 along each branch, including the current answer.',
                 'hidden-token-string means a visible control marker; invisible token floods cannot be inferred from chat text alone.',
                 f'Assistant messages with broken/cyclic parent links: {broken_histories} (history size unknown).', '']
        for title, table in (('By model id', by_model), ('By month (UTC)', by_month), ('By estimated history size', by_bucket)):
            lines += [f'## {title}', '', '| Group | Assistant messages | Flagged messages |', '| --- | ---: | ---: |']
            lines += [f"| {markdown(key)} | {counts['assistant_messages']} | {counts['hits']} |" for key, counts in sorted(table.items())]
            lines += ['']
        lines += ['## Flags', '', '| Flag | Messages |', '| --- | ---: |']
        lines += [f'| {key} | {count} |' for key, count in sorted(flag_counts.items())]
        lines += ['', 'Full chats were read only from the snapshot. Only hits.jsonl contains excerpts and stored request parameters; keep it on Framework.', '']
        # Exclusive publication prevents accidental replacement on a repeat run.
        os.link(temporary, output/'hits.jsonl')
        published.append(output/'hits.jsonl')
        fd = os.open(output/'summary.md', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        published.append(output/'summary.md')
        with os.fdopen(fd, 'w') as summary:
            summary.write('\n'.join(lines))
        return dict(chats=total_chats, assistant_messages=total_messages, hits=total_hits)
    except BaseException:
        for path in published:
            path.unlink(missing_ok=True)
        raise
    finally:
        temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        counts = scan(args.db, args.out)
    except (OSError, ValueError, sqlite3.Error):
        parser.exit(1, 'Scan failed; no new report retained (check snapshot schema, JSON and output permissions).\n')
    print(f"SCAN-OK: {counts['chats']} chats; {counts['assistant_messages']} assistant messages; {counts['hits']} hits. Excerpts remain in hits.jsonl.")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
