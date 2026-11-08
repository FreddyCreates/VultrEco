"""Remote disposable worker. Requires separate network/VM identity; no host Docker socket."""
import os, subprocess, tempfile, pathlib, uuid, json, hmac, hashlib, time, sys, selectors
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from typing import Literal

app=FastAPI(title='CAPSULA bounded worker',version='0.6.0-alpha.1')
TOKEN=os.getenv('CAPSULA_WORKER_TOKEN','')
MAX_BYTES=24_000


def bounded_process(argv,timeout=18,output_limit=1024*1024):
    """Bound pipe memory while the process is running, not after capture_output."""
    proc=subprocess.Popen(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    output={'stdout':bytearray(),'stderr':bytearray()};total=0;reason=''
    deadline=time.monotonic()+timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout,selectors.EVENT_READ,'stdout');selector.register(proc.stderr,selectors.EVENT_READ,'stderr')
            while selector.get_map():
                if time.monotonic()>=deadline:reason='Execution timed out';break
                for key,_ in selector.select(timeout=.05):
                    data=os.read(key.fileobj.fileno(),32768)
                    if not data:selector.unregister(key.fileobj);continue
                    total+=len(data)
                    remaining=max(0,MAX_BYTES-len(output[key.data]))
                    output[key.data].extend(data[:remaining])
                    if total>output_limit:reason='Execution output limit exceeded';break
                if reason:break
        if reason:
            proc.kill();proc.wait(timeout=5)
        else:
            proc.wait(timeout=max(.01,deadline-time.monotonic()))
    except BaseException:
        if proc.poll() is None:proc.kill();proc.wait(timeout=5)
        raise
    finally:
        proc.stdout.close();proc.stderr.close()
    return {'status':'failed' if reason or proc.returncode else 'completed',
        'exit_code':124 if reason=='Execution timed out' else 125 if reason else proc.returncode,
        'stdout':output['stdout'].decode(errors='replace'),'stderr':output['stderr'].decode(errors='replace'),
        **({'reason':reason} if reason else {})}
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
            result=subprocess.run([sys.executable,'-I','-B',str(p)],cwd=tmp,env={'PATH':'/usr/local/bin:/usr/bin:/bin','HOME':tmp,'PYTHONNOUSERSITE':'1'},capture_output=True,text=True,timeout=9,preexec_fn=preexec)
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
            result=bounded_process(cmd)
            if result.get('reason'):
                subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=5,check=False)
            return result
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=5,check=False)
            return {'status':'failed','reason':'Sandbox timeout; terminated','stdout':'','stderr':'','exit_code':124}
        except FileNotFoundError:
            return {'status':'denied','reason':'Docker runtime unavailable; refusing unisolated execution','stdout':'','stderr':'','exit_code':None}

def run_browser(url,selector):
    """Browser tasks are disposable containers, never a long-lived Playwright process."""
    from urllib.parse import urlparse
    from ipaddress import ip_address
    import socket,re
    u=urlparse(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise HTTPException(422,'Only HTTPS URLs without credentials are accepted')
    allowed=[x.strip().lower() for x in os.getenv('CAPSULA_BROWSER_ALLOWLIST','').split(',') if x.strip()]
    if not allowed or u.hostname.lower() not in allowed:
        raise HTTPException(403,'Browser origin is not operator allowlisted')
    for item in socket.getaddrinfo(u.hostname,443):
        if not ip_address(item[4][0]).is_global:raise HTTPException(403,'Private or reserved address forbidden')
    root=os.getenv('CAPSULA_WORKER_CONTAINER_RUN_PATH','/work/runs')
    host_root=os.getenv('CAPSULA_WORKER_HOST_RUN_PATH','')
    docker_net=os.getenv('CAPSULA_BROWSER_NETWORK','')
    image=os.getenv('CAPSULA_BROWSER_SANDBOX_IMAGE','capsula-browser:local')
    # An application allowlist cannot replace a network-enforced egress gateway.
    if (not host_root or not pathlib.Path(root).is_dir() or not docker_net
            or os.getenv('CAPSULA_BROWSER_EGRESS_ENFORCED')!='1'):
        return {'status':'denied','reason':'Disposable browser runtime and egress firewall required',
                'stdout':'','stderr':'','exit_code':None}
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,60}',docker_net) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:@-]{1,127}',image):
        return {'status':'denied','reason':'Unapproved browser runtime configuration','stdout':'','stderr':'','exit_code':None}
    with tempfile.TemporaryDirectory(prefix='capsula-browser-',dir=root) as directory:
        path=pathlib.Path(directory)/'job.json';path.write_text(json.dumps({'url':url,'selector':selector,'allowed_hosts':allowed}))
        host_file=pathlib.Path(host_root)/pathlib.Path(directory).name/'job.json'
        name='capsula-browser-'+uuid.uuid4().hex[:16]
        cmd=['docker','run','--rm','--name',name,'--network',docker_net,'--read-only',
             '--cap-drop','ALL','--security-opt','no-new-privileges',
             '--pids-limit','128','--memory','768m','--memory-swap','768m','--cpus','1',
             '--user','10001:10001','--tmpfs','/tmp:rw,nosuid,size=128m',
             '--mount',f'type=bind,src={host_file},dst=/work/job.json,readonly',image,'/work/job.json']
        try:
            run=subprocess.run(cmd,capture_output=True,text=True,timeout=32)
            if run.returncode!=0:
                return {'status':'failed','reason':'Disposable browser task failed','stdout':'','stderr':run.stderr[:2000],'exit_code':run.returncode}
            data=json.loads(run.stdout)
            if not isinstance(data,dict) or data.get('status') not in ('completed','failed'):
                raise ValueError('Invalid disposable browser response')
            return data
        except subprocess.TimeoutExpired:
            subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=5,check=False)
            return {'status':'failed','reason':'Browser timeout; container destroyed','stdout':'','stderr':'','exit_code':124}
        except (FileNotFoundError,ValueError,json.JSONDecodeError):
            return {'status':'denied','reason':'Browser container unavailable or malformed response',
                    'stdout':'','stderr':'','exit_code':None}

@app.get('/health')
def health():return {'role':'isolated-worker','node_id':os.getenv('CAPSULA_WORKER_NODE_ID','unconfigured'),'version':'0.6.0-alpha.1','configured':bool(TOKEN),'browser_egress_policy':'allowlist-and-network-firewall-required','python_mode':'unsafe-loopback-smoke' if os.getenv('CAPSULA_WORKER_DEV_ALLOW_UNISOLATED')=='1' else 'per-job-docker-or-deny'}

@app.post('/execute')
def execute(job:Job,authorization:str|None=Header(None)):
    auth(authorization)
    if job.kind=='python':result=run_python(job.code)
    else:result=run_browser(job.url,job.selector)
    data=json.dumps(result,sort_keys=True,separators=(',',':')).encode()
    return {'result':result,'digest':'sha256:'+hashlib.sha256(data).hexdigest(),'worker_claim':'process-observed-within-deployed-worker-container','attestation':'not-hardware-attested'}
