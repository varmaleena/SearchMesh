"""Replay an exported investigation's real search trace, without inventing repeats.
This isolates retrieval coordination; it is NOT an end-to-end agent quality benchmark.
"""
import argparse
import json
import os
import tempfile
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .coordinator import Coordinator
from .fingerprints import canonical, content_hash
from .models import SearchRequest
from .provider import FixtureProvider, SerpApiProvider
from .scenarios import wait
from .store import Store
from .worker import WorkerPool


def evaluate(trace, mode='fixture', iterations=3):
    requests=trace.get('requests',[])
    if not requests or len(requests)>50:
        raise ValueError('Export a run with 1–50 search requests from Run explorer')
    # Researchers run concurrently, each preserving its own tool-call order.
    # Verifier searches follow all researcher searches.
    groups={}
    for item in requests:
        params=item['params']
        SearchRequest(run_id='validation',agent_id='validation',idempotency_key='validation',params=params)
        groups.setdefault(item['agent_id'],[]).append(params)
    phases=[{k:v for k,v in groups.items() if k!='verifier'},
            {k:v for k,v in groups.items() if k=='verifier'}]
    samples=[]
    for iteration in range(iterations):
        # Alternate order to reduce systematic warm-cache/time ordering bias.
        order=['Direct','Shared TTL','SearchMesh']
        if iteration%2: order.reverse()
        for baseline in order:
            upstream=FixtureProvider(delay=.025) if mode=='fixture' else SerpApiProvider(os.environ.get('SERPAPI_API_KEY'))
            lock=threading.Lock(); cache={}; calls=[]; outcomes=[]
            class MeasuredProvider:
                mode=upstream.mode
                def search(self,params,refresh=False):
                    start=time.perf_counter();success=False
                    try:
                        result=upstream.search(params,refresh)
                        success=True
                        return result
                    finally:
                        with lock:calls.append({'seconds':time.perf_counter()-start,'succeeded':success})
            provider=MeasuredProvider()
            with tempfile.TemporaryDirectory() as directory:
                co=Coordinator(Store(Path(directory)/'evaluation.sqlite'),mode=mode,max_per_run=2)
                run=co.create_run('demo','Trace replay',max(20,len(requests)*3))
                workers=WorkerPool(co,provider,size=2)
                if baseline=='SearchMesh':workers.start()
                direct_slots=threading.Semaphore(2)
                def one(agent,params):
                    started=time.perf_counter()
                    try:
                        if baseline=='SearchMesh':
                            submitted=co.submit(SearchRequest(run_id=run['id'],agent_id=agent,idempotency_key=uuid.uuid4().hex,params=params,deadline_seconds=120))
                            state=wait(co,submitted,125)
                            if state['status']!='SUCCEEDED':raise RuntimeError('Request failed')
                            raw=co.result(state['id'],'demo')['result']
                        else:
                            key=canonical(params)
                            with lock:stored=cache.get(key)
                            raw=stored[1] if baseline=='Shared TTL' and stored and time.time()-stored[0]<=300 else None
                            if raw is None:
                                with direct_slots:raw=provider.search(params)
                                with lock:cache[key]=(time.time(),raw)
                        outcome={'agent':agent,'params':params,'success':True,'content_hash':content_hash(raw)}
                    except Exception:
                        outcome={'agent':agent,'params':params,'success':False,'content_hash':None}
                    outcome['seconds']=time.perf_counter()-started
                    with lock:outcomes.append(outcome)
                def sequence(agent,queries):
                    for params in queries:one(agent,params)
                started=time.perf_counter()
                try:
                    for phase in phases:
                        with ThreadPoolExecutor(max_workers=max(1,len(phase))) as executor:
                            futures=[executor.submit(sequence,agent,queries) for agent,queries in phase.items()]
                            for future in futures:future.result()
                    elapsed=time.perf_counter()-started
                finally:
                    if baseline=='SearchMesh':workers.close()
                samples.append({'iteration':iteration+1,'baseline':baseline,'provider_attempts':len(calls),
                                'failures':sum(not x['success'] for x in outcomes),'wall_seconds':elapsed,
                                'requests':outcomes,'provider_calls':calls})
    return {'mode':mode,'measured':True,'trace_run':trace.get('run',{}).get('id'),
            'requests_per_trial':len(requests),'iterations':iterations,'samples':samples,
            'methodology':'Identical exported queries and parameters; per-agent order preserved; verifier runs last; two outbound slots; independent cold local caches; alternate baseline order. SerpApi upstream caches remain enabled. Direct/TTL use one attempt; SearchMesh bounded retries are included in attempts and failures. Timing excludes local setup and shutdown. This is search-trace replay, not agent-output evaluation or billed credit measurement. Source changes may change hashes between baselines.',
            'quality':'Review the original live brief separately with docs/evaluation-rubric.md; no automatic quality score is claimed.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',required=True)
    parser.add_argument('--mode',choices=['fixture','live'],default='fixture')
    parser.add_argument('--iterations',type=int,choices=range(1,11),default=3)
    parser.add_argument('--output',default='reports/trace-evaluation.json')
    args=parser.parse_args()
    report=evaluate(json.loads(Path(args.trace).read_text(encoding='utf-8')),args.mode,args.iterations)
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Saved measured trace replay:',path)
    for row in report['samples']:
        print(row['baseline'],row['provider_attempts'],'attempts;',row['failures'],'failures;',round(row['wall_seconds'],3),'seconds')

if __name__=='__main__':main()
