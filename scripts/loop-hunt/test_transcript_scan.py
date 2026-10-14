"""Synthetic saved transcripts matching the repository's producers."""
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

import scan_openwebui as scanner
from transcript_scan import scan_transcripts

REPEAT = 'The amber release requires the maple switch to remain closed until the cedar ticket is verified. '


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)/'inputs'
        self.root.mkdir()
        self.out = Path(self.tmp.name)/'out'

    def write(self, relative, value, jsonl=False):
        path = self.root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(''.join(json.dumps(row)+'\n' for row in value) if jsonl else json.dumps(value))
        return path

    def hits(self):
        return [json.loads(line) for line in (self.out/'hits.jsonl').read_text().splitlines()]

    def test_lm_eval_raw_generations_not_filtered_duplicates_and_recorded_identity(self):
        self.write('run/run.json', dict(run='recorded-run', created_utc='2026-10-14T00:00:00Z', max_gen_toks=8192,
                    server=dict(model_id='qwen-target', props=dict(model_alias='qwen-alias', build_info='build-123'))))
        self.write('run/model/samples_ifeval_stamp.jsonl', [
            dict(resps=[[REPEAT*8]], filtered_resps=[REPEAT*8], arguments=[['PRIVATE prompt']]),
            dict(resps=[['A clean distinct answer.']], filtered_resps=[REPEAT*8], arguments=[['PRIVATE prompt']])], True)
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        result = scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(result['responses'], 2)
        self.assertEqual(result['degeneration'], 1)
        hit = self.hits()[0]
        self.assertIn('loop', hit['flags'])
        self.assertEqual(hit['model_id'], 'qwen-target')
        self.assertEqual(hit['model_alias'], 'qwen-alias')
        self.assertEqual(hit['build_info'], 'build-123')
        self.assertEqual(hit['run_id'], 'recorded-run')
        self.assertEqual(hit['token_cap'], 8192)
        self.assertEqual(hit['settings']['run']['max_gen_toks'], 8192)
        self.assertGreater(hit['estimated_prompt_tokens'], 0)
        self.assertLessEqual(len(hit['excerpt']), 400)
        self.assertNotIn('PRIVATE prompt', (self.out/'hits.jsonl').read_text())
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_lm_eval_filtered_fallback_results_metadata_and_settings_redaction(self):
        self.write('results_stamp.json', dict(config=dict(model_args='model=glm-target,api_key=PRIVATE-KEY',
                         gen_kwargs='max_gen_toks=8192,temperature=0'), date='2026-10-01'))
        self.write('samples_gpqa_stamp.jsonl', [dict(filtered_resps=[REPEAT*5], parameters=dict(seed=42, api_key='PRIVATE-KEY'))], True)
        scan_transcripts(self.root, self.out, 'lm-eval')
        hit = self.hits()[0]
        self.assertEqual(hit['model_id'], 'glm-target')
        self.assertEqual(hit['token_cap'], 8192)
        self.assertEqual(hit['settings']['response.parameters'], dict(seed=42))
        self.assertNotIn('PRIVATE-KEY', (self.out/'hits.jsonl').read_text())
        self.assertIn('2026-10', (self.out/'summary.md').read_text())

    def test_cap_exhaustion_requires_limit_evidence_and_no_final_answer(self):
        self.write('run.json', dict(max_tokens=10, server=dict(model_id='target')))
        self.write('samples_task_stamp.jsonl', [
            dict(resps=[[dict(choices=[dict(message=dict(content='', reasoning_content='Short reasoning'), finish_reason='length')], usage=dict(completion_tokens=10))]]),
            dict(resps=[[dict(content='', reasoning_content='More reasoning')]], usage=dict(completion_tokens=10)),
            dict(resps=[['']]),  # Empty text alone does not prove budget exhaustion.
            dict(resps=[[dict(choices=[dict(message=dict(content='Final answer'), finish_reason='length')], usage=dict(completion_tokens=10))]])], True)
        result = scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(result['responses'], 4)
        self.assertEqual(result['cap_exhausted'], 2)
        self.assertEqual(result['degeneration'], 0)
        self.assertEqual(len(self.hits()), 2)
        self.assertTrue(all(hit['flags']==['cap-exhausted'] and hit['cap_only'] for hit in self.hits()))
        summary = (self.out/'summary.md').read_text()
        self.assertIn('Cap-exhausted (separate): 2', summary)
        self.assertIn('Responses without cap evidence: 1', summary)

    def test_cse_response_json_actual_model_build_and_empty_negative(self):
        self.write('run/run.json', dict(started_at='2026-09-20T00:00:00Z', backend_model='requested-model'))
        self.write('run/result.json', dict(served_model=dict(alias='actual-model', build='actual-build'), backend_model='requested-model'))
        self.write('run/responses.json', [dict(response=REPEAT*6, model='requested-model', prompt='PRIVATE PROMPT'), dict(response='')])
        self.write('run/judge_responses.json', [dict(response=REPEAT*6, judge_response=REPEAT*8)])
        result = scan_transcripts(self.root, self.out, 'cse')
        self.assertEqual(result['responses'], 2)
        self.assertEqual(result['hits'], 1)
        self.assertEqual(result['cap_exhausted'], 0)
        hit = self.hits()[0]
        self.assertEqual(hit['model_id'], 'actual-model')
        self.assertEqual(hit['build_info'], 'actual-build')
        self.assertNotIn('PRIVATE PROMPT', (self.out/'hits.jsonl').read_text())

    def test_cse_dialogue_and_operation_logs_do_not_scan_environment_or_judge(self):
        self.write('run/responses.json', [
            dict(model='target', operation_log='>>> USER: '+REPEAT*8+'>>> AI: echo done'),
            dict(attacker_model='attacker', victim_model='victim', dialogue_history='Attacker: '+REPEAT*8+'/nVictim: Clean unique answer')])
        result = scan_transcripts(self.root, self.out, 'cse')
        self.assertEqual(result['responses'], 3)
        self.assertEqual(result['hits'], 1)
        self.assertEqual(self.hits()[0]['model_id'], 'attacker')

    def test_deep_research_ui_events_pair_reasoning_and_text_without_agent_session_duplicates(self):
        data = dict(session_id='session-123', timestamp='2026-10-02T00:00:00', model_id='recorded-model',
                    agent_session=dict(duplicate_text=REPEAT*9), ui_events=[
            dict(type='prompt', source='User', data=dict(text='PRIVATE REQUEST')),
            dict(type='function_result', source='Searcher', data=dict(text=REPEAT*8)),
            dict(type='reasoning', source='Searcher', data=dict(text=REPEAT*6)),
            dict(type='text', source='Searcher', data=dict(text='Final answer')),
            dict(type='text', source='Writer', data=dict(text='Unique report text.'))])
        self.write('session_123.json', data)
        result = scan_transcripts(self.root, self.out, 'deep-research')
        self.assertEqual(result['responses'], 2)
        self.assertEqual(result['hits'], 1)
        hit = self.hits()[0]
        self.assertEqual(hit['model_id'], 'recorded-model')
        self.assertEqual(hit['run_id'], 'session-123')
        self.assertEqual(hit['excerpt_channel'], 'reasoning')
        self.assertIn('actual agent request history not recorded', hit['prompt_estimate_basis'])
        self.assertNotIn('PRIVATE REQUEST', (self.out/'hits.jsonl').read_text())

    def test_deep_research_orphan_reasoning_not_assigned_to_another_agent(self):
        self.write('session_x.json', dict(ui_events=[
            dict(type='reasoning', source='A', data=dict(text=REPEAT*6)),
            dict(type='text', source='B', data=dict(text='Clean output'))]))
        result = scan_transcripts(self.root, self.out, 'deep-research')
        self.assertEqual(result['responses'], 2)
        self.assertEqual(self.hits()[0]['model_id'], 'unknown')
        self.assertEqual(self.hits()[0]['excerpt_channel'], 'reasoning')
        self.assertEqual(result['cap_exhausted'], 0)

    def test_deep_research_invalid_json_is_coverage_gap_not_loss_of_valid_sessions(self):
        # Reproduce the production failure: valid session schema alongside an
        # incomplete persisted JSON file. Use synthetic text only.
        broken = self.root/'session_broken.json'
        broken.write_text('{"timestamp":"2026-10-15","ui_events":[')
        from transcript_scan import deep_research_records
        with self.assertRaises(json.JSONDecodeError):
            list(deep_research_records(broken, self.root))
        self.write('session_good.json', dict(ui_events=[dict(type='text', source='A', data=dict(text=REPEAT*6))]))
        before = broken.read_bytes()
        result = scan_transcripts(self.root, self.out, 'deep-research')
        self.assertEqual(result['files'], 2)
        self.assertEqual(result['unreadable_files'], 1)
        self.assertEqual(result['responses'], 1)
        self.assertEqual(result['hits'], 1)
        self.assertEqual(broken.read_bytes(), before)
        self.assertIn('Unreadable session files (invalid JSON at scan time): 1', (self.out/'summary.md').read_text())
        self.assertEqual(json.loads((self.out/'unreadable.jsonl').read_text()),
                         dict(source_file='session_broken.json', exception_class='JSONDecodeError'))
        self.assertEqual((self.out/'unreadable.jsonl').stat().st_mode & 0o077, 0)

    def test_cse_usage_length_calls_are_counted_without_guessing_response_join(self):
        self.write('run/run.json', dict(started_at='2026-10-01T00:00:00Z'))
        self.write('run/responses.json', [dict(response=''), dict(response='A final answer.')])
        self.write('run/usage.jsonl', [dict(model='target', finish_reason='length', completion_tokens=65536),
                    dict(model='judge', finish_reason='length', completion_tokens=16384),
                    dict(model='target', finish_reason='stop'), dict(model='target')], True)
        result = scan_transcripts(self.root, self.out, 'cse')
        self.assertEqual(result['usage_cap_exhausted'], 2)
        self.assertEqual(result['cap_exhausted'], 0)  # No per-response IDs to establish a join.
        self.assertEqual(result['hits'], 0)
        summary = json.loads((self.out/'usage-summary.json').read_text())
        self.assertEqual(summary['calls'], 4)
        self.assertEqual(summary['missing_finish_reason'], 1)
        self.assertEqual(summary['by_model']['target']['cap_exhausted'], 1)
        self.assertEqual(summary['by_model']['judge']['cap_exhausted'], 1)
        self.assertEqual(summary['by_month']['2026-10']['calls'], 4)
        self.assertIn('No positional join', (self.out/'summary.md').read_text())
        self.assertEqual((self.out/'usage-summary.json').stat().st_mode & 0o077, 0)

    def test_cse_producer_meta_and_manifest_supply_date_and_requested_identity(self):
        self.write('run/meta.json', dict(started_at='2026-10-01T00:00:00Z', backend_model='recorded-request'))
        self.write('run/manifest.json', dict(run_id='recorded-id', started_at='2026-09-01T00:00:00Z'))
        self.write('run/responses.json', [dict(response=REPEAT*6)])
        scan_transcripts(self.root, self.out, 'cse')
        hit = self.hits()[0]
        self.assertEqual(hit['model_id'], 'recorded-request')
        self.assertEqual(hit['model_id_source'], 'recorded requested model')
        self.assertEqual(hit['timestamp'], '2026-10-01T00:00:00Z')
        self.assertEqual(hit['run_id'], 'recorded-id')
        self.assertIn('2026-10', (self.out/'summary.md').read_text())

    def test_dialogue_victim_is_not_assigned_attacker_served_identity(self):
        self.write('run/result.json', dict(served_model=dict(alias='attacker-served', build='build-1')))
        self.write('run/responses.json', [dict(attacker_model='recorded-attacker',
                   dialogue_history='Attacker: '+REPEAT*5+'/nVictim: '+REPEAT*5)])
        scan_transcripts(self.root, self.out, 'cse')
        self.assertEqual([hit['model_id'] for hit in self.hits()], ['recorded-attacker', 'unknown'])
        self.assertTrue(all(hit['model_alias'] is None and hit['build_info'] is None for hit in self.hits()))

    def test_deep_session_date_is_fallback_for_events_without_timestamp(self):
        self.write('session_x.json', dict(timestamp='2026-09-15T12:00:00', ui_events=[
            dict(type='text', source='A', data=dict(text=REPEAT*6))]))
        scan_transcripts(self.root, self.out, 'deep-research')
        self.assertEqual(self.hits()[0]['timestamp'], '2026-09-15T12:00:00')
        self.assertIn('2026-09', (self.out/'summary.md').read_text())

    def test_bad_transcript_does_not_publish_partial_results(self):
        self.write('samples_task_stamp.jsonl', [dict(resps=[[REPEAT*6]]), dict(wrong='unsupported')], True)
        with self.assertRaises(ValueError):
            scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_empty_existing_root_reports_no_evidence_and_missing_root_refuses(self):
        with self.assertRaisesRegex(ValueError, 'root does not exist'):
            scan_transcripts(self.root/'missing', self.out, 'lm-eval')
        self.assertFalse(self.out.exists())
        result = scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(result['files'], 0)
        self.assertEqual(result['responses'], 0)
        self.assertIn('no responses evaluated', (self.out/'summary.md').read_text())
        self.assertIn('not evidence that loops did not occur', (self.out/'summary.md').read_text())

    def test_unknown_structured_response_refuses_instead_of_becoming_clean(self):
        self.write('samples_task_stamp.jsonl', [dict(resps=[[dict(unrecognized='PRIVATE')]])], True)
        with self.assertRaisesRegex(ValueError, 'unsupported structured'):
            scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_metadata_symlink_outside_root_is_not_read(self):
        outside = self.root.parent/'private.json'
        outside.write_text('do not read')
        (self.root/'run.json').symlink_to(outside)
        self.write('samples_task_stamp.jsonl', [dict(resps=[['clean']])], True)
        with self.assertRaisesRegex(ValueError, 'metadata escapes'):
            scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(list(self.out.iterdir()), [])

    def test_outputs_private_and_exclusive_and_cli_only_returns_counts(self):
        self.write('samples_task_stamp.jsonl', [dict(resps=[[REPEAT*7]])], True)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            self.assertEqual(scanner.main(['--format', 'lm-eval', '--root', str(self.root), '--out', str(self.out)]), 0)
        self.assertIn('SCAN-OK', stdout.getvalue())
        self.assertNotIn(REPEAT, stdout.getvalue())
        for path in (self.out, self.out/'hits.jsonl', self.out/'summary.md'):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        before = {path.name: path.read_bytes() for path in self.out.iterdir()}
        with self.assertRaises(ValueError):
            scan_transcripts(self.root, self.out, 'lm-eval')
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.out.iterdir()})


if __name__ == '__main__':
    unittest.main()
