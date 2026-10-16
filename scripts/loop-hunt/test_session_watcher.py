import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import watch_run


class SessionWatcherTests(unittest.TestCase):
    def test_resume_preserves_condition_paths_and_parameters(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            builds=root/'builds.json'
            builds.write_text(json.dumps(dict(nathanw=dict(name='fixture'))))
            identity=dict(dry_run=False,base_url='http://127.0.0.1:8080',swap_url='http://127.0.0.1:8099',
                          condition='C3',entry='qwen3.8-flash-next-q4-nathanw-sess131k',
                          builds=json.loads(builds.read_text()),sessions=[1],client_output_limit=8192,timeout=77,
                          max_turns=7,checkpoint_tokens=[10,20],local_paths=dict(session_dir='/fixture/sessions',
                          continue_from='/fixture/c1',replay=None,builds_root='/fixture/builds',redis_config='/fixture/redis.json',api_key_file='/fixture/key'))
            watcher=watch_run.Watcher(root,'loop-hunt-fixture.service',builds)
            commands=[]
            with patch.object(watcher,'swap_ready') as ready,patch.object(watcher,'pause_timer') as timer,patch.object(watcher,'command',side_effect=lambda args:commands.append(args)),patch.object(watcher,'save'):
                watcher.resume(dict(identity=identity))
            self.assertEqual(watcher.state['retries'],1)
            ready.assert_called_once_with(identity)
            timer.assert_called_once()
            command=commands[0]
            self.assertIn(str(Path(watch_run.__file__).with_name('session_bugs.py')),command)
            for option,value in (('--condition','C3'),('--continue-from','/fixture/c1'),('--timeout','77'),('--max-turns','7')):
                self.assertEqual(command[command.index(option)+1],value)
            identity['builds']={}
            with self.assertRaisesRegex(RuntimeError,'build expectations differ'):watcher.resume(dict(identity=identity))


if __name__=='__main__':unittest.main()
