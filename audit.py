"""Independent, signed governance audit statements. Local integrity, not external truth."""
import json, hashlib, uuid, datetime
from proof import canon, sha

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS audit_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, ts TEXT NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL, payload TEXT NOT NULL, prev_hash TEXT NOT NULL, event_hash TEXT NOT NULL, signature TEXT NOT NULL)')

def append(db,signer,action,subject,payload,actor='single-admin'):
    previous=db.execute('SELECT event_hash FROM audit_events ORDER BY seq DESC LIMIT 1').fetchone()
    prev_hash=previous['event_hash'] if previous else '0'*64
    ts=datetime.datetime.now(datetime.timezone.utc).isoformat()
    statement={'protocol':'capsula.governance-evidence.v1','id':uuid.uuid4().hex,'ts':ts,'actor':actor,'action':action,'subject':subject,'payload':payload,'prev_hash':prev_hash}
    event_hash=sha(canon(statement))
    sig=signer.sign(statement)
    db.execute('INSERT INTO audit_events(id,ts,actor,action,subject,payload,prev_hash,event_hash,signature) VALUES(?,?,?,?,?,?,?,?,?)',(statement['id'],ts,actor,action,subject,json.dumps(payload,sort_keys=True,separators=(',',':')),prev_hash,event_hash,sig))
    return {'statement':statement,'event_hash':event_hash,'signature':sig,'key_id':signer.key_id}

def verify(rows,signer):
    previous='0'*64
    for r in rows:
        statement={'protocol':'capsula.governance-evidence.v1','id':r['id'],'ts':r['ts'],'actor':r['actor'],'action':r['action'],'subject':r['subject'],'payload':json.loads(r['payload']),'prev_hash':r['prev_hash']}
        if statement['prev_hash']!=previous:return False
        if r['event_hash']!=sha(canon(statement)):return False
        if not signer.verify(statement,r['signature']):return False
        previous=r['event_hash']
    return True
