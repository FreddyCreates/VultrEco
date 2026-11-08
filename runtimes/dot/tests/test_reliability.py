import concurrent.futures
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from dot import guest
from dot.core import Runtime
from dot.outcomes import validate_outcome
from dot.vm import Libvirt
import test_runtime as runtime_tests


class ReliabilityCase(unittest.TestCase):
    setUp = runtime_tests.RuntimeCase.setUp
    tearDown = runtime_tests.RuntimeCase.tearDown
    ready = runtime_tests.RuntimeCase.ready

    def test_request_replay_returns_same_task_even_after_completion_or_vm_stop(self):
        a=self.ready();body={'prompt':'Write a report','request_key':'request-0001'}
        j=self.runtime.submit(a['id'],body)
        self.assertEqual(self.runtime.submit(a['id'],body)['id'],j['id'])
        self.runtime.cancel(j['id']);a['status']='stopped';self.runtime.save_agent(a)
        self.assertEqual(self.runtime.submit(a['id'],body)['id'],j['id'])
        self.assertEqual(len(self.runtime.jobs()),1)

    def test_request_key_conflict_cannot_replace_authorized_task(self):
        a=self.ready();self.runtime.submit(a['id'],{'prompt':'First','request_key':'request-0001'})
        with self.assertRaises(ValueError):self.runtime.submit(a['id'],{'prompt':'Changed','request_key':'request-0001'})
        self.assertEqual(self.runtime.jobs()[0]['prompt'],'First')

    def test_concurrent_retries_make_only_one_job(self):
        a=self.ready();body={'prompt':'Only once','request_key':'request-0002'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            jobs=list(pool.map(lambda _:self.runtime.submit(a['id'],body),range(16)))
        self.assertEqual(len({j['id'] for j in jobs}),1)
        self.assertEqual(len(self.runtime.jobs()),1)

    def test_request_key_is_scoped_to_agent_and_survives_restart(self):
        a=self.ready();b=self.ready();body={'prompt':'Do it','request_key':'request-0003'}
        j=self.runtime.submit(a['id'],body);k=self.runtime.submit(b['id'],body)
        self.assertNotEqual(j['id'],k['id'])
        self.runtime.close();self.runtime=Runtime(self.config,self.backend)
        self.assertEqual(self.runtime.submit(a['id'],body)['id'],j['id'])

    def test_cancel_during_disconnect_is_durable_and_retries_after_restart(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Long task'})
        self.runtime._advance_job(j['id']);self.backend.fail=True
        self.assertEqual(self.runtime.cancel(j['id'])['status'],'cancelling')
        self.assertIn('connection_error',self.runtime.job(j['id']))
        self.runtime.close();self.runtime=Runtime(self.config,self.backend,recover=True)
        self.backend.fail=False;self.runtime._advance_job(j['id'])
        self.assertEqual(self.runtime.job(j['id'])['status'],'cancelled')
        self.assertEqual(self.runtime.job(j['id'])['receipt']['status'],'cancelled')

    def test_guest_cannot_overwrite_host_authority(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Original task'})
        self.runtime._advance_job(j['id'])
        self.backend.results[j['id']]={'id':j['id'],'status':'completed','response':'Done','agent_id':'e'*32,'provider':'evil','lease':{},'prompt':'Changed','receipt':{'status':'fake'},'capsula_task':{}}
        self.runtime._advance_job(j['id']);result=self.runtime.job(j['id'])
        self.assertEqual(result['agent_id'],a['id'])
        self.assertEqual(result['provider'],'chatgpt')
        self.assertEqual(result['prompt'],'Original task')
        self.assertEqual(result['lease'],j['lease'])
        self.assertEqual(result['capsula_task'],j['capsula_task'])
        self.assertEqual(result['receipt']['schema'],'pocket.execution-receipt.v1')

    def test_wrong_job_result_does_not_complete_task(self):
        a=self.ready();j=self.runtime.submit(a['id'],{'prompt':'Run'})
        self.runtime._advance_job(j['id']);self.backend.results[j['id']]={'id':'f'*32,'status':'completed','response':'Wrong job'}
        self.runtime._advance_job(j['id']);result=self.runtime.job(j['id'])
        self.assertEqual(result['status'],'running')
        self.assertIn('identity mismatch',result['connection_error'])
        self.assertNotIn('receipt',result)

    def test_reconcile_adopts_only_inspected_identity_without_provisioning_again(self):
        a=self.ready();a.update(status='error',error='Restart during provisioning');self.runtime.save_agent(a)
        with patch.object(self.backend,'inspect',create=True,return_value={'domain_uuid':'domain-123','power_state':'running'}):
            result=self.runtime.reconcile(a['id'])
        self.assertEqual(result['status'],'booting')
        self.assertNotIn('error',result)
        self.assertEqual(result['domain_uuid'],'domain-123')
        self.assertTrue(any(r['data']['kind']=='vm_reconciled' for r in self.runtime.receipts()))

    def test_reconcile_rejection_preserves_error_state(self):
        a=self.ready();a['status']='error';self.runtime.save_agent(a)
        with patch.object(self.backend,'inspect',create=True,side_effect=ValueError('Wrong disk')):
            with self.assertRaises(ValueError):self.runtime.reconcile(a['id'])
        self.assertEqual(self.runtime.agent(a['id'])['status'],'error')

    def test_independent_runtime_writers_preserve_one_receipt_chain(self):
        other=Runtime(self.config,self.backend)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                list(pool.map(lambda i:(self.runtime if i%2 else other).event('parallel',index=i),range(24)))
            previous='0'*64
            for r in self.runtime.receipts():
                self.assertEqual(r['prev'],previous)
                payload=json.dumps(r['data'],sort_keys=True,separators=(',',':'))
                self.assertEqual(r['hash'],hashlib.sha256((previous+str(r['at'])+payload).encode()).hexdigest())
                previous=r['hash']
        finally:other.close()


class OutcomeCase(unittest.TestCase):
    def test_invalid_outcomes_rejected(self):
        job='a'*32
        cases=[None,[],{'status':'done'},{'id':'b'*32,'status':'running'},{'status':'completed','response':''},
               {'status':'failed','finished':float('nan')},{'status':'failed','started':True},
               {'status':'completed','response':'ok','changed_bytes':-1}]
        cases += [{'status':'completed','response':'ok','artifacts':[{'path':p,'sha256':'a'*64}]} for p in ['../secret','/etc/passwd','a/../b','a//b','a\\b','x\x00y']]
        for value in cases:
            with self.subTest(value=value),self.assertRaises(ValueError):validate_outcome(value,job)

    def test_export_rejects_symlink_swap_after_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);work=root/'work';work.mkdir();safe=work/'report.txt';safe.write_text('safe');secret=root/'secret';secret.write_text('do not export')
            with patch.object(guest,'WORK',work):
                manifest=guest.workspace_manifest();safe.unlink();safe.symlink_to(secret)
                with patch.object(guest,'workspace_manifest',return_value=manifest),self.assertRaises(OSError):guest.export_workspace()

    def test_export_rejects_file_change_after_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            work=Path(tmp);(work/'a').write_text('old')
            with patch.object(guest,'WORK',work):
                manifest=guest.workspace_manifest();(work/'a').write_text('new')
                with patch.object(guest,'workspace_manifest',return_value=manifest),self.assertRaises(ValueError):guest.export_workspace()

    def test_vm_inspection_checks_disk_and_uuid(self):
        backend=Libvirt({'vm_root':'/tmp/dot-vms'})
        agent={'id':'a'*32,'domain':'dot-'+'a'*32,'domain_uuid':'uuid1'}
        expected=str(backend.paths(agent)/'disk.qcow2')
        def xml(path,identity='uuid1'):
            return f'<domain><name>{agent["domain"]}</name><uuid>{identity}</uuid><devices><disk device="disk"><source file="{path}"/></disk></devices></domain>'
        with patch.object(backend,'virsh',side_effect=[xml(expected),'running']):self.assertEqual(backend.inspect(agent)['domain_uuid'],'uuid1')
        for value in (xml('/tmp/other-disk'),xml(expected,'wrong-uuid')):
            with patch.object(backend,'virsh',return_value=value),self.assertRaises(ValueError):backend.inspect(agent)
