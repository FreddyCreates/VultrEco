"""Security regression suite: no live external dependencies required."""
import os, json, uuid, copy, datetime, hashlib
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from capsula.integrations.federation import WorkerRegistration, FinanceIntent, GrantInput, ApprovalInput, inventory
from capsula.intelligence.inference import InferenceInput
from capsula.security.policy import evaluate
from types import SimpleNamespace
from test_api_v2 import c,auth
from capsula.api import app


def api(path,method='get',body=None,headers=auth):return getattr(c,method)(path,headers=headers,json=body) if method!='get' else c.get(path,headers=headers)

def test_security_truth():
    r=api('/api/security/posture');assert r.status_code==200
    d=r.json();assert d['execution_attested'] is False;assert d['finance_signing_enabled'] is False
    assert d['tenancy']=='single-admin';assert d['external_witness'] is False

def test_contracts_truth():
    x=api('/api/federation/contracts').json()
    assert x['external_services_verified'] is False
    for k in ('nexus','loom_cluster','pocket_agent','nova_runtime','livevault','parralax','medina_memory'):
        assert x['adapters'][k]['status']=='unconnected'

def test_worker_registration_gates(monkeypatch):
    monkeypatch.setattr(app,'WORKER_ALLOWED',set())
    r=api('/api/workers','post',{'id':'worker-tester','kind':'python','endpoint':'http://127.0.0.1:8081','capabilities':['python']})
    assert r.status_code==403
    monkeypatch.setattr(app,'WORKER_ALLOWED',{'http://127.0.0.1:8081'})
    monkeypatch.setattr(app,'WORKER_TOKEN','worker-secret')
    x=api('/api/workers','post',{'id':'worker-tester','kind':'python','endpoint':'http://127.0.0.1:8081','capabilities':['python']})
    assert x.status_code==200;assert x.json()['lease_seconds']==45
    ys=api('/api/workers').json();assert any(w['id']=='worker-tester' and w['online'] for w in ys)
    assert api('/api/workers/worker-tester/heartbeat','post',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert api('/api/workers/worker-tester/heartbeat','post',headers={'Authorization':'Bearer worker-secret'}).status_code==200
    monkeypatch.setattr(app,'WORKER_ALLOWED',set());monkeypatch.setattr(app,'WORKER_TOKEN','')

def test_approval_lifecycle():
    x=api('/api/approvals','post',{'action':'wallet_sign','scope':'capsula','payload':{'transaction':'unbroadcast'}})
    assert x.status_code==200;pid=x.json()['id'];assert x.json()['execution']=='none'
    assert any(a['id']==pid and a['status']=='pending' for a in api('/api/approvals').json())
    y=api('/api/approvals/'+pid+'/decide?decision=approve','post')
    assert y.status_code==200;assert y.json()['execution'].startswith('none')
    assert api('/api/approvals/'+pid+'/decide?decision=reject','post').status_code==409

def test_finance_proposal_never_spends():
    x=api('/api/finance/intents','post',{'recipient':'phantom-account-reference-01','amount':'12.50','asset':'USDC','chain':'solana-devnet','reason':'Bounded invoice proposal'})
    assert x.status_code==200;v=x.json();assert v['broadcast'] is False and v['signed'] is False
    assert v['status']=='proposal-only-unfunded';assert v['custody']=='none'
    assert any(y['id']==v['id'] for y in api('/api/finance/intents').json())

def test_expiring_grants():
    expiry=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(hours=1)).isoformat()
    x=api('/api/finance/grants','post',{'scope':'invoice','kind':'payment_proposal','amount_limit':'50.00','expires':expiry})
    assert x.status_code==200;id=x.json()['id'];assert x.json()['spending_authority'] is False
    args={'recipient':'phantom-account-reference-01','amount':'51','asset':'USDC','chain':'solana-devnet','reason':'Over limit','grant_id':id}
    assert api('/api/finance/intents','post',args).status_code==403
    args['amount']='10'
    assert api('/api/finance/intents','post',args).status_code==200
    assert api('/api/finance/grants/'+id+'/revoke','post').json()['revoked']
    assert api('/api/finance/intents','post',args).status_code==403
    assert api('/api/finance/grants/'+id+'/revoke','post').status_code==404

def test_governance_chain_detects_tamper():
    data=api('/api/audit').json();assert data['verified'];assert len(data['entries'])>=4
    with app.conn() as db:
        row=db.execute('SELECT seq,action FROM audit_events ORDER BY seq ASC LIMIT 1').fetchone()
        db.execute('UPDATE audit_events SET action=? WHERE seq=?',('forged',row['seq']))
    assert api('/api/audit').json()['verified'] is False
    with app.conn() as db:db.execute('UPDATE audit_events SET action=? WHERE seq=?',(row['action'],row['seq']))
    assert api('/api/audit').json()['verified'] is True

def test_inference_requires_provider(monkeypatch):
    for k in ('VULTR_INFERENCE_URL','VULTR_INFERENCE_API_KEY','VULTR_ALLOWED_MODELS'):
        monkeypatch.delenv(k,raising=False)
    r=api('/api/inference/complete','post',{'model':'test','prompt':'hello'})
    assert r.status_code==503

def test_jobs_initial_shape():
    r=api('/api/jobs');assert r.status_code==200;assert isinstance(r.json(),list)

@pytest.mark.parametrize('kind,permitted',[('browser',False),('research',False),('loom',False),('pocket-agent',False),('wallet',False),('payments',False),('python',True)])
def test_worker_does_not_imply_other_permissions(kind,permitted):
    x=evaluate(SimpleNamespace(kind=kind,code='print(1)',url='https://example.org'),True)
    assert (x['decision']=='permit') is (permitted or kind=='browser')
    assert x['authority']['financial_spend'] is False
    assert x['authority']['cross_workspace'] is False

@pytest.mark.parametrize('url',["http://example.org","file:///etc/passwd","ftp://example.org","","ws://example.org","javascript:alert(1)","http://127.0.0.1","httpsx://example.org"])
def test_browser_rejects_untrusted_schemes(url):
    x=evaluate(SimpleNamespace(kind='browser',url=url,code=''),True)
    assert x['decision']=='deny'

@pytest.mark.parametrize('amount',["-1","0x10","1e6","1.2345678","1000000000","NaN","Infinity","01,00","1 USD","12.3.4","", " "])
def test_finance_rejects_malformed_amount(amount):
    with pytest.raises(ValidationError):FinanceIntent(recipient='wallet-address-001',amount=amount,asset='USDC',chain='solana-mainnet',reason='valid reason')

@pytest.mark.parametrize('asset',["BTC","ETH","USD","USDCX","usdC","DOGE","", " USDC"])
def test_finance_rejects_unapproved_assets(asset):
    with pytest.raises(ValidationError):FinanceIntent(recipient='wallet-address-001',amount='1',asset=asset,chain='solana-mainnet',reason='valid reason')

@pytest.mark.parametrize('chain',["ethereum-mainnet","polygon","bitcoin","", "solana", "solana-testnet"])
def test_finance_rejects_unapproved_chains(chain):
    with pytest.raises(ValidationError):FinanceIntent(recipient='wallet-address-001',amount='1',asset='USDC',chain=chain,reason='valid reason')

@pytest.mark.parametrize('worker_id',["INVALID","a","ab","space worker","under_score","a/worker","a\\worker","a@host","1worker", ".worker"])
def test_worker_identity_format(worker_id):
    with pytest.raises(ValidationError):WorkerRegistration(id=worker_id,kind='python',endpoint='http://127.0.0.1:8081')

@pytest.mark.parametrize('action',["pay","send","withdraw","transfer","root","shell","unknown","", "wallet_sign_and_broadcast"])
def test_reject_unapproved_approval_actions(action):
    with pytest.raises(ValidationError):ApprovalInput(action=action,scope='example')

@pytest.mark.parametrize('tokens',[0,-1,1025,100000])
def test_inference_limits(tokens):
    with pytest.raises(ValidationError):InferenceInput(model='example',prompt='hello',max_tokens=tokens)

@pytest.mark.parametrize('days',[-1,0,8,100])
def test_grants_time_bounds(days):
    exp=(datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(days=days)).isoformat()
    x=api('/api/finance/grants','post',{'scope':'test','kind':'payment_proposal','amount_limit':'1','expires':exp})
    assert x.status_code==422
