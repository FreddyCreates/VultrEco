#!/usr/bin/env python3
"""Install a compiled custom kernel into a COPY of an Ubuntu qcow2 base image."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def install(base, expected_sha256, kernel_dir, out):
    base, kernel_dir, out = map(lambda p: Path(p).resolve(), (base, kernel_dir, out))
    if out.exists():
        raise ValueError('Output image must be new')
    with base.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != expected_sha256:
            raise ValueError('Base image SHA-256 mismatch')
    receipt = json.loads((kernel_dir / 'kernel-build-receipt.json').read_text())
    version = receipt['kernel_release']
    if not re.fullmatch(r'[a-zA-Z0-9._+-]+', version):
        raise ValueError('Invalid kernel release')
    images = []
    for item in receipt['artifacts']:
        path = (kernel_dir / item['path']).resolve()
        if not path.is_relative_to(kernel_dir):
            raise ValueError('Artifact path escapes kernel build')
        with path.open('rb') as f:
            if hashlib.file_digest(f, 'sha256').hexdigest() != item['sha256']:
                raise ValueError('Kernel artifact hash mismatch')
        if path.name.startswith('linux-image-') and path.suffix == '.deb' and 'dbg' not in path.name:
            images.append(path)
    if len(images) != 1:
        raise ValueError('Expected one non-debug kernel image package')
    shutil.copyfile(base, out)
    command = ['virt-customize', '-a', str(out), '--upload', str(images[0]) + ':/tmp/dot-kernel.deb',
               '--run-command', 'dpkg -i /tmp/dot-kernel.deb',
               '--run-command', 'update-initramfs -u -k ' + version,
               '--run-command', "printf '\\nGRUB_DEFAULT=\"Advanced options for Ubuntu>Ubuntu, with Linux " + version + "\"\\n' >> /etc/default/grub",
               '--run-command', 'update-grub', '--delete', '/tmp/dot-kernel.deb']
    subprocess.run(command, check=True)
    with out.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    result = {'status': 'image_prepared', 'path': str(out), 'sha256': digest,
              'kernel_release': version, 'boot_verified': False}
    out.with_suffix('.receipt.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--base', required=True)
    p.add_argument('--base-sha256', required=True)
    p.add_argument('--kernel-dir', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    print(json.dumps(install(a.base, a.base_sha256, a.kernel_dir, a.out), indent=2))
