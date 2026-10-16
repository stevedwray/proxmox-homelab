#!/usr/bin/env python3
"""lh-08: build the blind judge corpus from saved loop-hunt results.

extract  Read results.jsonl files (run it on Framework, read-only) and print
         one compact JSON record per assistant turn: no request history, only
         what a judge needs plus private identity fields.
build    Read the extract output locally, drop duplicates, hide model, build
         and condition behind opaque ids, shuffle, and write batches plus a
         private id map.

The judge never sees model, build, condition, seed, session or turn numbers.
"""

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

SKIP_PARTS = ('regrade-backups', 'before-', 'source-before', '__pycache__')
RULES_CAP = 1500
TAIL_CAP = 1500
REPLAY_PREFIX = 'V'


def sha(*parts):
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode('utf-8', 'replace'))
        h.update(b'\0')
    return h.hexdigest()


def request_tail(last):
    text = last.get('content') or ''
    if not isinstance(text, str):
        text = json.dumps(text)
    marker = text.rfind('QUESTIONS')
    if marker != -1:
        return text[marker:]
    return text[-TAIL_CAP:]


def compact(row, run):
    payload = row.get('payload') or {}
    messages = payload.get('messages') or []
    system = next((m.get('content') or '' for m in messages if m.get('role') == 'system'), '')
    last = messages[-1] if messages else {}
    prior = next((m.get('content') or '' for m in reversed(messages[:-1])
                  if m.get('role') == 'assistant' and m.get('content')), '')
    choice = ((row.get('response') or {}).get('choices') or [{}])[0]
    message = choice.get('message') or {}
    return dict(
        src=run, key=row.get('key'), session=row.get('session'), turn=row.get('turn'),
        mode=row.get('mode'), seed=row.get('seed'), flags=row.get('flags') or [],
        model=(row.get('response') or {}).get('model'),
        finish_reason=choice.get('finish_reason'),
        replay=run.startswith(REPLAY_PREFIX),
        rules=system[:RULES_CAP] + ('\n[system prompt truncated]' if len(system) > RULES_CAP else ''),
        request_role=last.get('role'), request=request_tail(last),
        prior_answer=prior, answer=row.get('answer') or '', reasoning=row.get('reasoning') or '',
        tool_calls=message.get('tool_calls') or [],
    )


def cmd_extract(args):
    seen = set()
    for root in args.roots:
        for path in sorted(Path(root).rglob('results.jsonl')):
            rel = path.relative_to(root).parts
            if any(part.startswith(SKIP_PARTS) or part in SKIP_PARTS for part in rel[:-1]):
                continue
            run = path.parent.name
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                if row.get('error') or row.get('answer') is None:
                    continue
                rec = compact(row, run)
                ident = sha(rec['model'], row.get('prompt_sha256'), rec['mode'], rec['seed'],
                            rec['answer'], rec['reasoning'], json.dumps(rec['tool_calls']))
                if ident in seen:
                    continue
                seen.add(ident)
                rec['ident'] = ident
                print(json.dumps(rec, ensure_ascii=False))


def blind(rec, opaque):
    return dict(id=opaque, rules=rec['rules'], request=rec['request'],
               prior_answer=rec['prior_answer'], answer=rec['answer'],
               reasoning=rec['reasoning'], tool_calls=rec['tool_calls'],
               truncated_by_token_limit=rec['finish_reason'] == 'length')


def batches(items, max_records, max_chars):
    chunk, size = [], 0
    for item in items:
        cost = len(json.dumps(item, ensure_ascii=False))
        if chunk and (len(chunk) >= max_records or size + cost > max_chars):
            yield chunk
            chunk, size = [], 0
        chunk.append(item)
        size += cost
    if chunk:
        yield chunk


def cmd_build(args):
    records = [json.loads(line) for line in Path(args.extract).read_text().splitlines() if line.strip()]
    rng = random.Random(args.seed)
    order = list(range(len(records)))
    rng.shuffle(order)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    keymap = []
    groups = {'synthetic': [], 'replay': []}
    for n, i in enumerate(order, 1):
        rec = records[i]
        opaque = 'j-%04d' % n
        groups['replay' if rec['replay'] else 'synthetic'].append(blind(rec, opaque))
        keymap.append({k: rec[k] for k in ('src', 'key', 'session', 'turn', 'mode', 'seed', 'flags',
                                           'model', 'finish_reason', 'ident')} | {'id': opaque})
    for name, items in groups.items():
        if not items:
            continue
        (out / f'corpus-{name}.jsonl').write_text(
            ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in items))
        (out / 'batches').mkdir(exist_ok=True)
        for n, chunk in enumerate(batches(items, args.max_records, args.max_chars)):
            (out / 'batches' / f'{name}-{n:03d}.jsonl').write_text(
                ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in chunk))
    key = out / 'PRIVATE-key-map.jsonl'
    key.write_text(''.join(json.dumps(x) + '\n' for x in keymap))
    key.chmod(0o600)
    print({n: len(v) for n, v in groups.items()}, file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('extract')
    e.add_argument('roots', nargs='+')
    e.set_defaults(func=cmd_extract)
    b = sub.add_parser('build')
    b.add_argument('extract')
    b.add_argument('--out', required=True)
    b.add_argument('--seed', type=int, default=20261017)
    b.add_argument('--max-records', type=int, default=20)
    b.add_argument('--max-chars', type=int, default=60000)
    b.set_defaults(func=cmd_build)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
