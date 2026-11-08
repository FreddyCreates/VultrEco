"""Blast Radius Zero and Future of Work contract / adversarial checks.
These tests DO NOT constitute a deployed containment demonstration.
"""
import json
import pytest
from fastapi.testclient import TestClient
from test_api_v2 import c, auth
import app
from challenge import SAMPLE_CSV, PROCUREMENT_SCRIPT
from inference import InferenceInput


def api(method, path, body=None):
    kwargs={'headers':auth}
    if body is not None:kwargs['json']=body
    return getattr(c,method)(path,**kwargs)

def configured_agent(monkeypatch, caps=None, max_steps=3):
    monkeypatch.setenv('CAPSULA_MODEL_URL','http://127.0.0.1:11434/v1/chat/completions')
    monkeypatch.setenv('CAPSULA_MODEL_ALLOWED_MODELS','isolated-llm')
    api('post','/api/workspaces',{'slug':'challenge-lab','description':'challenge test'})
    r=api('post','/api/agents',{'workspace':'challenge-lab','name':'Evidence Worker','role':'Analyst','model':'isolated-llm',
        'capabilities':caps if caps is not None else ['python','inference'],'max_steps':max_steps})
    assert r.status_code==200,r.text
    return r.json()['id']

def fake_model(monkeypatch, answer=None):
    from challenge import bind
    import inference
    calls=[]
    def fake(body):
        calls.append(body)
        return {'text':answer if answer is not None else json.dumps({'title':'Run bounded analysis','code':'print(6*7)'}),'model':body.model,'provider':'test-model','usage':{}}
    monkeypatch.setattr(inference,'infer',fake)
    # challenge.bind imports `infer` into closures; patch the registered route globals via rebind
    # Not using raw route overrides: replace dependency via target function globals.
    for route in app.app.routes:
        if getattr(route,'path','') in ('/api/challenge/code/propose','/api/challenge/code/retry'):
            route.endpoint.__globals__['infer']=fake
    return calls


def test_preflight_does_not_fake_pass():
    r=api('get','/api/challenge/preflight');assert r.status_code==200
    j=r.json();assert j['ready_to_claim_challenge_1'] is False
    assert j['ready_to_claim_challenge_2'] is False
    for name in ('vultr_attested','container_isolation_verified','public_demo_verified','video_verified'):
        assert j[name] is False


def test_auth_required():
    assert c.get('/api/challenge/preflight').status_code==401
    assert c.post('/api/challenge/procurement/sample',json={}).status_code==401
    assert c.post('/api/challenge/code/propose',json={'agent_id':'abcdefgh','goal':'Analyze a CSV file please'}).status_code==401


def test_sample_procurement_proposal_is_approved_not_auto_run():
    r=api('post','/api/challenge/procurement/sample',{'workspace':'procurement-lab'})
    assert r.status_code==200,r.text
    d=r.json();assert d['status']=='requires-human-approval' and d['purchasing']=='not-permitted'
    assert d['run']['approval_id'] and d['run']['status']=='awaiting_approval'
    rid=d['run']['id']
    assert api('post','/api/agent-runs/'+rid+'/execute').status_code==403
    with app.conn() as db:
        steps=app.core.run_secrets(db,rid,app.vault)
    assert steps[0]['kind']=='python' and 'ranked' in steps[0]['code']
    assert steps[1]['kind']=='artifact' and '{{last.output}}' in steps[1]['content']
    assert len(list(__import__('csv').DictReader(__import__('io').StringIO(d['example_data']))))==5


def test_procurement_core_algorithm_not_simulated():
    import subprocess,sys
    scope={'CSV_DATA':SAMPLE_CSV}
    exec(PROCUREMENT_SCRIPT,scope)
    code='CSV_DATA='+repr(SAMPLE_CSV)+'\n'+PROCUREMENT_SCRIPT
    p=subprocess.run([sys.executable,'-c',code],capture_output=True,text=True,timeout=4)
    assert p.returncode==0 and json.loads(p.stdout)['offers']==5
    assert json.loads(p.stdout)['approval_required_before_purchasing'] is True
    assert any(x['risk']=='review' for x in json.loads(p.stdout)['ranked'])


def test_requires_agent_inference_permission(monkeypatch):
    aid=configured_agent(monkeypatch,caps=['python'])
    r=api('post','/api/challenge/code/propose',{'agent_id':aid,'goal':'Compute arithmetic with Python, report the answer'})
    assert r.status_code==403


def test_propose_code_persists_sealed_human_approval(monkeypatch):
    aid=configured_agent(monkeypatch)
    calls=fake_model(monkeypatch)
    r=api('post','/api/challenge/code/propose',{'agent_id':aid,'goal':'Compute the number of seconds in one hour','csv_data':'vendor,cost\nA,10\nB,8'})
    assert r.status_code==200,r.text
    data=r.json();assert data['status']=='requires-human-approval' and data['execution']=='not-executed'
    assert calls and 'CSV columns' in calls[-1].prompt
    rid=data['run']['id'];assert api('post','/api/agent-runs/'+rid+'/execute').status_code==403
    with app.conn() as db:
        row=db.execute('SELECT * FROM challenge_attempts WHERE run_id=?',(rid,)).fetchone()
        assert row['attempt']==0
        assert 'seconds in one hour' not in row['context']
        steps=app.core.run_secrets(db,rid,app.vault)
    assert steps[0]['code'].startswith('CSV_DATA = ')
    assert steps[1]['kind']=='inference'
    assert '{{last.output}}' in steps[1]['prompt']


def test_model_bad_json_rejected_without_work(monkeypatch):
    aid=configured_agent(monkeypatch)
    fake_model(monkeypatch,'not valid JSON')
    r=api('post','/api/challenge/code/propose',{'agent_id':aid,'goal':'Calculate this simple arithmetic safely'})
    assert r.status_code==422


@pytest.mark.parametrize('csv', ['a,b\n', 'a,b', 'a,b\n1,2\n'*140])
def test_reject_bad_csv(monkeypatch,csv):
    aid=configured_agent(monkeypatch)
    fake_model(monkeypatch)
    r=api('post','/api/challenge/code/propose',{'agent_id':aid,'goal':'Analyze these rows as a spreadsheet', 'csv_data':csv})
    assert r.status_code==422


def test_retry_denied_for_incomplete_run(monkeypatch):
    aid=configured_agent(monkeypatch)
    fake_model(monkeypatch)
    r=api('post','/api/challenge/code/propose',{'agent_id':aid,'goal':'Safely calculate the answer to a question'})
    assert r.status_code==200
    rid=r.json()['run']['id']
    rr=api('post','/api/challenge/code/retry',{'run_id':rid})
    assert rr.status_code==409


def test_competition_mode_never_falls_back_to_controller(monkeypatch):
    monkeypatch.setenv('CAPSULA_COMPETITION_MODE','1')
    monkeypatch.setenv('CAPSULA_ALLOW_DIRECT_DOCKER','1')
    monkeypatch.setattr(app,'docker_ready',lambda:True)
    monkeypatch.setattr(app,'select_worker',lambda db,kind:None)
    r=api('post','/api/missions',{'title':'Isolation fallback test','kind':'python','code':'print(1)'})
    assert r.status_code==200 and r.json()['status']=='denied'


def test_worker_default_is_deny_without_docker(monkeypatch):
    import worker_runtime
    monkeypatch.delenv('CAPSULA_WORKER_DEV_ALLOW_UNISOLATED',raising=False)
    monkeypatch.delenv('CAPSULA_WORKER_HOST_RUN_PATH',raising=False)
    r=worker_runtime.run_python('print(3)')
    assert r['status']=='denied'
