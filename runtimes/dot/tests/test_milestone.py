import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dot.checkpoint import Checkpoints, workspace_guard
from dot.computer import validate_actions
from dot.verification import validate_checks, verify, evidence_matches
import test_runtime as base


class CheckpointCase(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.work=self.root/'work';self.work.mkdir();self.store=Checkpoints(self.root/'state',self.work)
    def tearDown(self): self.temp.cleanup()
    def test_roundtrip_and_undo(self):
        (self.work/'a.txt').write_text('before');(self.work/'empty').mkdir();(self.work/'run.sh').write_text('exit 0');(self.work/'run.sh').chmod(0o700)
        first=self.store.create();(self.work/'a.txt').write_text('after');(self.work/'new.txt').write_text('new')
        result=self.store.restore(first['id'])
        self.assertEqual((self.work/'a.txt').read_text(),'before');self.assertFalse((self.work/'new.txt').exists());self.assertTrue((self.work/'empty').is_dir());self.assertTrue(os.access(self.work/'run.sh',os.X_OK))
        self.store.restore(result['undo_checkpoint']);self.assertEqual((self.work/'a.txt').read_text(),'after');self.assertTrue((self.work/'new.txt').exists())
    def test_credential_directory_outside_workspace_not_snapshotted(self):
        (self.root/'auth.json').write_text('secret');(self.work/'safe').write_text('ok')
        manifest=self.store.create();self.assertEqual([x['path'] for x in manifest['files']],['safe'])
    def test_symlinks_rejected(self):
        (self.work/'leak').symlink_to(self.root/'secret')
        with self.assertRaises(ValueError):self.store.create()
    def test_corruption_preserves_current_workspace(self):
        (self.work/'a').write_text('good');manifest=self.store.create();(self.work/'a').write_text('current')
        (self.store.blobs/manifest['files'][0]['sha256']).write_text('tampered')
        with self.assertRaises(ValueError):self.store.restore(manifest['id'])
        self.assertEqual((self.work/'a').read_text(),'current')
    def test_bad_manifest_paths_cannot_escape(self):
        (self.work/'a').write_text('ok');manifest=self.store.create();path=self.store.manifests/(manifest['id']+'.json')
        manifest['files'][0]['path']='../outside';path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):self.store.restore(manifest['id'])
        self.assertFalse((self.root/'outside').exists());self.assertEqual((self.work/'a').read_text(),'ok')
    def test_restore_failure_between_renames_recovers_old_workspace(self):
        (self.work/'a').write_text('before');checkpoint=self.store.create();(self.work/'a').write_text('current')
        replace=os.replace
        def fail_stage(source,destination):
            if '.stage-' in str(source):raise OSError('Injected power loss between directory renames')
            return replace(source,destination)
        with patch('dot.checkpoint.os.replace',side_effect=fail_stage),self.assertRaises(OSError):self.store.restore(checkpoint['id'])
        self.assertEqual((self.work/'a').read_text(),'current');self.assertFalse((self.store.root/'restore-journal.json').exists())
    def test_workspace_lock_refuses_concurrent_mutation(self):
        with workspace_guard(self.root/'state'):
            with self.assertRaises(ValueError):
                with workspace_guard(self.root/'state'):pass
    def test_real_local_recovery_exercise(self):
        spec=importlib.util.spec_from_file_location('recovery_script',Path(__file__).resolve().parents[1]/'scripts/exercise_recovery.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        result=module.exercise(self.root/'exercise')
        self.assertEqual(result['status'],'local_recovery_verified');self.assertEqual(result['phases'][1]['exit_code'],-15);self.assertFalse(result['phases'][2]['acceptance']['passed']);self.assertTrue(result['phases'][3]['acceptance']['passed']);self.assertFalse(result['subscription_inference_verified'])


class VerificationCase(unittest.TestCase):
    def test_real_command_success_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            contract={'commands':[['python3','-c','print("actual check")']]}
            result=verify(tmp,contract,time.time()+5)
            self.assertTrue(result['passed']);self.assertTrue(evidence_matches(contract,result))
            self.assertFalse(verify(tmp,{'commands':[['python3','-c','raise SystemExit(7)']]},time.time()+5)['passed'])
    def test_false_passing_flag_rejected(self):
        contract={'commands':[['python3','-m','unittest']]}
        self.assertFalse(evidence_matches(contract,{'passed':True,'checks':[]}))
        self.assertFalse(evidence_matches(contract,{'passed':True,'checks':[{'argv':['npm','test'],'passed':True,'exit_code':0}]}))
        self.assertFalse(evidence_matches(contract,{'passed':True,'checks':[{'argv':['python3','-m','unittest'],'passed':True,'exit_code':1}]}))
    def test_unsafe_and_unbounded_check_requests_rejected(self):
        cases=[{'commands':['python3 -c whatever']},{'commands':[['bash','-c','echo hi']]},{'files':[{'path':'../../secret'}]},{'files':[{'path':'/etc/passwd'}]},{'commands':[[]]},{'files':[{'path':'a','contains':True}]}]
        for item in cases:
            with self.subTest(item=item),self.assertRaises(ValueError):validate_checks(item)
    def test_timeout_stops_real_check_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(subprocess.TimeoutExpired):verify(tmp,{'commands':[['python3','-c','import time; time.sleep(30)']]},time.time()+0.1)
    def test_browser_actions_reject_private_ips_and_nonweb_schemes(self):
        for url in ('file:///etc/passwd','http://169.254.169.254/','http://10.0.0.1/','http://u:p@example.com','javascript:alert(1)'):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_actions({'actions':[{'action':'goto','url':url}]})
        self.assertEqual(validate_actions({'actions':[{'action':'goto','url':'http://127.0.0.1:3000'}]})['actions'][0]['action'],'goto')


class MissionCase(unittest.TestCase):
    setUp=base.RuntimeCase.setUp;tearDown=base.RuntimeCase.tearDown;ready=base.RuntimeCase.ready
    def spec(self):
        a,b=self.ready(),self.ready('gemini')
        return {'objective':'Build then review','limits':{'task_seconds':120,'wall_seconds':600,'max_changed_bytes':2000},'steps':[
            {'name':'build','agent_id':a['id'],'prompt':'Build','timeout':60,'max_changed_bytes':1000},
            {'name':'review','agent_id':b['id'],'prompt':'Review','timeout':60,'max_changed_bytes':1000,'depends_on':['build']}]}
    def test_persistent_goal_context_and_optimistic_revision(self):
        a=self.ready();mission=self.runtime.mission(a['id'],{'objective':'Finish project','notes':'Preserve tests'})
        j=self.runtime.submit(a['id'],{'prompt':'Continue'})
        self.assertEqual(j['mission_context']['objective'],'Finish project')
        with self.assertRaises(ValueError):self.runtime.mission(a['id'],{'objective':'Overwrite','revision':0})
        self.runtime.close();self.runtime=base.Runtime(self.config,self.backend)
        self.assertEqual(self.runtime.agent(a['id'])['mission']['revision'],1)
    def test_graph_dispatches_dependencies_only_after_success(self):
        graph=self.runtime.graphs.create(self.spec());self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id'])
        self.assertIsNotNone(graph['steps'][0]['job_id']);self.assertIsNone(graph['steps'][1]['job_id'])
        j=self.runtime.job(graph['steps'][0]['job_id']);j.update(status='completed',response='Built and checked');self.runtime.save_job(j)
        self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id'])
        self.assertIsNotNone(graph['steps'][1]['job_id']);self.assertIn('Built and checked',self.runtime.job(graph['steps'][1]['job_id'])['prompt'])
    def test_graph_survives_restart_without_duplicate_jobs(self):
        graph=self.runtime.graphs.create(self.spec());self.runtime.graphs.advance();first=self.runtime.graphs.get(graph['id'])['steps'][0]['job_id']
        self.runtime.close();self.runtime=base.Runtime(self.config,self.backend);self.runtime.graphs.advance()
        self.assertEqual(self.runtime.graphs.get(graph['id'])['steps'][0]['job_id'],first);self.assertEqual(len(self.runtime.jobs()),1)
    def test_graph_rejects_cycles_shared_vms_and_budget_escalation(self):
        spec=self.spec();spec['steps'][0]['depends_on']=['review']
        with self.assertRaises(ValueError):self.runtime.graphs.create(spec)
        spec['steps'][0]['depends_on']=[];spec['steps'][1]['agent_id']=spec['steps'][0]['agent_id']
        with self.assertRaises(ValueError):self.runtime.graphs.create(spec)
        spec=self.spec();spec['limits']['task_seconds']=30
        with self.assertRaises(ValueError):self.runtime.graphs.create(spec)
    def test_parent_cancellation_prevents_future_dispatch(self):
        graph=self.runtime.graphs.create(self.spec());self.runtime.graphs.advance();self.runtime.graphs.cancel(graph['id']);self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id'])
        self.assertEqual(graph['status'],'cancelled');self.assertIsNone(graph['steps'][1]['job_id'])
    def test_deadline_expiry_never_dispatches(self):
        graph=self.runtime.graphs.create(self.spec());graph['deadline']=time.time()-1;self.runtime.graphs.save(graph);self.runtime.graphs.advance()
        self.assertEqual(self.runtime.graphs.get(graph['id'])['status'],'expired');self.assertEqual(self.runtime.jobs(),[])
    def test_failed_step_cancels_undispatched_dependents(self):
        graph=self.runtime.graphs.create(self.spec());self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id']);job=self.runtime.job(graph['steps'][0]['job_id']);job['status']='failed';self.runtime.save_job(job);self.runtime.graphs.advance()
        graph=self.runtime.graphs.get(graph['id']);self.assertEqual(graph['status'],'failed');self.assertEqual(graph['steps'][1]['status'],'cancelled')
    def test_host_rejects_completed_job_missing_requested_checks(self):
        a=self.ready();job=self.runtime.submit(a['id'],{'prompt':'Test it','acceptance':{'commands':[['python3','-m','unittest']]}});self.runtime._advance_job(job['id']);self.backend.results[job['id']]={'id':job['id'],'status':'completed','response':'Trust me'};self.runtime._advance_job(job['id']);self.assertEqual(self.runtime.job(job['id'])['status'],'failed')
    def test_restore_refused_while_task_active(self):
        a=self.ready();self.runtime.submit(a['id'],{'prompt':'Working'})
        with self.assertRaises(ValueError):self.runtime.workspace_action(a['id'],'restore','a'*32)
