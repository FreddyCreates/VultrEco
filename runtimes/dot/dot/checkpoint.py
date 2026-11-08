"""Content-addressed workspace checkpoints. Never snapshots provider credential directories."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import time
import uuid

MAX_BYTES = 128 * 1024 * 1024


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('x') as f:
        os.chmod(temp, 0o600)
        json.dump(value, f, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


@contextmanager
def workspace_guard(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / 'workspace.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Workspace is busy; cancel or finish the current task first')
        yield


def relative_path(value):
    if not isinstance(value, str) or not value or '\\' in value or '\0' in value:
        raise ValueError('Invalid checkpoint path')
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or str(path) != value or value == '.':
        raise ValueError('Checkpoint path escapes workspace')
    return path


class Checkpoints:
    def __init__(self, root, work):
        self.root = Path(root) / 'checkpoints'
        self.work = Path(work)
        self.blobs = self.root / 'blobs'
        self.manifests = self.root / 'manifests'
        for directory in (self.blobs, self.manifests):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def create(self, reason='manual'):
        if self.work.is_symlink():
            raise ValueError('Workspace cannot be a symlink')
        self.work.mkdir(parents=True, exist_ok=True, mode=0o700)
        items, directories, total = [], [], 0
        for path in sorted(self.work.rglob('*')):
            if path.is_symlink():
                raise ValueError('Checkpoint refuses symlinks: ' + str(path.relative_to(self.work)))
            rel = str(path.relative_to(self.work))
            relative_path(rel)
            if path.is_dir():
                directories.append(rel)
                continue
            # Never block on a FIFO or follow a swapped final symlink.
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as f:
                before = os.fstat(f.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise ValueError('Checkpoint supports regular files only')
                total += before.st_size
                if total > MAX_BYTES or len(items) >= 10000:
                    raise ValueError('Checkpoint workspace limit exceeded')
                data = f.read(MAX_BYTES + 1)
                after = os.fstat(f.fileno())
                if len(data) != before.st_size or (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                    raise ValueError('Workspace changed during checkpoint')
            digest = hashlib.sha256(data).hexdigest()
            blob = self.blobs / digest
            if blob.exists():
                if hashlib.sha256(blob.read_bytes()).hexdigest() != digest:
                    raise ValueError('Checkpoint blob corruption')
            else:
                with blob.open('xb') as f:
                    os.chmod(blob, 0o600)
                    f.write(data)
            items.append({'path': rel, 'sha256': digest, 'size': len(data), 'executable': bool(before.st_mode & 0o111)})
        identity = uuid.uuid4().hex
        manifest = {'schema': 'dot.workspace-checkpoint.v1', 'id': identity, 'created': time.time(),
                    'reason': str(reason)[:200], 'bytes': total, 'files': items, 'directories': directories}
        atomic_json(self.manifests / (identity + '.json'), manifest)
        return manifest

    def get(self, identity):
        if not isinstance(identity, str) or not re.fullmatch('[a-f0-9]{32}', identity):
            raise ValueError('Invalid checkpoint ID')
        manifest = json.loads((self.manifests / (identity + '.json')).read_text())
        if manifest.get('id') != identity:
            raise ValueError('Checkpoint identity mismatch')
        return manifest

    def list(self):
        return [{'id': m['id'], 'created': m['created'], 'reason': m['reason'], 'bytes': m['bytes'], 'files': len(m['files'])}
                for m in (json.loads(p.read_text()) for p in sorted(self.manifests.glob('*.json'))) ]

    def recover(self):
        journal = self.root / 'restore-journal.json'
        if not journal.exists():
            return
        record = json.loads(journal.read_text())
        suffix = record['operation']
        if not re.fullmatch('[a-f0-9]{32}', suffix):
            raise ValueError('Invalid restore journal')
        old = self.work.with_name(self.work.name + '.old-' + suffix)
        stage = self.work.with_name(self.work.name + '.stage-' + suffix)
        # If the new workspace was never installed, restore the previous directory.
        if not self.work.exists() and old.exists():
            os.replace(old, self.work)
        if old.exists() and self.work.exists():
            shutil.rmtree(old)
        if stage.exists():
            shutil.rmtree(stage)
        journal.unlink()

    def restore(self, identity):
        self.recover()
        manifest = self.get(identity)
        # Preserve the current contents before replacing anything.
        before = self.create('before-restore:' + identity)
        operation = uuid.uuid4().hex
        stage = self.work.with_name(self.work.name + '.stage-' + operation)
        old = self.work.with_name(self.work.name + '.old-' + operation)
        stage.mkdir(mode=0o700)
        try:
            entries = manifest['files']
            if len(entries) > 10000 or sum(x['size'] for x in entries) > MAX_BYTES:
                raise ValueError('Invalid checkpoint size')
            seen = set()
            for directory in manifest.get('directories', []):
                (stage / relative_path(directory)).mkdir(parents=True, exist_ok=True, mode=0o700)
            for item in entries:
                path = relative_path(item['path'])
                if str(path) in seen:
                    raise ValueError('Duplicate checkpoint path')
                seen.add(str(path))
                digest = item['sha256']
                if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
                    raise ValueError('Invalid checkpoint hash')
                data = (self.blobs / digest).read_bytes()
                if len(data) != item['size'] or hashlib.sha256(data).hexdigest() != digest:
                    raise ValueError('Checkpoint blob corruption')
                destination = stage / path
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                destination.write_bytes(data)
                os.chmod(destination, 0o700 if item.get('executable') else 0o600)
            atomic_json(self.root / 'restore-journal.json', {'operation': operation, 'checkpoint_id': identity})
            os.replace(self.work, old)
            os.replace(stage, self.work)
            shutil.rmtree(old)
            (self.root / 'restore-journal.json').unlink()
        except Exception:
            if (self.root / 'restore-journal.json').exists():
                self.recover()
            elif stage.exists():
                shutil.rmtree(stage)
            raise
        return {'restored': identity, 'undo_checkpoint': before['id'], 'files': len(entries)}
