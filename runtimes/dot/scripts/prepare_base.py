#!/usr/bin/env python3
"""Bake a checksum-verified official Node distribution into a fresh Linux qcow2."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def prepare(base, base_hash, node, node_hash, out):
    base, node, out = [Path(p).resolve() for p in (base, node, out)]
    if out.exists():
        raise ValueError('Output must be a new image')
    for path, expected in ((base, base_hash), (node, node_hash)):
        with path.open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() != expected:
                raise ValueError('Checksum mismatch: ' + path.name)
    shutil.copyfile(base, out)
    subprocess.run(['virt-customize', '-a', str(out), '--upload', str(node) + ':/tmp/node.tar.xz',
                    '--run-command', 'mkdir -p /opt/node && tar -xJf /tmp/node.tar.xz --strip-components=1 -C /opt/node',
                    '--run-command', 'ln -sf /opt/node/bin/node /usr/local/bin/node && ln -sf /opt/node/bin/npm /usr/local/bin/npm && ln -sf /opt/node/bin/npx /usr/local/bin/npx',
                    '--run-command', 'test "$(node -p \'parseInt(process.versions.node)\')" -ge 20',
                    '--delete', '/tmp/node.tar.xz'], check=True)
    with out.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    result = {'path': str(out), 'sha256': digest, 'status': 'base_prepared', 'boot_verified': False}
    out.with_suffix('.receipt.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--base-sha256', required=True)
    p.add_argument('--node-archive', required=True)
    p.add_argument('--node-sha256', required=True)
    p.add_argument('--out', required=True)
    a=p.parse_args()
    print(json.dumps(prepare(a.base,a.base_sha256,a.node_archive,a.node_sha256,a.out),indent=2))
