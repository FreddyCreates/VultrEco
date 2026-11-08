"""Live multi-VM containment and saturation acceptance.

Requires two or more independently configured worker VM endpoints, TLS and
per-host bearer tokens. NEVER a local test fixture. Receipt remains honest:
it proves endpoint behavior and declared node identities, not hypervisor
attestation or cloud physical separation.
"""
from __future__ import annotations
import concurrent.futures
import hashlib
import json
import os
import re
import statistics
import time
from urllib.parse import urlsplit

import httpx
from capsula.evidence.proof import canon

PROBE = """import json,os,socket
uid=os.geteuid()
secrets_seen=any(k in os.environ for k in ('CAPSULA_API_KEY','VULTR_API_KEY','CAPSULA_WORKER_TOKEN','OPENAI_API_KEY','CAPSULA_MODEL_API_KEY'))
try:
 with open('/capsula-probe-should-not-write','w') as f:f.write('unsafe')
 read_only=False
except OSError:read_only=True
try:
 socket.create_connection(('1.1.1.1',53),timeout=1).close()
 network_denied=False
except OSError:network_denied=True
caps={}
for name in ('memory.max','cpu.max','pids.max'):
 try:
  with open('/sys/fs/cgroup/'+name) as f:caps[name]=f.read().strip()
 except OSError:caps[name]='unavailable'
print(json.dumps({'uid':uid,'read_only_root':read_only,'network_denied':network_denied,'secrets_seen':secrets_seen,'cgroups':caps}))
"""

def targets_from_env(env=None):
    env=env or os.environ
    try:items=json.loads(env.get("CAPSULA_LIVE_VM_TARGETS",""))
    except (ValueError,TypeError) as exc:raise ValueError("Provide a JSON list of distinct VM worker endpoints") from exc
    if not isinstance(items,list) or not 2<=len(items)<=16:
        raise ValueError("Require 2-16 independent VM worker endpoints")
    origins=set();identities=set()
    for entry in items:
        if not isinstance(entry,dict) or set(entry)!={"id","origin","token_env"}:
            raise ValueError("Each target requires id, origin and token_env only")
        parsed=urlsplit(entry["origin"])
        if parsed.scheme!="https" or not parsed.hostname or parsed.path not in ("","/") or parsed.port not in (None,443) or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError("Live worker origin must use HTTPS and a direct host")
        if not re.fullmatch(r"[A-Za-z0-9_-]{3,64}",entry["id"]):
            raise ValueError("Invalid host identity")
        if entry["origin"] in origins or entry["id"] in identities:
            raise ValueError("VM identities and endpoints must be distinct")
        if not re.fullmatch(r"CAPSULA_LIVE_TOKEN_[A-Z0-9_]{1,32}",entry["token_env"]):
            raise ValueError("Credential must come from an explicitly named environment variable")
        if not env.get(entry["token_env"]):
            raise ValueError("Missing private bearer token for VM worker")
        origins.add(entry["origin"]);identities.add(entry["id"])
    return items

def percentile(values,p):
    if not values:return None
    data=sorted(values)
    return round(data[min(len(data)-1,int((len(data)-1)*p/100))]*1000,3)

def run_live(*,tasks_per_host=3,max_per_host=1):
    if os.getenv("CAPSULA_LIVE_VM_TEST_APPROVED")!="1":
        raise RuntimeError("Real VM load testing needs explicit operator activation")
    if type(tasks_per_host) is not int or not 1<=tasks_per_host<=20 or max_per_host!=1:
        raise ValueError("Conservative per-VM rate cap required")
    targets=targets_from_env()
    started=time.perf_counter()
    evidence=[]
    health=[]
    def test_target(item):
        with httpx.Client(timeout=100,follow_redirects=False,trust_env=False) as client:
            h=client.get(item["origin"].rstrip("/")+"/health",timeout=8)
            h.raise_for_status()
            detail=h.json()
            if detail.get("role")!="isolated-worker" or detail.get("python_mode")!="per-job-docker-or-deny":
                raise RuntimeError("Dedicated worker is missing enforced per-job Docker isolation")
            if detail.get("node_id")!=item["id"]:
                raise RuntimeError("Operator-declared worker node does not match")
            runs=[]
            for index in range(tasks_per_host):
                t=time.perf_counter()
                response=client.post(item["origin"].rstrip("/")+"/execute",
                    headers={"Authorization":"Bearer "+os.environ[item["token_env"]]},
                    json={"kind":"python","code":PROBE},timeout=90)
                response.raise_for_status()
                body=response.json();result=body.get("result") or {}
                expected="sha256:"+hashlib.sha256(canon(result)).hexdigest()
                if body.get("digest")!=expected or result.get("status")!="completed":
                    raise RuntimeError("Worker result or digest failed")
                try:probe=json.loads(result.get("stdout","").strip())
                except ValueError as exc:raise RuntimeError("Worker did not return a JSON probe") from exc
                limits=probe.get("cgroups") or {}
                ok=(probe.get("uid")==65534 and probe.get("read_only_root") is True
                  and probe.get("network_denied") is True and probe.get("secrets_seen") is False
                  and limits.get("memory.max") not in ("unavailable","max",None)
                  and limits.get("pids.max") not in ("unavailable","max",None))
                runs.append({"job":index,"seconds":round(time.perf_counter()-t,3),
                    "containment_probe_passed":ok,"cgroup_limits":limits})
            return {"id":item["id"],"origin":item["origin"],"health":"available","runs":runs}
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures=[pool.submit(test_target,item) for item in targets]
        for future in concurrent.futures.as_completed(futures):
            try:evidence.append(future.result())
            except Exception as exc:
                evidence.append({"health":"failed","error_type":type(exc).__name__})
    durations=[r["seconds"] for w in evidence for r in w.get("runs",[])]
    success=(len(evidence)==len(targets) and len(durations)==tasks_per_host*len(targets)
         and all(w.get("health")=="available" and all(r.get("containment_probe_passed") for r in w.get("runs",[])) for w in evidence))
    return {"label":"REAL_REMOTE_VM_ENDPOINT_LOAD_NOT_HARDWARE_ATTESTATION",
      "hosts":len(targets),"tasks_expected":tasks_per_host*len(targets),
      "tasks_completed":len(durations),"all_probe_checks_passed":success,
      "duration_seconds":round(time.perf_counter()-started,3),
      "task_latency_p50_ms":percentile(durations,50),
      "task_latency_p95_ms":percentile(durations,95),
      "per_host":evidence,"vm_physical_independence_cryptographically_attested":False,
      "status":"PASS" if success else "FAIL"}

if __name__=="__main__":
    receipt=run_live()
    print(json.dumps(receipt,indent=2,sort_keys=True))
    if os.getenv("CAPSULA_VM_RECEIPT_PATH"):
        from pathlib import Path
        Path(os.environ["CAPSULA_VM_RECEIPT_PATH"]).write_text(json.dumps(receipt,indent=2)+"\n")
    raise SystemExit(0 if receipt["status"]=="PASS" else 1)
