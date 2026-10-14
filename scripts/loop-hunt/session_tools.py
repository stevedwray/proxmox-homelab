"""Synthetic agent tools. Never accesses real files, shells or networks."""
import copy
import hashlib
import json
import re

from copilot_scan import content_tool_checks

BASE_TOOLS=('read_file','grep_search','run_in_terminal','replace_string_in_file','list_dir','create_file','file_search','get_errors')
TOOL_NAMES=BASE_TOOLS+tuple(f'inspect_fixture_{i:02d}' for i in range(32))


def schemas():
    return [dict(type='function',function=dict(name=name,description=f'Synthetic {name}; operates only on the fixture tree.',
        parameters=dict(type='object',properties=dict(path=dict(type='string'),content=dict(type='string'),
                        command=dict(type='string'),old=dict(type='string'),new=dict(type='string'))))) for name in TOOL_NAMES]


def initial_tree():
    return {f'/fixture/module-{i:02d}.txt':f'fixture module {i}: state=old\n' for i in range(30)}


def execute(call,tree):
    function=call.get('function',{})
    name=function.get('name')
    arguments=function.get('arguments','{}')
    try:args=json.loads(arguments) if isinstance(arguments,str) else arguments
    except ValueError:return dict(error='malformed JSON arguments'),None
    if not isinstance(args,dict):return dict(error='arguments must be an object'),None
    signature=(name,json.dumps(args,sort_keys=True))
    if name not in TOOL_NAMES:return dict(error='unknown synthetic tool'),signature
    path=args.get('path','')
    if name in ('create_file','replace_string_in_file'):
        if path not in tree:return dict(error='path outside fixture tree'),signature
        if name=='create_file':tree[path]=str(args.get('content',''))
        else:tree[path]=tree[path].replace(str(args.get('old','state=old')),str(args.get('new','state=new')))
        return dict(path=path,content=tree[path]),signature
    if name=='read_file':return dict(path=path,content=tree.get(path,'NOT PROVIDED')),signature
    if name=='run_in_terminal':
        # Command text is evidence only: no subprocess, eval, shell or file writes.
        return dict(synthetic=True,command=args.get('command'),files_changed=sum('state=new' in text for text in tree.values())),signature
    if name=='list_dir':return dict(files=sorted(tree)),signature
    return dict(matches=[p for p in sorted(tree) if str(args.get('content','')) in tree[p]]),signature


def done(tree):return all('state=new' in value for value in tree.values())


def checks(response,previous=None,streak=0):
    choice=response.get('choices',[{}])[0]
    message=choice.get('message',{})
    flags=set(content_tool_checks(message.get('content') or '')[0])
    if re.search(r'<think>|</think>|^\s*(?:analysis|reasoning)\s*:',message.get('content') or '',re.I):flags.add('reasoning-in-content')
    for tool in message.get('tool_calls') or []:
        function=tool.get('function') or {}
        arguments=function.get('arguments') or ''
        if isinstance(arguments,str) and re.search(r'<think>|</think>|^\s*(?:analysis|reasoning)\s*:',arguments,re.I):flags.add('reasoning-in-arguments')
        try:
            parsed=json.loads(arguments) if isinstance(arguments,str) else arguments
            if not isinstance(parsed,dict):raise ValueError('not an object')
        except ValueError:
            flags.add('tool-malformed')
            previous,streak=None,0
            continue
        signature=(function.get('name'),json.dumps(parsed,sort_keys=True))
        streak=streak+1 if signature==previous else 1
        previous=signature
        if streak>=3:flags.add('tool-repeat')
    return flags,previous,streak


def fit_text(client,prefix,filler,target):
    """Approximate a raw-text token target using the loaded tokenizer."""
    if client.tokenize(prefix)>target:return prefix
    while client.tokenize(prefix+filler)<target:filler+=filler
    low,high=0,len(filler)
    best=prefix
    while low<=high:
        middle=(low+high)//2
        text=prefix+filler[:middle]
        count=client.tokenize(text)
        if count<=target:
            best=text
            low=middle+1
        else:high=middle-1
    return best


def run_agent(run):
    from session_bugs import cb, grade
    import gen_sessions as gs
    caps=list(dict.fromkeys((run.args.client_output_limit,16384)))
    for cap in caps:
        for seed in run.args.sessions:
            run.reload()
            session=f'agent-{seed}-cap{cap}'
            tree=initial_tree()
            # ~12k-token synthetic system text by estimate, measured at runtime.
            filler=run.fixtures[seed][0]['user']+run.fixtures[seed][1]['user']
            system=fit_text(run.client,run.system+'\nSynthetic tool exercise. Background audit text follows.\n',filler,12288)
            messages=[dict(role='system',content=system),
                      dict(role='user',content='Update all 30 /fixture/module-00.txt through /fixture/module-29.txt files from state=old to state=new using tools. Verify them, then answer TASK COMPLETE. End your final answer with ref: '+gs.reference(seed))]
            initial_tokens=run.client.count(messages,schemas())
            target=run.size-cap-2048
            if initial_tokens>=target:raise ValueError('synthetic C5 system/tools leave no history growth room')
            previous,streak,calls,was_cut=None,0,0,False
            limit=min(run.args.max_turns or 60,60)
            for turn in range(1,limit+1):
                key=f'{session}/{turn}/warm'
                record=next((r for r in run.records if r['key']==key),None)
                if record is None:
                    record=run.measure(session,turn,messages,None,budget=cap,seed=seed,tools=schemas())
                    message=record['response'].get('choices',[{}])[0].get('message',{})
                    if not message.get('tool_calls') and message.get('content'):
                        fixture=dict(reference=gs.reference(seed),expected=[])
                        record.update(grade(record['response'],fixture,record['visible_tokens'],messages,**record['detector_evidence']))
                        record['fixture']=fixture
                    flags,previous,streak=checks(record['response'],previous,streak)
                    if was_cut:flags.add('cut-off-then-retry')
                    record['flags']=sorted(set(record['flags'])|flags)
                    if record['response'].get('choices',[{}])[0].get('message',{}).get('tool_calls'):
                        record['flags']=[f for f in record['flags'] if f!='no-answer']
                    record['fixture_tree_before_sha256']=hashlib.sha256(json.dumps(tree,sort_keys=True).encode()).hexdigest()
                    run.checkpoint(record)
                else:
                    _,previous,streak=checks(record['response'],previous,streak)
                choice=record['response'].get('choices',[{}])[0]
                message=copy.deepcopy(choice.get('message',{}))
                message.pop('reasoning_content',None)
                message['role']='assistant'
                message['content']=message.get('content') or ''
                messages.append(message)
                was_cut=choice.get('finish_reason')=='length'
                tools=message.get('tool_calls') or []
                for tool in tools:
                    calls+=1
                    result,_=execute(tool,tree)
                    # Spread synthetic tool evidence across ~30 calls up to the
                    # near-full prompt budget. Tokenization, not chars, sets size.
                    current=run.client.count(messages,schemas())
                    desired=initial_tokens+(target-initial_tokens)*min(calls,30)//30
                    allowance=max(0,desired-current-64)
                    result['audit']=fit_text(run.client,'',filler,allowance)
                    messages.append(dict(role='tool',tool_call_id=tool.get('id',''),content=json.dumps(result,sort_keys=True)))
                    if calls>=60:break
                if calls>=60 or (done(tree) and not tools):break
                if not tools:
                    if was_cut:
                        messages.append(dict(role='user',content='The previous answer was cut off. Continue the synthetic task using tools.'))
                    else:break
            run.manifest.setdefault('agent_results',{})[session]=dict(done=done(tree),calls=calls,
                    output_limit=cap,system_tokens=run.client.tokenize(system),largest_prompt_tokens=max((r['prompt_tokens'] for r in run.records if r['session']==session),default=0),final_tree_sha256=hashlib.sha256(json.dumps(tree,sort_keys=True).encode()).hexdigest())
            run.save()


def stub_agent_reply(messages):
    changed=set()
    for message in messages:
        if message['role']!='tool':continue
        try:data=json.loads(message['content'])
        except ValueError:continue
        if 'state=new' in data.get('content',''):changed.add(data.get('path'))
    remaining=[p for p in initial_tree() if p not in changed]
    if not remaining:
        reference=re.search(r'End your final answer with ref: (INC-\d+)',messages[1]['content'])
        return dict(role='assistant',content='[TRIAGE] TASK COMPLETE\nref: '+(reference[1] if reference else 'INC-7001')),'stop'
    path=remaining[0]
    call=dict(id=f'call-{len(changed)}',type='function',function=dict(name='replace_string_in_file',arguments=json.dumps(dict(path=path,old='state=old',new='state=new'))))
    return dict(role='assistant',content='',tool_calls=[call]),'tool_calls'
