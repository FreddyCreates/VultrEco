"""Tenant-scoped live finance API, separated from all agent/worker authority."""
from fastapi import APIRouter,Header,HTTPException,Request
from pydantic import BaseModel,Field
from typing import Literal
from capsula.security import cluster_auth
from capsula.execution.cluster_queue import Queue
from capsula.finance.finance_rails import Receivables

router=APIRouter(prefix='/api/v1/finance',tags=['finance'])
_engine=None

def engine():
    global _engine
    if _engine is None:_engine=Receivables(Queue())
    return _engine

def authority(header,tenant,role):
    try:
        p=cluster_auth.authenticate(header)
        cluster_auth.authorize(p,tenant,role)
        return p
    except PermissionError as exc:
        raise HTTPException(403,'Tenant finance authority required') from exc
    except RuntimeError as exc:
        raise HTTPException(503,'Enterprise identity not configured') from exc

class InvoiceRequest(BaseModel):
    title:str=Field(min_length=3,max_length=120)
    amount_minor:int=Field(ge=100,le=5000000)
    currency:Literal['usd']='usd'
    idempotency_key:str=Field(pattern=r'^[A-Za-z0-9_-]{8,100}$')

@router.post('/{tenant}/invoices',status_code=201)
def create_invoice(tenant:str,body:InvoiceRequest,authorization:str|None=Header(None)):
    authority(authorization,tenant,'operator')
    try:return engine().create(tenant,body.title,body.amount_minor,body.idempotency_key,body.currency)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc

@router.get('/{tenant}/invoices/{invoice}')
def get_invoice(tenant:str,invoice:str,authorization:str|None=Header(None)):
    authority(authorization,tenant,'viewer')
    try:item=engine().get(tenant,invoice)
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    if item is None:raise HTTPException(404,'Invoice not found')
    return item

@router.post('/{tenant}/invoices/{invoice}/checkout')
def checkout(tenant:str,invoice:str,authorization:str|None=Header(None)):
    # Only a finance admin may activate a hosted payment session.
    authority(authorization,tenant,'admin')
    try:return engine().checkout(tenant,invoice)
    except KeyError as exc:raise HTTPException(404,'Invoice not found') from exc
    except ValueError as exc:raise HTTPException(409,str(exc)) from exc
    except RuntimeError as exc:raise HTTPException(503,'Payment processor not configured') from exc

@router.post('/stripe/webhook')
async def stripe_webhook(request:Request,stripe_signature:str|None=Header(None)):
    # Stripe signs the raw bytes; do not use OIDC or a public client status.
    raw=await request.body()
    if len(raw)>262144:raise HTTPException(413,'Webhook too large')
    try:return engine().webhook(raw,stripe_signature or '')
    except PermissionError as exc:raise HTTPException(401,'Stripe webhook signature invalid') from exc
    except ValueError as exc:raise HTTPException(409,'Webhook invoice reconciliation failed') from exc

def bind(app):app.include_router(router)
