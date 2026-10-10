import os
import time
import uuid
import httpx


class SearchMeshError(Exception):
    def __init__(self,code,message):
        super().__init__(f"{code}: {message}")
        self.code=code


class SearchMeshClient:
    """Synchronous serpapi-search-tools client. Identity is explicit, never global."""
    def __init__(self,gateway_url="http://127.0.0.1:8000",workspace_id="demo",run_id=None,agent_id="agent",max_age_seconds=300,token=None,deadline_seconds=30,force_refresh=False):
        self.url=gateway_url.rstrip('/')
        self.workspace_id,self.run_id,self.agent_id=workspace_id,run_id,agent_id
        self.max_age_seconds,self.deadline_seconds=max_age_seconds,deadline_seconds
        self.force_refresh=force_refresh
        self.token=token or os.getenv("SEARCHMESH_GATEWAY_TOKEN","")

    def _call(self,method,path,**kwargs):
        for attempt in range(3):
            try:
                r=httpx.request(method,self.url+path,headers={"Authorization":"Bearer "+self.token},timeout=10,**kwargs)
                body=r.json()
                if r.status_code>=400:
                    error=body.get("error",{})
                    raise SearchMeshError(error.get("code","HTTP_ERROR"),error.get("message",f"HTTP {r.status_code}"))
                return body
            except (httpx.TimeoutException,httpx.NetworkError):
                if attempt==2: raise SearchMeshError("GATEWAY_UNAVAILABLE","Gateway transport failed") from None
                time.sleep(.1*2**attempt)

    def create_run(self,title="Agent investigation",budget_limit=20):
        r=self._call("POST","/v1/runs",json={"workspace_id":self.workspace_id,"title":title,"budget_limit":budget_limit})
        self.run_id=r["id"]
        return r

    def search_with_metadata(self,params):
        if not self.run_id: raise SearchMeshError("INVALID_REQUEST","Create or supply a run_id first")
        envelope={"workspace_id":self.workspace_id,"run_id":self.run_id,"agent_id":self.agent_id,"idempotency_key":uuid.uuid4().hex,"freshness":{"max_age_seconds":self.max_age_seconds,"unknown_age":"refresh","force_refresh":self.force_refresh},"deadline_seconds":self.deadline_seconds,"params":params}
        # _call retries this exact envelope; no new idempotency key on transport retry.
        request=self._call("POST","/v1/requests",json=envelope)
        until=time.monotonic()+self.deadline_seconds+1
        pause=.04
        while request["status"]=="PENDING":
            if time.monotonic()>=until: raise SearchMeshError("DEADLINE_EXCEEDED","Poll deadline expired; request remains retrievable")
            time.sleep(pause); pause=min(pause*1.25,.3)
            request=self._call("GET","/v1/requests/"+request["id"])
        if request["status"]=="FAILED": raise SearchMeshError(request["error_code"],request["error_message"])
        return self._call("GET","/v1/requests/"+request["id"]+"/result")

    def search(self,params):
        return self.search_with_metadata(params)["result"]

