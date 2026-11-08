"""Medina Capability Kernel: user-space mission authority over Linux VM workers."""
import hashlib
import hmac
import json
from pathlib import Path
import re
import time
from .guest import checked_id
from .vendor.capsula_ecosystem import validate_task
from .vendor.capsula_portable import accept_vaul


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()


def validate_schema(value, schema, path='bundle'):
    types = {'object': lambda v: isinstance(v, dict), 'array': lambda v: isinstance(v, list),
             'string': lambda v: isinstance(v, str), 'integer': lambda v: type(v) is int,
             'null': lambda v: v is None}
    expected = schema.get('type')
    if expected:
        names = expected if isinstance(expected, list) else [expected]
        if not any(types[t](value) for t in names):
            raise ValueError(path + ': invalid type')
    if 'const' in schema and (value != schema['const'] or type(value) != type(schema['const'])):
        raise ValueError(path + ': invalid constant')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(path + ': unsupported value')
    if isinstance(value, str):
        if len(value) < schema.get('minLength', 0) or ('pattern' in schema and not re.fullmatch(schema['pattern'], value)):
            raise ValueError(path + ': invalid string')
    if type(value) is int and value < schema.get('minimum', value):
        raise ValueError(path + ': below minimum')
    if isinstance(value, dict):
        required = schema.get('required', [])
        if any(k not in value for k in required):
            raise ValueError(path + ': missing required fields')
        props = schema.get('properties', {})
        if schema.get('additionalProperties') is False and set(value) - set(props):
            raise ValueError(path + ': unknown fields')
        for key, child in value.items():
            if key in props:
                validate_schema(child, props[key], path + '.' + key)
    if isinstance(value, list) and 'items' in schema:
        for i, item in enumerate(value):
            validate_schema(item, schema['items'], path + '[' + str(i) + ']')


class CapabilityKernel:
    def __init__(self, owner_secret):
        self.secret = owner_secret.encode()

    def issue(self, *, job_id, agent_id, timeout, mode, changed_bytes=16 * 1024 * 1024, deadline=None):
        checked_id(job_id)
        checked_id(agent_id)
        now = time.time()
        if mode not in ('work', 'plan') or type(timeout) is not int or not 30 <= timeout <= 3600:
            raise ValueError('Invalid mission')
        if type(changed_bytes) is not int or not 1 <= changed_bytes <= 64 * 1024 * 1024:
            raise ValueError('Invalid change budget')
        lease = {'schema': 'medina.mission-lease.v1', 'request_id': job_id,
                 'principal': 'owner', 'agent_id': agent_id, 'issued_at': now,
                 'expires_at': now + timeout + 120, 'mode': mode,
                 'scope': {'project_id': agent_id, 'workspace': '/home/dot/workspace'},
                 'capabilities': ['workspace.read'] + (['workspace.write', 'guest.tools.execute', 'public.network'] if mode == 'work' else []),
                 'limits': {'wall_seconds': timeout, 'max_changed_bytes': changed_bytes if mode == 'work' else 0,
                            'max_output_bytes': 8 * 1024 * 1024, 'child_agents': 0},
                 'boundaries': {'host_shell': False, 'private_network': False, 'production_deploy': False}}
        if deadline is not None:
            if type(deadline) not in (int, float) or not now < deadline <= now + 7200:
                raise ValueError('Invalid inherited deadline')
            lease['expires_at'] = min(lease['expires_at'], deadline)
        lease['signature'] = hmac.new(self.secret, canonical(lease), hashlib.sha256).hexdigest()
        return lease

    def verify(self, lease, *, agent_id, job_id):
        if not isinstance(lease, dict):
            raise ValueError('Mission lease required')
        payload = {k: v for k, v in lease.items() if k != 'signature'}
        signature = hmac.new(self.secret, canonical(payload), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, str(lease.get('signature', ''))):
            raise ValueError('Invalid mission signature')
        if lease.get('agent_id') != agent_id or lease.get('request_id') != job_id:
            raise ValueError('Mission scope mismatch')
        if lease.get('expires_at', 0) <= time.time():
            raise ValueError('Mission lease expired')
        return payload

    def capsula_task(self, lease):
        action = 'capsula.session.run' if lease['mode'] == 'work' else 'capsula.manifest.build'
        task = {'schema': 'nexus.task.v1', 'request_id': lease['request_id'], 'action': action,
                'scope': lease['scope'], 'budget': {'limits': lease['limits']}}
        check = validate_task(task)
        if not check['ok']:
            raise ValueError('CAPSULA contract rejected task: ' + ', '.join(check['errors']))
        return task

    def accept_sealed(self, bundle, agent_id):
        checked_id(agent_id)
        schema = json.loads(Path(__file__).with_name('vendor').joinpath('capsule-contract.v1.json').read_text())
        validate_schema(bundle, schema)
        if bundle['manifest']['records'] != len(bundle['sealed_state']['records']):
            raise ValueError('Sealed record count mismatch')
        # Upstream parser validates NOVASVAUL format, deny-default permissions and content hash.
        return accept_vaul(bundle, 'dot-vm://' + agent_id)


def execution_receipt(job):
    started = job.get('started', job['created'])
    finished = job.get('finished', time.time())
    receipt = {'schema': 'pocket.execution-receipt.v1', 'receipt_id': 'dot-' + job['id'],
               'request_id': job['id'], 'action': 'agent.run',
               'status': 'succeeded' if job['status'] == 'completed' else ('failed' if job['status'] == 'lost' else job['status']),
               'principal_id': 'owner', 'tenant_id': 'owner', 'agent_id': job['agent_id'],
               'session_id': job['agent_id'], 'runtime': 'medina-dot-kvm',
               'duration_ms': max(0, int((finished - started) * 1000)),
               'result': {'summary': job.get('response', '')[:1000],
                          'artifact_hashes': [a['sha256'] for a in job.get('artifacts', [])]},
               'error': job.get('error'), 'policy': {'lease_id': job['id'], 'vm_scope': True},
               'metadata': {'reasoning_exposed': False, 'provider': job['provider']}}
    receipt['digest'] = hashlib.sha256(canonical(receipt)).hexdigest()
    return receipt
