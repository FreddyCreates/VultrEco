"""Run explicit owner acceptance commands inside the guest, after the model exits."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tempfile
import time


def validate_checks(value):
    if not isinstance(value, dict) or set(value) - {'commands', 'files'}:
        raise ValueError('Acceptance must contain commands and/or files')
    commands, files = value.get('commands', []), value.get('files', [])
    if not isinstance(commands, list) or len(commands) > 8 or not isinstance(files, list) or len(files) > 32:
        raise ValueError('Acceptance limit exceeded')
    for cmd in commands:
        if not isinstance(cmd, list) or not 1 <= len(cmd) <= 32 or not all(isinstance(x, str) and x and len(x) <= 500 and '\0' not in x for x in cmd):
            raise ValueError('Acceptance commands must be argument arrays')
        # No shell-string interpretation; these commands still execute code in the VM.
        if cmd[0] not in ('python3', 'node', 'npm', 'git', 'make', 'cargo', 'go'):
            raise ValueError('Unsupported acceptance executable')
    for item in files:
        if not isinstance(item, dict) or set(item) - {'path', 'sha256', 'contains'}:
            raise ValueError('Invalid file acceptance check')
        path = item.get('path')
        if not isinstance(path, str) or not path or '\\' in path or '\0' in path:
            raise ValueError('Invalid acceptance file path')
        p = PurePosixPath(path)
        if p.is_absolute() or '..' in p.parts or str(p) != path or path == '.':
            raise ValueError('Acceptance path escapes workspace')
        for key in ('sha256', 'contains'):
            if key in item and (not isinstance(item[key], str) or len(item[key]) > 10000):
                raise ValueError('Invalid file acceptance value')
    return {'commands': commands, 'files': files}


def verify(work, checks, deadline, env=None):
    work = Path(work)
    checks = validate_checks(checks)
    results = []
    for argv in checks['commands']:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise TimeoutError('Acceptance time budget exhausted')
        with tempfile.TemporaryFile() as log:
            proc = subprocess.Popen(argv, cwd=work, env=env, stdout=log, stderr=log, start_new_session=True)
            try:
                while proc.poll() is None:
                    if time.time() >= deadline:
                        raise subprocess.TimeoutExpired(argv, remaining)
                    if log.tell() > 1024 * 1024:
                        raise RuntimeError('Acceptance output limit exceeded')
                    time.sleep(0.02)
            except BaseException:
                # Kill descendants of the acceptance command too, including on cancellation.
                import os, signal
                try: os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                proc.wait()
                raise
            log.seek(0)
            output = log.read(1024 * 1024 + 1)
        results.append({'argv': argv, 'passed': proc.returncode == 0 and len(output) <= 1024 * 1024,
                        'exit_code': proc.returncode, 'output_sha256': hashlib.sha256(output).hexdigest(),
                        'output_tail': output[-2000:].decode(errors='replace')})
    for item in checks['files']:
        path = work / item['path']
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(work.resolve()):
                raise ValueError('Acceptance file is outside workspace')
            if path.stat().st_size > 16 * 1024 * 1024:
                raise ValueError('Acceptance file exceeds size limit')
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            passed = ('sha256' not in item or digest == item['sha256']) and ('contains' not in item or item['contains'].encode() in data)
            results.append({'path': item['path'], 'passed': passed, 'sha256': digest})
        except (OSError, ValueError) as exc:
            results.append({'path': item['path'], 'passed': False, 'error': str(exc)})
    return {'schema': 'dot.acceptance-result.v1', 'passed': all(r['passed'] for r in results),
            'configured': bool(results), 'checks': results, 'finished': time.time()}


def evidence_matches(contract, evidence):
    """A passing flag alone is insufficient; match every owner-requested check in order."""
    contract = validate_checks(contract)
    if not isinstance(evidence, dict) or evidence.get('passed') is not True:
        return False
    expected = [('argv', x) for x in contract['commands']] + [('path', x['path']) for x in contract['files']]
    results = evidence.get('checks')
    if not isinstance(results, list) or len(results) != len(expected):
        return False
    for (kind, value), observed in zip(expected, results):
        if not isinstance(observed, dict) or observed.get(kind) != value or observed.get('passed') is not True:
            return False
        if kind == 'argv' and observed.get('exit_code') != 0:
            return False
    for wanted, observed in zip(contract['files'], results[len(contract['commands']):]):
        if wanted.get('sha256') and wanted['sha256'] != observed.get('sha256'):
            return False
    return True
