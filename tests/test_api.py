from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider


def test_local_session_and_auth(tmp_path):
    app=create_app(tmp_path/'api.sqlite',FixtureProvider(delay=.01),token='secret')
    with TestClient(app) as client:
        assert client.get('/v1/runs').status_code==401
        assert client.post('/v1/session',headers={'X-SearchMesh-Local':'1','Origin':'https://evil.example'}).status_code==403
        assert client.post('/v1/session',headers={'X-SearchMesh-Local':'1'}).status_code==200
        assert client.get('/v1/runs').status_code==200
        assert client.get('/').status_code==200
        assert 'Content-Security-Policy' in client.get('/').headers


def test_authenticated_workspace_boundary(tmp_path):
    app=create_app(tmp_path/'api.sqlite',FixtureProvider(delay=.01),token='demo-token',tokens={'demo-token':'demo','other-token':'other'})
    with app.state.coordinator.store.transaction() as c:c.execute("INSERT INTO workspaces VALUES('other','other-scope')")
    with TestClient(app) as client:
        run=client.post('/v1/runs',headers={'Authorization':'Bearer demo-token'},json={'title':'Test'}).json()
        assert client.get('/v1/runs/'+run['id']+'/report',headers={'Authorization':'Bearer other-token'}).status_code==404
        assert client.post('/v1/runs',headers={'Authorization':'Bearer other-token'},json={'workspace_id':'demo'}).status_code==403


def test_fixture_scenario_and_event_log(tmp_path):
    import time
    app=create_app(tmp_path/'api.sqlite',FixtureProvider(delay=.2),token='secret',lease_seconds=.2)
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client:
        r=client.post('/v1/demo',json={'kind':'sharing'});assert r.status_code==200
        run=r.json()['run_id']
        for _ in range(100):
            report=client.get(f'/v1/runs/{run}/report').json()
            if report['run']['status']!='ACTIVE':break
            time.sleep(.02)
        assert report['metrics']['requests']==4
        assert report['metrics']['provider_attempts']==1
        events=client.get(f'/v1/runs/{run}/event-log').json()
        assert [e['id'] for e in events]==sorted(e['id'] for e in events)
        assert any(e['kind']=='inflight_joined' for e in events)


def test_live_mode_disables_injections(tmp_path):
    provider=FixtureProvider();provider.mode='live'
    app=create_app(tmp_path/'api.sqlite',provider,token='secret')
    with TestClient(app,headers={'Authorization':'Bearer secret'}) as client:
        assert client.post('/v1/demo',json={'kind':'recovery'}).status_code==409
        assert client.post('/v1/benchmark').status_code==409


def test_fake_host_denied(tmp_path):
    app=create_app(tmp_path/'api.sqlite',FixtureProvider(),token='secret')
    with TestClient(app) as client:assert client.get('/',headers={'Host':'evil.example'}).status_code==403

