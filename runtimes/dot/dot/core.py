from contextlib import contextmanager
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
from .vm import Libvirt
from .guest import checked_id
from .kernel import CapabilityKernel, execution_receipt
from .outcomes import validate_outcome
from .verification import validate_checks, evidence_matches

TERMINAL = ('completed', 'failed', 'cancelled', 'lost')


def load_config(path):
    config = json.loads(Path(path).read_text())
    required = ('state_dir', 'vm_root', 'image', 'image_sha256', 'codex_version', 'gemini_version', 'network', 'gateway', 'subnet')
    for key in required:
        if not isinstance(config.get(key), str) or not config[key]:
            raise ValueError('Missing configuration: ' + key)
    if not re.fullmatch('[0-9a-f]{64}', config['image_sha256']):
        raise ValueError('image_sha256 must be a verified SHA-256')
    for key in ('codex_version', 'gemini_version'):
        if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?', config[key]):
            raise ValueError(key + ' must be an exact release version')
    for key in ('state_dir', 'vm_root', 'image'):
        if not Path(config[key]).is_absolute() or ',' in config[key] or '\n' in config[key]:
            raise ValueError(key + ' must be an absolute path without commas or newlines')
    if not re.fullmatch('[a-zA-Z0-9_-]{1,60}', config['network']):
        raise ValueError('Invalid libvirt network')
    import ipaddress
    net = ipaddress.ip_network(config['subnet'])
    gw = ipaddress.ip_address(config['gateway'])
    if net.version != 4 or gw not in net or not gw.is_private:
        raise ValueError('Gateway must be in a private IPv4 subnet')
    for key, default, maximum in (('max_agents', 8, 32), ('max_vcpus', 16, 256), ('max_memory_mb', 32768, 1048576), ('max_disk_gb', 400, 100000)):
        value = config.setdefault(key, default)
        if type(value) is not int or not 1 <= value <= maximum:
            raise ValueError('Invalid resource limit: ' + key)
    return config


class Runtime:
    def __init__(self, config, backend=None, recover=False):
        self.config = config
        self.root = Path(config['state_dir'])
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.db = self.root / 'dot.sqlite3'
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        self.inflight = set()
        self.job_locks = {}
        self.backend = backend or Libvirt(config)
        token_file = self.root / 'owner.token'
        if not token_file.exists():
            token_file.write_text(secrets.token_urlsafe(32))
        os.chmod(token_file, 0o600)
        self.token = token_file.read_text().strip()
        self.kernel = CapabilityKernel(self.token)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS agents (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, data TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS requests (agent_id TEXT, request_key TEXT, digest TEXT, job_id TEXT, PRIMARY KEY(agent_id,request_key))')
            db.execute('CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL, data TEXT, prev TEXT, hash TEXT)')
        os.chmod(self.db, 0o600)
        from .missions import MissionGraphs
        self.graphs = MissionGraphs(self)
        self.event('runtime_started', version='0.4.1')
        # A provisioning thread cannot be resumed safely after process death.
        for agent in self.agents():
            if recover and agent['status'] == 'provisioning':
                agent.update(status='error', error='Control plane restarted during provisioning. Inspect the domain before retrying.')
                self.save_agent(agent)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db, timeout=20)
        try:
            db.execute('PRAGMA journal_mode=WAL')
            with db:
                yield db
        finally:
            db.close()

    def event(self, kind, **fields):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
            prev = row[0] if row else '0' * 64
            data = json.dumps({'kind': kind, **fields}, sort_keys=True, separators=(',', ':'))
            at = time.time()
            digest = hashlib.sha256((prev + str(at) + data).encode()).hexdigest()
            db.execute('INSERT INTO events(at,data,prev,hash) VALUES(?,?,?,?)', (at, data, prev, digest))

    def agents(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM agents ORDER BY rowid')]

    def agent(self, agent_id):
        checked_id(agent_id)
        with self.connect() as db:
            row = db.execute('SELECT data FROM agents WHERE id=?', (agent_id,)).fetchone()
        if not row:
            raise KeyError('Agent not found')
        return json.loads(row[0])

    def save_agent(self, agent):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO agents VALUES(?,?)', (agent['id'], json.dumps(agent)))

    def jobs(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs ORDER BY rowid DESC LIMIT 200')]

    def job(self, job_id):
        checked_id(job_id)
        with self.connect() as db:
            row = db.execute('SELECT data FROM jobs WHERE id=?', (job_id,)).fetchone()
        if not row:
            raise KeyError('Task not found')
        return json.loads(row[0])

    def save_job(self, job):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)', (job['id'], job['agent_id'], json.dumps(job)))

    def create(self, body):
        key = body.get('request_key')
        if key is not None and (not isinstance(key, str) or not re.fullmatch('[A-Za-z0-9_-]{8,100}', key)):
            raise ValueError('Invalid provisioning request key')
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with self.lock:
            if key:
                with self.connect() as db:
                    prior = db.execute("SELECT data FROM agents WHERE json_extract(data, '$.provision_key')=?", (key,)).fetchone()
                if prior:
                    agent = json.loads(prior[0])
                    if agent.get('provision_digest') != digest:
                        raise ValueError('Provisioning key conflicts with another computer request')
                    return agent
            return self._create(body, key, digest)

    def _create(self, body, provision_key, provision_digest):
        name = body.get('name')
        provider = body.get('provider')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 60 or any(ord(c) < 32 for c in name):
            raise ValueError('Name must contain 1–60 printable characters')
        if provider not in ('chatgpt', 'gemini'):
            raise ValueError('Choose ChatGPT or Gemini')
        resources = {key: body.get(key, default) for key, default in (('vcpus', 2), ('memory_mb', 4096), ('disk_gb', 32))}
        bounds = {'vcpus': (1, 16), 'memory_mb': (4096, 65536), 'disk_gb': (16, 512)}
        for key, value in resources.items():
            if type(value) is not int or not bounds[key][0] <= value <= bounds[key][1]:
                raise ValueError('Invalid ' + key)
        with self.lock:
            agents = self.agents()
            if len(agents) >= self.config['max_agents']:
                raise ValueError('Agent capacity reached')
            for key, limit in (('vcpus', 'max_vcpus'), ('memory_mb', 'max_memory_mb'), ('disk_gb', 'max_disk_gb')):
                if sum(a[key] for a in agents) + resources[key] > self.config[limit]:
                    raise ValueError('Host allocation limit reached: ' + key)
            if not self.backend.doctor()['ready']:
                raise ValueError('VM host is unavailable. Open Host status for the missing requirements.')
            agent_id = uuid.uuid4().hex
            agent = {'id': agent_id, 'domain': 'dot-' + agent_id, 'name': name.strip(), 'provider': provider,
                     'provision_key': provision_key, 'provision_digest': provision_digest,
                     'status': 'provisioning', 'created': time.time(), **resources}
            self.save_agent(agent)
            self.event('agent_create_authorized', agent_id=agent_id, resources=resources, provider=provider)
            self.pool.submit(self._provision, agent_id)
            return agent

    def _provision(self, agent_id):
        agent = self.agent(agent_id)
        try:
            domain_uuid = self.backend.provision(agent)
            agent.update(status='booting', domain_uuid=domain_uuid)
        except Exception as exc:
            agent.update(status='error', error=str(exc))
        with self.lock:
            current = self.agent(agent_id)
            current.update({k: agent[k] for k in ('status', 'error', 'domain_uuid') if k in agent})
            self.save_agent(current)
        self.event('agent_provision_result', agent_id=agent_id, status=agent['status'])

    def submit(self, agent_id, body):
        prompt = body.get('prompt')
        model = body.get('model', '')
        mode = body.get('mode', 'work')
        timeout = body.get('timeout', 600)
        acceptance = validate_checks(body.get('acceptance', {}))
        request_key = body.get('request_key')
        if request_key is not None and (not isinstance(request_key, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', request_key)):
            raise ValueError('Invalid request key')
        material = {'prompt': prompt, 'model': model, 'mode': mode, 'timeout': timeout, 'max_changed_bytes': body.get('max_changed_bytes', 16 * 1024 * 1024), 'acceptance': acceptance, 'deadline': body.get('deadline')}
        request_digest = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
        if not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 32000:
            raise ValueError('Task must contain 1–32000 characters')
        if not isinstance(model, str) or (model and not re.fullmatch(r'[a-zA-Z0-9._:-]{1,100}', model)):
            raise ValueError('Invalid model name')
        if mode not in ('plan', 'work') or type(timeout) is not int or not 30 <= timeout <= 3600:
            raise ValueError('Invalid execution mode or timeout')
        with self.lock:
            agent = self.agent(agent_id)
            if request_key is not None:
                with self.connect() as db:
                    existing = db.execute('SELECT digest,job_id FROM requests WHERE agent_id=? AND request_key=?', (agent_id, request_key)).fetchone()
                if existing:
                    if existing[0] != request_digest:
                        raise ValueError('Request key already belongs to a different task')
                    return self.job(existing[1])
            if agent['status'] != 'ready':
                raise ValueError('Agent VM is not ready')
            with self.connect() as db:
                rows = db.execute('SELECT data FROM jobs WHERE agent_id=?', (agent_id,)).fetchall()
            active = [json.loads(row[0]) for row in rows]
            if any(j['status'] not in TERMINAL for j in active):
                raise ValueError('This agent already has an active task')
            job = {'id': uuid.uuid4().hex, 'agent_id': agent_id, 'provider': agent['provider'],
                   'prompt': prompt, 'model': model, 'mode': mode, 'timeout': timeout,
                   'status': 'queued', 'created': time.time(), 'acceptance': acceptance,
                   'mission_context': {k: v for k, v in agent.get('mission', {}).items() if k != 'recent_outcomes'}}
            if agent.get('mission'):
                recent = agent['mission'].get('recent_outcomes', [])[-4:]
                job['mission_context']['recent_outcomes'] = recent
            job['lease'] = self.kernel.issue(job_id=job['id'], agent_id=agent_id, timeout=timeout, mode=mode, changed_bytes=body.get('max_changed_bytes', 16 * 1024 * 1024), deadline=body.get('deadline'))
            job['capsula_task'] = self.kernel.capsula_task(job['lease'])
            with self.connect() as db:
                db.execute('INSERT INTO jobs VALUES(?,?,?)', (job['id'], agent_id, json.dumps(job)))
                if request_key is not None:
                    db.execute('INSERT INTO requests VALUES(?,?,?,?)', (agent_id, request_key, request_digest, job['id']))
            self.event('task_authorized', job_id=job['id'], agent_id=agent_id, mode=mode,
                       prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest())
        return job

    def mission(self, agent_id, body):
        objective = body.get('objective')
        notes = body.get('notes', '')
        if not isinstance(objective, str) or not 1 <= len(objective.strip()) <= 4000 or not isinstance(notes, str) or len(notes) > 4000:
            raise ValueError('Mission requires an objective and bounded notes')
        with self.lock:
            agent = self.agent(agent_id)
            old = agent.get('mission', {})
            if body.get('revision', 0) != old.get('revision', 0):
                raise ValueError('Mission changed; refresh before editing')
            agent['mission'] = {'objective': objective.strip(), 'notes': notes, 'revision': old.get('revision', 0) + 1,
                                'updated': time.time(), 'recent_outcomes': old.get('recent_outcomes', [])}
            agent['generation'] = agent.get('generation', 0) + 1
            self.save_agent(agent)
            self.event('mission_updated', agent_id=agent_id, revision=agent['mission']['revision'])
            return agent['mission']

    def _record_outcome(self, job):
        with self.lock:
            agent = self.agent(job['agent_id'])
            mission = agent.get('mission')
            if not mission:
                return
            # Operational state, never hidden model reasoning or login caches.
            outcome = {'job_id': job['id'], 'status': job['status'], 'finished': job.get('finished', time.time()),
                       'artifacts': [a['path'][:160] for a in job.get('artifacts', [])][:3],
                       'checkpoint_id': job.get('checkpoint_id')}
            mission['recent_outcomes'] = (mission.get('recent_outcomes', []) + [outcome])[-8:]
            agent['generation'] = agent.get('generation', 0) + 1
            self.save_agent(agent)

    def workspace_action(self, agent_id, action, identity=None):
        with self.lock:
            agent = self.agent(agent_id)
            with self.connect() as db:
                active = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE agent_id=?', (agent_id,))]
            if any(j['status'] not in TERMINAL for j in active):
                raise ValueError('Finish or cancel the active task before checkpoint operations')
            if action not in ('list', 'create', 'restore'):
                raise ValueError('Invalid checkpoint action')
            args = (action, checked_id(identity)) if action == 'restore' else (action,)
            result = self.backend.guest(agent, 'checkpoints', *args)
            self.event('checkpoint_' + action, agent_id=agent_id, checkpoint_id=identity)
            return result

    def import_workspace(self, agent_id, data):
        with self.lock:
            agent = self.agent(agent_id)
            if agent['status'] != 'ready':
                raise ValueError('Computer must be ready before workspace import')
            with self.connect() as db:
                agent_jobs = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE agent_id=?', (agent_id,))]
            if any(j['status'] not in TERMINAL for j in agent_jobs):
                raise ValueError('Finish or cancel active work before importing project files')
            result = self.backend.guest(agent, 'workspace_import', data=data)
            self.event('workspace_imported', agent_id=agent_id, files=result.get('imported'), checkpoint_id=result.get('checkpoint_id'))
            return result

    def job_lock(self, job_id):
        with self.lock:
            return self.job_locks.setdefault(job_id, threading.RLock())

    def cancel(self, job_id):
        with self.job_lock(job_id):
            job = self.job(job_id)
            if job['status'] in TERMINAL:
                return job
            if job['status'] == 'queued':
                job.update(status='cancelled', finished=time.time())
                job['receipt'] = execution_receipt(job)
                self.save_job(job)
            else:
                job.update(status='cancelling', cancel_requested_at=time.time())
                self.save_job(job)
                # Intent is durable before SSH. Polling retries this idempotent stop after reconnect.
                try:
                    self.backend.guest(self.agent(job['agent_id']), 'cancel', job_id)
                    job.pop('connection_error', None)
                except Exception as exc:
                    job['connection_error'] = str(exc)
                self.save_job(job)
            self.event('task_cancel_authorized', job_id=job_id)
            return job

    def power(self, agent_id, action):
        with self.lock:
            agent = self.agent(agent_id)
            if agent['status'] in ('provisioning', 'booting'):
                raise ValueError('Wait for VM provisioning to finish')
            if action == 'start':
                self.backend.start(agent)
                agent['status'] = 'booting'
            elif action == 'stop':
                with self.connect() as db:
                    active = [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE agent_id=?', (agent_id,))]
                if any(j['status'] not in TERMINAL for j in active):
                    raise ValueError('Cancel the active task before stopping the VM')
                self.backend.stop(agent)
                agent['status'] = 'stopping'
            else:
                raise ValueError('Invalid power action')
            agent['generation'] = agent.get('generation', 0) + 1
            self.save_agent(agent)
            self.event('vm_' + action, agent_id=agent_id)
        return agent

    def reconcile(self, agent_id):
        with self.lock:
            agent = self.agent(agent_id)
            if agent['status'] == 'provisioning':
                raise ValueError('Provisioning is still running')
            observed = self.backend.inspect(agent)
            agent.update(observed)
            agent['status'] = 'booting' if observed['power_state'] == 'running' else 'stopped'
            agent['generation'] = agent.get('generation', 0) + 1
            agent.pop('error', None)
            self.save_agent(agent)
            self.event('vm_reconciled', agent_id=agent_id, domain_uuid=observed['domain_uuid'])
        return agent

    def _refresh_agent(self, agent_id):
        agent = self.agent(agent_id)
        if agent['status'] in ('provisioning', 'error'):
            return
        try:
            state = self.backend.state(agent)
            agent['power_state'] = state
            if state == 'running':
                health = self.backend.guest(agent, 'health')
                agent['health'] = health
                if health.get('protocol_version') != '0.3':
                    raise RuntimeError('Guest runtime upgrade required: expected protocol 0.3')
                if self.config.get('expected_kernel') and health.get('kernel_release') != self.config['expected_kernel']:
                    raise RuntimeError('Expected custom Linux kernel did not boot')
                agent['status'] = 'ready' if health['ready'] and health.get('firewall_receipt', False) and all(v != 'unavailable' for v in health['versions'].values()) else 'booting'
                agent['ip'] = self.backend.address(agent)
            else:
                agent['status'] = 'stopped'
            agent.pop('connection_error', None)
        except Exception as exc:
            agent['connection_error'] = str(exc)
            if agent['status'] == 'ready':
                agent['status'] = 'unreachable'
        with self.lock:
            current = self.agent(agent_id)
            if current.get('generation', 0) != agent.get('generation', 0):
                return
            if current['status'] not in ('stopping',) or agent.get('power_state') != 'running':
                self.save_agent(agent)

    def _advance_job(self, job_id):
        with self.job_lock(job_id):
            job = self.job(job_id)
            if job['status'] in TERMINAL:
                return
            agent = self.agent(job['agent_id'])
            try:
                if job['status'] == 'queued':
                    try:
                        self.kernel.verify(job['lease'], agent_id=agent['id'], job_id=job_id)
                    except ValueError as exc:
                        job.update(status='failed', error=str(exc), finished=time.time())
                        job['receipt'] = execution_receipt(job)
                        self.save_job(job)
                        self.event('mission_denied', job_id=job_id, reason=str(exc))
                        return
                    # Persist dispatch intent before the side effect; never retry an ambiguous submission.
                    job.update(status='dispatching')
                    self.save_job(job)
                    self.backend.guest(agent, 'submit', data={k: job[k] for k in ('id', 'provider', 'prompt', 'model', 'mode', 'timeout', 'lease', 'acceptance', 'mission_context')})
                    job.update(status='running')
                else:
                    result = validate_outcome(self.backend.guest(agent, 'status', job_id), job_id)
                    if job['status'] == 'cancelling' and result['status'] == 'running':
                        self.backend.guest(agent, 'cancel', job_id)
                        result = validate_outcome(self.backend.guest(agent, 'status', job_id), job_id)
                    if 'delegations' in result:
                        job['delegations'] = result['delegations']
                    if result.get('checkpoint_id'):
                        job['checkpoint_id'] = result['checkpoint_id']
                    if result['status'] in TERMINAL:
                        job.update(result)
                        if job['status'] == 'completed' and any(job.get('acceptance', {}).values()) and not evidence_matches(job['acceptance'], job.get('acceptance_result')):
                            job.update(status='failed', error='Guest did not supply passing acceptance evidence')
                        job['receipt'] = execution_receipt(job)
                        self._record_outcome(job)
                        self.event('task_finished', job_id=job_id, status=job['status'],
                                   response_sha256=hashlib.sha256(job.get('response', '').encode()).hexdigest())
                    elif result['status'] == 'running' and job['status'] == 'dispatching':
                        job['status'] = 'running'
                job.pop('connection_error', None)
            except Exception as exc:
                job['connection_error'] = str(exc)
                # Connection failure is NOT task completion/failure; poll again after reconnect.
            self.save_job(job)

    def tick(self):
        self.graphs.advance()
        for agent in self.agents():
            if agent['status'] not in ('provisioning', 'error', 'stopped'):
                self._schedule('agent:' + agent['id'], self._refresh_agent, agent['id'])
        with self.connect() as db:
            ids = [row[0] for row in db.execute('SELECT id,data FROM jobs') if json.loads(row[1])['status'] not in TERMINAL]
        for job_id in ids:
            self._schedule('job:' + job_id, self._advance_job, job_id)

    def _schedule(self, key, fn, arg):
        with self.lock:
            if key in self.inflight:
                return
            self.inflight.add(key)
        def wrapped():
            try:
                fn(arg)
            finally:
                with self.lock:
                    self.inflight.discard(key)
        self.pool.submit(wrapped)

    def watch(self):
        while not self.stop_event.is_set():
            self.tick()
            self.stop_event.wait(5)

    def close(self):
        self.stop_event.set()
        self.pool.shutdown(wait=True)

    def receipts(self):
        with self.connect() as db:
            return [{'seq': seq, 'at': at, 'data': json.loads(data), 'prev': prev, 'hash': digest}
                    for seq, at, data, prev, digest in db.execute('SELECT seq,at,data,prev,hash FROM events ORDER BY seq')]
