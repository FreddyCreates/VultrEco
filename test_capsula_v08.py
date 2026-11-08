"""Real job boundaries and finance anti-spoofing checks for CAPSULA v0.8."""
import base64,hashlib,hmac,json,os,time,sqlite3
from contextlib import contextmanager
from types import SimpleNamespace
from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest,httpx

import capsule_runtime
import capsule_api
import platform_core as core
from finance_rails import verify_event,stripe_key,public_origin

def encoded(data):return base64.b64encode(data).decode()

@pytest.mark.parametrize('value',['../secret','/etc/passwd','a/../b','a//b','.ssh/key','a/.hidden','a\\b','a/',''])
def test_unsafe_file_paths_never_enter_capsule(value):
    assert capsule_runtime.safe_name(value) is False

def test_bounded_input_accepts_real_csv_and_denies_overflow():
    assert capsule_runtime.decode_inputs({'reports/q.csv':encoded(b'a,b\n1,2\n')})['reports/q.csv']==b'a,b\n1,2\n'
    with pytest.raises(ValueError):capsule_runtime.decode_inputs({'test.csv':encoded(b'1'*256001)})
    with pytest.raises(ValueError):capsule_runtime.decode_inputs({'test.csv':'not-base64'})

def test_containment_denies_unconfigured_runtime():
    r=capsule_runtime.execute_capsule('print(42)',{},bounded_process=lambda *a,**kw:None,env={})
    assert r['status']=='denied' and r['cleanup']=='not-started'

def test_capsule_removes_container_before_return(tmp_path):
    root=tmp_path/'runs';root.mkdir()
    env={'CAPSULA_WORKER_HOST_RUN_PATH':str(root),'CAPSULA_WORKER_CONTAINER_RUN_PATH':str(root),
         'CAPSULA_WORKER_SANDBOX_IMAGE':'python:3.12-alpine'}
    launched=[]
    def bounded(args,timeout,output_limit):
        assert args[:2]==['docker','run']
        assert ['--network','none']==args[args.index('--network'):args.index('--network')+2]
        assert '--read-only' in args and '--cap-drop' in args
        folder=next(root.glob('capsula-job-*'))
        assert (folder/'inputs'/'q.csv').read_bytes()==b'a,b\n1,2\n'
        assert ((folder/'outputs').stat().st_mode & 0o777)==0o777
        (folder/'outputs'/'result.csv').write_bytes(b'total\n3\n')
        launched.append(True)
        return {'status':'completed','stdout':'wrote file','stderr':'','exit_code':0}
    def run(args,**kw):
        if 'inspect' in args:return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)
    r=capsule_runtime.execute_capsule('print(3)',{'q.csv':encoded(b'a,b\n1,2\n')},
                                      bounded_process=bounded,run=run,env=env)
    assert r['status']=='completed' and r['cleanup']=='verified-destroyed'
    assert base64.b64decode(r['artifacts']['result.csv']['base64'])==b'total\n3\n'
    assert list(root.iterdir())==[] and launched

def test_receivable_webhook_hmac_valid():
    value={'object':'event','id':'evt_real123','type':'checkout.session.completed'}
    body=json.dumps(value).encode();stamp=int(time.time())
    mac=hmac.new(b'whsec_test',str(stamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
    assert verify_event(body,f't={stamp},v1={mac}','whsec_test')==value
    with pytest.raises(PermissionError):
        verify_event(body+b' ',f't={stamp},v1={mac}','whsec_test')
    with pytest.raises(PermissionError):
        verify_event(body,f't={stamp-301},v1={mac}','whsec_test')

def test_provider_access_never_defaults_to_fake_money():
    with pytest.raises(RuntimeError):stripe_key({})
    with pytest.raises(RuntimeError):public_origin({'CAPSULA_FINANCE_PUBLIC_ORIGIN':'http://localhost:5000'})
    with pytest.raises(RuntimeError):public_origin({'CAPSULA_FINANCE_PUBLIC_ORIGIN':'https://admin@pay.example.com'})
    assert stripe_key({'CAPSULA_STRIPE_SECRET_KEY':'sk_test_'+'x'*24}).startswith('sk_test_')

@pytest.fixture
def capsule_client(tmp_path):
    dbpath=tmp_path/'test.db';app=FastAPI()
    class Vault:
        def seal(self,data,context):return {'context':context,'body':data}
        def open(self,s,context):
            assert s['context']==context
            return s['body']
    vault=Vault()
    @contextmanager
    def conn():
        db=sqlite3.connect(dbpath,timeout=20);db.row_factory=sqlite3.Row
        try:yield db;db.commit()
        finally:db.close()
    with conn() as db:
        db.execute('CREATE TABLE workspaces(slug TEXT PRIMARY KEY,description TEXT,created TEXT)')
        db.execute("INSERT INTO workspaces VALUES('research','workspace','today')")
        core.schema(db)
    class Fleet:
        def reserve(self,db,kind,job,lease_seconds):return {'lease_id':'slot','worker':{'id':'worker1','endpoint':'https://worker.example'}}
        def complete(self,db,slot,success):return True
    class HTTP:
        HTTPError=httpx.HTTPError
        class Client:
            def __init__(self,**kwargs):assert kwargs['trust_env'] is False
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def post(self,url,json,headers):
                assert url=='https://worker.example/capsules/execute'
                body=b'one,two\n3,4\n'
                result={'status':'completed','cleanup':'verified-destroyed','stdout':'created','stderr':'',
                        'artifacts':{'result.csv':{'base64':encoded(body),'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}}}
                digest=hashlib.sha256(__import__('json').dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'result':result,'digest':'sha256:'+digest})
    m=SimpleNamespace(app=app,conn=conn,vault=vault,signer=None,now=lambda:'today',
          canonical=lambda obj:json.dumps(obj,sort_keys=True,separators=(',',':')),
          audit_append=lambda *args:None,authed=lambda header:None if header=='Bearer owner' else (_ for _ in ()).throw(RuntimeError('auth')),
          fleet=Fleet(),WORKER_TOKEN='secret',WORKER_ALLOWED={'https://worker.example'},httpx=HTTP)
    capsule_api.bind(m)
    return TestClient(app),conn,vault

def test_real_user_capsule_execution_and_download(capsule_client):
    client,conn,vault=capsule_client
    with conn() as db:
        core.put_file(db,core.ProjectFile(workspace='research',path='q.csv',content='a,b\n1,2\n'),vault,None,lambda *args:None)
    h={'Authorization':'Bearer owner'}
    created=client.post('/api/capsules',headers=h,json={'workspace':'research','title':'Parse a CSV and save outputs',
       'code':'import csv;print(42)','input_paths':['q.csv']})
    assert created.status_code==201,created.text
    job=created.json()['id']
    outcome=client.post('/api/capsules/'+job+'/execute',headers=h)
    assert outcome.status_code==200,outcome.text
    assert outcome.json()['cleanup']=='verified-destroyed'
    artifact=client.get('/api/capsules/'+job+'/outputs/result.csv',headers=h)
    assert artifact.status_code==200 and artifact.content==b'one,two\n3,4\n'
    assert artifact.headers['x-capsula-sha256']==hashlib.sha256(artifact.content).hexdigest()
    assert client.post('/api/capsules/'+job+'/execute',headers=h).status_code==409
    assert client.delete('/api/capsules/'+job,headers=h).json()['discarded']
    assert client.get('/api/capsules/'+job,headers=h).status_code==404

def test_agent_cannot_cross_workspace_without_authority(capsule_client):
    client,conn,_=capsule_client
    with conn() as db:
        profile=core.create_agent(db,core.AgentInput(workspace='research',name='Test agent',capabilities=['memory']),None,lambda *args:None)
    h={'Authorization':'Bearer owner'}
    result=client.post('/api/capsules',headers=h,json={'workspace':'research','title':'Forbidden execution','code':'print(42)','agent_id':profile['id']})
    assert result.status_code==403
