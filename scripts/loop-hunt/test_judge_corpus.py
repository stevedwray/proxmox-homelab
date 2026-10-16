import json
import tempfile
import unittest
from pathlib import Path

import judge_corpus as jc


def row(answer, reasoning='', mode='warm', model='qwen-x-nathanw', last='base\nQUESTIONS\nQ1: ?'):
    return dict(key='k', session='seed-1', turn=3, mode=mode, seed=1, flags=['repetition'],
                prompt_sha256=answer + mode, error=None, answer=answer, reasoning=reasoning,
                payload=dict(messages=[dict(role='system', content='rules'),
                                       dict(role='user', content='old'),
                                       dict(role='assistant', content='prev'),
                                       dict(role='user', content=last)]),
                response=dict(model=model, choices=[dict(finish_reason='length', message={})]))


class JudgeCorpusTest(unittest.TestCase):
    def test_blind_corpus_hides_identity_and_dedupes(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / 'root'
            for run, rows in (('fork-current-C1', [row('a'), row('b', mode='cold')]),
                              ('fork-current-C3', [row('a')]), ('V9-upstream', [row('c')])):
                (root / run).mkdir(parents=True)
                (root / run / 'results.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            (root / 'x' / 'regrade-backups').mkdir(parents=True)
            (root / 'x' / 'regrade-backups' / 'results.jsonl').write_text(json.dumps(row('z')) + '\n')
            import io, contextlib
            args = type('A', (), dict(roots=[str(root)]))
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                jc.cmd_extract(args)
            recs = [json.loads(l) for l in buf.getvalue().splitlines()]
            self.assertEqual(sorted(r['answer'] for r in recs), ['a', 'b', 'c'])
            self.assertEqual(recs[0]['request'], 'QUESTIONS\nQ1: ?')
            self.assertEqual(recs[0]['prior_answer'], 'prev')
            ex = Path(d) / 'e.jsonl'
            ex.write_text(buf.getvalue())
            out = Path(d) / 'out'
            jc.cmd_build(type('B', (), dict(extract=str(ex), out=str(out), seed=1,
                                            max_records=2, max_chars=10**6)))
            blind = ''.join(p.read_text() for p in out.glob('corpus-*.jsonl'))
            for leak in ('qwen', 'nathanw', 'fork', 'upstream', 'seed-1', 'C1', 'warm', 'cold', 'repetition'):
                self.assertNotIn(leak, blind)
            self.assertEqual(len((out / 'PRIVATE-key-map.jsonl').read_text().splitlines()), 3)
            self.assertTrue((out / 'corpus-replay.jsonl').exists())


if __name__ == '__main__':
    unittest.main()
