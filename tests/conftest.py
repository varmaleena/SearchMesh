import time
import uuid
import pytest
from searchmesh.store import Store
from searchmesh.coordinator import Coordinator
from searchmesh.provider import FixtureProvider
from searchmesh.worker import WorkerPool
from searchmesh.models import SearchRequest


@pytest.fixture
def mesh(tmp_path):
    co=Coordinator(Store(tmp_path/"test.sqlite"),lease_seconds=2)
    provider=FixtureProvider(delay=.025)
    pool=WorkerPool(co,provider)
    run=co.create_run("demo","Test run",100)
    yield co,provider,pool,run
    pool.close()


def submit(co,run,q="query",**changes):
    body={"run_id":run["id"],"agent_id":"test-agent","idempotency_key":uuid.uuid4().hex,"params":{"engine":"google_light","q":q}}
    body.update(changes)
    return co.submit(SearchRequest(**body))


def terminal(co,req,timeout=6):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        state=co.status(req["id"],req["workspace_id"])
        if state["status"]!="PENDING":return state
        time.sleep(.01)
    raise AssertionError("Request did not finish")

