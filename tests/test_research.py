from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider
import time


def test_investigation_workflow(tmp_path):
    app=create_app(tmp_path/'desk.sqlite',FixtureProvider(delay=.15),token='secret')
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client:
        body={'service':'Payments API','current':'3.12','target':'3.13','dependencies':'FastAPI, NumPy','platform':'Linux x86_64'}
        response=client.post('/v1/investigations',json=body)
        assert response.status_code==202
        run=response.json()['run_id']
        for _ in range(150):
            state=client.get('/v1/investigations/'+run).json()
            if state['status']!='RUNNING':break
            time.sleep(.02)
        assert state['status']=='COMPLETED'
        assert 'SYNTHETIC WALKTHROUGH' in state['brief']
        assert all(a['status']=='COMPLETED' for a in state['agents'].values())
        report=client.get('/v1/runs/'+run+'/report').json()
        assert report['metrics']['requests']==3
        assert report['metrics']['provider_attempts']==2
        assert report['findings']
        assert client.post('/v1/investigations',json={**body,'target':'invalid'}).status_code==422
