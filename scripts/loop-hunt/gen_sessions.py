#!/usr/bin/env python3
"""Deterministic incident sessions, seeds 1–6; synthetic text only."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random

SEEDS = tuple(range(1, 7))
TURNS = 64  # Headroom for tokenizers: the runner ends at measured context, not turn 20/40.
SYSTEM = ('You investigate a synthetic incident. Start every answer with [TRIAGE], '
          'end with the requested ref: INC-<n>, and use no bullets. Answer only '
          'from supplied evidence; use NOT PROVIDED for absent facts. '
          'Answer in question order, one line per question as Q1: value, Q2: value, etc. '
          'Do not include reasoning in the answer.')
VOCAB = ('inspection rotation service queue window archive monitor routing storage '
         'review baseline process capacity status local schedule network worker '
         'session inventory trace maintenance request approved pending complete').split()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)+'\n').encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def reference(seed):
    return f'INC-{7000+seed}'


def value(seed, turn):
    return f'route-{seed:02d}-{turn:03d}-'+sha(f'{seed}/{turn}/fact'.encode())[:10]


def turn_fixture(seed, turn, chars=18000):
    rng = random.Random(seed*100000+turn)
    # Probe earlier history at early, middle and recent depths, deterministically.
    earlier = (1, max(1, turn//2), max(1, turn-3))[(turn-1)%3]
    records = []
    length = 0
    while length < chars:
        number = len(records)
        words = ' '.join(rng.choices(VOCAB, k=17))
        line = f'audit={seed:02d}-{turn:03d}-{number:04d} host=host-{rng.randrange(20):02d} {words}\n'
        records.append(line)
        length += len(line)
    expected = [value(seed, turn), value(seed, earlier)]
    questions = [f'What is the route value recorded for turn {turn}?',
                 f'What is the route value recorded for turn {earlier}?']
    if turn % 3 == 0:
        questions.append('What is the incident recovery password?')
        expected.append('NOT PROVIDED')
    # Filler has no passwords, planted values or alternative answer records.
    user = (f'INCIDENT {reference(seed)}. EVIDENCE TURN {turn}\n'
            f'PLANTED FACT: turn {turn} route value = {value(seed, turn)}\n'
            + ''.join(records) + 'END EVIDENCE\nQUESTIONS\n'
            + '\n'.join(f'Q{i}: {q}' for i,q in enumerate(questions,1))
            + f'\nEnd with ref: {reference(seed)}')
    return dict(seed=seed, turn=turn, user=user, expected=expected,
                reference=reference(seed), recalled_turn=earlier,
                absent_question=len(expected)==3,
                estimated_tokens=math.ceil(len(user)/3.0))


def generate(directory, *, seeds=SEEDS, turns=TURNS, chars=18000):
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    manifest=dict(version=1, seeds=list(seeds), turns=turns, system=SYSTEM,
                  estimate='ceil(chars/3.0); only /apply-template and /tokenize measure runtime context',sessions={})
    for seed in seeds:
        metadata=[]
        folder=directory/f'seed-{seed}'
        folder.mkdir(exist_ok=True)
        for turn in range(1,turns+1):
            fixture=turn_fixture(seed,turn,chars)
            data=encoded(fixture)
            path=folder/f'turn-{turn:03d}.json'
            path.write_bytes(data)
            metadata.append(dict(file=str(path.relative_to(directory)),sha256=sha(data),
                                 expected=fixture['expected'],recalled_turn=fixture['recalled_turn'],
                                 estimated_tokens=fixture['estimated_tokens']))
        manifest['sessions'][str(seed)]=metadata
    (directory/'manifest.json').write_bytes(encoded(manifest))
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path(__file__).parent/'sessions')
    args=parser.parse_args()
    manifest=generate(args.out)
    print(f"Generated {len(manifest['seeds'])} deterministic sessions, {manifest['turns']} available turns each.")


if __name__=='__main__':main()
