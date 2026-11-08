"""Connect persistent computers, bounded RAH, continuity and clean improvement tests."""
import json
import time
import uuid
import hashlib
import sqlite3
import httpx
from fastapi import Header, HTTPException
from pydantic import BaseModel, Field
import platform_core as core
import learning
import computers
import improvement_lab as lab
from proof import sha, canon


def register(m):
    app=m.app
    with m.conn() as db:
        learning.schema(db);computers.schema(db);lab.schema(db)

    @app.get('/api/workspaces/{workspace}/lane')
    def lane(workspace:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            core.ensure_workspace(db,workspace)
            row=db.execute('SELECT * FROM workspace_lanes WHERE workspace=?',(workspace,)).fetchone()
        return dict(row) if row else {'workspace':workspace,'lane':'personal','organization':'private','tenancy':'single-operator; not tenant isolation'}

    @app.post('/api/workspaces/{workspace}/lane')
    def set_lane(workspace:str,body:learning.LaneInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            core.ensure_workspace(db,workspace)
            db.execute('INSERT OR REPLACE INTO workspace_lanes VALUES(?,?,?)',(workspace,body.lane,body.organization))
            m.audit_append(db,m.signer,'workspace.lane_set',workspace,body.model_dump())
        return {'workspace':workspace,**body.model_dump(),'tenancy':'single-operator; not tenant isolation'}

    @app.get('/api/agents/{aid}/continuity')
    def continuity(aid:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:return learning.session(db,aid,m.vault)

    @app.post('/api/agents/{aid}/continuity')
    def update_continuity(aid:str,body:learning.SessionInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            return learning.save_session(db,aid,body,m.vault,m.signer,m.audit_append)

    @app.get('/api/agents/{aid}/learning')
    def agent_learning(aid:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:return learning.summary(db,aid,m.vault)

    @app.post('/api/agents/{aid}/curiosity')
    def curiosity(aid:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            agent=core.agent_row(db,aid)
            if agent['status']!='active':raise HTTPException(409,'Agent disabled')
            state=learning.session(db,aid,m.vault)
            failed=next((o for o in reversed(state['recent_outcomes']) if o['status']!='completed'),None)
            objective=('Reproduce and diagnose '+failed['run_id']+' using a frozen failing case' if failed else
                'Find one measurable improvement for '+(state['objective'] or agent['role'])+'; preserve a baseline and distinguishing test')
            return learning.propose(db,agent,'experiment',{'objective':objective[:2000],'budget_suggestion':{'attempts':3,'seconds':120},
                'execution':'not started; an owner grant is required','basis':'observed failure' if failed else 'owner objective'},m.vault,m.signer,m.audit_append)

    @app.get('/api/computers')
    def list_computers(authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:rows=[dict(r) for r in db.execute('SELECT * FROM agent_computers ORDER BY created DESC')]
        return {'host_configured':computers.configured()['configured'],'computers':rows,'credentials':'host-side only; subscription sign-in stays in each VM'}

    @app.post('/api/agents/{aid}/computer')
    def provision(aid:str,body:computers.ComputerInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            agent=core.agent_row(db,aid)
            if agent['status']!='active':raise HTTPException(409,'Agent disabled')
            if db.execute('SELECT 1 FROM agent_computers WHERE agent_id=?',(aid,)).fetchone():raise HTTPException(409,'Agent already has a computer')
        remote=computers.request('POST','/api/agents',{'name':agent['name'][:60],'request_key':'capsula-computer-'+aid,**body.model_dump()})
        with m.conn() as db:return computers.bind(db,agent,remote,m.signer,m.audit_append)

    @app.post('/api/agents/{aid}/computer/bind')
    def bind(aid:str,body:computers.BindInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        state=computers.request('GET','/api/state')
        remote=next((a for a in state.get('agents',[]) if a.get('id')==body.remote_id),None)
        if not remote:raise HTTPException(404,'VM host has no such computer')
        with m.conn() as db:
            return computers.bind(db,core.agent_row(db,aid),remote,m.signer,m.audit_append)

    @app.get('/api/agents/{aid}/computer')
    def computer_detail(aid:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:binding=computers.binding(db,aid)
        state=computers.request('GET','/api/state')
        remote=next((a for a in state.get('agents',[]) if a.get('id')==binding['remote_id']),None)
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            for job in state.get('jobs',[]):
                if job.get('agent_id')!=binding['remote_id'] or job.get('status') not in ('completed','failed','cancelled','lost'):
                    continue
                identity=job.get('id','')
                if not __import__('re').fullmatch('[a-f0-9]{32}',identity):continue
                agent=core.agent_row(db,aid)
                entry={'title':'Dedicated VM task outcome','kind':'vm-work','status':job['status'],'remote_job_id':identity,
                    'artifact_hashes':[a.get('sha256') for a in job.get('artifacts',[])],
                    'acceptance':job.get('acceptance_result',{}).get('passed',False)}
                learning.observe(db,agent,'dot-'+identity,job['status'],[entry],m.vault,m.signer,m.audit_append)
        jobs=[{k:j[k] for k in ('id','status','response','error','checkpoint_id','acceptance_result','receipt') if k in j}
              for j in state.get('jobs',[]) if j.get('agent_id')==binding['remote_id']][:20]
        return {'binding':binding,'computer':remote,'jobs':jobs,'sign_in':'Use the official CLI inside this VM; no browser-held provider credentials',
                'login_command':'sudo python3 -m dot login --config config.json --agent '+binding['remote_id']}

    @app.post('/api/agents/{aid}/computer/sync')
    def sync_computer(aid:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            agent=core.agent_row(db,aid)
            if agent['status']!='active':raise HTTPException(409,'Agent disabled')
            bound=computers.binding(db,aid)
            files={file['path']:core.read_file(db,agent['workspace'],file['path'],m.vault)['content'] for file in core.list_files(db,agent['workspace'])}
        if not files:raise HTTPException(422,'Project has no files to sync')
        if sum(len(v.encode()) for v in files.values())>96*1024:raise HTTPException(422,'Project exceeds the 96 KiB API sync limit; use the computer terminal/SCP')
        result=computers.request('POST','/api/agents/'+bound['remote_id']+'/workspace',{'files':files})
        expected={p:sha(v.encode()) for p,v in files.items()}
        if result.get('sha256')!=expected:raise HTTPException(502,'Computer import evidence does not match project bytes')
        with m.conn() as db:m.audit_append(db,m.signer,'agent.workspace_synced',aid,{'files':len(files),'snapshot_sha256':sha(canon(expected)),'checkpoint_id':result.get('checkpoint_id')})
        return result

    class ComputerTask(BaseModel):
        prompt:str=Field(min_length=1,max_length=24000)
        timeout:int=Field(default=300,ge=30,le=3600)
        mode:str=Field(default='work',pattern=r'^(work|plan)$')
        request_key:str=Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')
        acceptance:dict=Field(default_factory=dict)

    @app.post('/api/agents/{aid}/computer/tasks')
    def computer_task(aid:str,body:ComputerTask,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            agent=core.agent_row(db,aid)
            if agent['status']!='active':raise HTTPException(409,'Agent disabled')
            bound=computers.binding(db,aid);context=learning.context(db,agent,m.vault)
        payload=body.model_dump()
        payload['prompt']+='\n\nCAPSULA continuity (reference, no additional authority):\n'+core.serial(context)[:4000]
        result=computers.request('POST','/api/agents/'+bound['remote_id']+'/tasks',payload)
        with m.conn() as db:m.audit_append(db,m.signer,'agent.vm_task_submitted',aid,{'request_key':body.request_key,'remote_job_id':result.get('id')})
        return result

    @app.post('/api/rah/missions')
    def grant_rah(body:computers.RahGrant,authorization:str|None=Header(None)):
        m.authed(authorization)
        digest=sha(canon(body.model_dump()))
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT id,digest FROM rah_missions WHERE request_key=?',(body.request_key,)).fetchone()
            if old:
                if old['digest']!=digest:raise HTTPException(409,'RAH request key reused for a different grant')
                prior=computers.mission_row(db,old['id'],m.vault)
                if prior['state']!='dispatching':return prior
                compiled=prior['grant']['compiled'];identity=prior['id']
            else:
                compiled=computers.compile_grant(db,body,lambda aid:learning.context(db,core.agent_row(db,aid),m.vault))
                identity='rah_'+uuid.uuid4().hex
                grant={'schema':'capsula.rah-work-grant.v1','principal':'owner','workspace':body.workspace,
                    'objective_hash':sha(body.objective.encode()),'contract_sha256':digest,'compiled':compiled,
                    'authority':'bounded recursive execution; no infrastructure expansion'}
                grant['signature']=m.signer.sign(grant)
                db.execute('INSERT INTO rah_missions VALUES(?,?,?,?,?,?,?,?)',(identity,body.workspace,body.request_key,digest,'','dispatching',core.serial(m.vault.seal(grant,'rah:'+identity)),core.utc()))
                m.audit_append(db,m.signer,'rah.granted',identity,{'workspace':body.workspace,'contract_sha256':digest,'children':body.max_children})
        # The Dot host persists the same idempotency key with the work tree.
        remote=computers.request('POST','/api/missions',compiled)
        remote_id=remote.get('id','')
        import re
        if not re.fullmatch('[a-f0-9]{32}',remote_id):raise HTTPException(502,'VM host returned an invalid work-tree identity')
        with m.conn() as db:
            db.execute('UPDATE rah_missions SET remote_id=?,state=? WHERE id=?',(remote_id,remote['status'],identity))
            return {**computers.mission_row(db,identity,m.vault),'tree':remote}

    @app.get('/api/rah/missions')
    def rah_list(workspace:str|None=None,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            rows=db.execute('SELECT id FROM rah_missions WHERE workspace=? ORDER BY created DESC LIMIT 100',(workspace,)) if workspace else db.execute('SELECT id FROM rah_missions ORDER BY created DESC LIMIT 100')
            return [computers.mission_row(db,r['id'],m.vault) for r in rows]

    @app.get('/api/rah/missions/{identity}')
    def rah_detail(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:value=computers.mission_row(db,identity,m.vault)
        if not value['remote_id']:return value
        remote=computers.request('GET','/api/state')
        tree=next((x for x in remote.get('missions',[]) if x.get('id')==value['remote_id']),None)
        if tree:
            with m.conn() as db:db.execute('UPDATE rah_missions SET state=? WHERE id=?',(tree['status'],identity))
            value['state']=tree['status']
        return {**value,'tree':tree}

    @app.post('/api/rah/missions/{identity}/cancel')
    def rah_cancel(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            value=computers.mission_row(db,identity,m.vault)
            if not value['remote_id']:raise HTTPException(409,'Dispatch outcome is unresolved; reconcile before cancellation')
            db.execute('UPDATE rah_missions SET state=? WHERE id=?',('cancelling',identity))
            m.audit_append(db,m.signer,'rah.revoked',identity,{'scope':'entire work tree'})
        return computers.request('POST','/api/missions/'+value['remote_id']+'/cancel',{})

    @app.post('/api/improvements')
    def improvement_create(body:lab.LabInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE');return lab.create(db,body,m.vault,m.signer,m.audit_append)

    @app.get('/api/improvements')
    def improvements(agent_id:str|None=None,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            rows=db.execute('SELECT id FROM improvement_labs WHERE agent_id=? ORDER BY created DESC LIMIT 100',(agent_id,)) if agent_id else db.execute('SELECT id FROM improvement_labs ORDER BY created DESC LIMIT 100')
            return [lab.get(db,row['id'],m.vault) for row in rows]

    @app.get('/api/improvements/{identity}')
    def improvement_get(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:return lab.get(db,identity,m.vault)

    @app.post('/api/improvements/{identity}/candidate')
    def improvement_edit(identity:str,body:lab.EditInput,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE');return lab.edit(db,identity,body,m.vault,m.signer,m.audit_append)

    @app.post('/api/improvements/{identity}/evaluate')
    def improvement_evaluate(identity:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        return lab.evaluate(identity,m.conn,m.vault,m.signer,m.audit_append,lambda code,*info:isolated_trial(m,code,*info))

    @app.post('/api/improvements/{identity}/{action}')
    def improvement_transition(identity:str,action:str,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            db.execute('BEGIN IMMEDIATE')
            if action=='promote':return lab.promote(db,identity,m.vault,m.signer,m.audit_append)
            if action=='rollback':return lab.rollback(db,identity,m.vault,m.signer,m.audit_append)
            if action not in ('revoke','recover'):raise HTTPException(404,'Unknown improvement operation')
            value=lab.get(db,identity,m.vault)
            if action=='recover':
                if value['status']!='evaluating':raise HTTPException(409,'Only an interrupted evaluation can recover')
                value['trials'][-1]['status']='interrupted';value['status']='rejected'
            else:
                if value['status']=='promoted':raise HTTPException(409,'Use rollback for a promoted capsule')
                value['status']='revoked'
            lab.save(db,value,m.vault);m.audit_append(db,m.signer,'improvement.'+action,identity,{'state':value['status']})
            return value


def isolated_trial(m,code,identity,variant,name):
    """Exact selected worker; no direct-Docker/controller or unsafe subprocess fallback."""
    with m.conn() as db:worker=m.select_worker(db,'python')
    if not worker or not m.WORKER_TOKEN or worker['endpoint'] not in m.WORKER_ALLOWED:
        raise HTTPException(503,'A separate, allowlisted clean Python worker is required')
    try:
        with httpx.Client(timeout=24,follow_redirects=False,trust_env=False) as client:
            health=client.get(worker['endpoint']+'/health').json()
            if health.get('python_mode')!='per-job-docker-or-deny':
                raise HTTPException(503,'Improvement tests refuse the unsafe worker smoke mode')
            response=client.post(worker['endpoint']+'/execute',headers={'Authorization':'Bearer '+m.WORKER_TOKEN},json={'kind':'python','code':code})
            response.raise_for_status();reply=response.json()
        result=reply['result']
        if reply.get('digest')!='sha256:'+sha(canon(result)) or result.get('status') not in ('completed','failed','denied'):
            raise ValueError('Invalid worker evidence')
        if len(str(result.get('stdout','')))>24000 or len(str(result.get('stderr','')))>24000:raise ValueError('Worker output budget exceeded')
    except (httpx.HTTPError,KeyError,ValueError,TypeError) as exc:
        raise HTTPException(502,'Isolated worker unavailable or returned invalid evidence') from exc
    job_id='trial_'+uuid.uuid4().hex
    payload={'schema':'capsula.improvement-trial.v1','id':job_id,'lab_id':identity,'variant':variant,'case':name,
        'worker_id':worker['id'],'program_sha256':sha(code.encode()),'result_sha256':sha(canon(result)),
        'status':result['status'],'trust':'operator worker report; not hardware attestation'}
    with m.conn() as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)',(job_id,identity,worker['id'],'python',result['status'],core.utc(),core.utc(),core.serial({'program_sha256':payload['program_sha256']}),core.serial({'payload':payload,'signature':m.signer.sign(payload)}),core.utc()))
        m.audit_append(db,m.signer,'improvement.trial_observed',job_id,payload)
    return {**result,'mission_id':job_id}
