"""Multiple workers, quota admission, draining and replay are exercised locally."""
import datetime as dt
import sqlite3
import tempfile
import threading
from capsula.execution import fleet
from capsula.integrations.federation import schema as worker_schema

def fresh():
    path=tempfile.mktemp(suffix='.sqlite')
    db=sqlite3.connect(path,timeout=30)
    db.row_factory=sqlite3.Row
    worker_schema(db);fleet.schema(db)
    stamp=fleet.iso(fleet.utcnow());expiry=fleet.iso(fleet.utcnow()+dt.timedelta(seconds=90))
    for name in ('alpha','beta','gamma'):
        db.execute('INSERT INTO workers VALUES(?,?,?,?,?,?,?,?)',(name,'python','https://'+name+'.example.com','["python"]','active',stamp,stamp,expiry))
    db.commit()
    return db,path

def slot(db,mission,seconds=45,now=None):
    db.commit()
    r=fleet.reserve(db,'python',mission,lease_seconds=seconds,now=now)
    db.commit()
    return r

def test_five_slots_distributed_across_three_workers():
    db,_=fresh()
    fleet.configure(db,'alpha',2,node='first')
    fleet.configure(db,'beta',2,node='second')
    db.commit()
    allocations=[slot(db,str(i)) for i in range(5)]
    assert all(allocations)
    assert len({x['worker']['id'] for x in allocations})==3
    assert slot(db,'overloaded') is None
    assert fleet.status(db)['active_slots']==5
    assert fleet.complete(db,allocations[0]['lease_id'])
    assert not fleet.complete(db,allocations[0]['lease_id'])
    assert slot(db,'again')
    db.close()

def test_draining_excludes_new_placements():
    db,_=fresh()
    first=slot(db,'first')
    fleet.configure(db,first['worker']['id'],1,draining=True)
    db.commit()
    next_job=slot(db,'second')
    assert next_job['worker']['id']!=first['worker']['id']
    assert fleet.complete(db,first['lease_id'])
    db.close()

def test_reconcile_keeps_remote_termination_unproven():
    db,_=fresh()
    start=fleet.utcnow()
    first=slot(db,'expiring',seconds=1,now=start)
    assert fleet.reconcile(db,start+dt.timedelta(seconds=2))==1
    assert not fleet.complete(db,first['lease_id'])
    assert db.execute('SELECT state FROM fleet_slots WHERE id=?',(first['lease_id'],)).fetchone()['state']=='expired'
    db.close()

def test_no_worker_after_heartbeat_expiry():
    db,_=fresh()
    db.execute("UPDATE workers SET lease_expiry='2020-01-01T00:00:00+00:00'")
    db.commit()
    assert slot(db,'miss') is None
    db.close()

def test_concurrent_reservations_cannot_oversubscribe():
    db,path=fresh()
    db.execute("DELETE FROM workers WHERE id IN ('beta','gamma')")
    db.commit();db.close()
    barrier=threading.Barrier(12)
    results=[];lock=threading.Lock()
    def reserve_one(i):
        connection=sqlite3.connect(path,timeout=30)
        connection.row_factory=sqlite3.Row
        barrier.wait()
        r=fleet.reserve(connection,'python',str(i))
        connection.commit();connection.close()
        with lock:results.append(r)
    threads=[threading.Thread(target=reserve_one,args=(i,)) for i in range(12)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert len(results)==12
    assert sum(x is not None for x in results)==1

def test_invalid_metadata_and_capacity_denied():
    import pytest
    db,_=fresh()
    with pytest.raises(ValueError):fleet.configure(db,'alpha',0)
    with pytest.raises(ValueError):fleet.configure(db,'alpha',129)
    with pytest.raises(ValueError):fleet.configure(db,'nobody',1)
    with pytest.raises(ValueError):fleet.reserve(db,'python','x',lease_seconds=0)
    db.close()

def test_fleet_routes_are_authenticated():
    from capsula.api import app
    from fastapi.testclient import TestClient
    client=TestClient(app.app)
    assert client.get('/api/fleet').status_code in (401,503)
    if app.API_KEY:
        headers={'Authorization':'Bearer '+app.API_KEY}
        assert client.get('/api/fleet',headers=headers).status_code==200
        assert client.put('/api/fleet/workers/no-such-worker/capacity',headers=headers,json={'capacity':4}).status_code==422
