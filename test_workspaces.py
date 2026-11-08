import json
from fastapi.testclient import TestClient
import app
import uuid
c=TestClient(app.app);h={'Authorization':'Bearer '+app.API_KEY}

def test_workspaces_and_encrypted_memory():
    slug='lab'+uuid.uuid4().hex[:8]
    assert c.post('/api/workspaces',headers=h,json={'slug':slug,'description':'Evidence lab'}).status_code==200
    assert c.post('/api/workspaces',headers=h,json={'slug':slug}).status_code==409
    m=c.post('/api/memory',headers=h,json={'workspace':slug,'label':'Research fact','content':'sensitive-note-alpha','origin':'research-worker'})
    assert m.status_code==200
    item=m.json();assert item['persisted'];assert item['encryption']=='AES-256-GCM'
    assert item['id'] in [r['id'] for r in c.get('/api/memory/'+slug,headers=h).json()]
    fetched=c.get('/api/memory/'+slug+'/'+item['id'],headers=h).json()
    assert fetched['content']=='sensitive-note-alpha' and fetched['digest_valid']
    with app.conn() as db:
        row=db.execute('SELECT ciphertext FROM memory WHERE id=?',(item['id'],)).fetchone()
        assert 'sensitive-note-alpha' not in row['ciphertext']
    assert c.get('/api/memory/'+slug+'/not-present',headers=h).status_code==404
    assert c.get('/api/memory/no-such-workspace',headers=h).status_code==404
    assert c.get('/api/memory/'+slug).status_code==401

def test_integrations_disconnected():
    data=c.get('/api/integrations',headers=h).json()
    for name in ('nexus','loom_cluster','pocket_agent','nova_runtime','livevault','parralax'):
        assert data[name]['status']=='unconnected'
    assert data['phantom']['status']=='browser-connection-only'
