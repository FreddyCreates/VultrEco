"""Encrypted improvement capsules; execute candidates only through isolated workers.

Expected results stay on the controller, outside the candidate execution process.
No eval, exec, subprocess or dynamic import of candidate code occurs here.
"""
import json
import time
import uuid
from pathlib import PurePosixPath
from typing import Literal
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
import platform_core as core
from proof import sha, canon


class Case(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    name: str = Field(min_length=1, max_length=80)
    kind: Literal['regression','holdout']
    stdin: str = Field(default='', max_length=2000)
    stdout: str = Field(max_length=4000)
    exit_code: int = Field(default=0, ge=0, le=255)


class LabInput(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    agent_id: str = Field(pattern=r'^agt_[a-f0-9]{18}$')
    objective: str = Field(min_length=3, max_length=2000)
    request_key: str = Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
    source_paths: list[str] = Field(min_length=1, max_length=16)
    allowed_paths: list[str] = Field(min_length=1, max_length=16)
    entrypoint: str = Field(max_length=160)
    cases: list[Case] = Field(min_length=2, max_length=8)
    procedure_path: str | None = None
    max_attempts: int = Field(default=3, ge=1, le=8)
    seconds: int = Field(default=120, ge=15, le=600)
    lease_seconds: int = Field(default=3600, ge=60, le=7200)
    max_changed_bytes: int = Field(default=12000, ge=1, le=12000)


class EditInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    files: dict[str,str] = Field(min_length=1, max_length=16)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS improvement_labs(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,workspace TEXT NOT NULL,request_key TEXT UNIQUE NOT NULL,request_digest TEXT NOT NULL,status TEXT NOT NULL,sealed TEXT NOT NULL,created TEXT NOT NULL)')


def get(db, identity, vault):
    row = db.execute('SELECT * FROM improvement_labs WHERE id=?', (identity,)).fetchone()
    if not row: raise HTTPException(404, 'Improvement capsule not found')
    data = vault.open(json.loads(row['sealed']), 'improvement:'+identity)
    return {'id':identity,'agent_id':row['agent_id'],'workspace':row['workspace'],'status':row['status'],'created':row['created'],**data}


def save(db, value, vault):
    data = {k:v for k,v in value.items() if k not in ('id','agent_id','workspace','status','created')}
    db.execute('UPDATE improvement_labs SET status=?,sealed=? WHERE id=?',
        (value['status'],core.serial(vault.seal(data,'improvement:'+value['id'])),value['id']))


def active(value):
    if value['status'] in ('revoked','promoted','rolled_back'):
        raise HTTPException(409,'Improvement capsule is terminal')
    if time.time() >= value['expires']:
        raise HTTPException(409,'Improvement grant expired')


def create(db, body, vault, signer, audit):
    digest = sha(canon(body.model_dump()))
    old = db.execute('SELECT id,request_digest FROM improvement_labs WHERE request_key=?',(body.request_key,)).fetchone()
    if old:
        if old['request_digest'] != digest: raise HTTPException(409,'Improvement request key reused for another contract')
        return get(db,old['id'],vault)
    agent = core.agent_row(db,body.agent_id)
    if agent['status'] != 'active': raise HTTPException(409,'Agent disabled')
    paths = body.source_paths
    for path in paths:
        try:core.ProjectFile.safe_path(path)
        except ValueError as exc:raise HTTPException(422,'Invalid capsule source path') from exc
    if len(set(paths))!=len(paths) or not set(body.allowed_paths)<=set(paths) or len(set(body.allowed_paths))!=len(body.allowed_paths):
        raise HTTPException(422,'Writable paths must be unique frozen source paths')
    if body.entrypoint not in paths or not body.entrypoint.endswith('.py'):
        raise HTTPException(422,'A frozen Python entrypoint is required')
    if body.procedure_path and (body.procedure_path not in body.allowed_paths or not body.procedure_path.endswith('/SKILL.md')):
        raise HTTPException(422,'Procedure promotion must name an allowed SKILL.md')
    if {c.kind for c in body.cases}!={'regression','holdout'} or len({c.name for c in body.cases})!=len(body.cases):
        raise HTTPException(422,'Unique regression and distinguishing cases are required')
    files, revisions = {}, {}
    for path in paths:
        if any(p.startswith('.') for p in PurePosixPath(path).parts) or path.endswith(('.pem','.key')) or PurePosixPath(path).name in ('auth.json','credentials.json','oauth_creds.json'):
            raise HTTPException(422,'Credential paths cannot enter a test capsule')
        file = core.read_file(db,agent['workspace'],path,vault)
        files[path]=file['content'];revisions[path]=file['revision']
    if len(canon(files))>10000: raise HTTPException(422,'Clean test capsule source limit is 10 KB; use a dedicated VM for larger projects')
    identity='lab_'+uuid.uuid4().hex
    data={'contract':body.model_dump(),'baseline':files,'candidate':files.copy(),'baseline_revisions':revisions,
        'attempts':0,'expires':time.time()+body.lease_seconds,'trials':[],'candidate_hash':sha(canon(files)),
        'grant':{'schema':'capsula.improvement-grant.v1','objective_hash':sha(body.objective.encode()),
                 'contract_sha256':digest,'workspace':agent['workspace'],'agent_id':agent['id'],
                 'execution':'credential-free per-job worker; no controller execution'}}
    data['grant']['signature']=signer.sign(data['grant'])
    db.execute('INSERT INTO improvement_labs VALUES(?,?,?,?,?,?,?,?)',
        (identity,agent['id'],agent['workspace'],body.request_key,digest,'proposed',core.serial(vault.seal(data,'improvement:'+identity)),core.utc()))
    audit(db,signer,'improvement.granted',identity,{'agent_id':agent['id'],'contract_sha256':digest,'max_attempts':body.max_attempts,'scope':'frozen source paths only'})
    return get(db,identity,vault)


def edit(db, identity, body, vault, signer, audit):
    value=get(db,identity,vault);active(value)
    if value['status']=='evaluating':raise HTTPException(409,'Evaluation is running')
    if set(body.files)-set(value['contract']['allowed_paths']):raise HTTPException(403,'Candidate changes exceed the owner file grant')
    candidate={**value['candidate'],**body.files}
    if len(canon(candidate))>12000:raise HTTPException(422,'Candidate source exceeds clean worker capsule limit')
    changes=[p for p in candidate if candidate[p]!=value['baseline'][p]]
    if sum(max(len(candidate[p].encode()),len(value['baseline'][p].encode())) for p in changes)>value['contract']['max_changed_bytes']:
        raise HTTPException(422,'Candidate byte budget exceeded')
    value.update(candidate=candidate,candidate_hash=sha(canon(candidate)),status='proposed')
    save(db,value,vault);audit(db,signer,'improvement.candidate_saved',identity,{'candidate_sha256':value['candidate_hash']})
    return value


def program(files, entrypoint, stdin):
    # This string is never run on the controller. No expected answers are sent.
    code=('import os,sys,json,tempfile,pathlib,runpy,io\n'
        'files=json.loads('+repr(core.serial(files))+')\n'
        'with tempfile.TemporaryDirectory() as work:\n'
        ' for name,content in files.items():\n'
        '  p=pathlib.Path(work)/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content)\n'
        ' os.chdir(work);sys.path.insert(0,work)\n'
        ' sys.stdin=io.StringIO('+repr(stdin)+')\n'
        ' sys.argv=['+repr(entrypoint)+']\n'
        ' runpy.run_path('+repr(entrypoint)+',run_name="__main__")\n')
    if len(code)>16000:raise HTTPException(422,'Serialized trial exceeds isolated worker code limit')
    return code


def evaluate(identity, connect, vault, signer, audit, execute):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        value=get(db,identity,vault);active(value)
        if value['status']=='evaluating':raise HTTPException(409,'Evaluation already running; inspect before recovering')
        if value['attempts']>=value['contract']['max_attempts']:raise HTTPException(409,'Improvement attempt budget exhausted')
        if value['candidate']==value['baseline']:raise HTTPException(422,'No candidate changes')
        if core.agent_row(db,value['agent_id'])['status']!='active':raise HTTPException(409,'Agent disabled')
        value['attempts']+=1;value['status']='evaluating'
        trial={'attempt':value['attempts'],'candidate_hash':value['candidate_hash'],'cases':[],'status':'running'}
        value['trials'].append(trial);save(db,value,vault)
    deadline=min(value['expires'],time.time()+value['contract']['seconds'])
    try:
        for variant in ('baseline','candidate'):
            for case in value['contract']['cases']:
                with connect() as db:
                    current=get(db,identity,vault)
                    if current['status']!='evaluating':raise HTTPException(409,'Improvement revoked during evaluation')
                    if core.agent_row(db,value['agent_id'])['status']!='active':raise HTTPException(409,'Agent disabled during evaluation')
                if time.time()>=deadline:raise HTTPException(409,'Shared improvement deadline exhausted')
                observed=execute(program(value[variant],value['contract']['entrypoint'],case['stdin']), identity, variant, case['name'])
                executed=type(observed.get('exit_code')) is int and 0<=observed['exit_code']<124
                accepted=(observed.get('status') in ('completed','failed') and executed and observed.get('exit_code')==case['exit_code'] and observed.get('stdout')==case['stdout'])
                trial['cases'].append({'variant':variant,'name':case['name'],'kind':case['kind'],'passed':accepted,
                    'execution_status':observed.get('status'),'execution_observed':executed,'output_sha256':sha(str(observed.get('stdout','')).encode()),
                    'stderr_tail':str(observed.get('stderr',''))[-2000:],
                    'mission_id':observed.get('mission_id'),'exit_code':observed.get('exit_code')})
                with connect() as db:
                    current=get(db,identity,vault)
                    if current['status']!='evaluating':raise HTTPException(409,'Improvement revoked during evaluation')
                    value['trials'][-1]=trial;save(db,value,vault)
        checks=trial['cases']
        passed=(all(c['passed'] for c in checks if c['variant']=='candidate' or c['kind']=='regression')
            and any(not c['passed'] for c in checks if c['variant']=='baseline' and c['kind']=='holdout')
            and all(c['execution_observed'] and c['execution_status'] in ('completed','failed') for c in checks)
            and time.time()<deadline)
        value['status']='verified' if passed else 'rejected'
        trial['status']=value['status']
        if passed:value['verified_candidate_hash']=value['candidate_hash']
    except Exception as exc:
        value['status']='rejected';trial['status']='rejected';trial['reason']=str(exc.detail if isinstance(exc,HTTPException) else type(exc).__name__)[:300]
    with connect() as db:
        current=get(db,identity,vault)
        if current['status']=='revoked':
            value['status']='revoked';trial['status']='revoked'
        save(db,value,vault);audit(db,signer,'improvement.'+value['status'],identity,{'attempt':value['attempts'],'candidate_sha256':value['candidate_hash']})
    return value


def promote(db, identity, vault, signer, audit):
    value=get(db,identity,vault);active(value)
    if core.agent_row(db,value['agent_id'])['status']!='active':raise HTTPException(409,'Agent disabled')
    if value['status']!='verified' or value.get('verified_candidate_hash')!=sha(canon(value['candidate'])):
        raise HTTPException(409,'A matching passing candidate trial is required')
    for path, revision in value['baseline_revisions'].items():
        current=core.read_file(db,value['workspace'],path,vault)
        if current['revision']!=revision or current['content']!=value['baseline'][path]:
            raise HTTPException(409,'Live source changed since the baseline')
    promoted={}
    for path, content in value['candidate'].items():
        if content==value['baseline'][path]:continue
        result=core.put_file(db,core.ProjectFile(workspace=value['workspace'],path=path,content=content,expected_revision=value['baseline_revisions'][path]),vault,signer,audit)
        promoted[path]=result['revision']
    procedure=value['contract']['procedure_path']
    if procedure:
        active_path='skills/active/'+identity+'/SKILL.md'
        core.put_file(db,core.ProjectFile(workspace=value['workspace'],path=active_path,content=value['candidate'][procedure],expected_revision=0),vault,signer,audit)
        db.execute('INSERT INTO active_procedures VALUES(?,?,?,?)',
            (value['workspace'],active_path,sha(value['candidate'][procedure].encode()),identity))
        value['active_procedure_path']=active_path
    value.update(status='promoted',promoted_revisions=promoted,promoted_at=time.time());save(db,value,vault)
    audit(db,signer,'improvement.promoted',identity,{'candidate_sha256':value['candidate_hash'],'revisions':promoted})
    return value


def rollback(db, identity, vault, signer, audit):
    value=get(db,identity,vault)
    if value['status']!='promoted':raise HTTPException(409,'Only a promoted capsule can roll back')
    for path,revision in value['promoted_revisions'].items():
        current=core.read_file(db,value['workspace'],path,vault)
        if current['revision']!=revision or current['content']!=value['candidate'][path]:raise HTTPException(409,'Later work exists; rollback would overwrite it')
    for path,revision in value['promoted_revisions'].items():
        core.put_file(db,core.ProjectFile(workspace=value['workspace'],path=path,content=value['baseline'][path],expected_revision=revision),vault,signer,audit)
    db.execute('DELETE FROM active_procedures WHERE lab_id=?',(identity,))
    value.update(status='rolled_back',rolled_back_at=time.time());save(db,value,vault)
    audit(db,signer,'improvement.rolled_back',identity,{'prior_trial_preserved':True})
    return value
