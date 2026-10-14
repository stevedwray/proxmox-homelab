#!/usr/bin/env python3
"""Synthetic fixed-seed fixtures. No network or tokenizer dependencies."""
import argparse
import hashlib
import json
import math
import random
from pathlib import Path

SEED = 4471
DEPTHS = (5, 25, 50, 75, 95)
SYSTEM = ('Start every answer with [LOG-QA]. Answer only from the log. '
          'If the log does not say, answer NOT IN LOG. Return a JSON list of '
          'eight answers in question order after the prefix. No other text.')
NEEDLES = [dict(id=f"REC-N{i}", host=f"host-needle-{i}", severity="warning",
                ticket=f"TCK-{8200+i}", value=f"amber-{913+i}") for i in range(1, 6)]
QUESTIONS = [f"What is the value in {r['id']}?" for r in NEEDLES] + [
    "What is the recovery password for host-absent?",
    "What is the value in REC-ABSENT?",
    "How many critical records are there for host-03?"]
VOCAB = ('inspection rotation service queue window archive monitor routing '
         'storage check review baseline process event capacity status local '
         'schedule network worker session inventory update trace maintenance').split()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def record_line(record):
    # Equal-width records keep record depths close to character depths.
    text = ' | '.join(f"{k}={v}" for k, v in record.items())
    return text.ljust(158) + '\n'


def make_log(count=200, seed=SEED):
    if count < 20:
        raise ValueError('at least 20 records required for five distinct depths')
    rng = random.Random(seed)
    records = [dict(id=f"REC-F{i:06d}", host=f"host-{rng.randrange(10):02d}",
                    severity=rng.choice(('info', 'warning', 'critical')),
                    ticket=f"TCK-{rng.randrange(1000, 7000)}",
                    value=f"cobalt-{rng.randrange(10000, 99999)}") for i in range(count)]
    positions = []
    for depth, needle in zip(DEPTHS, NEEDLES):
        index = round((count - 1) * depth / 100)
        records[index] = dict(needle)
        positions.append(dict(id=needle['id'], depth_percent=depth, record_index=index,
                              char_offset=index * 159, value=needle['value']))
    expected = [r['value'] for r in NEEDLES] + ['NOT IN LOG', 'NOT IN LOG',
        sum(r['host'] == 'host-03' and r['severity'] == 'critical' for r in records)]
    return records, positions, expected


def qa_prompt(count=200, seed=SEED, padding='', with_count=True):
    records, positions, expected = make_log(count, seed)
    questions = QUESTIONS if with_count else QUESTIONS[:7]
    system = SYSTEM if with_count else SYSTEM.replace('eight answers', 'seven answers')
    expected = expected if with_count else expected[:7]
    log = ''.join(record_line(r) for r in records)
    user = 'OPS LOG\n' + log + padding + '\nEND LOG\nQUESTIONS\n' + '\n'.join(
        f'{i}. {q}' for i, q in enumerate(questions, 1))
    return dict(messages=[dict(role='system', content=system), dict(role='user', content=user)],
                expected=expected, needles=positions, record_ids=[r['id'] for r in records],
                records=count, log_sha256=sha(log.encode()))


def prompt_text(prompt):
    """Estimate text, not a substitute for server-side chat template/tokenization."""
    return '\n'.join(m['content'] for m in prompt['messages'])


def build_prompts():
    prompts = {
        'S1': dict(messages=[dict(role='user', content=(
            'Compute 17 times 23 and 144 divided by 12. The lookup table says '
            'host-maple has value 708. What are the two arithmetic results and '
            'that lookup value, in that order? Answer with only the numbers, '
            'comma-separated.'))], expected='391,12,708'),
        'S2': dict(messages=[dict(role='user', content=(
            'Write a safe synthetic service restart procedure. Follow these eight '
            'constraints: (1) the body parses as JSON; (2) it is an object; '
            '(3) exactly the keys title, steps, risk; (4) steps is a list; '
            '(5) exactly five steps; (6) each step has at most 12 words; '
            '(7) no word very anywhere and risk is low, medium or high; '
            '(8) append a final line END after the JSON body. No fences or '
            'explanations. Use plain strings for the title and each step. '
            'Context for the procedure: the made-up service is a queue worker '
            'called Maple. It consumes synthetic inventory events on an isolated '
            'host and stores an audit trail locally. Operators normally inspect '
            'its status, tell their colleagues about the maintenance window, '
            'stop the worker, start it again, and inspect its status afterwards. '
            'No customers, credentials, external dependencies or real systems '
            'are involved. The service has an ordinary stop and start interface; '
            'there is no special recovery mechanism. The procedure should '
            'describe this ordinary sequence in the requested compact format. '
            'This background is simply task context; the eight response '
            'constraints above determine whether the response passes.'))]),
        'S3': qa_prompt(),
        'S4': dict(messages=[dict(role='user', content=(
            'Write a runbook for a synthetic service migration with exactly 12 '
            'numbered sections, in order, using headings like 1. Title. Each '
            'section must have a different title and 150–250 words of body text. '
            'No sentence may be repeated. End with -- END OF RUNBOOK --. '
            'The fictional migration concerns Maple, a service that reads '
            'synthetic inventory events from a local queue. The new release '
            'uses a replacement event parser and a new local audit directory. '
            'The old release can be restored from an offline package kept on '
            'the same host. Possible topics include preparation, ownership, '
            'dependency review, package inspection, configuration review, '
            'queue draining, service shutdown, installation, service startup, '
            'validation, rollback and operational handover. These topics are '
            'background suggestions. The numbered section count, distinct '
            'titles, body lengths, unique sentences and final marker are the '
            'requirements. All host names and values in the runbook should '
            'belong to this fictional example.'))]),
    }
    rng = random.Random(SEED + 1)
    messages = []
    for turn in range(1, 9):
        if turn == 1:
            user = 'For this conversation never use bullet points. End every reply with ref: TCK-4471.'
        elif turn == 3:
            user = 'Remember: the chosen rollback gateway is cedar-582. Record this decision.'
        elif turn == 8:
            user = 'What rollback gateway did we choose in turn 3? State its exact name and follow our two rules.'
        else:
            user = f'Turn {turn}: retain this synthetic operational note for later. '
        if turn < 8:
            user += '\n' + ' '.join(rng.choice(VOCAB) for _ in range(365))
        messages.append(dict(role='user', content=user))
        if turn < 8:
            assistant = (f'Turn {turn} noted. ' + ('The rollback gateway is cedar-582. ' if turn == 3 else '')
                         + ' '.join(rng.choice(VOCAB) for _ in range(190)) + '\nref: TCK-4471')
            messages.append(dict(role='assistant', content=assistant))
    prompts['S5'] = dict(messages=messages, expected='cedar-582')
    # Template is executable data: runtime generation uses this fixed seed and needles.
    prompts['F-template'] = dict(seed=SEED + 2, with_count=False,
                                system=SYSTEM.replace('eight answers', 'seven answers'), questions=QUESTIONS[:7],
                                expected=[r['value'] for r in NEEDLES] + ['NOT IN LOG', 'NOT IN LOG'],
                                needles=NEEDLES, depths_percent=list(DEPTHS),
                                target='ctx_size - 16384 - 2048')
    return prompts


def generate(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(version=1, seed=SEED, estimate_chars_per_token=3.0, prompts={})
    for name, prompt in build_prompts().items():
        data = json_bytes(prompt)
        (directory / f'{name}.json').write_bytes(data)
        estimate = math.ceil(len(prompt_text(prompt)) / 3) if 'messages' in prompt else None
        if estimate is not None and estimate > 12000:
            raise ValueError(f'{name} estimated {estimate} tokens exceeds 12000')
        manifest['prompts'][name] = dict(file=f'{name}.json', sha256=sha(data),
            estimated_tokens=estimate, needles=prompt.get('needles', []),
            expected=prompt.get('expected'))
    (directory / 'manifest.json').write_bytes(json_bytes(manifest))
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'prompts')
    args = parser.parse_args()
    print(json.dumps(generate(args.output), indent=2))
