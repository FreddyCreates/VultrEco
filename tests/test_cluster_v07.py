"""CAPSULA 0.7 queue, identity, provisioning and isolation contracts."""
import datetime as dt
import os
import threading
import time
from types import SimpleNamespace
import pytest

from capsula.security import cluster_auth
from capsula.providers.vultr import fleet_provider
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

@pytest.fixture
def store():
    if not os.getenv("CAPSULA_CLUSTER_DATABASE_URL"):
        pytest.skip("PostgreSQL integration requires dedicated CI service")
    from capsula.execution.cluster_queue import Queue
    q=Queue()
    q.migrate()
    with q.tx() as conn:
        conn.execute("TRUNCATE cluster_events,cluster_jobs,cluster_workers")
    yield q
    with q.tx() as conn:
        conn.execute("TRUNCATE cluster_events,cluster_jobs,cluster_workers")

def worker(q,tenant="acme"):
    d=q.enroll(tenant,"host-1",["python"],capacity=1)
    return d["worker_id"],d["worker_token"]

def test_submit_replay_and_cross_tenant_isolation(store):
    q=store
    a=q.submit("acme","python",{"code":"print(3)"},"repeat-key-123")
    assert a["existing"] is False
    assert q.submit("acme","python",{"code":"print(3)"},"repeat-key-123") == {"id":a["id"],"existing":True}
    with pytest.raises(ValueError):
        q.submit("acme","python",{"code":"print(4)"},"repeat-key-123")
    assert q.job("beta",a["id"]) is None
    assert len(q.summary("beta")["workers"])==0

def test_claim_complete_reject_replay(store):
    q=store
    wid,key=worker(q)
    job=q.submit("acme","python",{"code":"print(42)"},"job-key-one")
    claimed=q.claim(wid,key)
    assert claimed["id"]==job["id"]
    assert claimed["epoch"]==1 and claimed["fence_token"]
    assert q.claim(wid,key) is None
    assert not q.finish(wid,key,job["id"],1,"wrong",{"output":42})
    assert q.renew(wid,key,job["id"],1,claimed["fence_token"])
    assert q.finish(wid,key,job["id"],1,claimed["fence_token"],{"output":42})
    assert not q.finish(wid,key,job["id"],1,claimed["fence_token"],{"output":42})
    assert q.job("acme",job["id"])["state"]=="completed"

def test_expired_lease_is_fenced_after_reassignment(store):
    q=store
    wid,key=worker(q)
    job=q.submit("acme","python",{"task":"run"},"expired-job")
    original=q.claim(wid,key,10)
    with q.tx() as conn:
        conn.execute("UPDATE cluster_jobs SET lease_until=now()-interval '1 second' WHERE id=%s",(job["id"],))
    assert q.recover_expired("acme")==1
    fresh=q.claim(wid,key,10)
    assert fresh["epoch"]==original["epoch"]+1
    assert not q.finish(wid,key,job["id"],original["epoch"],original["fence_token"],{"bad":True})
    assert q.finish(wid,key,job["id"],fresh["epoch"],fresh["fence_token"],{"good":True})

def test_dead_letter_and_backoff(store):
    q=store
    wid,key=worker(q)
    job=q.submit("acme","python",{"code":"broken"},"retry-job",max_attempts=2)
    a=q.claim(wid,key)
    assert not q.finish(wid,key,job["id"],a["epoch"],"bad",{"no":True})
    assert q.finish(wid,key,job["id"],a["epoch"],a["fence_token"],{"error":"oops"},False)
    with q.tx() as conn:
        conn.execute("UPDATE cluster_jobs SET eligible_at=now()-interval '1 second' WHERE id=%s",(job["id"],))
    b=q.claim(wid,key)
    assert b["epoch"]==2
    assert q.finish(wid,key,job["id"],b["epoch"],b["fence_token"],{"error":"again"},False)
    assert q.job("acme",job["id"])["state"]=="dead"

def test_worker_revocation_and_heartbeat(store):
    q=store
    wid,key=worker(q)
    with pytest.raises(PermissionError):q.heartbeat(wid,"wrong")
    assert q.heartbeat(wid,key)["tenant_id"]=="acme"
    assert q.drain("acme",wid)["draining"]
    q.submit("acme","python",{"code":"safe"},"drained-job")
    assert q.claim(wid,key) is None
    with pytest.raises(KeyError):q.drain("other",wid)

def test_two_tenants_only_claim_own_work(store):
    q=store
    a,ak=worker(q,"acme")
    b,bk=worker(q,"beta")
    q.submit("beta","python",{"k":2},"beta-key")
    assert q.claim(a,ak) is None
    assert q.claim(b,bk)["tenant_id"]=="beta"

def test_concurrent_postgres_claims_under_capacity(store):
    q=store
    wid,key=worker(q)
    ids=[q.submit("acme","python",{"task":n},f"task-{n:08}") for n in range(24)]
    barrier=threading.Barrier(16)
    answers=[];lock=threading.Lock()
    def grab():
        barrier.wait()
        result=q.claim(wid,key)
        with lock:answers.append(result)
    threads=[threading.Thread(target=grab) for _ in range(16)]
    for t in threads:t.start()
    for t in threads:t.join(timeout=20)
    assert len(answers)==16
    assert sum(x is not None for x in answers)==1
    assert q.summary("acme")["jobs"]["leased"]==1

def test_capacity_spread_and_priority(store):
    q=store
    a=q.enroll("acme","host-a",["python"],capacity=2)
    b=q.enroll("acme","host-b",["python"],capacity=2)
    q.submit("acme","python",{"weight":1},"low-prio",priority=-5)
    q.submit("acme","python",{"weight":2},"high-prio",priority=10)
    v=q.claim(a["worker_id"],a["worker_token"])
    assert v["payload"]["weight"]==2
    w=q.claim(b["worker_id"],b["worker_token"])
    assert w["payload"]["weight"]==1

def test_queue_rejects_invalid_envelopes(store):
    q=store
    with pytest.raises(ValueError):q.submit("ACME","python",{},"idempotent")
    with pytest.raises(ValueError):q.submit("acme","shell",{},"valid-key")
    with pytest.raises(ValueError):q.submit("acme","python",{"x":"x"*132000},"large-payload")
    with pytest.raises(ValueError):q.enroll("acme","host",["shell"])
    with pytest.raises(ValueError):q.enroll("acme","host",["python"],capacity=129)

@pytest.fixture
def identity():
    private=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    config=("https://identity.example.com","capsula-control","https://identity.example.com/.well-known/jwks.json")
    client=SimpleNamespace(get_signing_key_from_jwt=lambda token:SimpleNamespace(key=private.public_key()))
    def issue(tenant="acme",role="operator",aud="capsula-control",alg="RS256",expires=300):
        t=int(time.time())
        data={"iss":config[0],"aud":aud,"sub":"person-1","iat":t,"exp":t+expires,
              "capsula_tenant":tenant,"capsula_role":role}
        return "Bearer "+jwt.encode(data,private,algorithm=alg)
    return config,client,issue

def test_oidc_verifies_role_and_tenant(identity):
    cfg,client,issue=identity
    p=cluster_auth.authenticate(issue(),config=cfg,jwks_client=client)
    assert p.tenant=="acme"
    cluster_auth.authorize(p,"acme","operator")
    with pytest.raises(PermissionError):cluster_auth.authorize(p,"beta","viewer")
    with pytest.raises(PermissionError):cluster_auth.authorize(p,"acme","admin")

@pytest.mark.parametrize("changes",[
    {"aud":"other"},{"expires":-60},{"tenant":"../bad"},{"role":"superadmin"}
])
def test_oidc_rejects_claim_attack(identity,changes):
    cfg,client,issue=identity
    with pytest.raises(PermissionError):
        cluster_auth.authenticate(issue(**changes),config=cfg,jwks_client=client)

def test_oidc_rejects_fake_token(identity):
    cfg,client,issue=identity
    for value in ("Bearer no-token","malformed","Bearer ","Bearer a.b.c"):
        with pytest.raises(PermissionError):
            cluster_auth.authenticate(value,config=cfg,jwks_client=client)

class Response:
    def __init__(self,data,status=200):
        self.value=data;self.status_code=status
    def raise_for_status(self):
        if self.status_code>=400:
            import httpx
            raise httpx.HTTPStatusError("upstream",request=httpx.Request("GET","https://api.vultr.com/v2"),response=httpx.Response(self.status_code))
    def json(self):return self.value
class Cloud:
    def __init__(self):self.created=[];self.instances=[]
    def get(self,url,headers):
        if url.endswith("/plans"):return Response({"plans":[{"id":"vc2-1c-2gb","monthly_cost":10}]})
        if url.endswith("/instances"):return Response({"instances":self.instances})
        return Response({},404)
    def post(self,url,headers,json):
        self.created.append(json)
        self.instances.append({"label":json["label"],"region":json["region"],"plan":json["plan"],"id":"vm-123"})
        return Response({"instance":{"id":"vm-123"}})

def test_vultr_plan_budget_idempotency_no_secrets(monkeypatch):
    cloud=Cloud();v=fleet_provider.VultrFleet("test-not-real-key",client=cloud)
    args=dict(prefix="capsula",region="ewr",plan="vc2-1c-2gb",
              os_id=2284,count=3,role="worker",ssh_key_id="ssh-1",max_monthly_usd=35)
    plan=v.plan(**args)
    assert len(plan["missing"])==3 and plan["monthly_usd_estimate"]==30
    with pytest.raises(fleet_provider.ProvisionError):v.apply(plan,approved=True)
    monkeypatch.setenv("CAPSULA_DEPLOY_APPROVED","1")
    result=v.apply(plan,approved=True)
    assert len(result["created"])==3 and not result["runtime_verified"]
    assert len(v.plan(**args)["missing"])==0
    assert not v.apply(plan,approved=True)["created"]
    for request in cloud.created:
        import base64
        user_data=base64.b64decode(request["user_data"])
        assert b"test-not-real-key" not in user_data
        assert b"CAPSULA_API_KEY" not in user_data

def test_vultr_overbudget_fails_without_spend():
    cloud=Cloud();v=fleet_provider.VultrFleet("mock",client=cloud)
    with pytest.raises(fleet_provider.ProvisionError):
        v.plan(prefix="capsula",region="ewr",plan="vc2-1c-2gb",os_id=2284,
               count=3,role="worker",ssh_key_id="ssh-1",max_monthly_usd=20)
    assert cloud.created==[]
