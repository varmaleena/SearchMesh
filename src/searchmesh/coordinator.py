"""Durable coordination. All ownership and budget mutations are transactional."""
import json
import time
import uuid
from .models import MeshFailure, SearchRequest
from .fingerprints import canonical, digest, fingerprint, content_hash, provider_time


def uid(prefix):
    return prefix + "-" + uuid.uuid4().hex[:16]


class Coordinator:
    def __init__(self, store, mode="fixture", clock=time.time, lease_seconds=30, max_attempts=3,max_per_run=2):
        self.store, self.mode, self.clock = store, mode, clock
        self.lease_seconds, self.max_attempts = lease_seconds, max_attempts
        self.max_per_run=max_per_run

    def event(self, c, run, kind, data=None, search=None, request=None):
        c.execute("INSERT INTO events(workspace_id,run_id,search_id,request_id,kind,data_json,created_at) VALUES(?,?,?,?,?,?,?)",
                  (run["workspace_id"], run["id"], search, request, kind, canonical(data or {}), self.clock()))

    def create_run(self, workspace, title, budget):
        with self.store.transaction() as c:
            if not c.execute("SELECT 1 FROM workspaces WHERE id=?", (workspace,)).fetchone():
                raise MeshFailure("FORBIDDEN", "Workspace is not available", 403)
            run_id = uid("run")
            c.execute("INSERT INTO runs(id,workspace_id,title,budget_limit,created_at) VALUES(?,?,?,?,?)", (run_id,workspace,title,budget,self.clock()))
            row = dict(c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone())
            self.event(c,row,"run_created",{"title":title,"mode":self.mode})
            return row

    def _run(self, c, run_id, workspace=None):
        row = c.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row or (workspace is not None and row["workspace_id"] != workspace):
            raise MeshFailure("NOT_FOUND", "Run not found", 404)
        return dict(row)

    def _fail(self, c, req, code, message):
        c.execute("UPDATE requests SET status='FAILED',error_code=?,error_message=?,finished_at=? WHERE id=?", (code,message,self.clock(),req["id"]))
        self.event(c,self._run(c,req["run_id"]),"request_failed",{"code":code,"message":message},req.get("search_id"),req["id"])

    def _eligible(self, response, policy, requested_at=None):
        if policy["force_refresh"]:
            return response["age_basis"] == "FRESH_PROVIDER_OPERATION" and response["effective_at"] >= requested_at
        at = response["effective_at"]
        return at is not None and -5 <= self.clock()-at <= policy["max_age_seconds"]

    def _reserve(self,c,run_id):
        return c.execute("UPDATE runs SET reserved_units=reserved_units+1 WHERE id=? AND attempted_units+reserved_units<budget_limit",(run_id,)).rowcount == 1

    def submit(self, request: SearchRequest):
        now = self.clock()
        payload = request.model_dump()
        ph = digest(payload)
        with self.store.transaction() as c:
            run = self._run(c,request.run_id,request.workspace_id)
            existing = c.execute("SELECT * FROM requests WHERE run_id=? AND idempotency_key=?",(request.run_id,request.idempotency_key)).fetchone()
            if existing:
                if existing["payload_hash"] != ph:
                    raise MeshFailure("IDEMPOTENCY_CONFLICT","Idempotency key was used with a different payload",409)
                return dict(existing)
            if run['status']!='ACTIVE':
                raise MeshFailure('RUN_CLOSED','This run is complete; create a new run for new work',409)
            scope = c.execute("SELECT credential_scope_id FROM workspaces WHERE id=?",(request.workspace_id,)).fetchone()[0]
            fp = fingerprint({"workspace":request.workspace_id,"credential":scope,"mode":self.mode},request.params)
            rid = uid("req")
            c.execute("INSERT INTO requests(id,run_id,workspace_id,agent_id,idempotency_key,payload_hash,policy_json,status,decision,reason,created_at,deadline_at) VALUES(?,?,?,?,?,?,?,'PENDING','EXECUTED','New retrieval requested',?,?)",
                      (rid,request.run_id,request.workspace_id,request.agent_id,request.idempotency_key,ph,canonical(payload["freshness"]),now,now+request.deadline_seconds))
            self.event(c,run,"request_submitted",{"agent_id":request.agent_id,"query":request.params["q"]},request=rid)
            req = dict(c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone())
            if not request.freshness.force_refresh:
                for resp in c.execute("SELECT * FROM responses WHERE workspace_id=? AND fingerprint=? ORDER BY received_at DESC",(request.workspace_id,fp)).fetchall():
                    if self._eligible(resp,payload["freshness"]):
                        c.execute("UPDATE requests SET status='SUCCEEDED',response_id=?,decision='REUSED_RESPONSE',reason='Exact retrieval parameters and freshness policy match',finished_at=? WHERE id=?",(resp["id"],now,rid))
                        self.event(c,run,"response_reused",{"response_id":resp["id"]},request=rid)
                        return dict(c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone())
            self._attach(c,req,request.params,fp,request.freshness.force_refresh)
            return dict(c.execute("SELECT * FROM requests WHERE id=?",(rid,)).fetchone())

    def _attach(self,c,req,params,fp,refresh):
        run = self._run(c,req["run_id"])
        ek = digest({"fingerprint":fp,"refresh":refresh})
        job = c.execute("SELECT s.* FROM active_keys a JOIN searches s ON a.search_id=s.id WHERE a.workspace_id=? AND a.execution_key=?",(req["workspace_id"],ek)).fetchone()
        # A force-refresh subscription requires an operation started after its submission.
        # QUEUED refresh work qualifies. A later force-refresh caller gets a new job.
        if job and refresh and job["started_at"] is not None and job["started_at"] <= req["created_at"]:
            ek = digest({"fingerprint":fp,"refresh_after":req["id"]})
            job = None
        if job:
            c.execute("UPDATE requests SET search_id=?,decision='JOINED_INFLIGHT',reason='Attached to compatible pending retrieval' WHERE id=?",(job["id"],req["id"]))
            self.event(c,run,"inflight_joined",{"owner_run_id":job["run_id"]},job["id"],req["id"])
            return
        if not self._reserve(c,req["run_id"]):
            self._fail(c,req,"BUDGET_EXHAUSTED","No provider-attempt units remain")
            return
        sid = uid("search")
        c.execute("INSERT INTO searches(id,workspace_id,run_id,fingerprint,execution_key,params_json,refresh,state,created_at) VALUES(?,?,?,?,?,?,?,'QUEUED',?)",(sid,req["workspace_id"],req["run_id"],fp,ek,canonical(params),int(refresh),self.clock()))
        c.execute("INSERT INTO active_keys VALUES(?,?,?)",(req["workspace_id"],ek,sid))
        c.execute("UPDATE requests SET search_id=?,decision=?,reason=? WHERE id=?",(sid,"REFRESH_REQUIRED" if refresh else "EXECUTED","Fresh provider operation required" if refresh else "No eligible stored or pending response",req["id"]))
        self.event(c,run,"search_queued",{"refresh":bool(refresh)},sid,req["id"])

    def _finish_job_error(self,c,job,code,message):
        c.execute("UPDATE searches SET state='FAILED',error_code=?,error_message=?,finished_at=? WHERE id=?",(code,message,self.clock(),job["id"]))
        c.execute("DELETE FROM active_keys WHERE search_id=?",(job["id"],))
        for req in c.execute("SELECT * FROM requests WHERE search_id=? AND status='PENDING'",(job["id"],)).fetchall():
            self._fail(c,dict(req),code,message)

    def claim(self, owner):
        with self.store.transaction() as c:
            # Timestamp dispatch after acquiring the transaction. A queued caller
            # may have committed while this worker was waiting for the lock.
            now=self.clock()
            # Deadlines are per subscriber, not per shared job.
            for req in c.execute("SELECT * FROM requests WHERE status='PENDING' AND deadline_at<=?",(now,)).fetchall():
                self._fail(c,dict(req),"DEADLINE_EXCEEDED","Caller deadline expired")
            for row in c.execute("SELECT * FROM searches WHERE state='RUNNING' AND lease_until<=?",(now,)).fetchall():
                job=dict(row)
                c.execute("UPDATE attempts SET outcome='AMBIGUOUS_WORKER_LOSS',finished_at=? WHERE search_id=? AND generation=? AND outcome='RUNNING'",(now,job["id"],job["generation"]))
                self.event(c,self._run(c,job["run_id"]),"lease_reclaimed",{"previous_generation":job["generation"]},job["id"])
                if job["attempt_count"] >= self.max_attempts or not self._reserve(c,job["run_id"]):
                    self._finish_job_error(c,job,"BUDGET_EXHAUSTED" if job["attempt_count"]<self.max_attempts else "PROVIDER_ERROR","Cannot reserve a recovery attempt")
                else:
                    c.execute("UPDATE searches SET state='RETRY_WAIT',not_before=? WHERE id=?",(now,job["id"]))
            row=c.execute("SELECT s.* FROM searches s WHERE s.state IN ('QUEUED','RETRY_WAIT') AND s.not_before<=? AND (SELECT COUNT(*) FROM searches running WHERE running.run_id=s.run_id AND running.state='RUNNING')<? ORDER BY s.created_at LIMIT 1",(now,self.max_per_run)).fetchone()
            if not row:
                return None
            job=dict(row)
            if not c.execute("SELECT 1 FROM requests WHERE search_id=? AND status='PENDING'",(job["id"],)).fetchone():
                c.execute("UPDATE runs SET reserved_units=reserved_units-1 WHERE id=?",(job["run_id"],))
                self._finish_job_error(c,job,"DEADLINE_EXCEEDED","No active subscribers remain")
                return None
            c.execute("UPDATE runs SET reserved_units=reserved_units-1,attempted_units=attempted_units+1 WHERE id=?",(job["run_id"],))
            generation=job["generation"]+1
            c.execute("UPDATE searches SET state='RUNNING',owner_token=?,generation=?,lease_until=?,attempt_count=attempt_count+1,started_at=? WHERE id=?",(owner,generation,now+self.lease_seconds,now,job["id"]))
            aid=uid("attempt")
            c.execute("INSERT INTO attempts(id,search_id,run_id,generation,started_at,outcome) VALUES(?,?,?,?,?,'RUNNING')",(aid,job["id"],job["run_id"],generation,now))
            self.event(c,self._run(c,job["run_id"]),"attempt_started",{"generation":generation},job["id"])
            claimed=dict(c.execute("SELECT * FROM searches WHERE id=?",(job["id"],)).fetchone())
            claimed["attempt_id"]=aid
            return claimed

    def heartbeat(self,job):
        with self.store.transaction() as c:
            return c.execute("UPDATE searches SET lease_until=? WHERE id=? AND owner_token=? AND generation=? AND state='RUNNING'",(self.clock()+self.lease_seconds,job["id"],job["owner_token"],job["generation"])).rowcount==1

    def _owner(self,c,job):
        row=c.execute("SELECT * FROM searches WHERE id=? AND owner_token=? AND generation=? AND state='RUNNING'",(job["id"],job["owner_token"],job["generation"])).fetchone()
        return dict(row) if row else None

    def complete(self,job,raw):
        now=self.clock()
        with self.store.transaction() as c:
            current=self._owner(c,job)
            if not current:
                return False
            sid=job["id"]
            c.execute("UPDATE attempts SET outcome='SUCCEEDED',finished_at=?,provider_search_id=? WHERE id=?",(now,raw.get("search_metadata",{}).get("id"),job["attempt_id"]))
            stamp=provider_time(raw)
            if job["refresh"]:
                basis, effective="FRESH_PROVIDER_OPERATION",job["started_at"]
            elif stamp is not None and stamp<=now+5:
                basis,effective="PROVIDER_TIMESTAMP",stamp
            else:
                basis,effective="UNKNOWN",None
            resp_id=uid("resp")
            ch=content_hash(raw)
            c.execute("INSERT INTO responses VALUES(?,?,?,?,?,?,?,?,?,?)",(resp_id,job["workspace_id"],job["fingerprint"],canonical(raw),ch,now,stamp,basis,effective,self.mode))
            c.execute("UPDATE searches SET state='SUCCEEDED',response_id=?,finished_at=? WHERE id=?",(resp_id,now,sid))
            c.execute("DELETE FROM active_keys WHERE search_id=?",(sid,))
            resp=dict(c.execute("SELECT * FROM responses WHERE id=?",(resp_id,)).fetchone())
            for row in c.execute("SELECT * FROM requests WHERE search_id=? AND status='PENDING'",(sid,)).fetchall():
                req=dict(row); policy=json.loads(req["policy_json"])
                if req["deadline_at"]<=now:
                    self._fail(c,req,"DEADLINE_EXCEEDED","Caller deadline expired")
                elif self._eligible(resp,policy,req["created_at"]):
                    c.execute("UPDATE requests SET status='SUCCEEDED',response_id=?,finished_at=? WHERE id=?",(resp_id,now,req["id"]))
                    self.event(c,self._run(c,req["run_id"]),"request_completed",{"response_id":resp_id,"age_basis":basis},sid,req["id"])
                elif not job["refresh"] and req["refresh_count"]==0 and (effective is not None or policy["unknown_age"]=="refresh"):
                    c.execute("UPDATE requests SET refresh_count=1 WHERE id=?",(req["id"],))
                    self._attach(c,req,json.loads(job["params_json"]),job["fingerprint"],True)
                else:
                    self._fail(c,req,"FRESHNESS_UNSATISFIED","Response cannot establish the requested retrieval age")
            self.event(c,self._run(c,job["run_id"]),"attempt_finished",{"outcome":"SUCCEEDED","response_id":resp_id},sid)
            # Registering dependencies is explicit; changes trigger review, not a truth verdict.
            affected=c.execute("SELECT DISTINCT f.id,f.run_id FROM findings f JOIN dependencies d ON f.id=d.finding_id JOIN responses r ON r.id=d.response_id WHERE r.workspace_id=? AND r.fingerprint=? AND r.content_hash<>? AND f.status='CURRENT'",(job["workspace_id"],job["fingerprint"],ch)).fetchall()
            for f in affected:
                c.execute("UPDATE findings SET status='NEEDS_REVIEW' WHERE id=?",(f["id"],))
                self.event(c,self._run(c,f["run_id"]),"evidence_changed",{"finding_id":f["id"],"new_response_id":resp_id},sid)
            return True

    def fail_attempt(self,job,error):
        with self.store.transaction() as c:
            current=self._owner(c,job)
            if not current:
                return False
            now=self.clock()
            c.execute("UPDATE attempts SET outcome=?,finished_at=? WHERE id=?",(error.code,now,job["attempt_id"]))
            self.event(c,self._run(c,job["run_id"]),"attempt_finished",{"outcome":error.code},job["id"])
            if error.retryable and current["attempt_count"]<self.max_attempts and self._reserve(c,job["run_id"]):
                delay=min(error.retry_after or (0.25*2**(current["attempt_count"]-1)),10)
                c.execute("UPDATE searches SET state='RETRY_WAIT',not_before=? WHERE id=?",(now+delay,job["id"]))
                self.event(c,self._run(c,job["run_id"]),"retry_scheduled",{"delay_seconds":delay},job["id"])
            else:
                self._finish_job_error(c,job,error.code,error.message)
            return True

    def status(self,request_id,workspace):
        rows=self.store.rows("SELECT * FROM requests WHERE id=? AND workspace_id=?",(request_id,workspace))
        if not rows: raise MeshFailure("NOT_FOUND","Request not found",404)
        return rows[0]

    def result(self,request_id,workspace):
        req=self.status(request_id,workspace)
        if req["status"]=="FAILED":
            raise MeshFailure(req["error_code"],req["error_message"],409)
        if req["status"]!="SUCCEEDED": raise MeshFailure("NOT_READY","Request is not complete",409)
        rows=self.store.rows("SELECT * FROM responses WHERE id=?",(req["response_id"],))
        if not rows: raise MeshFailure("RESULT_EXPIRED","Response was pruned",410)
        resp=rows[0]
        return {"request_id":request_id,"response_id":resp["id"],"decision":req["decision"],"result":json.loads(resp.pop("raw_json")),"provenance":resp}

    def add_finding(self,run_id,workspace,text,response_ids):
        with self.store.transaction() as c:
            run=self._run(c,run_id,workspace)
            for rid in response_ids:
                if not c.execute("SELECT 1 FROM responses WHERE id=? AND workspace_id=?",(rid,workspace)).fetchone():
                    raise MeshFailure("NOT_FOUND","Evidence response not found in this workspace",404)
            fid=uid("finding")
            c.execute("INSERT INTO findings(id,run_id,text,created_at) VALUES(?,?,?,?)",(fid,run_id,text,self.clock()))
            for rid in set(response_ids): c.execute("INSERT INTO dependencies VALUES(?,?)",(fid,rid))
            self.event(c,run,"finding_registered",{"finding_id":fid})
            return {"id":fid,"status":"CURRENT"}

    def report(self,run_id,workspace):
        runs=self.store.rows("SELECT * FROM runs WHERE id=? AND workspace_id=?",(run_id,workspace))
        if not runs: raise MeshFailure("NOT_FOUND","Run not found",404)
        requests=self.store.rows("SELECT q.*,s.params_json,s.fingerprint FROM requests q LEFT JOIN searches s ON s.id=q.search_id WHERE q.run_id=? ORDER BY q.created_at",(run_id,))
        for q in requests:
            if not q["params_json"] and q["response_id"]:
                # Provider echoes may add defaults. Reports must preserve the
                # canonical parameters actually submitted to the source job.
                source=self.store.rows("SELECT params_json,fingerprint FROM searches WHERE response_id=? AND workspace_id=? LIMIT 1",(q["response_id"],workspace))
                if source:
                    q["params_json"]=source[0]["params_json"]
                    q["fingerprint"]=source[0]["fingerprint"]
            q["params"]=json.loads(q.pop("params_json") or '{}')
            q["freshness"]=json.loads(q.pop("policy_json"))
        attempts=self.store.rows("SELECT * FROM attempts WHERE run_id=? ORDER BY started_at",(run_id,))
        findings=self.store.rows("SELECT * FROM findings WHERE run_id=? ORDER BY created_at",(run_id,))
        for f in findings:
            f["response_ids"]=[r["response_id"] for r in self.store.rows("SELECT response_id FROM dependencies WHERE finding_id=?",(f["id"],))]
        metrics={"requests":len(requests),"provider_attempts":runs[0]["attempted_units"],"reserved_units":runs[0]["reserved_units"],"joins":sum(q["decision"]=="JOINED_INFLIGHT" for q in requests),"reuses":sum(q["decision"]=="REUSED_RESPONSE" for q in requests),"failures":sum(q["status"]=="FAILED" for q in requests),"pending":sum(q["status"]=="PENDING" for q in requests)}
        return {"run":runs[0],"mode":self.mode,"metrics":metrics,"requests":requests,"attempts":attempts,"findings":findings}

