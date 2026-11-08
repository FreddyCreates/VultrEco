"""Validate untrusted guest outcomes without allowing a guest to rewrite host authority."""
import math
from pathlib import PurePosixPath
import re


def validate_outcome(result, job_id):
    if not isinstance(result, dict) or result.get('id', job_id) != job_id:
        raise ValueError('Guest outcome identity mismatch')
    status = result.get('status')
    if status not in ('running', 'completed', 'failed', 'cancelled', 'lost'):
        raise ValueError('Invalid guest outcome status')
    clean = {'status': status}
    for key in ('started', 'finished'):
        if key in result:
            value = result[key]
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError('Invalid guest timestamp')
            clean[key] = value
    for key in ('error', 'response'):
        if key in result and result[key] is not None:
            if not isinstance(result[key], str) or len(result[key].encode()) > 8 * 1024 * 1024:
                raise ValueError('Invalid guest text')
            clean[key] = result[key]
    if status == 'completed' and not clean.get('response', '').strip():
        raise ValueError('Guest completion has no response')
    if 'changed_bytes' in result:
        if type(result['changed_bytes']) is not int or result['changed_bytes'] < 0:
            raise ValueError('Invalid changed-byte count')
        clean['changed_bytes'] = result['changed_bytes']
    if 'artifacts' in result:
        artifacts = result['artifacts']
        if not isinstance(artifacts, list) or len(artifacts) > 10000:
            raise ValueError('Invalid guest artifact list')
        clean['artifacts'] = []
        seen = set()
        for item in artifacts:
            if not isinstance(item, dict):
                raise ValueError('Invalid artifact')
            path = item.get('path')
            if not isinstance(path, str) or not path or '\x00' in path or '\\' in path:
                raise ValueError('Invalid artifact path')
            p = PurePosixPath(path)
            if p.is_absolute() or '..' in p.parts or str(p) != path or path in seen:
                raise ValueError('Artifact path escapes scope or duplicates another artifact')
            digest = item.get('sha256')
            if not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest):
                raise ValueError('Invalid artifact hash')
            size = item.get('size', 0)
            if type(size) is not int or size < 0:
                raise ValueError('Invalid artifact size')
            clean['artifacts'].append({'path': path, 'size': size, 'sha256': digest})
            seen.add(path)
    if 'checkpoint_id' in result:
        value = result['checkpoint_id']
        if not isinstance(value, str) or not re.fullmatch('[a-f0-9]{32}', value):
            raise ValueError('Invalid checkpoint ID')
        clean['checkpoint_id'] = value
    if 'acceptance' in result:
        value = result['acceptance']
        if not isinstance(value, dict) or type(value.get('passed')) is not bool or not isinstance(value.get('checks'), list) or len(value['checks']) > 40:
            raise ValueError('Invalid acceptance result')
        if len(str(value)) > 150000:
            raise ValueError('Acceptance result too large')
        clean['acceptance_result'] = value
    if 'delegations' in result:
        from .delegation import requests
        clean['delegations'] = requests(result['delegations'])
    return clean
