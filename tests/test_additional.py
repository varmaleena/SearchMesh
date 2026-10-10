import time
from unittest.mock import patch
import httpx
from fastapi.testclient import TestClient
from searchmesh.api import create_app
from searchmesh.client import SearchMeshClient
from searchmesh.provider import FixtureProvider,SerpApiProvider,ProviderError
from searchmesh.models import MeshFailure
from conftest import submit,terminal


def test_real_tools_through_gateway(tmp_path):
    from serpapi_search_tools import web_search,news_search,SearchResultFormat
    app=create_app(tmp_path/'tools.sqlite',FixtureProvider(delay=.01),token='secret')
    with TestClient(app) as http:
        def send(method,url,**kwargs):return http.request(method,url,**kwargs)
        with patch('searchmesh.client.httpx.request',side_effect=send):
            mesh=SearchMeshClient(token='secret')
            run=mesh.create_run('Real package transport',10)
            web=web_search(provider='function',client=mesh,response_format=SearchResultFormat.JSON)
            news=news_search(provider='function',client=mesh,response_format=SearchResultFormat.JSON)
            assert 'Synthetic' in web(query='compatibility')
            assert 'Synthetic' in news(query='compatibility updates')
            report=http.get('/v1/runs/'+run['id']+'/report',headers={'Authorization':'Bearer secret'}).json()
            assert report['metrics']['provider_attempts']==2


def test_provider_redacts_echoed_secrets():
    raw={'search_metadata':{'status':'Success'},'search_parameters':{'api_key':'sensitive'},'organic_results':[{'link':'https://example.org?api_key=sensitive'}]}
    response=httpx.Response(200,json=raw)
    with patch('searchmesh.provider.httpx.get',return_value=response):
        result=SerpApiProvider('sensitive').search({'engine':'google','q':'test'})
    assert 'sensitive' not in str(result) and 'api_key' not in result['search_parameters']


def test_provider_auth_status_is_terminal():
    with patch('searchmesh.provider.httpx.get',return_value=httpx.Response(401)):
        try:SerpApiProvider('secret').search({'engine':'google','q':'test'})
        except ProviderError as e:assert e.code=='PROVIDER_AUTH_ERROR' and not e.retryable
        else:raise AssertionError('Expected authentication failure')


def test_per_run_concurrency_limit(mesh):
    co,_,_,run=mesh
    for i in range(3):submit(co,run,str(i))
    assert co.claim('a') and co.claim('b')
    assert co.claim('c') is None


def test_closed_run_rejects_new_work_but_keeps_idempotency(mesh):
    co,_,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run,idempotency_key='same'))
    with co.store.transaction() as c:c.execute("UPDATE runs SET status='COMPLETED' WHERE id=?",(run['id'],))
    assert submit(co,run,idempotency_key='same')['id']==first['id']
    try:submit(co,run,'new')
    except MeshFailure as e:assert e.code=='RUN_CLOSED'
    else:raise AssertionError('Closed run accepted new work')


def test_force_refresh_cannot_join_older_running_operation(mesh):
    co,p,_,run=mesh
    first=submit(co,run,freshness={'force_refresh':True})
    old=co.claim('old')
    second=submit(co,run,freshness={'force_refresh':True})
    assert first['search_id']!=second['search_id']
    new=co.claim('new')
    assert old['id']!=new['id']
    co.complete(old,p.search({'engine':'google','q':'q'}))
    co.complete(new,p.search({'engine':'google','q':'q'}))


def test_prune_preserves_registered_evidence(mesh,monkeypatch):
    from searchmesh.cli import main
    co,_,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run))
    co.add_finding(run['id'],'demo','Keep this evidence',[first['response_id']])
    with co.store.transaction() as c:c.execute("UPDATE runs SET status='COMPLETED',created_at=? WHERE id=?",(time.time()-86400*30,run['id']))
    monkeypatch.setattr('sys.argv',['searchmesh','prune','--db',co.store.path,'--days','7'])
    main()
    assert co.report(run['id'],'demo')['findings']


def test_store_constructor_does_not_leak_file_handle(tmp_path):
    from searchmesh.store import Store
    path=tmp_path/'closed.sqlite'
    store=Store(path)
    path.unlink()  # Windows rejects this if a connection is still open.
    assert not path.exists()
