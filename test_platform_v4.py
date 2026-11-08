"""Release 0.4 integration and adversarial tests: application-level contracts."""
import json,pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from test_api_v2 import c,auth
from platform_core import ProjectFile,AgentInput,Step,AgentRunInput
import app, inference

WS='v4-lab'

def api(method,path,body=None):return getattr(c,method)(path,headers=auth,json=body) if body is not None else getattr(c,method)(path,headers=auth)

def ws():
    r=api('post','/api/workspaces',{'slug':WS,'description':'CAPSULA platform testing'})
    assert r.status_code in (200,409)

def agent(caps=None,model=''):
    ws()
    return api('post','/api/agents',{'workspace':WS,'name':'Capsula verification agent','role':'Isolated test runner','model':model,'max_steps':5,'capabilities':caps or ['python','memory','artifact','inference']})

def test_platform_status_and_provider_independence():
    x=api('get','/api/platform');assert x.status_code==200
    d=x.json();assert d['version']=='0.4.0-alpha.1';assert d['provider_policy']=='no dependency on Vultr'
    for key in ('workspaces','project_files','agent_profiles','agent_runs','missions','workers','approvals','artifact_blobs','memory'):assert key in d['counts']
    y=api('get','/api/providers');assert y.status_code==200
    for provider in ('local-docker','remote-worker','model-compatible','vultr','phantom'):assert provider in [p['id'] for p in y.json()]
    assert all('API_KEY' not in json.dumps(p) for p in y.json())
    assert api('get','/api/platform').json()['payment_execution']=='disabled'

def test_site_is_real_application():
    r=c.get('/');assert r.status_code==200
    assert '<title>CAPSULA' in r.text
    for page in ('overview','projects','agents','runs','missions','computers','models','vault','finance','approvals','security'):
        assert f'id="page-{page}"' in r.text
    assert c.get('/static/app.js').status_code==200
    assert c.get('/static/app.css').status_code==200
    assert 'run-form' in c.get('/static/app.js').text.lower()

def test_workspace_file_write_revision_read_encrypted():
    ws();b={'workspace':WS,'path':'src/release.py','content':'print(\"revision 1\")','expected_revision':0}
    r=api('post','/api/project-files',b);assert r.status_code in (200,409)
    if r.status_code==409:
        prev=api('get','/api/project-files/read?workspace='+WS+'&path=src%2Frelease.py').json()['revision'];b['expected_revision']=prev
        r=api('post','/api/project-files',b)
    assert r.status_code==200;d=r.json();rev=d['revision']
    assert d['sealed'] is True and d['digest'].startswith('sha256:')
    q=api('get','/api/project-files/read?workspace='+WS+'&path=src%2Frelease.py');assert q.status_code==200
    assert q.json()['content']==b['content'] and q.json()['verified']
    assert api('post','/api/project-files',b).status_code==409
    b['expected_revision']=rev;b['content']='print(\"revision 2\")'
    n=api('post','/api/project-files',b);assert n.status_code==200 and n.json()['revision']==rev+1
    old=api('get',f'/api/project-files/read?workspace={WS}&path=src%2Frelease.py&revision={rev}');assert old.json()['content']=='print("revision 1")'
    hist=api('get',f'/api/project-files/revisions?workspace={WS}&path=src%2Frelease.py').json();assert len(hist)>=2
    listings=api('get',f'/api/project-files?workspace={WS}').json();assert sum(x['path']=='src/release.py' for x in listings)==1
    with app.conn() as db:
        rows=db.execute('SELECT sealed FROM project_files WHERE workspace=? AND path=?',(WS,b['path'])).fetchall()
        assert all('revision 1' not in row['sealed'] and 'revision 2' not in row['sealed'] for row in rows)

def test_file_reject_nonexistent_workspace():
    r=api('post','/api/project-files',{'workspace':'does-not-exist','path':'ok.txt','content':'x'});assert r.status_code==404

@pytest.mark.parametrize('bad',["../escape.py","folder/../escape.py","folder//bad", "/absolute.txt",".git/config","a\\windows.txt","a/<evil>.txt","a/",".","..","abc//def","a\x00b","#file"])
def test_project_file_paths_reject_traversal(bad):
    with pytest.raises(ValidationError):ProjectFile(workspace='v4-lab',path=bad,content='anything')

@pytest.mark.parametrize('bad',[-2, -1])
def test_file_revision_reject_invalid(bad):
    with pytest.raises(ValidationError):ProjectFile(workspace='v4-lab',path='good.txt',content='x',expected_revision=bad)

@pytest.mark.parametrize('cap',["shell","finance","wallet","root","database","spawn","terminal","cloud","mcp"])
def test_agents_only_known_capabilities(cap):
    with pytest.raises(ValidationError):AgentInput(workspace='v4-lab',name='Test agent',role='Limited',capabilities=[cap])

def test_agent_creation_listing_disabling():
    result=agent();assert result.status_code==200;d=result.json();assert d['status']=='active';assert 'python' in d['capabilities'];aid=d['id']
    assert api('get','/api/agents/'+aid).json()['id']==aid
    assert aid in [a['id'] for a in api('get','/api/agents?workspace='+WS).json()]
    assert api('post','/api/agents/'+aid+'/disable').json()['status']=='disabled'
    x=api('post','/api/agents/'+aid+'/runs',{'title':'Run after disabling','steps':[{'kind':'python','title':'Do a test','code':'print(1)'}]})
    assert x.status_code==409

def test_agent_run_approval_memory_artifact_pipeline():
    r=agent(['memory','artifact']);assert r.status_code==200;aid=r.json()['id']
    steps=[{'kind':'memory','title':'Store results','label':'Lab notes','content':'result=42'}, {'kind':'artifact','title':'Publish report','name':'report.txt','content':'Lab report: result=42'}]
    run=api('post','/api/agents/'+aid+'/runs',{'title':'End-to-end memory and artifact workflow','steps':steps});assert run.status_code==200
    rid=run.json()['id'];approval=run.json()['approval_id'];assert approval
    assert api('post','/api/agent-runs/'+rid+'/execute').status_code==403
    q=api('post','/api/approvals/'+approval+'/decide?decision=approve');assert q.status_code==200
    ex=api('post','/api/agent-runs/'+rid+'/execute');assert ex.status_code==200;data=ex.json()
    assert data['status']=='completed';assert data['steps_completed']==2
    assert 'memory_id' in data['results'][0];assert 'artifact_id' in data['results'][1]
    assert api('get','/api/agent-runs/'+rid).json()['state']=='completed'
    assert api('post','/api/agent-runs/'+rid+'/execute').status_code==409
    mem=api('get',f'/api/memory/{WS}/{data["results"][0]["memory_id"]}');assert mem.json()['content']=='result=42'
    artifact=api('get','/api/artifacts/'+data['results'][1]['artifact_id']);assert artifact.json()['content']=='Lab report: result=42'
    with app.conn() as db:
        raw=db.execute('SELECT steps,results FROM agent_runs WHERE id=?',(rid,)).fetchone()
        assert 'result=42' not in raw['steps'] and 'result=42' not in raw['results']

def test_agent_run_reject_overstep_and_unauthorized():
    a=agent(['memory']);assert a.status_code==200;aid=a.json()['id']
    assert api('post','/api/agents/'+aid+'/runs',{'title':'Cross permission','steps':[{'kind':'python','title':'Not granted','code':'print(1)'}]}).status_code==403
    assert api('post','/api/agents/'+aid+'/runs',{'title':'Exceeds step budget','steps':[{'kind':'memory','title':'Step','content':'hello'}]*6}).status_code==422
    assert api('post','/api/agents/'+aid+'/runs',{'title':'Empty memory','steps':[{'kind':'memory','title':'Step','content':''}]}).status_code==422

def test_agent_run_python_denied_without_sandbox(monkeypatch):
    a=agent(['python']);assert a.status_code==200;aid=a.json()['id']
    monkeypatch.setattr(app,'WORKER_ALLOWED',set());monkeypatch.setattr(app,'WORKER_TOKEN','');monkeypatch.setattr(app,'docker_ready',lambda:False)
    run=api('post','/api/agents/'+aid+'/runs',{'title':'Bounded Python execution','steps':[{'kind':'python','title':'Print result','code':'print(6*7)'}]});assert run.status_code==200
    rid=run.json()['id'];aid2=run.json()['approval_id'];api('post','/api/approvals/'+aid2+'/decide?decision=approve')
    outcome=api('post','/api/agent-runs/'+rid+'/execute');assert outcome.status_code==200
    assert outcome.json()['status']=='denied'
    mid=outcome.json()['results'][0]['mission_id']
    assert api('get','/api/missions/'+mid).json()['proof_valid']

def test_rejected_approval_prevents_execution():
    a=agent(['memory']);aid=a.json()['id']
    run=api('post','/api/agents/'+aid+'/runs',{'title':'No execution after rejection','steps':[{'kind':'memory','title':'Write notes','content':'reject me'}]})
    assert run.status_code==200
    api('post','/api/approvals/'+run.json()['approval_id']+'/decide?decision=reject')
    assert api('post','/api/agent-runs/'+run.json()['id']+'/execute').status_code==403

def test_no_approval_required_for_non_execution():
    a=agent(['memory']);aid=a.json()['id']
    run=api('post','/api/agents/'+aid+'/runs',{'title':'Authorized memory action','steps':[{'kind':'memory','title':'Store note','content':'allowed'}], 'approval_required':False})
    assert run.status_code==200;assert run.json()['approval_id']==''
    assert api('post','/api/agent-runs/'+run.json()['id']+'/execute').json()['status']=='completed'

def test_model_provider_loopback_without_vultr(monkeypatch):
    monkeypatch.setenv('CAPSULA_MODEL_URL','http://127.0.0.1:11434/v1/chat/completions')
    monkeypatch.setenv('CAPSULA_MODEL_ALLOWED_MODELS','local-small,local-large')
    monkeypatch.setenv('CAPSULA_MODEL_PROVIDER','self-hosted')
    monkeypatch.delenv('VULTR_INFERENCE_URL',raising=False);monkeypatch.delenv('VULTR_INFERENCE_API_KEY',raising=False)
    cfg=inference.public_config();assert cfg['configured'] and cfg['mode']=='loopback' and cfg['provider']=='self-hosted'
    assert 'endpoint' not in cfg and 'key' not in cfg
    assert api('post','/api/inference/complete',{'model':'unexpected','prompt':'hello'}).status_code==403
    class Resp:
        def raise_for_status(self):pass
        def json(self):return {'choices':[{'message':{'content':'Local inference verified'}}],'usage':{'total_tokens':10}}
    class Client:
        def __init__(self,**kwargs):assert not kwargs['follow_redirects'] and not kwargs['trust_env']
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def post(self,url,headers,json):
            assert url=='http://127.0.0.1:11434/v1/chat/completions';assert json['model']=='local-small';return Resp()
    monkeypatch.setattr(inference.httpx,'Client',Client)
    out=api('post','/api/inference/complete',{'model':'local-small','prompt':'hello'});assert out.status_code==200
    assert out.json()['text']=='Local inference verified'

@pytest.mark.parametrize('host',["http://evil.example/v1/chat/completions","file:///etc/passwd","http://10.0.0.1/v1/chat/completions","https://badhost.example/v1/chat/completions"])
def test_model_provider_rejects_unpinned_or_insecure(monkeypatch,host):
    monkeypatch.setenv('CAPSULA_MODEL_URL',host);monkeypatch.setenv('CAPSULA_MODEL_ALLOWED_MODELS','local-model');monkeypatch.delenv('CAPSULA_MODEL_HOST',raising=False)
    assert inference.config()['configured'] is False

def test_audit_remains_valid_with_application_actions():
    assert api('get','/api/audit').json()['verified'] is True
    names={entry['action'] for entry in api('get','/api/audit').json()['entries']}
    for required in ('agent.created','agent.run_created','project.file_saved','agent.run_completed'):
        assert required in names

@pytest.mark.parametrize('bad',[{'kind':'browser','title':'Visit','url':'http://127.0.0.1'},{'kind':'python','title':'Execute'},{'kind':'inference','title':'Plan','prompt':''},{'kind':'memory','title':'Write'}])
def test_agent_run_step_validation(bad):
    a=agent(['python','browser','inference','memory'],model='approved-local')
    if a.status_code!=200:pytest.fail(a.text)
    r=api('post','/api/agents/'+a.json()['id']+'/runs',{'title':'Adversarial step validation','steps':[bad]})
    assert r.status_code in (422,403)

def test_model_planning_creates_reviewable_run_without_execution(monkeypatch):
    a=agent(['python','inference'],model='approved-local');assert a.status_code==200
    aid=a.json()['id']
    def fake_infer(data):
        assert data.model=='approved-local'
        assert 'propose' in data.prompt.lower()
        return {'status':'completed','provider':'test-local','model':data.model,'text':json.dumps({'title':'Inspect release with code', 'steps':[{'kind':'python','title':'Verify arithmetic','code':'print(6*7)'}]}),'usage':{}}
    monkeypatch.setattr(inference,'infer',fake_infer)
    r=api('post','/api/agents/'+aid+'/plan',{'goal':'Propose an isolated Python test for the next release'})
    assert r.status_code==200,r.text
    d=r.json();assert d['status']=='proposed-not-executed'
    rid=d['run']['id'];aid2=d['run']['approval_id']
    assert d['run']['status']=='awaiting_approval' and aid2
    assert api('post','/api/agent-runs/'+rid+'/execute').status_code==403
    with app.conn() as db:
        x=db.execute('SELECT * FROM agent_runs WHERE id=?',(rid,)).fetchone()
        assert x['state']=='awaiting_approval' and 'print(6*7)' not in x['steps']


def test_model_planning_rejects_unauthorized_capability(monkeypatch):
    a=agent(['inference'],model='approved-local');aid=a.json()['id']
    def fake_infer(_):return {'status':'completed','provider':'test-local','model':'approved-local','text':json.dumps({'title':'Escalate privileges','steps':[{'kind':'python','title':'Try shell','code':'print(1)'}]}),'usage':{}}
    monkeypatch.setattr(inference,'infer',fake_infer)
    before=len(api('get','/api/agent-runs').json())
    r=api('post','/api/agents/'+aid+'/plan',{'goal':'Please propose unauthorized Python execution'})
    assert r.status_code==403
    assert len(api('get','/api/agent-runs').json())==before

@pytest.mark.parametrize('bad',['not-json','[]','{"name":"not a plan"}','{"title":"too short","steps":[]}','```json\nNOPE\n```'])
def test_model_plan_invalid_output_never_runs(monkeypatch,bad):
    a=agent(['python','inference'],model='approved-local');aid=a.json()['id']
    monkeypatch.setattr(inference,'infer',lambda _:{'status':'completed','provider':'test-local','model':'approved-local','text':bad,'usage':{}})
    before=len(api('get','/api/agent-runs').json())
    r=api('post','/api/agents/'+aid+'/plan',{'goal':'Create a planned test for the release candidate'})
    assert r.status_code==422
    assert len(api('get','/api/agent-runs').json())==before


def test_agent_model_output_to_artifact(monkeypatch):
    a=agent(['inference','artifact'],model='approved-local');aid=a.json()['id']
    monkeypatch.setattr(inference,'infer',lambda _:{'status':'completed','provider':'test-local','model':'approved-local','text':'Model generated a verified work summary','usage':{'total_tokens':24}})
    r=api('post','/api/agents/'+aid+'/runs',{'title':'Model and artifact pipeline','steps':[
        {'kind':'inference','title':'Produce report','prompt':'Summarize work'},
        {'kind':'artifact','title':'Archive report','name':'model-report.txt','content':'{{last.output}}'}]})
    assert r.status_code==200
    rid=r.json()['id'];approval=r.json()['approval_id']
    assert api('post','/api/approvals/'+approval+'/decide?decision=approve').status_code==200
    result=api('post','/api/agent-runs/'+rid+'/execute')
    assert result.status_code==200,result.text
    assert result.json()['status']=='completed'
    artifact_id=result.json()['results'][1]['artifact_id']
    archived=api('get','/api/artifacts/'+artifact_id).json()
    assert archived['content']=='Model generated a verified work summary'
    assert archived['verified_local_integrity']
