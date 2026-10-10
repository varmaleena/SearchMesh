"""Disclosed scripted clients, real coordinator, synthetic provider results."""
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from .models import SearchRequest, MeshFailure


def request(coordinator,run_id,agent,q,force=False,budget_age=300):
    return coordinator.submit(SearchRequest(run_id=run_id,agent_id=agent,idempotency_key=uuid.uuid4().hex,params={"engine":"google_light","q":q,"hl":"en","gl":"in"},freshness={"max_age_seconds":budget_age,"force_refresh":force},deadline_seconds=30))


def wait(coordinator,req,timeout=35):
    until=time.monotonic()+timeout
    while time.monotonic()<until:
        s=coordinator.status(req["id"],req["workspace_id"])
        if s["status"]!="PENDING": return s
        time.sleep(.025)
    raise TimeoutError("Scenario request did not finish")


def run_scenario(coordinator,provider,workers,kind,run_id):
    q="Fixture migration / " + run_id
    try:
        if kind=="sharing":
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures=[executor.submit(request,coordinator,run_id,a,q) for a in ("Compatibility agent","Platform agent","Verifier")]
                requests=[f.result() for f in futures]
            for r in requests: wait(coordinator,r)
            wait(coordinator,request(coordinator,run_id,"Follow-up agent",q))
        elif kind=="qualifier":
            wait(coordinator,request(coordinator,run_id,"Compatibility agent",q+" Python 3.13 support"))
            wait(coordinator,request(coordinator,run_id,"Verifier",q+" Python 3.13 free-threaded support"))
        elif kind=="recovery":
            workers.crash_next()
            wait(coordinator,request(coordinator,run_id,"Research agent",q))
        elif kind=="evidence":
            first=wait(coordinator,request(coordinator,run_id,"Research agent",q))
            if first["status"]!="SUCCEEDED": raise RuntimeError("Initial retrieval failed")
            coordinator.add_finding(run_id,"demo","The synthetic bulletin documents standard support; exact platform still requires checking.",[first["response_id"]])
            with provider._lock: provider.revision+=1
            wait(coordinator,request(coordinator,run_id,"Verifier",q,True))
        elif kind=="budget":
            reqs=[request(coordinator,run_id,"Research agent",q+f" variant {i}") for i in range(4)]
            for r in reqs: wait(coordinator,r)
        else: raise ValueError("Unknown scenario")
    finally:
        with coordinator.store.transaction() as c:
            c.execute("UPDATE runs SET status='COMPLETED' WHERE id=?",(run_id,))

