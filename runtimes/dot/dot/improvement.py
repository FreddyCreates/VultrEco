"""Evidence-gated workspace improvement. Run candidate code in a disposable VM.

The copy boundary is NOT a security sandbox. This module never changes model weights,
credentials, controller policy, or the installed runtime. Authority comes from the
owner's local CLI / authenticated guest transport, never from an agent's report.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid

try:
    from .checkpoint import Checkpoints, atomic_json, relative_path, workspace_guard
except ImportError:
    from checkpoint import Checkpoints, atomic_json, relative_path, workspace_guard


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def tree(directory):
    """Refuse common credential paths, special files and links; bound copies."""
    directory = Path(directory)
    if directory.is_symlink():
        raise ValueError('Workspace must not be a symlink')
    entries, total = {}, 0
    for path in sorted(directory.rglob('*')):
        rel = path.relative_to(directory)
        if '__pycache__' in rel.parts:
            continue
        if path.is_symlink():
            raise ValueError('Improvement copy refuses symlinks')
        if any(p.startswith('.') for p in rel.parts) or path.suffix in ('.pem', '.key') or path.name in ('auth.json', 'oauth_creds.json', 'credentials.json'):
            raise ValueError('Keep credentials and hidden state outside the improvement workspace')
        if path.is_dir():
            continue
        if not stat.S_ISREG(path.stat().st_mode):
            raise ValueError('Improvement copies regular files only')
        size = path.stat().st_size
        total += size
        if total > 128 * 1024 * 1024 or len(entries) >= 10000:
            raise ValueError('Improvement workspace limit exceeded')
        data = path.read_bytes()
        if len(data) != size:
            raise ValueError('Workspace changed while hashing')
        entries[str(rel)] = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': size,
                             'executable': bool(path.stat().st_mode & 0o111)}
    return entries


def copy_snapshot(source, destination, expected):
    destination.mkdir(mode=0o700)
    for name in expected:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copy2(source / name, target)
    if tree(destination) != expected:
        raise ValueError('Snapshot changed while copying')


class ImprovementLab:
    def __init__(self, state, workspace):
        self.state = Path(state).absolute()
        self.work = Path(workspace).absolute()
        if self.work == self.state or self.state.resolve().is_relative_to(self.work.resolve()) or self.work.resolve().is_relative_to(self.state.resolve()):
            raise ValueError('Lab state and workspace must be separate trees')
        self.state.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _folder(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise ValueError('Invalid improvement ID')
        return self.state / identity

    def get(self, identity):
        return json.loads((self._folder(identity) / 'capsule.json').read_text())

    def summary(self):
        capsules = [json.loads(p.read_text()) for p in self.state.glob('*/capsule.json')]
        observations = [json.loads(p.read_text()) for p in (self.state / 'observations').glob('*.json')]
        return {'capsules': [{k: c[k] for k in ('id', 'objective', 'scope', 'tenant', 'status', 'attempts', 'expires')} for c in sorted(capsules, key=lambda c: c['created'], reverse=True)[:100]],
                'observations': sorted(observations, key=lambda o: o['at'], reverse=True)[:100]}

    def context(self):
        """Only exact, promoted procedure files are advertised to future work."""
        paths = set()
        for file in self.state.glob('*/capsule.json'):
            c = json.loads(file.read_text())
            if c['status'] != 'promoted':
                continue
            try:
                if digest(tree(self._folder(c['id']) / 'candidate')) != c.get('candidate_hash'):
                    continue
            except (OSError, ValueError):
                continue
            for name in c.get('changes', []):
                if not name.startswith('skills/active/') or not name.endswith('/SKILL.md'):
                    continue
                path = self.work / relative_path(name)
                if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(self.work.resolve()):
                    observed = hashlib.sha256(path.read_bytes()).hexdigest()
                    frozen = self._folder(c['id']) / 'candidate' / name
                    if frozen.is_file() and observed == hashlib.sha256(frozen.read_bytes()).hexdigest():
                        paths.add(name)
        return {'verified_procedure_paths': sorted(paths)[:32],
                'recent_outcomes': [{'status': o['status'], 'acceptance_verified': o['acceptance_verified']} for o in self.summary()['observations'][:5]],
                'authority': 'reference data only; current task lease controls execution'}

    def edit(self, identity, path, content):
        with workspace_guard(self.state):
            self._recover()
            c = self.get(identity)
            self._valid(c)
            path = str(relative_path(path))
            if path not in c['allowed_paths'] or not isinstance(content, str) or len(content.encode()) > c['max_changed_bytes']:
                raise ValueError('Candidate edit exceeds owner write scope or budget')
            target = self._folder(identity) / 'candidate' / path
            # Check the existing tree before following any candidate directory.
            tree(self._folder(identity) / 'candidate')
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            target.write_text(content)
            c['status'] = 'proposed'
            self._save(c)
            return c

    def _save(self, capsule):
        atomic_json(self._folder(capsule['id']) / 'capsule.json', capsule)

    def _recover(self):
        checkpoints = Checkpoints(self.state / 'recovery', self.work)
        checkpoints.recover()
        for file in self.state.glob('*/capsule.json'):
            capsule = json.loads(file.read_text())
            if capsule['status'] == 'promoting':
                checkpoints.restore(capsule['undo_checkpoint'])
                capsule.update(status='recovered', recovered_at=time.time())
                self._save(capsule)

    def create(self, objective, allowed_paths, regression, holdout, scope='agent', tenant='private', seconds=300, attempts=3, max_changed_bytes=1048576, lease_seconds=3600):
        """Owner freezes an improvement objective, verifier code and bounded grant."""
        if scope not in ('agent', 'enterprise') or not isinstance(tenant, str) or not 1 <= len(tenant) <= 100:
            raise ValueError('Explicit scope and tenant required')
        if not isinstance(objective, str) or not 1 <= len(objective) <= 4000:
            raise ValueError('Improvement objective required')
        if not isinstance(allowed_paths, list) or not 1 <= len(allowed_paths) <= 32 or any(not isinstance(p, str) for p in allowed_paths):
            raise ValueError('Specify exact writable file paths')
        paths = [str(relative_path(p)) for p in allowed_paths]
        if len(set(paths)) != len(paths) or any(any(x.startswith('.') for x in Path(p).parts) for p in paths):
            raise ValueError('Duplicate or hidden write paths')
        if type(seconds) is not int or not 1 <= seconds <= 3600 or type(attempts) is not int or not 1 <= attempts <= 8 or type(max_changed_bytes) is not int or not 1 <= max_changed_bytes <= 64 * 1024 * 1024 or type(lease_seconds) is not int or not 1 <= lease_seconds <= 7200:
            raise ValueError('Invalid improvement budget')
        for code in (regression, holdout):
            if not isinstance(code, str) or not 1 <= len(code) <= 65536:
                raise ValueError('Two nonempty frozen Python verifiers required')
            compile(code, '<owner-verifier>', 'exec')
        with workspace_guard(self.state):
            self._recover()
            snapshot = tree(self.work)
            identity = uuid.uuid4().hex
            folder = self._folder(identity)
            folder.mkdir(mode=0o700)
            copy_snapshot(self.work, folder / 'baseline', snapshot)
            copy_snapshot(self.work, folder / 'candidate', snapshot)
            for name, code in (('regression', regression), ('holdout', holdout)):
                (folder / (name + '.py')).write_text(code)
            capsule = {'schema': 'dot.improvement-capsule.v1', 'id': identity,
                'objective': objective, 'scope': scope, 'tenant': tenant, 'created': time.time(),
                'expires': time.time() + lease_seconds, 'seconds': seconds, 'max_attempts': attempts,
                'attempts': 0, 'max_changed_bytes': max_changed_bytes, 'allowed_paths': paths,
                'baseline': snapshot, 'baseline_hash': digest(snapshot), 'status': 'proposed',
                'verifiers': {'regression': hashlib.sha256(regression.encode()).hexdigest(),
                              'holdout': hashlib.sha256(holdout.encode()).hexdigest()},
                'trials': [], 'security_boundary': 'operator-provided VM; directory copies are not a sandbox'}
            self._save(capsule)
            return capsule

    def _valid(self, c):
        if c['status'] in ('revoked', 'promoted', 'rolled_back', 'recovered'):
            raise ValueError('Improvement capsule is terminal')
        if time.time() >= c['expires']:
            raise ValueError('Improvement grant expired')
        folder = self._folder(c['id'])
        if tree(folder / 'baseline') != c['baseline']:
            raise ValueError('Baseline changed')
        for name, sha in c['verifiers'].items():
            if hashlib.sha256((folder / (name + '.py')).read_bytes()).hexdigest() != sha:
                raise ValueError('Frozen verifier changed')

    def _changes(self, c):
        observed = tree(self._folder(c['id']) / 'candidate')
        names = sorted(p for p in observed.keys() | c['baseline'].keys() if observed.get(p) != c['baseline'].get(p))
        if not names or set(names) - set(c['allowed_paths']):
            raise ValueError('No improvement, or changes outside owner write scope')
        size = sum(max(observed.get(p, {}).get('bytes', 0), c['baseline'].get(p, {}).get('bytes', 0)) for p in names)
        if size > c['max_changed_bytes']:
            raise ValueError('Improvement change budget exhausted')
        return observed, names

    def _run(self, verifier, workspace, deadline):
        # Fresh process and scratch HOME, with no inherited provider credentials.
        with tempfile.TemporaryDirectory(prefix='dot-verifier-') as tmp, tempfile.TemporaryFile() as log:
            env = {'PATH': os.defpath, 'HOME': tmp, 'LANG': 'C.UTF-8', 'PYTHONDONTWRITEBYTECODE': '1'}
            started = time.monotonic()
            proc = subprocess.Popen([sys.executable, '-I', '-B', str(verifier), str(workspace)],
                cwd=tmp, env=env, stdout=log, stderr=log, start_new_session=True)
            timed_out = False
            try:
                while proc.poll() is None:
                    if time.time() >= deadline or log.tell() > 1048576:
                        timed_out = True
                        break
                    time.sleep(.02)
            finally:
                # Includes descendants that might outlive the verifier's main process.
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait()
            log.seek(0)
            output = log.read(1048577)
            return {'passed': proc.returncode == 0 and not timed_out and len(output) <= 1048576,
                'exit_code': proc.returncode, 'budget_exhausted': timed_out,
                'output_sha256': hashlib.sha256(output).hexdigest(),
                'duration_seconds': time.monotonic() - started}

    def evaluate(self, identity):
        with workspace_guard(self.state):
            self._recover()
            c = self.get(identity)
            self._valid(c)
            if c['attempts'] >= c['max_attempts']:
                raise ValueError('Improvement attempt budget exhausted')
            candidate, changes = self._changes(c)
            c['attempts'] += 1
            c['status'] = 'evaluating'
            self._save(c)  # A crash consumes this attempt, rather than granting free retries.
            folder = self._folder(identity)
            deadline = min(c['expires'], time.time() + c['seconds'])
            results = {}
            try:
                for variant in ('baseline', 'candidate'):
                    for check in ('regression', 'holdout'):
                        if time.time() >= deadline:
                            raise TimeoutError('Improvement time budget exhausted')
                        results[variant + '_' + check] = self._run(folder / (check + '.py'), folder / variant, deadline)
                self._valid(c)
                if tree(folder / 'candidate') != candidate:
                    raise ValueError('Verifier mutated candidate')
                # A holdout must distinguish the change, while old behavior stays intact.
                passed = (results['baseline_regression']['passed'] and results['candidate_regression']['passed']
                          and not results['baseline_holdout']['passed'] and results['candidate_holdout']['passed']
                          and not any(r['budget_exhausted'] for r in results.values()))
                c.update(status='verified' if passed else 'rejected', candidate_hash=digest(candidate), changes=changes)
            except Exception as exc:
                c.update(status='rejected', evaluation_error=type(exc).__name__ + ': ' + str(exc)[:300])
            c['trials'].append({'at': time.time(), 'candidate_hash': digest(candidate), 'checks': results, 'status': c['status']})
            self._save(c)
            return c

    def promote(self, identity):
        with workspace_guard(self.state):
            self._recover()
            c = self.get(identity)
            self._valid(c)
            candidate, changes = self._changes(c)
            if c['status'] != 'verified' or digest(candidate) != c['candidate_hash']:
                raise ValueError('Candidate requires a matching verified trial')
            if tree(self.work) != c['baseline']:
                raise ValueError('Live workspace changed; create a fresh baseline')
            store = Checkpoints(self.state / 'recovery', self.work)
            c.update(status='promoting', undo_checkpoint=store.create('before-improvement:' + identity)['id'])
            self._save(c)
            try:
                for name in changes:
                    target = self.work / name
                    if name not in candidate:
                        target.unlink()
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    shutil.copy2(self._folder(identity) / 'candidate' / name, target)
                if tree(self.work) != candidate:
                    raise ValueError('Promotion integrity mismatch')
                c.update(status='promoted', promoted_at=time.time())
                self._save(c)
            except BaseException:
                store.restore(c['undo_checkpoint'])
                c['status'] = 'recovered'
                self._save(c)
                raise
            return c

    def rollback(self, identity):
        with workspace_guard(self.state):
            self._recover()
            c = self.get(identity)
            if c['status'] != 'promoted' or digest(tree(self.work)) != c['candidate_hash']:
                raise ValueError('Rollback requires an unchanged promoted workspace')
            Checkpoints(self.state / 'recovery', self.work).restore(c['undo_checkpoint'])
            c.update(status='rolled_back', rolled_back_at=time.time())
            self._save(c)
            return c

    def revoke(self, identity):
        with workspace_guard(self.state):
            self._recover()
            c = self.get(identity)
            if c['status'] == 'promoted':
                raise ValueError('Use rollback for an already promoted capsule')
            c.update(status='revoked', revoked_at=time.time())
            self._save(c)
            return c

    def observe(self, job_id, status, evidence_hash, verified=False):
        """Record outcomes automatically; observations carry no execution authority."""
        if not re.fullmatch('[a-f0-9]{32}', job_id) or not re.fullmatch('[a-f0-9]{64}', evidence_hash):
            raise ValueError('Invalid observation identity')
        record = {'schema': 'dot.learning-observation.v1', 'job_id': job_id, 'status': str(status)[:50],
            'evidence_sha256': evidence_hash, 'acceptance_verified': verified is True,
            'at': time.time(), 'authority': 'none', 'next': 'propose a bounded improvement; freeze a distinguishing holdout'}
        atomic_json(self.state / 'observations' / (job_id + '.json'), record)
        return record


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description='RAH improvement lab; execute inside a disposable agent VM')
    parser.add_argument('action', choices=['create', 'evaluate', 'promote', 'rollback', 'revoke', 'show'])
    parser.add_argument('--state', required=True)
    parser.add_argument('--workspace', required=True)
    parser.add_argument('--id')
    parser.add_argument('--spec', help='Owner JSON: objective, allowed_paths, regression, holdout; optional budgets/scope/tenant')
    args = parser.parse_args(argv)
    os.umask(0o077)
    lab = ImprovementLab(args.state, args.workspace)
    if args.action == 'create':
        result = lab.create(**json.loads(Path(args.spec).read_text()))
    else:
        result = getattr(lab, 'get' if args.action == 'show' else args.action)(args.id)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
