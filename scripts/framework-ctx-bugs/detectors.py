"""Deterministic response checks; answer and reasoning are never conflated."""
import json
import re
import zlib
from collections import Counter


def words(text):
    return re.findall(r"\b[\w'-]+\b", text)


def loop(text):
    return bool(re.search(r'(.{50,}?)\1\1', text[-2000:], re.S))


def repetition(text, runbook=False):
    if runbook:
        text = re.sub(r'^\s*\d+\.\s+[^\n]+$', '', text, flags=re.M)
    tokens = [w.lower() for w in words(text)]
    shingles = Counter(tuple(tokens[i:i+8]) for i in range(len(tokens)-7))
    tail = text[-4000:].encode()
    ratio = len(zlib.compress(tail)) / len(tail) if tail else 1
    return (["shingle"] if any(n >= 4 for n in shingles.values()) else []) + (["zlib"] if ratio < .20 else [])


def first_difference(left, right):
    for index, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return index
    return min(len(left), len(right)) if len(left) != len(right) else None


def gpu_errors(window):
    return [line for line in window.splitlines()
            if 'amdgpu' in line.lower() and re.search(r'ring .* timeout|wedged|reset|Fence fallback timer expired', line, re.I)]


def instruction_checks(prompt_id, answer, fixture):
    """Named boolean checks and literal QA failures; no semantic cloud judge."""
    checks, wrong, hallucinations = {}, [], []
    if prompt_id == 'S1':
        normalized = re.sub(r'\s*,\s*', ',', answer.strip())
        checks['only-numbers'] = bool(re.fullmatch(r'\d+,\d+,\d+', normalized))
        if normalized != fixture['expected']:
            wrong.append('sanity')
    elif prompt_id == 'S2':
        lines = answer.rstrip().splitlines()
        checks['end'] = bool(lines) and lines[-1] == 'END'
        body = '\n'.join(lines[:-1]) if checks['end'] else answer
        try:
            obj = json.loads(body)
            checks['json'] = True
        except ValueError:
            obj = None
            checks['json'] = False
        checks['object'] = isinstance(obj, dict)
        obj = obj if isinstance(obj, dict) else {}
        checks['keys'] = set(obj) == {'title', 'steps', 'risk'}
        steps = obj.get('steps')
        checks['steps-list'] = isinstance(steps, list)
        checks['five-steps'] = isinstance(steps, list) and len(steps) == 5
        checks['step-length'] = (isinstance(steps, list) and all(
            isinstance(s, str) and len(words(s)) <= 12 for s in steps))
        checks['risk-and-no-very'] = (obj.get('risk') in ('low', 'medium', 'high')
                                    and not re.search(r'\bvery\b', answer, re.I))
        checks['strings'] = isinstance(obj.get('title'), str)
    elif prompt_id in ('S3', 'F'):
        checks['prefix'] = answer.startswith('[LOG-QA]')
        body = answer[len('[LOG-QA]'):].strip() if checks['prefix'] else answer
        try:
            values = json.loads(body)
            checks['json-list'] = isinstance(values, list) and len(values) == len(fixture['expected'])
        except ValueError:
            values = []
            checks['json-list'] = False
        values = values if isinstance(values, list) else []
        for i, expected in enumerate(fixture['expected']):
            value = values[i] if i < len(values) else None
            # Reject bool as a numeric count, or a quoted numeric string.
            equal = type(value) is type(expected) and value == expected
            if i in (5, 6):
                if value is not None and not equal:
                    hallucinations.append(f'q{i+1}')
                elif value is None:
                    wrong.append(f'q{i+1}')
            elif not equal:
                wrong.append(f'q{i+1}')
        for record in sorted(set(re.findall(r'\bREC-[A-Za-z0-9-]+\b', answer))):
            if record not in fixture['record_ids']:
                hallucinations.append(f'record:{record}')
    elif prompt_id == 'S4':
        marker = '-- END OF RUNBOOK --'
        headings = list(re.finditer(r'^\s*(\d+)\.\s+([^\n]+)', answer, re.M))
        checks['sections'] = [int(h[1]) for h in headings] == list(range(1, 13))
        checks['titles'] = len(headings) == 12 and len({h[2].strip().lower() for h in headings}) == 12
        bodies = [answer[h.end():headings[i+1].start() if i+1 < len(headings) else len(answer)]
                  .replace(marker, '').strip() for i, h in enumerate(headings)]
        checks['word-counts'] = len(bodies) == 12 and all(150 <= len(words(b)) <= 250 for b in bodies)
        sentences = [s.strip().lower() for b in bodies for s in re.split(r'(?<=[.!?])\s+', b) if s.strip()]
        checks['sentences'] = len(sentences) == len(set(sentences))
        checks['end-marker'] = answer.rstrip().endswith(marker)
    elif prompt_id == 'S5':
        checks['no-bullets'] = not bool(re.search(r'^\s*(?:[-*•]|\d+[.)])\s+', answer, re.M))
        checks['reference'] = answer.rstrip().endswith('ref: TCK-4471')
        if not re.search(r'\b' + re.escape(fixture['expected']) + r'\b', answer):
            wrong.append('turn3')
    return checks, wrong, hallucinations


def detect(prompt_id, response, fixture, visible_tokens, *, error=None, healthy=True,
           restarted=False, dmesg_window='', ctx_baseline=None, build_baseline=None):
    flags, details = [], {}
    choice = response.get('choices', [{}])[0]
    message = choice.get('message', {})
    answer = message.get('content') or ''
    reasoning = message.get('reasoning_content') or ''
    if choice.get('finish_reason') == 'length':
        flags.append('runaway')
    for name, text in (('answer', answer), ('reasoning', reasoning)):
        if loop(text):
            flags.append('loop')
            details.setdefault('loop', []).append(name)
        checks_fired = repetition(text, prompt_id == 'S4' and name == 'answer')
        if checks_fired:
            details.setdefault('repetition', {})[name] = checks_fired
            flags.append('dense-reasoning' if name == 'reasoning' and checks_fired == ['zlib'] else 'repetition')
    completion_tokens = response.get('usage', {}).get('completion_tokens', 0)
    if visible_tokens is not None and completion_tokens > 1.5 * visible_tokens and completion_tokens - visible_tokens > 100:
        flags.append('hidden-tokens')
    if any(token in answer for token in ('〈|', '<|im_end|>', '<|im_start|>', '<think>', '</think>')):
        flags.append('template-leak')
    if not answer.strip() and reasoning.strip():
        flags.append('no-answer')
    checks, wrong, hallucinations = instruction_checks(prompt_id, answer, fixture)
    flags.extend(f'if-fail:{rule}' for rule, passed in checks.items() if not passed)
    flags.extend(f'wrong:{q}' for q in wrong)
    flags.extend(f'hallucination:{q}' for q in hallucinations)
    for flag, baseline in (('ctx-divergence', ctx_baseline), ('build-divergence', build_baseline)):
        if baseline is not None:
            difference = first_difference(answer, baseline)
            if difference is not None:
                flags.append(flag)
                details[flag] = dict(first_differing_character=difference)
    if error or not healthy or restarted:
        flags.append('crash')
        details['crash'] = dict(error=error, healthy=healthy, restarted=restarted)
    gpu = gpu_errors(dmesg_window)
    if gpu:
        flags.append('gpu-error')
        details['gpu-error'] = gpu
    return dict(flags=sorted(set(flags)), details=details, checks=checks,
                answer=answer, reasoning=reasoning, visible_tokens=visible_tokens)
