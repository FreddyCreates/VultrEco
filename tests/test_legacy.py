import os, tempfile, importlib, json, hashlib
os.environ['CAPSULA_API_KEY']='test-key'
os.environ['CAPSULA_DATA']=tempfile.mkdtemp()
from capsula.api import app
from fastapi.testclient import TestClient
c=TestClient(app.app)
h={'Authorization':'Bearer test-key'}
def test_health():
    x=c.get('/api/health');assert x.status_code==200;assert 'sandbox_ready' in x.json()
def test_auth():
    assert c.get('/api/missions').status_code==401
    assert c.get('/api/missions',headers=h).status_code==200
def test_denied_not_fake():
    x=c.post('/api/missions',headers=h,json={'title':'Browser test','kind':'browser','code':''});assert x.status_code==200
    mid=x.json()['id'];assert x.json()['status']=='denied'
    detail=c.get('/api/missions/'+mid,headers=h).json();assert detail['chain_valid'];assert len(detail['events'])==3
    assert detail['proof_valid'];assert detail['receipt']['payload']['result_digest']==app.sha(app.canonical_bytes(detail['output']))
def test_invoice_draft():
    x=c.post('/api/invoices',headers=h,json={'title':'Prototype invoice','amount':'123.45','currency':'USDC','destination':'abc'});assert x.status_code==200;assert x.json()['status']=='draft — not payable'
def test_invalid_invoice():
    assert c.post('/api/invoices',headers=h,json={'title':'x','amount':'-10','currency':'USDC'}).status_code==422
def test_static():assert c.get('/').status_code==200
def test_missing_mission():assert c.get('/api/missions/nope',headers=h).status_code==404
