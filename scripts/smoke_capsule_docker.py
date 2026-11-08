"""Run a REAL disposable Docker file-processing task in GitHub Actions.

This is a live container regression on a CI host, NOT evidence of Vultr VM
or hypervisor isolation. It must fail if the container, limits, or cleanup fail.
"""
import base64,hashlib,json,pathlib,tempfile,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"src"))
from capsula.execution.capsule_runtime import execute_capsule
from capsula.execution.worker_runtime import bounded_process

CODE = """import csv, json, os, socket
try:
    open('/capsula-should-not-write','w').write('bad')
    raise RuntimeError('root filesystem unexpectedly writable')
except OSError:
    pass
try:
    socket.create_connection(('1.1.1.1',53),timeout=1)
    raise RuntimeError('external network unexpectedly reachable')
except OSError:
    pass
if any(k in os.environ for k in ('CAPSULA_API_KEY','VULTR_API_KEY','CAPSULA_WORKER_TOKEN','CAPSULA_STRIPE_SECRET_KEY')):
    raise RuntimeError('controller or merchant secrets in capsule environment')
with open('/inputs/report.csv',newline='') as f:
    rows=list(csv.DictReader(f))
total=sum(int(row['amount']) for row in rows)
with open('/outputs/result.csv','w') as out:
    out.write('metric,value\\namount_total,%d\\n'%total)
print('CAPSULA file execution complete')
"""

def main():
    source=b'item,amount\napple,15\norange,27\n'
    with tempfile.TemporaryDirectory(prefix='capsula-real-docker-') as d:
        root=pathlib.Path(d)/'work';root.mkdir()
        env={'CAPSULA_WORKER_HOST_RUN_PATH':str(root),
             'CAPSULA_WORKER_CONTAINER_RUN_PATH':str(root),
             'CAPSULA_WORKER_SANDBOX_IMAGE':'python:3.12-alpine'}
        result=execute_capsule(CODE,{'report.csv':base64.b64encode(source).decode()},
                               bounded_process=bounded_process,env=env)
        if result.get('status')!='completed' or result.get('cleanup')!='verified-destroyed':
            raise RuntimeError('Real file capsule failed or cleanup unverified: '+json.dumps({
                'status':result.get('status'),'reason':result.get('reason'),
                'stderr':result.get('stderr'),'cleanup':result.get('cleanup')}))
        artifact=result.get('artifacts',{}).get('result.csv')
        if not artifact:raise RuntimeError('Output file was not collected')
        raw=base64.b64decode(artifact['base64'],validate=True)
        if raw!=b'metric,value\namount_total,42\n':
            raise RuntimeError('Actual file result differs from expected')
        if artifact['sha256']!=hashlib.sha256(raw).hexdigest():
            raise RuntimeError('Real output digest mismatch')
        if list(root.iterdir()):
            raise RuntimeError('Capsule working directory was not discarded')
        print(json.dumps({'label':'REAL_DISPOSABLE_DOCKER_CONTAINER_ON_GITHUB_RUNNER',
              'status':'PASS','input_sha256':hashlib.sha256(source).hexdigest(),
              'output_sha256':artifact['sha256'],'output_bytes':len(raw),
              'cleanup':result['cleanup'],'limited_runtime':True,
              'live_vultr_execution_verified':False,
              'hardware_attestation_verified':False},sort_keys=True))
if __name__=='__main__':main()
