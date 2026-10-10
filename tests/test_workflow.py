from unittest.mock import patch
import time
from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider


def finish(client,run):
    for _ in range(300):
        data=client.get('/v1/workflows/'+run+'/execution').json()
        if data['workflow']['status']!='RUNNING':return data
        time.sleep(.02)
    raise AssertionError('Workflow did not finish')


def test_workflow_sharing_branches_reuse_and_recovery(tmp_path):
    app=create_app(tmp_path/'workflow.sqlite',FixtureProvider(delay=.05),token='secret',lease_seconds=.2)
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client, patch('searchmesh.client.httpx.request',side_effect=lambda method,url,**kwargs:client.request(method,url,**kwargs)):
        response=client.post('/v1/workflows',json={})
        assert response.status_code==202
        run=response.json()['run_id'];data=finish(client,run)
        assert data['workflow']['status']=='COMPLETED'
        m=data['report']['metrics']
        assert m['requests']==7 and m['provider_attempts']==4
        assert m['joins']==2 and m['reuses']==1
        assert len(data['jobs'])==4
        assert all('owner_token' not in j for j in data['jobs'])
        recovery=client.post('/v1/workflows/'+run+'/recovery')
        assert recovery.status_code==202
        recovered=finish(client,recovery.json()['run_id'])
        assert recovered['workflow']['status']=='COMPLETED'
        assert recovered['report']['metrics']['provider_attempts']==2
        assert any(e['kind']=='lease_reclaimed' for e in recovered['events'])
        assert any(e['kind']=='failure_injection_requested' for e in recovered['events'])



def test_custom_question_drives_actual_queries(tmp_path):
    app=create_app(tmp_path/'custom.sqlite',FixtureProvider(delay=.05),token='secret')
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client, patch('searchmesh.client.httpx.request',side_effect=lambda method,url,**kwargs:client.request(method,url,**kwargs)):
        question='Find accessible museums in Bengaluru'
        angles=['opening hours','wheelchair access','public transport']
        assert client.post('/v1/workflows',json={'question':question,'angles':['only one']}).status_code==422
        response=client.post('/v1/workflows',json={'question':question,'angles':angles})
        assert response.status_code==202
        data=finish(client,response.json()['run_id'])
        assert data['workflow']['status']=='COMPLETED'
        queries=[r['params']['q'] for r in data['report']['requests']]
        assert queries.count(question)==4
        assert set(queries)=={question,*[question+' '+a for a in angles]}
        assert len(data['workflow']['sections'])==3
        assert all(s['sources'] for s in data['workflow']['sections'])
