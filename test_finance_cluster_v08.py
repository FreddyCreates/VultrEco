"""Real PostgreSQL receivables / Stripe reconciliation; no mock paid balances."""
import hashlib,hmac,json,os,time
from types import SimpleNamespace
import pytest
from finance_rails import Receivables,verify_event
from cluster_queue import Queue

@pytest.fixture
def bank():
    if not os.getenv('CAPSULA_CLUSTER_DATABASE_URL'):
        pytest.skip('Needs real PostgreSQL service')
    q=Queue();q.migrate()
    env={'CAPSULA_STRIPE_SECRET_KEY':'sk_test_'+'t'*30,
         'CAPSULA_STRIPE_WEBHOOK_SECRET':'whsec_integration',
         'CAPSULA_FINANCE_PUBLIC_ORIGIN':'https://capsula.example.com'}
    class MockStripe:
        def __init__(self):self.calls=[]
        def post(self,url,data,headers):
            self.calls.append({'url':url,'data':data,'headers':headers})
            return SimpleNamespace(raise_for_status=lambda:None,
                json=lambda:{'id':'cs_test_1234567890','url':'https://checkout.stripe.com/c/pay/example'})
    http=MockStripe();pay=Receivables(q,env,http)
    pay.migrate()
    with q.tx() as db:db.execute('TRUNCATE finance_webhook_events,finance_receivables')
    yield pay,http
    with q.tx() as db:db.execute('TRUNCATE finance_webhook_events,finance_receivables')

def stripe_event(invoice,tenant='acme',amount=2499,session='cs_test_1234567890',status='paid',eventid='evt_123456'):
    return {'object':'event','id':eventid,'type':'checkout.session.completed',
            'data':{'object':{'id':session,'metadata':{'tenant_id':tenant,'invoice_id':invoice},
                              'currency':'usd','amount_total':amount,'payment_status':status}}}

def signed(payload,secret='whsec_integration'):
    body=json.dumps(payload,separators=(',',':')).encode()
    stamp=int(time.time())
    digest=hmac.new(secret.encode(),str(stamp).encode()+b'.'+body,hashlib.sha256).hexdigest()
    return body,f't={stamp},v1={digest}'

def test_checkout_receivable_and_webhook_are_real_state_machine(bank):
    payments,processor=bank
    record=payments.create('acme','Actual services invoice',2499,'invoice-key-123')
    assert record['state']=='draft'
    open_session=payments.checkout('acme',record['id'])
    assert open_session['state']=='checkout_open'
    assert open_session['checkout_url'].startswith('https://checkout.stripe.com/')
    assert len(processor.calls)==1
    # Stripe idempotency is stable even if an HTTP call is retried.
    assert processor.calls[0]['headers']['Idempotency-Key']=='capsula-'+record['id']
    assert 'CAPSULA_STRIPE_SECRET_KEY' not in str(processor.calls[0]['data'])
    body,signature=signed(stripe_event(record['id']))
    paid=payments.webhook(body,signature)
    assert paid['state']=='paid'
    assert payments.get('acme',record['id'])['state']=='paid'
    assert payments.webhook(body,signature)['duplicate'] is True
    assert payments.get('beta',record['id']) is None
    assert len(processor.calls)==1

def test_invalid_settlement_cannot_mark_paid(bank):
    payments,_=bank
    record=payments.create('acme','Invoice for client',2499,'invoice-key-456')
    payments.checkout('acme',record['id'])
    body,sig=signed(stripe_event(record['id'],amount=2500))
    with pytest.raises(ValueError):payments.webhook(body,sig)
    assert payments.get('acme',record['id'])['state']=='checkout_open'
    body,sig=signed(stripe_event(record['id'],tenant='other'))
    with pytest.raises(ValueError):payments.webhook(body,sig)
    body,sig=signed(stripe_event(record['id'],status='unpaid'))
    with pytest.raises(ValueError):payments.webhook(body,sig)

def test_payment_provider_webhook_signature_mandatory(bank):
    payments,_=bank
    record=payments.create('acme','Invoice for tools',1900,'invoice-key-789')
    payments.checkout('acme',record['id'])
    body,sig=signed(stripe_event(record['id']))
    with pytest.raises(PermissionError):payments.webhook(body+b' ',sig)
    assert payments.get('acme',record['id'])['state']=='checkout_open'

def test_idempotency_scope_and_amount_guards(bank):
    payments,_=bank
    a=payments.create('acme','Invoice to replay',1000,'invoice-repeat')
    assert payments.create('acme','Invoice to replay',1000,'invoice-repeat')['id']==a['id']
    assert payments.create('beta','Invoice to replay',1000,'invoice-repeat')['id']!=a['id']
    with pytest.raises(ValueError):payments.create('acme','Changed invoice',1000,'invoice-repeat')
    with pytest.raises(ValueError):payments.create('acme','Invalid amount',0,'invoice-zero')
    with pytest.raises(ValueError):payments.create('acme','Unapproved asset',2500,'invoice-eth',currency='eth')
