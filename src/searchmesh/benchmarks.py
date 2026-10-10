import csv
import json
import platform
import statistics
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from .store import Store
from .coordinator import Coordinator
from .provider import FixtureProvider
from .worker import WorkerPool
from .scenarios import request,wait
from .fingerprints import canonical


def percentile(values,p):
    ordered=sorted(values)
    return ordered[max(0,min(len(ordered)-1,int((len(ordered)-1)*p)))]


def benchmark(iterations=30):
    samples={k:[] for k in ("Direct calls","Shared TTL cache","SearchMesh")}
    for iteration in range(iterations):
        q=f"fixture-benchmark-{iteration}"
        for name in samples:
            provider=FixtureProvider(delay=.025)
            latencies=[]
            started=time.perf_counter()
            if name=="SearchMesh":
                with tempfile.TemporaryDirectory() as directory:
                    co=Coordinator(Store(Path(directory)/"mesh.sqlite"))
                    run=co.create_run("demo","Benchmark",20)
                    pool=WorkerPool(co,provider);pool.start()
                    try:
                        def call(query):
                            start=time.perf_counter()
                            state=wait(co,request(co,run["id"],"benchmark",query))
                            if state["status"]!="SUCCEEDED": raise RuntimeError("Benchmark failure")
                            return time.perf_counter()-start
                        with ThreadPoolExecutor(max_workers=3) as executor:
                            latencies.extend(executor.map(call,[q]*3))
                        latencies.extend([call(q),call(q),call(q+" free-threaded")])
                    finally: pool.close()
            else:
                cache={};lock=threading.Lock(); barrier=threading.Barrier(3)
                def call(query,synchronize=False):
                    start=time.perf_counter()
                    params={"engine":"google_light","q":query}
                    key=canonical(params)
                    with lock: result=cache.get(key) if name=="Shared TTL cache" else None
                    if synchronize: barrier.wait(timeout=5)
                    if result is None:
                        result=provider.search(params)
                        if name=="Shared TTL cache":
                            with lock: cache[key]=result
                    return time.perf_counter()-start
                with ThreadPoolExecutor(max_workers=3) as executor:
                    latencies.extend(executor.map(lambda _:call(q,True),range(3)))
                latencies.extend([call(q),call(q),call(q+" free-threaded")])
            samples[name].append({"provider_calls":provider.calls,"wall_seconds":time.perf_counter()-started,"latencies":latencies})
    rows=[]
    for name,runs in samples.items():
        latencies=[v for r in runs for v in r["latencies"]]
        rows.append({"baseline":name,"iterations":iterations,"requests_per_iteration":6,"mean_provider_calls":statistics.mean(r["provider_calls"] for r in runs),"p50_ms":round(percentile(latencies,.5)*1000,2),"p95_ms":round(percentile(latencies,.95)*1000,2),"mean_wall_ms":round(statistics.mean(r["wall_seconds"] for r in runs)*1000,2)})
    return {"mode":"fixture","measured":True,"created_at":time.time(),"machine":platform.platform(),"python":platform.python_version(),"trace":"3 simultaneous identical requests, 2 sequential repeats, 1 qualified request","methodology":"Synthetic provider with 25 ms latency. Same six-request trace per baseline; independent cold stores per iteration. TTL cache has no in-flight sharing. Direct calls are synthetic and do not simulate SerpApi billing/cache latency. Wall time includes runtime startup/cleanup; per-request latency reported separately. No credit savings claimed.","baselines":rows,"iterations":iterations}


def export(report,directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    (directory/"benchmark.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
    with (directory/"benchmark.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=list(report["baselines"][0]))
        writer.writeheader();writer.writerows(report["baselines"])

