import argparse
import json
import os
import secrets
import sys
import time
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(prog="searchmesh",description="Shared, persistent SerpApi retrieval for agent teams")
    commands=parser.add_subparsers(dest="command",required=True)
    serve=commands.add_parser("serve",help="Start local runtime and dashboard")
    serve.add_argument("--mode",choices=["fixture","live"],default="fixture")
    serve.add_argument("--port",type=int,default=int(os.getenv("SEARCHMESH_PORT","8000")))
    serve.add_argument("--db",default=os.getenv("SEARCHMESH_DB_PATH"))
    serve.add_argument("--open",action="store_true",help="Open dashboard in the default browser")
    demo=commands.add_parser("demo",help="Run a fixture scenario or real ADK agent team")
    demo.add_argument("--mode",choices=["fixture","live"],default="fixture")
    demo.add_argument("--scenario",choices=["sharing","qualifier","recovery","evidence","budget"],default="sharing")
    demo.add_argument("--gateway",default="http://127.0.0.1:8000")
    bench=commands.add_parser("benchmark",help="Measure fixture-only coordination baselines")
    bench.add_argument("--mode",choices=["fixture"],default="fixture")
    bench.add_argument("--iterations",type=int,default=30)
    bench.add_argument("--output",default="reports")
    prune=commands.add_parser("prune",help="Prune old completed runs that have no registered findings")
    prune.add_argument("--db",default=os.getenv("SEARCHMESH_DB_PATH","data/searchmesh.sqlite3"))
    prune.add_argument("--days",type=int,default=7)
    args=parser.parse_args()
    if args.command=="serve":
        import uvicorn
        from .api import create_app
        from .provider import FixtureProvider,SerpApiProvider
        token=os.getenv("SEARCHMESH_GATEWAY_TOKEN") or secrets.token_urlsafe(32)
        try: provider=FixtureProvider() if args.mode=="fixture" else SerpApiProvider(os.getenv("SERPAPI_API_KEY"))
        except ValueError as e: parser.error(str(e))
        print(f"\n  SearchMesh v0.1.0 | {args.mode.upper()} mode")
        print(f"  Dashboard: http://127.0.0.1:{args.port}")
        print(f"  Agent access token: {token}")
        print("  Treat this local token as a secret. Set SEARCHMESH_GATEWAY_TOKEN to persist it.\n",flush=True)
        if args.open:
            import threading,webbrowser
            def open_browser():
                time.sleep(1.3);webbrowser.open(f"http://127.0.0.1:{args.port}")
            threading.Thread(target=open_browser,daemon=True).start()
        # Short fixture leases make the disclosed recovery scenario observable.
        db=args.db or ("data/searchmesh-live.sqlite3" if args.mode=="live" else "data/searchmesh.sqlite3")
        app=create_app(db,provider,token,lease_seconds=2 if args.mode=="fixture" else 30)
        uvicorn.run(app,host="127.0.0.1",port=args.port,access_log=False)
    elif args.command=="demo":
        import httpx
        token=os.getenv("SEARCHMESH_GATEWAY_TOKEN","")
        if args.mode=="live":
            from .adk_demo import run_live
            import asyncio
            asyncio.run(run_live(args.gateway,token))
        else:
            if not token: parser.error("Set SEARCHMESH_GATEWAY_TOKEN to the token printed by the server")
            headers={"Authorization":"Bearer "+token}
            result=httpx.post(args.gateway+"/v1/demo",headers=headers,json={"kind":args.scenario},timeout=10)
            result.raise_for_status();run=result.json()["run_id"]
            while True:
                r=httpx.get(args.gateway+f"/v1/runs/{run}/report",headers=headers,timeout=10);r.raise_for_status();body=r.json()
                if body["run"]["status"]!="ACTIVE": break
                time.sleep(.2)
            print(json.dumps(body,indent=2))
    elif args.command=="benchmark":
        from .benchmarks import benchmark,export
        if not 1<=args.iterations<=100: parser.error("Iterations must be between 1 and 100")
        result=benchmark(args.iterations);export(result,args.output)
        print(json.dumps(result,indent=2))
    elif args.command=="prune":
        from .store import Store
        if args.days<1: parser.error("Retention must be at least one day")
        store=Store(args.db);cutoff=time.time()-args.days*86400
        removed=0
        with store.transaction() as c:
            # Preserve all runs participating in shared jobs or referenced evidence.
            rows=c.execute("SELECT r.id FROM runs r WHERE r.created_at<? AND r.status IN ('COMPLETED','FAILED') AND NOT EXISTS(SELECT 1 FROM findings f WHERE f.run_id=r.id) AND NOT EXISTS(SELECT 1 FROM requests q WHERE q.run_id=r.id AND q.status='PENDING') AND NOT EXISTS(SELECT 1 FROM searches s JOIN requests q ON q.search_id=s.id WHERE s.run_id=r.id AND q.run_id<>r.id)",(cutoff,)).fetchall()
            for row in rows:
                run=row[0]
                c.execute("DELETE FROM events WHERE run_id=?",(run,))
                c.execute("DELETE FROM requests WHERE run_id=?",(run,))
                c.execute("DELETE FROM active_keys WHERE search_id IN (SELECT id FROM searches WHERE run_id=?)",(run,))
                c.execute("DELETE FROM attempts WHERE run_id=?",(run,))
                c.execute("DELETE FROM searches WHERE run_id=?",(run,))
                c.execute("DELETE FROM runs WHERE id=?",(run,));removed+=1
            c.execute("DELETE FROM responses WHERE received_at<? AND id NOT IN(SELECT response_id FROM dependencies) AND id NOT IN(SELECT response_id FROM requests WHERE response_id IS NOT NULL) AND id NOT IN(SELECT response_id FROM searches WHERE response_id IS NOT NULL)",(cutoff,))
        print(f"Pruned {removed} terminal runs. Referenced evidence was preserved.")


if __name__=="__main__": main()
