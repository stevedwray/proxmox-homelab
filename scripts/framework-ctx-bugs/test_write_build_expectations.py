import contextlib
import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import write_build_expectations as helper


class ExpectationsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.builds = self.root/'builds'
        self.out = self.root/'expectations.json'
        self.props = {
            'nathanw': dict(model_alias='nomic-embed-text', total_slots=1,
                           default_generation_settings=dict(n_ctx=2048), build_info='b10814-9e21f2e53'),
            'upstream': dict(model_alias='qwen3-coder-next-upstream', total_slots=4,
                            n_ctx=131072, build_info='b11514-de7fa0a3c', extra={'retained': True})}
        self.records = {
            'nathanw': dict(name='20261008-9e21f2e53', sha='9e21f2e5329c697a46fd790c0eb172d1ee2f0923'),
            'upstream': dict(name='20261008-de7fa0a3c', sha='de7fa0a3c6a2e1b4cd9f22eb8d6bf5b12dbdb63b')}
        self.args = ['--builds-root', str(self.builds), '--out', str(self.out)]
        for label, backend in helper.BACKENDS.items():
            path = self.builds/backend/'current'/'build.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(self.records[label]))
            self.save_props(label)
            self.args += ['--props', f'{label}={self.root/label}']

    def save_props(self, label):
        (self.root/label).write_text(json.dumps(self.props[label]))

    def invoke(self, args=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = helper.main(self.args if args is None else args)
        return code, stdout.getvalue(), stderr.getvalue()

    def assert_refused(self, message, args=None):
        before = sorted(p.name for p in self.root.iterdir())
        code, stdout, stderr = self.invoke(args)
        self.assertEqual(code, 1, stderr)
        self.assertEqual(stdout, '')
        self.assertIn(message, stderr)
        self.assertFalse(self.out.exists())
        self.assertEqual(sorted(p.name for p in self.root.iterdir()), before)

    def test_success_preserves_complete_props_and_prints_exact_line(self):
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, 'nathanw b10814-9e21f2e53 upstream b11514-de7fa0a3c\n')
        self.assertEqual(stderr, '')
        expected = {label: dict(self.records[label], build_info=self.props[label]['build_info'], props=self.props[label])
                    for label in helper.BACKENDS}
        self.assertEqual(json.loads(self.out.read_text()), expected)
        self.assertFalse(list(self.root.glob('.expectations.json.*')))

    def test_cli_success_with_reversed_props_argument_order(self):
        result = subprocess.run([sys.executable, str(Path(helper.__file__)), *self.args[:4],
                                 *self.args[6:8], *self.args[4:6]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'nathanw b10814-9e21f2e53 upstream b11514-de7fa0a3c\n')

    def test_refuses_missing_or_nonstring_build_info(self):
        for value in (None, 11514, {}, []):
            with self.subTest(value=value):
                self.props['upstream']['build_info'] = value
                self.save_props('upstream')
                self.assert_refused('build_info must be a string')
        del self.props['upstream']['build_info']
        self.save_props('upstream')
        self.assert_refused('build_info must be a string')

    def test_refuses_each_missing_schema_field(self):
        original = copy.deepcopy(self.props['upstream'])
        for field in ('model_alias', 'total_slots', 'n_ctx'):
            with self.subTest(field=field):
                self.props['upstream'] = dict(original)
                del self.props['upstream'][field]
                self.save_props('upstream')
                self.assert_refused(field)
        # Nested context is accepted; an absent or malformed settings object isn't.
        for settings in ({}, None, [], 'invalid'):
            with self.subTest(settings=settings):
                self.props['upstream'] = dict(original)
                del self.props['upstream']['n_ctx']
                self.props['upstream']['default_generation_settings'] = settings
                self.save_props('upstream')
                self.assert_refused('n_ctx')

    def test_refuses_mismatched_missing_or_empty_sha_suffix(self):
        for value in ('b11514-abcdef123', 'b11514', 'b11514-', ''):
            with self.subTest(value=value):
                self.props['upstream']['build_info'] = value
                self.save_props('upstream')
                self.assert_refused('SHA does not match')

    def test_refuses_missing_or_malformed_source_files(self):
        path = self.root/'upstream'
        path.unlink()
        self.assert_refused('No such file')
        path.write_text('invalid json')
        self.assert_refused('Expecting value')
        path.write_text('[]')
        self.assert_refused('must be JSON objects')
        self.save_props('upstream')
        build_path = self.builds/'upstream'/'current'/'build.json'
        build_path.unlink()
        self.assert_refused('No such file')
        build_path.write_text('invalid json')
        self.assert_refused('Expecting value')
        build_path.write_text('[]')
        self.assert_refused('must be JSON objects')

    def test_refuses_missing_or_invalid_build_metadata(self):
        path = self.builds/'upstream'/'current'/'build.json'
        for field in ('name', 'sha'):
            for value in (None, '', 123):
                with self.subTest(field=field, value=value):
                    record = dict(self.records['upstream'], **{field:value})
                    path.write_text(json.dumps(record))
                    self.assert_refused(field)
            record = dict(self.records['upstream'])
            del record[field]
            path.write_text(json.dumps(record))
            self.assert_refused(field)

    def test_refuses_missing_duplicate_or_invalid_labels(self):
        cases = [(['--props', f'nathanw={self.root/"nathanw"}'], 'both --props'),
                 (self.args[4:]+['--props', f'nathanw={self.root/"nathanw"}'], 'duplicate'),
                 (['--props', 'fork=path'], '--props must be'),
                 (['--props', 'nathanw'], '--props must be'),
                 (['--props', 'nathanw='], '--props must be')]
        for props, message in cases:
            with self.subTest(props=props):
                self.assert_refused(message, self.args[:4]+props)

    def test_never_overwrites_existing_files_directories_or_symlinks(self):
        self.out.write_text('preserve these bytes')
        code, stdout, stderr = self.invoke()
        self.assertEqual(code, 1)
        self.assertEqual(stdout, '')
        self.assertIn('refusing to overwrite', stderr)
        self.assertEqual(self.out.read_text(), 'preserve these bytes')
        self.out.unlink()
        self.out.mkdir()
        self.assertEqual(self.invoke()[0], 1)
        self.assertTrue(self.out.is_dir())
        self.out.rmdir()
        self.out.symlink_to(self.root/'missing-target')
        self.assertEqual(self.invoke()[0], 1)
        self.assertTrue(self.out.is_symlink())
        self.assertFalse((self.root/'missing-target').exists())

    def test_destination_created_during_publish_is_preserved(self):
        def competing_link(source, target):
            self.out.write_text('another writer')
            raise FileExistsError('destination appeared')
        with mock.patch.object(helper.os, 'link', side_effect=competing_link):
            self.assertEqual(self.invoke()[0], 1)
        self.assertEqual(self.out.read_text(), 'another writer')
        self.assertFalse(list(self.root.glob('.expectations.json.*')))

    def test_output_io_failure_leaves_no_output_or_temporary_file(self):
        with mock.patch.object(helper.os, 'fsync', side_effect=OSError('simulated write failure')):
            self.assert_refused('simulated write failure')


if __name__ == '__main__':
    unittest.main()
