"""Generate safe Python code for a per-job sandbox containment demonstration.

This script emits code; it does NOT run the probe on the host. Submit the emitted
code as a Python mission to a separately isolated CAPSULA worker with Docker.
"""
from __future__ import annotations
import argparse

PROBE = '''import pathlib, socket, json
results = {}
try:
    pathlib.Path('/capsula-root-write-probe').write_text('probe')
    results['read_only_root'] = 'FAIL: write unexpectedly succeeded'
except OSError as exc:
    results['read_only_root'] = f'PASS: denied ({type(exc).__name__})'
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2).close()
    results['network_none'] = 'FAIL: outbound socket unexpectedly connected'
except OSError as exc:
    results['network_none'] = f'PASS: denied ({type(exc).__name__})'
print(json.dumps(results, sort_keys=True))
'''

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', help='Write generated probe to file; otherwise print stdout')
    args = parser.parse_args()
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(PROBE, encoding='utf-8')
    else:
        print(PROBE, end='')
