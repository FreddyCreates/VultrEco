import os, tempfile, json, sqlite3, copy
os.environ['CAPSULA_DATA']=tempfile.mkdtemp(prefix='capsula-v2-tests-')
os.environ['CAPSULA_API_KEY']='test-key'
import app
from fastapi.testclient import TestClient
c=TestClient(app.app);auth={'Authorization':'Bearer test-key'}

def create(kind='browser',code=''):
    x=c.post('/api/missions',headers=auth,json={'title':'Verification mission','kind':kind,'code':code})
    assert x.status_code==200
    return x.json()['id']

def test_release_identity():
    h=c.get('/api/health').json();assert h['version']=='0.6.0-alpha.1';assert h['proof_protocol']=='capsula.proof.v2'
    pk=c.get('/api/proof/public-key').json();assert pk['algorithm']=='Ed25519';assert pk['key_id']==h['signing_key_id']

def test_evidence_integrity():
    mid=create()
    doc=c.get('/api/missions/'+mid,headers=auth).json()
    assert doc['chain_valid'] and doc['proof_valid']
    ev=c.get('/api/missions/'+mid+'/evidence',headers=auth).json()
    assert ev['verified'] and ev['inclusion']['verified']
    assert ev['trust_level']=='operator-signed'
    assert 'hardware-attestation' in ev['not_verified']
    for k in ('signature','public_key','payload'):assert k in ev['receipt']
    assert ev['receipt']['payload']['policy']['decision']=='deny'
    assert ev['receipt']['payload']['execution_claim']=='not-executed'
    with app.conn() as db:
        r=db.execute('SELECT input,output FROM missions WHERE id=?',(mid,)).fetchone()
        assert 'Verification mission' not in r['input'];assert 'execution adapter not activated' not in r['output']

def test_db_event_tamper_detected():
    mid=create();assert c.get('/api/missions/'+mid,headers=auth).json()['proof_valid']
    with app.conn() as db:db.execute("UPDATE events SET type='policy.permit' WHERE mission_id=? AND type='policy.decision'",(mid,))
    data=c.get('/api/missions/'+mid,headers=auth).json()
    assert not data['proof_valid'] and not data['chain_valid']

def test_receipt_tamper_detected():
    mid=create()
    with app.conn() as db:
        row=db.execute('SELECT receipt FROM missions WHERE id=?',(mid,)).fetchone()
        receipt=json.loads(row['receipt']);receipt['payload']['status']='completed'
        db.execute('UPDATE missions SET receipt=? WHERE id=?',(json.dumps(receipt),mid))
    assert not c.get('/api/missions/'+mid,headers=auth).json()['proof_valid']

def test_capabilities_truthful():
    r=c.get('/api/capabilities',headers=auth).json();assert not r['finance_enabled']
    assert r['capabilities']['python']['implemented']
    for k in ('browser','research','loom','pocket-agent','wallet','payments'):assert not r['capabilities'][k]['implemented']

def test_auth_v2():
    assert c.get('/api/capabilities').status_code==401
    assert c.get('/api/missions/nope/evidence',headers=auth).status_code==404
