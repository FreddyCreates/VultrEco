import base64
from contextlib import redirect_stdout
import hashlib
from http.client import HTTPConnection
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import uuid
import zipfile

from dot.core import Runtime, load_config
from dot.guest import checked_id, parse_output, provider_command
from dot import guest
from dot.kernel import CapabilityKernel, execution_receipt
from dot.server import make_server
from dot.vm import Libvirt


class BackendFixture:
    """TEST ONLY. Never imported or selected by the shipped runtime."""
    def __init__(self):
        self.available = True
        self.fail = False
        self.calls = []
        self.results = {}
    def doctor(self):
        return {'ready': self.available, 'missing': [], 'kvm': True, 'image': True, 'libvirt': True}
    def provision(self, agent):
        return str(uuid.uuid4())
    def state(self, agent):
        return 'running'
    def address(self, agent):
        return '192.168.122.22'
    def guest(self, agent, action, *args, data=None):
        self.calls.append((agent['id'], action, args, data))
        if self.fail:
            raise ConnectionError('SSH connection interrupted')
        if action == 'health':
            return {'protocol_version':'0.3', 'ready': True, 'firewall_receipt':True, 'versions': {'codex':'test', 'gemini':'test'}, 'auth_cache':{'chatgpt':False,'gemini':False}}
        if action == 'submit':
            self.results[data['id']] = {'id': data['id'], 'status':'running'}
            return self.results[data['id']]
        if action == 'status':
            return self.results.get(args[0], {'status':'lost'})
        if action == 'cancel':
            self.results[args[0]] = {'id': args[0], 'status':'cancelled', 'finished':time.time()}
            return self.results[args[0]]
        if action == 'export':
            return {'zip_base64':base64.b64encode(b'zip-test').decode()}
        return {}
    def start(self, agent):
        pass
    def stop(self, agent):
        pass


class RuntimeCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {'state_dir':self.temp.name+'/state','vm_root':self.temp.name+'/vms','image':self.temp.name+'/base.qcow2',
                       'image_sha256':'a'*64,'codex_version':'1.0.0','gemini_version':'1.0.0',
                       'network':'default','gateway':'192.168.122.1','subnet':'192.168.122.0/24',
                       'max_agents':8,'max_vcpus':16,'max_memory_mb':32768,'max_disk_gb':400}
        self.backend = BackendFixture()
        self.runtime = Runtime(self.config, self.backend)
    def tearDown(self):
        self.runtime.close()
        self.temp.cleanup()
    def ready(self, provider='chatgpt'):
        # A source test sets up a provisioned state; no LIVE/KVM claim is made.
        with patch.object(self.runtime.pool, 'submit'):
            a=self.runtime.create({'name':'Atlas','provider':provider})
        a['status']='ready'
        self.runtime.save_agent(a)
        return a
    def test_private_token_and_state(self):
        self.assertGreaterEqual(len(self.runtime.token),40)
        self.assertEqual(os.stat(self.runtime.root / 'owner.token').st_mode & 0o777,0o600)
        self.assertEqual(os.stat(self.runtime.root).st_mode & 0o777,0o700)
        self.assertEqual(os.stat(self.runtime.db).st_mode & 0o777,0o600)
        other=Runtime(self.config,self.backend)
        self.assertEqual(other.token,self.runtime.token)
        other.close()
    def test_unique_vm_identity_and_scopes(self):
        a,b=self.ready(),self.ready('gemini')
        self.assertNotEqual(a['id'],b['id'])
        self.assertNotEqual(a['domain'],b['domain'])
        self.assertNotEqual(Libvirt(self.config).paths(a),Libvirt(self.config).paths(b))
        self.assertEqual(a['domain'],'dot-'+a['id'])
    def test_create_rejects_invalid_inputs(self):
        bad=[{}, {'name':'A','provider':'other'}, {'name':'','provider':'chatgpt'}, {'name':'x'*61,'provider':'chatgpt'}, {'name':'x\n','provider':'chatgpt'}]
        bad += [{'name':'A','provider':'chatgpt',key:value} for key,values in [('vcpus',[0,17,True,'2',None]),('memory_mb',[0,1024,65537,False,'4096']),('disk_gb',[0,15,513,True,'32'])] for value in values]
        for body in bad:
            with self.subTest(body=body),self.assertRaises(ValueError):self.runtime.create(body)
        self.assertEqual(self.runtime.agents(),[])
    def test_host_unavailable_no_fake_agent(self):
        self.backend.available=False
        with self.assertRaises(ValueError):self.runtime.create({'name':'A','provider':'chatgpt'})
        self.assertEqual(self.runtime.agents(),[])
    def test_allocation_caps(self):
        self.runtime.config['max_agents']=1
        self.ready()
        with self.assertRaises(ValueError):self.ready()
        for limit in ('max_vcpus','max_memory_mb','max_disk_gb'):
            with self.subTest(limit=limit):
                self.runtime.config['max_agents']=8
                self.runtime.config[limit]=1
                with self.assertRaises(ValueError):self.ready()
                self.runtime.config[limit]=100000
    def test_queued_cancel_never_dispatches(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Inspect files'})
        result=self.runtime.cancel(j['id'])
        self.runtime._advance_job(j['id'])
        self.assertEqual(result['status'],'cancelled')
        self.assertFalse(any(c[1]=='submit' for c in self.backend.calls))
    def test_task_submission_validation(self):
        a=self.ready()
        cases=[{}, {'prompt':''},{'prompt':'x'*32001},{'prompt':None},{'prompt':'x','mode':'root'},
               {'prompt':'x','model':'--config=evil'},{'prompt':'x','model':'a;touch x'},
               {'prompt':'x','timeout':29},{'prompt':'x','timeout':3601},{'prompt':'x','timeout':True},
               {'prompt':'x','max_changed_bytes':0},{'prompt':'x','max_changed_bytes':True}]
        for body in cases:
            with self.subTest(body=body),self.assertRaises(ValueError):self.runtime.submit(a['id'],body)
        self.assertEqual(self.runtime.jobs(),[])
    def test_active_task_exclusion(self):
        a=self.ready();self.runtime.submit(a['id'],{'prompt':'Task one'})
        with self.assertRaises(ValueError):self.runtime.submit(a['id'],{'prompt':'Task two'})
        b=self.ready();self.assertEqual(self.runtime.submit(b['id'],{'prompt':'Other VM'})['status'],'queued')
    def test_end_to_end_control_plane_success(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Build a file'})
        self.assertEqual(j['capsula_task']['schema'],'nexus.task.v1')
        self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'running')
        self.backend.results[j['id']]={'id':j['id'],'status':'completed','response':'Done','finished':time.time(),'artifacts':[{'path':'result.txt','sha256':'b'*64}]}
        self.runtime._advance_job(j['id']);result=self.runtime.job(j['id'])
        self.assertEqual(result['status'],'completed')
        self.assertEqual(result['response'],'Done')
        self.assertEqual(result['receipt']['status'],'succeeded')
        self.assertEqual(result['receipt']['result']['artifact_hashes'],['b'*64])
        self.assertFalse(result['receipt']['metadata']['reasoning_exposed'])
    def test_interrupted_dispatch_not_repeated(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Build a file'})
        self.backend.fail=True;self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'dispatching')
        self.backend.fail=False;self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'lost')
        self.assertEqual(sum(c[1]=='submit' for c in self.backend.calls),1)
    def test_running_reconnect_and_cancel(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Run'})
        self.runtime._advance_job(j['id']);self.backend.fail=True;self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'running')
        self.backend.fail=False;self.runtime.cancel(j['id']);self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'cancelled')
    def test_restart_reattaches_running_jobs(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Run'});self.runtime._advance_job(j['id'])
        self.runtime.close();self.runtime=Runtime(self.config,self.backend,recover=True)
        self.assertEqual(self.runtime.job(j['id'])['status'],'running')
        self.runtime._advance_job(j['id'])
        self.assertEqual(sum(c[1]=='submit' for c in self.backend.calls),1)
    def test_expired_lease_denies_dispatch(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Run'})
        with patch('dot.kernel.time.time',return_value=time.time()+5000):self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'failed')
        self.assertFalse(any(c[1]=='submit' for c in self.backend.calls))
    def test_receipt_chain_and_tamper_detection(self):
        self.runtime.event('test',value=1);self.runtime.event('test',value=2)
        previous='0'*64
        for r in self.runtime.receipts():
            payload=json.dumps(r['data'],sort_keys=True,separators=(',',':'))
            self.assertEqual(r['prev'],previous)
            self.assertEqual(r['hash'],hashlib.sha256((previous+str(r['at'])+payload).encode()).hexdigest())
            previous=r['hash']
        r=self.runtime.receipts()[-1]
        self.assertNotEqual(r['hash'],hashlib.sha256((r['prev']+str(r['at'])+'tampered').encode()).hexdigest())
    def test_no_power_stop_during_work(self):
        a=self.ready();self.runtime.submit(a['id'],{'prompt':'Run'})
        with self.assertRaises(ValueError):self.runtime.power(a['id'],'stop')
    def test_unreachable_not_ready(self):
        a=self.ready();self.backend.fail=True;self.runtime._refresh_agent(a['id'])
        self.assertEqual(self.runtime.agent(a['id'])['status'],'unreachable')
        with self.assertRaises(ValueError):self.runtime.submit(a['id'],{'prompt':'Run'})
    def test_config_rejects_bad_values(self):
        cases=[('image','relative'),('image','/tmp/x,bad'),('image_sha256','x'),('codex_version','latest'),('gemini_version','1.2;evil'),('gateway','8.8.8.8'),('network','default;evil'),('max_agents',True)]
        p=Path(self.temp.name)/'config.json'
        for key,value in cases:
            with self.subTest(key=key):
                p.write_text(json.dumps({**self.config,key:value}))
                with self.assertRaises(ValueError):load_config(p)
        p.write_text(json.dumps(self.config));self.assertEqual(load_config(p)['network'],'default')


class KernelCase(unittest.TestCase):
    def setUp(self):
        self.k=CapabilityKernel('secret-test-only');self.a='a'*32;self.j='b'*32
    def test_signed_scope_and_mutation_denial(self):
        lease=self.k.issue(job_id=self.j,agent_id=self.a,timeout=60,mode='work')
        self.assertEqual(self.k.verify(lease,agent_id=self.a,job_id=self.j)['principal'],'owner')
        for key,value in [('agent_id','c'*32),('expires_at',1),('mode','root'),('request_id','c'*32),('principal','other')]:
            with self.subTest(key=key),self.assertRaises(ValueError):self.k.verify({**lease,key:value},agent_id=self.a,job_id=self.j)
        for a,j in [('c'*32,self.j),(self.a,'c'*32)]:
            with self.assertRaises(ValueError):self.k.verify(lease,agent_id=a,job_id=j)
        with patch('dot.kernel.time.time',return_value=time.time()+1000),self.assertRaises(ValueError):self.k.verify(lease,agent_id=self.a,job_id=self.j)
    def test_plan_has_no_mutation_capability(self):
        lease=self.k.issue(job_id=self.j,agent_id=self.a,timeout=60,mode='plan')
        self.assertEqual(lease['capabilities'],['workspace.read'])
        self.assertEqual(lease['limits']['max_changed_bytes'],0)
        self.assertFalse(lease['boundaries']['host_shell'])
        self.assertEqual(self.k.capsula_task(lease)['action'],'capsula.manifest.build')
    def test_sealed_capsula_hash_and_plaintext_denial(self):
        from dot.vendor.capsula_portable import content_hash
        bundle={'schema':'capsule.contract.v1','capsule':{'id':'vault-123','mode':'sealed-transfer','parent_hash':None,'created_at':'2026-10-14'},'source':{'product':'NOVASVAUL','instance_id':'test','version':'1'},'manifest':{'format':'novasvaul-encrypted-records-v1','records':0},'sealed_state':{'ciphertext_only':True,'vault_manifest':'ciphertext-envelope','records':[]},'permissions':{'default':'deny','filesystem':{},'network':{},'process':{},'wallet':{},'secrets':{}},'runtime':{'engine':'NOVASVAUL','entrypoint':'vaul','state':'read-only','compatibility':{}},'receipts':[{'type':'export','capsule_id':'vault-123','operation':'export','content_hash':'a'*64,'created_at':'2026-10-14'}]}
        bundle['manifest']['content_hash']=content_hash(bundle)
        self.assertEqual(self.k.accept_sealed(bundle,self.a)['operation'],'capsula.import.vaul')
        bundle['sealed_state']['ciphertext_only']=False
        with self.assertRaises(ValueError):self.k.accept_sealed(bundle,self.a)
        bundle['sealed_state']['ciphertext_only']=True;bundle['manifest']['content_hash']='bad'
        with self.assertRaises(ValueError):self.k.accept_sealed(bundle,self.a)
    def test_identifiers_reject_traversal_and_shell_payloads(self):
        bad=['','../x','a'*31,'a'*33,'A'*32,';touch /tmp/x','$(id)','a'*31+'/','a'*31+'\n',None,22,'a'*32+'\0']
        for value in bad:
            with self.subTest(value=value),self.assertRaises(ValueError):checked_id(value)
        self.assertEqual(checked_id('a'*32),'a'*32)


class GuestCase(unittest.TestCase):
    def test_provider_commands_and_parser(self):
        self.assertIn('workspace-write',provider_command('chatgpt'))
        self.assertIn('read-only',provider_command('chatgpt',mode='plan'))
        self.assertIn('yolo',provider_command('gemini'))
        self.assertIn('plan',provider_command('gemini',mode='plan'))
        with self.assertRaises(ValueError):provider_command('unknown')
        codex='\n'.join(map(json.dumps,[{'type':'item.completed','item':{'type':'agent_message','text':'done'}},{'type':'turn.completed','usage':{'input_tokens':4}}]))
        self.assertEqual(parse_output('chatgpt',codex),('done',{'input_tokens':4}))
        self.assertEqual(parse_output('gemini','{"response":"done","stats":{}}'),('done',{}))
        cases=[('chatgpt',''),('chatgpt','{"type":"turn.failed"}'),('chatgpt','{"type":"turn.completed"}'),('gemini','{}'),('gemini','{"error":"quota"}'),('gemini','not json')]
        for provider,text in cases:
            with self.subTest(provider=provider,text=text),self.assertRaises((ValueError,RuntimeError)):parse_output(provider,text)
    def test_real_subprocess_execution_and_artifact_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'workspace';work.mkdir();jobs=root/'state'/'jobs'
            cli=root/'codex';cli.write_text('#!/usr/bin/env python3\nimport json,sys\nsys.stdin.read()\nopen("result.txt","w").write("verified artifact")\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"done"}}))\nprint(json.dumps({"type":"turn.completed","usage":{}}))\n');cli.chmod(0o755)
            j='d'*32;(jobs/j).mkdir(parents=True)
            req={'provider':'chatgpt','prompt':'Make result','timeout':30,'mode':'work','lease':{'limits':{'max_changed_bytes':1000}}}
            (jobs/j/'request.json').write_text(json.dumps(req))
            with patch.object(guest,'ROOT',root/'state'),patch.object(guest,'WORK',work),patch.dict(os.environ,{'PATH':str(root)+':'+os.environ['PATH']}):
                guest.run_job(j);result=json.loads((jobs/j/'result.json').read_text())
                self.assertEqual(result['status'],'completed')
                self.assertEqual(result['artifacts'][0]['sha256'],hashlib.sha256(b'verified artifact').hexdigest())
                self.assertEqual(result['changed_bytes'],17)
                archive=guest.export_workspace()
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(archive['zip_base64']))) as z:self.assertEqual(z.read('result.txt'),b'verified artifact')
    def test_symlink_escape_excluded_from_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();(root/'secret').write_text('private');(work/'leak').symlink_to(root/'secret');(work/'.env').write_text('private');(work/'safe.txt').write_text('public')
            with patch.object(guest,'WORK',work):
                manifest=guest.workspace_manifest()
                self.assertNotIn('leak',[x['path'] for x in manifest])
                self.assertIn('.env',[x['path'] for x in manifest])
                with zipfile.ZipFile(io.BytesIO(base64.b64decode(guest.export_workspace()['zip_base64']))) as z:self.assertEqual(z.namelist(),['safe.txt'])
    def test_budget_accounts_deletions_and_modifications(self):
        before=[{'path':'a','size':10,'sha256':'a'},{'path':'b','size':20,'sha256':'b'}]
        after=[{'path':'b','size':20,'sha256':'c'},{'path':'c','size':30,'sha256':'d'}]
        self.assertEqual(guest.changed_bytes(before,after),60)


class HTTPCase(unittest.TestCase):
    setUp = RuntimeCase.setUp
    tearDown = RuntimeCase.tearDown
    def test_http_auth_origin_and_paths(self):
        server=make_server(self.runtime,0);thread=threading.Thread(target=server.serve_forever);thread.start()
        def request(path,method='GET',body=None,headers=None):
            conn=HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            conn.request(method,path,body,headers or {});r=conn.getresponse();data=r.read();code=r.status;conn.close();return code,data
        try:
            self.assertEqual(request('/')[0],200)
            self.assertEqual(request('/app.js')[0],200)
            self.assertEqual(request('/api/state')[0],401)
            good={'Authorization':'Bearer '+self.runtime.token}
            self.assertEqual(request('/api/state',headers=good)[0],200)
            self.assertEqual(request('/api/state',headers={**good,'Host':'evil.example'})[0],403)
            self.assertEqual(request('/api/state',headers={**good,'Origin':'http://evil.example'})[0],403)
            self.assertEqual(request('/api/state',headers={'Authorization':'Bearer wrong'})[0],401)
            self.assertEqual(request('/../../etc/passwd',headers=good)[0],404)
            self.assertEqual(request('/api/agents','POST','{}',good)[0],400)
            self.assertEqual(request('/api/agents','POST','[]',{**good,'Content-Type':'application/json'})[0],400)
            self.assertEqual(request('/api/agents','POST','not json',{**good,'Content-Type':'application/json'})[0],400)
            self.assertEqual(request('/api/host',headers=good)[0],200)
            self.assertEqual(request('/api/receipts',headers=good)[0],200)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__=='__main__':unittest.main()
