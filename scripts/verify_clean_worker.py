#!/usr/bin/env python3
"""Actual worker acceptance; no fixture transport or controller-side code executor.

Run against an operator-owned, separately isolated disposable Python worker.
The optional /probe inspection endpoints exist only in build_worker_probe.py.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def verify(endpoint,token_file,out,inspect_bootstrap=False):
    import httpx
    out=Path(out).resolve();out.mkdir(parents=True,exist_ok=False)
    token=Path(token_file).read_text().strip()
    owner=secrets.token_urlsafe(40)
    os.environ.update(CAPSULA_DATA=str(out/'controller-data'),CAPSULA_API_KEY=owner,
        CAPSULA_WORKER_TOKEN=token,CAPSULA_WORKER_ALLOWED_ENDPOINTS=endpoint,
        CAPSULA_ALLOW_DIRECT_DOCKER='0',CONTROLLER_ONLY_CANARY=secrets.token_urlsafe(40))
    os.environ.pop('CAPSULA_WORKER_DEV_ALLOW_UNISOLATED',None)
    import app,platform_routes
    from fastapi.testclient import TestClient
    client=TestClient(app.app);headers={'Authorization':'Bearer '+owner}
    def api(method,path,body=None):
        result=getattr(client,method)('/api/'+path,headers=headers,**({'json':body} if body is not None else {}))
        if result.status_code!=200:raise RuntimeError(path+' rejected: '+str(result.status_code))
        return result.json()
    with httpx.Client(timeout=2,trust_env=False) as direct:
        for _ in range(180):
            try:
                if direct.get(endpoint+'/health').status_code==200:break
            except httpx.HTTPError:pass
            time.sleep(1)
        else:raise RuntimeError('Disposable worker did not become ready')
    api('post','workers',{'id':'clean-verifier','kind':'python','endpoint':endpoint,'capabilities':['python']})
    with httpx.Client(timeout=24,trust_env=False) as direct:
        first=direct.post(endpoint+'/execute',headers={'Authorization':'Bearer '+token},json={'kind':'python','code':'print(42)'})
        first.raise_for_status();result=first.json()['result']
    if result.get('status')!='completed' or result.get('stdout')!='42\n':
        (out/'preflight-failure.json').write_text(json.dumps(result,indent=2))
        raise RuntimeError('Clean worker execution preflight failed: '+str(result.get('stderr',''))[-2000:])
    stop=threading.Event()
    def heartbeat():
        while not stop.wait(8):
            result=client.post('/api/workers/clean-verifier/heartbeat',headers={'Authorization':'Bearer '+token})
            if result.status_code!=200:break
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start()
    try:
        workspace='clean-worker-proof'
        api('post','workspaces',{'slug':workspace,'description':'Actual isolated worker evidence'})
        agent=api('post','agents',{'workspace':workspace,'name':'Actual improvement verifier','capabilities':['python','memory','artifact']})
        aid=agent['id']
        api('post','agents/'+aid+'/continuity',{'objective':'Improve only when frozen cases pass; retain failures','expected_revision':0})
        api('post','project-files',{'workspace':workspace,'path':'main.py','content':'print(4)\n','expected_revision':0})
        capsule=api('post','improvements',{'agent_id':aid,'objective':'Generalize doubling with a measured distinguishing input',
            'request_key':'actual-worker-improvement','source_paths':['main.py'],'allowed_paths':['main.py'],'entrypoint':'main.py',
            'seconds':300,'cases':[{'name':'existing','kind':'regression','stdin':'2','stdout':'4\n'},
                                   {'name':'new','kind':'holdout','stdin':'3','stdout':'6\n'}]})
        identity=capsule['id']
        api('post','improvements/'+identity+'/candidate',{'files':{'main.py':'print(7)\n'}})
        rejected=api('post','improvements/'+identity+'/evaluate')
        assert rejected['status']=='rejected',rejected['status']
        api('post','improvements/'+identity+'/candidate',{'files':{'main.py':'import sys\nprint(int(sys.stdin.read())*2)\n'}})
        passed=api('post','improvements/'+identity+'/evaluate')
        assert passed['status']=='verified',passed['trials'][-1]
        assert len(passed['trials'])==2 and passed['trials'][0]['status']=='rejected'
        promoted=api('post','improvements/'+identity+'/promote');assert promoted['status']=='promoted'
        rolled=api('post','improvements/'+identity+'/rollback');assert rolled['status']=='rolled_back'
        containment='''import os,json,pathlib,socket
r={'uid':os.getuid(),'controller_key_present':'CAPSULA_API_KEY' in os.environ,'worker_token_present':'CAPSULA_WORKER_TOKEN' in os.environ,'controller_canary_present':'CONTROLLER_ONLY_CANARY' in os.environ,'controller_path_visible':pathlib.Path('/controller-only-canary').exists()}
for k in ('memory.max','cpu.max','pids.max'):
 p=pathlib.Path('/sys/fs/cgroup')/k;r[k]=p.read_text().strip() if p.exists() else None
try:pathlib.Path('/capsula-host-write').write_text('deny');r['root_write_denied']=False
except OSError:r['root_write_denied']=True
try:s=socket.create_connection(('1.1.1.1',443),timeout=.3);s.close();r['network_denied']=False
except OSError:r['network_denied']=True
print(json.dumps(r))
'''
        isolated=platform_routes.isolated_trial(app,containment,identity,'candidate','containment-boundary')
        assert isolated['status']=='completed',isolated
        measured=json.loads(isolated['stdout'])
        assert measured['uid']==65534 and measured['root_write_denied'] and measured['network_denied']
        assert measured['memory.max']=='201326592' and measured['cpu.max']=='50000 100000' and measured['pids.max']=='64',measured
        assert not any(measured[k] for k in ('controller_key_present','worker_token_present','controller_canary_present','controller_path_visible'))
        run=api('post','agents/'+aid+'/runs',{'title':'Persist the verified experiment','approval_required':False,
            'steps':[{'kind':'memory','title':'Keep outcome','content':'Actual clean worker experiment passed; negative trial retained'}]})
        outcome=api('post','agent-runs/'+run['id']+'/execute');assert outcome['status']=='completed'
        state=api('get','agents/'+aid+'/learning');assert state['proposals'] and state['observations']
        audit=api('get','audit');assert audit['verified']
        report={'schema':'capsula.clean-worker-acceptance.v1','status':'verified','transport':'actual HTTP worker; no fixture executor',
            'capsule_id':identity,'negative_trial_retained':True,'trials':passed['trials'],'promotion':promoted['status'],
            'rollback':rolled['status'],'containment':measured,'automatic_learning_observations':len(state['observations']),
            'automatic_procedure_drafts':len(state['proposals']),'audit_verified':audit['verified'],'audit_public_key':audit['public_key'],
            'vultr_deployment_verified':False,'provider_inference_verified':False,'hardware_kvm_verified':False,
            'source_sha256':{name:hashlib.sha256((Path(__file__).resolve().parents[1]/name).read_bytes()).hexdigest()
                for name in ('app.py','worker_runtime.py','improvement_lab.py','learning.py','platform_routes.py')}}
        if inspect_bootstrap:
            with httpx.Client(timeout=15,trust_env=False) as direct:
                response=direct.get(endpoint+'/probe/proof',headers={'Authorization':'Bearer '+token});response.raise_for_status()
            evidence=response.json();assert evidence['uid']==1000 and evidence['active_containers']==[]
            runs=[argv for argv in evidence['calls'] if argv and argv[0]=='run']
            assert len(runs)>=9
            for argv in runs:
                for flag in ('--rm','--read-only','--cap-drop','--pids-limit','--memory','--memory-swap','--cpus','--user'):
                    assert flag in argv,flag
                assert argv[argv.index('--network')+1]=='none' and argv[argv.index('--user')+1]=='65534:65534'
            report['worker_vm']=evidence
        (out/'receipt.json').write_text(json.dumps(report,indent=2))
        print(json.dumps({'status':report['status'],'trials':len(passed['trials']),'containment':measured,'receipt':str(out/'receipt.json')}),flush=True)
        return report
    finally:
        stop.set();thread.join(timeout=2)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--endpoint',required=True);parser.add_argument('--token-file',required=True);parser.add_argument('--out',required=True);parser.add_argument('--inspect-bootstrap',action='store_true')
    args=parser.parse_args();verify(args.endpoint,args.token_file,args.out,args.inspect_bootstrap)
