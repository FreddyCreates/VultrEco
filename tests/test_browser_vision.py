"""Challenge B security: browser is isolated, screenshot verification is opt-in."""
import base64
import json
from pathlib import Path
from unittest.mock import Mock
import pytest
from fastapi import HTTPException
from capsula.execution import browser_task
from capsula.execution import worker_runtime
from capsula.intelligence import vision
from test_api_v2 import c,auth


@pytest.mark.parametrize('url',[
 'http://example.com','https://localhost','https://127.0.0.1','https://169.254.169.254/latest/meta-data/',
 'https://guest:password@example.com','ftp://example.com','https://example.com:8080'
])
def test_browser_requires_https_allowlisted_public_target(monkeypatch,url):
    monkeypatch.setenv('CAPSULA_BROWSER_ALLOWLIST','example.com')
    monkeypatch.setattr(worker_runtime.socket if hasattr(worker_runtime,'socket') else __import__('socket'),'getaddrinfo',lambda *a:[(None,None,None,None,('127.0.0.1',443))])
    with pytest.raises(HTTPException):worker_runtime.run_browser(url,'')


def test_worker_browser_fails_closed_without_disposable_sandbox(monkeypatch,tmp_path):
    monkeypatch.setenv('CAPSULA_BROWSER_ALLOWLIST','example.com')
    monkeypatch.delenv('CAPSULA_BROWSER_NETWORK',raising=False)
    monkeypatch.setattr(__import__('socket'),'getaddrinfo',lambda *args:[(None,None,None,None,('93.184.215.14',443))])
    result=worker_runtime.run_browser('https://example.com','main')
    assert result['status']=='denied'
    assert 'required' in result['reason']


def test_browser_container_command_is_non_privileged_and_disposable(monkeypatch,tmp_path):
    import subprocess
    monkeypatch.setenv('CAPSULA_BROWSER_ALLOWLIST','example.com')
    monkeypatch.setenv('CAPSULA_BROWSER_NETWORK','policy-egress')
    monkeypatch.setenv('CAPSULA_BROWSER_EGRESS_ENFORCED','1')
    monkeypatch.setenv('CAPSULA_WORKER_CONTAINER_RUN_PATH',str(tmp_path))
    monkeypatch.setenv('CAPSULA_WORKER_HOST_RUN_PATH',str(tmp_path))
    monkeypatch.setattr(__import__('socket'),'getaddrinfo',lambda *args:[(None,None,None,None,('93.184.215.14',443))])
    calls=[]
    def fake_run(cmd,**kwargs):
        calls.append(cmd)
        return Mock(returncode=0,stdout=json.dumps({'status':'completed','stdout':'Page exists',
                     'screenshot_b64':base64.b64encode(b'\xff\xd8\xff').decode(),
                     'image_mime':'image/jpeg'}),stderr='')
    monkeypatch.setattr(subprocess,'run',fake_run)
    data=worker_runtime.run_browser('https://example.com','main')
    assert data['status']=='completed';args=calls[0]
    assert '--rm' in args and '--read-only' in args and '--cap-drop' in args
    assert '--memory' in args and '--pids-limit' in args
    assert '--network' in args and args[args.index('--network')+1]=='policy-egress'
    assert '--user' in args and args[args.index('--user')+1]=='10001:10001'
    assert 'CAPSULA_API_KEY' not in str(args) and 'CAPSULA_MODEL_API_KEY' not in str(args)
    assert 'no-new-privileges' in str(args)


@pytest.mark.parametrize('x',[
 {'url':'http://example.com','allowed_hosts':['example.com']},
 {'url':'https://example.com','allowed_hosts':['another.com']},
 {'url':'https://private.example','allowed_hosts':['private.example']},
])
def test_browser_task_target_guard(monkeypatch,x):
    monkeypatch.setattr(browser_task.socket,'getaddrinfo',lambda *args:[(None,None,None,None,('10.0.0.9',443))])
    with pytest.raises(ValueError):browser_task.safe_target(x['url'],set(x['allowed_hosts']))


def test_vision_denied_without_separate_approved_vision_model(monkeypatch):
    monkeypatch.setattr(vision,'config',lambda:{'configured':True,'models':['model-a'],'provider':'test','endpoint':'http://127.0.0.1'})
    monkeypatch.delenv('CAPSULA_MODEL_VISION_MODELS',raising=False)
    with pytest.raises(HTTPException) as err:vision.review('model-a','Describe screenshot',base64.b64encode(b'\xff\xd8\xff').decode())
    assert err.value.status_code==503


@pytest.mark.parametrize('data,mime',[
   ('not-base64','image/jpeg'),
   (base64.b64encode(b'not an image').decode(),'image/jpeg'),
   (base64.b64encode(b'\xff\xd8\xff').decode(),'image/svg+xml'),
   (base64.b64encode(b'\x89PNG\r\n\x1a\n').decode(),'image/jpeg'),
])
def test_vision_rejects_malformed_or_incompatible_media(monkeypatch,data,mime):
    monkeypatch.setattr(vision,'config',lambda:{'configured':True,'models':['model-a'],'provider':'test','endpoint':'https://example.com'})
    monkeypatch.setenv('CAPSULA_MODEL_VISION_MODELS','model-a')
    with pytest.raises(HTTPException) as err:vision.review('model-a','Describe screenshot',data,mime)
    assert err.value.status_code==422


def test_vision_uses_pinned_provider_not_browser_origin(monkeypatch):
    import httpx
    monkeypatch.setattr(vision,'config',lambda:{'configured':True,'models':['model-a'],'provider':'test',
                                               'endpoint':'https://approved-model.test/v1/chat/completions','key':'top-secret'})
    monkeypatch.setenv('CAPSULA_MODEL_VISION_MODELS','model-a')
    observed={}
    class FakeClient:
        def __init__(self,**kwargs):assert kwargs['follow_redirects']==False;assert kwargs['trust_env']==False
        def __enter__(self):return self
        def __exit__(self,*a):return False
        def post(self,url,**kwargs):
            observed['url']=url;observed['payload']=kwargs['json'];observed['headers']=kwargs['headers']
            return Mock(raise_for_status=lambda:None,json=lambda:{'choices':[{'message':{'content':'Visible login form'}}]})
    monkeypatch.setattr(httpx,'Client',FakeClient)
    img=base64.b64encode(b'\xff\xd8\xfffakejpeg').decode()
    out=vision.review('model-a','Identify visible form',img)
    assert out['status']=='completed'
    assert observed['url']=='https://approved-model.test/v1/chat/completions'
    assert 'data:image/jpeg;base64,' in str(observed['payload'])
    assert observed['headers']['Authorization']=='Bearer top-secret'
    assert out['verification'].startswith('model-interpretation')


def test_vision_step_requires_prior_browser_and_capability():
    from test_autonomy import req,create_agent
    agent=create_agent()
    a=req('post',f"/api/agents/{agent['id']}/runs",{'title':'No screenshot available',
       'steps':[{'kind':'vision','title':'Describe an unseen screenshot','prompt':'Describe'}]})
    assert a.status_code==403 # model-enabled agent was not granted vision
    new_agent=create_agent(caps=['vision','browser','inference'])
    b=req('post',f"/api/agents/{new_agent['id']}/runs",{'title':'Wrong workflow order',
       'steps':[{'kind':'vision','title':'Describe an unseen screenshot','prompt':'Describe'}]})
    assert b.status_code==422
    q=req('post',f"/api/agents/{new_agent['id']}/runs",{'title':'Read-only browsing with visual review',
       'steps':[{'kind':'browser','title':'Inspect public site','url':'https://example.com'},
                {'kind':'vision','title':'Verify screenshot','prompt':'Describe what you can see'}]})
    assert q.status_code==200
    assert q.json()['approval_id']


def test_production_compose_does_not_mount_host_docker_socket():
    content=Path('docker-compose.production.yml').read_text()
    assert '/var/run/docker.sock' not in content
    assert 'CAPSULA_API_KEY' in content
    for path in ('Dockerfile.production','Dockerfile'):
        docker=Path(path).read_text()
        for module in ('autonomy.py','challenge.py','vision.py'):
            assert module in docker


def test_static_autonomy_ui_and_model_boundaries():
    s=Path('static/index.html').read_text()
    assert 'page-autonomy' in s and 'autonomy-form' in s
    assert 'Autonomous missions' in s
    js=Path('static/app.js').read_text()
    for name in ('loadAutonomy','autonomy/goals','autonomy/playbooks','data-auto'):
        assert name in js
