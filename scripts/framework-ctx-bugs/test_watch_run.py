import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

loader = importlib.machinery.SourceFileLoader('watcher_test_module', str(Path(__file__).with_name('watch_run')))
spec = importlib.util.spec_from_loader(loader.name, loader)
w = importlib.util.module_from_spec(spec)
loader.exec_module(w)


class WatchTests(unittest.TestCase):
    def make(self, folder, status='running', restored=True, failure=''):
        identity = dict(models=['qwen3.8-flash-next-q4','laguna-s-2.1'],
                        builds_selected=['nathanw','upstream'], sizes=[32768,65536,98304,131072],
                        greedy_only=False, candidate=False, entry_suffix=None, extra_seeds=None,
                        prompts=['S1','S2','S3','S4','S5','F'], dry_run=False, swap_url='http://127.0.0.1:8099')
        (folder/'run.json').write_text(json.dumps(dict(status=status, identity=identity, started='2026-10-14T07:00:00+00:00',
                              restored_default=restored, failure=failure)))
        (folder/'progress.json').write_text(json.dumps(dict(status=status, completed=12)))
        return w.Watcher(folder, 'run.service', 'expectations.json')

    def test_running_performs_no_mutation_and_complete_restores_timer_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); watcher=self.make(folder)
            with mock.patch.object(watcher, 'unit_state', return_value='active'), \
                 mock.patch.object(watcher, 'restore_timer') as restore, mock.patch.object(watcher, 'resume') as resume:
                self.assertFalse(watcher.poll()); restore.assert_not_called(); resume.assert_not_called()
            self.make(folder, status='complete')
            with mock.patch.object(watcher, 'unit_state', return_value='inactive'), \
                 mock.patch.object(watcher, 'restore_timer') as restore:
                self.assertTrue(watcher.poll()); restore.assert_called_once()
                self.assertEqual(watcher.state['status'], 'complete')

    def test_only_one_infrastructure_retry_after_successful_restoration(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); watcher=self.make(folder, 'failed', failure='llama-swap restarted or unreachable during key')
            order=[]
            def command(argv, check=True):
                order.append(argv)
                if argv==['systemctl','is-active','apt-daily-upgrade.service']: return 'inactive'
                if argv==['systemctl','is-active','apt-daily-upgrade.service','apt-daily-upgrade.timer']:
                    return 'inactive\ninactive'
                return ''
            with mock.patch.object(watcher, 'unit_state', return_value='inactive'), \
                 mock.patch.object(watcher, 'restore_timer', side_effect=lambda: order.append('restore')), \
                 mock.patch.object(watcher, 'swap_ready'), mock.patch.object(watcher, 'command', side_effect=command):
                self.assertFalse(watcher.poll())
                self.assertEqual(order[0], 'restore')
                self.assertEqual(watcher.state['retries'], 1)
                self.assertTrue(any(isinstance(x,list) and x[0]=='systemd-run' for x in order))
                self.assertTrue(watcher.state['unit'].startswith('framework-ctx-bugs-watch-resume-'))
                self.assertTrue(watcher.poll())
                self.assertEqual(watcher.state['status'], 'needs-attention')
                self.assertEqual(sum(isinstance(x,list) and x[0]=='systemd-run' for x in order), 1)

    def test_model_failure_interruption_or_failed_restoration_never_resumes(self):
        for status, restored, failure in (('failed',True,'fit failure'), ('interrupted',True,''),
                ('failed',False,'llama-swap restarted or unreachable during key'), ('running',False,'')):
            with self.subTest(status=status, restored=restored), tempfile.TemporaryDirectory() as tmp:
                watcher=self.make(Path(tmp), status, restored, failure)
                with mock.patch.object(watcher, 'unit_state', return_value='inactive'), \
                     mock.patch.object(watcher, 'restore_timer') as restore, mock.patch.object(watcher, 'resume') as resume:
                    self.assertTrue(watcher.poll()); restore.assert_called_once(); resume.assert_not_called()
                    self.assertEqual(watcher.state['status'], 'needs-attention')

    def test_active_upgrade_refuses_resume_and_restores_timer(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher=self.make(Path(tmp), 'failed', failure='llama-swap restarted or unreachable during key')
            with mock.patch.object(watcher, 'unit_state', return_value='inactive'), \
                 mock.patch.object(watcher, 'restore_timer') as restore, \
                 mock.patch.object(watcher, 'swap_ready'), mock.patch.object(watcher, 'command', return_value='active') as command:
                self.assertTrue(watcher.poll())
                self.assertEqual(restore.call_count, 2)
                self.assertEqual(watcher.state['status'], 'needs-attention')
                self.assertFalse(any(call.args[0][0]=='systemd-run' for call in command.call_args_list))

    def test_launch_error_with_active_tracked_unit_keeps_timer_paused(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher=self.make(Path(tmp), 'failed', failure='llama-swap restarted or unreachable during key')
            def resume(manifest):
                watcher.state['unit']='tracked-resume.service'
                raise RuntimeError('launcher timed out')
            with mock.patch.object(watcher, 'unit_state', side_effect=['inactive','active']), \
                 mock.patch.object(watcher, 'restore_timer') as restore, mock.patch.object(watcher, 'resume', side_effect=resume):
                self.assertFalse(watcher.poll()); self.assertEqual(restore.call_count,1)
                self.assertEqual(watcher.state['unit'], 'tracked-resume.service')

    def test_unknown_unit_query_and_timer_restoration_failure_propagate(self):
        with tempfile.TemporaryDirectory() as tmp:
            watcher=self.make(Path(tmp), 'complete')
            with mock.patch.object(watcher, 'command', return_value=''):
                with self.assertRaisesRegex(RuntimeError, 'cannot determine'):
                    watcher.unit_state()
            with mock.patch.object(watcher, 'unit_state', return_value='inactive'), \
                 mock.patch.object(watcher, 'restore_timer', side_effect=RuntimeError('sudo refused')):
                with self.assertRaisesRegex(RuntimeError, 'sudo refused'): watcher.poll()

    def test_separate_watcher_does_not_change_resume_code_hash_set(self):
        root=Path(__file__).parent
        names={p.name for p in root.glob('*.py') if not p.name.startswith('test_') and p.name!='stub_server.py'}
        self.assertNotIn('watch_run', names)
        self.assertNotIn('test_watch_run.py', names)


if __name__=='__main__': unittest.main()
