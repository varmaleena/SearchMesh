from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.provider import FixtureProvider


def test_dashboard_sessions_do_not_collide_across_ports(tmp_path):
    a=create_app(tmp_path/'a.sqlite',FixtureProvider(),token='first')
    b=create_app(tmp_path/'b.sqlite',FixtureProvider(),token='second')
    with TestClient(a,base_url='http://127.0.0.1:8000') as first, TestClient(b,base_url='http://127.0.0.1:8001') as second:
        first.post('/v1/session',headers={'X-SearchMesh-Local':'1'})
        second.cookies.update(first.cookies)
        second.post('/v1/session',headers={'X-SearchMesh-Local':'1'})
        first.cookies.update(second.cookies)
        assert first.get('/v1/config').status_code==200
        assert second.get('/v1/config').status_code==200
        assert len(first.cookies)==2
