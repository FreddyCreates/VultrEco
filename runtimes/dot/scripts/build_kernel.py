#!/usr/bin/env python3
"""Build a verified upstream Linux archive into a custom guest kernel and Debian packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import time


def build(archive, expected_sha256, destination, jobs, image_only=False, headless=False):
    if jobs < 1 or jobs > 256:
        raise ValueError('Invalid build parallelism')
    archive = Path(archive).resolve()
    with archive.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if digest != expected_sha256:
        raise ValueError('Linux source archive hash mismatch')
    out = Path(destination).resolve()
    out.mkdir(parents=True, exist_ok=False)
    with tarfile.open(archive) as source:
        source.extractall(out, filter='data')
    roots = [p for p in out.iterdir() if p.is_dir() and (p / 'Makefile').is_file()]
    if len(roots) != 1:
        raise ValueError('Expected one Linux source directory')
    root = roots[0]
    env = dict(os.environ, KBUILD_BUILD_USER='itsnotai', KBUILD_BUILD_HOST='dot-kernel',
               KBUILD_BUILD_TIMESTAMP='2026-11-08 00:00:00 UTC', KBUILD_BUILD_VERSION='1')
    def run(*args):
        return subprocess.check_output(args, cwd=root, env=env, text=True)
    started = time.time()
    run('make', 'x86_64_defconfig')
    fragment = Path(__file__).resolve().parents[1] / 'kernel/dot.config'
    run('bash', 'scripts/kconfig/merge_config.sh', '-m', '.config', str(fragment))
    if headless:
        for option in ('DRM', 'SOUND', 'WIRELESS', 'WLAN', 'MEDIA_SUPPORT', 'USB_SUPPORT'):
            run('scripts/config', '--disable', option)
    run('make', 'olddefconfig')
    # A failed or incompatible fragment may silently lose symbols. Fail required gates.
    actual = (root / '.config').read_text()
    for option in ('CONFIG_VIRTIO_BLK=y', 'CONFIG_VIRTIO_NET=y', 'CONFIG_EXT4_FS=y',
                   'CONFIG_NF_TABLES=y', 'CONFIG_MEMCG=y', 'CONFIG_SECCOMP=y',
                   'CONFIG_SECURITY_LANDLOCK=y', 'CONFIG_BPF_SYSCALL=y', 'CONFIG_CGROUP_BPF=y'):
        if option not in actual.splitlines():
            raise RuntimeError('Required kernel option missing: ' + option)
    version = run('make', '-s', 'kernelrelease').strip()
    # Capture compiler errors directly; no success receipt until all targets exist.
    target = 'bzImage' if image_only else 'bindeb-pkg'
    subprocess.run(['make', '-j' + str(jobs), target], cwd=root, env=env, check=True)
    image = root / 'arch/x86/boot/bzImage'
    if not image.is_file():
        raise RuntimeError('Kernel build did not produce bzImage')
    artifacts = []
    for path in [image, root / '.config', *out.glob('*.deb')]:
        with path.open('rb') as f:
            sha = hashlib.file_digest(f, 'sha256').hexdigest()
        artifacts.append({'path': str(path.relative_to(out)), 'sha256': sha, 'size': path.stat().st_size})
    if not image_only and not any(p.name.startswith('linux-image-') for p in out.glob('*.deb')):
        raise RuntimeError('Missing kernel image Debian package')
    receipt = {'status': 'built', 'kernel_release': version, 'source_sha256': digest,
               'duration_seconds': time.time() - started, 'artifacts': artifacts,
               'boot_verified': False, 'target': target,
               'debian_package_build_verified': not image_only, 'headless': headless}
    (out / 'kernel-build-receipt.json').write_text(json.dumps(receipt, indent=2))
    return receipt


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--archive', required=True)
    p.add_argument('--sha256', required=True)
    p.add_argument('--out', required=True)
    p.add_argument('--jobs', type=int, default=4)
    p.add_argument('--image-only', action='store_true', help='Build bzImage without claiming a Debian package')
    p.add_argument('--headless', action='store_true', help='Omit unused graphics, sound, wireless, media and USB devices')
    a = p.parse_args()
    print(json.dumps(build(a.archive, a.sha256, a.out, a.jobs, a.image_only, a.headless), indent=2))
