#!/usr/bin/env python3
"""Real Linux guest proof: no provider cache, network or simulated boot markers."""
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import unittest

sys.path[:0] = ['/app', '/app/tests']
from dot.improvement import ImprovementLab


def run():
    root = Path('/data')
    vm_id = next(s.split('=', 1)[1] for s in Path('/proc/cmdline').read_text().split() if s.startswith('dotvm='))
    boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    identity = root / 'vm-owner'
    if identity.exists():
        assert identity.read_text() == vm_id, 'Disk belongs to a different VM'
    else:
        identity.write_text(vm_id)
    left, right = socket.socketpair()
    left.sendall(b'isolated-kernel')
    assert right.recv(100) == b'isolated-kernel'
    left.close(); right.close()
    receipt = {'schema':'dot.guest-improvement-proof.v1', 'vm_id':vm_id, 'boot_id':boot_id,
        'kernel_release':os.uname().release, 'uid':os.getuid(), 'unix_socket_verified':True,
        'provider_inference_verified':False, 'browser_render_verified':False,
        'execution':'actual QEMU Linux guest; CPU emulation, not hardware KVM'}
    print('DOT_BOOT_PROOF ' + json.dumps(receipt), flush=True)
    assert os.getuid() == 1000, 'Guest test must run without root privileges'
    work = root / 'workspace'; work.mkdir(exist_ok=True)
    lab = ImprovementLab(root / 'lab', work)
    saved = root / 'improvement-id'
    if not saved.exists():
        suite = unittest.defaultTestLoader.discover('/app/tests', pattern='test_improvement.py')
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        assert result.wasSuccessful(), 'Improvement integration tests failed inside actual guest'
        receipt['guest_tests'] = result.testsRun
        (work / 'procedure.py').write_text('def double(x): return 4\n')
        regression = "import runpy,pathlib,sys\nm=runpy.run_path(str(pathlib.Path(sys.argv[1])/'procedure.py'))\nassert m['double'](2)==4\n"
        holdout = regression + "assert m['double'](-3)==-6\n"
        capsule = lab.create('Persist a verified improvement across guest reboot', ['procedure.py'], regression, holdout, seconds=60)
        lab.edit(capsule['id'], 'procedure.py', 'def double(x): return x * 2\n')
        trial = lab.evaluate(capsule['id'])
        assert trial['status'] == 'verified'
        promoted = lab.promote(capsule['id'])
        saved.write_text(capsule['id'])
        (root / 'first-boot').write_text(boot_id)
        receipt.update(phase='promoted_before_reboot', capsule_id=capsule['id'], trials=trial['trials'],
            candidate_hash=promoted['candidate_hash'])
    else:
        capsule_id = saved.read_text()
        assert (root / 'first-boot').read_text() != boot_id, 'Expected a new Linux boot'
        assert lab.get(capsule_id)['status'] == 'promoted'
        assert 'x * 2' in (work / 'procedure.py').read_text()
        rolled = lab.rollback(capsule_id)
        assert 'return 4' in (work / 'procedure.py').read_text()
        receipt.update(phase='reboot_persistence_and_rollback_verified', capsule_id=capsule_id,
            rollback_status=rolled['status'], previous_boot_id=(root / 'first-boot').read_text())
    (root / (receipt['phase'] + '.json')).write_text(json.dumps(receipt, indent=2))
    print('DOT_PROBE_RESULT ' + json.dumps(receipt), flush=True)


if __name__ == '__main__':
    run()
