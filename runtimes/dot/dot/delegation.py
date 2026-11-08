"""Bounded child-work requests. An outbox entry is a proposal, never authority."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import uuid
try:
    from .checkpoint import atomic_json
except ImportError:
    from checkpoint import atomic_json


def requests(value):
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError('At most eight delegation proposals per task')
    result=[]
    for item in value:
        if not isinstance(item, dict):raise ValueError('Invalid delegation proposal')
        identity=item.get('id');agent=item.get('agent_id');prompt=item.get('prompt')
        if not isinstance(identity,str) or not re.fullmatch('[a-f0-9]{32}',identity):raise ValueError('Invalid delegation identity')
        if not isinstance(agent,str) or not re.fullmatch('[a-f0-9]{32}',agent):raise ValueError('Invalid child agent')
        if not isinstance(prompt,str) or not 1 <= len(prompt) <= 8000:raise ValueError('Invalid child prompt')
        seconds=item.get('timeout',300);changed=item.get('max_changed_bytes',1048576)
        if type(seconds) is not int or not 30 <= seconds <= 3600 or type(changed) is not int or not 1 <= changed <= 67108864:raise ValueError('Invalid child budget')
        result.append({'id':identity,'agent_id':agent,'prompt':prompt,'timeout':seconds,'max_changed_bytes':changed})
    if len({r['id'] for r in result})!=len(result):raise ValueError('Duplicate delegation proposal')
    return result


def propose(root,job_id,prompt,agent_id,timeout=300,max_changed_bytes=1048576,request_id=None):
    if not isinstance(job_id,str) or not re.fullmatch('[a-f0-9]{32}',job_id):raise ValueError('Invalid parent job')
    folder=Path(root)/'jobs'/job_id
    if not (folder/'request.json').is_file():raise ValueError('Parent job does not exist')
    with (folder/'delegations.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path=folder/'delegations.json'
        current=json.loads(path.read_text()) if path.exists() else []
        proposal={'id':request_id or uuid.uuid4().hex,'agent_id':agent_id,'prompt':prompt,'timeout':timeout,'max_changed_bytes':max_changed_bytes}
        if any(p.get('id')==proposal['id'] for p in current):
            existing=next(p for p in current if p['id']==proposal['id'])
            if existing!=proposal:raise ValueError('Delegation ID already used for different work')
            return existing
        current=requests(current+[proposal]);atomic_json(path,current);return proposal


if __name__=='__main__':
    p=argparse.ArgumentParser(description='Propose child work within the owner-approved mission grant')
    p.add_argument('--agent',required=True);p.add_argument('--prompt',required=True);p.add_argument('--timeout',type=int,default=300);p.add_argument('--changed-bytes',type=int,default=1048576);p.add_argument('--request-id')
    a=p.parse_args()
    print(json.dumps(propose(Path.home()/'.dot',os.environ.get('DOT_JOB_ID',''),a.prompt,a.agent,a.timeout,a.changed_bytes,a.request_id)))
