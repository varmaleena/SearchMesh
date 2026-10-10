from contextlib import contextmanager
from searchmesh.store import Store
from searchmesh.coordinator import Coordinator
from searchmesh.models import SearchRequest
from searchmesh.provider import FixtureProvider


def test_dispatch_time_is_sampled_after_transaction_lock(tmp_path):
    clock=[150.0]
    store=Store(tmp_path/'clock.sqlite')
    co=Coordinator(store,clock=lambda:clock[0])
    run=co.create_run('demo','Clock race',5)
    req=co.submit(SearchRequest(run_id=run['id'],agent_id='worker',idempotency_key='one',freshness={'force_refresh':True},params={'engine':'google_light','q':'same'}))
    original=store.transaction
    clock[0]=100.0
    @contextmanager
    def acquire():
        with original() as c:
            # Simulate lock acquisition after another caller committed.
            clock[0]=160.0
            yield c
    store.transaction=acquire
    job=co.claim('owner')
    assert job['started_at']>=req['created_at']
    co.complete(job,FixtureProvider(delay=0).search({'engine':'google_light','q':'same'},True))
    assert co.status(req['id'],'demo')['status']=='SUCCEEDED'


def test_reused_report_does_not_import_provider_defaults(tmp_path):
    store=Store(tmp_path/'echo.sqlite');co=Coordinator(store)
    run=co.create_run('demo','Exact report',5)
    params={'engine':'google_light','q':'exact'}
    first=co.submit(SearchRequest(run_id=run['id'],agent_id='one',idempotency_key='one',params=params))
    job=co.claim('owner')
    raw=FixtureProvider(delay=0).search(params)
    raw['search_parameters']={**params,'device':'desktop','google_domain':'google.com'}
    co.complete(job,raw)
    co.submit(SearchRequest(run_id=run['id'],agent_id='two',idempotency_key='two',params=params))
    report=co.report(run['id'],'demo')
    assert report['metrics']['reuses']==1
    assert all(row['params']==params for row in report['requests'])
    assert all(row['fingerprint'] for row in report['requests'])
