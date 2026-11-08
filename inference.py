"""Provider-neutral, operator-pinned OpenAI-compatible inference boundary.

Supports a local OpenAI-compatible service (including Ollama's /v1/chat/completions)
with a loopback HTTP address, or any operator-selected HTTPS provider.  A model
name and user prompt can never redirect outbound traffic to arbitrary hosts.
"""
from urllib.parse import urlparse
import os, httpx, ipaddress
from fastapi import HTTPException
from pydantic import BaseModel, Field

class InferenceInput(BaseModel):
    model:str=Field(min_length=1,max_length=120)
    system:str=Field(default='You are a bounded work assistant.',max_length=1000)
    prompt:str=Field(min_length=1,max_length=5000)
    max_tokens:int=Field(default=256,ge=1,le=1024)

class InferenceResult(BaseModel):
    status:str
    provider:str
    model:str
    text:str
    usage:dict={}

def config():
    """No fake provider: the URL and explicit allowlist must exist.

    A Vultr Serverless Inference token with no other endpoint pins the official
    chat-completions host. A prompt cannot change that host.
    """
    vendor=os.getenv('CAPSULA_MODEL_PROVIDER','openai-compatible').strip()
    endpoint=os.getenv('CAPSULA_MODEL_URL','') or os.getenv('VULTR_INFERENCE_URL','')
    key=os.getenv('CAPSULA_MODEL_API_KEY','') or os.getenv('VULTR_INFERENCE_API_KEY','')
    models=[x.strip() for x in (os.getenv('CAPSULA_MODEL_ALLOWED_MODELS','') or os.getenv('VULTR_ALLOWED_MODELS','')).split(',') if x.strip()]
    host=os.getenv('CAPSULA_MODEL_HOST','') or os.getenv('VULTR_INFERENCE_HOST','')
    vultr_key=os.getenv('VULTR_INFERENCE_API_KEY','').strip()
    if not endpoint and vultr_key:
        endpoint='https://api.vultrinference.com/v1/chat/completions'
        host=host or 'api.vultrinference.com'
        if not models:
            models=[os.getenv('VULTR_CHAT_MODEL','mimo-v2.6-flash').strip() or 'mimo-v2.6-flash']
        if vendor in ('','openai-compatible','self-hosted'):
            vendor='vultr-serverless'
        key=key or vultr_key
    if not endpoint or not models:return {'configured':False,'provider':vendor,'models':[], 'mode':'unconfigured'}
    p=urlparse(endpoint)
    loopback=p.hostname in ('127.0.0.1','localhost','::1')
    internal=(os.getenv('CAPSULA_MODEL_ALLOW_INTERNAL_HTTP','')=='1' and bool(host) and p.hostname==host and p.scheme=='http')
    if p.scheme not in ('https','http') or (p.scheme=='http' and not (loopback or internal)) or p.username or p.password or p.fragment or not p.hostname:
        return {'configured':False,'provider':vendor,'models':[],'mode':'invalid-endpoint'}
    if not loopback and (not host or p.hostname.lower()!=host.lower()):
        return {'configured':False,'provider':vendor,'models':[],'mode':'host-not-pinned'}
    if loopback and p.hostname not in ('127.0.0.1','localhost','::1'):
        return {'configured':False,'provider':vendor,'models':[],'mode':'invalid-loopback'}
    return {'configured':True,'provider':vendor,'models':models,'mode':'loopback' if loopback else ('operator-pinned-private-http' if internal else 'https'),'endpoint':endpoint,'key':key}

def public_config():
    x=config();return {k:x[k] for k in ('configured','provider','models','mode')}

def infer(body:InferenceInput):
    cfg=config()
    if not cfg['configured']:raise HTTPException(503,'No approved local or remote model provider configured')
    if body.model not in cfg['models']:raise HTTPException(403,'Model not in operator allowlist')
    headers={'Content-Type':'application/json'}
    if cfg['key']:headers['Authorization']='Bearer '+cfg['key']
    payload={'model':body.model,'messages':[{'role':'system','content':body.system},{'role':'user','content':body.prompt}],'max_tokens':body.max_tokens,'stream':False}
    try:
        with httpx.Client(timeout=28,follow_redirects=False,trust_env=False) as client:
            resp=client.post(cfg['endpoint'],headers=headers,json=payload)
            resp.raise_for_status();data=resp.json()
        message=data['choices'][0]['message']['content']
        if not isinstance(message,str):raise ValueError('Missing text output')
        return {'status':'completed','provider':cfg['provider'],'model':body.model,'text':message[:20000],'usage':data.get('usage') or {}}
    except (httpx.HTTPError,KeyError,IndexError,TypeError,ValueError) as exc:
        raise HTTPException(502,'Configured model provider failed or returned malformed response') from exc
