"""Measured PostgreSQL queue benchmark, NOT a multi-VM containment test.

Runs many independent DB clients/threads, records claim/recovery metrics.
Requires an actual PostgreSQL service and names the environment honestly.
"""
import concurrent.futures
import json
import os
import statistics
import time
import uuid
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cluster_queue import Queue

def pct(values,p):
    if not values:return 0.0
    ordered=sorted(values)
    return round(ordered[min(len(ordered)-1,int((len(ordered)-1)*p/100))]*1000,3)

def benchmark(n=100,workers=8):
    if not 1<=n<=2000 or not 1<=workers<=64:raise ValueError("Bounded benchmark arguments required")
    q=Queue();q.migrate()
    tenant="bench-"+uuid.uuid4().hex[:12]
    nodes=[q.enroll(tenant,"benchmark-host-"+str(i),["python"],capacity=1)
           for i in range(workers)]
    started=time.perf_counter()
    for i in range(n):
        q.submit(tenant,"python",{"case":i},f"measure-{i:08d}")
    dispatch=time.perf_counter()
    latencies=[]
    finished=[]
    def run(node):
        wid=node["worker_id"];token=node["worker_token"]
        while True:
            at=time.perf_counter()
            job=q.claim(wid,token,45)
            latency=time.perf_counter()-at
            if not job:return
            accepted=q.finish(wid,token,job["id"],job["epoch"],job["fence_token"],
                              {"status":"completed","case":job["payload"]["case"]})
            if not accepted:raise RuntimeError("Unexpected stale claim during benchmark")
            latencies.append(latency)
            finished.append(job["id"])
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(run,nodes))
    ended=time.perf_counter()
    if len(set(finished))!=n:raise RuntimeError("Benchmark did not complete all jobs exactly once")
    return {"label":"POSTGRESQL_QUEUE_ONLY_NOT_REAL_VM_LOAD",
        "cases":n,"simulated_worker_clients":workers,"completed":len(finished),
        "submit_seconds":round(dispatch-started,3),
        "total_seconds":round(ended-started,3),
        "throughput_jobs_per_second":round(n/max(.000001,ended-started),2),
        "claim_latency_p50_ms":pct(latencies,50),
        "claim_latency_p95_ms":pct(latencies,95),
        "duplicates":len(finished)-len(set(finished)),
        "real_vm_isolation_verified":False,"cloud_provider":"none"}

if __name__=="__main__":
    value=benchmark(int(os.getenv("CAPSULA_BENCH_JOBS","100")),
                    int(os.getenv("CAPSULA_BENCH_WORKERS","8")))
    print(json.dumps(value,indent=2))
    out=os.getenv("CAPSULA_BENCH_RECEIPT")
    if out:
        from pathlib import Path
        Path(out).write_text(json.dumps(value,indent=2)+"\n")
