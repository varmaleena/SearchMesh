import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider,ProviderError


def wait_json(client,path,field=None):
    for _ in range(500):
        data=client.get(path).json()
        state=data[field] if field else data
        if state['status']!='RUNNING':return data
        time.sleep(.02)
    raise AssertionError('Background execution timed out')


def test_identical_trace_comparison_and_failures(tmp_path):
    provider=FixtureProvider(delay=.02)
    app=create_app(tmp_path/'compare.sqlite',provider,token='secret')
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client,patch('searchmesh.client.httpx.request',side_effect=lambda method,url,**kw:client.request(method,url,**kw)):
        run=client.post('/v1/workflows',json={'question':'workshops','angles':['prices','dates','reviews']}).json()['run_id']
        original=wait_json(client,'/v1/workflows/'+run+'/execution','workflow')
        assert original['workflow']['status']=='COMPLETED'
        path='/v1/workflows/'+run+'/comparison'
        assert client.get(path).json()['status']=='IDLE'
        assert client.post(path).status_code==202
        result=wait_json(client,path)
        assert result['status']=='COMPLETED',result
        assert result['direct']['provider_attempts']==7
        assert result['mesh']['provider_attempts']==4
        assert result['direct']['failures']==result['mesh']['failures']==0
        assert result['mesh']['joins']==2 and result['mesh']['reuses']==1
        assert result['manifest']==[r['params'] for r in original['report']['requests']]
        assert len({row['response_id'] for row in result['mesh']['calls'][:3]})==1
        original_search=provider.search
        def fail_one(params,refresh=False):
            if params['q']=='workshops prices':raise ProviderError('PROVIDER_ERROR','Controlled failure')
            return original_search(params,refresh)
        with patch.object(provider,'search',side_effect=fail_one):
            assert client.post(path).status_code==202
            failed=wait_json(client,path)
        assert failed['status']=='COMPLETED'
        assert failed['direct']['failures']==failed['mesh']['failures']==1
        assert failed['mesh']['provider_attempts']==4
