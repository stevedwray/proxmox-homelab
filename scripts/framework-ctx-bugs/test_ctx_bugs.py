import contextlib
import hashlib
import io
import json
import re
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock
from pathlib import Path

import ctx_bugs as cb
import detectors as d
import gen_prompts as gp
import stub_server as stub

HERE = Path(__file__).parent


@contextlib.contextmanager
def server(**kwargs):
    instance = stub.StubServer(**kwargs)
    thread = threading.Thread(target=instance.serve_forever, daemon=True)
    thread.start()
    try:
        yield instance
    finally:
        instance.release_delay.set()
        instance.shutdown()
        instance.server_close()
        thread.join(5)


def response(answer='391,12,708', reasoning='', finish='stop', tokens=10):
    return dict(choices=[dict(message=dict(content=answer, reasoning_content=reasoning), finish_reason=finish)],
                usage=dict(completion_tokens=tokens))


class GeneratorTests(unittest.TestCase):
    def test_deterministic_bytes_and_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            manifest = gp.generate(folder)
            first = {p.name: p.read_bytes() for p in folder.iterdir()}
            gp.generate(folder)
            self.assertEqual(first, {p.name: p.read_bytes() for p in folder.iterdir()})
            for name, item in manifest['prompts'].items():
                self.assertEqual(item['sha256'], gp.sha(first[item['file']]))
                if name != 'F-template':
                    self.assertLessEqual(item['estimated_tokens'], 12000)

    def test_needles_and_count_at_manifest_positions(self):
        fixture = gp.qa_prompt()
        lines = fixture['messages'][-1]['content'].split('OPS LOG\n')[1].split('END LOG')[0]
        for needle in fixture['needles']:
            line = lines.splitlines()[needle['record_index']]
            self.assertIn('id=' + needle['id'], line)
            self.assertIn('value=' + needle['value'], line)
            self.assertEqual(lines.index('id=' + needle['id']), needle['char_offset'])
            self.assertLess(abs(needle['record_index']/199*100 - needle['depth_percent']), .3)
        self.assertEqual(len(set(fixture['record_ids'])), 200)
        self.assertNotIn('host-absent', lines)
        self.assertNotIn('REC-ABSENT', lines)
        self.assertEqual(fixture['expected'][-1], lines.count('host=host-03 | severity=critical'))

    def test_s5_eight_turns_and_fixed_answer(self):
        fixture = gp.build_prompts()['S5']
        self.assertEqual(len(fixture['messages']), 15)
        self.assertEqual(sum(m['role'] == 'user' for m in fixture['messages']), 8)
        self.assertIn(fixture['expected'], fixture['messages'][4]['content'])
        self.assertIn('never use bullet points', fixture['messages'][0]['content'])

    def test_f_has_seven_questions_and_s3_keeps_eight(self):
        prompts = gp.build_prompts()
        template = prompts['F-template']
        self.assertFalse(template['with_count'])
        self.assertEqual(len(template['questions']), 7)
        self.assertEqual(len(template['expected']), 7)
        self.assertNotIn(gp.QUESTIONS[-1], template['questions'])
        self.assertIn('seven answers', template['system'])
        fill = gp.qa_prompt(200, template['seed'], with_count=False)
        s3 = prompts['S3']
        self.assertEqual(fill['expected'], s3['expected'][:7])
        self.assertNotIn('How many critical records', fill['messages'][-1]['content'])
        self.assertEqual(len(s3['expected']), 8)
        self.assertIn('8. How many critical records', s3['messages'][-1]['content'])
        self.assertIn('eight answers', s3['messages'][0]['content'])
        # Dropping the question does not change the seeded log itself.
        self.assertEqual(fill['log_sha256'], gp.qa_prompt(200, template['seed'])['log_sha256'])

    def test_fill_exact_and_relocated_for_each_model_and_size(self):
        with server(clean=True) as s:
            client = cb.Client(s.url)
            for model in cb.MODELS:
                for size in cb.SIZES:
                    client.load(cb.entry_id(model, 'nathanw', size))
                    fixture, count = cb.make_fill(client, size, gp.build_prompts()['F-template'])
                    self.assertEqual(count, size - cb.BUDGET - cb.MARGIN)
                    self.assertEqual(count, client.prompt_tokens(fixture))
                    self.assertEqual(fixture['expected'][:7], gp.qa_prompt()['expected'][:7])
                    log = fixture['messages'][-1]['content'].split('END LOG')[0]
                    self.assertEqual(len(fixture['expected']), 7)
                    self.assertNotIn('How many critical records', fixture['messages'][-1]['content'])
                    self.assertNotIn('host-absent', log)
                    self.assertNotIn('REC-ABSENT', log)
                    for needle in fixture['needles']:
                        self.assertLess(abs(needle['record_index']/(fixture['records']-1)*100 - needle['depth_percent']), .5)
                    self.assertEqual(len(set(fixture['record_ids'])), fixture['records'])


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.fixtures = gp.build_prompts()

    def flags(self, result=None, prompt='S1', **kwargs):
        return d.detect(prompt, result or response(), self.fixtures[prompt], kwargs.pop('visible_tokens', 10), **kwargs)['flags']

    def test_runaway_positive_negative(self):
        self.assertIn('runaway', self.flags(response(finish='length')))
        self.assertNotIn('runaway', self.flags())

    def test_s1_comma_whitespace_only(self):
        for answer in ('391, 12, 708', ' 391 ,\t12,708\n'):
            self.assertEqual(self.flags(response(answer=answer)), [])
        for answer in ('391, 12, 708.', 'The answer is 391,12,708', '391,1 2,708'):
            self.assertIn('if-fail:only-numbers', self.flags(response(answer=answer)))
            self.assertIn('wrong:sanity', self.flags(response(answer=answer)))

    def test_dense_reasoning_is_information_only(self):
        log = '\n'.join(f'F{i:06d} host-{i%10:02d} info' for i in range(500))
        result = d.detect('S1', response(reasoning=log), self.fixtures['S1'], 10)
        self.assertIn('dense-reasoning', result['flags'])
        self.assertNotIn('repetition', result['flags'])
        self.assertEqual(result['details']['repetition'], {'reasoning': ['zlib']})
        record = dict(model=cb.MODELS[0], size=32768, prompt='S1', build='nathanw',
                      run='greedy', seed=1, **result)
        self.assertEqual(cb.findings([record]), [])
        result = d.detect('S1', response(answer=log), self.fixtures['S1'], 10)
        self.assertIn('repetition', result['flags'])
        self.assertNotIn('dense-reasoning', result['flags'])
        self.assertEqual(result['details']['repetition'], {'answer': ['zlib']})

    def test_repeated_sentence_remains_repetition(self):
        text = 'This sentence has enough distinct words to create a shingle. ' * 5
        result = d.detect('S1', response(reasoning=text), self.fixtures['S1'], 10)
        self.assertIn('repetition', result['flags'])
        self.assertNotIn('dense-reasoning', result['flags'])
        self.assertIn('shingle', result['details']['repetition']['reasoning'])

    def test_loop_positive_negative_and_boundaries(self):
        self.assertTrue(d.loop(('abcdefghijklmnopqrstuvwxzy' * 2) * 3))
        self.assertFalse(d.loop('a' * 49 * 3))
        self.assertFalse(d.loop('abcde' * 19))
        self.assertFalse(d.loop('unique text'))
        unique_tail = ''.join(hashlib.sha256(str(i).encode()).hexdigest() for i in range(32))[-2000:]
        self.assertFalse(d.loop(('a' * 50) * 3 + unique_tail))
        result = d.detect('S1', response(reasoning='a'*150), self.fixtures['S1'], 10)
        self.assertIn('reasoning', result['details']['loop'])

    def test_repetition_positive_negative_shingle_and_compression(self):
        phrase = 'one two three four five six seven eight'
        self.assertTrue(d.repetition('\n'.join(f'{i} {phrase}' for i in range(4))))
        self.assertFalse(d.repetition(phrase * 2))
        self.assertTrue(d.repetition('z' * 4000))
        self.assertFalse(d.repetition(stub.RUNBOOK, runbook=True))
        headings = '\n'.join(f'{i}. {phrase}' for i in range(1, 13))
        self.assertTrue(d.repetition(headings))
        self.assertFalse(d.repetition(headings, runbook=True))

    def test_recorded_token14_thresholds(self):
        # Recorded aggregate from model-params: 465 / 476 tokens were hidden token 14.
        self.assertIn('hidden-tokens', self.flags(response(tokens=476), visible_tokens=11))
        self.assertNotIn('hidden-tokens', self.flags(response(tokens=150), visible_tokens=100))
        self.assertNotIn('hidden-tokens', self.flags(response(tokens=200), visible_tokens=100))
        self.assertIn('hidden-tokens', self.flags(response(tokens=201), visible_tokens=100))

    def test_template_leak_positive_negative(self):
        for token in ('〈|', '<|im_end|>', '<|im_start|>', '<think>', '</think>'):
            self.assertIn('template-leak', self.flags(response(answer=token)))
            self.assertNotIn('template-leak', self.flags(response(reasoning=token)))
        self.assertNotIn('template-leak', self.flags())

    def test_no_answer_positive_negative(self):
        self.assertIn('no-answer', self.flags(response(answer='', reasoning='Thinking')))
        self.assertNotIn('no-answer', self.flags(response(answer='', reasoning='')))
        self.assertNotIn('no-answer', self.flags(response(reasoning='Thinking')))

    def test_every_instruction_check_positive_and_negative(self):
        clean = {p: stub.clean_answer(p, self.fixtures[p]['messages']) for p in ('S2', 'S3', 'S4', 'S5')}
        for prompt, answer in clean.items():
            checks, wrong, hallucinations = d.instruction_checks(prompt, answer, self.fixtures[prompt])
            self.assertTrue(all(checks.values()), (prompt, checks))
            self.assertEqual(wrong + hallucinations, [])
        s2 = json.loads(clean['S2'].split('\nEND')[0])
        bad_s2 = {
            'json': 'bad\nEND', 'object': '[]\nEND', 'keys': json.dumps(dict(s2, extra=1))+'\nEND',
            'steps-list': json.dumps(dict(s2, steps='invalid'))+'\nEND',
            'five-steps': json.dumps(dict(s2, steps=s2['steps'][:4]))+'\nEND',
            'step-length': json.dumps(dict(s2, steps=['word '*13]*5))+'\nEND',
            'risk-and-no-very': json.dumps(dict(s2, risk='extreme'))+'\nEND',
            'strings': json.dumps(dict(s2, title=1))+'\nEND', 'end': clean['S2']+'\nextra'}
        for rule, answer in bad_s2.items():
            self.assertIn('if-fail:'+rule, self.flags(response(answer=answer), 'S2'))
        self.assertIn('if-fail:risk-and-no-very', self.flags(response(answer=clean['S2'].replace('safely', 'very')), 'S2'))
        bad = {
            'S3': {'prefix': clean['S3'][8:], 'json-list': '[LOG-QA]{}'},
            'S4': {'sections': clean['S4'].replace('1. Migration', '13. Migration', 1),
                   'titles': clean['S4'].replace('Migration stage 2', 'Migration stage 1'),
                   'word-counts': '1. Tiny\nFew words.\n-- END OF RUNBOOK --',
                   'sentences': clean['S4'].replace('-- END', 'Repeated sentence. Repeated sentence.\n-- END'),
                   'end-marker': clean['S4']+'extra'},
            'S5': {'no-bullets': '- '+clean['S5'], 'reference': clean['S5']+'extra'}}
        for prompt, cases in bad.items():
            for rule, answer in cases.items():
                self.assertIn('if-fail:'+rule, self.flags(response(answer=answer), prompt), (prompt, rule))

    def test_wrong_needles_count_and_turn_positive_negative(self):
        fixture = self.fixtures['S3']
        clean = list(fixture['expected'])
        for index in (0, 1, 2, 3, 4, 7):
            values = clean[:]
            values[index] = 'wrong'
            self.assertIn(f'wrong:q{index+1}', self.flags(response(answer='[LOG-QA]'+json.dumps(values)), 'S3'))
        self.assertNotIn('wrong:q1', self.flags(response(answer='[LOG-QA]'+json.dumps(clean)), 'S3'))
        self.assertIn('wrong:turn3', self.flags(response(answer='cedar-999\nref: TCK-4471'), 'S5'))
        self.assertNotIn('wrong:turn3', self.flags(response(answer=stub.clean_answer('S5', [])), 'S5'))

    def test_qa_list_length_follows_saved_fixture(self):
        for with_count in (False, True):
            fixture = gp.qa_prompt(with_count=with_count)
            answer = '[LOG-QA]' + json.dumps(fixture['expected'])
            self.assertEqual(d.detect('F', response(answer=answer), fixture, 10)['flags'], [])
            wrong_length = fixture['expected'] + [0]
            self.assertIn('if-fail:json-list', d.detect('F', response(answer='[LOG-QA]'+json.dumps(wrong_length)), fixture, 10)['flags'])
        fixture = gp.qa_prompt(with_count=False)
        wrong = fixture['expected'][:]
        wrong[5] = 'invented password'
        self.assertIn('hallucination:q6', d.detect('F', response(answer='[LOG-QA]'+json.dumps(wrong)), fixture, 10)['flags'])

    def test_absent_fact_and_unknown_id_positive_negative(self):
        clean = self.fixtures['S3']['expected'][:]
        for index in (5, 6):
            values = clean[:]
            values[index] = 'invented'
            self.assertIn(f'hallucination:q{index+1}', self.flags(response(answer='[LOG-QA]'+json.dumps(values)), 'S3'))
        answer = '[LOG-QA]'+json.dumps(clean)
        self.assertFalse(any(f.startswith('hallucination:') for f in self.flags(response(answer=answer), 'S3')))
        self.assertIn('hallucination:record:REC-Z999', self.flags(response(answer=answer+' REC-Z999'), 'S3'))
        self.assertNotIn('hallucination:record:REC-N1', self.flags(response(answer=answer+' REC-N1'), 'S3'))

    def test_context_and_build_divergence_positive_negative(self):
        for name, arg in (('ctx-divergence', 'ctx_baseline'), ('build-divergence', 'build_baseline')):
            result = d.detect('S1', response(), self.fixtures['S1'], 10, **{arg: '391,12,700'})
            self.assertIn(name, result['flags'])
            self.assertEqual(result['details'][name]['first_differing_character'], 9)
            self.assertNotIn(name, self.flags(**{arg: '391,12,708'}))
        self.assertEqual(d.first_difference('a', 'ab'), 1)

    def test_crash_positive_negative(self):
        for params in (dict(error='request timed out'), dict(healthy=False), dict(restarted=True)):
            self.assertIn('crash', self.flags(**params))
        self.assertNotIn('crash', self.flags())

    def test_gpu_error_positive_negative(self):
        for text in ('amdgpu ring gfx timeout', 'amdgpu device wedged', 'amdgpu GPU reset',
                     'amdgpu Fence fallback timer expired on ring comp_1.3.0'):
            self.assertIn('gpu-error', self.flags(dmesg_window=text))
        self.assertNotIn('gpu-error', self.flags(dmesg_window='unrelated reset'))
        self.assertNotIn('gpu-error', self.flags(dmesg_window=''))


class HarnessTests(unittest.TestCase):
    def test_swap_restart_stops_checkpointing_restores_and_resume_retries(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True, swap_restart_request=2) as s:
            argv = ['--dry-run', '--base-url', s.url, '--run-dir', tmp, '--models', cb.MODELS[0],
                    '--builds', 'upstream', '--sizes', '32768', '--greedy-only']
            run = cb.Run(cb.parse_args(argv))
            self.assertEqual(run.execute(), 1)
            self.assertEqual(len(run.records), 1)
            self.assertEqual(len(s.requests), 2)
            key = cb.entry_id(cb.MODELS[0], 'upstream', 32768)+'/S2/greedy'
            self.assertEqual(run.manifest['failure'], 'llama-swap restarted or unreachable during '+key)
            self.assertEqual(run.manifest['status'], 'failed')
            self.assertTrue(run.manifest['restored_default'])
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)
            directory = Path(tmp)
            self.assertFalse((directory/'raw'/run.records[0]['cell']/'S2-greedy.json').exists())
            evidence = json.loads((directory/'raw'/run.records[0]['cell']/'S2-greedy-infrastructure.json').read_text())
            self.assertNotEqual(evidence['swap_before'], evidence['swap_after'])
            resumed = cb.Run(cb.parse_args(argv))
            self.assertEqual(resumed.execute(), 0)
            self.assertEqual(len(resumed.records), 6)
            self.assertEqual(len(s.requests), 7)
            self.assertEqual(s.requests[1], s.requests[2])
            self.assertTrue(all(not r['flags'] for r in resumed.records))
            self.assertTrue(all(r['swap_before']==r['swap_after'] for r in resumed.records))
            self.assertNotIn('failure', resumed.manifest)

    def test_server_death_without_swap_restart_is_still_a_crash(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True, server_death_request=2) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                         '--models', cb.MODELS[0], '--builds', 'upstream', '--sizes', '32768', '--greedy-only']))
            self.assertEqual(run.execute(), 0)
            self.assertEqual(len(run.records), 6)
            self.assertIn('crash', run.records[1]['flags'])
            self.assertEqual(run.records[1]['swap_before'], run.records[1]['swap_after'])
            self.assertNotIn('infrastructure_failure', run.manifest)
            self.assertTrue(run.manifest['restored_default'])

    def test_swap_identity_live_system_unit_and_restore_three_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = cb.Run(cb.parse_args(['--dry-run', '--run-dir', tmp]))
            run.args.dry_run = False
            with mock.patch.object(cb, 'command', return_value='12345\n998877\n') as capture:
                self.assertEqual(run.swap_identity(), ['12345', '998877'])
                capture.assert_called_once_with(['systemctl', 'show', '-p', 'MainPID', '-p',
                                                'ActiveEnterTimestampMonotonic', '--value', 'llama-swap.service'])
            with mock.patch.object(cb, 'command', return_value='0\n0\n'):
                with self.assertRaises(RuntimeError):
                    run.swap_identity()
            run.manifest = dict(restore_model=stub.INITIAL_MODEL)
            with mock.patch.object(run, 'lock', return_value=contextlib.nullcontext()), \
                 mock.patch.object(run, 'check_lock'), mock.patch.object(run, 'matrix'), \
                 mock.patch.object(run, 'save'), \
                 mock.patch.object(run, 'load_entry', side_effect=[OSError('refused'), OSError('refused'), {}]) as load:
                self.assertEqual(run.execute_locked(), 0)
                self.assertEqual(load.call_count, 3)
                self.assertTrue(run.manifest['restored_default'])

    def test_swap_wait_has_bounded_timeout_and_no_load_when_unreachable(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = cb.Run(cb.parse_args(['--dry-run', '--run-dir', tmp]))
            with mock.patch.object(cb, 'SWAP_WAIT_SECONDS', .01), \
                 mock.patch.object(run.client, 'call', side_effect=OSError('refused')) as call, \
                 mock.patch.object(run.client, 'load') as load:
                with self.assertRaisesRegex(RuntimeError, 'did not become reachable'):
                    run.load_entry('some-entry')
                self.assertTrue(all(0 < c.kwargs['timeout'] <= .01 for c in call.call_args_list))
                load.assert_not_called()

    def test_regrade_stub_run_is_offline_idempotent_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as tmp, server() as s:
            directory = Path(tmp)
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                      '--models', cb.MODELS[1], '--sizes', '32768', '--greedy-only']))
            self.assertEqual(run.execute(), 0)
            records = cb.read_results(directory/'results.jsonl')
            # Reproduce the pilot's spacing/compression mistakes in saved evidence.
            first = next(r for r in records if r['build']=='upstream' and r['prompt']=='S1')
            first['response'] = response(answer='391, 12, 708', reasoning='\n'.join(
                f'F{i:06d} host-{i%10:02d} info' for i in range(500)))
            first['flags'] = ['if-fail:only-numbers', 'wrong:sanity', 'repetition']
            (directory/'results.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
            original = (directory/'results.jsonl').read_bytes()
            evidence_keys = ('response', 'settings', 'error', 'evidence_error', 'kernel_window',
                             'visible_tokens', 'prompt_sha256', 'server_before', 'server_after')
            with mock.patch.object(cb.Client, 'call', side_effect=AssertionError('HTTP forbidden')), \
                 mock.patch.object(cb.Run, 'lock', side_effect=AssertionError('lock forbidden')), \
                 mock.patch.object(cb.fcntl, 'flock', side_effect=AssertionError('lock forbidden')):
                self.assertEqual(cb.main(['--regrade', tmp]), 0)
                updated = cb.read_results(directory/'results.jsonl')
                fixed = next(r for r in updated if r['key']==first['key'])
                self.assertIn('dense-reasoning', fixed['flags'])
                for flag in ('wrong:sanity', 'if-fail:only-numbers', 'repetition'):
                    self.assertNotIn(flag, fixed['flags'])
                for old, new in zip(records, updated):
                    self.assertEqual({k: old[k] for k in evidence_keys}, {k: new[k] for k in evidence_keys})
                    self.assertEqual(json.loads((directory/'raw'/new['cell']/f"{new['prompt']}-{new['run']}.json").read_text()), new)
                backup = directory/'results.pre-regrade.jsonl'
                self.assertEqual(backup.read_bytes(), original)
                before = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*') if p.is_file()}
                self.assertEqual(cb.main(['--regrade', tmp]), 0)
                after = {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob('*') if p.is_file()}
                self.assertEqual(before, after)
                manifest = json.loads((directory/'run.json').read_text())
                probe = manifest['cells'][cb.entry_id(cb.MODELS[1], 'nathanw', 32768)]['probe']
                self.assertEqual(json.loads((directory/'raw'/probe['cell']/'S1-probe.json').read_text()), probe)
                manifest['status'] = 'running'
                cb.write_json(directory/'run.json', manifest)
                with self.assertRaisesRegex(ValueError, 'running'):
                    cb.regrade(directory)
                self.assertEqual(backup.read_bytes(), original)
                self.assertEqual((directory/'results.jsonl').read_bytes(), before['results.jsonl'])
                manifest['status'] = 'complete'
                cb.write_json(directory/'run.json', manifest)
                prompt = directory/'prompts/S1.json'
                prompt.write_bytes(prompt.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                    cb.regrade(directory)
                self.assertEqual((directory/'results.jsonl').read_bytes(), before['results.jsonl'])

    def test_prepare_falls_back_if_props_does_not_answer(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            call = run.client.call
            def no_props(path, *args, **kwargs):
                if path == '/props':
                    raise ConnectionRefusedError('server not loaded')
                return call(path, *args, **kwargs)
            with mock.patch.object(run.client, 'call', side_effect=no_props):
                run.prepare()
            saved = json.loads(run.manifest_path.read_text())
            self.assertEqual(saved['restore_model'], cb.DEFAULT_MODEL)
            self.assertEqual(saved['restore_model_note'], 'nothing answered on :8080')
            # The server subsequently answers, but resume keeps the original fallback.
            run.prepare()
            self.assertEqual(run.manifest['restore_model'], cb.DEFAULT_MODEL)
            with mock.patch.object(run, 'matrix'):
                self.assertEqual(run.execute_locked(), 0)
            self.assertEqual(s.loads[-1], cb.DEFAULT_MODEL)

    def test_live_prepare_records_alias_before_lock_and_preserves_it_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            root = Path(tmp)
            for label, backend in (('nathanw', 'fork'), ('upstream', 'upstream')):
                cb.write_json(root/backend/'current'/'build.json', stub.BUILDS[label])
            cb.write_json(root/'builds.json', stub.BUILDS)
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', str(root/'run'),
                '--builds-json', str(root/'builds.json'), '--builds-root', str(root)]))
            run.args.dry_run = False  # Production preparation, against loopback only.
            with mock.patch.object(run, 'lock', side_effect=AssertionError('prepare must not take the lock')):
                run.prepare()
                self.assertEqual(run.manifest['restore_model'], stub.INITIAL_MODEL)
                s.entry = cb.entry_id(cb.MODELS[0], 'nathanw', 32768)
                with mock.patch.object(run.client, 'call', side_effect=AssertionError('resume must not recapture props')):
                    run.prepare()
            self.assertEqual(run.manifest['restore_model'], stub.INITIAL_MODEL)

    def test_saved_test_entry_restores_default_for_every_context_suffix(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            run.prepare()
            for size in cb.SIZES:
                with self.subTest(size=size):
                    run.manifest['restore_model'] = cb.entry_id(cb.MODELS[0], 'nathanw', size)
                    with mock.patch.object(run, 'matrix'):
                        self.assertEqual(run.execute_locked(), 0)
                    self.assertEqual(s.loads[-1], cb.DEFAULT_MODEL)
                    self.assertEqual(run.manifest['restored_model'], cb.DEFAULT_MODEL)

    def test_report_tables_match_header_separator_and_data_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = []
            for build, size, answer in (('nathanw', 32768, 'base'), ('nathanw', 65536, 'changed'),
                                         ('upstream', 65536, 'another')):
                cell = cb.entry_id(cb.MODELS[0], build, size)
                for prompt in ('S1', 'F'):
                    records.append(dict(key=f'{cell}/{prompt}/greedy', cell=cell, model=cb.MODELS[0],
                        build=build, size=size, prompt=prompt, run='greedy', seed=1, answer=answer,
                        flags=[], details={}, prompt_tokens=100, response={}, wall_seconds=1))
            cells = {r['cell']: dict(fill_key=r['cell']) for r in records}
            fills = {cell: dict(expected=gp.qa_prompt(with_count=False)['expected']) for cell in cells}
            cb.report(Path(tmp), records, dict(dry_run=True, status='complete', cells=cells, fill_prompts=fills))
            lines = (Path(tmp)/'report.md').read_text().splitlines()
            separators = 0
            for i, line in enumerate(lines):
                if not re.fullmatch(r'\|(?:\s*:?-+:?\s*\|)+', line):
                    continue
                separators += 1
                columns = line.count('|') - 1
                self.assertEqual(lines[i-1].count('|') - 1, columns, lines[i-1])
                for row in lines[i+1:]:
                    if not row.startswith('|'):
                        break
                    self.assertEqual(row.count('|') - 1, columns, row)
            self.assertEqual(separators, 3)

    def test_fill_report_uses_saved_expected_count_and_warns_about_comparability(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, cells, fills = [], {}, {}
            for build, with_count in (('nathanw', False), ('upstream', True)):
                cell = cb.entry_id(cb.MODELS[0], build, 131072)
                fixture = gp.qa_prompt(with_count=with_count)
                cells[cell] = dict(fill_key=cell)
                fills[cell] = dict(expected=fixture['expected'])
                records.append(dict(key=cell+'/F/greedy', cell=cell, model=cb.MODELS[0],
                    build=build, size=131072, prompt='F', run='greedy', seed=1,
                    answer='', flags=['wrong:q1'], details={}, prompt_tokens=112640,
                    response={}, wall_seconds=1))
            cb.report(Path(tmp), records, dict(dry_run=True, status='complete', cells=cells, fill_prompts=fills))
            text = (Path(tmp)/'report.md').read_text()
            self.assertIn('| Correct |', text)
            self.assertIn('| 6/7 |', text)
            self.assertIn('| 7/8 |', text)
            self.assertIn('not comparable with later F results', text)

    def test_kernel_capture_uses_bounded_system_journal_and_appends_once(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            fixture = gp.build_prompts()['S1']
            entry = cb.entry_id(cb.MODELS[0], 'upstream', 32768)
            run.args.dry_run = False
            line = '2026-10-14T01:00:00+00:00 kernel: amdgpu ring gfx timeout\n'
            with mock.patch.object(run, 'check_lock'), mock.patch.object(run, 'swap_identity', return_value=[789, '123']), \
                 mock.patch.object(cb, 'server_pid', return_value=[123, '456']), \
                 mock.patch.object(cb, 'command', return_value=line) as capture:
                record = run.request(cb.MODELS[0], 'upstream', 32768, entry, fixture, 100,
                                     'S1', 'greedy', 1, True, False)
            window = record['kernel_window']
            self.assertLessEqual(window['since'], window['until'])
            capture.assert_called_once_with(['sudo', '-n', 'journalctl', '-k', '--since', f"@{window['since']:.6f}",
                '--until', f"@{window['until']:.6f}", '--no-pager', '-o', 'short-iso'])
            self.assertIn('gpu-error', record['flags'])
            self.assertIsNone(record['evidence_error'])
            saved = (run.directory/'dmesg.txt').read_text()
            self.assertEqual(saved.count(line), 1)
            self.assertNotIn('## after', saved)

    def test_before_identity_failure_does_not_abort_request(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            with mock.patch.object(run, 'server_identity', side_effect=[RuntimeError('identity unavailable'), 123]):
                record = run.request(cb.MODELS[0], 'upstream', 32768, cb.entry_id(cb.MODELS[0], 'upstream', 32768),
                    gp.build_prompts()['S1'], 100, 'S1', 'greedy', 1, True, False)
            self.assertEqual(len(s.requests), 1)
            self.assertIn('before server identity', record['evidence_error'])
            self.assertIsNone(record['error'])
            self.assertNotIn('crash', record['flags'])

    def test_system_cell_journal_failure_is_written_without_aborting(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                '--models', cb.MODELS[0], '--builds', 'nathanw', '--sizes', '32768', '--greedy-only']))
            def logs(start):
                # Exercise the actual production command path while all requests
                # and lock operations continue to use the local stand-in.
                run.args.dry_run = False
                try:
                    return cb.Run.cell_logs(run, start)
                finally:
                    run.args.dry_run = True
            with mock.patch.object(run, 'cell_logs', side_effect=logs), \
                 mock.patch.object(cb, 'command', side_effect=RuntimeError('journal access denied')) as capture:
                self.assertEqual(run.execute(), 0)
            self.assertEqual(len(run.records), 6)
            capture.assert_called_once()
            argv = capture.call_args.args[0]
            self.assertEqual(argv[:6], ['sudo', '-n', 'journalctl', '-u', 'llama-swap.service', '--since'])
            self.assertEqual(argv[-1], '--no-pager')
            self.assertNotIn('--user', argv)
            log = (run.directory/'logs'/f'{cb.entry_id(cb.MODELS[0], "nathanw", 32768)}.log').read_text()
            self.assertIn('journal access denied', log)

    def test_kernel_command_exceptions_do_not_abort_completion(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            run.args.dry_run = False
            for failure in (RuntimeError('permission denied'), subprocess.TimeoutExpired('journalctl', 30)):
                with self.subTest(failure=type(failure).__name__), mock.patch.object(run, 'check_lock'), \
                     mock.patch.object(run, 'swap_identity', return_value=[789, '123']), \
                     mock.patch.object(cb, 'server_pid', return_value=[123, '456']), \
                     mock.patch.object(cb, 'command', side_effect=failure):
                    record = run.request(cb.MODELS[0], 'upstream', 32768, cb.entry_id(cb.MODELS[0], 'upstream', 32768),
                        gp.build_prompts()['S1'], 100, 'S1', 'greedy', 1, True, False)
                    self.assertIn('kernel window capture', record['evidence_error'])
                    self.assertIsNone(record['error'])
                    self.assertEqual(record['flags'], [])
            self.assertEqual(len(s.requests), 2)

    def test_stub_kernel_window_excludes_historical_and_future_lines(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            s.kernel_events = [(99, 'amdgpu historical reset'), (100.5, 'kernel normal event'),
                               (101, 'amdgpu ring gfx timeout'), (102, 'amdgpu future reset')]
            window = run.kernel_window(100.25, 101.75)
            self.assertEqual(window, 'kernel normal event\namdgpu ring gfx timeout')
            self.assertEqual(d.gpu_errors(window), ['amdgpu ring gfx timeout'])

    def test_stub_kernel_command_failure_records_evidence_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True, kernel_log_error=True) as s:
            directory = Path(tmp)/'kernel-failure'
            result = subprocess.run(self.command(s, directory), capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            records = cb.read_results(directory/'results.jsonl')
            self.assertEqual(len(records), 22)
            self.assertTrue(all('simulated kernel log permission failure' in r['evidence_error'] for r in records))
            self.assertTrue(all(r['error'] is None and not r['flags'] for r in records))
            self.assertEqual(len(s.kernel_windows), 22)
            self.assertTrue(all(since <= until for since, until in s.kernel_windows))
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)

    def test_matrix_and_short_form(self):
        self.assertEqual(len(cb.runs()), 22)
        self.assertEqual(len(cb.runs(short=True)), 6)
        self.assertEqual(len(cb.runs(greedy_only=True)), 6)
        self.assertEqual(len(cb.runs(extra_seeds=[4, 5, 6])), 18)
        for size in cb.SIZES:
            self.assertIn('-ctx', cb.entry_id(cb.MODELS[0], 'upstream', size))

    def test_variant_entry_ids_and_option_validation(self):
        for candidate in (False, True):
            base = 'laguna-s-2.1-nathanw' + ('-candidate' if candidate else '') + '-ctx131k'
            self.assertEqual(cb.entry_id(cb.MODELS[1], 'nathanw', 131072, candidate), base)
            self.assertEqual(cb.entry_id(cb.MODELS[1], 'nathanw', 131072, candidate, 'b512'), base+'-b512')
        for invalid in ('', 'B512', 'b-512', '../b512', 'b_512'):
            with self.subTest(suffix=invalid), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    cb.parse_args(['--entry-suffix', invalid])
        self.assertEqual(cb.parse_args(['--prompts', 'F', 'S2', 'F']).prompts, ['S2', 'F'])

    def test_selected_prompt_scheduling(self):
        self.assertEqual(cb.runs(prompts=['F']), [('F', 'greedy', 1, True), ('F', 'seed1', 1, False)])
        self.assertEqual(cb.runs(greedy_only=True, prompts=['F']), [('F', 'greedy', 1, True)])
        self.assertEqual(cb.runs(short=True, prompts=['F']), [('F', 'greedy', 1, True)])
        self.assertEqual(cb.runs(extra_seeds=[4, 5, 6], prompts=['F']),
                         [('F', f'seed{i}', i, False) for i in (4, 5, 6)])
        self.assertEqual([r[0] for r in cb.runs(greedy_only=True, prompts=['F', 'S3', 'S1'])],
                         ['S1', 'S3', 'F'])

    def test_suffix_fill_only_run_restore_and_resume_identity(self):
        # Nathanw Laguna would normally probe S1; F-only must not send that probe.
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            initial = cb.entry_id(cb.MODELS[1], 'upstream', 131072, suffix='b512')
            s.entry = initial
            argv = ['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                    '--models', cb.MODELS[1], '--builds', 'nathanw', '--sizes', '131072',
                    '--entry-suffix', 'b512', '--prompts', 'F', '--greedy-only']
            run = cb.Run(cb.parse_args(argv))
            self.assertEqual(run.execute(), 0)
            self.assertEqual(len(s.requests), 1)
            self.assertEqual(len(run.records), 1)
            self.assertEqual(run.records[0]['prompt'], 'F')
            entry = cb.entry_id(cb.MODELS[1], 'nathanw', 131072, suffix='b512')
            self.assertEqual(run.records[0]['cell'], entry)
            self.assertEqual(run.manifest['cells'][entry]['props']['model_alias'], entry)
            self.assertEqual(run.manifest['cells'][entry]['props']['default_generation_settings']['n_ctx'], 131072)
            self.assertNotIn('probe', run.manifest['cells'][entry])
            self.assertEqual(run.manifest['restore_model'], initial)
            self.assertEqual(run.manifest['restored_model'], cb.DEFAULT_MODEL)
            self.assertEqual(s.loads[-1], cb.DEFAULT_MODEL)
            self.assertEqual(run.manifest['identity']['entry_suffix'], 'b512')
            self.assertEqual(run.manifest['identity']['prompts'], ['F'])
            self.assertEqual(cb.Run(cb.parse_args(argv)).execute(), 0)
            for changed in (['--entry-suffix', 'b256'], ['--prompts', 'S1']):
                with self.assertRaisesRegex(ValueError, 'resume settings'):
                    cb.Run(cb.parse_args(argv+changed)).execute()
            self.assertEqual(len(s.requests), 1)

    def test_fill_only_default_sampling_sends_greedy_and_seed1(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                    '--models', cb.MODELS[0], '--builds', 'upstream', '--sizes', '32768', '--prompts', 'F']))
            self.assertEqual(run.execute(), 0)
            self.assertEqual([(r['prompt'], r['run']) for r in run.records], [('F', 'greedy'), ('F', 'seed1')])
            self.assertEqual(len(s.requests), 2)

    def test_fit_and_props_fail_closed(self):
        cb.fit_check(14336, 32768)
        with self.assertRaises(ValueError):
            cb.fit_check(14337, 32768)
        good = dict(alias='entry', n_ctx=32768, build_info='expected', total_slots=1)
        cb.check_props(good, 'entry', 32768, 'expected')
        for key, value in (('alias', 'wrong'), ('n_ctx', 65536), ('build_info', 'unexpected'), ('total_slots', 4)):
            with self.assertRaises(ValueError):
                cb.check_props(dict(good, **{key: value}), 'entry', 32768, 'expected')

    def test_refused_cell_sends_no_requests_and_restores_initial_model(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            args = cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp,
                                  '--models', cb.MODELS[0], '--builds', 'upstream', '--sizes', '32768'])
            run = cb.Run(args)
            with mock.patch.object(run.client, 'prompt_tokens', return_value=14337):
                self.assertEqual(run.execute(), 1)
            self.assertEqual(s.requests, [])
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)
            self.assertEqual(run.manifest['status'], 'failed')

    def test_divergences_are_persisted_in_checkpoint_and_raw(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            run.prepare()
            records = []
            for size, build, answer in ((32768, 'nathanw', 'base'), (65536, 'nathanw', 'different'), (65536, 'upstream', 'third')):
                entry = cb.entry_id(cb.MODELS[0], build, size)
                records.append(dict(key=entry+'/S1/greedy', cell=entry, model=cb.MODELS[0],
                    build=build, size=size, prompt='S1', run='greedy', seed=1, flags=[], details={},
                    answer=answer, prompt_tokens=100, generated_tokens=2, response={}, wall_seconds=1))
            for record in records:
                run.checkpoint(record)
            persisted = cb.read_results(run.results_path)
            self.assertIn('ctx-divergence', persisted[1]['flags'])
            self.assertIn('build-divergence', persisted[2]['flags'])
            raw = json.loads((run.directory/'raw'/records[2]['cell']/'S1-greedy.json').read_text())
            self.assertIn('build-divergence', raw['flags'])

    def test_build_finding_requires_complete_comparison(self):
        records = []
        for build in cb.BUILDS:
            for seed in (1, 2, 3):
                records.append(dict(model=cb.MODELS[0], size=32768, prompt='S1', build=build,
                    run=f'seed{seed}', seed=seed, flags=['loop'] if build=='nathanw' and seed<3 else []))
        self.assertTrue(any(f['kind']=='build bug' for f in cb.findings(records)))
        self.assertFalse(any(f['kind']=='build bug' for f in cb.findings(records[:-1])))

    def test_saved_fill_hash_mismatch_refuses_reuse(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            run = cb.Run(cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp]))
            run.prepare()
            run.preflight_cell(cb.MODELS[0], 'nathanw', 32768)
            meta = next(iter(run.manifest['fill_prompts'].values()))
            (run.directory/meta['file']).write_text('{}')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                run.preflight_cell(cb.MODELS[0], 'upstream', 32768)

    def test_candidate_short_form(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True) as s:
            args = cb.parse_args(['--dry-run', '--base-url', s.url, '--run-dir', tmp, '--candidate',
                                  '--models', cb.MODELS[1], '--builds', 'nathanw', '--sizes', '32768'])
            run = cb.Run(args)
            self.assertEqual(run.execute(), 0)
            self.assertEqual(len(run.records), 6)
            self.assertTrue(all('-candidate-' in r['cell'] and r['settings']['max_tokens']==2048 for r in run.records))

    def test_incomplete_append_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'results.jsonl'
            path.write_bytes(b'{"key":"complete"}\n{"unfinished"')
            self.assertEqual(cb.read_results(path), [{'key': 'complete'}])
            self.assertEqual(path.read_bytes(), b'{"key":"complete"}\n')

    def command(self, s, directory, full=False):
        args = [sys.executable, str(HERE/'ctx_bugs.py'), '--dry-run', '--base-url', s.url, '--run-dir', str(directory)]
        if not full:
            args += ['--models', cb.MODELS[0], '--builds', 'upstream', '--sizes', '32768']
        return args

    def test_end_to_end_resume_after_interrupted_request(self):
        with tempfile.TemporaryDirectory() as tmp, server(clean=True, delay_request=2, delay_seconds=30) as s:
            directory = Path(tmp)/'resume'
            args = self.command(s, directory)
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            try:
                self.assertTrue(s.delayed.wait(15), 'second request did not start')
                proc.send_signal(signal.SIGTERM)
                output, _ = proc.communicate(timeout=15)
                self.assertEqual(proc.returncode, 130, output)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.communicate()
                s.release_delay.set()
            partial = cb.read_results(directory/'results.jsonl')
            self.assertEqual(len(partial), 1)
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)
            self.assertEqual(json.loads((directory/'run.json').read_text())['restore_model'], stub.INITIAL_MODEL)
            s.entry = cb.entry_id(cb.MODELS[0], 'upstream', 32768)
            resumed = subprocess.run(args, capture_output=True, text=True, timeout=60)
            self.assertEqual(resumed.returncode, 0, resumed.stdout+resumed.stderr)
            records = cb.read_results(directory/'results.jsonl')
            self.assertEqual(len(records), 22)
            self.assertEqual(len({r['key'] for r in records}), 22)
            self.assertEqual(len(s.requests), 23)  # interrupted request was sent again
            self.assertEqual(s.requests[1]['seed'], s.requests[2]['seed'])
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)
            saved = json.loads((directory/'run.json').read_text())
            self.assertEqual(saved['restore_model'], stub.INITIAL_MODEL)
            self.assertEqual(saved['restored_model'], stub.INITIAL_MODEL)
            self.assertTrue(all(not r['flags'] for r in records))
            self.assertTrue((directory/'report.md').is_file())
            before = len(s.requests)
            completed_resume = subprocess.run(args, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed_resume.returncode, 0, completed_resume.stdout)
            self.assertEqual(len(s.requests), before)
            changed = subprocess.run(args+['--greedy-only'], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(changed.returncode, 0)

    def test_full_dry_run_canned_flags_and_clean_answers(self):
        with tempfile.TemporaryDirectory() as tmp, server() as s:
            directory = Path(tmp)/'full'
            result = subprocess.run(self.command(s, directory, full=True), capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            records = cb.read_results(directory/'results.jsonl')
            self.assertEqual(len(records), 288)
            expected = {'loop': 'loop', 'repetition': 'repetition', 'runaway': 'runaway',
                        'token-14-flood': 'hidden-tokens', 'template-leak': 'template-leak',
                        'absent-fact': 'hallucination:q6'}
            observed = set()
            report = (directory/'report.md').read_text()
            for r in records:
                canned = r['response']['ctx_bugs_canned']
                if canned == 'clean':
                    self.assertEqual(r['flags'], [], r['key'])
                else:
                    self.assertIn(expected[canned], r['flags'], r['key'])
                    observed.add(canned)
                    self.assertIn(r['cell'], report)
                    self.assertIn(expected[canned], report)
                self.assertFalse(r['settings']['cache_prompt'])
                cb.fit_check(r['prompt_tokens'], r['size'])
                if r['prompt'] == 'F':
                    self.assertEqual(r['prompt_tokens'], r['size']-cb.BUDGET-cb.MARGIN)
            self.assertEqual(observed, set(expected))
            manifest = json.loads((directory/'run.json').read_text())
            self.assertEqual(manifest['restore_model'], stub.INITIAL_MODEL)
            self.assertEqual(manifest['restored_model'], stub.INITIAL_MODEL)
            self.assertEqual(len(manifest['cells']), 16)
            self.assertEqual(len(manifest['fill_prompts']), 8)
            for cell, data in manifest['cells'].items():
                if 'laguna' in cell and 'nathanw' in cell:
                    own = [r for r in records if r['cell'] == cell]
                    self.assertEqual(len(own), 6)
                    self.assertTrue(all(r['settings']['max_tokens'] == 2048 for r in own))
                    self.assertIn('hidden-tokens', data['probe']['flags'])
            for model in cb.MODELS:
                for size in cb.SIZES:
                    hashes = {r['prompt_sha256'] for r in records if r['model']==model and r['size']==size and r['prompt']=='F'}
                    self.assertEqual(len(hashes), 1)
            self.assertEqual(s.loads[-1], stub.INITIAL_MODEL)


if __name__ == '__main__':
    unittest.main()
