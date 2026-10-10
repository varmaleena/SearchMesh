import asyncio
import json
import secrets
import threading
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI,Request,Depends
from fastapi.responses import JSONResponse,FileResponse,StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,model_validator
from .models import MeshFailure,RunCreate,SearchRequest,FindingCreate
from .store import Store
from .coordinator import Coordinator
from .worker import WorkerPool
from .scenarios import run_scenario
from .benchmarks import benchmark
from .research import ResearchDesk,live_ready
from .release import ReleaseDesk
from .comparison import ComparisonDesk


def create_app(db_path,provider,token=None,lease_seconds=30,workers=4,tokens=None):
    token=token or secrets.token_urlsafe(32)
    permissions=tokens or {token:"demo"}
    store=Store(db_path)
    signature=hashlib.sha256((provider.mode+':'+getattr(provider,'api_key','fixture')).encode()).hexdigest()
    with store.transaction() as c:
        c.execute('CREATE TABLE IF NOT EXISTS runtime_identity(signature TEXT NOT NULL)')
        identity=c.execute('SELECT signature FROM runtime_identity').fetchone()
        if identity and identity[0]!=signature:
            raise ValueError('This database belongs to another provider mode or credential. Use a separate --db path.')
        if not identity:c.execute('INSERT INTO runtime_identity VALUES(?)',(signature,))
    co=Coordinator(store,provider.mode,lease_seconds=lease_seconds)
    pool=WorkerPool(co,provider,workers)
    desk=ResearchDesk(co,provider,Path(db_path).parent)
    workflow=ReleaseDesk(desk,pool)
    comparison=ComparisonDesk(workflow)
    benchmark_state={"state":"IDLE","report":None,"error":None}
    benchmark_path=Path(db_path).parent/"latest-benchmark.json"
    if benchmark_path.exists():
        try:benchmark_state.update(state="COMPLETED",report=json.loads(benchmark_path.read_text(encoding="utf-8")))
        except (ValueError,OSError):pass
    state_lock=threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        pool.start()
        yield
        pool.close()

    app=FastAPI(title="SearchMesh",version="0.1.0",lifespan=lifespan)
    app.state.coordinator=co;app.state.pool=pool;app.state.token=token

    @app.exception_handler(MeshFailure)
    async def failure_handler(request,error):
        return JSONResponse({"error":{"code":error.code,"message":error.message}},status_code=error.status)

    @app.middleware("http")
    async def constraints(request,call_next):
        try: length=int(request.headers.get("content-length","0"))
        except ValueError: length=65537
        if urlparse(str(request.base_url)).hostname not in {"127.0.0.1","localhost","testserver"}:
            return JSONResponse({"error":{"code":"FORBIDDEN","message":"Only local hostnames are supported"}},status_code=403)
        if length>65536:
            return JSONResponse({"error":{"code":"INVALID_REQUEST","message":"Request exceeds 64 KB"}},status_code=413)
        # Browser writes must originate on this exact local origin. No permissive CORS.
        origin=request.headers.get("origin")
        if request.method not in {"GET","HEAD","OPTIONS"} and origin and origin != str(request.base_url).rstrip('/'):
            return JSONResponse({"error":{"code":"FORBIDDEN","message":"Cross-origin writes are disabled"}},status_code=403)
        response=await call_next(request)
        response.headers["X-Content-Type-Options"]="nosniff"
        response.headers["Referrer-Policy"]="no-referrer"
        response.headers["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        return response

    def auth(request:Request):
        header=request.headers.get("authorization","")
        supplied=header[7:] if header.startswith("Bearer ") else request.cookies.get(f"mesh_session_{request.url.port or 80}_{provider.mode}","")
        for key,workspace in permissions.items():
            if secrets.compare_digest(supplied,key): return workspace
        raise MeshFailure("UNAUTHORIZED","A valid gateway token is required",401)

    def own_run(run_id,workspace):
        if not store.rows("SELECT 1 FROM runs WHERE id=? AND workspace_id=?",(run_id,workspace)):
            raise MeshFailure("NOT_FOUND","Run not found",404)

    @app.post("/v1/session")
    def session(request:Request):
        # Same-origin custom-header handshake allows local UI use without leaking API token.
        # Loopback is the explicit trust boundary, not a production remote auth mechanism.
        hostname=urlparse(str(request.base_url)).hostname
        if hostname not in {"127.0.0.1","localhost","testserver"} or request.headers.get("x-searchmesh-local")!="1" or request.headers.get("sec-fetch-site") not in {None,"same-origin"}:
            raise MeshFailure("FORBIDDEN","Local dashboard session denied",403)
        response=JSONResponse({"workspace_id":"demo","mode":provider.mode,"user":"Developer operating an agent team"})
        response.set_cookie(f"mesh_session_{request.url.port or 80}_{provider.mode}",token,httponly=True,samesite="strict",max_age=86400)
        return response

    @app.get("/v1/config")
    def config(workspace=Depends(auth)):
        return {"mode":provider.mode,"workspace_id":workspace,"version":"0.1.0","research_ready":provider.mode=='fixture' or live_ready(),"engines":["google_light","google","google_news"]}

    class InvestigationBody(BaseModel):
        service:str=Field(min_length=1,max_length=160)
        current:str=Field(pattern=r'^3\.\d{1,2}$')
        target:str=Field(pattern=r'^3\.\d{1,2}$')
        dependencies:str=Field(min_length=1,max_length=1000)
        platform:str=Field(min_length=1,max_length=160)

    @app.post('/v1/investigations',status_code=202)
    def investigate(body:InvestigationBody,request:Request,workspace=Depends(auth)):
        if workspace!='demo': raise MeshFailure('FORBIDDEN','Local research workspace only',403)
        if provider.mode=='live' and not live_ready():
            raise MeshFailure('MODEL_NOT_CONFIGURED','Set GOOGLE_API_KEY and SEARCHMESH_MODEL on the gateway, then restart it.',409)
        with state_lock:
            if store.rows("SELECT 1 FROM runs WHERE workspace_id=? AND status='RUNNING'",(workspace,)):
                raise MeshFailure('RESEARCH_BUSY','Let the current investigation finish first',409)
            run=co.create_run(workspace,'Migration: '+body.service,20)
            # ACTIVE is required by the coordinator; job concurrency tracked separately.
            jobs=store.rows("SELECT id FROM runs WHERE workspace_id=? AND status='ACTIVE' AND title LIKE 'Migration:%'",(workspace,))
            if len(jobs)>1:
                with store.transaction() as c:c.execute("UPDATE runs SET status='FAILED' WHERE id=?",(run['id'],))
                raise MeshFailure('RESEARCH_BUSY','Let the current investigation finish first',409)
            return desk.launch(run,body.model_dump(),str(request.base_url).rstrip('/'),token)

    class WorkflowBody(BaseModel):
        version:str=Field('3.13',pattern=r'^3\.\d{1,2}$')
        platform:str=Field('Linux x86_64',min_length=1,max_length=100)
        question:str|None=Field(None,min_length=1,max_length=500)
        angles:list[str]=Field(default_factory=list,max_length=3)

        @model_validator(mode='after')
        def check_angles(self):
            if self.question and self.angles and (len(self.angles)!=3 or any(not a.strip() or len(a)>300 for a in self.angles)):
                raise ValueError('Provide three nonempty research angles of at most 300 characters')
            return self

    @app.post('/v1/workflows',status_code=202)
    def start_workflow(body:WorkflowBody,request:Request,workspace=Depends(auth)):
        if workspace!='demo':raise MeshFailure('FORBIDDEN','Local workspace only',403)
        with state_lock:
            if store.rows("SELECT 1 FROM runs WHERE status='ACTIVE' AND title LIKE 'Workflow:%'"):
                raise MeshFailure('WORKFLOW_BUSY','A workflow is already running',409)
            run=co.create_run(workspace,'Workflow: '+(body.question or 'shared prerequisite and branches')[:180],20)
            return (workflow.launch_automatic if body.question and not body.angles else workflow.launch)(run,body.model_dump(),str(request.base_url).rstrip('/'),token)

    @app.post('/v1/workflows/{run_id}/recovery',status_code=202)
    def recover_workflow(run_id:str,request:Request,workspace=Depends(auth)):
        own_run(run_id,workspace)
        original=desk.get(run_id)
        if not original or original.get('kind')!='release' or original['status']=='RUNNING':
            raise MeshFailure('WORKFLOW_BUSY','Finish the main workflow before the recovery probe',409)
        with state_lock:
            if store.rows("SELECT 1 FROM runs WHERE status='ACTIVE' AND title='Workflow: recovery probe'"):
                raise MeshFailure('WORKFLOW_BUSY','A recovery probe is already running',409)
            run=co.create_run(workspace,'Workflow: recovery probe',5)
            return workflow.recover(original,run,str(request.base_url).rstrip('/'),token)

    @app.post('/v1/workflows/{run_id}/comparison',status_code=202)
    def compare_workflow(run_id:str,request:Request,workspace=Depends(auth)):
        own_run(run_id,workspace)
        original=desk.get(run_id)
        if workspace!='demo' or not original or original.get('kind')!='release' or original['status']=='RUNNING':
            raise MeshFailure('WORKFLOW_BUSY','Finish a research run before comparing.',409)
        return comparison.launch(original,str(request.base_url).rstrip('/'),token)

    @app.get('/v1/workflows/{run_id}/comparison')
    def get_comparison(run_id:str,workspace=Depends(auth)):
        own_run(run_id,workspace)
        return comparison.get(run_id)

    @app.get('/v1/workflows/{run_id}/execution')
    def workflow_execution(run_id:str,workspace=Depends(auth)):
        own_run(run_id,workspace)
        report=co.report(run_id,workspace)
        jobs=store.rows('SELECT * FROM searches WHERE run_id=? ORDER BY created_at',(run_id,))
        for job in jobs:
            job['params']=json.loads(job.pop('params_json'))
            job.pop('owner_token',None)
        rows=store.rows('SELECT * FROM events WHERE run_id=? ORDER BY id',(run_id,))
        for row in rows:row['data']=json.loads(row.pop('data_json'))
        return {'report':report,'jobs':jobs,'events':rows,'workflow':desk.get(run_id)}

    @app.get('/v1/investigations/{run_id}')
    def investigation(run_id:str,workspace=Depends(auth)):
        own_run(run_id,workspace)
        state=desk.get(run_id)
        if state is None: raise MeshFailure('NOT_FOUND','Investigation not found',404)
        return state

    @app.get("/healthz")
    def health(): return {"status":"ok"}

    @app.get("/readyz")
    def ready():
        try: store.rows("SELECT 1")
        except Exception: return JSONResponse({"status":"unavailable"},status_code=503)
        return {"status":"ready"}

    @app.post("/v1/runs",status_code=201)
    def create_run(body:RunCreate,workspace=Depends(auth)):
        if body.workspace_id!=workspace: raise MeshFailure("FORBIDDEN","Workspace access denied",403)
        return co.create_run(workspace,body.title,body.budget_limit)

    @app.get("/v1/runs")
    def runs(workspace=Depends(auth)):
        return store.rows("SELECT * FROM runs WHERE workspace_id=? ORDER BY created_at DESC LIMIT 100",(workspace,))

    @app.post("/v1/runs/{run_id}/complete")
    def complete_run(run_id:str,workspace=Depends(auth)):
        own_run(run_id,workspace)
        with store.transaction() as c:
            if c.execute("SELECT 1 FROM requests WHERE run_id=? AND status='PENDING'",(run_id,)).fetchone():
                raise MeshFailure("RUN_BUSY","Pending requests must finish first",409)
            c.execute("UPDATE runs SET status='COMPLETED' WHERE id=?",(run_id,))
        return {"id":run_id,"status":"COMPLETED"}

    @app.post("/v1/requests",status_code=202)
    def submit(body:SearchRequest,workspace=Depends(auth)):
        if body.workspace_id!=workspace: raise MeshFailure("FORBIDDEN","Workspace access denied",403)
        result=co.submit(body);result["status_url"]="/v1/requests/"+result["id"]
        return result

    @app.get("/v1/requests/{request_id}")
    def status(request_id:str,workspace=Depends(auth)): return co.status(request_id,workspace)

    @app.get("/v1/requests/{request_id}/result")
    def result(request_id:str,workspace=Depends(auth)): return co.result(request_id,workspace)

    @app.get("/v1/runs/{run_id}/report")
    def report(run_id:str,workspace=Depends(auth)): return co.report(run_id,workspace)

    @app.get("/v1/runs/{run_id}/events")
    async def events(run_id:str,request:Request,workspace=Depends(auth)):
        own_run(run_id,workspace)
        try: after=int(request.headers.get("last-event-id",request.query_params.get("after","0")))
        except ValueError: raise MeshFailure("INVALID_REQUEST","Invalid event cursor",422)
        async def stream():
            cursor=after
            while not await request.is_disconnected():
                rows=store.rows("SELECT * FROM events WHERE run_id=? AND id>? ORDER BY id LIMIT 100",(run_id,cursor))
                for row in rows:
                    cursor=row["id"];row["data"]=json.loads(row.pop("data_json"))
                    yield f"id: {cursor}\ndata: {json.dumps(row)}\n\n"
                if not rows: yield ": heartbeat\n\n"
                await asyncio.sleep(.35)
        return StreamingResponse(stream(),media_type="text/event-stream",headers={"Cache-Control":"no-cache"})

    @app.get("/v1/runs/{run_id}/event-log")
    def event_log(run_id:str,workspace=Depends(auth)):
        own_run(run_id,workspace)
        rows=store.rows("SELECT * FROM events WHERE run_id=? ORDER BY id",(run_id,))
        for row in rows: row["data"]=json.loads(row.pop("data_json"))
        return rows

    @app.post("/v1/findings",status_code=201)
    def finding(body:FindingCreate,workspace=Depends(auth)):
        return co.add_finding(body.run_id,workspace,body.text,body.response_ids)

    class ScenarioBody(BaseModel):
        kind:str

    @app.post("/v1/demo")
    def demo(body:ScenarioBody,workspace=Depends(auth)):
        if provider.mode!="fixture": raise MeshFailure("UNSUPPORTED","Synthetic scenarios are disabled in live mode",409)
        if workspace!="demo": raise MeshFailure("FORBIDDEN","Demo workspace only",403)
        titles={"sharing":"One search. Four agents.","qualifier":"Similar is not equivalent.","recovery":"A worker fails. The work survives.","evidence":"New evidence. Findings need review.","budget":"A hard limit stays a hard limit."}
        if body.kind not in titles: raise MeshFailure("INVALID_REQUEST","Unknown scenario",422)
        with state_lock:
            active=store.rows("SELECT 1 FROM runs WHERE workspace_id='demo' AND status='ACTIVE' AND title IN (?,?,?,?,?)",tuple(titles.values()))
            if active: raise MeshFailure("DEMO_BUSY","Another demo is running; let it finish first",409)
            run=co.create_run(workspace,titles[body.kind],2 if body.kind=="budget" else 12)
        def execute():
            try: run_scenario(co,provider,pool,body.kind,run["id"])
            except Exception:
                with store.transaction() as c:
                    c.execute("UPDATE runs SET status='FAILED' WHERE id=?",(run["id"],))
        threading.Thread(target=execute,daemon=True).start()
        return {"run_id":run["id"],"mode":"fixture","scenario":body.kind}

    @app.post("/v1/benchmark")
    def start_benchmark(workspace=Depends(auth)):
        if provider.mode!="fixture": raise MeshFailure("UNSUPPORTED","Dashboard benchmarks are fixture-only",409)
        with state_lock:
            if benchmark_state["state"]=="RUNNING": return benchmark_state
            benchmark_state.update(state="RUNNING",error=None)
        def execute():
            try:
                report=benchmark(30)
                benchmark_path.write_text(json.dumps(report,indent=2),encoding="utf-8")
                with state_lock: benchmark_state.update(state="COMPLETED",report=report)
            except Exception:
                with state_lock: benchmark_state.update(state="FAILED",error="Benchmark execution failed; inspect local tests")
        threading.Thread(target=execute,daemon=True).start()
        return benchmark_state

    @app.get("/v1/benchmark")
    def get_benchmark(workspace=Depends(auth)): return benchmark_state

    static=Path(__file__).parent/"static"
    app.mount("/static",StaticFiles(directory=static),name="static")
    @app.get("/")
    def index(): return FileResponse(static/"index.html")
    return app


