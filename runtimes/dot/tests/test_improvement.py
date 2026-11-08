import hashlib
import json
from pathlib import Path
import tempfile
import time
import sys
import threading
import unittest
from unittest.mock import patch

from dot.improvement import ImprovementLab, tree

REGRESSION = '''import pathlib,sys
p=pathlib.Path(sys.argv[1])/'procedure.py'
ns={};exec(p.read_text(),ns)
assert ns['answer'](2)==4
'''
HOLDOUT = REGRESSION + "assert ns['answer'](3)==6\n"


class ImprovementCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.work = self.root/'work'; self.work.mkdir()
        (self.work/'procedure.py').write_text('def answer(x):\n    return 4\n')
        self.lab = ImprovementLab(self.root/'lab', self.work)

    def tearDown(self):
        self.tmp.cleanup()

    def create(self, **kwargs):
        return self.lab.create('Generalize the procedure', ['procedure.py'], REGRESSION, HOLDOUT, **kwargs)

    def fix(self, c):
        (self.lab._folder(c['id'])/'candidate/procedure.py').write_text('def answer(x):\n    return x * 2\n')

    def test_real_holdout_promotion_and_rollback(self):
        c = self.create(); self.fix(c)
        evaluated = self.lab.evaluate(c['id'])
        self.assertEqual(evaluated['status'], 'verified')
        trial = evaluated['trials'][0]['checks']
        self.assertTrue(trial['baseline_regression']['passed'])
        self.assertFalse(trial['baseline_holdout']['passed'])
        self.assertTrue(trial['candidate_holdout']['passed'])
        self.assertEqual(self.lab.promote(c['id'])['status'], 'promoted')
        self.assertIn('x * 2', (self.work/'procedure.py').read_text())
        self.assertEqual(self.lab.rollback(c['id'])['status'], 'rolled_back')
        self.assertIn('return 4', (self.work/'procedure.py').read_text())

    def test_rejected_trial_preserved_then_valid_retry(self):
        c=self.create(); folder=self.lab._folder(c['id'])
        (folder/'candidate/procedure.py').write_text('def answer(x):\n    return 7\n')
        self.assertEqual(self.lab.evaluate(c['id'])['status'], 'rejected')
        self.fix(c)
        result=self.lab.evaluate(c['id'])
        self.assertEqual(result['status'],'verified'); self.assertEqual(len(result['trials']),2)
        self.assertEqual(result['trials'][0]['status'],'rejected')

    def test_unchanged_copy_not_improvement(self):
        c=self.create()
        with self.assertRaises(ValueError): self.lab.evaluate(c['id'])

    def test_pass_everything_without_gain_rejected(self):
        c=self.lab.create('No measured gain',['procedure.py'],REGRESSION,REGRESSION)
        self.fix(c)
        self.assertEqual(self.lab.evaluate(c['id'])['status'],'rejected')

    def test_regression_cannot_be_traded_for_holdout(self):
        c=self.create(); (self.lab._folder(c['id'])/'candidate/procedure.py').write_text('def answer(x):\n    return 6\n')
        self.assertEqual(self.lab.evaluate(c['id'])['status'],'rejected')

    def test_no_unverified_promotion(self):
        c=self.create();self.fix(c)
        with self.assertRaises(ValueError): self.lab.promote(c['id'])

    def test_out_of_scope_edit_rejected(self):
        c=self.create();self.fix(c)
        (self.lab._folder(c['id'])/'candidate/extra.py').write_text('print(1)')
        with self.assertRaises(ValueError): self.lab.evaluate(c['id'])

    def test_verifier_tampering_rejected(self):
        c=self.create();self.fix(c)
        (self.lab._folder(c['id'])/'holdout.py').write_text('pass')
        with self.assertRaises(ValueError): self.lab.evaluate(c['id'])

    def test_baseline_tampering_rejected(self):
        c=self.create();self.fix(c)
        (self.lab._folder(c['id'])/'baseline/procedure.py').write_text('pass')
        with self.assertRaises(ValueError): self.lab.evaluate(c['id'])

    def test_candidate_changed_after_verification(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id'])
        (self.lab._folder(c['id'])/'candidate/procedure.py').write_text('def answer(x): return 0')
        with self.assertRaises(ValueError): self.lab.promote(c['id'])

    def test_live_workspace_change_blocks_promotion(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id'])
        (self.work/'new.txt').write_text('later work')
        with self.assertRaises(ValueError): self.lab.promote(c['id'])
        self.assertEqual((self.work/'new.txt').read_text(),'later work')

    def test_live_workspace_change_blocks_destructive_rollback(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id']);self.lab.promote(c['id'])
        (self.work/'new.txt').write_text('later work')
        with self.assertRaises(ValueError): self.lab.rollback(c['id'])

    def test_expiry_revocation_and_attempt_budget(self):
        c=self.create(lease_seconds=1);self.fix(c)
        with patch('dot.improvement.time.time',return_value=time.time()+10):
            with self.assertRaises(ValueError):self.lab.evaluate(c['id'])
        c=self.create();self.fix(c);self.lab.revoke(c['id'])
        with self.assertRaises(ValueError):self.lab.evaluate(c['id'])
        c=self.create(attempts=1);self.fix(c);self.lab.evaluate(c['id'])
        with self.assertRaises(ValueError):self.lab.evaluate(c['id'])

    def test_byte_budget(self):
        c=self.create(max_changed_bytes=1);self.fix(c)
        with self.assertRaises(ValueError):self.lab.evaluate(c['id'])

    def test_timeout_and_no_verifier_mutation(self):
        c=self.lab.create('Bound verifier',['procedure.py'],REGRESSION,'import time;time.sleep(10)',seconds=1)
        self.fix(c);self.assertEqual(self.lab.evaluate(c['id'])['status'],'rejected')
        mutate="import pathlib,sys\n(pathlib.Path(sys.argv[1])/'procedure.py').write_text('changed')\n"
        c=self.lab.create('No checker edits',['procedure.py'],REGRESSION,mutate)
        self.fix(c);result=self.lab.evaluate(c['id']);self.assertEqual(result['status'],'rejected')
        self.assertIn('Baseline changed',result['evaluation_error'])

    def test_secrets_and_symlinks_refused(self):
        for name in ('.env','auth.json','key.pem'):
            (self.work/name).write_text('secret')
            with self.assertRaises(ValueError):self.create()
            (self.work/name).unlink()
        (self.work/'link').symlink_to(self.root/'outside')
        with self.assertRaises(ValueError):self.create()

    def test_state_nesting_and_path_traversal(self):
        with self.assertRaises(ValueError):ImprovementLab(self.work/'state',self.work)
        for name in ('../other','/etc/passwd','.env'):
            with self.assertRaises(ValueError):self.lab.create('No escape',[name],REGRESSION,HOLDOUT)
        with self.assertRaises(ValueError):self.lab.get('../capsule')

    def test_promotion_failure_rolls_back(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id'])
        with patch('dot.improvement.shutil.copy2',side_effect=OSError('injected write failure')):
            with self.assertRaises(OSError):self.lab.promote(c['id'])
        self.assertIn('return 4',(self.work/'procedure.py').read_text())
        self.assertEqual(self.lab.get(c['id'])['status'],'recovered')

    def test_restart_recovers_interrupted_promotion(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id'])
        from dot.checkpoint import Checkpoints
        store=Checkpoints(self.lab.state/'recovery',self.work)
        c=self.lab.get(c['id']);c.update(status='promoting',undo_checkpoint=store.create()['id']);self.lab._save(c)
        (self.work/'procedure.py').write_text('partial')
        fresh=ImprovementLab(self.lab.state,self.work)
        with self.assertRaises(ValueError):fresh.evaluate(c['id'])
        self.assertIn('return 4',(self.work/'procedure.py').read_text())
        self.assertEqual(fresh.get(c['id'])['status'],'recovered')

    def test_observation_has_no_authority_or_raw_prompt(self):
        record=self.lab.observe('a'*32,'failed',hashlib.sha256(b'result').hexdigest())
        self.assertEqual(record['authority'],'none');self.assertFalse(record['acceptance_verified'])
        self.assertNotIn('prompt',record);self.assertNotIn('response',record)

    def test_scope_and_tenant_are_durable(self):
        c=self.create(scope='enterprise',tenant='team-a')
        fresh=ImprovementLab(self.lab.state,self.work).get(c['id'])
        self.assertEqual(fresh['scope'],'enterprise');self.assertEqual(fresh['tenant'],'team-a')

    def test_candidate_editor_invalidates_previous_verification(self):
        c=self.create();self.fix(c);self.lab.evaluate(c['id'])
        self.lab.edit(c['id'],'procedure.py','def answer(x): return x * 2\n')
        self.assertEqual(self.lab.get(c['id'])['status'],'proposed')
        with self.assertRaises(ValueError):self.lab.promote(c['id'])
        with self.assertRaises(ValueError):self.lab.edit(c['id'],'outside.py','pass')

    def test_only_exact_promoted_skills_advertised(self):
        path='skills/active/double/SKILL.md'
        regression='import pathlib,sys\nassert (pathlib.Path(sys.argv[1])/"procedure.py").exists()\n'
        holdout='import pathlib,sys\nassert (pathlib.Path(sys.argv[1])/"'+path+'").read_text()=="verified procedure"\n'
        c=self.lab.create('Retain a procedure',[path],regression,holdout)
        self.lab.edit(c['id'],path,'verified procedure')
        self.assertEqual(self.lab.context()['verified_procedure_paths'],[])
        self.lab.evaluate(c['id']);self.lab.promote(c['id'])
        self.assertEqual(self.lab.context()['verified_procedure_paths'],[path])
        (self.work/path).write_text('later unverified edit')
        self.assertEqual(self.lab.context()['verified_procedure_paths'],[])
        (self.lab._folder(c['id'])/'candidate'/path).write_text('later unverified edit')
        self.assertEqual(self.lab.context()['verified_procedure_paths'],[])


class GuestLearningCase(unittest.TestCase):
    def test_real_job_writes_hash_only_observation(self):
        from dot import guest
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();state=root/'state'
            identity='b'*32;folder=state/'jobs'/identity;folder.mkdir(parents=True)
            job={'provider':'chatgpt','prompt':'private user prompt not retained in learning', 'mode':'work','timeout':30,
                 'lease':{'expires_at':time.time()+30,'limits':{'max_changed_bytes':1000}},
                 'acceptance':{'files':[{'path':'answer.txt','contains':'done'}]}}
            (folder/'request.json').write_text(json.dumps(job))
            code='from pathlib import Path\nimport json\nPath("answer.txt").write_text("done")\nprint(json.dumps({"type":"item.completed","item":{"type":"agent_message","text":"done"}}))\nprint(json.dumps({"type":"turn.completed"}))\n'
            with patch.object(guest,'ROOT',state),patch.object(guest,'WORK',work),patch.object(guest,'provider_command',return_value=[sys.executable,'-c',code]):
                guest.run_job(identity)
            result=json.loads((folder/'result.json').read_text())
            self.assertEqual(result['status'],'completed')
            observation=json.loads((state/'improvement/observations'/(identity+'.json')).read_text())
            self.assertTrue(observation['acceptance_verified']);self.assertEqual(observation['authority'],'none')
            self.assertNotIn('private user prompt',json.dumps(observation))

    def test_guest_http_budget_guard(self):
        from dot import guest
        with tempfile.TemporaryDirectory() as tmp,patch.object(guest,'ROOT',Path(tmp)/'state'),patch.object(guest,'WORK',Path(tmp)/'work'):
            with self.assertRaises(ValueError):guest.improvement({'action':'create','spec':{'seconds':31}})


class ImprovementHTTPCase(unittest.TestCase):
    def test_authenticated_owner_flow_runs_real_verifiers(self):
        from http.client import HTTPConnection
        import test_runtime as base
        from dot import guest
        from dot.server import make_server
        fixture=base.RuntimeCase();fixture.setUp()
        server=None
        try:
            agent=fixture.ready();root=Path(fixture.temp.name);work=root/'guest-work';work.mkdir()
            (work/'procedure.py').write_text('def answer(x): return 4\n')
            server=make_server(fixture.runtime,0)
            thread=threading.Thread(target=server.serve_forever);thread.start()
            def call(body,authorized=True):
                conn=HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                headers={'Content-Type':'application/json'}
                if authorized:headers['Authorization']='Bearer '+fixture.runtime.token
                conn.request('POST','/api/agents/'+agent['id']+'/improvement',json.dumps(body),headers)
                response=conn.getresponse();result=json.loads(response.read());code=response.status;conn.close()
                return code,result
            with patch.object(guest,'ROOT',root/'guest-state'),patch.object(guest,'WORK',work),patch.object(fixture.backend,'guest',side_effect=lambda a,action,*args,data=None:guest.improvement(data)):
                self.assertEqual(call({'action':'list'},False)[0],401)
                self.assertEqual(call({'action':'execute-arbitrary-host-code'})[0],400)
                code,c=call({'action':'create','spec':{'objective':'Fix doubling','allowed_paths':['procedure.py'],'regression':REGRESSION,'holdout':HOLDOUT,'seconds':30}})
                self.assertEqual(code,200)
                self.assertEqual(call({'action':'edit','id':c['id'],'path':'procedure.py','content':'def answer(x): return x * 2\n'})[0],200)
                code,trial=call({'action':'evaluate','id':c['id']});self.assertEqual(code,200);self.assertEqual(trial['status'],'verified')
                self.assertEqual(call({'action':'promote','id':c['id']})[1]['status'],'promoted')
                self.assertEqual(call({'action':'rollback','id':c['id']})[1]['status'],'rolled_back')
                self.assertEqual(len(call({'action':'list'})[1]['capsules']),1)
                self.assertTrue(any(e['data']['kind']=='improvement_promote' for e in fixture.runtime.receipts()))
        finally:
            if server:server.shutdown();server.server_close();thread.join()
            fixture.tearDown()


if __name__=='__main__':unittest.main()
