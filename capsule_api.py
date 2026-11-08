"""Real user -> disposable computer -> verified downloadable artifact workflow.

Single-operator CAPSULA lane; not the tenant API. Users and agents must have
operator authority and agents must hold explicit Python/workspace capability.
"""
import base64,hashlib,json,mimetypes,uuid
from fastapi import Header,HTTPException
from fastapi.responses import Response
from pydantic import BaseModel,Field
import platform_core as core
from capsule_runtime import safe_name,MAX_INPUT_FILES,MAX_INPUT_TOTAL,MAX_FILE,MAX_OUTPUT_TOTAL

class CapsuleDraft(BaseModel):
    workspace:str=Field(pattern=r'^[a-z][a-z0-9-]{1,63}$')
    title:str=Field(min_length=3,max_length=120)
    code:str=Field(min_length=1,max_length=16000)
    input_paths:list[str]=Field(default_factory=list,max_length=MAX_INPUT_FILES)
    agent_id:str=Field(default='',max_length=90)

def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS capsule_tasks(
        id TEXT PRIMARY KEY,workspace TEXT NOT NULL,agent_id TEXT NOT NULL,
        title TEXT NOT NULL,state TEXT NOT NULL,code_sealed TEXT NOT NULL,
        result_sealed TEXT NOT NULL,worker_id TEXT NOT NULL DEFAULT '',
        attempts INTEGER NOT NULL DEFAULT 0,created TEXT NOT NULL,updated TEXT NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_capsule_tasks_ws ON capsule_tasks(workspace,created)")

def detail(m,db,identity):
    row=db.execute("SELECT * FROM capsule_tasks WHERE id=?",(identity,)).fetchone()
    if row is None:raise HTTPException(404,'Capsule not found')
    result=m.vault.open(json.loads(row['result_sealed']),'capsule:'+identity+':result')
    return {'id':identity,'workspace':row['workspace'],'agent_id':row['agent_id'],
            'title':row['title'],'state':row['state'],'worker_id':row['worker_id'],
            'attempts':row['attempts'],'created':row['created'],'updated':row['updated'],
            'cleanup':result.get('cleanup','not-started'),
            'stdout':result.get('stdout',''),'stderr':result.get('stderr',''),
            'reason':result.get('reason',''),'exit_code':result.get('exit_code'),
            'isolation':result.get('isolation','not-verified'),
            'artifacts':[{'name':p,'bytes':a['bytes'],'sha256':a['sha256'],
                'url':'/api/capsules/'+identity+'/outputs/'+p}
                for p,a in result.get('artifacts',{}).items()]}

def bind(m):
    with m.conn() as db:schema(db)
    app=m.app
    @app.post('/api/capsules',status_code=201)
    def create(body:CapsuleDraft,authorization:str|None=Header(None)):
        m.authed(authorization)
        if not body.code.strip():raise HTTPException(422,'Code must be nonempty')
        if len(set(body.input_paths))!=len(body.input_paths) or any(not safe_name(x) for x in body.input_paths):
            raise HTTPException(422,'Unsafe or repeated input paths')
        cid='caps_'+uuid.uuid4().hex[:20]
        with m.conn() as db:
            core.ensure_workspace(db,body.workspace)
            if body.agent_id:
                agent=core.agent_row(db,body.agent_id)
                if agent['workspace']!=body.workspace or agent['status']!='active' or 'python' not in agent['capabilities']:
                    raise HTTPException(403,'Agent lacks authorized workspace/capsule capability')
            inputs={};total=0
            for path in body.input_paths:
                file=core.read_file(db,body.workspace,path,m.vault)
                raw=file['content'].encode('utf-8')
                total+=len(raw)
                if len(raw)>MAX_FILE or total>MAX_INPUT_TOTAL:raise HTTPException(422,'Input data limit exceeded')
                inputs[path]=base64.b64encode(raw).decode('ascii')
            secret=m.vault.seal({'code':body.code,'inputs':inputs},'capsule:'+cid+':input')
            initial=m.vault.seal({'artifacts':{},'cleanup':'not-started'},'capsule:'+cid+':result')
            ts=m.now()
            db.execute('INSERT INTO capsule_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (cid,body.workspace,body.agent_id,body.title,'draft',m.canonical(secret),
                 m.canonical(initial),'',0,ts,ts))
            m.audit_append(db,m.signer,'capsule.created',cid,
                           {'workspace':body.workspace,'agent_id':body.agent_id,'input_paths':body.input_paths})
            return detail(m,db,cid)

    @app.get('/api/capsules')
    def list_capsules(workspace:str|None=None,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            if workspace:
                core.ensure_workspace(db,workspace)
                records=db.execute('SELECT id FROM capsule_tasks WHERE workspace=? ORDER BY created DESC LIMIT 100',(workspace,))
            else:records=db.execute('SELECT id FROM capsule_tasks ORDER BY created DESC LIMIT 100')
            return [detail(m,db,row['id']) for row in records]

    @app.get('/api/capsules/{identity}')
    def get_capsule(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:return detail(m,db,identity)

    @app.post('/api/capsules/{identity}/execute')
    def execute(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            row=db.execute('SELECT * FROM capsule_tasks WHERE id=?',(identity,)).fetchone()
            if row is None:raise HTTPException(404,'Capsule not found')
            if row['state']!='draft':raise HTTPException(409,'Capsule already launched; create a new capsule')
            payload=m.vault.open(json.loads(row['code_sealed']),'capsule:'+identity+':input')
        with m.conn() as db:
            lease=m.fleet.reserve(db,'python',identity,lease_seconds=90)
        if not lease:raise HTTPException(503,'No isolated worker capacity. Capsule remains a draft')
        worker=lease['worker'];status='failed'
        result={'status':'failed','reason':'Isolated worker request or evidence failed',
                'cleanup':'not-verified','artifacts':{},'stdout':'','stderr':''}
        try:
            if not m.WORKER_TOKEN or worker['endpoint'] not in m.WORKER_ALLOWED:
                raise ValueError('Worker endpoint not approved')
            with m.conn() as db:
                updated=db.execute("""UPDATE capsule_tasks SET state='running',
                    worker_id=?,attempts=attempts+1,updated=?
                    WHERE id=? AND state='draft'""",(worker['id'],m.now(),identity))
                if updated.rowcount!=1:raise HTTPException(409,'Capsule already claimed')
                m.audit_append(db,m.signer,'capsule.dispatched',identity,{'worker_id':worker['id']})
            with m.httpx.Client(timeout=60,follow_redirects=False,trust_env=False) as client:
                reply=client.post(worker['endpoint']+'/capsules/execute',
                    json={'code':payload['code'],'inputs':payload['inputs']},
                    headers={'Authorization':'Bearer '+m.WORKER_TOKEN})
                reply.raise_for_status();body=reply.json()
            candidate=body['result']
            expected='sha256:'+hashlib.sha256(m.canonical(candidate).encode()).hexdigest()
            if body.get('digest')!=expected:raise ValueError('Worker proof digest mismatch')
            if candidate.get('status') not in ('completed','failed','denied'):
                raise ValueError('Invalid worker status')
            if candidate.get('status')=='completed' and candidate.get('cleanup')!='verified-destroyed':
                raise ValueError('Disposable computer destruction not verified')
            artifacts=candidate.get('artifacts',{})
            if not isinstance(artifacts,dict) or len(artifacts)>16:raise ValueError('Artifact envelope invalid')
            total=0
            for name,item in artifacts.items():
                if not safe_name(name) or not isinstance(item,dict):raise ValueError('Unsafe artifact')
                raw=base64.b64decode(item['base64'],validate=True);total+=len(raw)
                if (len(raw)>MAX_FILE or total>MAX_OUTPUT_TOTAL or item['bytes']!=len(raw)
                        or item['sha256']!=hashlib.sha256(raw).hexdigest()):
                    raise ValueError('Artifact integrity/size mismatch')
            result=candidate;status=result['status']
        except HTTPException:
            raise
        except (m.httpx.HTTPError,ValueError,KeyError,TypeError,OverflowError):
            pass
        finally:
            with m.conn() as db:m.fleet.complete(db,lease['lease_id'],status=='completed')
        sealed=m.vault.seal(result,'capsule:'+identity+':result')
        with m.conn() as db:
            db.execute('UPDATE capsule_tasks SET state=?,result_sealed=?,updated=? WHERE id=?',
                       (status,m.canonical(sealed),m.now(),identity))
            m.audit_append(db,m.signer,'capsule.finished',identity,{
                'worker_id':worker['id'],'status':status,'cleanup':result.get('cleanup'),
                'artifacts':{k:v['sha256'] for k,v in result.get('artifacts',{}).items()}})
            return detail(m,db,identity)

    @app.get('/api/capsules/{identity}/outputs/{filename:path}')
    def download(identity:str,filename:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        if not safe_name(filename):raise HTTPException(404,'Output not available')
        with m.conn() as db:
            row=db.execute('SELECT * FROM capsule_tasks WHERE id=?',(identity,)).fetchone()
            if not row or row['state']!='completed':raise HTTPException(404,'Output not available')
            data=m.vault.open(json.loads(row['result_sealed']),'capsule:'+identity+':result')
            item=(data.get('artifacts') or {}).get(filename)
            if not item:raise HTTPException(404,'Output not available')
            try:raw=base64.b64decode(item['base64'],validate=True)
            except ValueError as exc:raise HTTPException(409,'Artifact encoding error') from exc
            if hashlib.sha256(raw).hexdigest()!=item['sha256']:
                raise HTTPException(409,'Artifact integrity mismatch')
            mime=mimetypes.guess_type(filename)[0] or 'application/octet-stream'
            return Response(content=raw,media_type=mime,headers={
                'Content-Disposition':'attachment; filename="'+filename.split('/')[-1]+'"',
                'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store',
                'X-Capsula-SHA256':item['sha256']})

    @app.delete('/api/capsules/{identity}')
    def discard(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            row=db.execute('SELECT state FROM capsule_tasks WHERE id=?',(identity,)).fetchone()
            if row is None:raise HTTPException(404,'Capsule not found')
            if row['state']=='running':raise HTTPException(409,'Running capsule cannot be discarded')
            db.execute('DELETE FROM capsule_tasks WHERE id=?',(identity,))
            m.audit_append(db,m.signer,'capsule.discarded',identity,{'prior_state':row['state']})
            return {'id':identity,'discarded':True,'worker_environment':'ephemeral'}
