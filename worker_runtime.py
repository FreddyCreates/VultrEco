"""Remote disposable worker. Requires separate network/VM identity; no host Docker socket."""
import os, subprocess, tempfile, pathlib, uuid, json, hmac, hashlib, time
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

app=FastAPI(title='CAPSULA bounded worker',version='0.4.0-alpha.1')
TOKEN=os.getenv('CAPSULA_WORKER_TOKEN','')
MAX_BYTES=24_000
class Job(BaseModel):
    kind:Literal['python','browser']
    code:str=Field(default='',max_length=16_000)
    url:str=Field(default='',max_length=300)
    selector:str=Field(default='',max_length=200)

def auth(authorization):
    if not TOKEN:raise HTTPException(503,'Worker token not provisioned')
    if not hmac.compare_digest(authorization or '', 'Bearer '+TOKEN):raise HTTPException(401,'Worker authentication failed')

def run_python_dev(code):
    if not code.strip():raise HTTPException(422,'Code required')
    # This service MUST run as non-root in an isolated worker container/VM. Code runs as a child process.
    # Process limits are layered with the host-enforced deployment limits. This is not a security boundary alone.
    with tempfile.TemporaryDirectory(prefix='capsula-task-') as tmp:
        p=pathlib.Path(tmp)/'task.py';p.write_text(code,encoding='utf-8')
        preexec=None
        if os.name=='posix':
            def limits():
                import resource
                resource.setrlimit(resource.RLIMIT_CPU,(6,7))
                resource.setrlimit(resource.RLIMIT_FSIZE,(1_000_000,1_000_000))
                resource.setrlimit(resource.RLIMIT_NOFILE,(32,32))
            preexec=limits
        try:
            result=subprocess.run(['python','-I','-B',str(p)],cwd=tmp,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':tmp,'PYTHONNOUSERSITE':'1'},capture_output=True,text=True,timeout=9,preexec_fn=preexec)
            return {'status':'completed' if result.returncode==0 else 'failed','exit_code':result.returncode,'stdout':result.stdout[:MAX_BYTES],'stderr':result.stderr[:MAX_BYTES]}
        except subprocess.TimeoutExpired:
            return {'status':'failed','exit_code':124,'stdout':'','stderr':'Execution timed out'}

def run_python(code):
    # Production path: every task executes in its own disposable container on a dedicated worker VM.
    # Do not allow untrusted code into the long-lived worker-service process by default.
    if not code.strip():raise HTTPException(422,'Code required')
    if os.getenv('CAPSULA_WORKER_DEV_ALLOW_UNISOLATED')=='1':
        # Explicitly unsafe loopback smoke path; never enable on an internet-facing worker.
        return run_python_dev(code)
    host_root=os.getenv('CAPSULA_WORKER_HOST_RUN_PATH','')
    container_root=os.getenv('CAPSULA_WORKER_CONTAINER_RUN_PATH','/work/runs')
    image=os.getenv('CAPSULA_WORKER_SANDBOX_IMAGE','python:3.12-alpine')
    import re
    if not host_root or not pathlib.Path(container_root).is_dir():
        return {'status':'denied','reason':'Isolated per-job runtime not configured','exit_code':None,'stdout':'','stderr':''}
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:@-]{1,127}',image):
        return {'status':'denied','reason':'Invalid sandbox image','exit_code':None,'stdout':'','stderr':''}
    with tempfile.TemporaryDirectory(prefix='capsula-task-',dir=container_root) as tmp:
        filename='task.py';(pathlib.Path(tmp)/filename).write_text(code,encoding='utf-8')
        host_file=pathlib.Path(host_root)/pathlib.Path(tmp).name/filename
        name='capsula-work-'+uuid.uuid4().hex[:16]
        cmd=['docker','run','--rm','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
             '--pids-limit','64','--memory','192m','--memory-swap','192m','--cpus','0.5','--user','65534:65534',
             '--tmpfs','/tmp:rw,noexec,nosuid,size=16m','--mount',f'type=bind,src={host_file},dst=/work/task.py,readonly',
             '--workdir','/work',image,'python','-B','/work/task.py']
        try:
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=18)
            return {'status':'completed' if run.returncode==0 else 'failed','stdout':run.stdout[:MAX_BYTES],'stderr':run.stderr[:MAX_BYTES],'exit_code':run.returncode}
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=5,check=False)
            return {'status':'failed','reason':'Sandbox timeout; terminated','stdout':'','stderr':'','exit_code':124}
        except FileNotFoundError:
            return {'status':'denied','reason':'Docker runtime unavailable; refusing unisolated execution','stdout':'','stderr':'','exit_code':None}

def run_browser(url,selector):
    from urllib.parse import urlparse
    from ipaddress import ip_address
    import socket
    u=urlparse(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):raise HTTPException(422,'Only HTTPS URLs without credentials are accepted')
    allow=[x.strip().lower() for x in os.getenv('CAPSULA_BROWSER_ALLOWLIST','').split(',') if x.strip()]
    if not allow or u.hostname.lower() not in allow:raise HTTPException(403,'Domain not in explicit browser allowlist')
    # DNS/IP checks reduce common SSRF routes, but DNS rebinding remains a concern.
    # Production requires a network egress proxy/firewall that enforces destinations.
    for item in socket.getaddrinfo(u.hostname,443):
        host=item[4][0]
        if not ip_address(host).is_global:raise HTTPException(403,'Non-public target rejected')
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:raise HTTPException(503,'Playwright is not installed')
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        try:
            context=browser.new_context(accept_downloads=False,service_workers='block',permissions=[])
            page=context.new_page()
            def block(route):
                req=route.request
                hostname=urlparse(req.url).hostname
                if hostname not in allow:route.abort()
                else:route.continue_()
            page.route('**/*',block)
            response=page.goto(url,wait_until='domcontentloaded',timeout=9000)
            if selector:page.locator(selector).first.wait_for(timeout=2000)
            title=page.title();final=page.url;text=page.locator('body').inner_text(timeout=2000)[:4000]
            return {'status':'completed','http_status':response.status if response else None,'title':title,'final_url':final,'text':text,'selector_found':bool(selector)}
        finally:browser.close()

@app.get('/health')
def health():return {'role':'isolated-worker','version':'0.4.0-alpha.1','configured':bool(TOKEN),'browser_egress_policy':'allowlist-and-network-firewall-required','python_mode':'unsafe-loopback-smoke' if os.getenv('CAPSULA_WORKER_DEV_ALLOW_UNISOLATED')=='1' else 'per-job-docker-or-deny'}

@app.post('/execute')
def execute(job:Job,authorization:str|None=Header(None)):
    auth(authorization)
    if job.kind=='python':result=run_python(job.code)
    else:result=run_browser(job.url,job.selector)
    data=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    return {'result':result,'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'worker_claim':'process-observed-within-deployed-worker-container','attestation':'not-hardware-attested'}
