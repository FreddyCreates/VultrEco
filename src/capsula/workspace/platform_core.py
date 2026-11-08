"""CAPSULA application layer: encrypted project files, agents, governed runs.

Uses application-owned storage and existing Ed25519 audit; no cloud assumptions.
This is a single-admin operator product, NOT a multi-tenant security design.
"""
import json, re, uuid, hashlib, datetime
from typing import Literal
from pydantic import BaseModel, Field, field_validator
from fastapi import HTTPException

CAPS={'python','browser','vision','inference','memory','artifact'}
PATH_RE=re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9._/\-]{0,159}$')

class ProjectFile(BaseModel):
    workspace:str=Field(min_length=2,max_length=64,pattern=r'^[a-z][a-z0-9-]+$')
    path:str=Field(min_length=1,max_length=160)
    content:str=Field(max_length=100_000)
    expected_revision:int|None=Field(default=None,ge=0)
    @field_validator('path')
    @classmethod
    def safe_path(cls,v):
        if not PATH_RE.fullmatch(v) or any(p in ('.','..','') for p in v.split('/')) or v.endswith('/') or v.startswith('.git/'):
            raise ValueError('Invalid project-relative path')
        return v

class AgentInput(BaseModel):
    workspace:str=Field(pattern=r'^[a-z][a-z0-9-]{1,63}$')
    name:str=Field(min_length=2,max_length=80)
    role:str=Field(default='Engineering assistant',min_length=3,max_length=120)
    instructions:str=Field(default='',max_length=3000)
    capabilities:list[Literal['python','browser','vision','inference','memory','artifact']]=Field(default_factory=lambda:['python','inference'],max_length=6)
    max_steps:int=Field(default=4,ge=1,le=12)
    model:str=Field(default='',max_length=120)

class Step(BaseModel):
    kind:Literal['python','browser','vision','inference','memory','artifact']
    title:str=Field(min_length=2,max_length=100)
    code:str=Field(default='',max_length=16000)
    url:str=Field(default='',max_length=300)
    selector:str=Field(default='',max_length=200)
    prompt:str=Field(default='',max_length=5000)
    content:str=Field(default='',max_length=20000)
    name:str=Field(default='',max_length=100)
    label:str=Field(default='',max_length=100)
    @field_validator('url')
    @classmethod
    def safe_url(cls,v):
        if v and not v.startswith('https://'):raise ValueError('Browser URL must use HTTPS')
        return v

class AgentRunInput(BaseModel):
    title:str=Field(min_length=3,max_length=120)
    steps:list[Step]=Field(min_length=1,max_length=12)
    approval_required:bool=True

def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS project_files
        (workspace TEXT NOT NULL, path TEXT NOT NULL, revision INTEGER NOT NULL,
         digest TEXT NOT NULL, sealed TEXT NOT NULL, updated TEXT NOT NULL,
         PRIMARY KEY (workspace,path,revision))''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_profiles
        (id TEXT PRIMARY KEY,workspace TEXT NOT NULL,name TEXT NOT NULL,role TEXT NOT NULL,
         instructions TEXT NOT NULL,capabilities TEXT NOT NULL,max_steps INTEGER NOT NULL,
         model TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS agent_runs
        (id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,workspace TEXT NOT NULL,title TEXT NOT NULL,
         state TEXT NOT NULL,steps TEXT NOT NULL,results TEXT NOT NULL,approval_id TEXT NOT NULL,
         created TEXT NOT NULL,updated TEXT NOT NULL)''')
    db.execute('CREATE INDEX IF NOT EXISTS idx_agents_ws ON agent_profiles(workspace)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_runs_agent ON agent_runs(agent_id,created)')
    db.execute('CREATE INDEX IF NOT EXISTS idx_files_ws ON project_files(workspace,path)')

def utc():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def serial(x):return json.dumps(x,sort_keys=True,separators=(',',':'))
def ensure_workspace(db,slug):
    if not db.execute('SELECT 1 FROM workspaces WHERE slug=?',(slug,)).fetchone():raise HTTPException(404,'Workspace not found')

def put_file(db,body,vault,signer,audit_append):
    ensure_workspace(db,body.workspace)
    prior=db.execute('SELECT revision FROM project_files WHERE workspace=? AND path=? ORDER BY revision DESC LIMIT 1',(body.workspace,body.path)).fetchone()
    current=prior['revision'] if prior else 0
    if body.expected_revision is not None and body.expected_revision!=current:raise HTTPException(409,{'revision_conflict':True,'actual_revision':current})
    nextv=current+1
    digest=hashlib.sha256(body.content.encode('utf-8')).hexdigest()
    secret=vault.seal({'content':body.content,'digest':digest},f'file:{body.workspace}:{body.path}:{nextv}')
    db.execute('INSERT INTO project_files VALUES(?,?,?,?,?,?)',(body.workspace,body.path,nextv,digest,serial(secret),utc()))
    audit_append(db,signer,'project.file_saved',f'{body.workspace}/{body.path}',{'revision':nextv,'sha256':digest})
    return {'workspace':body.workspace,'path':body.path,'revision':nextv,'digest':'sha256:'+digest,'sealed':True}

def read_file(db,workspace,path,vault,revision=None):
    if revision is None:r=db.execute('SELECT * FROM project_files WHERE workspace=? AND path=? ORDER BY revision DESC LIMIT 1',(workspace,path)).fetchone()
    else:r=db.execute('SELECT * FROM project_files WHERE workspace=? AND path=? AND revision=?',(workspace,path,revision)).fetchone()
    if not r:raise HTTPException(404,'File not found')
    data=vault.open(json.loads(r['sealed']),f'file:{workspace}:{path}:{r["revision"]}')
    if hashlib.sha256(data['content'].encode()).hexdigest()!=r['digest'] or data['digest']!=r['digest']:
        raise HTTPException(409,'Project file integrity failure')
    return {'workspace':workspace,'path':path,'revision':r['revision'],'updated':r['updated'],'digest':'sha256:'+r['digest'],'content':data['content'],'verified':True}

def list_files(db,workspace):
    ensure_workspace(db,workspace)
    return [dict(r) for r in db.execute('''SELECT f.workspace,f.path,f.revision,f.digest,f.updated FROM project_files f
        JOIN (SELECT path,MAX(revision) rev FROM project_files WHERE workspace=? GROUP BY path) latest
        ON latest.path=f.path AND latest.rev=f.revision WHERE f.workspace=? ORDER BY f.path''',(workspace,workspace))]

def list_revisions(db,workspace,path):
    return [dict(r) for r in db.execute('SELECT revision,digest,updated FROM project_files WHERE workspace=? AND path=? ORDER BY revision DESC',(workspace,path))]

def create_agent(db,body,signer,audit_append):
    ensure_workspace(db,body.workspace)
    aid='agt_'+uuid.uuid4().hex[:18];stamp=utc()
    vals=(aid,body.workspace,body.name,body.role,body.instructions,serial(list(dict.fromkeys(body.capabilities))),body.max_steps,body.model,'active',stamp)
    db.execute('INSERT INTO agent_profiles VALUES(?,?,?,?,?,?,?,?,?,?)',vals)
    audit_append(db,signer,'agent.created',aid,{'workspace':body.workspace,'capabilities':body.capabilities,'max_steps':body.max_steps})
    return {'id':aid,'workspace':body.workspace,'name':body.name,'role':body.role,'capabilities':body.capabilities,'model':body.model,'status':'active','max_steps':body.max_steps,'created':stamp}

def agent_row(db,aid):
    row=db.execute('SELECT * FROM agent_profiles WHERE id=?',(aid,)).fetchone()
    if not row:raise HTTPException(404,'Agent missing')
    x=dict(row);x['capabilities']=json.loads(x['capabilities']);return x

def list_agents(db,workspace=None):
    rows=db.execute('SELECT * FROM agent_profiles WHERE workspace=? ORDER BY created DESC',(workspace,)) if workspace else db.execute('SELECT * FROM agent_profiles ORDER BY created DESC')
    return [{**dict(r),'capabilities':json.loads(r['capabilities'])} for r in rows]

def create_run(db,agent,body,signer,vault,audit_append):
    if agent['status']!='active':raise HTTPException(409,'Agent disabled')
    if len(body.steps)>agent['max_steps']:raise HTTPException(422,'Exceeds agent step limit')
    if any(s.kind not in agent['capabilities'] for s in body.steps):raise HTTPException(403,'Agent capability not granted')
    for i,s in enumerate(body.steps):
        if s.kind=='vision' and (i==0 or body.steps[i-1].kind!='browser'):
            raise HTTPException(422,'Vision verification must immediately follow the browser screenshot')
        if s.kind=='python' and not s.code.strip():raise HTTPException(422,'Python step requires code')
        if s.kind=='browser' and not s.url.startswith('https://'):raise HTTPException(422,'Browser step requires HTTPS URL')
        if s.kind in ('inference','vision') and not (s.prompt.strip() and agent['model']):raise HTTPException(422,'Model step requires prompt and configured agent model')
        if s.kind in ('memory','artifact') and not s.content.strip():raise HTTPException(422,'Write step requires content')
    rid='run_'+uuid.uuid4().hex[:20];ts=utc()
    requires=body.approval_required or any(s.kind in ('python','browser') for s in body.steps)
    approval=''
    if requires:
        approval='apr_'+uuid.uuid4().hex[:20]
        db.execute('INSERT INTO approvals VALUES(?,?,?,?,?,?,?)',(approval,'tool',agent['workspace'],serial({'run_id':rid,'agent_id':agent['id'],'steps':[s.kind for s in body.steps]}),'pending',ts,''))
        audit_append(db,signer,'approval.requested',approval,{'run_id':rid,'agent_id':agent['id']})
    sealed=vault.seal({'steps':[x.model_dump() for x in body.steps]},'agent-run:'+rid+':steps')
    db.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?,?,?)',(rid,agent['id'],agent['workspace'],body.title,'awaiting_approval' if requires else 'ready',serial(sealed),serial(vault.seal({'steps':[]},'agent-run:'+rid+':results')),approval,ts,ts))
    audit_append(db,signer,'agent.run_created',rid,{'agent_id':agent['id'],'approval_id':approval,'step_count':len(body.steps)})
    return {'id':rid,'agent_id':agent['id'],'workspace':agent['workspace'],'title':body.title,'status':'awaiting_approval' if requires else 'ready','approval_id':approval,'steps':[{'index':i,'kind':s.kind,'title':s.title} for i,s in enumerate(body.steps)]}

def run_row(db,rid,vault,reveal=False):
    r=db.execute('SELECT * FROM agent_runs WHERE id=?',(rid,)).fetchone()
    if not r:raise HTTPException(404,'Run missing')
    data=dict(r)
    steps=vault.open(json.loads(r['steps']),'agent-run:'+rid+':steps')['steps']
    results=vault.open(json.loads(r['results']),'agent-run:'+rid+':results')['steps']
    data.pop('steps');data.pop('results')
    data['steps']=[{**({'code':s['code'],'prompt':s['prompt'],'content':s['content']} if reveal else {}),'index':i,'kind':s['kind'],'title':s['title']} for i,s in enumerate(steps)]
    data['results']=results
    return data

def run_secrets(db,rid,vault):
    r=db.execute('SELECT * FROM agent_runs WHERE id=?',(rid,)).fetchone()
    if not r:raise HTTPException(404,'Run missing')
    return vault.open(json.loads(r['steps']),'agent-run:'+rid+':steps')['steps']

def update_run(db,rid,state,results,vault,signer,audit_append):
    enc=vault.seal({'steps':results},'agent-run:'+rid+':results')
    db.execute('UPDATE agent_runs SET state=?,updated=?,results=? WHERE id=?',(state,utc(),serial(enc),rid))
    audit_append(db,signer,'agent.run_'+state,rid,{'step_count':len(results),'last_status':results[-1].get('status') if results else None})

TEMPLATES=[
 {'name':'Code verification','description':'Run a bounded Python verification script in an isolated runtime','capabilities':['python']},
 {'name':'Research brief','description':'Ask your configured model to produce a sourced research plan; model output is not externally verified','capabilities':['inference']},
 {'name':'Page inspection','description':'Inspect an approved HTTPS page in a separate browser worker','capabilities':['browser']},
 {'name':'Persistent notebook','description':'Create encrypted notes in a workspace with signed audit records','capabilities':['memory']},
 {'name':'Artifact publication','description':'Store a versioned output as an encrypted, auditable artifact','capabilities':['artifact']}
]
