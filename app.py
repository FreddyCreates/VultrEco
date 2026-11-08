"""CAPSULA web control plane. Execution fails closed without Docker isolation."""
import os, json, time, uuid, hashlib, sqlite3, subprocess, tempfile, pathlib, re, hmac
from datetime import datetime, timezone
from contextlib import contextmanager
from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Literal
from proof import Signer, Vault, canon as canonical_bytes, sha, tree, inclusion, check_inclusion
from policy import CAPABILITIES, evaluate
import platform_core as core
import learning
from workspaces import MemoryInput, WorkspaceInput
from audit import schema as audit_schema, append as audit_append, verify as audit_verify
from federation import schema as federation_schema, inventory as federation_inventory, WorkerRegistration, FinanceIntent, GrantInput, ApprovalInput, now as fed_now, expiry as fed_expiry, worker_status
import ipaddress, urllib.parse, decimal, httpx
import fleet

ROOT=pathlib.Path(__file__).resolve().parent
DATA=pathlib.Path(os.environ.get('CAPSULA_DATA','./data')).resolve()
DATA.mkdir(parents=True, exist_ok=True)
DB=DATA/'capsula.sqlite3'
API_KEY=os.environ.get('CAPSULA_API_KEY','')
DOCKER_IMAGE=os.environ.get('CAPSULA_SANDBOX_IMAGE','python:3.12-alpine')
ALLOWED_IMAGE=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._/:@-]{1,127}$')
if not ALLOWED_IMAGE.fullmatch(DOCKER_IMAGE): raise RuntimeError('Invalid sandbox image')
app=FastAPI(title='CAPSULA Mission Control',version='0.7.0-alpha.1')
signer=Signer(DATA/'keys'/'ed25519.pem')
vault=Vault(DATA/'keys'/'vault.key')

@contextmanager
def conn():
    db=sqlite3.connect(DB,timeout=20)
    db.row_factory=sqlite3.Row
    try:
        yield db
        db.commit()
    finally: db.close()

with conn() as db:
    db.execute('CREATE TABLE IF NOT EXISTS missions (id TEXT PRIMARY KEY, title TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL, created TEXT NOT NULL, updated TEXT NOT NULL, input TEXT NOT NULL, output TEXT NOT NULL, receipt TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id TEXT NOT NULL, ts TEXT NOT NULL, type TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS workspaces (slug TEXT PRIMARY KEY, description TEXT NOT NULL, created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS memory (id TEXT PRIMARY KEY, workspace TEXT NOT NULL, label TEXT NOT NULL, created TEXT NOT NULL, origin TEXT NOT NULL, ciphertext TEXT NOT NULL, digest TEXT NOT NULL)')
    federation_schema(db)
    audit_schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS artifact_blobs (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,mission_id TEXT,name TEXT NOT NULL,mime TEXT NOT NULL,created TEXT NOT NULL,digest TEXT NOT NULL,blob TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS invoices (id TEXT PRIMARY KEY, created TEXT NOT NULL, title TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, destination TEXT NOT NULL, status TEXT NOT NULL)')
    core.schema(db)

def now(): return datetime.now(timezone.utc).isoformat()
def docker_ready():
    try:return subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,timeout=3).returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired):return False
def event_data(db,mid):
    return [{'ts':r['ts'],'type':r['type'],'payload':json.loads(r['payload']),'prev_hash':r['prev_hash'],'hash':r['hash']} for r in db.execute('SELECT ts,type,payload,prev_hash,hash FROM events WHERE mission_id=? ORDER BY id',(mid,))]
def verify_chain(mid,events):
    previous='0'*64
    for e in events:
        expected={'mission_id':mid,'ts':e['ts'],'type':e['type'],'payload':e['payload'],'prev_hash':previous}
        if e['prev_hash']!=previous or digest(canonical(expected))!=e['hash']:return False
        previous=e['hash']
    return True
def decode_output(row,mid):
    obj=json.loads(row['output'])
    return vault.open(obj['sealed'],mid) if 'sealed' in obj else obj
def canonical(x): return json.dumps(x,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def digest(s): return hashlib.sha256(s.encode('utf-8')).hexdigest()
def event(db,mid,kind,data):
    prev=db.execute('SELECT hash FROM events WHERE mission_id=? ORDER BY id DESC LIMIT 1',(mid,)).fetchone()
    prevhash=prev['hash'] if prev else '0'*64
    ts=now()
    content={'mission_id':mid,'ts':ts,'type':kind,'payload':data,'prev_hash':prevhash}
    hashval=digest(canonical(content))
    db.execute('INSERT INTO events(mission_id,ts,type,payload,prev_hash,hash) VALUES(?,?,?,?,?,?)',(mid,ts,kind,canonical(data),prevhash,hashval))
    return hashval

def authed(authorization):
    if os.getenv("CAPSULA_ENTERPRISE_MODE")=="1":
        raise HTTPException(403,"Legacy single-admin API disabled in enterprise mode")
    if not API_KEY: raise HTTPException(503,'Set CAPSULA_API_KEY before use')
    if not authorization or not hmac.compare_digest(authorization, 'Bearer '+API_KEY): raise HTTPException(401,'Invalid API key')

class MissionInput(BaseModel):
    title:str=Field(min_length=3,max_length=100)
    kind:Literal['python','browser','research']='python'
    code:str=Field(default='',max_length=16000)
    url:str=Field(default='',max_length=300)
    selector:str=Field(default='',max_length=200)

class InvoiceInput(BaseModel):
    title:str=Field(min_length=2,max_length=160)
    amount:str=Field(pattern=r'^\d{1,10}(\.\d{1,2})?$',max_length=14)
    currency:Literal['USDC','USD']='USDC'
    destination:str=Field(default='',max_length=160)

@app.get('/')
def index():return FileResponse(ROOT/'static'/'index.html')
@app.get('/api/health')
def health():
    docker_ready=False
    try:
        r=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,timeout=3)
        docker_ready=r.returncode==0
    except (FileNotFoundError,subprocess.TimeoutExpired):pass
    return {'service':'capsula','version':'0.7.0-alpha.1','auth_configured':bool(API_KEY),'sandbox_ready':docker_ready,'execution_mode':'docker-or-worker' if docker_ready else 'worker-required-or-deny','proof_protocol':'capsula.proof.v2','signing_key_id':signer.key_id,'inference_configured':__import__('inference').config()['configured']}

@app.get('/api/overview')
def overview(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        counts={r['status']:r['n'] for r in db.execute('SELECT status,COUNT(*) n FROM missions GROUP BY status')}
        n=db.execute('SELECT COUNT(*) n FROM events').fetchone()['n']
        return {'missions':sum(counts.values()),'complete':counts.get('completed',0),'denied':counts.get('denied',0),'failed':counts.get('failed',0),'events':n,'workspaces':db.execute('SELECT COUNT(*) n FROM workspaces').fetchone()['n'],'memory_records':db.execute('SELECT COUNT(*) n FROM memory').fetchone()['n'],'systems':[{'name':x['name'],'status':x['status']} for x in federation_inventory().values()]+[{'name':'CAPSULA Worker','status':'worker lease managed'}]}

@app.get('/api/missions')
def missions(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db: return [dict(x) for x in db.execute('SELECT id,title,kind,status,created,updated FROM missions ORDER BY created DESC LIMIT 80')]

@app.get('/api/missions/{mid}')
def mission(mid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        row=db.execute('SELECT * FROM missions WHERE id=?',(mid,)).fetchone()
        if not row: raise HTTPException(404,'Mission not found')
        x=dict(row)
        raw_input=json.loads(x['input']);x['input']=vault.open(raw_input['sealed'],mid+':input') if 'sealed' in raw_input else raw_input;x['output']=decode_output(row,mid);x['receipt']=json.loads(x['receipt'])
        x['events']=[{**dict(e),'payload':json.loads(e['payload'])} for e in db.execute('SELECT ts,type,payload,prev_hash,hash FROM events WHERE mission_id=? ORDER BY id',(mid,))]
        x['chain_valid']=verify_chain(mid,x['events'])
        x['proof_valid']=verify_proof(x['receipt'],x['events'],x['output'],mid)
        return x

# No shell, no host filesystem mounts, no network, no new privileges, and strict resource bounds.
# Only execute Python provided by an authorized principal. This is NOT an arbitrary host command interface.
def run_python(code,mid):
    if not code.strip():return {'status':'denied','reason':'Python code required','stdout':'','stderr':'','exit_code':None}
    with tempfile.TemporaryDirectory(prefix='capsula-',dir=str(DATA)) as tmp:
        p=pathlib.Path(tmp)/'mission.py';p.write_text(code,encoding='utf-8')
        host_root=os.environ.get('CAPSULA_WORKSPACE_HOST_PATH')
        if host_root:
            source=pathlib.Path(host_root)/pathlib.Path(tmp).name/'mission.py'
        else: source=p
        container_name='capsula-'+uuid.uuid4().hex[:20]
        cmd=['docker','run','--rm','--name',container_name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64','--memory','192m','--memory-swap','192m','--cpus','0.5','--user','65534:65534','--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--mount',f'type=bind,src={source},dst=/work/mission.py,readonly','--workdir','/work',DOCKER_IMAGE,'python','-B','/work/mission.py']
        try:
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=18)
            return {'status':'completed' if run.returncode==0 else 'failed','stdout':run.stdout[:24000],'stderr':run.stderr[:12000],'exit_code':run.returncode}
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',container_name],capture_output=True,timeout=5,check=False)
            return {'status':'failed','reason':'Execution timeout; container forcibly removed','stdout':'','stderr':'','exit_code':124}
        except FileNotFoundError:return {'status':'denied','reason':'Docker unavailable; refusing unisolated execution','stdout':'','stderr':'','exit_code':None}

@app.post('/api/missions')
def create(body:MissionInput,authorization:str|None=Header(None)):
    authed(authorization)
    mid=uuid.uuid4().hex[:16];ts=now()
    with conn() as db:
        db.execute('INSERT INTO missions VALUES(?,?,?,?,?,?,?,?,?)',(mid,body.title,body.kind,'queued',ts,ts,canonical({'sealed':vault.seal(body.model_dump(),mid+':input')}),'{}','{}'))
        decision=evaluate(body,((docker_ready() and os.getenv('CAPSULA_ALLOW_DIRECT_DOCKER')=='1') if body.kind=='python' and os.getenv('CAPSULA_COMPETITION_MODE')!='1' else False) or bool(select_worker(db,body.kind)))
        event(db,mid,'mission.accepted',{'title':body.title,'kind':body.kind})
        event(db,mid,'policy.decision',decision)
    if decision['decision']=='deny':output={'status':'denied','reason':'; '.join(decision['reasons']),'stdout':'','stderr':'','exit_code':None}
    else:output=dispatch_mission(body,mid)
    status=output['status'];ts=now()
    with conn() as db:
        hashval=event(db,mid,'mission.'+status,{'result_hash':digest(canonical(output)),'exit_code':output.get('exit_code'),'reason':output.get('reason')})
        events=event_data(db,mid)
        payload={'protocol':'capsula.proof.v2','mission_id':mid,'kind':body.kind,'status':status,'result_digest':sha(canonical_bytes(output)),'event_chain_head':hashval,'merkle_root':tree(events),'event_count':len(events),'policy':decision,'completed_at':ts,'execution_claim':output.get('execution_claim','not-executed') if decision['decision']=='permit' else 'not-executed','attestation':'operator-signed-record-not-hardware-attested'}
        receipt={'payload':payload,'signature':signer.sign(payload),'public_key':signer.public()}
        db.execute('UPDATE missions SET status=?,updated=?,output=?,receipt=? WHERE id=?',(status,ts,canonical({'sealed':vault.seal(output,mid)}),canonical(receipt),mid))
    return {'id':mid,'status':status,'receipt':receipt}


def verify_proof(receipt,events,output,mid):
    if receipt.get('payload',{}).get('protocol')!='capsula.proof.v2':return False
    pay=receipt['payload'];pub=receipt.get('public_key',{})
    try:
        if not (verify_chain(mid,events) and pay.get('mission_id')==mid):return False
        return (
        pay.get('event_count')==len(events) and pay.get('merkle_root')==tree(events) and
        pay.get('event_chain_head')==(events[-1]['hash'] if events else '0'*64) and
        pay.get('result_digest')==sha(canonical_bytes(output)) and
        pub.get('key_id')=='ed25519:'+sha(__import__('proof').unb64(pub.get('public_key','')))[:24] and
        Signer.verify_external(pay,receipt.get('signature',''),pub.get('public_key','')))
    except (ValueError,KeyError,TypeError):return False

@app.get('/api/proof/public-key')
def public_key():return signer.public()

@app.get('/api/capabilities')
def capabilities(authorization:str|None=Header(None)):
    authed(authorization)
    return {'protocol':'capsula.capabilities.v2','capabilities':CAPABILITIES,'finance_enabled':False,'integration_state':'none connected'}

@app.get('/api/missions/{mid}/evidence')
def evidence(mid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        row=db.execute('SELECT * FROM missions WHERE id=?',(mid,)).fetchone()
        if row is None:raise HTTPException(404,'Mission not found')
        events=event_data(db,mid);output=decode_output(row,mid);receipt=json.loads(row['receipt'])
        valid=verify_proof(receipt,events,output,mid)
        return {'verified':valid,'trust_level':'operator-signed','not_verified':['host-integrity','hardware-attestation','external-execution','docker-namespace-runtime-measurement'],
                'receipt':receipt,'output':output,'events':events,'inclusion':{'index':0,'path':inclusion(events,0),'verified':check_inclusion(events[0],inclusion(events,0),tree(events))} if events else None}


@app.get('/api/workspaces')
def list_workspaces(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [dict(row) for row in db.execute('SELECT * FROM workspaces ORDER BY slug LIMIT 100')]

@app.post('/api/workspaces')
def create_workspace(body:WorkspaceInput,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        if db.execute('SELECT slug FROM workspaces WHERE slug=?',(body.slug,)).fetchone():raise HTTPException(409,'Workspace exists')
        db.execute('INSERT INTO workspaces VALUES(?,?,?)',(body.slug,body.description,now()))
    return {'slug':body.slug,'description':body.description,'role':'single-admin','isolation':'logical namespace, not tenant security'}

@app.post('/api/memory')
def save_memory(body:MemoryInput,authorization:str|None=Header(None)):
    authed(authorization)
    mid=uuid.uuid4().hex;ts=now()
    with conn() as db:
        if not db.execute('SELECT slug FROM workspaces WHERE slug=?',(body.workspace,)).fetchone():raise HTTPException(404,'Workspace not found')
        encrypted=vault.seal({'content':body.content,'origin':body.origin},'memory:'+body.workspace+':'+mid)
        db.execute('INSERT INTO memory VALUES(?,?,?,?,?,?,?)',(mid,body.workspace,body.label,ts,body.origin,canonical(encrypted),sha(body.content.encode())))
    return {'id':mid,'workspace':body.workspace,'label':body.label,'created':ts,'content_digest':sha(body.content.encode()),'encryption':'AES-256-GCM','persisted':True}

@app.get('/api/memory/{workspace}')
def list_memory(workspace:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        if not db.execute('SELECT slug FROM workspaces WHERE slug=?',(workspace,)).fetchone():raise HTTPException(404,'Workspace not found')
        return [{k:r[k] for k in ('id','workspace','label','created','origin','digest')} for r in db.execute('SELECT * FROM memory WHERE workspace=? ORDER BY created DESC LIMIT 100',(workspace,))]

@app.get('/api/memory/{workspace}/{memory_id}')
def get_memory(workspace:str,memory_id:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        r=db.execute('SELECT * FROM memory WHERE workspace=? AND id=?',(workspace,memory_id)).fetchone()
        if not r:raise HTTPException(404,'Memory not found')
        payload=vault.open(json.loads(r['ciphertext']),'memory:'+workspace+':'+memory_id)
        return {'id':memory_id,'workspace':workspace,'label':r['label'],'content':payload['content'],'origin':payload['origin'],'digest':r['digest'],'digest_valid':sha(payload['content'].encode())==r['digest']}

@app.get('/api/integrations')
def integrations(authorization:str|None=Header(None)):
    authed(authorization)
    x=federation_inventory();x['model_provider']={'status':'configured-not-verified' if __import__('inference').config()['configured'] else 'unconnected','purpose':'operator-selected OpenAI-compatible inference, local or remote'};x['vultr_inference']={'status':'optional adapter, required in challenge deployment profile','purpose':'Vultr challenge model lane'};x['phantom']={'status':'browser-connection-only','purpose':'user-controlled wallet discovery'}
    x['rah']={'name':'RAH bounded mission autonomy','status':'host configured, live execution requires acceptance' if __import__('computers').configured()['configured'] else 'implemented; dedicated host unconfigured','purpose':'Existing VM pool, recursive grants, hashed artifact handoffs'}
    x['improvement']={'name':'Clean improvement capsules','status':'implemented; separate worker required','purpose':'Frozen baseline/candidate cases and verified procedure promotion'}
    return x

@app.get('/api/invoices')
def invoices(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [dict(x) for x in db.execute('SELECT * FROM invoices ORDER BY created DESC LIMIT 50')]

@app.post('/api/invoices')
def make_invoice(body:InvoiceInput,authorization:str|None=Header(None)):
    authed(authorization)
    item={'id':'INV-'+uuid.uuid4().hex[:8].upper(),'created':now(),**body.model_dump(),'status':'draft — not payable'}
    with conn() as db:db.execute('INSERT INTO invoices VALUES(?,?,?,?,?,?,?)',tuple(item[k] for k in ['id','created','title','amount','currency','destination','status']))
    return item

app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')


# Federated execution: scoped per-worker lease. A worker's heartbeat proves reachability claim, not integrity.
WORKER_TOKEN=os.getenv('CAPSULA_WORKER_TOKEN','')
WORKER_ALLOWED=os.getenv('CAPSULA_WORKER_ALLOWED_ENDPOINTS','').split(',')
WORKER_ALLOWED={x.strip() for x in WORKER_ALLOWED if x.strip()}

def select_worker(db,kind):
    return fleet.peek(db,kind)

def dispatch_mission(body,mid):
    with conn() as db: reservation=fleet.reserve(db,body.kind,mid,lease_seconds=45)
    worker=reservation['worker'] if reservation else None
    if not worker:
        if body.kind=='python' and os.getenv('CAPSULA_ALLOW_DIRECT_DOCKER')=='1' and os.getenv('CAPSULA_COMPETITION_MODE')!='1':
            out=run_python(body.code,mid);out['execution_claim']='docker-process-exit-observed' if out['status']!='denied' else 'not-executed';return out
        return {'status':'denied','reason':'No isolated worker lease or approved sandbox backend for capability','exit_code':None,'stdout':'','stderr':''}
    if not WORKER_TOKEN or worker['endpoint'] not in WORKER_ALLOWED:
        with conn() as db:fleet.complete(db,reservation['lease_id'],False)
        return {'status':'denied','reason':'Worker endpoint/token not allowlisted','exit_code':None,'stdout':'','stderr':''}
    jobid=uuid.uuid4().hex;ts=now();deadline=fed_expiry(15)
    with conn() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(jobid,mid,worker['id'],body.kind,'dispatched',ts,ts,canonical({'kind':body.kind}),canonical({}),deadline))
    try:
        with httpx.Client(timeout=12,follow_redirects=False,trust_env=False) as client:
            res=client.post(worker['endpoint']+'/execute',json={'kind':body.kind,'code':body.code,'url':body.url,'selector':body.selector},headers={'Authorization':'Bearer '+WORKER_TOKEN})
            res.raise_for_status();reply=res.json()
        result=reply['result'];result['execution_claim']=reply.get('worker_claim','worker-reported-execution-not-attested')
        if result.get('status') not in ('completed','failed','denied'):raise ValueError('Invalid worker status')
        if reply.get('digest') != 'sha256:'+hashlib.sha256(canonical({k:v for k,v in result.items() if k!='execution_claim'}).encode()).hexdigest():raise ValueError('Worker result integrity mismatch')
    except (httpx.HTTPError,ValueError,KeyError,TypeError) as exc:
        result={'status':'failed','reason':'Worker dispatch or proof failure','exit_code':None,'stdout':'','stderr':'','execution_claim':'not-verified'}
    with conn() as db:
        db.execute('UPDATE jobs SET status=?,updated=?,result=? WHERE id=?',(result['status'],now(),canonical(result),jobid))
        fleet.complete(db,reservation['lease_id'],result['status']=='completed')
    return result

@app.get('/api/workers')
def workers(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [worker_status(r) for r in db.execute('SELECT * FROM workers ORDER BY registered DESC LIMIT 100')]

@app.post('/api/workers')
def register_worker(body:WorkerRegistration,authorization:str|None=Header(None)):
    authed(authorization)
    if body.kind not in ('python','browser','research','compute','agent'):raise HTTPException(422,'Invalid worker type')
    if body.endpoint not in WORKER_ALLOWED:raise HTTPException(403,'Endpoint must be configured by operator')
    u=urllib.parse.urlparse(body.endpoint)
    if u.username or u.password or u.query or u.fragment or u.path not in ('','/') or not u.hostname:raise HTTPException(403,'Malformed worker origin')
    if u.scheme!='https' and not (u.scheme=='http' and u.hostname in ('127.0.0.1','localhost','::1')):raise HTTPException(403,'Remote workers require HTTPS')
    if not WORKER_TOKEN:raise HTTPException(503,'Worker authentication not provisioned')
    with conn() as db:
        db.execute('INSERT INTO workers VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET kind=excluded.kind, endpoint=excluded.endpoint, capabilities=excluded.capabilities, status=excluded.status, heartbeat=excluded.heartbeat,lease_expiry=excluded.lease_expiry',(body.id,body.kind,body.endpoint,canonical(body.capabilities),'active',now(),now(),fed_expiry(45)))
        audit_append(db,signer,'worker.registered',body.id,{'kind':body.kind,'endpoint':body.endpoint})
    return {'id':body.id,'status':'registered','lease_seconds':45,'security':'registration only; not execution attestation'}

@app.post('/api/workers/{worker_id}/heartbeat')
def heartbeat(worker_id:str,authorization:str|None=Header(None)):
    if not WORKER_TOKEN or not hmac.compare_digest(authorization or '', 'Bearer '+WORKER_TOKEN):raise HTTPException(401,'Worker authentication failed')
    with conn() as db:
        r=db.execute('UPDATE workers SET heartbeat=?,lease_expiry=? WHERE id=? AND status=?',(now(),fed_expiry(45),worker_id,'active'))
        if r.rowcount!=1:raise HTTPException(404,'Unknown worker')
    return {'worker_id':worker_id,'lease_seconds':45}

@app.get('/api/jobs')
def jobs(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [dict(r) for r in db.execute('SELECT id,mission_id,worker_id,kind,status,created,updated,deadline FROM jobs ORDER BY created DESC LIMIT 100')]

@app.post('/api/approvals')
def request_approval(body:ApprovalInput,authorization:str|None=Header(None)):
    authed(authorization)
    aid=uuid.uuid4().hex;ts=now()
    with conn() as db:
        db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(aid,body.action,body.scope,canonical(body.payload),'pending',ts,''))
        audit_append(db,signer,'approval.requested',aid,{'action':body.action,'scope':body.scope,'payload':body.payload})
    return {'id':aid,'status':'pending','execution':'none'}

@app.get('/api/approvals')
def list_approvals(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [{**dict(r),'payload':json.loads(r['payload'])} for r in db.execute('SELECT * FROM approvals ORDER BY created DESC LIMIT 100')]

@app.post('/api/approvals/{aid}/decide')
def decide_approval(aid:str,decision:Literal['approve','reject'],authorization:str|None=Header(None)):
    authed(authorization)
    state='approved' if decision=='approve' else 'rejected'
    with conn() as db:
        r=db.execute('UPDATE approvals SET status=?, decided=? WHERE id=? AND status=?',(state,now(),aid,'pending'))
        if r.rowcount!=1:raise HTTPException(409,'Approval missing or already decided')
        audit_append(db,signer,'approval.'+state,aid,{'decision':decision})
    return {'id':aid,'status':state,'execution':'none; approval does not execute transactions'}

@app.post('/api/finance/intents')
def propose_payment(body:FinanceIntent,authorization:str|None=Header(None)):
    authed(authorization)
    iid='PAY-'+uuid.uuid4().hex[:16].upper()
    item={'id':iid,**body.model_dump(),'status':'proposal-only-unfunded','created':now()}
    with conn() as db:
        if body.grant_id:
            grant=db.execute('SELECT * FROM grants WHERE id=?',(body.grant_id,)).fetchone()
            if not grant or grant['kind']!='payment_proposal' or grant['revoked'] or grant['expires']<=now() or decimal.Decimal(body.amount)>decimal.Decimal(grant['amount_limit']):raise HTTPException(403,'Grant absent, expired or insufficient for proposal')
        db.execute('INSERT INTO finance_intents VALUES(?,?,?,?,?,?,?,?,?)',(iid,body.grant_id,body.recipient,body.amount,body.asset,body.chain,body.reason,item['status'],item['created']))
        audit_append(db,signer,'finance.intent_proposed',iid,{'asset':body.asset,'chain':body.chain,'amount':body.amount,'grant':body.grant_id,'status':item['status']})
    return {**item,'signed':False,'broadcast':False,'custody':'none'}

@app.get('/api/finance/intents')
def list_payment_intents(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [dict(r) for r in db.execute('SELECT * FROM finance_intents ORDER BY created DESC LIMIT 100')]

@app.get('/api/security/posture')
def security_posture(authorization:str|None=Header(None)):
    authed(authorization)
    return {'version':'0.6.0-alpha.1','execution_attested':False,'remote_workers_enforced':bool(WORKER_ALLOWED and WORKER_TOKEN),'external_witness':False,'finance_signing_enabled':False,'key_management':'local encrypted private key; not external KMS','tenancy':'single-admin','browser_status':'requires separately isolated Playwright worker and network-level egress policy','deployment_verified':False}

from artifacts import ArtifactInput
from inference import InferenceInput, infer
@app.post('/api/inference/complete')
def inference_complete(body:InferenceInput,authorization:str|None=Header(None)):
    authed(authorization)
    return infer(body)

@app.get('/api/federation/contracts')
def contracts(authorization:str|None=Header(None)):
    authed(authorization)
    return {'supported':['capsula.policy.v2','capsula.proof.v2','capsula.worker.v1','capsula.finance-intent.v1','capsula.approval.v1','capsula.rah-work-grant.v1','capsula.improvement-grant.v1','capsula.improvement-trial.v1'],
      'adapters':federation_inventory(), 'external_services_verified':False,
      'transport':'operator-configured HTTPS only', 'execution_permissions':'deny-by-default'}


@app.post('/api/finance/grants')
def propose_grant(body:GrantInput,authorization:str|None=Header(None)):
    authed(authorization)
    try:exp=datetime.fromisoformat(body.expires.replace('Z','+00:00'))
    except ValueError:raise HTTPException(422,'Invalid ISO8601 expiry')
    if not exp.tzinfo or exp<=datetime.now(timezone.utc) or exp>datetime.now(timezone.utc)+__import__('datetime').timedelta(days=7):raise HTTPException(422,'Expiry must be within seven days')
    gid='GR-'+uuid.uuid4().hex[:16];ts=now()
    with conn() as db:
        db.execute('INSERT INTO grants VALUES(?,?,?,?,?,?,?,?)',(gid,body.scope,body.kind,body.amount_limit,'0',body.expires,ts,0))
        audit_append(db,signer,'finance.proposal_grant_created',gid,{'scope':body.scope,'limit':body.amount_limit,'kind':body.kind,'expiry':body.expires})
    return {'id':gid,'status':'proposal-limit-only','spending_authority':False}

@app.get('/api/finance/grants')
def list_grants(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [dict(r) for r in db.execute('SELECT * FROM grants ORDER BY created DESC LIMIT 100')]

@app.post('/api/finance/grants/{gid}/revoke')
def revoke_grant(gid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        r=db.execute('UPDATE grants SET revoked=1 WHERE id=? AND revoked=0',(gid,))
        if r.rowcount!=1:raise HTTPException(404,'Active grant not found')
        audit_append(db,signer,'finance.proposal_grant_revoked',gid,{'revoked':True})
    return {'id':gid,'revoked':True,'onchain_action':False}

@app.get('/api/audit')
def governance_audit(authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        rows=[dict(r) for r in db.execute('SELECT * FROM audit_events ORDER BY seq ASC LIMIT 10000')]
        return {'protocol':'capsula.governance-evidence.v1','entries':rows,'verified':audit_verify(rows,signer),'public_key':signer.public(),'external_witness':False}

from nexus_bridge import NexusTask,compile_handoff
@app.post('/api/federation/nexus/task')
def accept_nexus_task(task:NexusTask,authorization:str|None=Header(None)):
    authed(authorization)
    if task.action=='execute.python':kind='python'
    else:kind='browser'
    with conn() as db:
        if not db.execute('SELECT 1 FROM workspaces WHERE slug=?',(task.workspace,)).fetchone():raise HTTPException(404,'Scoped workspace not found')
    body=MissionInput(title=task.title,kind=kind,code=task.code,url=task.url,selector=task.selector)
    result=create(body,authorization)
    return compile_handoff(task,result)


@app.post('/api/artifacts')
def write_artifact(body:ArtifactInput,authorization:str|None=Header(None)):
    authed(authorization)
    aid=uuid.uuid4().hex;timestamp=now();blobbytes=body.content.encode('utf-8');content_digest=sha(blobbytes)
    with conn() as db:
        if not db.execute('SELECT 1 FROM workspaces WHERE slug=?',(body.workspace,)).fetchone():raise HTTPException(404,'Workspace missing')
        if body.mission_id and not db.execute('SELECT 1 FROM missions WHERE id=?',(body.mission_id,)).fetchone():raise HTTPException(404,'Mission missing')
        encrypted=vault.seal({'content':body.content,'digest':content_digest},'artifact:'+body.workspace+':'+aid)
        db.execute('INSERT INTO artifact_blobs VALUES(?,?,?,?,?,?,?,?)',(aid,body.workspace,body.mission_id,body.name,body.mime,timestamp,content_digest,canonical(encrypted)))
        audit_append(db,signer,'artifact.sealed',aid,{'workspace':body.workspace,'mission_id':body.mission_id,'name':body.name,'content_digest':'sha256:'+content_digest,'bytes':len(blobbytes)})
    return {'id':aid,'workspace':body.workspace,'mission_id':body.mission_id,'name':body.name,'digest':'sha256:'+content_digest,'encrypted':True,'audit_signed':True}

@app.get('/api/artifacts')
def list_artifacts(workspace:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return [{k:r[k] for k in ('id','workspace','mission_id','name','mime','created','digest')} for r in db.execute('SELECT * FROM artifact_blobs WHERE workspace=? ORDER BY created DESC LIMIT 100',(workspace,))]

@app.get('/api/artifacts/{aid}')
def read_artifact(aid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        row=db.execute('SELECT * FROM artifact_blobs WHERE id=?',(aid,)).fetchone()
        if not row:raise HTTPException(404,'Artifact missing')
    item=vault.open(json.loads(row['blob']),'artifact:'+row['workspace']+':'+aid)
    if sha(item['content'].encode('utf-8'))!=row['digest'] or item['digest']!=row['digest']:raise HTTPException(409,'Artifact commitment invalid')
    return {'id':aid,'workspace':row['workspace'],'name':row['name'],'mime':row['mime'],'content':item['content'],'digest':'sha256:'+row['digest'],'verified_local_integrity':True,'verified_external_origin':False}


# CAPSULA Work OS v0.4: first-class projects/files/agents/runs. Provider independent.
@app.get('/api/platform')
def platform_status(authorization:str|None=Header(None)):
    authed(authorization)
    from inference import public_config
    with conn() as db:
        counts={k:db.execute(f'SELECT COUNT(*) n FROM {k}').fetchone()['n'] for k in ('workspaces','project_files','agent_profiles','agent_runs','missions','workers','approvals','artifact_blobs','memory')}
    return {'name':'CAPSULA','version':'0.6.0-alpha.1','counts':counts,'models':public_config(),
            'execution_backends':['docker-worker','remote-worker'],'default_runtime':'deny-without-isolation',
            'provider_policy':'no dependency on Vultr','tenancy':'single-admin','payment_execution':'disabled'}

@app.get('/api/providers')
def providers(authorization:str|None=Header(None)):
    authed(authorization)
    from inference import public_config
    model=public_config()
    vultr_on=bool(os.getenv('VULTR_API_KEY','').strip() or os.getenv('VULTR_INFERENCE_API_KEY','').strip())
    return [{'id':'local-docker','class':'sandbox','state':'operator-enabled' if os.getenv('CAPSULA_ALLOW_DIRECT_DOCKER')=='1' and docker_ready() else 'not-active','details':'Per-job Docker container; use a segregated host'},
        {'id':'remote-worker','class':'execution','state':'configured' if WORKER_ALLOWED and WORKER_TOKEN else 'not-active','details':'Leased, allowlisted worker endpoint with bounded execution'},
        {'id':'model-compatible','class':'inference','state':'configured-not-tested' if model['configured'] else 'not-active','details':model},
        {'id':'vultr','class':'cloud','state':'configured' if vultr_on else 'not-required','details':'Cloud Compute plus Serverless Inference when operator tokens are present. Live account data is /api/vultr/live.'},
        {'id':'phantom','class':'wallet','state':'browser-connect-only','details':'No custody or automatic spending'}]

@app.get('/api/vultr/live')
def vultr_live(authorization:str|None=Header(None)):
    authed(authorization)
    import vultr_cloud
    return vultr_cloud.snapshot()

@app.get('/api/templates')
def templates(authorization:str|None=Header(None)):
    authed(authorization);return core.TEMPLATES

@app.get('/api/project-files')
def project_files(workspace:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.list_files(db,workspace)

@app.post('/api/project-files')
def project_file_save(body:core.ProjectFile,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.put_file(db,body,vault,signer,audit_append)

@app.get('/api/project-files/read')
def project_file_read(workspace:str,path:str,revision:int|None=None,authorization:str|None=Header(None)):
    authed(authorization)
    core.ProjectFile(workspace=workspace,path=path,content='')
    with conn() as db:return core.read_file(db,workspace,path,vault,revision)

@app.get('/api/project-files/revisions')
def project_file_revisions(workspace:str,path:str,authorization:str|None=Header(None)):
    authed(authorization)
    core.ProjectFile(workspace=workspace,path=path,content='')
    with conn() as db:return core.list_revisions(db,workspace,path)

@app.get('/api/agents')
def agents(workspace:str|None=None,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.list_agents(db,workspace)

@app.post('/api/agents')
def agent_create(body:core.AgentInput,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.create_agent(db,body,signer,audit_append)

@app.get('/api/agents/{aid}')
def agent_detail(aid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.agent_row(db,aid)

@app.post('/api/agents/{aid}/disable')
def agent_disable(aid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        core.agent_row(db,aid)
        db.execute("UPDATE agent_profiles SET status='disabled' WHERE id=?",(aid,))
        audit_append(db,signer,'agent.disabled',aid,{'revoked':True})
    return {'id':aid,'status':'disabled'}

@app.get('/api/agent-runs')
def agent_runs(agent_id:str|None=None,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        if agent_id:rows=db.execute('SELECT id FROM agent_runs WHERE agent_id=? ORDER BY created DESC LIMIT 100',(agent_id,))
        else:rows=db.execute('SELECT id FROM agent_runs ORDER BY created DESC LIMIT 100')
        ids=[r['id'] for r in rows]
        return [core.run_row(db,rid,vault) for rid in ids]

class PlanRequest(BaseModel):
    goal:str=Field(min_length=10,max_length=3000)

@app.post('/api/agents/{aid}/plan')
def agent_plan(aid:str,body:PlanRequest,authorization:str|None=Header(None)):
    """Model proposes a bounded, reviewed run. It never executes directly."""
    authed(authorization)
    from inference import InferenceInput,infer
    with conn() as db:agent=core.agent_row(db,aid)
    if agent['status']!='active':raise HTTPException(409,'Agent disabled')
    if 'inference' not in agent['capabilities'] or not agent['model']:
        raise HTTPException(403,'Agent needs inference capability and an approved model')
    schema_prompt=(
        'Propose an executable CAPSULA workflow in strict JSON only: '
        '{"title":"...","steps":[{"kind":"python|inference|memory|artifact|browser|vision",'
        '"title":"...","code":"...","url":"...","prompt":"...",'
        '"content":"...","label":"...","name":"..."}]}. '
        'Do not include markdown. Use only permitted capabilities, never invent API keys or secrets, '
        'and do not include shells, network probes, money transfers, or filesystem escapes. '
        f'Capabilities: {core.serial(agent["capabilities"])}. Maximum steps: {agent["max_steps"]}. '
        'Every proposed step requires operator review. Goal: '+body.goal)
    with conn() as db:context=learning.context(db,agent,vault)
    compact={'objective':context['continuity']['objective'][:200],'notes':context['continuity']['notes'][:150],
        'recent_outcomes':context['continuity']['recent_outcomes'][-2:],
        'procedures':[{'path':s['path'],'content':s['content'][:300]} for s in context['verified_procedures'][:2]],
        'authority':'reference only; no additional capabilities'}
    schema_prompt+='\nPersistent agent continuity and verified procedures:\n'+core.serial(compact)
    response=infer(InferenceInput(model=agent['model'],system=('You are an execution-plan compiler. Role: '+agent['role']+' '+agent['instructions'])[:1000],prompt=schema_prompt[:5000],max_tokens=1024))
    raw=response['text'].strip()
    if raw.startswith('```'):
        parts=raw.split('\n',1)
        raw=parts[1].rsplit('```',1)[0].strip() if len(parts)>1 else ''
    try:
        draft=json.loads(raw)
        if not isinstance(draft,dict):raise ValueError('Plan must be an object')
        steps=core.AgentRunInput(title=draft['title'],steps=draft['steps'],approval_required=True)
    except (json.JSONDecodeError,ValueError,TypeError,KeyError) as exc:
        raise HTTPException(422,'Model returned an invalid structured plan; no action was executed') from exc
    with conn() as db:
        result=core.create_run(db,agent,steps,signer,vault,audit_append)
        audit_append(db,signer,'agent.plan_compiled',result['id'],{'goal_digest':'sha256:'+sha(body.goal.encode()),'model':agent['model'],'proposed_steps':len(steps.steps)})
    return {'status':'proposed-not-executed','provider':response['provider'],'model':response['model'],'run':result}

@app.post('/api/agents/{aid}/runs')
def agent_run_create(aid:str,body:core.AgentRunInput,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        a=core.agent_row(db,aid)
        return core.create_run(db,a,body,signer,vault,audit_append)

@app.get('/api/agent-runs/{rid}')
def agent_run_detail(rid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:return core.run_row(db,rid,vault)

@app.post('/api/agent-runs/{rid}/execute')
def agent_run_execute(rid:str,authorization:str|None=Header(None)):
    authed(authorization)
    with conn() as db:
        r=core.run_row(db,rid,vault)
        if r['state'] not in ('awaiting_approval','ready'):raise HTTPException(409,'Run already executed or blocked')
        if core.agent_row(db,r['agent_id'])['status']!='active':raise HTTPException(409,'Agent disabled; existing approvals do not reactivate it')
        if r['approval_id']:
            approval=db.execute('SELECT status FROM approvals WHERE id=?',(r['approval_id'],)).fetchone()
            if not approval or approval['status']!='approved':raise HTTPException(403,'Explicit operator approval required')
        updated=db.execute("UPDATE agent_runs SET state='running',updated=? WHERE id=? AND state=?",(now(),rid,r['state']))
        if updated.rowcount!=1:raise HTTPException(409,'Concurrent run transition')
        a=core.agent_row(db,r['agent_id']); steps=core.run_secrets(db,rid,vault)
        audit_append(db,signer,'agent.run_started',rid,{'agent_id':a['id'],'step_count':len(steps)})
    results=[];final='completed'
    from inference import InferenceInput, infer
    for ix,step in enumerate(steps):
        kind=step['kind'];entry={'index':ix,'title':step['title'],'kind':kind}
        with conn() as db:still_active=core.agent_row(db,a['id'])['status']=='active'
        if not still_active:
            entry.update(status='denied',reason='Agent disabled before this step')
            results.append(entry);final='denied';break
        try:
            if kind in ('python','browser'):
                mission=MissionInput(title=step['title'],kind=kind,code=step['code'],url=step['url'],selector=step['selector'])
                value=create(mission,authorization)
                observed=globals()['mission'](value['id'],authorization)
                out=observed['output']
                if not observed['proof_valid']:raise HTTPException(409,'Mission evidence failed verification')
                entry.update({'status':value['status'],'mission_id':value['id'],'receipt':value['receipt']['payload']['merkle_root'],
                    'verified':True,'output':str(out.get('stdout',''))[:9000],'stderr':str(out.get('stderr',''))[:4500],
                    'screenshot_b64':str(out.get('screenshot_b64',''))[:440000], 'image_mime':out.get('image_mime',''),
                    'exit_code':out.get('exit_code')})
            elif kind=='inference':
                response=infer(InferenceInput(model=a['model'],system=(a['role']+'\n'+a['instructions'])[:1000],prompt=step['prompt'].replace('{{last.output}}',str(results[-1].get('output',''))[:9000] if results else '')[:5000],max_tokens=512))
                entry.update({'status':'completed','model':response['model'],'output':response['text'],'usage':response['usage']})
            elif kind=='vision':
                from vision import review
                if not results or results[-1].get('kind')!='browser' or results[-1].get('status')!='completed' or not results[-1].get('screenshot_b64'):
                    raise HTTPException(409,'No successful browser screenshot to verify')
                response=review(a['model'],step['prompt'],results[-1]['screenshot_b64'],results[-1]['image_mime'])
                entry.update({'status':'completed','model':response['model'],'output':response['text'],
                              'verification':response['verification'],'usage':response['usage']})
            elif kind=='memory':
                resolved=step['content'].replace('{{last.output}}',results[-1].get('output','') if results else '')
                value=save_memory(MemoryInput(workspace=a['workspace'],label=step['label'] or step['title'],content=resolved,origin='agent:'+a['id']),authorization)
                entry.update({'status':'completed','memory_id':value['id']})
            elif kind=='artifact':
                file_name=step['name'] or 'agent-result.txt'
                resolved=step['content'].replace('{{last.output}}',results[-1].get('output','') if results else '')
                value=write_artifact(ArtifactInput(workspace=a['workspace'],name=file_name,mime='text/plain',content=resolved),authorization)
                entry.update({'status':'completed','artifact_id':value['id']})
            else:entry.update({'status':'denied','reason':'Unsupported capability'})
        except (HTTPException,ValueError) as exc:
            entry.update({'status':'failed','reason':str(exc.detail if isinstance(exc,HTTPException) else exc)[:300]})
        results.append(entry)
        if entry['status']!='completed':final='failed' if entry['status']=='failed' else 'denied';break
    with conn() as db:
        core.update_run(db,rid,final,results,vault,signer,audit_append)
        observed=learning.observe(db,a,rid,final,results,vault,signer,audit_append)
    return {'id':rid,'status':final,'steps_completed':sum(x['status']=='completed' for x in results),'steps_total':len(steps),'results':results,'learning':observed}


import sys as _sys
from platform_routes import register as _register_platform
_register_platform(_sys.modules[__name__])

# Challenge API is intentionally installed after all base routes and tables are initialized.
from challenge import bind as bind_challenge
bind_challenge(app)

# Scoped autonomy and agent-created capsule delegation.
from autonomy import bind as bind_autonomy
bind_autonomy(app)

from fleet_routes import bind as bind_fleet
bind_fleet(_sys.modules[__name__])

# Separate OIDC-verified, organization-scoped cluster API.
from cluster_api import bind as bind_cluster_api
bind_cluster_api(app)
