"""Governed worker federation and adapter inventories. Zero implicit trust."""
import os, secrets, sqlite3, datetime, json, hmac
from typing import Optional
from pydantic import BaseModel, Field

WORKER_TYPES={'python','browser','research','compute','agent'}
SYSTEMS={
 'nexus':('NEXUS','protocol admission, routing, approvals'),
 'loom_cluster':('Loom Cluster','worker scheduling, leases, resources'),
 'pocket_agent':('Pocket Agent','durable bounded agents and RAH'),
 'nova_runtime':('NOVA Runtime','LLM execution'),
 'livevault':('LiveVault','sealed remote state and key services'),
 'parralax':('PARRALAX','wallet budget and settlement controls'),
 'triple_mcp':('Triple-MCP','tool federation'),
 'medina_memory':('Medina Memory','durable memory plane'),
}

def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS workers (id TEXT PRIMARY KEY,kind TEXT NOT NULL,endpoint TEXT NOT NULL,capabilities TEXT NOT NULL,status TEXT NOT NULL,registered TEXT NOT NULL,heartbeat TEXT NOT NULL,lease_expiry TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY,mission_id TEXT,worker_id TEXT,kind TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,updated TEXT NOT NULL,request TEXT NOT NULL,result TEXT NOT NULL,deadline TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY,scope TEXT NOT NULL,kind TEXT NOT NULL,amount_limit TEXT NOT NULL,spent TEXT NOT NULL,expires TEXT NOT NULL,created TEXT NOT NULL,revoked INTEGER NOT NULL DEFAULT 0)')
    db.execute('CREATE TABLE IF NOT EXISTS finance_intents (id TEXT PRIMARY KEY,grant_id TEXT,recipient TEXT NOT NULL,amount TEXT NOT NULL,asset TEXT NOT NULL,chain TEXT NOT NULL,reason TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS approvals (id TEXT PRIMARY KEY,action TEXT NOT NULL,scope TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,decided TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS artifacts (id TEXT PRIMARY KEY,mission_id TEXT NOT NULL,name TEXT NOT NULL,mime TEXT NOT NULL,digest TEXT NOT NULL,bytes INTEGER NOT NULL,created TEXT NOT NULL)')

class WorkerRegistration(BaseModel):
    id:str=Field(pattern=r'^[a-z][a-z0-9-]{2,63}$')
    kind:str
    endpoint:str=Field(max_length=256)
    capabilities:list[str]=Field(default_factory=list,max_length=24)

class GrantInput(BaseModel):
    scope:str=Field(min_length=1,max_length=80)
    kind:str=Field(pattern=r'^(invoice|payment_proposal)$')
    amount_limit:str=Field(pattern=r'^\d{1,8}(\.\d{1,6})?$')
    expires:str

class FinanceIntent(BaseModel):
    recipient:str=Field(min_length=5,max_length=160)
    amount:str=Field(pattern=r'^\d{1,8}(\.\d{1,6})?$')
    asset:str=Field(pattern=r'^(USDC|USDT|SOL)$')
    chain:str=Field(pattern=r'^(solana-mainnet|solana-devnet)$')
    reason:str=Field(min_length=3,max_length=250)
    grant_id:Optional[str]=None

class ApprovalInput(BaseModel):
    action:str=Field(pattern=r'^(tool|deploy|wallet_sign|worker_register)$')
    scope:str=Field(min_length=1,max_length=80)
    payload:dict=Field(default_factory=dict)

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()

def expiry(seconds):return (datetime.datetime.now(datetime.timezone.utc)+datetime.timedelta(seconds=seconds)).isoformat()

def inventory():
    return {k:{'name':n,'purpose':p,'status':'unconnected','authority':'none'} for k,(n,p) in SYSTEMS.items()}

def worker_status(row):
    d=dict(row);d['capabilities']=json.loads(d['capabilities']);d['online']=d['status']=='active' and d['lease_expiry']>now();return d
