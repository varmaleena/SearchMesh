import json
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from pydantic import ValidationError
from searchmesh.models import SearchRequest,MeshFailure
from searchmesh.fingerprints import fingerprint,provider_time
from searchmesh.provider import ProviderError
from searchmesh.store import Store
from searchmesh.coordinator import Coordinator
from searchmesh.worker import WorkerPool
from conftest import submit,terminal


def test_twenty_concurrent_requests_share_one_attempt(mesh):
    co,p,pool,run=mesh
    with ThreadPoolExecutor(max_workers=20) as e: requests=list(e.map(lambda _:submit(co,run),range(20)))
    pool.start()
    final=[terminal(co,r) for r in requests]
    assert p.calls==1
    assert len({r['response_id'] for r in final})==1
    assert sum(r['decision']=='JOINED_INFLIGHT' for r in final)==19


def test_fresh_response_reused_without_budget(mesh):
    co,p,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run))
    other=co.create_run("demo","No budget",0)
    second=terminal(co,submit(co,other))
    assert first['response_id']==second['response_id']
    assert second['decision']=='REUSED_RESPONSE' and p.calls==1


@pytest.mark.parametrize('field,value',[('gl','in'),('hl','de'),('start',10),('engine','google'),('q','query free-threaded'),('q','"query"'),('q','query  '),('tbs','qdr:d')])
def test_retrieval_qualifiers_never_merge(mesh,field,value):
    co,p,pool,run=mesh
    one=submit(co,run)
    two=submit(co,run,params={'engine':'google_light','q':'query',field:value})
    pool.start();terminal(co,one);terminal(co,two)
    assert p.calls==2


def test_idempotency_retrieves_and_conflict_rejects(mesh):
    co,_,_,run=mesh
    first=submit(co,run,idempotency_key='stable')
    second=submit(co,run,idempotency_key='stable')
    assert first['id']==second['id']
    with pytest.raises(MeshFailure) as error:submit(co,run,q='different',idempotency_key='stable')
    assert error.value.code=='IDEMPOTENCY_CONFLICT'


def test_budget_race_cannot_overspend(mesh):
    co,p,pool,_=mesh;run=co.create_run('demo','Limited',2)
    with ThreadPoolExecutor(max_workers=10) as e: requests=list(e.map(lambda i:submit(co,run,q=str(i)),range(10)))
    pool.start();final=[terminal(co,r) for r in requests]
    assert p.calls==2 and sum(r['status']=='FAILED' for r in final)==8
    report=co.report(run['id'],'demo')
    assert report['metrics']['provider_attempts']==2 and report['metrics']['reserved_units']==0


def test_stale_provider_cache_refreshes(mesh):
    co,p,pool,run=mesh;pool.start()
    result=terminal(co,submit(co,run,q='[stale]'))
    assert result['status']=='SUCCEEDED' and p.calls==2
    assert co.result(result['id'],'demo')['provenance']['age_basis']=='FRESH_PROVIDER_OPERATION'


def test_unknown_age_can_be_rejected(mesh):
    co,p,pool,run=mesh;pool.start()
    result=terminal(co,submit(co,run,q='[unknown-age]',freshness={'unknown_age':'reject'}))
    assert result['error_code']=='FRESHNESS_UNSATISFIED' and p.calls==1


def test_unknown_age_refresh_establishes_operation_boundary(mesh):
    co,p,pool,run=mesh;pool.start()
    result=terminal(co,submit(co,run,q='[unknown-age]'))
    envelope=co.result(result['id'],'demo')
    assert p.calls==2 and envelope['provenance']['upstream_created_at'] is None
    assert envelope['provenance']['age_basis']=='FRESH_PROVIDER_OPERATION'


def test_force_refresh_does_not_reuse_existing_response(mesh):
    co,p,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run))
    second=terminal(co,submit(co,run,freshness={'force_refresh':True}))
    assert p.calls==2 and first['response_id']!=second['response_id']


def test_transient_failure_retries_and_counts_each_attempt(mesh):
    co,p,pool,run=mesh;pool.start()
    state=terminal(co,submit(co,run,q='[retry-once]'))
    assert state['status']=='SUCCEEDED' and p.calls==2
    assert co.report(run['id'],'demo')['metrics']['provider_attempts']==2


def test_auth_failure_not_retried(mesh):
    co,p,pool,run=mesh;pool.start()
    state=terminal(co,submit(co,run,q='[auth-fail]'))
    assert state['error_code']=='PROVIDER_AUTH_ERROR' and p.calls==1


def test_empty_result_is_success(mesh):
    co,_,pool,run=mesh;pool.start()
    state=terminal(co,submit(co,run,q='[empty]'))
    assert co.result(state['id'],'demo')['result']['organic_results']==[]


def test_old_worker_cannot_overwrite_reclaimed_job(mesh):
    co,p,_,run=mesh
    req=submit(co,run);old=co.claim('old-worker')
    with co.store.transaction() as c:c.execute('UPDATE searches SET lease_until=0 WHERE id=?',(old['id'],))
    new=co.claim('new-worker')
    assert new['generation']>old['generation']
    assert co.complete(old,p.search({'engine':'google_light','q':'old'})) is False
    assert co.complete(new,p.search({'engine':'google_light','q':'new'})) is True
    assert co.status(req['id'],'demo')['status']=='SUCCEEDED'


def test_restart_recovers_pending_request(mesh):
    co,p,_,run=mesh;req=submit(co,run)
    new=Coordinator(Store(co.store.path),lease_seconds=.2)
    pool=WorkerPool(new,p);pool.start()
    try:assert terminal(new,req)['status']=='SUCCEEDED'
    finally:pool.close()


def test_worker_loss_scenario_recovers(mesh):
    co,_,pool,run=mesh
    pool.crash_next();pool.start()
    state=terminal(co,submit(co,run))
    assert state['status']=='SUCCEEDED'
    kinds=[r['kind'] for r in co.store.rows('SELECT kind FROM events WHERE run_id=?',(run['id'],))]
    assert 'lease_reclaimed' in kinds


def test_changed_evidence_flags_explicit_dependencies(mesh):
    co,p,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run))
    co.add_finding(run['id'],'demo','A synthetic finding',[first['response_id']])
    p.revision=2
    terminal(co,submit(co,run,freshness={'force_refresh':True}))
    assert co.report(run['id'],'demo')['findings'][0]['status']=='NEEDS_REVIEW'


def test_metadata_only_change_does_not_invalidate(mesh):
    co,p,pool,run=mesh;pool.start()
    first=terminal(co,submit(co,run))
    co.add_finding(run['id'],'demo','A synthetic finding',[first['response_id']])
    terminal(co,submit(co,run,freshness={'force_refresh':True}))
    assert co.report(run['id'],'demo')['findings'][0]['status']=='CURRENT'


def test_workspace_cache_isolation(mesh):
    co,p,pool,run=mesh
    with co.store.transaction() as c:c.execute("INSERT INTO workspaces VALUES('other','local-serpapi')")
    other=co.create_run('other','Other',20)
    a=submit(co,run);b=submit(co,other,workspace_id='other')
    pool.start();terminal(co,a);terminal(co,b)
    assert p.calls==2
    with pytest.raises(MeshFailure):co.result(a['id'],'other')


def test_deadline_does_not_cancel_other_subscriber(mesh):
    co,_,pool,run=mesh
    a=submit(co,run,deadline_seconds=.001);b=submit(co,run)
    time.sleep(.01);pool.start()
    assert terminal(co,a)['error_code']=='DEADLINE_EXCEEDED'
    assert terminal(co,b)['status']=='SUCCEEDED'


@pytest.mark.parametrize('key',['api_key','url','output','async','no_cache'])
def test_transport_keys_rejected(key):
    with pytest.raises(ValidationError):SearchRequest(run_id='run',agent_id='a',idempotency_key='x',params={'engine':'google','q':'q',key:'x'})


def test_timestamp_requires_timezone():
    assert provider_time({'search_metadata':{'created_at':'2026-10-10 10:00:00'}}) is None
    assert provider_time({'search_metadata':{'created_at':'2026-10-10 10:00:00 UTC'}}) is not None
