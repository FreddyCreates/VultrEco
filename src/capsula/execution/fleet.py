"""Provider-independent bounded worker-fleet admission for CAPSULA.

This service schedules already-provisioned, allowlisted workers. It never
provisions paid machines or treats a lease as evidence of process termination.
"""
import datetime as dt
import json
import uuid

UTC = dt.timezone.utc

def utcnow():
    return dt.datetime.now(UTC)

def iso(when):
    return when.astimezone(UTC).isoformat()

def schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS fleet_limits (
        worker_id TEXT PRIMARY KEY REFERENCES workers(id),
        capacity INTEGER NOT NULL DEFAULT 1 CHECK(capacity BETWEEN 1 AND 128),
        provider TEXT NOT NULL DEFAULT 'self-hosted',
        node TEXT NOT NULL DEFAULT '',
        region TEXT NOT NULL DEFAULT '',
        draining INTEGER NOT NULL DEFAULT 0 CHECK(draining IN (0,1)),
        updated TEXT NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS fleet_slots (
        id TEXT PRIMARY KEY, worker_id TEXT NOT NULL, mission_id TEXT NOT NULL,
        kind TEXT NOT NULL, state TEXT NOT NULL,
        acquired TEXT NOT NULL, expires TEXT NOT NULL, finished TEXT NOT NULL DEFAULT '')""")
    db.execute("CREATE INDEX IF NOT EXISTS idx_fleet_slots_live ON fleet_slots(worker_id,state,expires)")

def reconcile(db, now=None):
    """Expired admission is not proof the underlying job was terminated."""
    stamp=iso(now or utcnow())
    return db.execute("UPDATE fleet_slots SET state='expired', finished=? WHERE state='active' AND expires<=?",(stamp,stamp)).rowcount

def candidates(db,kind,now=None):
    stamp=iso(now or utcnow())
    rows=db.execute("""SELECT w.*, COALESCE(l.capacity,1) capacity,
        COALESCE(l.draining,0) draining,
        COALESCE(l.provider,'self-hosted') provider,
        COALESCE(l.node,'') node, COALESCE(l.region,'') region
        FROM workers w LEFT JOIN fleet_limits l ON l.worker_id=w.id
        WHERE w.kind=? AND w.status='active' AND w.lease_expiry>?""",(kind,stamp)).fetchall()
    active={r['worker_id']:r['n'] for r in db.execute(
        "SELECT worker_id,COUNT(*) n FROM fleet_slots WHERE state='active' AND expires>? GROUP BY worker_id",(stamp,))}
    recent={r['worker_id']:r['last'] for r in db.execute(
        "SELECT worker_id, MAX(acquired) last FROM fleet_slots GROUP BY worker_id")}
    eligible=[]
    for row in rows:
        used=active.get(row['id'],0)
        if row['draining'] or used>=row['capacity']:continue
        eligible.append((used/row['capacity'],used,recent.get(row['id'],'') or '',row['id'],row))
    eligible.sort(key=lambda x:x[:4])
    return [item[-1] for item in eligible]

def peek(db,kind):
    pool=candidates(db,kind)
    return pool[0] if pool else None

def reserve(db,kind,mission_id,lease_seconds=45,now=None):
    if not (1<=lease_seconds<=3600):raise ValueError('Invalid slot lifetime')
    # Caller supplies a fresh transaction; SQLite IMMEDIATE serializes admissions.
    db.execute('BEGIN IMMEDIATE')
    now=now or utcnow()
    reconcile(db,now)
    pool=candidates(db,kind,now)
    if not pool:return None
    worker=pool[0];slot='slot_'+uuid.uuid4().hex
    expires=iso(now+dt.timedelta(seconds=lease_seconds))
    db.execute("""INSERT INTO fleet_slots(id,worker_id,mission_id,kind,state,acquired,expires,finished)
        VALUES(?,?,?,?,'active',?,?, '')""",(slot,worker['id'],mission_id,kind,iso(now),expires))
    return {'lease_id':slot,'worker':dict(worker),'expires':expires}

def complete(db,lease_id,success=True,now=None):
    result=db.execute("UPDATE fleet_slots SET state=?,finished=? WHERE id=? AND state='active'",
        ('released' if success else 'failed',iso(now or utcnow()),lease_id))
    return result.rowcount==1

def configure(db,worker_id,capacity,provider='self-hosted',node='',region='',draining=False):
    if isinstance(capacity,bool) or not isinstance(capacity,int) or not 1<=capacity<=128:
        raise ValueError('Capacity must be 1-128')
    if not all(isinstance(x,str) and len(x)<=80 for x in (provider,node,region)):
        raise ValueError('Invalid worker metadata')
    if not db.execute('SELECT 1 FROM workers WHERE id=?',(worker_id,)).fetchone():
        raise ValueError('Unknown registered worker')
    db.execute("""INSERT INTO fleet_limits(worker_id,capacity,provider,node,region,draining,updated)
        VALUES(?,?,?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET
        capacity=excluded.capacity,provider=excluded.provider,node=excluded.node,
        region=excluded.region,draining=excluded.draining,updated=excluded.updated""",
        (worker_id,capacity,provider,node,region,int(bool(draining)),iso(utcnow())))

def status(db):
    now=iso(utcnow());workers=[]
    for row in db.execute("""SELECT w.id,w.kind,w.status,w.lease_expiry,
        COALESCE(l.capacity,1) capacity, COALESCE(l.provider,'self-hosted') provider,
        COALESCE(l.node,'') node,COALESCE(l.region,'') region,
        COALESCE(l.draining,0) draining
        FROM workers w LEFT JOIN fleet_limits l ON w.id=l.worker_id ORDER BY w.id"""):
        item=dict(row);item['online']=item['status']=='active' and item['lease_expiry']>now
        item['running']=db.execute("SELECT COUNT(*) FROM fleet_slots WHERE worker_id=? AND state='active' AND expires>?",(item['id'],now)).fetchone()[0]
        item['available']=max(0,item['capacity']-item['running']) if item['online'] and not item['draining'] else 0
        workers.append(item)
    return {'workers':workers,'online':sum(x['online'] for x in workers),
        'active_slots':sum(x['running'] for x in workers),
        'available_slots':sum(x['available'] for x in workers),
        'total_capacity':sum(x['capacity'] for x in workers if x['online']),
        'scheduler':'single-controller SQLite admission, not distributed consensus',
        'attestation':'not-verified'}
