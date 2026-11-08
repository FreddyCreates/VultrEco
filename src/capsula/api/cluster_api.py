"""Separate authenticated enterprise plane for jobs, workers, and fleet governance.

Legacy APIs use a single-admin key and are *not* multi-tenant. In enterprise
mode the legacy privileged APIs are disabled by app.authed().
"""
from fastapi import APIRouter,Header,HTTPException
from fastapi.responses import Response
import base64,hashlib
from pydantic import BaseModel,Field
from typing import Literal
from capsula.security import cluster_auth
from capsula.execution import cluster_queue
import os

router=APIRouter(prefix="/api/v1/cluster",tags=["CAPSULA cluster"])
queue=None

def get_queue():
    global queue
    if queue is None:
        if not os.getenv("CAPSULA_CLUSTER_DATABASE_URL"):
            raise HTTPException(503,"Cluster database is not configured")
        queue=cluster_queue.Queue()
        # migration is explicit: run scripts/migrate_cluster.py
    return queue

def principal(header):
    try:return cluster_auth.authenticate(header)
    except (PermissionError,RuntimeError) as e:
        raise HTTPException(401,"OIDC authentication required or invalid") from e

def gated(header,tenant,minimum):
    p=principal(header)
    try:cluster_auth.authorize(p,tenant,minimum)
    except PermissionError as e:raise HTTPException(403,"Tenant scope or role denied") from e
    return p

class WorkRequest(BaseModel):
    kind:Literal["python","browser","agent","research","compute"]
    payload:dict
    idempotency_key:str=Field(min_length=8,max_length=100)
    priority:int=Field(default=0,ge=-100,le=100)
    max_attempts:int=Field(default=3,ge=1,le=10)

class Enrollment(BaseModel):
    host_id:str=Field(min_length=1,max_length=120)
    provider:str=Field(default="self-hosted",max_length=60)
    region:str=Field(default="private",max_length=60)
    kinds:list[Literal["python","browser","agent","research","compute"]]=Field(min_length=1,max_length=5)
    capacity:int=Field(default=1,ge=1,le=128)

class WorkerAuth(BaseModel):
    worker_id:str
    worker_token:str

class Claim(WorkerAuth):
    lease_seconds:int=Field(default=45,ge=10,le=300)

class Lease(WorkerAuth):
    job_id:str
    epoch:int=Field(ge=1)
    fence_token:str
    lease_seconds:int=Field(default=45,ge=10,le=300)

class Result(Lease):
    result:dict
    success:bool=True

@router.post("/{tenant}/jobs",status_code=201)
def submit(tenant:str,body:WorkRequest,authorization:str|None=Header(None)):
    gated(authorization,tenant,"operator")
    try:return get_queue().submit(tenant,body.kind,body.payload,body.idempotency_key,
                                  body.priority,body.max_attempts)
    except ValueError as e:raise HTTPException(422,str(e)) from e

@router.get("/{tenant}/jobs/{job_id}")
def job(tenant:str,job_id:str,authorization:str|None=Header(None)):
    gated(authorization,tenant,"viewer")
    value=get_queue().job(tenant,job_id)
    if value is None:raise HTTPException(404,"Task not found in tenant")
    return value

@router.get("/{tenant}/jobs/{job_id}/outputs/{filename:path}")
def output(tenant:str,job_id:str,filename:str,authorization:str|None=Header(None)):
    gated(authorization,tenant,"viewer")
    from capsula.execution.capsule_runtime import safe_name
    if not safe_name(filename):raise HTTPException(404,"Output unavailable")
    job=get_queue().job(tenant,job_id)
    if not job or job["state"]!="completed":raise HTTPException(404,"Output unavailable")
    stored=job.get("result") or {}
    item=(stored.get("artifacts") or {}).get(filename)
    if not isinstance(item,dict):raise HTTPException(404,"Output unavailable")
    try:data=base64.b64decode(item["base64"],validate=True)
    except (ValueError,KeyError) as exc:raise HTTPException(409,"Output encoding invalid") from exc
    if len(data)>256000 or hashlib.sha256(data).hexdigest()!=item.get("sha256") or item.get("bytes")!=len(data):
        raise HTTPException(409,"Output integrity mismatch")
    return Response(content=data,media_type="application/octet-stream",
                    headers={"Content-Disposition":'attachment; filename="'+filename.split("/")[-1]+'"',
                             "Cache-Control":"private, no-store",
                             "X-Content-Type-Options":"nosniff",
                             "X-Capsula-SHA256":item["sha256"]})

@router.get("/{tenant}/status")
def status(tenant:str,authorization:str|None=Header(None)):
    gated(authorization,tenant,"viewer")
    return get_queue().summary(tenant)

@router.post("/{tenant}/workers",status_code=201)
def enroll(tenant:str,body:Enrollment,authorization:str|None=Header(None)):
    gated(authorization,tenant,"admin")
    try:return get_queue().enroll(tenant,body.host_id,body.kinds,body.capacity,body.provider,body.region)
    except ValueError as e:raise HTTPException(422,str(e)) from e

@router.post("/{tenant}/workers/{worker_id}/drain")
def drain(tenant:str,worker_id:str,authorization:str|None=Header(None)):
    gated(authorization,tenant,"admin")
    try:return get_queue().drain(tenant,worker_id)
    except KeyError as e:raise HTTPException(404,"Unknown worker") from e

@router.post("/{tenant}/reconcile")
def reconcile(tenant:str,authorization:str|None=Header(None)):
    gated(authorization,tenant,"admin")
    return {"expired":get_queue().recover_expired(tenant),"remote_termination_verified":False}

@router.post("/workers/heartbeat")
def heartbeat(body:WorkerAuth):
    try:return get_queue().heartbeat(body.worker_id,body.worker_token)
    except PermissionError as e:raise HTTPException(401,"Worker credential invalid") from e

@router.post("/workers/claim")
def claim(body:Claim):
    try:return get_queue().claim(body.worker_id,body.worker_token,body.lease_seconds)
    except PermissionError as e:raise HTTPException(401,"Worker credential invalid") from e

@router.post("/workers/renew")
def renew(body:Lease):
    try:ok=get_queue().renew(body.worker_id,body.worker_token,body.job_id,body.epoch,
                             body.fence_token,body.lease_seconds)
    except PermissionError as e:raise HTTPException(401,"Worker credential invalid") from e
    if not ok:raise HTTPException(409,"Stale or revoked fencing epoch")
    return {"renewed":True}

@router.post("/workers/finish")
def finish(body:Result):
    try:ok=get_queue().finish(body.worker_id,body.worker_token,body.job_id,body.epoch,
                              body.fence_token,body.result,body.success)
    except PermissionError as e:raise HTTPException(401,"Worker credential invalid") from e
    if not ok:raise HTTPException(409,"Stale result rejected")
    return {"accepted":True}

def bind(app):
    app.include_router(router)
