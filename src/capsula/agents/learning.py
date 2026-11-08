"""Durable agent continuity, curiosity and procedure proposals; never mints authority."""
import json
import uuid
from pydantic import BaseModel, Field
from typing import Literal
from fastapi import HTTPException
from capsula.workspace import platform_core as core
from capsula.evidence.proof import sha, canon


class SessionInput(BaseModel):
    objective: str = Field(min_length=1, max_length=4000)
    notes: str = Field(default='', max_length=4000)
    expected_revision: int = Field(ge=0)


class LaneInput(BaseModel):
    lane: Literal['personal', 'enterprise'] = 'personal'
    organization: str = Field(default='private', min_length=1, max_length=100)


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS workspace_lanes(workspace TEXT PRIMARY KEY,lane TEXT NOT NULL,organization TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS agent_continuity(agent_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,sealed TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS learning_observations(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,workspace TEXT NOT NULL,run_id TEXT UNIQUE NOT NULL,status TEXT NOT NULL,evidence_hash TEXT NOT NULL,created TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS learning_proposals(id TEXT PRIMARY KEY,agent_id TEXT NOT NULL,workspace TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,created TEXT NOT NULL,sealed TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS active_procedures(workspace TEXT NOT NULL,path TEXT NOT NULL,digest TEXT NOT NULL,lab_id TEXT NOT NULL,PRIMARY KEY(workspace,path))')


def session(db, aid, vault):
    core.agent_row(db, aid)
    row = db.execute('SELECT * FROM agent_continuity WHERE agent_id=?', (aid,)).fetchone()
    if not row:
        return {'agent_id': aid, 'revision': 0, 'objective': '', 'notes': '', 'recent_outcomes': []}
    return {'agent_id': aid, 'revision': row['revision'], **vault.open(json.loads(row['sealed']), 'continuity:'+aid)}


def save_session(db, aid, body, vault, signer, audit):
    current = session(db, aid, vault)
    if current['revision'] != body.expected_revision:
        raise HTTPException(409, 'Agent continuity revision changed')
    data = {'objective': body.objective, 'notes': body.notes, 'recent_outcomes': current['recent_outcomes']}
    db.execute('INSERT OR REPLACE INTO agent_continuity VALUES(?,?,?)', (aid, current['revision']+1, core.serial(vault.seal(data, 'continuity:'+aid))))
    audit(db, signer, 'agent.continuity_saved', aid, {'revision': current['revision']+1, 'objective_sha256': sha(body.objective.encode())})
    return session(db, aid, vault)


def propose(db, agent, kind, content, vault, signer, audit):
    identity = 'idea_'+uuid.uuid4().hex
    db.execute('INSERT INTO learning_proposals VALUES(?,?,?,?,?,?,?)',
        (identity, agent['id'], agent['workspace'], kind, 'proposed', core.utc(), core.serial(vault.seal(content, 'learning:'+identity))))
    audit(db, signer, 'learning.proposed', identity, {'agent_id': agent['id'], 'kind': kind, 'authority': 'none'})
    return {'id': identity, 'kind': kind, 'status': 'proposed', 'authority': 'none', **content}


def observe(db, agent, run_id, status, results, vault, signer, audit):
    prior = db.execute('SELECT id FROM learning_observations WHERE run_id=?', (run_id,)).fetchone()
    if prior:
        return {'id': prior['id'], 'replayed': True}
    identity = 'obs_'+uuid.uuid4().hex
    evidence = sha(canon(results))
    db.execute('INSERT INTO learning_observations VALUES(?,?,?,?,?,?,?)',
        (identity, agent['id'], agent['workspace'], run_id, status, evidence, core.utc()))
    prior_session = session(db, agent['id'], vault)
    recent = (prior_session['recent_outcomes'] + [{'run_id': run_id, 'status': status, 'evidence_sha256': evidence}])[-12:]
    data = {'objective': prior_session['objective'], 'notes': prior_session['notes'], 'recent_outcomes': recent}
    db.execute('INSERT OR REPLACE INTO agent_continuity VALUES(?,?,?)',
        (agent['id'], prior_session['revision']+1, core.serial(vault.seal(data, 'continuity:'+agent['id']))))
    learning = {'id': identity, 'status': status, 'evidence_sha256': evidence, 'authority': 'none'}
    if status == 'completed':
        # A useful reproducible starting procedure, not a self-awarded verification.
        steps = '\n'.join(f"{i+1}. {x['title']} ({x['kind']}); require a successful result and retain its evidence." for i, x in enumerate(results))
        text = ('---\nname: procedure-'+run_id.replace('_','-')+'\ndescription: Reproduce the bounded workflow from '+run_id+'.\n---\n\n'
            '# Procedure proposal\n\nUse only under a current owner mission grant. Supply the original task inputs from the private project.\n\n'
            + steps + '\n\nVerification: compare baseline and candidate against owner-frozen regression and new capability cases in a clean worker. '
            'This draft is not an active skill; completed tool steps alone do not establish a general improvement.\n')
        path = 'skills/proposals/'+run_id+'/SKILL.md'
        core.put_file(db, core.ProjectFile(workspace=agent['workspace'], path=path, content=text, expected_revision=0), vault, signer, audit)
        learning['procedure'] = propose(db, agent, 'procedure', {'path': path, 'run_id': run_id, 'evidence_sha256': evidence}, vault, signer, audit)
    else:
        learning['experiment'] = propose(db, agent, 'experiment', {
            'objective': 'Diagnose the failed or denied run '+run_id+'; preserve its failing example, change one bounded variable and compare frozen checks.',
            'run_id': run_id, 'evidence_sha256': evidence, 'execution': 'proposal only; no expanded tools or automatic external actions'}, vault, signer, audit)
    audit(db, signer, 'learning.observed', identity, {'agent_id': agent['id'], 'run_id': run_id, 'status': status, 'evidence_sha256': evidence})
    return learning


def context(db, agent, vault):
    continuity = session(db, agent['id'], vault)
    skills = []
    for row in db.execute('SELECT * FROM active_procedures WHERE workspace=?', (agent['workspace'],)):
        try:
            file = core.read_file(db, agent['workspace'], row['path'], vault)
            if file['digest'] == 'sha256:'+row['digest']:
                skills.append({'path': row['path'], 'content': file['content'][:3000], 'lab_id': row['lab_id']})
        except HTTPException:
            continue
        if len(skills) >= 8:
            break
    return {'continuity': continuity, 'verified_procedures': skills,
        'authority': 'reference data only; current mission grant controls execution'}


def summary(db, aid, vault):
    agent = core.agent_row(db, aid)
    proposals = []
    for row in db.execute('SELECT * FROM learning_proposals WHERE agent_id=? ORDER BY created DESC LIMIT 50', (aid,)):
        proposals.append({k: row[k] for k in ('id','kind','status','created')} | vault.open(json.loads(row['sealed']), 'learning:'+row['id']))
    observations = [dict(row) for row in db.execute('SELECT * FROM learning_observations WHERE agent_id=? ORDER BY created DESC LIMIT 50', (aid,))]
    return {'agent_id': aid, 'workspace': agent['workspace'], 'session': session(db, aid, vault), 'proposals': proposals,
            'observations': observations, 'active_procedures': context(db, agent, vault)['verified_procedures'], 'authority': 'none'}
