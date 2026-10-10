import json
import threading
import time
import uuid
from .provider import ProviderError


class WorkerPool:
    def __init__(self,coordinator,provider,size=4):
        self.coordinator,self.provider,self.size=coordinator,provider,size
        self.stop=threading.Event()
        self.threads=[]
        self._crash_next=threading.Event()
        self.dispatch_lock=threading.RLock()
        self._crash_runs=set()

    def start(self):
        for i in range(self.size):
            t=threading.Thread(target=self.loop,name=f"mesh-worker-{i}",daemon=True)
            t.start(); self.threads.append(t)

    def close(self):
        self.stop.set()
        for t in self.threads: t.join(timeout=2)

    def crash_next(self,run_id=None):
        with self.dispatch_lock:
            if run_id:self._crash_runs.add(run_id)
            else:self._crash_next.set()

    def loop(self):
        owner=uuid.uuid4().hex
        while not self.stop.is_set():
            try:
                with self.dispatch_lock:
                    job=self.coordinator.claim(owner)
                    crash=bool(job and (self._crash_next.is_set() or job['run_id'] in self._crash_runs))
                    if crash:
                        self._crash_next.clear()
                        self._crash_runs.discard(job['run_id'])
            except Exception:
                # Store failure is visible through readiness. Do not bypass coordination.
                self.stop.wait(.1); continue
            if not job:
                self.stop.wait(.025); continue
            if crash:
                # Fixture injection after dispatch: provider did work, but its result is
                # abandoned. No heartbeat or completion. Recovery may repeat that work.
                try:self.provider.search(json.loads(job["params_json"]),bool(job["refresh"]))
                except ProviderError:pass
                continue
            done=threading.Event()
            def heartbeat():
                while not done.wait(max(.03,self.coordinator.lease_seconds/4)):
                    try:
                        if not self.coordinator.heartbeat(job): return
                    except Exception: return
            heart=threading.Thread(target=heartbeat,daemon=True); heart.start()
            try:
                raw=self.provider.search(json.loads(job["params_json"]),bool(job["refresh"]))
                self.coordinator.complete(job,raw)
            except ProviderError as error:
                self.coordinator.fail_attempt(job,error)
            except Exception:
                self.coordinator.fail_attempt(job,ProviderError("PROVIDER_ERROR","Unexpected provider failure",False))
            finally:
                done.set(); heart.join(timeout=.2)
