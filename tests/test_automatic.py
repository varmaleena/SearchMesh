import time
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider
from searchmesh.groq_model import ResearchPlan


def finish(client,path,field=None):
    for _ in range(600):
        data=client.get(path).json();state=data[field] if field else data
        if state['status']!='RUNNING':return data
        time.sleep(.02)
    raise AssertionError('Automatic research timed out')


def test_one_question_fixture_has_no_manufactured_repeats(tmp_path):
    app=create_app(tmp_path/'auto.sqlite',FixtureProvider(delay=.03),token='secret')
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client,patch('searchmesh.client.httpx.request',side_effect=lambda method,url,**kw:client.request(method,url,**kw)):
        response=client.post('/v1/workflows',json={'question':'Accessible museums in Bengaluru'})
        assert response.status_code==202
        run=response.json()['run_id'];data=finish(client,'/v1/workflows/'+run+'/execution','workflow')
        state=data['workflow'];m=data['report']['metrics']
        assert state['status']=='COMPLETED' and state['automatic']
        assert len(state['tasks'])==3 and state['plan']['shared_query'] is None
        assert m['requests']==m['provider_attempts']==3
        assert m['joins']==m['reuses']==0
        assert all(t['status']=='COMPLETED' for t in state['tasks'])
        assert any(e['kind']=='research_plan_created' for e in data['events'])
        path='/v1/workflows/'+run+'/comparison'
        assert client.post(path).status_code==202
        pair=finish(client,path)
        assert pair['status']=='COMPLETED'
        assert pair['direct']['requests']==pair['mesh']['requests']==3
        assert pair['direct']['provider_attempts']==pair['mesh']['provider_attempts']==3
        assert pair['mesh']['joins']==pair['mesh']['reuses']==0


def test_model_shared_dependency_is_used_to_refine_worker_queries(tmp_path):
    class LiveFixture(FixtureProvider):mode='live'
    plan={'rationale':'Two workers need the discovered entity list.', 'shared_query':'Bengaluru pottery workshops', 'shared_reason':'Discover names for price and review research.',
          'tasks':[{'name':'Pricing','objective':'Find prices','query':'pottery prices','needs_shared_context':True},
                   {'name':'Reviews','objective':'Find feedback','query':'pottery reviews','needs_shared_context':True},
                   {'name':'Transport','objective':'Find transport','query':'Bengaluru transport','needs_shared_context':False}]}
    app=create_app(tmp_path/'planned.sqlite',LiveFixture(delay=.05),token='secret')
    def refine(question,task,context):
        assert context['sources'] and context['response_id']
        return {'query':'discovered '+task['query'],'reason':'Used discovered context evidence.'}
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client,patch('searchmesh.client.httpx.request',side_effect=lambda method,url,**kw:client.request(method,url,**kw)),patch('searchmesh.groq_model.ready',return_value=True),patch('searchmesh.groq_model.automatic_plan',return_value=plan),patch('searchmesh.groq_model.refine_query',side_effect=refine) as refine_call,patch('searchmesh.groq_model.synthesize',return_value='Evidence-backed test answer'):
        run=client.post('/v1/workflows',json={'question':'Compare Bengaluru pottery workshops'}).json()['run_id']
        data=finish(client,'/v1/workflows/'+run+'/execution','workflow')
        state=data['workflow'];m=data['report']['metrics']
        assert state['status']=='COMPLETED'
        assert refine_call.call_count==2
        assert m['requests']==5 and m['provider_attempts']==4
        assert m['joins']+m['reuses']==1
        queries=[r['params']['q'] for r in data['report']['requests']]
        assert queries.count(plan['shared_query'])==2
        assert 'discovered pottery prices' in queries and 'discovered pottery reviews' in queries
        assert not any(r['agent_id']=='Brief editor' for r in data['report']['requests'])
        assert state['answer']=='Evidence-backed test answer'
        path='/v1/workflows/'+run+'/comparison';assert client.post(path).status_code==202
        pair=finish(client,path)
        assert pair['status']=='COMPLETED'
        assert pair['direct']['provider_attempts']==5 and pair['mesh']['provider_attempts']==4


def test_rejects_unjustified_shared_dependency():
    with pytest.raises(ValueError):ResearchPlan.model_validate({'rationale':'bad','shared_query':'repeated','shared_reason':'one worker only','tasks':[{'name':'a','objective':'a','query':'a','needs_shared_context':True},{'name':'b','objective':'b','query':'b','needs_shared_context':False}]})
