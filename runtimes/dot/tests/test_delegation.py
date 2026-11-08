import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import test_runtime as base
from dot.delegation import propose, requests


class DelegationCase(unittest.TestCase):
    setUp=base.RuntimeCase.setUp
    tearDown=base.RuntimeCase.tearDown
    ready=base.RuntimeCase.ready
    def mission(self,depth=2):
        root,a,b=self.ready(),self.ready(),self.ready('gemini')
        spec={'objective':'Bounded delegated work','limits':{'wall_seconds':1800,'task_seconds':600,'max_changed_bytes':6000},
              'delegation':{'agent_pool':[a['id'],b['id']],'max_depth':depth,'max_children':2},
              'steps':[{'name':'root','agent_id':root['id'],'prompt':'Coordinate','timeout':120,'max_changed_bytes':2000}]}
        graph=self.runtime.graphs.create(spec);self.runtime.graphs.advance();return self.runtime.graphs.get(graph['id']),a,b
    def request(self,graph,agent,identity='a'*32,seconds=120,changed=1000):
        parent=self.runtime.job(graph['steps'][0]['job_id'])
        parent['delegations']=[{'id':identity,'agent_id':agent['id'],'prompt':'Implement the child task','timeout':seconds,'max_changed_bytes':changed}]
        self.runtime.save_job(parent)
    def test_agent_requested_child_runs_in_approved_separate_vm(self):
        graph,a,b=self.mission();self.request(graph,a);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(len(result['steps']),2);child=result['steps'][1]
        self.assertEqual(child['agent_id'],a['id']);self.assertEqual(child['depth'],1);self.assertIsNotNone(child['job_id'])
        self.assertTrue(result['delegation_decisions'][0]['accepted'])
        self.assertLessEqual(self.runtime.job(child['job_id'])['lease']['expires_at'],result['deadline'])
    def test_child_can_request_grandchild_but_depth_is_bounded(self):
        graph,a,b=self.mission(depth=1);self.request(graph,a);self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id']);child=self.runtime.job(graph['steps'][1]['job_id'])
        child['delegations']=[{'id':'b'*32,'agent_id':b['id'],'prompt':'Outside depth grant','timeout':60,'max_changed_bytes':1000}];self.runtime.save_job(child);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(len(result['steps']),2);self.assertEqual(result['delegation_decisions'][-1]['reason'],'maximum_depth')
    def test_recursive_grandchild_within_depth_executes(self):
        graph,a,b=self.mission(depth=2);self.request(graph,a);self.runtime.graphs.advance();graph=self.runtime.graphs.get(graph['id']);child=self.runtime.job(graph['steps'][1]['job_id'])
        child['delegations']=[{'id':'b'*32,'agent_id':b['id'],'prompt':'Grandchild task','timeout':60,'max_changed_bytes':1000}];self.runtime.save_job(child);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(len(result['steps']),3);self.assertEqual(result['steps'][2]['depth'],2);self.assertIsNotNone(result['steps'][2]['job_id'])
    def test_unapproved_vm_request_denied(self):
        graph,a,b=self.mission();unapproved=self.ready();self.request(graph,unapproved);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(len(result['steps']),1);self.assertEqual(result['delegation_decisions'][0]['reason'],'agent_not_approved')
    def test_budget_escalation_denied(self):
        graph,a,b=self.mission();self.request(graph,a,seconds=600);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(result['delegation_decisions'][0]['reason'],'time_budget');self.assertEqual(len(result['steps']),1)
    def test_duplicate_proposal_and_restart_never_reexecute(self):
        graph,a,b=self.mission();self.request(graph,a);self.runtime.graphs.advance();first=self.runtime.graphs.get(graph['id'])['steps'][1]['job_id']
        self.runtime.close();self.runtime=base.Runtime(self.config,self.backend)
        self.runtime.graphs.advance();self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(len(result['steps']),2);self.assertEqual(result['steps'][1]['job_id'],first);self.assertEqual(len(result['delegation_decisions']),1)
    def test_parent_revoke_cancels_running_descendants(self):
        graph,a,b=self.mission();self.request(graph,a);self.runtime.graphs.advance();self.runtime.graphs.cancel(graph['id']);self.runtime.graphs.advance();result=self.runtime.graphs.get(graph['id'])
        self.assertEqual(result['status'],'cancelled');self.assertTrue(all(s['status']=='cancelled' for s in result['steps']))
    def test_request_outbox_has_no_independent_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent='c'*32;folder=Path(tmp)/'jobs'/parent;folder.mkdir(parents=True);(folder/'request.json').write_text('{}')
            first=propose(tmp,parent,'bounded work','d'*32,request_id='e'*32)
            self.assertEqual(propose(tmp,parent,'bounded work','d'*32,request_id='e'*32),first)
            self.assertEqual(len(json.loads((folder/'delegations.json').read_text())),1)
            with self.assertRaises(ValueError):propose(tmp,parent,'different','d'*32,request_id='e'*32)
            with self.assertRaises(ValueError):requests([{'id':'bad','agent_id':'d'*32,'prompt':'bad'}])
