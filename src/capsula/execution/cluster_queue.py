"""CAPSULA distributed admission queue, PostgreSQL source of truth.

All transitions are DB transactions. Each claim rotates an unguessable fence
token and increments an epoch; expired leases cannot publish results. This is
database fencing, NOT a guarantee a remote process has stopped running.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
import re
import secrets
import uuid

import psycopg
from psycopg.rows import dict_row

TENANT = re.compile(r"^[a-z][a-z0-9-]{2,62}$")
KINDS = frozenset({"python", "browser", "agent", "research", "compute"})
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS cluster_workers(
      id text PRIMARY KEY, tenant_id text NOT NULL, host_id text NOT NULL,
      provider text NOT NULL, region text NOT NULL, kinds text[] NOT NULL,
      capacity smallint NOT NULL CHECK(capacity BETWEEN 1 AND 128),
      credential_digest text NOT NULL, heartbeat timestamptz NOT NULL DEFAULT now(),
      draining boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE INDEX IF NOT EXISTS idx_cluster_workers_tenant
       ON cluster_workers(tenant_id,heartbeat)""",
    """CREATE TABLE IF NOT EXISTS cluster_jobs(
      id text PRIMARY KEY, tenant_id text NOT NULL, idempotency_key text NOT NULL,
      body_digest text NOT NULL, kind text NOT NULL, payload jsonb NOT NULL,
      state text NOT NULL DEFAULT 'queued'
        CHECK(state IN ('queued','leased','completed','dead','cancelled')),
      priority int NOT NULL DEFAULT 0, attempts int NOT NULL DEFAULT 0,
      max_attempts int NOT NULL DEFAULT 3 CHECK(max_attempts BETWEEN 1 AND 10),
      eligible_at timestamptz NOT NULL DEFAULT now(),
      worker_id text, epoch bigint NOT NULL DEFAULT 0,
      fence_digest text, lease_until timestamptz,
      result jsonb, created_at timestamptz NOT NULL DEFAULT now(),
      updated_at timestamptz NOT NULL DEFAULT now(),
      UNIQUE(tenant_id,idempotency_key))""",
    """CREATE INDEX IF NOT EXISTS idx_cluster_queue_ready ON cluster_jobs
       (tenant_id,priority DESC,eligible_at,created_at)
       WHERE state='queued'""",
    """CREATE INDEX IF NOT EXISTS idx_cluster_queue_leases ON cluster_jobs
       (tenant_id,lease_until) WHERE state='leased'""",
    """CREATE TABLE IF NOT EXISTS cluster_events(
      id bigserial PRIMARY KEY,tenant_id text NOT NULL,job_id text NOT NULL,
      event text NOT NULL,epoch bigint NOT NULL,
      detail jsonb NOT NULL,created_at timestamptz NOT NULL DEFAULT now())""",
    """CREATE INDEX IF NOT EXISTS idx_cluster_events_job ON cluster_events(tenant_id,job_id,id)""",
]

def digest(value):
    if not isinstance(value,str):
        value=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def valid_tenant(value):
    if not isinstance(value,str) or not TENANT.fullmatch(value):
        raise ValueError("Invalid tenant scope")
    return value

class Queue:
    def __init__(self,dsn=None):
        self.dsn=dsn or os.getenv("CAPSULA_CLUSTER_DATABASE_URL","")
        if not self.dsn:
            raise RuntimeError("PostgreSQL is required for cluster operations; no SQLite fallback")

    @contextmanager
    def tx(self):
        with psycopg.connect(self.dsn,connect_timeout=5,row_factory=dict_row) as conn:
            with conn.transaction():
                yield conn

    def migrate(self):
        with self.tx() as conn:
            for statement in SCHEMA: conn.execute(statement)

    def enroll(self,tenant,host_id,kinds,capacity=1,provider="self-hosted",region="private"):
        tenant=valid_tenant(tenant)
        if not host_id or len(host_id)>120 or not isinstance(kinds,list) or not kinds or not set(kinds)<=KINDS:
            raise ValueError("Invalid host or worker capabilities")
        if type(capacity) is not int or not 1<=capacity<=128:
            raise ValueError("Worker capacity must be between 1 and 128")
        if any(not isinstance(x,str) or not 1<=len(x)<=60 for x in (provider,region)):
            raise ValueError("Invalid provider/region")
        worker_id="wrk_"+uuid.uuid4().hex
        token=secrets.token_urlsafe(40)
        with self.tx() as conn:
            conn.execute("""INSERT INTO cluster_workers
              (id,tenant_id,host_id,provider,region,kinds,capacity,credential_digest)
              VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
              (worker_id,tenant,host_id,provider,region,sorted(set(kinds)),capacity,digest(token)))
        return {"worker_id":worker_id,"worker_token":token,"tenant_id":tenant}

    @staticmethod
    def _worker(conn,worker_id,token,lock=True):
        suffix=" FOR UPDATE" if lock else ""
        worker=conn.execute("SELECT * FROM cluster_workers WHERE id=%s"+suffix,(worker_id,)).fetchone()
        if not worker or not token or not secrets.compare_digest(worker["credential_digest"],digest(token)):
            raise PermissionError("Unknown worker or invalid worker credential")
        return worker

    def heartbeat(self,worker_id,token):
        with self.tx() as conn:
            worker=self._worker(conn,worker_id,token)
            conn.execute("UPDATE cluster_workers SET heartbeat=now() WHERE id=%s",(worker_id,))
            return {"tenant_id":worker["tenant_id"],"draining":worker["draining"]}

    def drain(self,tenant,worker_id,draining=True):
        tenant=valid_tenant(tenant)
        with self.tx() as conn:
            row=conn.execute("UPDATE cluster_workers SET draining=%s WHERE tenant_id=%s AND id=%s RETURNING id",
                             (bool(draining),tenant,worker_id)).fetchone()
            if not row: raise KeyError("Unknown worker in tenant")
            return {"worker_id":worker_id,"draining":bool(draining)}

    def submit(self,tenant,kind,payload,key,priority=0,max_attempts=3):
        tenant=valid_tenant(tenant)
        if kind not in KINDS or not isinstance(payload,dict):
            raise ValueError("Unrecognized task kind/payload")
        if not isinstance(key,str) or not 8<=len(key)<=100 or not re.fullmatch(r"[a-zA-Z0-9_-]+",key):
            raise ValueError("Invalid idempotency key")
        if type(priority) is not int or abs(priority)>100 or type(max_attempts) is not int or not 1<=max_attempts<=10:
            raise ValueError("Invalid task priority/retry budget")
        canonical=json.dumps({"kind":kind,"payload":payload},sort_keys=True,separators=(",",":"))
        if len(canonical)>131072:raise ValueError("Task exceeds 128 KiB envelope")
        fingerprint=digest(canonical);job_id="job_"+uuid.uuid4().hex
        with self.tx() as conn:
            # Per-tenant admission is serialized across multiple API replicas.
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",(tenant,))
            pending=conn.execute("SELECT count(*) n FROM cluster_jobs WHERE tenant_id=%s AND state IN ('queued','leased')",(tenant,)).fetchone()["n"]
            quota=int(os.getenv("CAPSULA_TENANT_MAX_PENDING","10000"))
            previous=conn.execute("SELECT id FROM cluster_jobs WHERE tenant_id=%s AND idempotency_key=%s",(tenant,key)).fetchone()
            if pending>=quota and not previous:
                raise ValueError("Tenant pending-job quota reached")
            row=conn.execute("""INSERT INTO cluster_jobs
              (id,tenant_id,idempotency_key,body_digest,kind,payload,priority,max_attempts)
              VALUES(%s,%s,%s,%s,%s,%s::jsonb,%s,%s)
              ON CONFLICT(tenant_id,idempotency_key) DO NOTHING RETURNING id""",
              (job_id,tenant,key,fingerprint,kind,json.dumps(payload),priority,max_attempts)).fetchone()
            if row:
                conn.execute("INSERT INTO cluster_events(tenant_id,job_id,event,epoch,detail) VALUES(%s,%s,'submitted',0,%s::jsonb)",
                             (tenant,job_id,'{}'))
                return {"id":job_id,"existing":False}
            old=conn.execute("SELECT id,body_digest FROM cluster_jobs WHERE tenant_id=%s AND idempotency_key=%s",
                             (tenant,key)).fetchone()
            if old["body_digest"]!=fingerprint:
                raise ValueError("Idempotency key reused with different task")
            return {"id":old["id"],"existing":True}

    def recover_expired(self,tenant):
        tenant=valid_tenant(tenant)
        with self.tx() as conn:
            rows=conn.execute("""UPDATE cluster_jobs SET
              state=CASE WHEN attempts>=max_attempts THEN 'dead' ELSE 'queued' END,
              fence_digest=NULL,lease_until=NULL,worker_id=NULL,
              eligible_at=now(), updated_at=now()
              WHERE tenant_id=%s AND state='leased' AND lease_until<=now()
              RETURNING id,epoch,state""",(tenant,)).fetchall()
            for row in rows:
                conn.execute("""INSERT INTO cluster_events(tenant_id,job_id,event,epoch,detail)
                  VALUES(%s,%s,'lease_expired',%s,%s::jsonb)""",
                  (tenant,row["id"],row["epoch"],json.dumps({"next_state":row["state"],"remote_terminated":False})))
            return len(rows)

    def claim(self,worker_id,token,lease_seconds=45):
        if type(lease_seconds) is not int or not 10<=lease_seconds<=300:
            raise ValueError("Lease seconds must be between 10 and 300")
        with self.tx() as conn:
            worker=self._worker(conn,worker_id,token)
            if worker["draining"] or worker["heartbeat"] < conn.execute("SELECT now()-interval '90 seconds' AS t").fetchone()["t"]:
                return None
            busy=conn.execute("""SELECT count(*) n FROM cluster_jobs
                 WHERE worker_id=%s AND state='leased' AND lease_until>now()""",
                 (worker_id,)).fetchone()["n"]
            if busy>=worker["capacity"]:return None
            row=conn.execute("""SELECT id FROM cluster_jobs
                 WHERE tenant_id=%s AND state='queued' AND eligible_at<=now()
                 AND kind=ANY(%s) ORDER BY priority DESC,created_at,id
                 FOR UPDATE SKIP LOCKED LIMIT 1""",(worker["tenant_id"],worker["kinds"])).fetchone()
            if not row:return None
            fence=secrets.token_urlsafe(32)
            job=conn.execute("""UPDATE cluster_jobs SET
                state='leased',attempts=attempts+1,worker_id=%s,
                epoch=epoch+1,fence_digest=%s,
                lease_until=now() + make_interval(secs => %s),
                updated_at=now()
                WHERE id=%s RETURNING id,tenant_id,kind,payload,epoch,attempts,lease_until""",
                (worker_id,digest(fence),lease_seconds,row["id"])).fetchone()
            conn.execute("""INSERT INTO cluster_events(tenant_id,job_id,event,epoch,detail)
                VALUES(%s,%s,'leased',%s,%s::jsonb)""",
                (worker["tenant_id"],job["id"],job["epoch"],json.dumps({"worker_id":worker_id})))
            return {**job,"fence_token":fence,"lease_until":job["lease_until"].isoformat()}

    def _transition(self,conn,worker_id,token,job_id,epoch,fence,statement,params):
        worker=self._worker(conn,worker_id,token)
        if not fence or type(epoch) is not int or epoch<1:return None
        return conn.execute(statement,(*params,worker["tenant_id"],job_id,worker_id,epoch,digest(fence))).fetchone()

    def renew(self,worker_id,token,job_id,epoch,fence,lease_seconds=45):
        if type(lease_seconds) is not int or not 10<=lease_seconds<=300:raise ValueError("Invalid lease")
        with self.tx() as conn:
            row=self._transition(conn,worker_id,token,job_id,epoch,fence,
                """UPDATE cluster_jobs SET lease_until=now()+make_interval(secs => %s),updated_at=now()
                WHERE tenant_id=%s AND id=%s AND worker_id=%s AND epoch=%s
                AND fence_digest=%s AND state='leased' AND lease_until>now()
                RETURNING id""",(lease_seconds,))
            return bool(row)

    def finish(self,worker_id,token,job_id,epoch,fence,result,success=True):
        if not isinstance(result,dict) or len(json.dumps(result))>131072:
            raise ValueError("Result envelope invalid")
        with self.tx() as conn:
            row=self._transition(conn,worker_id,token,job_id,epoch,fence,
                """UPDATE cluster_jobs SET
                state=CASE WHEN %s THEN 'completed' WHEN attempts>=max_attempts THEN 'dead' ELSE 'queued' END,
                result=%s::jsonb,
                worker_id=NULL,lease_until=NULL,fence_digest=NULL,
                eligible_at=CASE WHEN %s THEN now() ELSE now()+make_interval(secs => LEAST(60,attempts*5)) END,
                updated_at=now()
                WHERE tenant_id=%s AND id=%s AND worker_id=%s AND epoch=%s
                AND fence_digest=%s AND state='leased' AND lease_until>now()
                RETURNING id,tenant_id,epoch,state""",
                (bool(success),json.dumps(result),bool(success)))
            if not row:return False
            conn.execute("""INSERT INTO cluster_events(tenant_id,job_id,event,epoch,detail)
                 VALUES(%s,%s,'result_received',%s,%s::jsonb)""",
                 (row["tenant_id"],job_id,epoch,json.dumps({"state":row["state"],"cryptographic_attestation":False})))
            return True

    def summary(self,tenant):
        tenant=valid_tenant(tenant)
        with self.tx() as conn:
            counts=conn.execute("SELECT state,count(*) n FROM cluster_jobs WHERE tenant_id=%s GROUP BY state",
                                (tenant,)).fetchall()
            workers=conn.execute("""SELECT id,host_id,provider,region,kinds,capacity,draining,heartbeat
                 FROM cluster_workers WHERE tenant_id=%s ORDER BY created_at DESC""",(tenant,)).fetchall()
            return {"tenant":tenant,"jobs":{r["state"]:r["n"] for r in counts},
                    "workers":[{**w,"heartbeat":w["heartbeat"].isoformat()} for w in workers],
                    "store":"PostgreSQL transactional queue","fencing":"epoch+random token, reject late result",
                    "vm_isolation":"requires independent deployment validation"}

    def job(self,tenant,job_id):
        tenant=valid_tenant(tenant)
        with self.tx() as conn:
            return conn.execute("""SELECT id,tenant_id,kind,state,attempts,max_attempts,worker_id,epoch,
                      created_at,updated_at,result FROM cluster_jobs WHERE tenant_id=%s AND id=%s""",
                      (tenant,job_id)).fetchone()
