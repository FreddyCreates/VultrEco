"""Dedicated, provider-neutral CAPSULA cluster runner.

Runs on a separate worker VM. It claims work from PostgreSQL and invokes the
existing per-job Docker executor on that VM. It never imports/evals task code.
"""
import json
import os
import signal
import time
from urllib.parse import urlsplit

import httpx
from capsula.execution.cluster_queue import Queue,digest

STOP=False

def _stop(*args):
    global STOP
    STOP=True

def config():
    wid=os.getenv("CAPSULA_CLUSTER_WORKER_ID","")
    worker_secret=os.getenv("CAPSULA_CLUSTER_WORKER_TOKEN","")
    executor_secret=os.getenv("CAPSULA_EXECUTOR_TOKEN","")
    endpoint=os.getenv("CAPSULA_EXECUTOR_URL","http://127.0.0.1:8081").rstrip("/")
    parsed=urlsplit(endpoint)
    good=(parsed.scheme=="https" or
          parsed.scheme=="http" and parsed.hostname in ("127.0.0.1","localhost","::1"))
    good=good and not (parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment)
    if not (wid and worker_secret and executor_secret and good):
        raise RuntimeError("Worker credential or pinned isolated executor missing")
    return wid,worker_secret,executor_secret,endpoint

def execute(client,endpoint,token,job):
    if job["kind"]!="python" or not isinstance(job["payload"],dict):
        raise ValueError("Worker has no approved executor for this capability")
    code=job["payload"].get("code")
    if not isinstance(code,str) or not code or len(code)>16000:
        raise ValueError("Invalid bounded Python payload")
    health=client.get(endpoint+"/health",timeout=5)
    health.raise_for_status()
    if health.json().get("python_mode")!="per-job-docker-or-deny":
        raise RuntimeError("Unsafe or unavailable worker execution mode")
    inputs=job["payload"].get("inputs")
    if inputs is not None:
        if not isinstance(inputs,dict) or len(inputs)>12:
            raise ValueError("Invalid bounded file input envelope")
        route="/capsules/execute"
        task={"code":code,"inputs":inputs}
    else:
        route="/execute"
        task={"kind":"python","code":code}
    reply=client.post(endpoint+route,
        headers={"Authorization":"Bearer "+token},
        json=task,timeout=90)
    reply.raise_for_status()
    data=reply.json()
    result=data.get("result")
    if not isinstance(result,dict) or data.get("digest")!="sha256:"+digest(result):
        raise RuntimeError("Worker result digest rejected")
    if result.get("status") not in ("completed","failed","denied"):
        raise RuntimeError("Worker returned unrecognized execution state")
    return result

def tick(queue=None,client=None):
    q=queue or Queue()
    wid,worker_token,executor_token,endpoint=config()
    q.heartbeat(wid,worker_token)
    claim=q.claim(wid,worker_token,lease_seconds=180)
    if claim is None:return {"state":"idle"}
    # Worker executable is allowed to run at most 90 seconds. The lease is
    # longer than the network timeout; late results will still be DB-fenced.
    try:
        if client is None:
            with httpx.Client(follow_redirects=False,trust_env=False) as http:
                result=execute(http,endpoint,executor_token,claim)
        else:result=execute(client,endpoint,executor_token,claim)
        accepted=q.finish(wid,worker_token,claim["id"],claim["epoch"],claim["fence_token"],
                          result,success=result["status"]=="completed")
        return {"job_id":claim["id"],"accepted":accepted,"status":result["status"]}
    except (httpx.HTTPError,ValueError,RuntimeError) as exc:
        # Do not put raw exception text/remote secrets into the tenant result.
        accepted=q.finish(wid,worker_token,claim["id"],claim["epoch"],claim["fence_token"],
                          {"status":"failed","reason":"isolated worker transport or proof failure"},success=False)
        return {"job_id":claim["id"],"accepted":accepted,"status":"failed"}

def main():
    signal.signal(signal.SIGTERM,_stop)
    signal.signal(signal.SIGINT,_stop)
    while not STOP:
        outcome=tick()
        print(json.dumps(outcome),flush=True)
        if outcome.get("state")=="idle":
            time.sleep(2)

if __name__=="__main__":
    main()
