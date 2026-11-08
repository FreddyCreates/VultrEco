from test_api_v2 import c,auth
from capsula.api import app
import json
import pytest
from pydantic import ValidationError
from capsula.evidence.artifacts import ArtifactInput

def test_create_read_sealed_artifact():
    c.post('/api/workspaces',headers=auth,json={'slug':'artifact-test','description':'Evidence artifacts'})
    b={'workspace':'artifact-test','name':'result.json','mime':'application/json','content':'{"ok":true,"count":12}'}
    r=c.post('/api/artifacts',headers=auth,json=b)
    assert r.status_code==200;obj=r.json();assert obj['encrypted'] and obj['audit_signed']
    p=c.get('/api/artifacts/'+obj['id'],headers=auth);assert p.status_code==200
    assert p.json()['content']==b['content'];assert p.json()['verified_local_integrity']
    xs=c.get('/api/artifacts?workspace=artifact-test',headers=auth).json()
    assert any(x['id']==obj['id'] for x in xs)
    with app.conn() as db:
        row=db.execute('SELECT blob FROM artifact_blobs WHERE id=?',(obj['id'],)).fetchone()
        assert b['content'] not in row['blob']

def test_artifact_tamper_detection():
    r=c.post('/api/artifacts',headers=auth,json={'workspace':'artifact-test','name':'proof.md','mime':'text/markdown','content':'Original evidence'})
    id=r.json()['id']
    with app.conn() as db:
        r=db.execute('SELECT digest FROM artifact_blobs WHERE id=?',(id,)).fetchone()
        db.execute('UPDATE artifact_blobs SET digest=? WHERE id=?',('0'*64,id))
    assert c.get('/api/artifacts/'+id,headers=auth).status_code==409
    with app.conn() as db:db.execute('UPDATE artifact_blobs SET digest=? WHERE id=?',(r['digest'],id))
    assert c.get('/api/artifacts/'+id,headers=auth).status_code==200

@pytest.mark.parametrize('name',["../../etc/passwd","a/b","..\\windows","bad name","<script>","", "a"*101])
def test_artifact_filename_rejection(name):
    with pytest.raises(ValidationError):ArtifactInput(workspace='artifact-test',name=name,mime='text/plain',content='test')

@pytest.mark.parametrize('mime',["application/octet-stream","text/html","image/svg+xml","application/javascript","image/png","", "text/xml"])
def test_artifact_mime_rejection(mime):
    with pytest.raises(ValidationError):ArtifactInput(workspace='artifact-test',name='proof.txt',mime=mime,content='test')
