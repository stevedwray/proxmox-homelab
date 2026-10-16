"""Exercise the shell guard with a local llama-builds stand-in; no network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('guarded_swap_config.sh')
REQUIRED = [f'{model}-{build}-ctx{size}'
            for model in ('qwen3.8-flash-next-q4', 'laguna-s-2.1')
            for build in ('nathanw', 'upstream')
            for size in ('32k', '64k', '96k', '131k')]
ORDINARY = ['qwen3.8-flash-next-q4-'+b for b in ('nathanw', 'upstream', 'hip')] + [
    'laguna-s-2.1-upstream', 'laguna-s-2.1-hip']
EXTRA = 'laguna-s-2.1-upstream-ctx131k-b512'
TOOL = '''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

def load_config():
    return json.loads(Path(os.environ['GUARD_TEST_SCENARIO']).read_text())

def load_catalog(cfg):
    return {}

def swap_cfg(cfg):
    return {'config': cfg['config']}

def swap_entries(cfg, catalog):
    return [(entry, {}) for entry in cfg['entries']]

def render_swap(cfg, entries):
    return cfg['rendered']


if __name__ == '__main__':
    cfg = load_config()
    with Path(cfg['calls']).open('a') as out:
        out.write(' '.join(sys.argv[1:]) + '\\n')
    if '--dry-run' in sys.argv:
        print(cfg['preview'])
    else:
        print('llama-swap config written: 52 entries; initial-model loaded again')
'''


class GuardTests(unittest.TestCase):
    def run_guard(self, *, unchanged=False, entries=None, extra=False,
                  mismatch=False, missing_config=False, wrong_count=False, cleanup=False, preview_override=None,
                  only_extra=None):
        entries = list(REQUIRED if entries is None else entries)
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            tool = folder/'llama-builds'
            tool.write_text(TOOL)
            tool.chmod(0o755)
            config = folder/'config.yaml'
            rendered = 'models:\n' + ''.join('  '+json.dumps(e)+':\n    cmd: example\n' for e in entries)
            if not missing_config:
                config.write_text(rendered+'# mismatch\n' if mismatch else rendered)
            count = len(entries) + int(wrong_count)
            preview = (f'llama-swap config unchanged ({count} entries)' if unchanged else
                       f'would write {count} entries:\n'+'\n'.join('  '+e for e in entries))
            if preview_override is not None:
                preview = preview_override
            calls = folder/'calls.txt'
            scenario = folder/'scenario.json'
            scenario.write_text(json.dumps(dict(entries=entries, rendered=rendered, config=str(config),
                                                preview=preview, calls=str(calls))))
            env = dict(os.environ, PATH=str(folder)+os.pathsep+os.environ['PATH'],
                       GUARD_TEST_SCENARIO=str(scenario))
            result = subprocess.run(['bash', str(SCRIPT)]+(['--cleanup'] if cleanup else [])+(['--only-extra']+only_extra if only_extra is not None else [])+([EXTRA] if extra else []),
                                    env=env, text=True, capture_output=True, timeout=10)
            return result, calls.read_text().splitlines(), config.read_text() if config.exists() else None, rendered

    def test_changed_complete_config_writes_without_force(self):
        result, calls, _, _ = self.run_guard(entries=REQUIRED+[EXTRA], extra=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GATE OK', result.stdout)
        self.assertIn('loaded again', result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run', 'swap-config'])

    def test_only_extra_needs_no_ctx_list_and_writes(self):
        ids = ['laguna-s-2.1-nathanw-candidate-ctx32k', 'laguna-s-2.1-nathanw-candidate-ctx131k']
        result, calls, _, _ = self.run_guard(entries=ORDINARY+ids, only_extra=ids)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GATE OK', result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run', 'swap-config'])
        result, calls, _, _ = self.run_guard(unchanged=True, entries=ORDINARY+ids, only_extra=ids)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['swap-config --dry-run'])

    def test_only_extra_refuses_missing_extra_ordinary_or_unknown_preview(self):
        ids = ['laguna-s-2.1-nathanw-candidate-ctx32k']
        for entries in (ORDINARY, ORDINARY[1:]+ids):
            with self.subTest(entries=len(entries)):
                result, calls, _, _ = self.run_guard(entries=entries, only_extra=ids)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('nothing written', result.stdout)
                self.assertEqual(calls, ['swap-config --dry-run'])
        result, calls, _, _ = self.run_guard(entries=ORDINARY+ids, only_extra=ids,
                                             preview_override='something unfamiliar')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, ['swap-config --dry-run'])

    def test_only_extra_without_ids_refuses_before_any_call(self):
        with self.assertRaises(FileNotFoundError):  # the stand-in tool was never called
            self.run_guard(entries=ORDINARY, only_extra=[])

    def test_changed_missing_id_refuses_write(self):
        result, calls, _, _ = self.run_guard(entries=REQUIRED[:-1])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(REQUIRED[-1], result.stdout)
        self.assertIn('nothing written', result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run'])

    def test_unchanged_complete_config_verifies_without_write(self):
        result, calls, actual, rendered = self.run_guard(unchanged=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('GATE OK', result.stdout)
        self.assertIn('verified unchanged -- no write or reload', result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run'])
        self.assertEqual(actual, rendered)

    def test_unchanged_extra_ids_are_still_required(self):
        result, calls, _, _ = self.run_guard(unchanged=True, entries=REQUIRED+[EXTRA], extra=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, ['swap-config --dry-run'])
        result, calls, _, _ = self.run_guard(unchanged=True, extra=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(EXTRA, result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run'])

    def test_unchanged_missing_required_id_refuses_write(self):
        result, calls, _, _ = self.run_guard(unchanged=True, entries=REQUIRED[:-1])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(REQUIRED[-1], result.stdout)
        self.assertEqual(calls, ['swap-config --dry-run'])

    def test_unchanged_mismatch_read_failure_or_count_change_refuses_write(self):
        for option in ('mismatch', 'missing_config', 'wrong_count'):
            with self.subTest(option=option):
                result, calls, _, _ = self.run_guard(unchanged=True, **{option: True})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('GATE FAILED', result.stdout)
                self.assertIn('nothing written', result.stdout)
                self.assertEqual(calls, ['swap-config --dry-run'])

    def test_cleanup_changed_and_unchanged(self):
        for unchanged in (False, True):
            with self.subTest(unchanged=unchanged):
                result, calls, actual, rendered = self.run_guard(cleanup=True, unchanged=unchanged, entries=ORDINARY)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('GATE OK: no ctx-test entries', result.stdout)
                self.assertEqual(calls, ['swap-config --dry-run'] + ([] if unchanged else ['swap-config']))
                self.assertEqual(actual, rendered)

    def test_cleanup_refuses_any_ctx_entry_or_broken_fork(self):
        for entry in REQUIRED + [EXTRA, 'other-model-upstream-ctx64k', 'laguna-s-2.1-nathanw', 'laguna-s-2.1-nathanw-candidate']:
            with self.subTest(entry=entry):
                result, calls, _, _ = self.run_guard(cleanup=True, entries=ORDINARY+[entry])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('nothing written', result.stdout)
                self.assertEqual(calls, ['swap-config --dry-run'])

    def test_cleanup_refuses_missing_ordinary_entries_and_unknown_preview(self):
        for entries, preview in ((ORDINARY[:-1], None), (ORDINARY, 'unexpected output')):
            result, calls, _, _ = self.run_guard(cleanup=True, entries=entries, preview_override=preview)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, ['swap-config --dry-run'])

    def test_cleanup_still_verifies_unchanged_config_bytes_and_count(self):
        for option in ('mismatch', 'missing_config', 'wrong_count'):
            result, calls, _, _ = self.run_guard(cleanup=True, unchanged=True, entries=ORDINARY, **{option: True})
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(calls, ['swap-config --dry-run'])


if __name__ == '__main__':
    unittest.main()
