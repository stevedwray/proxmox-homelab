#!/usr/bin/env python3
"""Checkpointed multi-turn Framework tests. Production runs require approval."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import difflib
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import gen_sessions as gs

CTX_DIR=Path(__file__).resolve().parent.parent/'framework-ctx-bugs'
sys.path.insert(0,str(CTX_DIR))
import ctx_bugs as cb
import detectors


class SessionClient(cb.Client):
    def count(self,messages,tools=None):
        payload=dict(messages=messages,add_generation_prompt=True)
        if tools:payload['tools']=tools
        rendered=self.call('/apply-template',payload)
        if not isinstance(rendered.get('prompt'),str):raise ValueError('missing rendered prompt')
        if tools:
            bare=self.call('/apply-template',dict(messages=messages,add_generation_prompt=True))
            if bare.get('prompt')==rendered['prompt']:raise ValueError('/apply-template ignored tools; refuse unmeasured C5 prompt')
        return self.tokenize(rendered['prompt'],special=True)

    def unload(self,entry):
        # llama-swap v260 README, /api/models/unload/:model_id (POST).
        url=self.swap+'/api/models/unload/'+urllib.parse.quote(entry,safe='')
        request=urllib.request.Request(url,data=b'{}',headers={'Content-Type':'application/json'})
        with self.opener.open(request,timeout=self.timeout) as response:
            response.read()  # Management success may have an empty/plain-text body.

    def complete(self,payload):
        if not payload.get('stream'):return self.call('/v1/chat/completions',payload)
        headers={'Content-Type':'application/json'}
        if self.api_key:headers['Authorization']='Bearer '+self.api_key
        request=urllib.request.Request(self.base+'/v1/chat/completions',data=json.dumps(payload).encode(),headers=headers)
        answer,reasoning,calls='', '', {}
        finish,usage,timings,ended=None,{}, {},False
        with self.opener.open(request,timeout=self.timeout) as response:
            try:
                for raw in response:
                    line=raw.decode().strip()
                    if not line.startswith('data:'):continue
                    data=line[5:].strip()
                    if data=='[DONE]':
                        ended=True
                        break
                    chunk=json.loads(data)
                    if 'error' in chunk:raise OSError('stream returned an error')
                    usage.update(chunk.get('usage') or {})
                    timings.update(chunk.get('timings') or {})
                    for choice in chunk.get('choices',[]):
                        if choice.get('index',0)!=0:continue
                        finish=choice.get('finish_reason') or finish
                        delta=choice.get('delta',{})
                        answer+=delta.get('content') or ''
                        reasoning+=delta.get('reasoning_content') or ''
                        for tool in delta.get('tool_calls') or []:
                            index=tool['index']
                            target=calls.setdefault(index,dict(id='',type='function',function=dict(name='',arguments='')))
                            if tool.get('id'):target['id']=tool['id']
                            function=tool.get('function') or {}
                            target['function']['name']+=function.get('name') or ''
                            target['function']['arguments']+=function.get('arguments') or ''
            except http.client.HTTPException as exc:
                raise OSError('interrupted SSE response') from exc
        if not ended or finish is None:raise OSError('incomplete SSE response remains pending')
        message=dict(role='assistant',content=answer,reasoning_content=reasoning)
        if calls:message['tool_calls']=[calls[i] for i in sorted(calls)]
        return dict(choices=[dict(message=message,finish_reason=finish)],usage=usage,timings=timings)


def layout(props,slots,entry,size,expected):
    actual=props.get('n_ctx',props.get('default_generation_settings',{}).get('n_ctx'))
    if props.get('model_alias')!=entry or props.get('build_info')!=expected:
        raise ValueError('served model/build mismatch')
    if not isinstance(actual,int) or actual<size:raise ValueError('served context smaller than variant')
    if not isinstance(slots,list) or not slots or any(not isinstance(s,dict) for s in slots):
        raise ValueError('invalid /slots response')
    # The operator requires this exact layout check before any pilot inference.
    if props.get('total_slots')!=4 or len(slots)!=4 or any(s.get('n_ctx')!=size for s in slots):
        raise ValueError('slot layout differs: expected four full-context slots; stop before inference')
    return dict(props=props,slots=slots,context_size=actual,
                shared_pool='expected from approved server configuration; /slots is not proof of allocation topology')


def classify(warm,cold):
    informational={'dense-reasoning','ctx-divergence','build-divergence','http-error'}
    if 'crash' in warm['flags'] or 'crash' in cold['flags']:
        return 'not comparable (server failure)'
    a=set(warm['flags'])-informational
    b=set(cold['flags'])-informational
    if a and not b:
        if not isinstance(warm.get('cached_tokens'),(int,float)) or warm['cached_tokens']<=0:
            return 'not attributable (warm cache unconfirmed)'
        return 'runtime (warm only)'
    if a and b:
        return 'model/content' if a & b else 'not attributable (different failure modes)'
    if b:return 'cold only'
    if warm.get('error') or cold.get('error'):return 'not comparable (request refused)'
    return 'clean'


def recall_fields(answer, count):
    """Extract exact values independently of the requested line layout."""
    markers=list(re.finditer(r'(?<!\S)Q([1-9]\d*):[ \t]*',answer))
    values={}
    for offset,marker in enumerate(markers):
        end=markers[offset+1].start() if offset+1<len(markers) else len(answer)
        segment=answer[marker.end():end]
        reference=re.search(r'(?<!\S)ref:[ \t]*',segment)
        if reference:segment=segment[:reference.start()]
        values.setdefault(int(marker[1]),[]).append(segment.strip())
    # Duplicate labels are ambiguous, even if one happens to contain the right value.
    extracted={number:parts[0] if len(parts)==1 else None for number,parts in values.items()}
    lines=[answer.count('\n',0,marker.start()) for marker in markers]
    layout=([int(m[1]) for m in markers]==list(range(1,count+1))
            and len(set(lines))==count)
    return extracted,layout


def grade(response,fixture,visible,history,**evidence):
    result=detectors.detect('SESSION',response,{},visible,**evidence)
    answer=result['answer']
    if fixture and response:
        fields,question_lines=recall_fields(answer,len(fixture['expected']))
        checks=dict(prefix=answer.startswith('[TRIAGE]'),reference=answer.rstrip().endswith('ref: '+fixture['reference']),
                    no_bullets=not bool(re.search(r'^\s*(?:[-*•]|\d+[.)])\s+',answer,re.M)),
                    question_lines=question_lines)
        result['checks'].update(checks)
        result['flags']+=['if-fail:'+name for name,passed in checks.items() if not passed]
        recall=[]
        for index,expected in enumerate(fixture['expected'],1):
            actual=fields.get(index)
            passed=actual==expected
            recall.append(dict(question=index,expected=expected,actual=actual,correct=passed))
            if not passed:result['flags'].append(('hallucination:' if expected=='NOT PROVIDED' and actual else 'wrong:')+f'q{index}')
        result['recall']=recall
    previous=[m.get('content') or '' for m in history if m['role']=='assistant']
    # A reproducible text-similarity measure, not a semantic judgement.
    result['similarity']=max((difflib.SequenceMatcher(None,answer,p,autojunk=True).ratio() for p in previous),default=0)
    result['flags']=sorted(set(result['flags']))
    return result


class SessionRun(cb.Run):
    def __init__(self,args):
        super().__init__(args)
        self.client=SessionClient(args.base_url,args.swap_url,args.timeout,
            Path(args.api_key_file).read_text().strip() if args.api_key_file and not args.dry_run else None)
        self.guard=None

    def prepare(self):
        args=self.args
        match=re.fullmatch(r'(qwen3\.8-flash-next-q4|glm-5\.3-flash)-(nathanw|upstream)(-candidate)?-sess(131|262)k',args.entry)
        if not match:raise ValueError('entry must be an approved sess131k/sess262k variant')
        model,self.build,candidate,context=match.groups()
        self.size={'131':131072,'262':262144}[context]
        if model.startswith('glm') and (self.build!='upstream' or self.size!=131072):raise ValueError('GLM only upstream sess131k')
        if args.condition=='C4' and self.size!=262144:raise ValueError('C4 requires sess262k')
        if args.condition!='C4' and self.size!=131072:raise ValueError('condition requires sess131k')
        if args.condition=='C2' and len(args.sessions)!=4:raise ValueError('C2 requires exactly four distinct session seeds')
        if len(set(args.sessions))!=len(args.sessions):raise ValueError('session seeds must be distinct')
        if args.dry_run:
            if any(urllib.parse.urlsplit(url).hostname not in ('127.0.0.1','localhost','::1') for url in (self.client.base,self.client.swap)):
                raise ValueError('dry run requires loopback URLs')
            health=self.client.call('/health')
            if health.get('loop_hunt_stub') is not True:raise ValueError('not a loop-hunt stand-in')
            builds=health['builds']
        else:
            if not args.builds_json:raise ValueError('live runs require approved build expectations')
            builds=json.loads(Path(args.builds_json).read_text())
            link='candidate' if candidate else 'current'
            record=json.loads((Path(args.builds_root)/('fork' if self.build=='nathanw' else 'upstream')/link/'build.json').read_text())
            if any(builds[self.build][key]!=record[key] for key in ('name','sha')):raise ValueError('build link moved')
        self.expected=builds[self.build]['build_info']
        source=Path(args.session_dir)
        source_manifest=json.loads((source/'manifest.json').read_text())
        self.fixtures={}
        for seed in args.sessions:
            turns=[]
            for item in source_manifest['sessions'][str(seed)]:
                data=(source/item['file']).read_bytes()
                if gs.sha(data)!=item['sha256']:raise ValueError('session fixture hash mismatch')
                turns.append(json.loads(data))
            self.fixtures[seed]=turns
        self.system=source_manifest['system']
        self.replay=json.loads(Path(args.replay).read_text()) if args.replay else None
        if self.replay and not isinstance(self.replay.get('messages'),list):raise ValueError('replay needs messages up to final user turn')
        identity=dict(entry=args.entry,condition=args.condition,sessions=args.sessions,builds=builds,
                      fixture_sha256=gs.sha(gs.encoded(source_manifest)),replay_sha256=gs.sha(gs.encoded(self.replay)),
                      base_url=self.client.base,swap_url=self.client.swap,dry_run=args.dry_run,
                      timeout=args.timeout,
                      local_paths=dict(builds_root=args.builds_root,redis_config=args.redis_config,api_key_file=args.api_key_file,session_dir=str(Path(args.session_dir).resolve()),continue_from=str(args.continue_from.resolve()) if args.continue_from else None,replay=str(args.replay.resolve()) if args.replay else None),
                      max_turns=args.max_turns,checkpoint_tokens=args.checkpoint_tokens,
                      client_output_limit=args.client_output_limit,
                      continuation_sha256=gs.sha((Path(args.continue_from)/'results.jsonl').read_bytes()) if args.continue_from else None,
                      dependencies={name:gs.sha((CTX_DIR/name).read_bytes()) for name in ('ctx_bugs.py','detectors.py','framework_lock.py','resp_client.py','gen_prompts.py')},
                      scripts={p.name:gs.sha(p.read_bytes()) for p in Path(__file__).parent.glob('*.py') if not p.name.startswith('test_')})
        if self.records and not self.manifest_path.exists():raise ValueError('results exist without run manifest')
        if self.manifest_path.exists():
            self.manifest=json.loads(self.manifest_path.read_text())
            if self.manifest['identity']!=identity:raise ValueError('resume identity changed')
        else:
            restore=self.client.call('/props').get('model_alias') or cb.DEFAULT_MODEL
            if '-sess' in restore:restore=cb.DEFAULT_MODEL
            self.manifest=dict(identity=identity,started=cb.now(),job_id='loop-hunt-'+self.directory.name,
                restore_model=restore,checkpoints={},status='running',sampling='server defaults; no request sampling fields',
                replay_kind='reconstruction; system/tool schemas absent unless supplied by capture' if self.replay else None)
        if args.condition=='C3' and not args.continue_from:
            raise ValueError('C3 requires --continue-from a completed C1 run')
        if args.continue_from:
            if args.condition!='C3':raise ValueError('--continue-from is only for C3')
            source=Path(args.continue_from)
            source_run=json.loads((source/'run.json').read_text())
            source_id=source_run['identity']
            if (source_run.get('status')!='complete' or source_id['condition']!='C1'
                or any(source_id[key]!=identity[key] for key in ('entry','sessions','builds','fixture_sha256'))):
                raise ValueError('continuation must be completed matching C1 run')
            if not self.records:
                rows=[json.loads(line) for line in (source/'results.jsonl').read_text().splitlines() if line]
                self.manifest['checkpoints']=copy.deepcopy(source_run['checkpoints'])
                self.manifest['continuation_source']=str(source)
                for row in rows:self.checkpoint(dict(row,continued_from_c1=True))
        self.manifest['status']='running'
        self.save()

    def save(self):
        cb.write_json(self.manifest_path,self.manifest)
        cb.write_json(self.directory/'progress.json',dict(status=self.manifest.get('status'),completed=len(self.records),updated=cb.now(),run_dir=str(self.directory)))
        lines=['# Loop hunt session report','',f"Status: {self.manifest.get('status')}",
               'Sampling: server defaults (seed and output budget recorded per request).',
               'Coverage: '+(f"limited to turn {self.manifest['identity']['max_turns']}" if self.manifest['identity'].get('max_turns') else 'full configured condition'),'',
               '| Session | Turn | Mode | Prompt tokens | Server tokens | Cached | Generated | Prompt tok/s | Generation tok/s | Wall seconds | Recall | Similarity | Flags |',
               '| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |']
        for r in self.records:
            lines.append(f"| {r['session']} | {r['turn']} | {r['mode']} | {r['prompt_tokens']} | {r.get('server_prompt_tokens')} | {r.get('cached_tokens')} | {r['generated_tokens']} | {r.get('prompt_tok_s')} | {r.get('generation_tok_s')} | {r['wall_seconds']:.3f} | {sum(q['correct'] for q in r.get('recall',[]))}/{len(r.get('recall',[]))} | {r['similarity']:.3f} | {', '.join(r['flags'])} |")
        lines+=['','## Collapse context','','| Session | First flagged turn | Prompt tokens |','| --- | ---: | ---: |']
        for session in sorted({r['session'] for r in self.records}):
            bad=next((r for r in self.records if r['session']==session and r['mode']=='warm' and set(r['flags'])-{'dense-reasoning'}),None)
            lines.append(f"| {session} | {bad['turn'] if bad else 'none'} | {bad['prompt_tokens'] if bad else ''} |")
        lines+=['','## Warm/cold','','| Request | Classification | Warm tokens | Cold tokens |','| --- | --- | ---: | ---: |']
        for key,pair in self.manifest.get('checkpoints',{}).items():
            lines.append(f"| {key} | {pair['classification']} | {pair['warm_tokens']} | {pair['cold_tokens']} |")
        lines+=['','Similarity is text overlap, not a semantic judge. Dense reasoning alone is informational.',
                'Overflow comparisons use measured rendered tokens, server usage, timings and HTTP errors.',
                'A resumed warm request rebuilds its saved text history; cache continuity is not assumed.',
                'CK reloads flush every slot cache. C2 pauses all workers before CK; subsequent cache reuse is measured, not assumed.','']
        (self.directory/'report.md').write_text('\n'.join(lines))

    def checkpoint(self,record):
        # The coordinator is the sole checkpoint writer, including C2.
        cb.write_json(self.directory/'raw'/f"{record['key'].replace('/','-')}.json",record)
        cb.append_jsonl(self.results_path,record)
        self.records.append(record)
        self.done.add(record['key'])
        self.save()
        self.log(f"{record['key']}: {', '.join(record['flags']) or 'clean'}")

    def reload(self):
        self.check_lock()
        before=self.server_identity(self.args.entry)
        self.client.unload(self.args.entry)
        self.load_entry(self.args.entry)
        after=self.server_identity(self.args.entry)
        if before==after:raise RuntimeError('cold reload did not replace server process')
        layout(self.client.call('/props'),self.client.call('/slots'),self.args.entry,self.size,self.expected)

    def measure(self,session,turn,messages,fixture,*,mode='warm',budget=8192,seed=1,tools=None):
        self.check_lock()
        payload=dict(model=self.args.entry,messages=copy.deepcopy(messages),max_tokens=budget,
                     cache_prompt=mode=='warm',seed=seed,stream=bool(tools))
        if tools:payload.update(tools=tools,stream_options=dict(include_usage=True))
        count=self.client.count(messages,tools)
        key=f'{session}/{turn}/{mode}'
        swap=self.verify_request_swap(key)
        before=None
        evidence=[]
        try:before=self.server_identity(self.args.entry)
        except (OSError,RuntimeError,ValueError) as exc:evidence.append('before identity: '+str(exc))
        start_epoch,start=time.time(),time.monotonic()
        response,error={},None
        try:
            response=self.client.complete(payload)
            if not response.get('choices') or not isinstance(response['choices'][0].get('message'),dict):
                raise ValueError('invalid completion response')
        except urllib.error.HTTPError as exc:
            # Context exhaustion is evidence, not an invisible lost request.
            error=f'HTTP {exc.code}: '+exc.read(2000).decode(errors='replace')
            exc.close()
        except (OSError,ValueError,http.client.HTTPException) as exc:
            until=time.time()
            window,capture_error='',None
            try:window=self.kernel_window(start_epoch,until)
            except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as capture:
                capture_error=str(capture)
            with (self.directory/'dmesg.txt').open('a') as out:
                out.write(f'\n## {key} pending @{start_epoch:.6f} to @{until:.6f}\n{window}\n')
            cb.write_json(self.directory/'raw'/f"{key.replace('/','-')}-pending.json",
                          dict(payload=payload,error=str(exc),recorded=cb.now(),
                               kernel_window=dict(since=start_epoch,until=until),evidence_error=capture_error))
            self.verify_request_swap(key,swap,error=str(exc))
            raise cb.InfrastructureFailure(f'interrupted request remains pending: {key}') from exc
        end_epoch=time.time()
        elapsed=time.monotonic()-start
        healthy=True
        try:self.client.call('/health')
        except (OSError,ValueError):healthy=False
        after=None
        try:after=self.server_identity(self.args.entry)
        except (OSError,RuntimeError,ValueError) as exc:evidence.append('after identity: '+str(exc))
        window=''
        try:window=self.kernel_window(start_epoch,end_epoch)
        except (OSError,ValueError,RuntimeError,subprocess.SubprocessError) as exc:evidence.append('kernel window: '+str(exc))
        self.verify_request_swap(key,swap,response,error)
        message=response.get('choices',[{}])[0].get('message',{})
        visible=None
        if response and healthy:
            try:visible=self.client.tokenize((message.get('content') or '')+(message.get('reasoning_content') or '')+
                    (json.dumps(message['tool_calls'],sort_keys=True) if message.get('tool_calls') else ''))
            except (OSError,ValueError) as exc:evidence.append('visible tokenize: '+str(exc))
        detector_evidence=dict(error=None if error and error.startswith('HTTP ') and healthy else error,healthy=healthy,
                     restarted=before is not None and after is not None and before!=after,dmesg_window=window)
        result=grade(response,fixture,visible,messages,**detector_evidence)
        if error and error.startswith('HTTP '):result['flags'].append('http-error')
        usage=response.get('usage') or {}
        timings=response.get('timings') or {}
        cached=timings.get('cache_n',usage.get('prompt_tokens_details',{}).get('cached_tokens'))
        with (self.directory/'dmesg.txt').open('a') as out:
            out.write(f'\n## {key} @{start_epoch:.6f} to @{end_epoch:.6f}\n{window}\n')
        return dict(fixture=fixture,detector_evidence=detector_evidence,key=key,session=session,turn=turn,mode=mode,seed=seed,payload=payload,
            prompt_tokens=count,server_prompt_tokens=usage.get('prompt_tokens'),cached_tokens=cached,
            generated_tokens=usage.get('completion_tokens',0),timings=timings,
            prompt_tok_s=timings.get('prompt_per_second'),generation_tok_s=timings.get('predicted_per_second'),
            wall_seconds=elapsed,response=response,error=error,evidence_error='; '.join(evidence) or None,
            prompt_sha256=gs.sha(gs.encoded(payload)),recorded=cb.now(),
            server_before=before,server_after=after,**result)

    def ck(self,warm,fixture,target):
        key=warm['key']
        coldkey=key.rsplit('/',1)[0]+'/cold'
        cold=next((r for r in self.records if r['key']==coldkey),None)
        if cold is None:
            self.reload()
            self.manifest.setdefault('cache_resets',[]).append(dict(request=key,reason='CK cold comparison; all server slot caches discarded',recorded=cb.now()))
            cold=self.measure(warm['session'],warm['turn'],warm['payload']['messages'],fixture,
                              mode='cold',budget=warm['payload']['max_tokens'],seed=warm['seed'],tools=warm['payload'].get('tools'))
            self.checkpoint(cold)
        self.manifest['checkpoints'][key]=dict(target=target,classification=classify(warm,cold),
            warm_tokens=warm['prompt_tokens'],cold_tokens=cold['prompt_tokens'],
            identical_request_except_cache=({k:v for k,v in warm['payload'].items() if k!='cache_prompt'}==
                                          {k:v for k,v in cold['payload'].items() if k!='cache_prompt'}))
        self.save()

    def history(self,session,before_turn=None):
        messages=[dict(role='system',content=self.system)]
        warm=sorted((r for r in self.records if r['session']==session and r['mode']=='warm' and (before_turn is None or r['turn']<before_turn)),key=lambda r:r['turn'])
        for record in warm:
            messages=copy.deepcopy(record['payload']['messages'])
            if record['answer']:messages.append(dict(role='assistant',content=record['answer']))
        return messages

    def session_turn(self,seed,turn):
        session=f'seed-{seed}'
        key=f'{session}/{turn}/warm'
        existing=next((r for r in self.records if r['key']==key),None)
        if existing:return existing,False
        fixture=self.fixtures[seed][turn-1]
        messages=self.history(session,turn)+[dict(role='user',content=fixture['user'])]
        return self.measure(session,turn,messages,fixture,seed=seed),True

    def synthetic(self,seeds=None):
        if seeds is None:
            seeds=self.args.sessions
            if self.args.condition!='C2' and len(seeds)>1:
                for seed in seeds:
                    self.reload()
                    self.synthetic([seed])
                return
        condition=self.args.condition
        limit=min(self.args.max_turns or gs.TURNS,min(len(v) for v in self.fixtures.values()))
        targets=self.args.checkpoint_tokens or ([16384,32768] if condition=='C2' else [65536,98304,131072]+([196608,262144] if condition=='C4' else []))
        stopped=set()
        overflow_at=self.manifest.get('overflow_at')
        with ThreadPoolExecutor(max_workers=len(seeds) if condition=='C2' else 1) as pool:
            for turn in range(1,limit+1):
                pending=[]
                for seed in seeds:
                    if seed in stopped:continue
                    session=f'seed-{seed}'
                    messages=self.history(session,turn)+[dict(role='user',content=self.fixtures[seed][turn-1]['user'])]
                    count=self.client.count(messages)
                    if condition in ('C1','C4') and count+8192>self.size:
                        stopped.add(seed)
                        continue
                    pending.append((seed,pool.submit(self.session_turn,seed,turn)))
                if not pending:break
                # All concurrent requests finish before any management/reload operation.
                records=[]
                failures=[]
                by_future={future:seed for seed,future in pending}
                for future in as_completed(by_future):
                    try:
                        record,fresh=future.result()
                        if fresh:self.checkpoint(record)
                        records.append((by_future[future],record))
                    except Exception as exc:failures.append(exc)
                if failures:raise failures[0]
                records.sort(key=lambda pair:pair[0])
                total=sum(r['prompt_tokens'] for _,r in records)
                if condition=='C2' and total>=self.size and overflow_at is None:
                    overflow_at=turn
                    self.manifest['overflow_at']=turn
                for seed,record in records:
                    prior=[r for r in self.records if r['session']==record['session'] and r['mode']=='warm' and r['turn']<turn]
                    previous=max((r['prompt_tokens'] for r in prior),default=0)
                    selected=[target for target in targets if previous<target<=record['prompt_tokens']]
                    if condition=='C2' and overflow_at==turn:selected.append('first past shared pool')
                    # A final valid near-limit C1/C4 turn stands for the nominal context CK.
                    if turn<len(self.fixtures[seed]) and condition in ('C1','C4'):
                        next_messages=record['payload']['messages']+[dict(role='assistant',content=record['answer']),dict(role='user',content=self.fixtures[seed][turn]['user'])]
                        if self.client.count(next_messages)+8192>self.size:selected.append(self.size)
                    if selected:self.ck(record,self.fixtures[seed][turn-1],selected)
                    if condition=='C3' and record['prompt_tokens']>=self.size:
                        start=self.manifest.setdefault('overflow_turn',{}).setdefault(str(seed),turn)
                        if turn-start>=2:stopped.add(seed)
                    if condition=='C2' and overflow_at is not None and turn-overflow_at>=4:stopped.add(seed)
                self.save()
        if not self.args.max_turns:
            if condition=='C2' and overflow_at is None:raise ValueError('fixtures ended before shared pool overflow')
            if condition=='C3' and len(stopped)!=len(seeds):raise ValueError('fixtures ended before three overflow turns')
            if condition in ('C1','C4') and len(stopped)!=len(seeds):raise ValueError('fixtures ended before context reached')

    def replay_sessions(self):
        messages=self.replay['messages']
        if not messages or messages[-1].get('role')!='user':raise ValueError('replay must end at the user request to regenerate')
        for seed in (1,2,3):
            self.reload()
            session=f'replay-{seed}'
            # Regenerate assistant answers turn by turn; never feed reasoning into history.
            history=[]
            turn=0
            for index,message in enumerate(messages):
                if message.get('role')=='assistant':continue
                if message.get('role') not in ('system','user','tool'):raise ValueError('unsupported replay role')
                history.append(copy.deepcopy(message))
                if message['role']!='user':continue
                turn+=1
                key=f'{session}/{turn}/warm'
                warm=next((r for r in self.records if r['key']==key),None)
                if warm is None:
                    warm=self.measure(session,turn,history,None,seed=seed,tools=self.replay.get('tools'))
                    self.checkpoint(warm)
                history.append(dict(role='assistant',content=warm['answer']))
                if index==len(messages)-1:self.ck(warm,None,'selected replay turn')

    def matrix(self):
        self.log(f'Loading and checking {self.args.entry}')
        self.load_entry(self.args.entry)
        self.manifest['layout']=layout(self.client.call('/props'),self.client.call('/slots'),self.args.entry,self.size,self.expected)
        self.save()
        start=cb.now()
        try:
            if self.replay:self.replay_sessions()
            elif self.args.condition=='C5':
                from session_tools import run_agent
                run_agent(self)
            else:self.synthetic()
        finally:
            with (self.directory/'logs'/'llama-swap.log').open('a') as out:out.write(self.cell_logs(start)+'\n')


def parse_args(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--condition',choices=('C1','C2','C3','C4','C5'))
    parser.add_argument('--entry')
    parser.add_argument('--sessions',nargs='+',type=int,choices=gs.SEEDS,default=[1])
    parser.add_argument('--replay',type=Path)
    parser.add_argument('--continue-from',type=Path,help='C3: completed matching C1 run; imports its checkpoint')
    parser.add_argument('--regrade',type=Path)
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--base-url',default='http://127.0.0.1:8080')
    parser.add_argument('--swap-url')
    parser.add_argument('--run-dir')
    parser.add_argument('--results-root',default='/storage/artifacts/loop-hunt')
    parser.add_argument('--session-dir',default=str(Path(__file__).parent/'sessions'))
    parser.add_argument('--builds-json')
    parser.add_argument('--builds-root',default='/storage/llama-builds')
    parser.add_argument('--redis-config',default='/etc/llama-builds/backends.json')
    parser.add_argument('--api-key-file')
    parser.add_argument('--timeout',type=float,default=1800)
    parser.add_argument('--max-turns',type=int,help='bounded pilot/fixture run; recorded as limited coverage')
    parser.add_argument('--checkpoint-tokens',nargs='+',type=int,help='override CK thresholds, recorded in run identity')
    parser.add_argument('--client-output-limit',type=int,default=8192)
    args=parser.parse_args(argv)
    if not args.regrade and (not args.condition or not args.entry):parser.error('--condition and --entry required')
    if not args.dry_run:
        args.swap_url=args.swap_url or 'http://127.0.0.1:8099'
        args.api_key_file=args.api_key_file or '/etc/llamacpp/api-key'
    if args.max_turns is not None and args.max_turns<1:parser.error('--max-turns must be positive')
    if args.client_output_limit<1:parser.error('--client-output-limit must be positive')
    return args


def regrade(directory):
    directory=Path(directory)
    with (directory/'.checkpoint-lock').open('a') as guard:
        fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest=json.loads((directory/'run.json').read_text())
        if manifest['status']=='running':raise ValueError('refuse to regrade running run')
        records=cb.read_results(directory/'results.jsonl')
        # Preserve every pre-regrade grade/report before replacing any evidence.
        backup=directory/'regrade-backups'/str(time.time_ns())
        backup.mkdir(parents=True,mode=0o700)
        backup.parent.chmod(0o700)
        for name in ('results.jsonl','run.json','report.md','regraded.json'):
            if (directory/name).exists():shutil.copy2(directory/name,backup/name)
        if (directory/'raw').exists():shutil.copytree(directory/'raw',backup/'raw')
        for record in records:
            result=grade(record['response'],record.get('fixture'),record.get('visible_tokens'),
                         record['payload']['messages'],**record.get('detector_evidence',{}))
            # Agent protocol checks depend on earlier invocations; retain their saved evidence.
            result['flags']=sorted(set(result['flags'])|{flag for flag in record['flags'] if flag in
                ('tool-repeat','tool-malformed','tool-call-in-content','reasoning-in-content','reasoning-in-arguments','cut-off-then-retry','http-error')})
            if record['response'].get('choices',[{}])[0].get('message',{}).get('tool_calls'):
                result['flags']=[flag for flag in result['flags'] if flag!='no-answer']
            record.update(result)
        by_key={r['key']:r for r in records}
        for key,pair in manifest['checkpoints'].items():
            cold=by_key[key.rsplit('/',1)[0]+'/cold']
            pair['classification']=classify(by_key[key],cold)
        temporary=directory/'results.jsonl.tmp'
        with temporary.open('w') as out:
            for record in records:out.write(json.dumps(record,sort_keys=True)+'\n')
            out.flush()
            os.fsync(out.fileno())
        temporary.replace(directory/'results.jsonl')
        cb.write_json(directory/'regraded.json',records)
        for record in records:cb.write_json(directory/'raw'/f"{record['key'].replace('/','-')}.json",record)
        run=SessionRun.__new__(SessionRun)
        run.directory,run.manifest,run.records=directory,manifest,records
        run.manifest_path=directory/'run.json'
        run.manifest.setdefault('regrade_history',[]).append(dict(
            backup=str(backup.relative_to(directory)),recorded=cb.now(),
            results_sha256=gs.sha((backup/'results.jsonl').read_bytes()),
            scorer_sha256=gs.sha(Path(__file__).read_bytes())))
        run.save()
        return len(records)


def main(argv=None):
    os.umask(0o077)
    args=parse_args(argv)
    if args.regrade:
        print(f'Regraded {regrade(args.regrade)} saved turns')
        return 0
    def interrupt(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupt)
    return SessionRun(args).execute()


if __name__=='__main__':raise SystemExit(main())
