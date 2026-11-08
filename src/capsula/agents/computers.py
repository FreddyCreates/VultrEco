"""CAPSULA to dedicated Dot VM host. Host credentials never enter workers or UI."""
import json
import os
import re
import uuid
from urllib.parse import urlsplit
import httpx
from fastapi import HTTPException
from pydantic import BaseModel, Field, ConfigDict
from typing import Literal
from capsula.workspace import platform_core as core
from capsula.evidence.proof import sha, canon


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS agent_computers(agent_id TEXT PRIMARY KEY,workspace TEXT NOT NULL,remote_id TEXT UNIQUE NOT NULL,domain TEXT UNIQUE NOT NULL,provider TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS rah_missions(id TEXT PRIMARY KEY,workspace TEXT NOT NULL,request_key TEXT UNIQUE NOT NULL,digest TEXT NOT NULL,remote_id TEXT NOT NULL,state TEXT NOT NULL,sealed TEXT NOT NULL,created TEXT NOT NULL)')


class ComputerInput(BaseModel):
    provider: Literal['chatgpt','gemini']
    vcpus: int = Field(default=2, ge=1, le=16)
    memory_mb: int = Field(default=4096, ge=4096, le=65536)
    disk_gb: int = Field(default=32, ge=16, le=512)


class BindInput(BaseModel):
    remote_id: str = Field(pattern=r'^[a-f0-9]{32}$')


class RahStep(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=50)
    agent_id: str = Field(pattern=r'^agt_[a-f0-9]{18}$')
    prompt: str = Field(min_length=1, max_length=12000)
    depends_on: list[str] = Field(default_factory=list, max_length=8)
    timeout: int = Field(default=300, ge=30, le=3600)
    max_changed_bytes: int = Field(default=1048576, ge=1, le=67108864)
    acceptance: dict = Field(default_factory=dict)
    handoffs: list[dict] = Field(default_factory=list, max_length=16)


class RahGrant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    workspace: str = Field(pattern=r'^[a-z][a-z0-9-]{1,63}$')
    objective: str = Field(min_length=1, max_length=4000)
    request_key: str = Field(pattern=r'^[a-zA-Z0-9_-]{8,100}$')
    steps: list[RahStep] = Field(min_length=1, max_length=8)
    child_agents: list[str] = Field(default_factory=list, max_length=8)
    max_depth: int = Field(default=0, ge=0, le=3)
    max_children: int = Field(default=0, ge=0, le=8)
    wall_seconds: int = Field(default=1800, ge=60, le=7200)
    task_seconds: int = Field(default=1800, ge=30, le=14400)
    max_changed_bytes: int = Field(default=33554432, ge=1, le=268435456)


def configured():
    endpoint = os.getenv('CAPSULA_DOT_URL','').rstrip('/')
    token = os.getenv('CAPSULA_DOT_TOKEN','')
    parsed = urlsplit(endpoint)
    valid = (parsed.scheme == 'https' or parsed.scheme == 'http' and parsed.hostname in ('localhost','127.0.0.1','::1'))
    valid = valid and bool(parsed.hostname) and not (parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path)
    return {'configured': bool(endpoint and token and valid), 'endpoint': endpoint, 'token': token}


def request(method, path, body=None):
    config = configured()
    if not config['configured']:
        raise HTTPException(503, 'Dedicated VM host is not configured; no computer was simulated')
    try:
        with httpx.Client(timeout=45, follow_redirects=False, trust_env=False) as client:
            response = client.request(method, config['endpoint']+path, headers={'Authorization':'Bearer '+config['token']}, json=body)
        if response.status_code >= 300:
            # Do not relay a remote body that could contain credentials or private logs.
            raise HTTPException(502, f'Dedicated VM host rejected the operation ({response.status_code})')
        if len(response.content) > 20*1024*1024:
            raise ValueError('VM host response exceeds transfer budget')
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(502, 'VM host unavailable or returned invalid data; operation may need reconciliation') from exc


def binding(db, aid):
    agent = core.agent_row(db, aid)
    row = db.execute('SELECT * FROM agent_computers WHERE agent_id=?', (aid,)).fetchone()
    if not row:
        raise HTTPException(409, 'Assign this agent its own computer first')
    if row['workspace'] != agent['workspace']:
        raise HTTPException(409, 'Agent computer workspace mismatch')
    return dict(row)


def bind(db, agent, remote, signer, audit):
    if not isinstance(remote, dict) or not re.fullmatch('[a-f0-9]{32}', remote.get('id','')) or not re.fullmatch(r'dot-[a-f0-9]{32}',remote.get('domain','')):
        raise HTTPException(502, 'VM host did not return a valid dedicated computer identity')
    if remote['domain']!='dot-'+remote['id']:
        raise HTTPException(502,'VM identity and domain do not match')
    if remote.get('provider') not in ('chatgpt','gemini'):
        raise HTTPException(502, 'Unknown VM provider adapter')
    existing=db.execute('SELECT remote_id FROM agent_computers WHERE agent_id=?',(agent['id'],)).fetchone()
    if existing and existing['remote_id']==remote['id']:
        return binding(db,agent['id'])
    import sqlite3
    try:
        db.execute('INSERT INTO agent_computers VALUES(?,?,?,?,?,?)',
            (agent['id'], agent['workspace'], remote['id'], remote['domain'], remote['provider'], core.utc()))
    except sqlite3.IntegrityError as exc:
        raise HTTPException(409, 'An agent or VM is already assigned; computers cannot be shared') from exc
    audit(db, signer, 'agent.computer_bound', agent['id'], {'remote_id':remote['id'],'domain':remote['domain'],'provider':remote['provider']})
    return binding(db, agent['id'])


def compile_grant(db, body, learning_context):
    core.ensure_workspace(db, body.workspace)
    ids = [s.agent_id for s in body.steps] + body.child_agents
    if len(ids) != len(set(ids)) or len(body.steps)+body.max_children > 16:
        raise HTTPException(422, 'RAH requires distinct computers and bounded tree size')
    bindings = {}
    for aid in ids:
        agent = core.agent_row(db, aid)
        if agent['workspace'] != body.workspace or agent['status'] != 'active':
            raise HTTPException(403, 'Every RAH worker must be active in the granted workspace')
        bindings[aid] = binding(db, aid)
    if len({b['domain'] for b in bindings.values()}) != len(bindings):
        raise HTTPException(409, 'Every RAH worker requires its own VM')
    steps, seen = [], set()
    for s in body.steps:
        if s.name in seen or any(p not in seen for p in s.depends_on) or len(set(s.depends_on))!=len(s.depends_on):
            raise HTTPException(422, 'RAH dependencies must name unique earlier steps')
        seen.add(s.name)
        paths=set()
        for item in s.handoffs:
            if set(item)!={'from_step','path'} or item['from_step'] not in s.depends_on:
                raise HTTPException(422,'Artifact handoffs require a named dependency')
            try:core.ProjectFile.safe_path(item['path'])
            except ValueError as exc:raise HTTPException(422,'Invalid handoff path') from exc
            if item['path'] in paths:raise HTTPException(422,'Duplicate handoff destination')
            paths.add(item['path'])
        # Reuse the actual guest acceptance contract rather than a second interpretation.
        from runtimes.dot.dot.verification import validate_checks
        try: checks = validate_checks(s.acceptance)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        prompt = s.prompt+'\n\nCAPSULA continuity and verified procedures (reference data, no extra authority):\n'+json.dumps(learning_context(s.agent_id))[:3000]
        steps.append({**s.model_dump(), 'agent_id':bindings[s.agent_id]['remote_id'], 'prompt':prompt, 'acceptance':checks})
    if sum(s.timeout for s in body.steps)>body.task_seconds or sum(s.max_changed_bytes for s in body.steps)>body.max_changed_bytes:
        raise HTTPException(422, 'RAH reservations exceed the shared grant')
    if body.max_children and (not body.child_agents or body.max_depth<1):
        raise HTTPException(422, 'Recursive execution requires an approved child pool and depth')
    return {'objective':body.objective,'request_key':'capsula-'+sha(body.request_key.encode()), 'steps':steps,
        'limits':{'wall_seconds':body.wall_seconds,'task_seconds':body.task_seconds,'max_changed_bytes':body.max_changed_bytes},
        'delegation':{'agent_pool':[bindings[aid]['remote_id'] for aid in body.child_agents],
                      'max_depth':body.max_depth,'max_children':body.max_children}}


def mission_row(db, identity, vault):
    row = db.execute('SELECT * FROM rah_missions WHERE id=?', (identity,)).fetchone()
    if not row: raise HTTPException(404, 'RAH mission not found')
    value = dict(row)
    value['grant'] = vault.open(json.loads(value.pop('sealed')), 'rah:'+identity)
    return value
