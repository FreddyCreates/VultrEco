"""Integration contracts. Trusted test subprocesses are not production isolation."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
import pytest
from fastapi import HTTPException
from test_api_v2 import c, auth
from capsula.api import app
from capsula.agents import computers
from capsula.agents import learning
from capsula.agents import improvement_lab as lab
from capsula.api import platform_routes


def api(method,path,body=None):
    return getattr(c,method)(path,headers=auth,**({'json':body} if body is not None else {}))


@pytest.fixture
def agent():
    ws='rah-'+uuid.uuid4().hex[:12]
    assert api('post','/api/workspaces',{'slug':ws,'description':'RAH verification namespace'}).status_code==200
    result=api('post','/api/agents',{'workspace':ws,'name':'Persistent agent','capabilities':['python','inference','memory','artifact'],'model':'test-local'})
    assert result.status_code==200
    return result.json()


def put(agent,path,content):
    response=api('post','/api/project-files',{'workspace':agent['workspace'],'path':path,'content':content})
    assert response.status_code==200,response.text
    return response.json()


def specification(agent,**changes):
    body={'agent_id':agent['id'],'objective':'Generalize doubling without breaking old behavior','request_key':uuid.uuid4().hex,
        'source_paths':['main.py'],'allowed_paths':['main.py'],'entrypoint':'main.py',
        'cases':[{'name':'existing','kind':'regression','stdin':'2','stdout':'4\n'},
                 {'name':'new','kind':'holdout','stdin':'3','stdout':'6\n'}]}
    return body|changes


def new_lab(agent,**changes):
    put(agent,'main.py','print(4)\n')
    response=api('post','/api/improvements',specification(agent,**changes))
    assert response.status_code==200,response.text
    return response.json()


def candidate(value,source='import sys\nprint(int(sys.stdin.read())*2)\n'):
    result=api('post','/api/improvements/'+value['id']+'/candidate',{'files':{'main.py':source}})
    assert result.status_code==200,result.text
    return result.json()


@pytest.fixture
def trusted_execution(monkeypatch):
    # This test-only executor runs ONLY test-authored literal programs. It is never
    # registered by production code and does not count as a clean-worker proof.
    executed=[]
    def execute(_,code,*info):
        executed.append((code,info))
        with tempfile.TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,'-I','-B','-c',code],cwd=directory,
                env={'PATH':os.defpath,'HOME':directory},capture_output=True,text=True,timeout=5)
        return {'status':'completed' if result.returncode==0 else 'failed','stdout':result.stdout,'exit_code':result.returncode,'mission_id':'test-process-'+str(len(executed))}
    monkeypatch.setattr(platform_routes,'isolated_trial',execute)
    return executed


def test_learning_state_real_workflow_and_automatic_skill_draft(agent):
    aid=agent['id']
    saved=api('post',f'/api/agents/{aid}/continuity',{'objective':'Build reliable tools','notes':'Keep failed trials','expected_revision':0})
    assert saved.status_code==200 and saved.json()['revision']==1
    assert api('post',f'/api/agents/{aid}/continuity',{'objective':'Overwrite stale state','expected_revision':0}).status_code==409
    run=api('post',f'/api/agents/{aid}/runs',{'title':'Remember a real outcome','approval_required':False,'steps':[{'kind':'memory','title':'Store outcome','content':'Test-owned result'}]}).json()
    result=api('post','/api/agent-runs/'+run['id']+'/execute')
    assert result.status_code==200 and result.json()['status']=='completed'
    state=api('get',f'/api/agents/{aid}/learning').json()
    assert len(state['observations'])==1 and state['observations'][0]['run_id']==run['id']
    assert state['session']['objective']=='Build reliable tools'
    assert state['active_procedures']==[]
    draft=state['proposals'][0]
    assert draft['kind']=='procedure' and draft['status']=='proposed'
    assert draft['path'].startswith('skills/proposals/')
    text=api('get','/api/project-files/read?workspace='+agent['workspace']+'&path='+draft['path']).json()['content']
    assert 'Store outcome' in text and 'not an active skill' in text
    assert api('post',f'/api/agents/{aid}/curiosity').json()['authority']=='none'
    assert len(api('get',f'/api/agents/{aid}/learning').json()['proposals'])==2


def test_disabled_agent_cannot_execute_preapproved_run(agent):
    run=api('post','/api/agents/'+agent['id']+'/runs',{'title':'Revocable work','approval_required':False,'steps':[{'kind':'memory','title':'Write once','content':'must not write'}]}).json()
    assert api('post','/api/agents/'+agent['id']+'/disable').status_code==200
    assert api('post','/api/agent-runs/'+run['id']+'/execute').status_code==409


def test_actual_trial_comparison_promotion_and_rollback(agent,trusted_execution):
    value=new_lab(agent);candidate(value)
    result=api('post','/api/improvements/'+value['id']+'/evaluate')
    assert result.status_code==200 and result.json()['status']=='verified'
    checks=result.json()['trials'][0]['cases']
    assert [x['passed'] for x in checks]==[True,False,True,True]
    assert len(trusted_execution)==4
    assert api('post','/api/improvements/'+value['id']+'/promote').json()['status']=='promoted'
    current=api('get','/api/project-files/read?workspace='+agent['workspace']+'&path=main.py').json()
    assert '*2' in current['content']
    assert api('post','/api/improvements/'+value['id']+'/rollback').json()['status']=='rolled_back'
    restored=api('get','/api/project-files/read?workspace='+agent['workspace']+'&path=main.py').json()
    assert restored['content']=='print(4)\n' and restored['revision']>current['revision']
    assert len(api('get','/api/improvements/'+value['id']).json()['trials'])==1


def test_capsule_data_encrypted_and_expected_answers_not_sent(agent,trusted_execution):
    value=new_lab(agent);candidate(value)
    api('post','/api/improvements/'+value['id']+'/evaluate')
    for code,_ in trusted_execution:
        assert 'expected_stdout' not in code and "'stdout':" not in code
    with app.conn() as db:
        raw=db.execute('SELECT sealed FROM improvement_labs WHERE id=?',(value['id'],)).fetchone()['sealed']
        assert 'Generalize doubling' not in raw and 'print(4)' not in raw
        assert 'AES-256-GCM' in raw


def test_no_controller_or_unsafe_worker_fallback(agent,monkeypatch):
    value=new_lab(agent);candidate(value)
    monkeypatch.setattr(app,'select_worker',lambda *_:None)
    monkeypatch.setattr(app,'run_python',lambda *_:pytest.fail('Controller execution is forbidden for improvement trials'))
    result=api('post','/api/improvements/'+value['id']+'/evaluate').json()
    assert result['status']=='rejected' and not result['trials'][-1]['cases']


def test_reject_regression_without_generalization_and_preserve_failures(agent,trusted_execution):
    value=new_lab(agent);candidate(value,'print(7)\n')
    assert api('post','/api/improvements/'+value['id']+'/evaluate').json()['status']=='rejected'
    candidate(value)
    result=api('post','/api/improvements/'+value['id']+'/evaluate').json()
    assert result['status']=='verified' and len(result['trials'])==2 and result['trials'][0]['status']=='rejected'


def test_pass_everything_does_not_count_as_improvement(agent,trusted_execution):
    value=new_lab(agent,cases=[{'name':'old','kind':'regression','stdin':'2','stdout':'4\n'},
        {'name':'new','kind':'holdout','stdin':'2','stdout':'4\n'}]);candidate(value)
    assert api('post','/api/improvements/'+value['id']+'/evaluate').json()['status']=='rejected'


def test_scope_stale_candidate_and_revision_conflicts(agent,trusted_execution):
    value=new_lab(agent)
    assert api('post','/api/improvements/'+value['id']+'/candidate',{'files':{'other.py':'print(1)'}}).status_code==403
    candidate(value);assert api('post','/api/improvements/'+value['id']+'/promote').status_code==409
    api('post','/api/improvements/'+value['id']+'/evaluate')
    candidate(value,'print(0)\n')
    assert api('post','/api/improvements/'+value['id']+'/promote').status_code==409
    candidate(value);api('post','/api/improvements/'+value['id']+'/evaluate')
    put(agent,'main.py','print("later work")\n')
    assert api('post','/api/improvements/'+value['id']+'/promote').status_code==409


def test_rollback_does_not_overwrite_later_work(agent,trusted_execution):
    value=new_lab(agent);candidate(value);api('post','/api/improvements/'+value['id']+'/evaluate');api('post','/api/improvements/'+value['id']+'/promote')
    put(agent,'main.py','print("newer")\n')
    assert api('post','/api/improvements/'+value['id']+'/rollback').status_code==409


def test_revocation_expiry_attempt_limits_and_idempotency(agent,trusted_execution):
    value=new_lab(agent,max_attempts=1);candidate(value)
    api('post','/api/improvements/'+value['id']+'/evaluate')
    assert api('post','/api/improvements/'+value['id']+'/evaluate').status_code==409
    assert api('post','/api/improvements/'+value['id']+'/revoke').json()['status']=='revoked'
    assert api('post','/api/improvements/'+value['id']+'/promote').status_code==409
    body=specification(agent);first=api('post','/api/improvements',body).json()
    assert api('post','/api/improvements',body).json()['id']==first['id']
    assert api('post','/api/improvements',body|{'objective':'Conflicting contract'}).status_code==409
    with app.conn() as db:
        exp=lab.get(db,first['id'],app.vault);exp['expires']=time.time()-1;lab.save(db,exp,app.vault)
    assert api('post','/api/improvements/'+first['id']+'/candidate',{'files':{'main.py':'print(9)'}}).status_code==409


@pytest.mark.parametrize('path',['../escape.py','/root/auth.json','.env','nested/auth.json','key.pem'])
def test_lab_rejects_credential_or_escaping_paths(agent,path):
    if not path.startswith(('.', '/')):put(agent,path,'private')
    result=api('post','/api/improvements',specification(agent,source_paths=[path],allowed_paths=[path],entrypoint=path))
    assert result.status_code==422


@pytest.mark.parametrize('field,value',[('max_attempts',True),('max_attempts',0),('seconds',601),('lease_seconds',99999),('allowed_paths',[]),('cases',[])])
def test_lab_rejects_malformed_budgets(agent,field,value):
    put(agent,'main.py','print(4)')
    assert api('post','/api/improvements',specification(agent,**{field:value})).status_code==422


def test_procedures_promoted_only_after_distinguishing_tests(agent,trusted_execution):
    path='skills/proposals/double/SKILL.md'
    put(agent,path,'step-one')
    main='import sys,pathlib\nx=int(sys.stdin.read())\nprint(4 if x==2 else (6 if "step-two" in pathlib.Path("'+path+'").read_text() else 4))\n'
    put(agent,'main.py',main)
    body=specification(agent,source_paths=['main.py',path],allowed_paths=[path],procedure_path=path)
    value=api('post','/api/improvements',body).json()
    assert api('post','/api/improvements/'+value['id']+'/candidate',{'files':{path:'step-two'}}).status_code==200
    assert api('get','/api/agents/'+agent['id']+'/learning').json()['active_procedures']==[]
    assert api('post','/api/improvements/'+value['id']+'/evaluate').json()['status']=='verified'
    assert api('post','/api/improvements/'+value['id']+'/promote').status_code==200
    active=api('get','/api/agents/'+agent['id']+'/learning').json()['active_procedures']
    assert len(active)==1 and active[0]['content']=='step-two'
    put(agent,active[0]['path'],'edited outside verified promotion')
    assert api('get','/api/agents/'+agent['id']+'/learning').json()['active_procedures']==[]


def test_unconfigured_computer_never_creates_fake_binding(agent,monkeypatch):
    monkeypatch.delenv('CAPSULA_DOT_URL',raising=False);monkeypatch.delenv('CAPSULA_DOT_TOKEN',raising=False)
    response=api('post','/api/agents/'+agent['id']+'/computer',{'provider':'chatgpt'})
    assert response.status_code==503
    assert agent['id'] not in [x['agent_id'] for x in api('get','/api/computers').json()['computers']]


def bind_fixture(agent,monkeypatch,remote_id=None):
    remote_id=remote_id or uuid.uuid4().hex
    def remote(method,path,body=None):
        if path=='/api/state':return {'agents':[{'id':remote_id,'domain':'dot-'+remote_id,'provider':'chatgpt','status':'ready'}],'missions':[]}
        if path=='/api/missions':return {'id':'a'*32,'status':'active','steps':body['steps']}
        if path.endswith('/cancel'):return {'id':'a'*32,'status':'cancelling'}
        if path.endswith('/workspace'):return {'checkpoint_id':'c'*32,'imported':len(body['files']),'sha256':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in body['files'].items()}}
        return {'id':'b'*32,'status':'queued'}
    monkeypatch.setattr(computers,'request',remote)
    response=api('post','/api/agents/'+agent['id']+'/computer/bind',{'remote_id':remote_id})
    assert response.status_code==200,response.text
    return remote_id,remote


def test_computer_uniqueness_workspace_sync_and_subscription_transport(agent,monkeypatch):
    remote_id,remote=bind_fixture(agent,monkeypatch)
    other=api('post','/api/agents',{'workspace':agent['workspace'],'name':'Second worker'}).json()
    assert api('post','/api/agents/'+other['id']+'/computer/bind',{'remote_id':remote_id}).status_code==409
    put(agent,'main.py','print(42)')
    assert api('post','/api/agents/'+agent['id']+'/computer/sync').json()['imported']==1
    state=api('get','/api/agents/'+agent['id']+'/computer').json()
    assert remote_id in state['login_command']
    assert 'token' not in json.dumps(state).lower()
    assert api('post','/api/agents/'+agent['id']+'/computer/tasks',{'prompt':'Build the project','request_key':'task-request-123'}).status_code==200


def test_rah_grant_is_signed_idempotent_and_scoped(agent,monkeypatch):
    remote_id,remote=bind_fixture(agent,monkeypatch)
    body={'workspace':agent['workspace'],'objective':'Run a bounded work tree','request_key':uuid.uuid4().hex,
        'steps':[{'name':'implement','agent_id':agent['id'],'prompt':'Produce and test the project'}]}
    result=api('post','/api/rah/missions',body)
    assert result.status_code==200,result.text
    value=result.json();grant=value['grant'];signature=grant.pop('signature')
    assert app.signer.verify(grant,signature)
    assert value['tree']['steps'][0]['agent_id']==remote_id
    assert api('post','/api/rah/missions',body).json()['id']==value['id']
    assert api('post','/api/rah/missions',body|{'objective':'Different authority'}).status_code==409
    assert api('post','/api/rah/missions/'+value['id']+'/cancel').json()['status']=='cancelling'
    body['request_key']=uuid.uuid4().hex;body['steps']*=2
    assert api('post','/api/rah/missions',body).status_code==422


def test_rah_rejects_cross_workspace_workers(agent,monkeypatch):
    bind_fixture(agent,monkeypatch)
    other='other-'+uuid.uuid4().hex[:8];api('post','/api/workspaces',{'slug':other})
    body={'workspace':other,'objective':'Cross scope attempt','request_key':uuid.uuid4().hex,'steps':[{'name':'steal','agent_id':agent['id'],'prompt':'Use another project'}]}
    assert api('post','/api/rah/missions',body).status_code==403


@pytest.mark.parametrize('path',['/api/rah/missions','/api/computers','/api/improvements'])
def test_new_routes_authenticate(path):
    assert c.get(path).status_code==401


def test_personal_and_enterprise_lanes_are_explicit(agent):
    path='/api/workspaces/'+agent['workspace']+'/lane'
    assert api('get',path).json()['lane']=='personal'
    value=api('post',path,{'lane':'enterprise','organization':'Medina Labs'}).json()
    assert value['organization']=='Medina Labs' and 'not tenant isolation' in value['tenancy']


def test_completed_vm_outcomes_feed_continuity_once(agent,monkeypatch):
    remote_id,remote=bind_fixture(agent,monkeypatch)
    job={'id':'c'*32,'agent_id':remote_id,'status':'completed','artifacts':[],'acceptance_result':{'passed':True}}
    def state(method,path,body=None):
        if path=='/api/state':return {'agents':[{'id':remote_id,'domain':'dot-'+remote_id,'provider':'chatgpt','status':'ready'}],'jobs':[job]}
        return remote(method,path,body)
    monkeypatch.setattr(computers,'request',state)
    view=api('get','/api/agents/'+agent['id']+'/computer')
    assert view.status_code==200 and view.json()['jobs'][0]['id']==job['id']
    assert api('get','/api/agents/'+agent['id']+'/computer').status_code==200
    learned=api('get','/api/agents/'+agent['id']+'/learning').json()
    assert len(learned['observations'])==1 and learned['session']['recent_outcomes'][0]['run_id']=='dot-'+job['id']


def test_evolution_and_rah_sections_have_real_forms():
    text=c.get('/').text
    for name in ('page-learning','page-rah','rah-form','lab-form','computer-form','continuity-form'):
        assert 'id="'+name+'"' in text
    script=c.get('/static/app.js').text
    assert 'improvements/' in script and 'rah/missions' in script and '/computer/tasks' in script
