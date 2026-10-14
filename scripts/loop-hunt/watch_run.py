#!/usr/bin/env python3
"""Reuse the bounded ctx-bugs watcher, with exact session-run resume arguments."""
import argparse
import datetime
import importlib.machinery
import importlib.util
import json
from pathlib import Path

SOURCE=Path(__file__).resolve().parent.parent/'framework-ctx-bugs'/'watch_run'
loader=importlib.machinery.SourceFileLoader('ctx_watch_run',str(SOURCE))
spec=importlib.util.spec_from_loader(loader.name,loader)
base=importlib.util.module_from_spec(spec)
loader.exec_module(base)


class Watcher(base.Watcher):
    def resume(self,manifest):
        identity=manifest['identity']
        if identity['dry_run'] or identity['base_url']!='http://127.0.0.1:8080':
            raise RuntimeError('automatic recovery requires an approved local live run')
        if identity['condition'] not in ('C1','C2','C3','C4','C5'):
            raise RuntimeError('unknown condition')
        if json.loads(Path(self.builds_json).read_text())!=identity['builds']:
            raise RuntimeError('build expectations differ; refuse recovery')
        self.swap_ready(identity)
        self.state['retries']+=1
        self.save('Attempting the one permitted checkpointed infrastructure resume')
        self.pause_timer()
        stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ').lower()
        unit='loop-hunt-watch-resume-'+stamp
        self.state['unit']=unit+'.service'
        self.save('Tracking resume unit before launch: '+self.state['unit'])
        argv=['systemd-run','--user','--unit',unit,'--collect','--property=Nice=10',
              '--property=IOSchedulingClass=best-effort','--property=IOSchedulingPriority=6',
              'python3',str(Path(__file__).with_name('session_bugs.py')),
              '--run-dir',str(self.directory),'--builds-json',self.builds_json,
              '--entry',identity['entry'],'--condition',identity['condition'],
              '--sessions',*[str(seed) for seed in identity['sessions']],
              '--client-output-limit',str(identity['client_output_limit']),'--timeout',str(identity['timeout'])]
        for key,option in (('builds_root','--builds-root'),('redis_config','--redis-config'),('api_key_file','--api-key-file'),('session_dir','--session-dir'),('replay','--replay'),('continue_from','--continue-from')):
            value=identity['local_paths'].get(key)
            if value:argv.extend([option,value])
        if identity.get('max_turns'):argv.extend(['--max-turns',str(identity['max_turns'])])
        if identity.get('checkpoint_tokens'):argv.extend(['--checkpoint-tokens',*[str(n) for n in identity['checkpoint_tokens']]])
        self.command(argv)
        self.state['status']='watching'
        self.save('Checkpointed session resume launched as '+self.state['unit'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',required=True)
    parser.add_argument('--run-unit',required=True)
    parser.add_argument('--builds-json',required=True)
    args=parser.parse_args()
    raise SystemExit(Watcher(args.run_dir,args.run_unit,args.builds_json).run())
