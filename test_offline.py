from fastapi.testclient import TestClient
import app
from verify_evidence import verify
import copy
c=TestClient(app.app);h={'Authorization':'Bearer '+app.API_KEY}

def test_offline_pinned_verification():
    r=c.post('/api/missions',json={'title':'Offline receipt validation','kind':'browser'},headers=h)
    assert r.status_code==200
    e=c.get('/api/missions/'+r.json()['id']+'/evidence',headers=h).json()
    pinned=app.signer.public()['public_key']
    assert verify(e,pinned)
    assert not verify(e,pinned+'wrong')
    broken=copy.deepcopy(e);broken['output']['reason']='different';assert not verify(broken,pinned)
    broken=copy.deepcopy(e);broken['events'][0]['type']='changed';assert not verify(broken,pinned)
    broken=copy.deepcopy(e);broken['receipt']['payload']['event_count']=88;assert not verify(broken,pinned)
    broken=copy.deepcopy(e);broken['inclusion']['path']=[{'position':'left','hash':'0'*64}];assert not verify(broken,pinned)
