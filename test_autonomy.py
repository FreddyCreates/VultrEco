"""Bounded self-execution, delegated capsules, scope and negative-path tests."""
import json
import uuid
import datetime as dt
import pytest
from pydantic import ValidationError
from test_api_v2 import c,auth
import app, inference
from autonomy import GoalInput, ChildInput


def req(method,path,data=None,authorized=True):
    opts={'headers':auth if authorized else {}}
    if data is not None:opts['json']=data
    return getattr(c,method)(path,**opts)


def create_agent(caps=None):
    slug='aut-'+uuid.uuid4().hex[:10]
    ws=req('post','/api/workspaces',{'slug':slug,'description':'Autonomy validation'})
    assert ws.status_code==200
    body={'workspace':slug,'name':'Bounded research agent','role':'Automated tools specialist',
          'model':'capsula-test-model','max_steps':8,'capabilities':caps or ['inference','memory','artifact','python','browser']}
    res=req('post','/api/agents',body);assert res.status_code==200
    return res.json()


def make_goal(agent,caps=None,**extras):
    base={'agent_id':agent['id'],'objective':'Complete a bounded evidence-producing task safely',
          'capabilities':caps if caps is not None else ['inference','memory','artifact'], 'max_cycles':3,
          'max_children':2,'max_steps_per_cycle':3,'interval_seconds':0,'token_budget':4096}
    base.update(extras)
    return req('post','/api/autonomy/goals',base)


def approved(goal):
    assert req('post',f"/api/approvals/{goal['approval_id']}/decide?decision=approve").status_code==200
    act=req('post',f"/api/autonomy/goals/{goal['id']}/activate")
    assert act.status_code==200
    return act.json()


def response(text,used=160):return {'status':'completed','text':text,'provider':'test-model','model':'capsula-test-model','usage':{'total_tokens':used}}


def test_autonomy_unauthorized_requests_rejected():
    assert req('get','/api/autonomy/goals',authorized=False).status_code==401
    assert req('post','/api/autonomy/goals',{'agent_id':'agt_123456789','objective':'A bounded task for the model','capabilities':['inference']},authorized=False).status_code==401
    assert req('get','/api/autonomy/playbooks',authorized=False).status_code==401
    assert req('post','/api/autonomy/scheduler/tick',authorized=False).status_code==401


def test_playbooks_cover_many_domains():
    items=req('get','/api/autonomy/playbooks').json()
    assert len(items)>=10
    assert len({x['domain'] for x in items})>=8
    assert {'engineering','browser','research','sales','hr','operations','procurement','finance','analytics'}.issubset({x['domain'] for x in items})
    assert all('risk' in p and 'capabilities' in p for p in items)
    assert all('payments' not in p['capabilities'] for p in items)


@pytest.mark.parametrize('caps', [[],['python'],['wallet','inference'],['inference','root'],['inference','inference'],['memory']])
def test_scope_validation_negative(caps):
    a=create_agent();r=make_goal(a,caps=caps)
    assert r.status_code in (403,422)


@pytest.mark.parametrize('field,value', [('max_cycles',0),('max_cycles',17),('max_children',8),
                                           ('max_steps_per_cycle',0),('max_steps_per_cycle',9),
                                           ('deadline_minutes',0),('token_budget',80),('token_budget',999999)])
def test_invalid_bounds_rejected(field,value):
    payload={'agent_id':'agent_123456789','objective':'Bounded autonomous mission task',
             'capabilities':['inference'],'max_cycles':1,field:value}
    with pytest.raises(ValidationError):GoalInput.model_validate(payload)


def test_grant_mandatory_and_activation_one_shot():
    a=create_agent();g=make_goal(a).json()
    assert g['state']=='awaiting_approval'
    assert req('post',f"/api/autonomy/goals/{g['id']}/activate").status_code==403
    assert req('post',f"/api/autonomy/goals/{g['id']}/tick").status_code==409
    a1=approved(g)
    assert a1['state']=='active'
    assert req('post',f"/api/autonomy/goals/{g['id']}/activate").status_code==409
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['objective'].startswith('Complete')
    listed=req('get','/api/autonomy/goals').json()
    found=next(x for x in listed if x['id']==g['id'])
    assert 'objective' not in found
    with app.conn() as db:
        obj=db.execute('SELECT objective FROM autonomy_goals WHERE id=?',(g['id'],)).fetchone()[0]
        assert 'Complete a bounded' not in obj


def test_successful_self_execution_with_delegated_grant(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    proposal={'status':'continue','title':'Make a research receipt','steps':[
      {'kind':'memory','title':'Keep a verified observation','content':'test-run observation','label':'observations'},
      {'kind':'artifact','title':'Produce a durable report','content':'run completed','name':'out.txt'}]}
    monkeypatch.setattr(inference,'infer',lambda data:response(json.dumps(proposal),used=150))
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==200,t.text
    d=t.json();assert d['status']=='active';assert d['run']['status']=='completed'
    assert d['run']['steps_completed']==2
    learned=req('get',f"/api/agents/{a['id']}/learning").json()
    assert any(o['run_id']==d['run']['id'] for o in learned['observations'])
    assert any(p['kind']=='procedure' for p in learned['proposals'])
    rid=d['run']['id'];r=req('get','/api/agent-runs/'+rid).json()
    assert r['state']=='completed' and r['approval_id']
    with app.conn() as db:
        approval=db.execute('SELECT status FROM approvals WHERE id=?',(r['approval_id'],)).fetchone()
        assert approval['status']=='approved'
    assert req('get','/api/audit').json()['verified']
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['cycles_done']==1
    assert req('post',f'/api/agent-runs/{rid}/execute').status_code==409


def test_model_done_not_proof_of_completion(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    monkeypatch.setattr(inference,'infer',lambda d:response('{"status":"done","summary":"I am finished"}'))
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==200
    assert t.json()['status']=='completed'
    assert t.json()['verified_completion'] is False
    assert req('post',f"/api/autonomy/goals/{g['id']}/tick").status_code==409


@pytest.mark.parametrize('malicious',[
    'not-json', '{"status":"continue","title":"Invalid","steps":[]}',
    '{"status":"continue","title":"Unauthorized","steps":[{"kind":"payments","title":"Pay now"}]}',
    '{"status":"continue","title":"Unauthorized","steps":[{"kind":"python","title":"Break scope","code":"print(1)"}]}',
    '{"status":"continue","title":"Too many","steps":[{"kind":"memory","title":"Take notes","content":"x"},{"kind":"memory","title":"Take notes","content":"x"},{"kind":"memory","title":"Take notes","content":"x"},{"kind":"memory","title":"Take notes","content":"x"}]}',
    '{"status":"continue","title":"Delegate escalation","steps":[{"kind":"memory","title":"Take notes","content":"x"}],"delegations":[{"objective":"Steal privileged capabilities","capabilities":["payments"],"max_cycles":1}]}',
])
def test_reject_model_generated_scope_escalation(monkeypatch,malicious):
    a=create_agent();g=make_goal(a).json();approved(g)
    monkeypatch.setattr(inference,'infer',lambda d:response(malicious))
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==409
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['state']=='blocked'
    assert req('post',f"/api/autonomy/goals/{g['id']}/decision",{'decision':'retry'}).status_code==200
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['state']=='active'


def test_delegation_guardrails_no_escalation_and_budget():
    a=create_agent();g=make_goal(a,max_children=2).json();approved(g)
    child_req={'objective':'Research and store bounded results safely','capabilities':['inference','artifact'],'max_cycles':2}
    r=req('post',f"/api/autonomy/goals/{g['id']}/children",child_req)
    assert r.status_code==200,r.text
    child=r.json();assert child['state']=='active' and child['parent_id']==g['id'] and child['depth']==1
    assert child['approval_id']==g['approval_id']
    assert set(child['capabilities']).issubset(set(g['capabilities']))
    parent=req('get',f"/api/autonomy/goals/{g['id']}").json()
    assert parent['children_created']==1 and parent['token_budget']<g['token_budget']
    bad=req('post',f"/api/autonomy/goals/{g['id']}/children",{**child_req,'capabilities':['inference','python']})
    assert bad.status_code==403
    child2=req('post',f"/api/autonomy/goals/{g['id']}/children",child_req)
    assert child2.status_code==200
    assert req('post',f"/api/autonomy/goals/{g['id']}/children",child_req).status_code==403
    nested=req('post',f"/api/autonomy/goals/{child['id']}/children",{**child_req,'max_cycles':1})
    assert nested.status_code==200
    assert nested.json()['depth']==2
    assert req('post',f"/api/autonomy/goals/{nested.json()['id']}/children",{**child_req,'max_cycles':1}).status_code==403


def test_model_delegations_create_child_capsules(monkeypatch):
    a=create_agent();g=make_goal(a,max_children=2).json();approved(g)
    plan={'status':'continue','title':'Create work evidence','steps':[{'kind':'artifact','title':'Record result','name':'result.txt','content':'done'}],
          'delegations':[{'objective':'Analyze related samples and store evidence','capabilities':['inference','artifact'],'max_cycles':1}]}
    monkeypatch.setattr(inference,'infer',lambda d:response(json.dumps(plan)))
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==200,t.text
    child=req('get',f"/api/autonomy/goals/{t.json()['children'][0]}").json()
    assert child['parent_id']==g['id']
    assert child['state']=='active'


def test_manual_pause_resume_cancel_blocks_execution(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    req('post',f"/api/autonomy/goals/{g['id']}/decision",{'decision':'pause'})
    assert req('post',f"/api/autonomy/goals/{g['id']}/tick").status_code==409
    req('post',f"/api/autonomy/goals/{g['id']}/decision",{'decision':'resume'})
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['state']=='active'
    req('post',f"/api/autonomy/goals/{g['id']}/decision",{'decision':'cancel'})
    assert req('post',f"/api/autonomy/goals/{g['id']}/tick").status_code==409
    assert req('post',f"/api/autonomy/goals/{g['id']}/decision",{'decision':'resume'}).status_code==409


def test_scheduler_executes_due_cycles(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    monkeypatch.setattr(inference,'infer',lambda d:response('{"status":"done","summary":"Test contract completed"}'))
    with app.conn() as db:db.execute("UPDATE autonomy_goals SET next_run='2000-01-01T00:00:00+00:00' WHERE id=?",(g['id'],))
    q=req('post','/api/autonomy/scheduler/tick')
    assert q.status_code==200
    assert req('get',f"/api/autonomy/goals/{g['id']}").json()['state']=='completed'


def test_deadline_expiry_blocks_execution(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    past=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=2)).isoformat()
    with app.conn() as db:db.execute('UPDATE autonomy_goals SET deadline=? WHERE id=?',(past,g['id']))
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==200 and t.json()['status']=='expired'


def test_missing_model_blocks_with_no_fake_execution(monkeypatch):
    a=create_agent();g=make_goal(a).json();approved(g)
    def unavailable(d):raise ValueError('Model provider not configured')
    monkeypatch.setattr(inference,'infer',unavailable)
    t=req('post',f"/api/autonomy/goals/{g['id']}/tick")
    assert t.status_code==409
    status=req('get',f"/api/autonomy/goals/{g['id']}").json()
    assert status['state']=='blocked' and 'Model provider' in status['last_error']


def test_cancelled_root_revokes_entire_descendant_tree():
    a=create_agent();root=make_goal(a,max_children=3).json();approved(root)
    body={'objective':'Summarize limited evidence for the root task',
          'capabilities':['inference','artifact'],'max_cycles':1}
    child=req('post',f"/api/autonomy/goals/{root['id']}/children",body).json()
    grandchild=req('post',f"/api/autonomy/goals/{child['id']}/children",body).json()
    assert req('post',f"/api/autonomy/goals/{root['id']}/decision",{'decision':'cancel'}).status_code==200
    for id in [root['id'],child['id'],grandchild['id']]:
        assert req('get',f'/api/autonomy/goals/{id}').json()['state']=='cancelled'
        assert req('post',f'/api/autonomy/goals/{id}/tick').status_code==409


def test_paused_parent_prevents_child_autonomous_work():
    a=create_agent();root=make_goal(a).json();approved(root)
    body={'objective':'Make bounded research observations only',
          'capabilities':['inference','artifact'],'max_cycles':1}
    child=req('post',f"/api/autonomy/goals/{root['id']}/children",body).json()
    assert req('post',f"/api/autonomy/goals/{root['id']}/decision",{'decision':'pause'}).status_code==200
    assert req('post',f"/api/autonomy/goals/{child['id']}/tick").status_code==409
    assert req('post',f"/api/autonomy/goals/{child['id']}/children",body).status_code==409
