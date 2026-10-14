#!/usr/bin/env python3
"""Local session-aware extension of the ctx-bugs stand-in; no real inference."""
import argparse
import copy
import hashlib
import json
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'framework-ctx-bugs'))
import stub_server as base


class SessionStub(base.StubServer):
    def __init__(self,*,loop_mode='none',overflow='error',pool_full='evict',capacity=None,
                 interrupt_request=None,request_delay=0.02,**kwargs):
        super().__init__(**kwargs)
        self.RequestHandlerClass=SessionHandler
        self.loop_mode,self.overflow,self.pool_full=loop_mode,overflow,pool_full
        self.capacity=capacity
        self.interrupt_request=interrupt_request
        self.request_delay=request_delay
        self.caches={}
        self.reservations={}
        self.inflight=0
        self.max_inflight=0
        self.pool_events=[]
        self.request_events=[]

    def size(self):return 262144 if 'sess262k' in self.entry else 131072


class SessionHandler(base.Handler):
    def do_GET(self):
        s=self.server
        if self.path=='/health' and s.server_alive:
            self.reply(dict(status='ok',ctx_bugs_stub=True,loop_hunt_stub=True,
                            builds=base.BUILDS,server_instance=s.instance))
        elif self.path=='/props':
            build='nathanw' if '-nathanw' in s.entry else 'upstream'
            self.reply(dict(model_alias=s.entry,n_ctx=s.size(),total_slots=4,build_info=base.BUILDS[build]['build_info']))
        elif self.path=='/slots':
            self.reply([dict(id=i,n_ctx=s.size(),is_processing=i<s.inflight) for i in range(4)])
        elif self.path.startswith('/upstream/'):
            s.caches.clear()
            super().do_GET()
        else:super().do_GET()

    def do_POST(self):
        s=self.server
        if self.path.startswith('/api/models/unload/'):
            self.rfile.read(int(self.headers.get('Content-Length',0)))
            s.caches.clear()
            s.server_alive=False
            self.reply(dict(status='unloaded'))
            return
        if self.path=='/apply-template':
            payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
            prompt=base.render(payload['messages'])
            if payload.get('tools'):prompt='<tools>'+json.dumps(payload['tools'],sort_keys=True)+'</tools>'+prompt
            self.reply(dict(prompt=prompt))
            return
        if self.path!='/v1/chat/completions':return super().do_POST()
        payload=json.loads(self.rfile.read(int(self.headers.get('Content-Length',0))))
        messages=payload['messages']
        rendered=base.render(messages)
        if payload.get('tools'):rendered='<tools>'+json.dumps(payload['tools'],sort_keys=True)+'</tools>'+rendered
        count=base.token_count(rendered,s.entry)
        session=hashlib.sha256(messages[1]['content'].encode()).hexdigest() if len(messages)>1 else 'empty'
        with s.mutex:
            s.requests.append(copy.deepcopy(payload))
            number=len(s.requests)
            s.inflight+=1
            s.max_inflight=max(s.max_inflight,s.inflight)
            previous=s.caches.get(session,0) if payload.get('cache_prompt') else 0
            s.reservations[session]=count
            pool=sum(v for k,v in s.caches.items() if k not in s.reservations)+sum(s.reservations.values())
        try:
            time.sleep(s.request_delay)
            if number==s.interrupt_request:
                self.close_connection=True
                self.connection.shutdown(2)
                return
            capacity=s.capacity or s.size()
            if count>capacity and s.overflow=='error':
                self.reply(dict(error='context size exceeded',requested=count,capacity=capacity),400)
                return
            if pool>capacity:
                with s.mutex:
                    s.pool_events.append(dict(request=number,used=pool,behavior=s.pool_full))
                    if s.pool_full=='evict':
                        s.caches.clear()
                        previous=0
                if s.pool_full=='error':
                    self.reply(dict(error='shared KV pool exhausted',requested=pool,capacity=capacity),503)
                    return
            effective=min(count,capacity) if s.overflow=='truncate' else count
            facts={}
            for message in messages:
                if message['role']=='user':
                    for turn,value in re.findall(r'PLANTED FACT: turn (\d+) route value = (\S+)',message['content']):facts[int(turn)]=value
            user=next((m['content'] for m in reversed(messages) if m['role']=='user'),'')
            questions=re.findall(r'Q\d+: What is the route value recorded for turn (\d+)\?',user)
            expected=[facts.get(int(t),'NOT PROVIDED') for t in questions]
            if 'What is the incident recovery password?' in user:expected.append('NOT PROVIDED')
            reference=re.search(r'End with ref: (INC-\d+)',user)
            answer='[TRIAGE] '+ '\n'.join(f'Q{i}: {value}' for i,value in enumerate(expected,1))
            answer+='\nref: '+(reference[1] if reference else 'INC-7001')
            reasoning='Checked the supplied facts.'
            if s.loop_mode=='both' or s.loop_mode=='warm' and previous>0:
                reasoning=('The same reasoning phrase has already been considered; let us consider it once again. '*8)
            if payload.get('tools'):
                from session_tools import stub_agent_reply
                message,finish=stub_agent_reply(messages)
            else:message,finish=dict(role='assistant',content=answer,reasoning_content=reasoning),'stop'
            with s.mutex:
                s.caches[session]=effective
                s.request_events.append(dict(number=number,prompt_tokens=count,server_prompt_tokens=effective,cached_tokens=previous,stream=payload.get('stream')))
            usage=dict(prompt_tokens=effective,completion_tokens=base.token_count((message.get('content') or '')+(message.get('reasoning_content') or '')+(json.dumps(message['tool_calls'],sort_keys=True) if message.get('tool_calls') else ''),s.entry),
                       prompt_tokens_details=dict(cached_tokens=previous))
            result=dict(choices=[dict(message=message,finish_reason=finish)],usage=usage,
                        timings=dict(cache_n=previous,prompt_n=max(0,effective-previous),prompt_per_second=600,predicted_per_second=25))
            if payload.get('stream'):self.stream(result)
            else:self.reply(result)
        finally:
            with s.mutex:
                s.inflight-=1
                s.reservations.pop(session,None)

    def stream(self,result):
        message=result['choices'][0]['message']
        chunks=[]
        if message.get('reasoning_content'):chunks.append(dict(reasoning_content=message['reasoning_content']))
        if message.get('content'):chunks.append(dict(content=message['content']))
        for index,call in enumerate(message.get('tool_calls') or []):
            text=call['function']['arguments']
            middle=len(text)//2
            chunks.append(dict(tool_calls=[dict(index=index,id=call['id'],function=dict(name=call['function']['name'],arguments=text[:middle]))]))
            chunks.append(dict(tool_calls=[dict(index=index,function=dict(arguments=text[middle:]))]))
        frames=[dict(choices=[dict(index=0,delta=delta,finish_reason=None)]) for delta in chunks]
        frames.append(dict(choices=[dict(index=0,delta={},finish_reason=result['choices'][0]['finish_reason'])],usage=result['usage'],timings=result['timings']))
        body=''.join('data: '+json.dumps(frame)+'\n\n' for frame in frames)+'data: [DONE]\n\n'
        data=body.encode()
        self.send_response(200)
        self.send_header('Content-Type','text/event-stream')
        self.send_header('Content-Length',str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=18081)
    parser.add_argument('--loop-mode',choices=('none','warm','both'),default='none')
    parser.add_argument('--overflow',choices=('error','truncate'),default='error')
    parser.add_argument('--pool-full',choices=('error','evict'),default='evict')
    args=parser.parse_args()
    server=SessionStub(address=('127.0.0.1',args.port),loop_mode=args.loop_mode,overflow=args.overflow,pool_full=args.pool_full)
    print(server.url,flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
