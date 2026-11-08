"""Operator-authenticated fleet capacity and draining controls."""
import fleet
from fastapi import Header,HTTPException
from pydantic import BaseModel,Field

class Capacity(BaseModel):
    capacity:int=Field(ge=1,le=128)
    provider:str=Field(default='self-hosted',max_length=80)
    node:str=Field(default='',max_length=80)
    region:str=Field(default='',max_length=80)
    draining:bool=False

def bind(m):
    app=m.app
    with m.conn() as db:fleet.schema(db)

    @app.get('/api/fleet')
    def summary(authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:return fleet.status(db)

    @app.put('/api/fleet/workers/{worker_id}/capacity')
    def set_capacity(worker_id:str,body:Capacity,authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            try:fleet.configure(db,worker_id,**body.model_dump())
            except ValueError as exc:raise HTTPException(422,str(exc)) from exc
            m.audit_append(db,m.signer,'fleet.capacity_configured',worker_id,body.model_dump())
            return fleet.status(db)

    @app.post('/api/fleet/reconcile')
    def reconcile(authorization:str|None=Header(None)):
        m.authed(authorization)
        with m.conn() as db:
            n=fleet.reconcile(db)
            if n:m.audit_append(db,m.signer,'fleet.slots_expired','fleet',{'count':n,'remote_termination':'not-proven'})
            return {'expired':n,**fleet.status(db)}
