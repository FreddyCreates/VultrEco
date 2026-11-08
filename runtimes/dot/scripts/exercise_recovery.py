#!/usr/bin/env python3
"""Execute local workspace interruption/recovery and real project tests. No model or VM substitutes."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dot.checkpoint import Checkpoints, workspace_guard, atomic_json
from dot.verification import verify


def exercise(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    work = destination / 'workspace'
    work.mkdir()
    state = destination / 'state'
    checks = {'commands': [['python3', '-m', 'unittest', '-v']],
              'files': [{'path': 'calculator.py', 'contains': 'return a + b'}]}
    (work / 'calculator.py').write_text('def add(a, b):\n    return a + b\n')
    (work / 'test_calculator.py').write_text('import unittest\nfrom calculator import add\nclass CalculatorTest(unittest.TestCase):\n    def test_add(self): self.assertEqual(add(3, 4), 7)\n    def test_negative(self): self.assertEqual(add(-5, 2), -3)\n')
    store = Checkpoints(state, work)
    receipt = {'schema': 'dot.local-recovery-exercise.v1', 'execution': 'real local Python processes',
               'vm_boot_verified': False, 'subscription_inference_verified': False, 'phases': []}
    with workspace_guard(state):
        first = verify(work, checks, time.time()+20)
        if not first['passed']: raise RuntimeError('Initial project failed')
        checkpoint = store.create('before-interruption')
        receipt['phases'].append({'phase': 'initial_verified', 'checkpoint_id': checkpoint['id'], 'acceptance': first})
        atomic_json(state / 'mission.json', {'objective': 'Recover the calculator project and pass all checks', 'checkpoint_id': checkpoint['id'], 'phase': 'running'})
        # Simulate an interrupted WRITE, not a simulated inference response or VM.
        worker = 'from pathlib import Path\nimport time\nPath("calculator.py").write_text("def add(a, b):\\n    return 999\\n")\nprint("write-observed",flush=True)\ntime.sleep(60)\n'
        child = subprocess.Popen([sys.executable, '-c', worker], cwd=work, stdout=subprocess.PIPE, text=True)
        if child.stdout.readline().strip() != 'write-observed': raise RuntimeError('Worker did not write')
        child.terminate();child.wait(timeout=5);child.stdout.close()
        receipt['phases'].append({'phase': 'worker_interrupted', 'exit_code': child.returncode})
        # Child Python imports must not reuse stale bytecode of a same-size file.
        failed = verify(work, checks, time.time()+20)
        if failed['passed']: raise RuntimeError('Broken project incorrectly accepted')
        receipt['phases'].append({'phase': 'bad_output_rejected', 'acceptance': failed})
    # Construct fresh state objects to exercise recovery after process/context loss.
    recovered = json.loads((state / 'mission.json').read_text())
    with workspace_guard(state):
        restored = Checkpoints(state, work).restore(recovered['checkpoint_id'])
        resumed = subprocess.run([sys.executable, '-c', 'from pathlib import Path\np=Path("calculator.py")\np.write_text(p.read_text()+"\\n# resumed after interruption\\n")'], cwd=work, check=True)
        final = verify(work, checks, time.time()+20)
        if not final['passed']: raise RuntimeError('Recovered project failed')
        atomic_json(state / 'mission.json', {**recovered, 'phase': 'verified'})
        receipt['phases'].append({'phase': 'restored_and_resumed', 'restore': restored, 'acceptance': final})
    receipt.update(status='local_recovery_verified', artifacts=[{'path':str(p.relative_to(work)), 'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(work.glob('*.py'))])
    atomic_json(destination / 'receipt.json', receipt)
    return receipt


if __name__ == '__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    print(json.dumps(exercise(args.out),indent=2))
