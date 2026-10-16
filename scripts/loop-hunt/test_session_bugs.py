import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import gen_sessions as gs
import session_bugs as sb
from session_stub import SessionStub
import session_tools as tools


@contextlib.contextmanager
def server(**kwargs):
    stub=SessionStub(**kwargs)
    thread=threading.Thread(target=stub.serve_forever,daemon=True)
    thread.start()
    try:yield stub
    finally:
        stub.shutdown()
        stub.server_close()
        thread.join(5)


class SessionHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.fixtures=self.root/'fixtures'
        gs.generate(self.fixtures,turns=6,chars=3500)

    def runner(self,stub,condition='C1',extra=(),name='run'):
        return sb.SessionRun(sb.parse_args(['--dry-run','--base-url',stub.url,
            '--entry','qwen3.8-flash-next-q4-nathanw-sess131k',
            '--condition',condition,'--session-dir',str(self.fixtures),
            '--run-dir',str(self.root/name),'--max-turns','3',*extra]))

    def execute(self,run):
        with contextlib.redirect_stdout(io.StringIO()):return run.execute()

    def test_long_prompt_timeout_boundary_and_transport_isolation(self):
        for count,expected in ((199999,1800),(200000,1800),(200001,7200),(250110,7200)):
            self.assertEqual(sb.completion_timeout(count,1800),expected)
        with server() as stub:
            run=self.runner(stub,extra=['--max-turns','1','--checkpoint-tokens','999999'])
            with mock.patch.object(run.client.opener,'open',wraps=run.client.opener.open) as opened:
                self.assertEqual(self.execute(run),0)
            requests=[c for c in opened.call_args_list if c.args[0].full_url.endswith('/v1/chat/completions')]
            self.assertEqual(len(requests),1)
            self.assertEqual(requests[0].kwargs['timeout'],1800)
            self.assertEqual(run.records[0]['client_timeout'],1800)
            self.assertEqual(run.client.timeout,1800)

    def test_long_completion_timeout_does_not_change_management_timeout(self):
        client=sb.SessionClient('http://127.0.0.1:1',timeout=1800)
        for stream in (False,True):
            with self.subTest(stream=stream),mock.patch.object(client.opener,'open',side_effect=TimeoutError('test timeout')) as opened:
                with self.assertRaises(TimeoutError):client.complete({'stream':stream},timeout=7200)
                self.assertEqual(opened.call_args.kwargs['timeout'],7200)
                self.assertEqual(client.timeout,1800)
        with mock.patch.object(client.opener,'open',side_effect=TimeoutError('management')) as opened:
            with self.assertRaises(TimeoutError):client.call('/health')
            self.assertEqual(opened.call_args.kwargs['timeout'],1800)

    def test_measure_uses_loaded_prompt_count_for_long_timeout(self):
        with server() as stub:
            run=self.runner(stub)
            run.prepare()
            fixture=run.fixtures[1][0]
            messages=[dict(role='system',content=run.system),dict(role='user',content=fixture['user'])]
            with mock.patch.object(run.client,'count',return_value=250110),mock.patch.object(run.client.opener,'open',wraps=run.client.opener.open) as opened:
                row=run.measure('seed-1',1,messages,fixture)
            requests=[c for c in opened.call_args_list if c.args[0].full_url.endswith('/v1/chat/completions')]
            self.assertEqual(requests[0].kwargs['timeout'],7200)
            self.assertEqual(row['client_timeout'],7200)
            self.assertEqual(row['payload']['messages'],messages)
            self.assertEqual(run.client.timeout,1800)

    def test_warm_only_loop_classifies_runtime_and_payloads_match(self):
        with server(loop_mode='warm') as stub:
            run=self.runner(stub,extra=['--checkpoint-tokens','1800'])
            self.assertEqual(self.execute(run),0,run.manifest)
            pairs=list(run.manifest['checkpoints'].values())
            self.assertEqual(len(pairs),1)
            self.assertEqual(pairs[0]['classification'],'runtime (warm only)')
            self.assertTrue(pairs[0]['identical_request_except_cache'])
            cold=next(r for r in run.records if r['mode']=='cold')
            self.assertFalse(cold['payload']['cache_prompt'])
            for request in stub.requests:
                for key in ('temperature','top_p','top_k','min_p','id_slot'):self.assertNotIn(key,request)
                self.assertFalse(any('reasoning_content' in m for m in request['messages']))
            self.assertTrue(run.manifest['restored_default'])

    def test_loop_present_warm_and_cold_classifies_model_content(self):
        with server(loop_mode='both') as stub:
            run=self.runner(stub,extra=['--checkpoint-tokens','1800'])
            self.assertEqual(self.execute(run),0)
            self.assertEqual(next(iter(run.manifest['checkpoints'].values()))['classification'],'model/content')

    def test_resume_retries_only_interrupted_turn(self):
        with server(interrupt_request=2) as stub:
            first=self.runner(stub,extra=['--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(first),1)
            self.assertEqual([r['turn'] for r in first.records],[1])
            saved=(first.directory/'results.jsonl').read_bytes()
            resumed=self.runner(stub,extra=['--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(resumed),0,resumed.manifest)
            self.assertEqual([r['turn'] for r in resumed.records],[1,2,3])
            turns=[int(request['messages'][-1]['content'].split('EVIDENCE TURN ')[1].split()[0]) for request in stub.requests]
            self.assertEqual(turns,[1,2,2,3])
            self.assertGreater(len(resumed.records[-1]['payload']['messages']),len(resumed.records[0]['payload']['messages']))
            self.assertEqual(len({r['key'] for r in resumed.records}),len(resumed.records))
            self.assertTrue((resumed.directory/'results.jsonl').read_bytes().startswith(saved))

    def test_c2_four_concurrent_requests_shared_pool_eviction(self):
        with server(capacity=5000,overflow='truncate',pool_full='evict',request_delay=.05) as stub:
            run=self.runner(stub,'C2',extra=['--sessions','1','2','3','4','--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(run),0,run.manifest)
            self.assertEqual(stub.max_inflight,4)
            self.assertEqual(len(run.records),12)
            self.assertTrue(stub.pool_events)
            self.assertTrue(all(event['behavior']=='evict' for event in stub.pool_events))
            self.assertTrue(all('id_slot' not in request for request in stub.requests))

    def test_c2_resume_keeps_other_completed_requests(self):
        with server(interrupt_request=2,request_delay=.03) as stub:
            extra=['--sessions','1','2','3','4','--checkpoint-tokens','999999','--max-turns','2']
            first=self.runner(stub,'C2',extra=extra)
            self.assertEqual(self.execute(first),1)
            self.assertEqual(len(first.records),3)
            complete_keys={r['key'] for r in first.records}
            resumed=self.runner(stub,'C2',extra=extra)
            self.assertEqual(self.execute(resumed),0,resumed.manifest)
            self.assertEqual(len(resumed.records),8)
            self.assertTrue(complete_keys.issubset(resumed.done))
            self.assertEqual(len(stub.requests),9)

    def test_kernel_capture_failure_is_nonfatal(self):
        with server(kernel_log_error=True) as stub:
            run=self.runner(stub,extra=['--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(run),0)
            self.assertTrue(all('kernel window' in r['evidence_error'] for r in run.records))
            self.assertTrue(all(not r['flags'] for r in run.records))

    def test_tool_template_ignoring_tools_refuses_measurement(self):
        with server() as stub:
            client=sb.SessionClient(stub.url)
            original=client.call
            def ignore(path,payload=None,**kwargs):
                if path=='/apply-template':payload={k:v for k,v in payload.items() if k!='tools'}
                return original(path,payload,**kwargs)
            client.call=ignore
            with self.assertRaisesRegex(ValueError,'ignored tools'):
                client.count([dict(role='user',content='fixture')],tools.schemas())

    def test_c5_counts_complete_tool_exchange_under_upstream_prefill_rules(self):
        with server() as stub:
            run=self.runner(stub,'C5',extra=['--max-turns','2'])
            self.assertEqual(self.execute(run),0,run.manifest)
            self.assertEqual(len(run.records),4)
            self.assertTrue(all(p['messages'][-1]['role']!='assistant' for p in stub.template_probes))
            tool_probes=[p for p in stub.template_probes if p['messages'][-1]['role']=='tool']
            self.assertTrue(tool_probes)
            self.assertTrue(any('audit' not in json.loads(p['messages'][-1]['content']) for p in tool_probes))
            self.assertTrue(all('audit' in json.loads(m['content']) for r in stub.requests for m in r['messages'] if m['role']=='tool'))

    def test_upstream_prefill_rejects_partial_tool_calls_for_both_generation_flags(self):
        with server() as stub:
            client=sb.SessionClient(stub.url)
            messages=[dict(role='assistant',content='',tool_calls=[dict(id='saved-call',type='function',
                           function=dict(name='list_dir',arguments='{"path":"/fixture"}'))])]
            for generation in (True,False):
                with self.subTest(generation=generation),self.assertRaises(sb.urllib.error.HTTPError) as raised:
                    client.call('/apply-template',dict(messages=messages,tools=tools.schemas(),add_generation_prompt=generation))
                self.assertEqual(raised.exception.code,400)
                self.assertIn(b'Cannot continue',raised.exception.read())
                raised.exception.close()

    def test_c3_records_http_overflow_and_truncation_separately(self):
        with server() as first_stub:
            first=self.runner(first_stub,name='c1-source',extra=['--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(first),0)
        for behavior in ('error','truncate'):
            with self.subTest(behavior=behavior),server(capacity=1000,overflow=behavior) as stub:
                run=self.runner(stub,'C3',extra=['--checkpoint-tokens','999999','--continue-from',str(self.root/'c1-source'),'--max-turns','6'],name=behavior)
                self.assertEqual(self.execute(run),0,run.manifest)
                if behavior=='error':
                    self.assertTrue(all(r['error'].startswith('HTTP 400') for r in run.records if not r.get('continued_from_c1')))
                    self.assertTrue(all('http-error' in r['flags'] and 'crash' not in r['flags'] for r in run.records if not r.get('continued_from_c1')))
                else:
                    self.assertTrue(any(r['server_prompt_tokens']<r['prompt_tokens'] for r in run.records))

    def test_layout_diff_refuses_before_inference_and_restores(self):
        with server() as stub:
            run=self.runner(stub)
            original=run.client.call
            def altered(path,*args,**kwargs):
                result=original(path,*args,**kwargs)
                if path=='/slots':result[0]['n_ctx']=32768
                return result
            run.client.call=altered
            self.assertEqual(self.execute(run),1)
            self.assertFalse(stub.requests)
            self.assertIn('slot layout differs',run.manifest['failure'])
            self.assertTrue(run.manifest['restored_default'])

    def test_resume_refuses_changed_identity(self):
        with server() as stub:
            run=self.runner(stub)
            self.assertEqual(self.execute(run),0)
            changed=self.runner(stub,extra=['--max-turns','4'])
            with self.assertRaisesRegex(ValueError,'identity changed'):changed.execute()

    def test_report_table_columns_match_and_no_clean_flags(self):
        with server() as stub:
            run=self.runner(stub,extra=['--checkpoint-tokens','1800'])
            self.assertEqual(self.execute(run),0)
            self.assertTrue(all(not r['flags'] for r in run.records))
            self.assertTrue(any(r['cached_tokens'] for r in run.records))
            lines=(run.directory/'report.md').read_text().splitlines()
            for i,line in enumerate(lines):
                if line.startswith('| ---'):self.assertEqual(line.count('|'),lines[i-1].count('|'))

    def test_c5_streaming_tools_both_budgets_and_no_real_execution(self):
        with server(request_delay=0) as stub:
            run=self.runner(stub,'C5',extra=['--max-turns','35'])
            self.assertEqual(self.execute(run),0,run.manifest)
            self.assertEqual(len(run.manifest['agent_results']),2)
            self.assertTrue(all(not r['flags'] for r in run.records))
            self.assertTrue(all(r['done'] and r['calls']==30 for r in run.manifest['agent_results'].values()))
            self.assertEqual({r['output_limit'] for r in run.manifest['agent_results'].values()},{8192,16384})
            self.assertTrue(all(request['stream'] and len(request['tools'])==40 for request in stub.requests))
            self.assertTrue(all(r['response']['choices'][0]['message']['tool_calls'][0]['function']['name']=='replace_string_in_file' for r in run.records if r['response']['choices'][0]['message'].get('tool_calls')))
            self.assertTrue(all(12000<=r['system_tokens']<=12300 and r['largest_prompt_tokens']>100000 for r in run.manifest['agent_results'].values()))
            first=run.records[0]['response']['choices'][0]['message']['tool_calls'][0]
            self.assertEqual(json.loads(first['function']['arguments'])['path'],'/fixture/module-00.txt')

    def test_replay_has_three_seeds_and_final_cold_pairs(self):
        fixture=gs.turn_fixture(1,1,chars=400)
        replay=self.root/'replay.json'
        replay.write_text(json.dumps(dict(original_tool_invocations=3,messages=[dict(role='system',content=gs.SYSTEM),dict(role='user',content=fixture['user'])])))
        with server() as stub:
            run=self.runner(stub,extra=['--replay',str(replay)])
            self.assertEqual(self.execute(run),0,run.manifest)
            self.assertEqual(len(run.records),6)
            self.assertEqual({r['seed'] for r in run.records},{1,2,3})
            self.assertEqual(run.manifest['identity']['sessions'],[1,2,3])
            self.assertEqual(len(run.manifest['checkpoints']),3)
            report=(run.directory/'report.md').read_text()
            self.assertIn('synthetic full-context condition not exercised',report)
            self.assertIn('Historical tool-loop reproduction/absence is not established',report)
            self.assertNotIn('Coverage: full configured condition',report)

    def test_regrade_uses_saved_fixture_checks(self):
        with server() as stub:
            run=self.runner(stub,extra=['--checkpoint-tokens','999999'])
            self.assertEqual(self.execute(run),0)
            original=(run.directory/'results.jsonl').read_bytes()
            original_report=(run.directory/'report.md').read_bytes()
            original_progress=(run.directory/'progress.json').read_bytes()
            self.assertEqual(sb.regrade(run.directory),3)
            rows=json.loads((run.directory/'regraded.json').read_text())
            self.assertTrue(all(all(q['correct'] for q in r['recall']) for r in rows))
            backups=list((run.directory/'regrade-backups').iterdir())
            self.assertEqual(len(backups),1)
            self.assertEqual((backups[0]/'results.jsonl').read_bytes(),original)
            self.assertEqual((backups[0]/'report.md').read_bytes(),original_report)
            self.assertEqual((backups[0]/'progress.json').read_bytes(),original_progress)
            self.assertEqual((run.directory/'progress.json').read_bytes(),original_progress)
            self.assertTrue((backups[0]/'raw'/'seed-1-1-warm.json').exists())
            self.assertEqual(sb.regrade(run.directory),3)
            self.assertEqual(len(list((run.directory/'regrade-backups').iterdir())),2)
            self.assertEqual((backups[0]/'results.jsonl').read_bytes(),original)
            self.assertEqual((run.directory/'progress.json').read_bytes(),original_progress)


class RecallGradingTests(unittest.TestCase):
    def grade(self,answer,turn=11):
        response=dict(choices=[dict(message=dict(content=answer),finish_reason='stop')],
                      usage=dict(completion_tokens=40))
        return sb.grade(response,gs.turn_fixture(1,turn),40,[])

    def test_real_pilot_single_line_answers_keep_correct_recall(self):
        # Exact synthetic answers saved by the live pilot, turns 11 and 12.
        cases=[(11,'[TRIAGE] Q1: route-01-011-375356627d Q2: route-01-005-3c7a49ef44 ref: INC-7001'),
               (12,'[TRIAGE] Q1: route-01-012-f514b6847f Q2: route-01-009-eefca04ea9 Q3: NOT PROVIDED ref: INC-7001')]
        for turn,answer in cases:
            with self.subTest(turn=turn):
                result=self.grade(answer,turn)
                self.assertTrue(all(q['correct'] for q in result['recall']))
                self.assertEqual(result['flags'],['if-fail:question_lines'])

    def test_multiline_correct_answers_are_clean(self):
        result=self.grade('[TRIAGE] Q1: route-01-011-375356627d\nQ2: route-01-005-3c7a49ef44\nref: INC-7001')
        self.assertEqual(result['flags'],[])

    def test_real_glm_c2_comma_separators_do_not_change_recalled_values(self):
        # Exact saved synthetic answer: GLM C2, seed 3, turn 10 cold.
        answer='[TRIAGE] Q1: route-03-010-4a8cbec708, Q2: route-03-001-acfa5474c2, ref: INC-7003'
        response=dict(choices=[dict(message=dict(content=answer),finish_reason='stop')],usage=dict(completion_tokens=40))
        result=sb.grade(response,gs.turn_fixture(3,10),40,[])
        self.assertTrue(all(q['correct'] for q in result['recall']))
        self.assertEqual(result['flags'],['if-fail:question_lines'])
        result=sb.grade(dict(response,choices=[dict(message=dict(content=answer.replace('Q1: route-03-010-4a8cbec708','Q1: wrong')),finish_reason='stop')]),gs.turn_fixture(3,10),40,[])
        self.assertIn('wrong:q1',result['flags'])
        self.assertNotIn('wrong:q2',result['flags'])

    def test_comma_delimiters_keep_absent_facts_and_exact_matching(self):
        fixture=gs.turn_fixture(1,12)
        answer='[TRIAGE] '+', '.join('Q%d: %s'%(i,v) for i,v in enumerate(fixture['expected'],1))+', ref: '+fixture['reference']
        result=self.grade(answer,12)
        self.assertTrue(all(q['correct'] for q in result['recall']))
        self.assertEqual(result['flags'],['if-fail:question_lines'])
        for suffix in (', extra',','):
            changed=answer.replace('Q1: '+fixture['expected'][0],'Q1: '+fixture['expected'][0]+suffix)
            self.assertIn('wrong:q1',self.grade(changed,12)['flags'])

    def test_real_previous_build_repeated_triage_prefix_is_not_an_answer_suffix(self):
        # Exact synthetic answer from fork-previous C1 seed 1, turn 1.
        answer='[TRIAGE] Q1: route-01-001-3a1d47a406\n[TRIAGE] Q2: route-01-001-3a1d47a406\nref: INC-7001'
        result=self.grade(answer,1)
        self.assertTrue(all(q['correct'] for q in result['recall']))
        self.assertEqual(result['flags'],[])
        wrong=self.grade(answer.replace('Q1: route-01-001-3a1d47a406','Q1: wrong'),1)
        self.assertIn('wrong:q1',wrong['flags'])
        self.assertNotIn('wrong:q2',wrong['flags'])
        # Exact turns 24/27 also repeat the prefix before the final reference;
        # the old extractor incorrectly called their NOT PROVIDED hallucinated.
        for turn,answer in ((24,'[TRIAGE] Q1: route-01-024-2a0bc25c73\n[TRIAGE] Q2: route-01-021-d5317f516e\n[TRIAGE] Q3: NOT PROVIDED\n[TRIAGE] ref: INC-7001'),
                            (27,'[TRIAGE] Q1: route-01-027-b2290fe7f7\n[TRIAGE] Q2: route-01-024-2a0bc25c73\n[TRIAGE] Q3: NOT PROVIDED\n[TRIAGE] ref: INC-7001')):
            with self.subTest(turn=turn):
                result=self.grade(answer,turn)
                self.assertTrue(all(q['correct'] for q in result['recall']))
                self.assertEqual(result['flags'],[])

    def test_wrong_values_remain_wrong_on_single_line(self):
        result=self.grade('[TRIAGE] Q1: wrong Q2: route-01-005-3c7a49ef44 ref: INC-7001')
        self.assertIn('wrong:q1',result['flags'])
        self.assertNotIn('wrong:q2',result['flags'])
        self.assertIn('if-fail:question_lines',result['flags'])

    def test_duplicate_missing_and_extra_labels_fail_layout(self):
        for text in ('Q1: route-01-011-375356627d\nQ1: wrong',
                     'Q1: route-01-011-375356627d',
                     'Q1: route-01-011-375356627d\nQ2: route-01-005-3c7a49ef44\nQ3: extra'):
            with self.subTest(text=text):
                result=self.grade('[TRIAGE] '+text+'\nref: INC-7001')
                self.assertIn('if-fail:question_lines',result['flags'])
        duplicate=self.grade('[TRIAGE] Q1: route-01-011-375356627d\nQ1: wrong\nref: INC-7001')
        self.assertFalse(duplicate['recall'][0]['correct'])

    def test_exact_matching_does_not_accept_explanations_or_substrings(self):
        result=self.grade('[TRIAGE] Q1: route-01-011-375356627d extra\nQ2: prefix-route-01-005-3c7a49ef44\nref: INC-7001')
        self.assertTrue(all(not q['correct'] for q in result['recall']))
        self.assertNotIn('if-fail:question_lines',result['flags'])


class AgentChecksTests(unittest.TestCase):
    def test_refused_request_cannot_be_compared_with_a_flagged_answer(self):
        # Real C2 refusal shape combined with the pilot's formatting flag.
        refused=dict(flags=['http-error'],error='HTTP 500: Context size has been exceeded.')
        answered=dict(flags=['if-fail:question_lines'],cached_tokens=10)
        for warm,cold in ((refused,answered),(answered,refused)):
            with self.subTest(warm=warm):
                self.assertEqual(sb.classify(warm,cold),'not comparable (request refused)')

    def response(self,name='read_file',arguments='{}',content=''):
        return dict(choices=[dict(message=dict(content=content,tool_calls=[dict(function=dict(name=name,arguments=arguments))]),finish_reason='tool_calls')])

    def test_tool_repeat_and_malformed_and_reasoning_channels(self):
        previous,streak=None,0
        for _ in range(3):flags,previous,streak=tools.checks(self.response(),previous,streak)
        self.assertIn('tool-repeat',flags)
        self.assertNotIn('tool-repeat',tools.checks(self.response(arguments='{"path":"changed"}'),previous,streak)[0])
        self.assertIn('tool-malformed',tools.checks(self.response(arguments='{broken'))[0])
        self.assertIn('reasoning-in-arguments',tools.checks(self.response(arguments='<think>reason'))[0])
        self.assertIn('reasoning-in-content',tools.checks(self.response(content='<think>reason'))[0])
        self.assertNotIn('reasoning-in-content',tools.checks(self.response(content='Clean answer'))[0])

    def test_different_warm_cold_failures_do_not_establish_shared_cause(self):
        self.assertEqual(sb.classify(dict(flags=['loop'],cached_tokens=10),dict(flags=['template-leak'])),
                         'not attributable (different failure modes)')

    def test_no_cache_or_crash_does_not_establish_runtime_or_model_cause(self):
        self.assertEqual(sb.classify(dict(flags=['loop'],cached_tokens=0),dict(flags=[])),
                         'not attributable (warm cache unconfirmed)')
        self.assertEqual(sb.classify(dict(flags=['crash']),dict(flags=['crash'])),
                         'not comparable (server failure)')

    def test_terminal_does_not_run_and_tree_isolated(self):
        tree=tools.initial_tree()
        before=copy.deepcopy(tree)
        result,_=tools.execute(dict(function=dict(name='run_in_terminal',arguments=json.dumps(dict(command='never execute anything')))),tree)
        self.assertTrue(result['synthetic'])
        self.assertEqual(tree,before)
        result,_=tools.execute(dict(function=dict(name='create_file',arguments=json.dumps(dict(path='/outside',content='ignored')))),tree)
        self.assertIn('error',result)
        self.assertEqual(tree,before)


if __name__=='__main__':unittest.main()
