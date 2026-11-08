import pytest
from pydantic import ValidationError
from capsula.integrations.nexus_bridge import NexusTask,Budget,compile_handoff
from tests.test_api_v2 import c,auth

def payload():
    return {'protocol':'nexus.task.v1','correlation_id':'corr-123456789','tenant':'single-admin','principal':'operator','workspace':'nexus-testing','action':'execute.python','title':'Run contained task','code':'print(42)','budget':{'seconds':5,'cpu':.2,'memory_mb':128}}

def test_nexus_admission():
    c.post('/api/workspaces',headers=auth,json={'slug':'nexus-testing','description':'Ingress checks'})
    r=c.post('/api/federation/nexus/task',headers=auth,json=payload())
    assert r.status_code==200;v=r.json()
    assert v['protocol']=='nexus.handoff.v1';assert v['correlation_id']=='corr-123456789'
    assert v['authority']['financial_spend'] is False;assert v['verified_external_runtime'] is False
    assert v['mission_status'] in ('denied','completed','failed')
    assert 'signature' in v['receipt']

def test_nexus_workspace_rejection():
    body=payload();body['workspace']='nonexistent-workspace'
    assert c.post('/api/federation/nexus/task',headers=auth,json=body).status_code==404

@pytest.mark.parametrize('change,value',[('protocol','bad.protocol'),('tenant','other'),('principal','external'),('action','execute.wallet'),('workspace','../bad')])
def test_nexus_contract_fails_closed(change,value):
    b=payload();b[change]=value
    with pytest.raises(ValidationError):NexusTask(**b)

@pytest.mark.parametrize('change,value',[('seconds',0),('seconds',19),('cpu',.8),('memory_mb',500),('max_children',1),('spend_usdc',1)])
def test_nexus_budget_fails_closed(change,value):
    b=payload();b['budget'][change]=value
    with pytest.raises(ValidationError):NexusTask(**b)
