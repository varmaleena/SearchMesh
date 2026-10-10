"""Model-planned research workflows and legacy conformance workloads."""

import threading

import time
from concurrent.futures import ThreadPoolExecutor,as_completed

from .scenarios import wait
from . import groq_model
from .client import SearchMeshClient,SearchMeshError


class ReleaseDesk:
    def __init__(self,desk,pool):
        self.desk,self.co,self.pool=desk,desk.co,pool

    def fetch(self,req):
        state=wait(self.co,req,125)
        if state['status']!='SUCCEEDED':return {'status':'FAILED','error':state.get('error_code'),'request_id':state['id'],'sources':[]}
        result=self.co.result(state['id'],'demo')
        rows=result['result'].get('organic_results',[])
        return {'status':'COMPLETED','request_id':state['id'],'response_id':result['response_id'],
            'sources':[{'title':r.get('title','Untitled'),'url':r.get('link',''),'snippet':r.get('snippet','')} for r in rows[:5]],
            'provider_id':result['result'].get('search_metadata',{}).get('id')}

    def tool_search(self,run,agent,query,gateway,token,force_refresh=True):
        from serpapi_search_tools import web_search,SearchResultFormat,SearchResultMode
        mesh=SearchMeshClient(gateway,run_id=run['id'],agent_id=agent,token=token,deadline_seconds=120,force_refresh=force_refresh)
        captured=[]
        class EvidenceClient:
            def search(self,params):
                envelope=mesh.search_with_metadata(params)
                captured.append(envelope)
                return envelope['result']
        tool=web_search(provider='function',client=EvidenceClient(),response_format=SearchResultFormat.JSON,mode=SearchResultMode.FULL)
        try:
            tool(query=query)
            return self.fetch(self.co.status(captured[0]['request_id'],'demo'))
        except SearchMeshError as error:
            return {'status':'FAILED','error':error.code,'sources':[]}
        except Exception:
            return {'status':'FAILED','error':'TOOL_SEARCH_FAILED','sources':[]}

    def launch(self,run,inputs,gateway,token):
        state={'kind':'release','run_id':run['id'],'inputs':inputs,'mode':self.desk.provider.mode,
            'status':'RUNNING','phase':'PLANNING' if self.desk.provider.mode=='live' and groq_model.ready() and inputs.get('question') else 'SHARED_SOURCE','error':None,'brief':None,'agents':{},'sections':[],
            'shared':None,'reuse':None,'recovery':None,
            'disclosure':'Three scripted research workers share an explicit prerequisite, then follow different queries. Source snippets are evidence leads, not independently verified claims. No model-generated interpretation in this mode.'}
        self.desk.save(state)
        names=['Research worker 1','Research worker 2','Research worker 3'] if inputs.get('question') else ['Release researcher','Breaking changes researcher','Platform researcher']
        def execute():
            try:
                version=inputs['version']
                planned=None
                if self.desk.provider.mode=='live' and groq_model.ready() and inputs.get('question'):
                    state['model']={'provider':'Groq','planning':'RUNNING','synthesis':'WAITING'}
                    self.desk.save(state)
                    planned=groq_model.plan(inputs['question'],inputs['angles'])
                    state['model']['planning']='COMPLETED'
                    state['planned_queries']=planned
                    state['disclosure']='Groq plans three searches and synthesizes retrieved snippets. SearchMesh coordinates bounded search workers through the official SerpApi tool adapter. Retrieved claims are not independently verified.'
                    state['phase']='SHARED_SOURCE';self.desk.save(state)
                shared=inputs.get('question') or f'site.python.org Python {version} release announcement'
                # Queue all subscribers before dispatch so the explicit common prerequisite
                # demonstrates in-flight sharing even if upstream cached results are fast.
                with ThreadPoolExecutor(max_workers=3) as clients:
                    with self.pool.dispatch_lock:
                        common=[clients.submit(self.tool_search,run,name,shared,gateway,token) for name in names]
                        until=time.monotonic()+10
                        while len(self.co.store.rows('SELECT id FROM requests WHERE run_id=?',(run['id'],)))<3:
                            if time.monotonic()>until:raise RuntimeError('Clients failed to submit shared prerequisite')
                            time.sleep(.01)
                    shared_results=[f.result() for f in common]
                evidence=shared_results[0]
                state['shared']=evidence
                state['phase']='INDEPENDENT_RESEARCH';self.desk.save(state)
                queries=[f'site.docs.python.org/3.{version.split(".")[1]}/whatsnew/ Python {version} new features',
                         f'site.docs.python.org/3.{version.split(".")[1]}/whatsnew/ Python {version} removed deprecated porting',
                         f'site.python.org Python {version} {inputs["platform"]} free-threaded limitations']
                if inputs.get('question'):
                    queries=planned or [shared+' '+angle for angle in inputs['angles']]
                def research(item):
                    name,query=item
                    result=self.tool_search(run,name,query,gateway,token)
                    result.update(agent=name,query=query)
                    return result
                with ThreadPoolExecutor(max_workers=3) as executor:
                    futures=[executor.submit(research,item) for item in zip(names,queries)]
                    for future in as_completed(futures):
                        state['sections'].append(future.result())
                        self.desk.save(state)
                state['phase']='FRESH_REUSE';self.desk.save(state)
                state['reuse']=self.tool_search(run,'Brief editor',shared,gateway,token,False)
                ids=[x['response_id'] for x in [evidence,*state['sections']] if x.get('response_id')]
                state['brief']='Source dossier: '+shared+'\n\n'+ ('SYNTHETIC WALKTHROUGH â€” source content is invented.\n\n' if self.desk.provider.mode=='fixture' else '')
                for section in state['sections']:
                    state['brief']+=section['agent']+'\n'
                    for source in section['sources']:
                        state['brief']+=source['title']+'\n'+source['snippet']+'\n'+source['url']+'\n\n'
                state['brief']+='Next checks: open primary sources and verify the exact claims, dates and conditions. These are retrieved search snippets, not an independently verified recommendation.'
                if state.get('model'):
                    state['phase']='SYNTHESIZING';state['model']['synthesis']='RUNNING';self.desk.save(state)
                    state['answer']=groq_model.synthesize(shared,[evidence,*state['sections']])
                    state['model']['synthesis']='COMPLETED'
                    state['brief']=state['answer']
                if ids:self.co.add_finding(run['id'],'demo',state['brief'][:5000],ids)
                state['status']='COMPLETED' if all(s['status']=='COMPLETED' for s in state['sections']) and all(s['status']=='COMPLETED' for s in shared_results) and state['reuse']['status']=='COMPLETED' else 'PARTIAL'
                state['phase']='READY'
            except Exception:
                state.update(status='FAILED',phase='STOPPED',error='Research interrupted. Completed evidence is preserved. Check model stages and execution events.')
                if state.get('model'):
                    for key in ('planning','synthesis'):
                        if state['model'][key]=='RUNNING':state['model'][key]='FAILED'
            finally:
                self.desk.save(state)
                with self.co.store.transaction() as c:c.execute("UPDATE runs SET status=? WHERE id=?",('COMPLETED' if state['status'] in {'COMPLETED','PARTIAL'} else 'FAILED',run['id']))
        threading.Thread(target=execute,daemon=True).start()
        return state

    def launch_automatic(self,run,inputs,gateway,token):
        state={'kind':'release','automatic':True,'run_id':run['id'],'inputs':inputs,'mode':self.desk.provider.mode,
               'status':'RUNNING','phase':'PLANNING','plan':None,'tasks':[],'sections':[],'shared':None,'error':None,'answer':None,
               'model':{'provider':'Groq' if self.desk.provider.mode=='live' else 'Synthetic fixture','planning':'RUNNING','synthesis':'WAITING'},
               'disclosure':'One question is decomposed into delegated tasks. Shared prerequisites are optional model-selected dependencies. Runtime scheduling is bounded; search snippets are not independently verified facts.'}
        self.desk.save(state)
        def save():
            with self.desk.lock:self.desk.save(state)
        def event(kind,data):
            with self.co.store.transaction() as c:self.co.event(c,self.co._run(c,run['id']),kind,data)
        def execute():
            try:
                live=self.desk.provider.mode=='live'
                if live:
                    if not groq_model.ready():raise RuntimeError('Groq is not configured')
                    plan=groq_model.automatic_plan(inputs['question'])
                else:
                    plan={'rationale':'Synthetic fixture plan for testing orchestration; no model inference.',
                          'tasks':[{'name':name,'objective':objective,'query':inputs['question']+' '+suffix,'needs_shared_context':False}
                                   for name,objective,suffix in [('Source scout','Find relevant primary sources','official sources'),('Details researcher','Find practical requirements and details','requirements details'),('Verifier','Find limitations and unresolved checks','limitations reviews')]],
                          'shared_query':None,'shared_reason':None}
                state['plan']=plan;state['model']['planning']='COMPLETED'
                state['tasks']=[{**task,'id':'task-'+str(i+1),'status':'WAITING','context_status':'NOT_NEEDED'} for i,task in enumerate(plan['tasks'])]
                event('research_plan_created',{'task_count':len(state['tasks']),'shared_dependency':bool(plan['shared_query']),'rationale':plan['rationale']})
                save()
                subscribers=[t for t in state['tasks'] if t['needs_shared_context']]
                context_results=[]
                if subscribers:
                    state['phase']='SHARED_SOURCE';save()
                    def context(task):
                        with self.desk.lock:task['context_status']='SEARCHING';save()
                        result=self.tool_search(run,task['name']+' '+task['id'],plan['shared_query'],gateway,token,False)
                        result.update(query=plan['shared_query'],agent=task['name']+' shared context')
                        with self.desk.lock:task['context_status']=result['status'];save()
                        return result
                    with ThreadPoolExecutor(max_workers=len(subscribers)) as pool:context_results=list(pool.map(context,subscribers))
                    state['shared']=context_results[0];save()
                state['phase']='INDEPENDENT_RESEARCH';save()
                def worker(task):
                    with self.desk.lock:task['status']='READING_CONTEXT' if task['needs_shared_context'] else 'SEARCHING';save()
                    event('research_task_delegated',{'task_id':task['id'],'name':task['name'],'objective':task['objective']})
                    try:
                        if live and task['needs_shared_context']:
                            refined=groq_model.refine_query(inputs['question'],task,state['shared'])
                            with self.desk.lock:task['query']=refined['query'];task['refinement_reason']=refined['reason'];task['status']='SEARCHING';save()
                            event('worker_query_refined',{'task_id':task['id'],'query':task['query'],'reason':refined['reason']})
                        result=self.tool_search(run,task['name']+' '+task['id'],task['query'],gateway,token,False)
                    except Exception:result={'status':'FAILED','error':'WORKER_MODEL_FAILED','sources':[]}
                    result.update(agent=task['name'],task_id=task['id'],query=task['query'])
                    with self.desk.lock:
                        task['status']=result['status'];state['sections'].append(result);save()
                    event('research_task_finished',{'task_id':task['id'],'status':result['status'],'response_id':result.get('response_id'),'error':result.get('error')})
                    return result
                with ThreadPoolExecutor(max_workers=len(state['tasks'])) as pool:results=list(pool.map(worker,state['tasks']))
                state['phase']='SYNTHESIZING';state['model']['synthesis']='RUNNING';save()
                evidence=[*context_results,*results]
                if live:state['answer']=groq_model.synthesize(inputs['question'],evidence)
                else:state['answer']='SYNTHETIC WALKTHROUGH — the planner and source content are fixtures. The worker tasks, retrieval jobs and events are real. No factual recommendation is established.'
                state['brief']=state['answer'];state['model']['synthesis']='COMPLETED'
                ids=list(dict.fromkeys(s['response_id'] for s in evidence if s.get('response_id')))
                if ids:self.co.add_finding(run['id'],'demo',state['answer'][:5000],ids)
                # Freeze actual query stages for fair replay; do not add requests to
                # manufacture joins or editor reuse. Replay normalizes fresh operations.
                state['replay_stages']=[]
                if subscribers:state['replay_stages'].append([{'engine':'google_light','q':plan['shared_query']} for _ in subscribers])
                if all(r.get('error')!='WORKER_MODEL_FAILED' for r in results):state['replay_stages'].append([{'engine':'google_light','q':t['query']} for t in state['tasks']])
                state['status']='COMPLETED' if all(r['status']=='COMPLETED' for r in evidence) else 'PARTIAL'
                state['phase']='READY';event('research_synthesis_finished',{'status':state['status'],'response_ids':ids})
            except Exception as error:
                state.update(status='FAILED',phase='STOPPED',error=groq_model.public_error(error))
                for name in ('planning','synthesis'):
                    if state['model'][name]=='RUNNING':state['model'][name]='FAILED'
            finally:
                save()
                with self.co.store.transaction() as c:c.execute("UPDATE runs SET status=? WHERE id=?",('COMPLETED' if state['status'] in {'COMPLETED','PARTIAL'} else 'FAILED',run['id']))
        threading.Thread(target=execute,daemon=True).start()
        return state

    def recover(self,original,run,gateway,token):
        state={'kind':'recovery','run_id':run['id'],'parent_run_id':original['run_id'],'mode':self.desk.provider.mode,'status':'RUNNING','phase':'FAILURE_INJECTION','error':None}
        self.desk.save(state)
        def execute():
            try:
                with self.pool.dispatch_lock:
                    self.pool.crash_next(run['id'])
                    with self.co.store.transaction() as c:
                        self.co.event(c,self.co._run(c,run['id']),'failure_injection_requested',{'simulation':True,'description':'Abandon one provider result; let the real lease recovery run.'})
                probe=original['inputs'].get('question') or f'site.python.org Python {original["inputs"]["version"]} release documentation recovery probe'
                state['result']=self.tool_search(run,'Recovery probe',probe,gateway,token)
                state['status']='COMPLETED' if state['result']['status']=='COMPLETED' else 'FAILED'
            except Exception:state.update(status='FAILED',error='Recovery probe failed; inspect the attempt log.')
            finally:
                self.desk.save(state)
                with self.co.store.transaction() as c:c.execute('UPDATE runs SET status=? WHERE id=?',(state['status'],run['id']))
        threading.Thread(target=execute,daemon=True).start()
        return state

