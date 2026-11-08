import base64
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import uuid
import zipfile
import test_runtime as base
from dot import guest


class ImportCase(unittest.TestCase):
    def test_actual_import_upsert_and_undo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();state=root/'state'
            (work/'main.py').write_text('before')
            with patch.object(guest,'ROOT',state),patch.object(guest,'WORK',work):
                result=guest.import_workspace({'files':{'main.py':'after','src/tool.py':'print(42)'}})
                self.assertEqual(result['imported'],2);self.assertEqual((work/'main.py').read_text(),'after')
                self.assertEqual(result['sha256']['src/tool.py'],hashlib.sha256(b'print(42)').hexdigest())
                guest.checkpoints('restore',result['checkpoint_id'])
                self.assertEqual((work/'main.py').read_text(),'before');self.assertFalse((work/'src/tool.py').exists())

    def test_import_denies_secrets_escape_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir()
            with patch.object(guest,'ROOT',root/'state'),patch.object(guest,'WORK',work):
                for name in ('../escape','/root/x','.codex/auth.json','x/../y','secret.key','auth.json','a\\b'):
                    with self.subTest(name=name),self.assertRaises(ValueError):guest.import_workspace({'files':{name:'no'}})
                with self.assertRaises(ValueError):guest.import_workspace({'files':{'large':'a'*100000}})
                (work/'link').symlink_to(root/'outside')
                with self.assertRaises(ValueError):guest.import_workspace({'files':{'link/file':'no'}})
                self.assertFalse((root/'outside').exists())


class GraphBridgeCase(unittest.TestCase):
    setUp=base.RuntimeCase.setUp
    tearDown=base.RuntimeCase.tearDown
    ready=base.RuntimeCase.ready

    def spec(self,handoff=False):
        first,second=self.ready(),self.ready()
        return {'objective':'Build and independently inspect a bounded artifact','request_key':'bridge-request-123','steps':[
            {'name':'build','agent_id':first['id'],'prompt':'Write main.py','timeout':60},
            {'name':'verify','agent_id':second['id'],'prompt':'Inspect the actual imported main.py','timeout':60,'depends_on':['build'],
             'handoffs':[{'from_step':'build','path':'main.py'}] if handoff else []}]}

    def test_mission_request_replay_and_restart(self):
        spec=self.spec();first=self.runtime.graphs.create(spec)
        self.assertEqual(self.runtime.graphs.create(spec)['id'],first['id'])
        self.runtime.close();self.runtime=base.Runtime(self.config,self.backend)
        self.assertEqual(self.runtime.graphs.create(spec)['id'],first['id'])
        with self.assertRaises(ValueError):self.runtime.graphs.create(spec|{'objective':'Conflicting grant'})
        self.assertEqual(len(self.runtime.graphs.list()),1)

    def test_provisioning_retry_cannot_allocate_extra_computers(self):
        body={'name':'Retry-safe computer','provider':'chatgpt','request_key':'provision-request-123'}
        with patch.object(self.runtime.pool,'submit') as submit:
            first=self.runtime.create(body);second=self.runtime.create(body)
        self.assertEqual(first['id'],second['id']);self.assertEqual(submit.call_count,1)
        with self.assertRaises(ValueError):self.runtime.create(body|{'provider':'gemini'})
        self.assertEqual(len(self.runtime.agents()),1)

    def test_explicit_artifact_transfer_hashes_and_budget(self):
        spec=self.spec(True);mission=self.runtime.graphs.create(spec);self.runtime.graphs.advance()
        mission=self.runtime.graphs.get(mission['id']);job=self.runtime.job(mission['steps'][0]['job_id'])
        content=b'print(42)';sha=hashlib.sha256(content).hexdigest()
        job.update(status='completed',response='Built',artifacts=[{'path':'main.py','sha256':sha,'size':len(content)}]);self.runtime.save_job(job)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:archive.writestr('main.py',content)
        original=self.backend.guest
        def transport(agent,action,*args,data=None):
            if action=='export':return {'zip_base64':base64.b64encode(payload).decode()}
            if action=='workspace_import':return {'sha256':{p:hashlib.sha256(t.encode()).hexdigest() for p,t in data['files'].items()},'checkpoint_id':'c'*32}
            return original(agent,action,*args,data=data)
        payload=data.getvalue()
        with patch.object(self.backend,'guest',side_effect=transport):self.runtime.graphs.advance()
        final=self.runtime.graphs.get(mission['id']);verify=final['steps'][1]
        self.assertEqual(verify['handoff_receipt']['hashes'],{'main.py':sha})
        self.assertIsNotNone(verify['job_id'])
        task=self.runtime.job(verify['job_id'])
        self.assertEqual(task['lease']['limits']['max_changed_bytes'],4*1024*1024-len(content))
        self.assertTrue(any(r['data']['kind']=='mission_artifacts_transferred' for r in self.runtime.receipts()))

    def test_changed_source_artifact_blocks_downstream(self):
        spec=self.spec(True);mission=self.runtime.graphs.create(spec);self.runtime.graphs.advance()
        mission=self.runtime.graphs.get(mission['id']);job=self.runtime.job(mission['steps'][0]['job_id'])
        job.update(status='completed',response='Built',artifacts=[{'path':'main.py','sha256':'0'*64,'size':9}]);self.runtime.save_job(job)
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:archive.writestr('main.py','tampered')
        with patch.object(self.backend,'guest',return_value={'zip_base64':base64.b64encode(data.getvalue()).decode()}):self.runtime.graphs.advance()
        step=self.runtime.graphs.get(mission['id'])['steps'][1]
        self.assertIsNone(step['job_id']);self.assertIn('blocked',step['waiting_reason'])

    def test_handoff_must_name_dependency_and_visible_path(self):
        for handoffs in ([{'from_step':'unknown','path':'main.py'}],[{'from_step':'build','path':'../x'}],[{'from_step':'build','path':'.env'}]):
            spec=self.spec();spec['request_key']=uuid.uuid4().hex;spec['steps'][1]['handoffs']=handoffs
            with self.assertRaises(ValueError):self.runtime.graphs.create(spec)

    def test_import_detects_older_active_job_beyond_list_window(self):
        first,other=self.ready(),self.ready();self.runtime.submit(first['id'],{'prompt':'Still active'})
        with self.runtime.connect() as db:
            for _ in range(205):
                identity=uuid.uuid4().hex
                db.execute('INSERT INTO jobs VALUES(?,?,?)',(identity,other['id'],json.dumps({'id':identity,'agent_id':other['id'],'status':'completed'})))
        with self.assertRaises(ValueError):self.runtime.import_workspace(first['id'],{'files':{'main.py':'do not overwrite'}})


if __name__=='__main__':unittest.main()
