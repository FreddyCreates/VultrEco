"""Loopback-only integration smoke test. NOT evidence of container or VM isolation."""
import os,sys,time,socket,subprocess,tempfile,uuid,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
port=18800 + (os.getpid()%1000)
url=f'http://127.0.0.1:{port}'
os.environ['CAPSULA_DATA']=tempfile.mkdtemp(prefix='capsula-smoke-')
os.environ['CAPSULA_API_KEY']='local-smoke-key'
os.environ['CAPSULA_WORKER_ALLOWED_ENDPOINTS']=url
os.environ['CAPSULA_WORKER_TOKEN']='local-smoke-worker-token'
os.environ['CAPSULA_WORKER_DEV_ALLOW_UNISOLATED']='1' # trusted literal smoke code only; never deployed
worker=subprocess.Popen([sys.executable,'-m','uvicorn','capsula.execution.worker_runtime:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
try:
    import httpx
    for _ in range(40):
        try:
            if httpx.get(url+'/health',timeout=.2,trust_env=False).status_code==200:break
        except httpx.HTTPError:pass
        time.sleep(.1)
    else:raise RuntimeError('Worker failed to boot')
    from capsula.api import app
    from fastapi.testclient import TestClient
    client=TestClient(app.app)
    auth={'Authorization':'Bearer local-smoke-key'}
    r=client.post('/api/workers',headers=auth,json={'id':'smoke-worker-1','kind':'python','endpoint':url,'capabilities':['python']});assert r.status_code==200,r.text
    r=client.post('/api/missions',headers=auth,json={'title':'Loopback worker smoke execution','kind':'python','code':'print(6*7)'});assert r.status_code==200,r.text
    response=r.json();assert response['status']=='completed',response
    mid=response['id'];detail=client.get('/api/missions/'+mid,headers=auth).json()
    assert detail['output']['stdout'].strip()=='42';assert detail['proof_valid']
    jobs=client.get('/api/jobs',headers=auth).json();assert len(jobs)==1 and jobs[0]['status']=='completed'
    print(json.dumps({'smoke':'PASS','mission_id':mid,'worker_execution':'loopback-real-process','result':detail['output']['stdout'].strip(),'signed_receipt_valid':detail['proof_valid'],'sandbox_attested':False,'production_isolation_verified':False}))
finally:
    worker.terminate()
    try:worker.wait(timeout=5)
    except subprocess.TimeoutExpired:worker.kill()
