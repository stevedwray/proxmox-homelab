"""Synthetic local Copilot fixtures: no workstation chats or credentials."""
import contextlib
import io
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

from copilot_scan import (config_models, content_tool_checks, cutoff, load_session,
                          model_for, response_parts, scan_copilot, session_paths)


class CopilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base/'User'
        self.root.mkdir()
        self.config = self.root/'chatLanguageModels.json'
        self.config.write_text(json.dumps([dict(name='Framework', apiKey='fixture-secret-value', models=[
            dict(id='qwen3.8-flash-next-q4-nathanw', url='https://user:password@framework.example/v1?api_key=fixture-secret-value',
                 maxInputTokens=131072, maxOutputTokens=4096, toolCalling=True,
                 modelOptions=dict(enableThinking=False)),
            dict(id='ordinary-model', url='https://framework.example/v1', maxInputTokens=1000,
                 maxOutputTokens=4096, thinking='off'),
        ])]))
        self.directory = self.root/'workspaceStorage'/'private-workspace'/'chatSessions'
        self.directory.mkdir(parents=True)
        self.out = self.base/'results'

    def session(self, requests, name='fixture', journal=False):
        data = dict(sessionId=name, creationDate=1792022400000,
                    inputState=dict(selectedModel=dict(id='current-not-historical')), requests=requests)
        path = self.directory/(name+('.jsonl' if journal else '.json'))
        path.write_text(json.dumps(dict(kind=0,v=data))+'\n' if journal else json.dumps(data))
        return path

    def request(self, answer='A clean answer.', **extra):
        return dict(message=dict(text='A question.'), response=[dict(value=answer)],
                    timestamp=1792022400000, modelId='historical-model', **extra)

    def scan(self):
        return scan_copilot(self.root,self.out,progress=0)

    def hits(self):
        return [json.loads(line) for line in (self.out/'hits.jsonl').read_text().splitlines()]

    def test_journal_replay_set_push_truncate_unset(self):
        path=self.directory/'journal.jsonl'
        ops=[dict(kind=0,v=dict(requests=[],temporary=True)),
             dict(kind=2,k=['requests'],v=[self.request('streamed fragment')]),
             dict(kind=1,k=['requests',0,'response'],v=[dict(value='Final answer')]),
             dict(kind=2,k=['requests'],v=[self.request('discard')]),
             dict(kind=2,k=['requests'],i=1,v=[]),dict(kind=3,k=['temporary'])]
        path.write_text(''.join(json.dumps(op)+'\n' for op in ops))
        state,partial=load_session(path)
        self.assertFalse(partial)
        self.assertNotIn('temporary',state)
        self.assertEqual(len(state['requests']),1)
        self.assertEqual(response_parts(state['requests'][0])[0],'Final answer')
        self.assertEqual(self.scan()['responses'],1)

    def test_partial_tail_and_corrupt_middle(self):
        path=self.session([self.request()],journal=True)
        with path.open('a') as out:out.write('{"kind":')
        self.assertTrue(load_session(path)[1])
        self.assertEqual(self.scan()['partial_journals'],1)
        path.write_text('{bad}\n'+json.dumps(dict(kind=0,v=dict(requests=[])))+'\n')
        with self.assertRaises(ValueError):load_session(path)

    def test_snapshot_replacement_and_no_initial_state(self):
        path=self.directory/'state.jsonl'
        path.write_text('\n'.join(json.dumps(op) for op in [dict(kind=0,v=dict(old=1)),dict(kind=0,v=dict(new=2))]))
        self.assertEqual(load_session(path),(dict(new=2),False))
        path.write_text(json.dumps(dict(kind=1,k=['a'],v=1)))
        with self.assertRaises(ValueError):load_session(path)

    def test_limits_allowlist_and_credentials(self):
        limits,secrets=config_models(self.config)
        self.assertEqual(len(limits),2)
        self.assertIn('fixture-secret-value',secrets)
        self.assertEqual(limits[0]['url'],'https://framework.example/v1')
        self.assertEqual(limits[0]['flags'],dict(toolCalling=True,**{'modelOptions.enableThinking':False}))
        self.session([self.request('<think>fixture-secret-value Authorization: Bearer other-secret')])
        self.scan()
        combined=''.join(path.read_text() for path in self.out.iterdir())
        for forbidden in ('fixture-secret-value','other-secret','private-workspace','user:password','current-not-historical'):
            self.assertNotIn(forbidden,combined)
        findings=json.loads((self.out/'client-limits.json').read_text())['findings']
        self.assertEqual([row['model_id'] for row in findings],['qwen3.8-flash-next-q4-nathanw'])

    def test_private_outputs_and_read_only_input(self):
        path=self.session([self.request('<think> leaked')])
        before=path.read_bytes()
        stdout=io.StringIO()
        with contextlib.redirect_stdout(stdout):self.scan()
        self.assertEqual(stdout.getvalue(),'')
        self.assertEqual(path.read_bytes(),before)
        self.assertEqual(stat.S_IMODE(self.out.stat().st_mode),0o700)
        for output in self.out.iterdir():self.assertEqual(stat.S_IMODE(output.stat().st_mode),0o600)
        with self.assertRaises(FileExistsError):self.scan()

    def test_clean_and_loop_repetition_leak_cutoff(self):
        repeated='The same sufficiently long sentence keeps appearing over and over. '*12
        self.session([self.request(),self.request(repeated),self.request('<think>secret reasoning</think>'),
                      self.request('Reasoning: emitted in answer'),self.request('Incomplete',isCanceled=True)])
        counts=self.scan()
        self.assertEqual(counts['responses'],5)
        self.assertEqual(counts['candidates'],4)
        self.assertEqual(len(self.hits()),4)
        self.assertIn('loop',self.hits()[0]['flags'])
        self.assertIn('repetition',self.hits()[0]['flags'])
        self.assertIn('template-leak',self.hits()[1]['flags'])
        self.assertIn('cut-off',self.hits()[3]['flags'])

    def test_dense_reasoning_only_informational(self):
        self.session([dict(response=[dict(kind='thinking',value='dense reasoning')])])
        with patch('copilot_scan.detect_text',side_effect=[([],[],0,''),(['repetition'],['zlib'],0,'dense reasoning')]):
            counts=self.scan()
        self.assertEqual(counts['candidates'],0)
        self.assertEqual(counts['flags']['dense-reasoning'],1)

    def tool(self,args=None,**extra):
        part=dict(kind='toolInvocationSerialized',toolId='fixture_tool',invocationMessage='Run fixture',**extra)
        if args is not None:part['arguments']=args
        return part

    def test_tool_repeat_exact_arguments_across_requests(self):
        requests=[dict(response=[self.tool(args)]) for args in ('{"a":1,"b":2}',dict(b=2,a=1),'{"b":2,"a":1}')]
        self.session(requests)
        counts=self.scan()
        self.assertEqual(counts['tool_repeat_responses'],1)
        self.assertEqual(self.hits()[0]['details']['tool-repeat']['consecutive'],3)

    def test_tool_repeat_negative_changed_or_missing_arguments(self):
        self.session([dict(response=[self.tool(dict(a=1)),self.tool(dict(a=2)),self.tool(),self.tool(),self.tool()])])
        counts=self.scan()
        self.assertEqual(counts['candidates'],0)
        self.assertEqual(counts['tools_without_arguments'],3)

    def test_malformed_tool_and_content_false_positive(self):
        self.assertIn('tool-malformed',content_tool_checks('<tool_call>{broken}</tool_call>')[0])
        self.assertIn('tool-malformed',content_tool_checks('<tool_call>{')[0])
        self.assertNotIn('tool-malformed',content_tool_checks('<tool_call>{"name":"f","arguments":"{}"}</tool_call>')[0])
        self.assertFalse(content_tool_checks('Here is JSON code: {"name": "f"}')[0])
        self.session([dict(response=[self.tool('{broken')])])
        self.scan()
        self.assertIn('tool-malformed',self.hits()[0]['flags'])

    def test_markdown_objects_and_reasoning_deltas(self):
        answer,thinking,tools=response_parts(dict(response=[
            dict(kind='markdownContent',content=dict(value='Final answer')),
            dict(kind='thinking',value=['first ',dict(text='second '),dict(value='third')])]))
        self.assertEqual(answer,'Final answer')
        self.assertEqual(thinking,'first second third')
        self.assertEqual(tools,[])

    def test_model_and_cutoff_do_not_guess(self):
        self.assertEqual(model_for({})[0],'unknown')
        self.assertFalse(cutoff(dict(modelState=dict(value=2))))
        self.assertTrue(cutoff(dict(result=dict(errorDetails=dict(responseIsIncomplete=True)))))
        self.assertTrue(cutoff(dict(finish_reason='length')))
        self.assertFalse(cutoff({}))

    def test_latest_journal_supersedes_old_snapshot(self):
        self.session([self.request('<think> old')])
        self.session([self.request('Clean latest')],journal=True)
        self.assertEqual(len(session_paths(self.root)),1)
        self.assertEqual(self.scan()['candidates'],0)

    def test_invalid_schema_audit_without_contents(self):
        (self.directory/'bad.jsonl').write_text('["sensitive fixture"]\n')
        self.session([self.request()])
        counts=self.scan()
        self.assertEqual(counts['unreadable_files'],1)
        self.assertNotIn('sensitive fixture',(self.out/'unreadable.jsonl').read_text())
        self.assertEqual(counts['responses'],1)


if __name__=='__main__':unittest.main()
