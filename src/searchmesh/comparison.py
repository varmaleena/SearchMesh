"""Replay a frozen, model-generated query manifest through direct tools and the mesh adapter."""
import json
from collections import Counter
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from .provider import ProviderError


class ComparisonDesk:
    def __init__(self, workflow):
        self.workflow=workflow
        self.desk=workflow.desk
        self.lock=threading.Lock()
        self.states={}
        self.active=False

    def get(self, run_id):
        with self.lock:
            value=self.states.get(run_id)
            return json.loads(json.dumps(value)) if value else {"status":"IDLE"}

    def launch(self, original, gateway, token):
        from .models import MeshFailure
        report=self.workflow.co.report(original['run_id'],'demo')
        recorded=[r['params'] for r in report['requests']]
        if original.get('automatic'):
            stages=original.get('replay_stages') or []
            manifest=[params for stage in stages for params in stage]
            if not manifest or Counter(json.dumps(p,sort_keys=True) for p in manifest)!=Counter(json.dumps(p,sort_keys=True) for p in recorded):
                raise MeshFailure('UNSUPPORTED_TRACE','This plan does not have a complete replayable query manifest.',409)
            fresh=[True]*len(manifest)
        else:
            manifest=recorded
            if len(manifest)!=7 or not all(p==manifest[0] for p in manifest[:3]) or manifest[-1]!=manifest[0]:
                raise MeshFailure('UNSUPPORTED_TRACE','This legacy trace cannot be replayed.',409)
            stages=[manifest[:3],manifest[3:6],manifest[6:]]
            fresh=[True]*6+[False]
        groups=[];offset=0
        for stage in stages:
            groups.append(list(range(offset,offset+len(stage))));offset+=len(stage)
        with self.lock:
            if self.active:raise MeshFailure('COMPARISON_BUSY','A comparison is already running.',409)
            self.active=True
            state={'status':'RUNNING','phase':'DIRECT','mode':self.desk.provider.mode,
                   'source_run_id':original['run_id'],'manifest':manifest,'stages':groups,'force_refresh':fresh,'direct':None,'mesh':None,'error':None,
                    'methodology':'One sequential direct-then-mesh trial of this run’s same recorded queries and concurrent stages. Automatic plans add no duplicate calls or editor repeat. Both replay paths normalize fresh retrieval operations to avoid prior local cache entries; this can differ from the original run’s normal freshness policy. The legacy final editor repeat permits reuse. Maximum two simultaneous provider operations. Mesh queues each replay stage before dispatch for a controlled concurrent comparison. Upstream caching, content and network conditions can differ. Attempts are not billed credits. No statistical speedup claim.'}
            self.states[original['run_id']]=state
        def save():
            with self.lock:
                path=self.desk.directory/('comparison-'+original['run_id']+'.json')
                temp=path.with_suffix('.tmp');temp.write_text(json.dumps(state),encoding='utf-8');temp.replace(path)
        def execute():
            try:
                from serpapi_search_tools import web_search,SearchResultFormat,SearchResultMode
                counter=0;counter_lock=threading.Lock();limit=threading.Semaphore(2)
                def direct(item):
                    index,params=item;started=time.perf_counter()
                    class DirectClient:
                        def search(client, translated):
                            nonlocal counter
                            if translated!=params:raise ValueError('Tool translation changed the frozen parameters')
                            for attempt in range(3):
                                try:
                                    with limit:
                                        with counter_lock:counter+=1
                                        return self.desk.provider.search(translated,refresh=fresh[index])
                                except ProviderError as error:
                                    if not error.retryable or attempt==2:raise
                                    time.sleep(min(error.retry_after or .25*2**attempt,10))
                    try:
                        tool=web_search(provider='function',client=DirectClient(),response_format=SearchResultFormat.JSON,mode=SearchResultMode.FULL)
                        raw=tool(query=params['q'])
                        return {'index':index,'status':'SUCCEEDED','latency_ms':round((time.perf_counter()-started)*1000,2)}
                    except Exception:
                        return {'index':index,'status':'FAILED','latency_ms':round((time.perf_counter()-started)*1000,2)}
                started=time.perf_counter();rows=[]
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for group in groups:rows.extend(pool.map(direct,[(i,manifest[i]) for i in group]))
                state['direct']={'requests':len(manifest),'provider_attempts':counter,'failures':sum(r['status']=='FAILED' for r in rows),'wall_ms':round((time.perf_counter()-started)*1000,2),'calls':rows}
                state['phase']='SEARCHMESH';save()
                run=self.workflow.co.create_run('demo','Comparison: frozen trace replay',20)
                state['mesh_run_id']=run['id'];save()
                started=time.perf_counter();rows=[]
                def mesh(item):
                    i,params=item;start=time.perf_counter()
                    result=self.workflow.tool_search(run,'Comparison worker '+str(i+1),params['q'],gateway,token,fresh[i])
                    return {'index':i,'status':result['status'],'error':result.get('error'),'response_id':result.get('response_id'),'latency_ms':round((time.perf_counter()-start)*1000,2)}
                expected=0
                with ThreadPoolExecutor(max_workers=4) as pool:
                    for group in groups:
                        expected+=len(group)
                        with self.workflow.pool.dispatch_lock:
                            tasks=[pool.submit(mesh,(i,manifest[i])) for i in group]
                            until=time.monotonic()+15
                            while len(self.workflow.co.store.rows('SELECT id FROM requests WHERE run_id=?',(run['id'],)))<expected:
                                if time.monotonic()>until:raise RuntimeError('Comparison clients did not submit')
                                time.sleep(.01)
                        rows.extend(f.result() for f in tasks)
                mesh_report=self.workflow.co.report(run['id'],'demo')
                actual=[r['params'] for r in mesh_report['requests']]
                if Counter(json.dumps(p,sort_keys=True) for p in actual)!=Counter(json.dumps(p,sort_keys=True) for p in manifest):raise RuntimeError('Replay manifest mismatch')
                state['mesh']={**mesh_report['metrics'],'wall_ms':round((time.perf_counter()-started)*1000,2),'calls':rows}
                with self.workflow.co.store.transaction() as c:c.execute("UPDATE runs SET status='COMPLETED' WHERE id=?",(run['id'],))
                state['status']='COMPLETED';state['phase']='READY'
            except Exception:
                state.update(status='FAILED',phase='STOPPED',error='Comparison did not complete. Partial measurements remain visible; inspect the replay run if available.')
                if state.get('mesh_run_id'):
                    with self.workflow.co.store.transaction() as c:c.execute("UPDATE runs SET status='FAILED' WHERE id=?",(state['mesh_run_id'],))
            finally:
                save()
                with self.lock:self.active=False
        threading.Thread(target=execute,daemon=True).start()
        return self.get(original['run_id'])
