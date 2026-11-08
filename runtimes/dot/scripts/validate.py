#!/usr/bin/env python3
"""Source validation receipt. A passing result does not claim VM boot or subscription inference."""
import functools
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
root=Path(__file__).resolve().parents[1]
calls={'count':0}
# Count executed public assertion calls, including assertRaises/subtest negative cases.
for name in dir(unittest.TestCase):
    if name.startswith('assert') and not name.startswith('assert_'):
        original=getattr(unittest.TestCase,name)
        if not callable(original):continue
        def wrapper(*args,_fn=original,**kwargs):
            calls['count']+=1
            return _fn(*args,**kwargs)
        setattr(unittest.TestCase,name,wrapper)
started=time.time()
suite=unittest.defaultTestLoader.discover(str(root/'tests'))
result=unittest.TextTestRunner(verbosity=1).run(suite)
checks=[]
for argv in ([sys.executable,'-m','compileall','-q','dot','scripts'],['node','--check','dot/static/app.js'],['bash','-n','scripts/install_host.sh'],['bash','-n','scripts/install_guest_browser.sh']):
    completed=subprocess.run(argv,cwd=root,capture_output=True,text=True)
    checks.append({'command':argv,'passed':completed.returncode==0,'error':completed.stderr[-1000:]})
receipt={'status':'source_tests_passed' if result.wasSuccessful() and all(c['passed'] for c in checks) else 'failed',
         'tests':result.testsRun,'assertion_calls':calls['count'],'failures':len(result.failures),'errors':len(result.errors),
         'duration_seconds':time.time()-started,'checks':checks,
         'vm_boot':'not_verified','custom_linux_kernel_build':'not_executed','subscription_inference':'not_verified',
         'hypervisor_in_tests':'test fixtures only; production has no fixture backend'}
(root/'receipts/source-validation.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
raise SystemExit(0 if receipt['status']=='source_tests_passed' else 1)
