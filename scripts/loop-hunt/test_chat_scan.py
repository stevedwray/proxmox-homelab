"""Synthetic private-chat fixtures only; no production/database access."""
import contextlib
import io
import json
import math
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock

import scan_openwebui as scan
import snapshot_sqlite as snap


REPEATED = 'The amber release requires the maple switch to remain closed until the cedar ticket is verified. '


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.live = self.root/'live #1.db'
        self.destination = self.root/'copy.db'
        self.connection = sqlite3.connect(self.live)
        self.addCleanup(self.connection.close)
        self.connection.execute('PRAGMA journal_mode=WAL')
        self.connection.execute('PRAGMA wal_autocheckpoint=0')
        self.connection.execute('CREATE TABLE fixture (value TEXT)')
        self.connection.commit()
        self.connection.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def test_snapshot_includes_committed_wal_rows_and_integrity(self):
        main_before = self.live.read_bytes()
        self.connection.execute("INSERT INTO fixture VALUES ('committed in WAL')")
        self.connection.commit()
        self.assertEqual(self.live.read_bytes(), main_before)
        self.assertGreater(Path(str(self.live)+'-wal').stat().st_size, 0)
        wal_before = Path(str(self.live)+'-wal').read_bytes()
        snap.snapshot(self.live, self.destination)
        with contextlib.closing(snap.read_only(self.destination)) as check:
            self.assertEqual(check.execute('SELECT * FROM fixture').fetchall(), [('committed in WAL',)])
            self.assertEqual(check.execute('PRAGMA integrity_check').fetchall(), [('ok',)])
        self.assertEqual(self.live.read_bytes(), main_before)
        self.assertEqual(Path(str(self.live)+'-wal').read_bytes(), wal_before)
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o600)
        self.assertFalse(Path(str(self.destination)+'-wal').exists())
        self.assertFalse(Path(str(self.destination)+'-shm').exists())

    def test_read_only_source_rejects_writes(self):
        with contextlib.closing(snap.read_only(self.live)) as connection:
            with self.assertRaises(sqlite3.OperationalError):
                connection.execute("INSERT INTO fixture VALUES ('forbidden')")

    def test_uncommitted_rows_are_not_in_snapshot(self):
        writer = sqlite3.connect(self.live)
        try:
            writer.execute("INSERT INTO fixture VALUES ('uncommitted')")
            snap.snapshot(self.live, self.destination)
            with contextlib.closing(snap.read_only(self.destination)) as check:
                self.assertEqual(check.execute('SELECT * FROM fixture').fetchall(), [])
        finally:
            writer.rollback()
            writer.close()

    def test_refuses_existing_destination_same_source_and_symlink(self):
        self.destination.write_text('keep')
        with self.assertRaises(FileExistsError):
            snap.snapshot(self.live, self.destination)
        self.assertEqual(self.destination.read_text(), 'keep')
        with self.assertRaises(ValueError):
            snap.snapshot(self.live, self.live)
        link = self.root/'link.db'
        link.symlink_to(self.destination)
        with self.assertRaises(FileExistsError):
            snap.snapshot(self.live, link)
        self.assertEqual(self.destination.read_text(), 'keep')

    def test_refuses_stale_sidecar_without_touching_it(self):
        sidecar = Path(str(self.destination)+'-wal')
        sidecar.write_text('keep old sidecar')
        with self.assertRaises(FileExistsError):
            snap.snapshot(self.live, self.destination)
        self.assertFalse(self.destination.exists())
        self.assertEqual(sidecar.read_text(), 'keep old sidecar')

    def test_invalid_or_missing_source_leaves_no_snapshot(self):
        invalid = self.root/'invalid.db'
        invalid.write_text('not SQLite')
        for source in (invalid, self.root/'missing.db'):
            with self.subTest(source=source.name), self.assertRaises((sqlite3.Error, OSError)):
                snap.snapshot(source, self.destination)
            self.assertFalse(self.destination.exists())

    def test_integrity_failure_and_timeout_remove_snapshot(self):
        bad = mock.Mock()
        bad.execute.return_value.fetchall.return_value = [('damaged',)]
        with mock.patch.object(snap, 'read_only', side_effect=[sqlite3.connect(self.live), bad]):
            with self.assertRaisesRegex(ValueError, 'integrity'):
                snap.snapshot(self.live, self.destination)
        self.assertFalse(self.destination.exists())
        with self.assertRaises(TimeoutError):
            snap.snapshot(self.live, self.destination, timeout=-1)
        self.assertFalse(self.destination.exists())


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.database = self.root/'webui.db.copy'
        self.out = self.root/'out'
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('CREATE TABLE chat (id TEXT PRIMARY KEY, chat TEXT, created_at INTEGER)')

    def add(self, name, chat):
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute('INSERT INTO chat VALUES (?, ?, ?)', (name, json.dumps(chat), 1792022400))

    def hits(self):
        return [json.loads(line) for line in (self.out/'hits.jsonl').read_text().splitlines()]

    def test_fixture_loop_and_clean_chat_parameters_and_summary(self):
        self.add('clean-private-id', dict(models=['clean-model'], messages=[
            dict(role='user', content='A private clean question'),
            dict(role='assistant', content='A short distinct clean answer', model='clean-model')]))
        user = dict(id='u', role='user', content='Which release is safe?', parentId=None)
        answer = dict(id='a', role='assistant', content='Intro. '+REPEATED*8, parentId='u',
                      model='qwen3.8-flash-next-q4-nathanw', timestamp=1792022400,
                      params=dict(temperature=.7, seed=2))
        self.add('loop-private-id', dict(history=dict(messages=dict(u=user, a=answer)),
                                        messages=[user, answer], params=dict(top_p=.9)))
        original = self.database.read_bytes()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(scan.main(['--db', str(self.database), '--out', str(self.out)]), 0)
        self.assertNotIn('private', output.getvalue())
        self.assertNotIn(REPEATED, output.getvalue())
        self.assertIn('SCAN-OK', output.getvalue())
        self.assertEqual(self.database.read_bytes(), original)
        hits = self.hits()
        self.assertEqual(len(hits), 1)  # history map + flat list are not double counted.
        hit = hits[0]
        self.assertEqual(hit['flags'], ['loop', 'repetition'])
        self.assertEqual(hit['message_index'], 1)
        self.assertEqual(hit['model_id'], answer['model'])
        self.assertEqual(hit['timestamp'], answer['timestamp'])
        self.assertEqual(hit['request_parameters'], dict(chat=dict(params=dict(top_p=.9)),
                                                       message=dict(params=dict(temperature=.7, seed=2))))
        self.assertEqual(hit['estimated_history_tokens'], math.ceil((len(user['content'])+len(answer['content']))/3.5))
        self.assertEqual(hit['excerpt'], answer['content'][hit['excerpt_offset']:hit['excerpt_offset']+400])
        self.assertLessEqual(len(hit['excerpt']), 400)
        summary = (self.out/'summary.md').read_text()
        for label in ('Chats: 2.', 'Assistant messages: 2.', 'Flagged messages: 1.', 'By model id',
                      'By month', 'By estimated history size', '2026-10', '<32k', 'clean-model'):
            self.assertIn(label, summary)
        self.assertNotIn('loop-private-id', summary)
        self.assertNotIn(REPEATED, summary)
        for path in (self.out, self.out/'summary.md', self.out/'hits.jsonl'):
            self.assertEqual(path.stat().st_mode & 0o077, 0)

    def test_branch_lengths_do_not_include_other_branches(self):
        messages = {'u': dict(role='user', content='source', parentId=None),
                    'a': dict(role='assistant', content=REPEATED*5, parentId='u', model='first'),
                    'b': dict(role='assistant', content=REPEATED*6, parentId='u', model='second')}
        self.add('branches', dict(history=dict(messages=messages)))
        scan.scan(self.database, self.out)
        self.assertEqual(len(self.hits()), 2)
        self.assertEqual([hit['estimated_history_tokens'] for hit in self.hits()],
                         [math.ceil((6+len(messages[key]['content']))/3.5) for key in ('a', 'b')])

    def test_broken_and_cyclic_history_are_reported_unknown(self):
        self.add('broken', dict(history=dict(messages={
            'a': dict(role='assistant', parentId='missing', content=REPEATED*5),
            'b': dict(role='assistant', parentId='b', content=REPEATED*5)})))
        scan.scan(self.database, self.out)
        self.assertTrue(all(hit['estimated_history_tokens'] is None for hit in self.hits()))
        self.assertIn('broken/cyclic parent links: 2', (self.out/'summary.md').read_text())

    def test_marker_hits_and_reasoning_are_separate(self):
        self.add('markers', dict(messages=[dict(role='assistant', model='stored-model',
                     content='Safe short answer', reasoning_content='Reasoning 〈| <think>')]))
        scan.scan(self.database, self.out)
        hit = self.hits()[0]
        self.assertEqual(hit['flags'], ['hidden-token-string', 'template-leak'])
        self.assertEqual(hit['excerpt_channel'], 'reasoning_content')
        self.assertEqual(hit['details']['reasoning_content']['flags'], hit['flags'])
        self.assertIn('invisible token floods cannot be inferred', (self.out/'summary.md').read_text())

    def test_repetition_shingle_with_no_exact_loop(self):
        text = '\n'.join(f'{REPEATED}Unique variation number {i}.' for i in range(7))
        flags, checks, _, excerpt = scan.detect_text(text)
        self.assertIn('repetition', flags)
        self.assertNotIn('loop', flags)
        self.assertIn('shingle', checks)
        self.assertIn('amber release', excerpt)

    def test_markers_and_clean_negatives(self):
        for marker in scan.MARKERS:
            self.assertIn('template-leak', scan.detect_text('prefix '+marker+' suffix')[0])
        self.assertEqual(scan.detect_text('A unique clean answer.')[0], [])

    def test_content_blocks_model_fallback_and_unknown_timestamp(self):
        self.add('blocks', dict(models=['one-model'], messages=[dict(role='assistant',
                 content=[dict(type='text', text=REPEATED*5), dict(type='image_url', image_url='never read')],
                 timestamp='invalid')]))
        scan.scan(self.database, self.out)
        self.assertEqual(self.hits()[0]['model_id'], 'one-model')
        self.assertIn('unknown', (self.out/'summary.md').read_text())

    def test_bad_json_or_schema_publishes_no_outputs(self):
        with contextlib.closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("INSERT INTO chat VALUES ('bad', 'invalid JSON', 0)")
        with self.assertRaises(ValueError):
            scan.scan(self.database, self.out)
        self.assertEqual(list(self.out.iterdir()), [])
        empty = self.root/'empty.db'
        with contextlib.closing(sqlite3.connect(empty)):
            pass
        with self.assertRaises(ValueError):
            scan.scan(empty, self.out)
        self.assertEqual(list(self.out.iterdir()), [])

    def test_repeated_scan_and_open_permissions_refuse_without_overwriting(self):
        self.add('clean', dict(messages=[]))
        scan.scan(self.database, self.out)
        before = {path.name: path.read_bytes() for path in self.out.iterdir()}
        with self.assertRaises(FileExistsError):
            scan.scan(self.database, self.out)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.out.iterdir()})
        public = self.root/'public'
        public.mkdir(mode=0o755)
        with self.assertRaises(ValueError):
            scan.scan(self.database, public)
        self.assertEqual(list(public.iterdir()), [])

    def test_utc_month_and_history_buckets(self):
        self.assertEqual(scan.month('2026-11-01T00:30:00+01:00'), '2026-10')
        self.assertEqual(scan.month(1792022400000), '2026-10')
        self.assertEqual([scan.bucket(n) for n in (0, 32768, 65536, 98304, 131072, 262144)],
                         ['<32k', '32k–64k', '64k–96k', '96k–131k', '131k–262k', '>=262k'])


if __name__ == '__main__':
    unittest.main()
