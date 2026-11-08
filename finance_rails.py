"""Actual Stripe Checkout receivables for CAPSULA organizations.

No simulated balances or wallet payouts. Merchant API credentials never enter
agent workspaces, prompts, Docker capsules, job payloads or frontend code.
"""
import hashlib,hmac,json,os,re,time,uuid
from urllib.parse import urlsplit
import httpx
from cluster_queue import valid_tenant

SCHEMA=[
"""CREATE TABLE IF NOT EXISTS finance_receivables(
 id text PRIMARY KEY,tenant_id text NOT NULL,idempotency_key text NOT NULL,
 title text NOT NULL,amount_minor bigint NOT NULL CHECK(amount_minor BETWEEN 100 AND 5000000),
 currency text NOT NULL DEFAULT 'usd',
 state text NOT NULL DEFAULT 'draft'
 CHECK(state IN ('draft','checkout_open','paid','cancelled')),
 stripe_session text UNIQUE,checkout_url text,
 created_at timestamptz NOT NULL DEFAULT now(),paid_at timestamptz,
 UNIQUE(tenant_id,idempotency_key))""",
"CREATE INDEX IF NOT EXISTS idx_receivables_tenant ON finance_receivables(tenant_id,created_at DESC)",
"""CREATE TABLE IF NOT EXISTS finance_webhook_events(
 id text PRIMARY KEY,event_type text NOT NULL,invoice_id text,
 received_at timestamptz NOT NULL DEFAULT now())"""
]
INVOICE=re.compile(r'^inv_[a-f0-9]{32}$')
KEY=re.compile(r'^[A-Za-z0-9_-]{8,100}$')

def stripe_key(env):
    value=env.get('CAPSULA_STRIPE_SECRET_KEY','')
    if not value.startswith(('sk_live_','sk_test_')) or len(value)<20:
        raise RuntimeError('Stripe merchant key not configured')
    return value

def public_origin(env):
    base=env.get('CAPSULA_FINANCE_PUBLIC_ORIGIN','')
    parts=urlsplit(base)
    if parts.scheme!='https' or not parts.hostname or parts.username or parts.password or parts.path not in ('','/') or parts.query or parts.fragment:
        raise RuntimeError('Pinned HTTPS public payment origin required')
    return base.rstrip('/')

def verify_event(raw,signature,secret,now=None):
    if not isinstance(raw,bytes) or len(raw)>262144 or not secret or not isinstance(signature,str) or len(signature)>2048:
        raise PermissionError('Invalid webhook envelope')
    values={}
    for part in signature.split(','):
        k,sep,v=part.partition('=')
        if sep:values.setdefault(k.strip(),[]).append(v.strip())
    if len(values.get('t',[]))!=1:raise PermissionError('Missing Stripe timestamp')
    try:stamp=int(values['t'][0])
    except ValueError as exc:raise PermissionError('Invalid Stripe timestamp') from exc
    if abs(int(time.time() if now is None else now)-stamp)>300:
        raise PermissionError('Expired Stripe webhook timestamp')
    expected=hmac.new(secret.encode(),str(stamp).encode()+b'.'+raw,hashlib.sha256).hexdigest()
    if not any(len(v)==64 and hmac.compare_digest(v,expected) for v in values.get('v1',[])):
        raise PermissionError('Stripe signature invalid')
    try:data=json.loads(raw)
    except ValueError as exc:raise ValueError('Malformed Stripe webhook JSON') from exc
    if not isinstance(data,dict) or data.get('object')!='event' or not isinstance(data.get('id'),str):
        raise ValueError('Unexpected Stripe event envelope')
    return data

class Receivables:
    def __init__(self,queue,env=None,client=None):
        self.queue=queue;self.env=env if env is not None else os.environ;self.client=client
    def migrate(self):
        with self.queue.tx() as db:
            for ddl in SCHEMA:db.execute(ddl)
    @staticmethod
    def public(row):
        return ({name:row[name] for name in ('id','tenant_id','title','amount_minor','currency','state','checkout_url','stripe_session')}
                if row else None)
    def create(self,tenant,title,amount_minor,idempotency_key,currency='usd'):
        valid_tenant(tenant)
        if not isinstance(title,str) or not 3<=len(title)<=120 or any(ord(c)<32 for c in title):
            raise ValueError('Invalid invoice title')
        if currency!='usd' or type(amount_minor) is not int or not 100<=amount_minor<=5000000:
            raise ValueError('Invalid minor-unit USD amount')
        if not isinstance(idempotency_key,str) or not KEY.fullmatch(idempotency_key):
            raise ValueError('Invalid idempotency key')
        invoice='inv_'+uuid.uuid4().hex
        with self.queue.tx() as db:
            row=db.execute("""INSERT INTO finance_receivables(id,tenant_id,idempotency_key,title,amount_minor,currency)
              VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(tenant_id,idempotency_key) DO NOTHING RETURNING id""",
              (invoice,tenant,idempotency_key,title,amount_minor,currency)).fetchone()
            if row:
                return self.public(db.execute('SELECT * FROM finance_receivables WHERE id=%s AND tenant_id=%s',
                               (row['id'],tenant)).fetchone())
            old=db.execute('SELECT * FROM finance_receivables WHERE tenant_id=%s AND idempotency_key=%s',
                           (tenant,idempotency_key)).fetchone()
            if old['title']!=title or old['amount_minor']!=amount_minor or old['currency']!=currency:
                raise ValueError('Idempotency key reused with different amount or title')
            return self.public(old)
    def get(self,tenant,invoice):
        valid_tenant(tenant)
        if not INVOICE.fullmatch(invoice):raise ValueError('Invalid invoice identifier')
        with self.queue.tx() as db:
            return self.public(db.execute('SELECT * FROM finance_receivables WHERE id=%s AND tenant_id=%s',
                                          (invoice,tenant)).fetchone())
    def checkout(self,tenant,invoice):
        valid_tenant(tenant)
        if not INVOICE.fullmatch(invoice):raise ValueError('Invalid invoice identifier')
        key=stripe_key(self.env);origin=public_origin(self.env)
        with self.queue.tx() as db:
            row=db.execute('SELECT * FROM finance_receivables WHERE tenant_id=%s AND id=%s FOR UPDATE',
                           (tenant,invoice)).fetchone()
            if not row:raise KeyError('Receivable not found')
            if row['state']=='checkout_open':return self.public(row)
            if row['state']!='draft':raise ValueError('Receivable is not eligible for payment')
            fields={
                'mode':'payment','client_reference_id':invoice,
                'success_url':origin+'/finance/complete?session_id={CHECKOUT_SESSION_ID}',
                'cancel_url':origin+'/finance/cancel',
                'line_items[0][price_data][currency]':row['currency'],
                'line_items[0][price_data][unit_amount]':str(row['amount_minor']),
                'line_items[0][price_data][product_data][name]':row['title'],
                'line_items[0][quantity]':'1',
                'metadata[tenant_id]':tenant,'metadata[invoice_id]':invoice
            }
            headers={'Authorization':'Bearer '+key,'Idempotency-Key':'capsula-'+invoice}
            try:
                if self.client is not None:
                    reply=self.client.post('https://api.stripe.com/v1/checkout/sessions',data=fields,headers=headers)
                else:
                    with httpx.Client(timeout=12,follow_redirects=False,trust_env=False) as client:
                        reply=client.post('https://api.stripe.com/v1/checkout/sessions',data=fields,headers=headers)
                reply.raise_for_status();data=reply.json()
            except (httpx.HTTPError,ValueError) as exc:
                raise RuntimeError('Payment processor request failed') from exc
            session=data.get('id');url=data.get('url','');parts=urlsplit(url)
            if not isinstance(session,str) or not session.startswith('cs_') or parts.scheme!='https' or parts.hostname!='checkout.stripe.com':
                raise RuntimeError('Untrusted payment processor response')
            new=db.execute("""UPDATE finance_receivables SET state='checkout_open',
                stripe_session=%s,checkout_url=%s WHERE id=%s AND tenant_id=%s
                AND state='draft' RETURNING *""",(session,url,invoice,tenant)).fetchone()
            return self.public(new)
    def webhook(self,body,signature):
        data=verify_event(body,signature,self.env.get('CAPSULA_STRIPE_WEBHOOK_SECRET',''))
        event_id=data['id'];kind=data.get('type','')
        if not re.fullmatch(r'evt_[A-Za-z0-9]{3,120}',event_id):
            raise ValueError('Invalid event ID')
        with self.queue.tx() as db:
            if db.execute('SELECT 1 FROM finance_webhook_events WHERE id=%s',(event_id,)).fetchone():
                return {'accepted':True,'duplicate':True}
            if kind not in ('checkout.session.completed','checkout.session.async_payment_succeeded'):
                db.execute('INSERT INTO finance_webhook_events(id,event_type) VALUES(%s,%s)',(event_id,kind))
                return {'accepted':True,'ignored':True}
            obj=(data.get('data') or {}).get('object') or {}
            meta=obj.get('metadata') or {}
            invoice=meta.get('invoice_id','');tenant=meta.get('tenant_id','')
            if not isinstance(invoice,str) or not INVOICE.fullmatch(invoice) or not isinstance(tenant,str):
                raise ValueError('Payment metadata invalid')
            row=db.execute('SELECT * FROM finance_receivables WHERE id=%s AND tenant_id=%s FOR UPDATE',
                           (invoice,tenant)).fetchone()
            if (not row or row['stripe_session']!=obj.get('id') or row['currency']!=obj.get('currency')
                    or row['amount_minor']!=obj.get('amount_total') or obj.get('payment_status')!='paid'
                    or row['state'] not in ('checkout_open','paid')):
                raise ValueError('Payment settlement mismatch')
            db.execute("""UPDATE finance_receivables SET state='paid',
              paid_at=COALESCE(paid_at,now()) WHERE id=%s AND state='checkout_open'""",(invoice,))
            db.execute('INSERT INTO finance_webhook_events(id,event_type,invoice_id) VALUES(%s,%s,%s)',
                       (event_id,kind,invoice))
            return {'accepted':True,'invoice_id':invoice,'state':'paid'}
